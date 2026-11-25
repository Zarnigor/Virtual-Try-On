"""Fit gate in try-on (docs/11 step 3, docs/09 #126): POST tryon/ and GET tryon/fit-check/."""
from unittest import mock

from django.core.files.base import ContentFile
from django.test import override_settings
from django.utils import timezone

from apps.avatars.models import Avatar
from apps.bodies.models import Body
from apps.garments.models import Garment
from apps.jobs.models import Job
from apps.outfits.models import Outfit
from apps.sizing.measurements import RANGES
from apps.testing import MediaTestCase, png_bytes

LM = {"shoulder": {"y": 5, "left_x": 5, "right_x": 55}}
SIZES = {"height_cm": 175, "chest": 100, "waist": 80, "hip": 100, "shoulder_width": 44, "inseam": 80}
TSHIRT = {"chest_width": 55, "length": 70, "shoulder_width": 46}  # fits SIZES
PANTS = {"waist_width": 41, "hip_width": 55, "inseam": 81}  # fits SIZES


class FitBase(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.other = self.make_user("b@test.uz")
        self.login(self.user)
        self.avatar = Avatar.objects.create(sex="male", build="average",
                                            measurements={"shoulder": 116, "chest": 98, "waist": 86, "hip": 98})

    def garment(self, gtype="tshirt", sizes="default", owner="me", **kw):
        if sizes == "default":
            sizes = TSHIRT if gtype == "tshirt" else PANTS
        g = Garment(owner=self.user if owner == "me" else owner, type=gtype, landmarks=LM, sizes=sizes, **kw)
        g.image.save("g.png", ContentFile(png_bytes()), save=False)
        g.save()
        return g

    def body(self, measurements=None, height_cm=175):
        b = Body(user=self.user, landmarks={"shoulder": {"y": 1}}, sex="male", confirmed_at=timezone.now(),
                 height_cm=height_cm, measurements=measurements or {})
        b.image.save("b.png", ContentFile(png_bytes()), save=False)
        b.save()
        return b

    def post(self, garments, measurements=SIZES, base="avatar", **extra):
        data = {"base": base, "garment_ids": [g.id for g in garments], **extra}
        if base == "avatar":
            data["avatar_id"] = self.avatar.id
        if measurements is not None:
            data["measurements"] = measurements
        return self.client.post("/api/tryon/", data, format="json")

    def assert_nothing_created(self):
        self.assertEqual(Job.objects.filter(kind="tryon").count(), 0)
        self.assertEqual(Outfit.objects.count(), 0)


@override_settings(FIT_CHECK_ENABLED=True)
@mock.patch("apps.tryon_engine.views.run_tryon.delay")
class PostTryonFitTests(FitBase):
    def test_fitting_garments_start_the_job(self, delay):
        r = self.post([self.garment(), self.garment("pants")])
        self.assertEqual(r.status_code, 202, r.data)
        delay.assert_called_once()

    def test_garment_size_missing(self, delay):
        g = self.garment(sizes=None)
        r = self.post([g])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data, {"code": "GARMENT_SIZE_MISSING", "garment_id": g.id,
                                  "keys": ["chest_width", "shoulder_width"],
                                  "detail": "Bu kiyimning oʻlchamlari kiritilmagan."})
        self.assert_nothing_created()
        delay.assert_not_called()

    def test_body_size_missing(self, delay):
        r = self.post([self.garment()], measurements={"chest": 100})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data, {"code": "BODY_SIZE_MISSING", "keys": ["shoulder_width"],
                                  "detail": "Kiyimni tekshirish uchun oʻlchamlaringizni kiriting."})
        r = self.post([self.garment()], measurements=None)  # no measurements at all
        self.assertEqual((r.data["code"], r.data["keys"]), ("BODY_SIZE_MISSING", ["chest", "shoulder_width"]))
        self.assert_nothing_created()

    def test_size_mismatch(self, delay):
        g = self.garment(sizes={**TSHIRT, "chest_width": 47})  # 94 vs chest 100: 6 cm tight
        r = self.post([g])
        self.assertEqual((r.status_code, r.data["code"], r.data["garment_id"]), (400, "SIZE_MISMATCH", g.id))
        self.assertEqual(r.data["checks"][0], {"zone": "chest", "garment_cm": 94, "body_cm": 100, "ease_cm": -6,
                                               "verdict": "too_small", "limit_cm": 100})
        self.assertEqual(r.data["checks"][1]["verdict"], "ok")
        self.assertEqual(r.data["detail"], "Bu kiyim sizga mos emas: koʻkrak 6 sm tor.")
        self.assert_nothing_created()
        delay.assert_not_called()

    def test_first_failing_garment_in_garment_ids_order(self, delay):
        small_tshirt = self.garment(sizes={**TSHIRT, "chest_width": 40})
        no_size_pants = self.garment("pants", sizes=None)
        r = self.post([no_size_pants, small_tshirt])
        self.assertEqual((r.data["code"], r.data["garment_id"]), ("GARMENT_SIZE_MISSING", no_size_pants.id))
        r = self.post([small_tshirt, no_size_pants])
        self.assertEqual((r.data["code"], r.data["garment_id"]), ("SIZE_MISMATCH", small_tshirt.id))
        ok_tshirt = self.garment()
        r = self.post([ok_tshirt, no_size_pants])  # a fitting first garment does not hide the second
        self.assertEqual((r.data["code"], r.data["garment_id"]), ("GARMENT_SIZE_MISSING", no_size_pants.id))
        self.assert_nothing_created()

    def test_gender_mismatch_comes_before_the_fit_gate(self, delay):
        g = self.garment(sizes=None, gender="female")
        r = self.post([g])
        self.assertEqual(r.data["code"], "GENDER_MISMATCH")

    @override_settings(DEMO_MODE=True)
    def test_fit_gate_runs_before_the_demo_short_circuit(self, delay):
        with mock.patch("apps.tryon_engine.demo.lookup", return_value=None) as lookup:
            r = self.post([self.garment(sizes={**TSHIRT, "chest_width": 40})])
            self.assertEqual(r.data["code"], "SIZE_MISMATCH")
            lookup.assert_not_called()
            self.assertEqual(self.post([self.garment()]).status_code, 202)
            lookup.assert_called_once()

    def test_avatar_base_uses_the_request_sizes_not_the_avatar(self, delay):
        g = self.garment(sizes={**TSHIRT, "chest_width": 52})  # 104: fits chest 100, too large for chest 80
        self.assertEqual(self.post([g]).status_code, 202)
        r = self.post([g], measurements={**SIZES, "chest": 80})
        self.assertEqual((r.data["code"], r.data["checks"][0]["verdict"]), ("SIZE_MISMATCH", "too_large"))

    def test_body_base_uses_body_sizes_and_ignores_the_request(self, delay):
        self.body(measurements={"shoulder": 116, "chest": 100, "shoulder_width": 44})
        g = self.garment()
        r = self.post([g], base="body", measurements={"chest": 1000})  # ignored, not even validated
        self.assertEqual(r.status_code, 202, r.data)
        Body.objects.filter(user=self.user).update(measurements={"chest": 100, "shoulder": 116})
        r = self.post([g], base="body", measurements=SIZES)  # request has shoulder_width: still ignored
        self.assertEqual((r.data["code"], r.data["keys"]), ("BODY_SIZE_MISSING", ["shoulder_width"]))

    def test_body_base_pants_use_height_for_inseam(self, delay):
        self.body(measurements={"waist": 80, "hip": 100}, height_cm=180)  # 81 vs 81: ok
        self.assertEqual(self.post([self.garment("pants")], base="body").status_code, 202)

    def test_request_measurements_validated(self, delay):
        for key, (lo, hi) in RANGES.items():
            for value, ok in ((lo, True), (hi, True), (lo - 0.5, False), (hi + 0.5, False)):
                with self.subTest(key=key, value=value):
                    with override_settings(FIT_CHECK_ENABLED=False):
                        r = self.post([self.garment()], measurements={key: value})
                    if ok:
                        self.assertEqual(r.status_code, 202, r.data)
                    else:
                        self.assertEqual((r.status_code, r.data["code"], r.data["field"]),
                                         (400, "MEASUREMENTS_INVALID", key))


@override_settings(FIT_CHECK_ENABLED=False)
@mock.patch("apps.tryon_engine.views.run_tryon.delay")
class FlagOffTests(FitBase):
    def test_flag_off_is_the_old_behaviour(self, delay):
        for g in (self.garment(sizes=None), self.garment(sizes={**TSHIRT, "chest_width": 30})):
            with self.subTest(garment=g.id):
                self.assertEqual(self.post([g], measurements=None).status_code, 202)
                self.assertEqual(self.post([g]).status_code, 202)  # measurements accepted, not used

    def test_flag_off_still_validates_measurements(self, delay):
        r = self.post([self.garment()], measurements={"chest": 10})
        self.assertEqual(r.data["code"], "MEASUREMENTS_INVALID")
        self.assert_nothing_created()


class FitCheckEndpointTests(FitBase):
    URL = "/api/tryon/fit-check/"

    def get(self, garments, base="avatar", sizes=SIZES, **extra):
        params = {"base": base, "garment_ids": ",".join(str(g.id) for g in garments), **extra}
        if base == "avatar":
            params.setdefault("avatar_id", self.avatar.id)
            params.update(sizes or {})
        return self.client.get(self.URL, params)

    @override_settings(FIT_CHECK_ENABLED=False)
    def test_results_regardless_of_flag_and_non_fitting_is_200(self):
        ok, small, missing = (self.garment(), self.garment("pants", sizes={**PANTS, "waist_width": 30}),
                              self.garment(sizes=None))
        r = self.get([ok, small, missing])
        self.assertEqual(r.status_code, 200, r.data)
        res = r.data["results"]
        self.assertEqual([x["garment_id"] for x in res], [ok.id, small.id, missing.id])
        self.assertEqual((res[0]["fits"], [c["zone"] for c in res[0]["checks"]]), (True, ["chest", "shoulder"]))
        self.assertNotIn("code", res[0])
        self.assertEqual((res[1]["fits"], res[1]["checks"][0]["verdict"]), (False, "too_small"))
        self.assertEqual(res[2], {"garment_id": missing.id, "fits": False, "checks": [],
                                  "code": "GARMENT_SIZE_MISSING", "keys": ["chest_width", "shoulder_width"]})

    def test_body_size_missing_result(self):
        r = self.get([self.garment("pants")], sizes={"waist": 80})
        self.assertEqual(r.data["results"][0]["code"], "BODY_SIZE_MISSING")
        self.assertEqual(r.data["results"][0]["keys"], ["hip", "inseam"])

    def test_same_answer_as_post(self):
        g = self.garment(sizes={**TSHIRT, "chest_width": 47})
        res = self.get([g]).data["results"][0]
        with override_settings(FIT_CHECK_ENABLED=True), mock.patch("apps.tryon_engine.views.run_tryon.delay"):
            post = self.post([g]).data
        self.assertEqual(res["checks"], post["checks"])

    def test_body_base(self):
        self.body(measurements={"chest": 100, "shoulder_width": 44})
        r = self.get([self.garment()], base="body", chest="10")  # query sizes ignored for base=body
        self.assertTrue(r.data["results"][0]["fits"])

    def test_bad_params_are_400(self):
        g = self.garment()
        for params, code in (
            ({"base": "x", "garment_ids": str(g.id)}, "BAD_BASE"),
            ({"base": "avatar", "avatar_id": self.avatar.id}, "BAD_GARMENT_IDS"),
            ({"base": "avatar", "avatar_id": self.avatar.id, "garment_ids": "1,a"}, "BAD_GARMENT_IDS"),
            ({"base": "avatar", "garment_ids": str(g.id)}, "BAD_AVATAR_ID"),
            ({"base": "avatar", "avatar_id": self.avatar.id, "garment_ids": str(g.id), "chest": "10"},
             "MEASUREMENTS_INVALID"),
            ({"base": "avatar", "avatar_id": self.avatar.id, "garment_ids": str(g.id), "chest": "abc"},
             "MEASUREMENTS_INVALID"),
        ):
            with self.subTest(params=params):
                r = self.client.get(self.URL, params)
                self.assertEqual((r.status_code, r.data["code"]), (400, code))

    def test_other_users_private_garment_is_404(self):
        theirs = self.garment(owner=self.other)
        self.assertEqual(self.get([theirs]).status_code, 404)
        self.assertEqual(self.get([self.garment(), theirs]).status_code, 404)
        theirs.visibility, theirs.status = "public", "approved"
        theirs.save()
        self.assertEqual(self.get([theirs]).status_code, 200)

    def test_missing_avatar_or_body_is_404(self):
        g = self.garment()
        self.assertEqual(self.get([g], avatar_id=99999).status_code, 404)
        self.assertEqual(self.get([g], base="body").status_code, 404)


class FitCheckUnconfirmedBodyTests(FitBase):
    def test_unconfirmed_body_same_answer_as_post(self):
        b = self.body(measurements={"chest": 100, "shoulder_width": 44})
        Body.objects.filter(pk=b.pk).update(confirmed_at=None)
        g = self.garment()
        r = self.client.get("/api/tryon/fit-check/", {"base": "body", "garment_ids": str(g.id)})
        with mock.patch("apps.tryon_engine.views.run_tryon.delay"):
            post = self.post([g], base="body")
        self.assertEqual((r.status_code, r.data), (post.status_code, post.data))
        self.assertEqual(r.status_code, 400)


class ConfigFlagTests(MediaTestCase):
    def test_config_exposes_the_fit_check_flag(self):
        for flag in (True, False):
            with override_settings(FIT_CHECK_ENABLED=flag):
                r = self.client.get("/api/config/")  # public, no login
            self.assertEqual((r.status_code, r.data["fit_check_enabled"]), (200, flag))
