"""Fit gate in try-on (docs/11, docs/09 #126, #128, #129): POST tryon/ and GET tryon/fit-check/.
The gate uses the rendered body's sizes (Body or Avatar); only too_small rejects, too_large is a warning."""
from unittest import mock

from django.core.files.base import ContentFile
from django.test import override_settings
from django.utils import timezone

from apps.avatars.models import Avatar
from apps.bodies.models import Body
from apps.garments.models import Garment
from apps.jobs.models import Job
from apps.outfits.models import Outfit
from apps.testing import MediaTestCase, png_bytes

LM = {"shoulder": {"y": 5, "left_x": 5, "right_x": 55}}
# Avatar sizes: inseam estimated from height (178 x 0.45 = 80.1)
AVATAR_M = {"shoulder": 116, "chest": 100, "waist": 80, "hip": 100, "shoulder_width": 44}
TSHIRT = {"chest_width": 55, "length": 70, "shoulder_width": 46}  # fits: chest +10, shoulder +2
PANTS = {"waist_width": 41, "hip_width": 55, "inseam": 81}  # fits: waist +2, hip +10, inseam +0.9


class FitBase(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.other = self.make_user("b@test.uz")
        self.login(self.user)
        self.avatar = Avatar.objects.create(sex="male", build="average", height_cm=178, measurements=dict(AVATAR_M))

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

    def post(self, garments, base="avatar", **extra):
        data = {"base": base, "garment_ids": [g.id for g in garments], **extra}
        if base == "avatar":
            data["avatar_id"] = self.avatar.id
        return self.client.post("/api/tryon/", data, format="json")

    def assert_nothing_created(self):
        self.assertEqual(Job.objects.filter(kind="tryon").count(), 0)
        self.assertEqual(Outfit.objects.count(), 0)


@override_settings(FIT_CHECK_ENABLED=True)
@mock.patch("apps.tryon_engine.views.run_tryon.delay")
class PostTryonFitTests(FitBase):
    def test_fitting_garments_start_the_job_without_warnings(self, delay):
        r = self.post([self.garment(), self.garment("pants")])
        self.assertEqual(r.status_code, 202, r.data)
        delay.assert_called_once()
        self.assertEqual(Job.objects.get(pk=r.data["job_id"]).result, {"fit_warnings": []})

    def test_too_large_only_is_rendered_with_fit_warnings(self, delay):
        g = self.garment(sizes={**TSHIRT, "chest_width": 62})  # 124 vs limit 120: 4 cm big
        r = self.post([g])
        self.assertEqual(r.status_code, 202, r.data)
        delay.assert_called_once()
        warnings = Job.objects.get(pk=r.data["job_id"]).result["fit_warnings"]
        self.assertEqual(warnings, [{"garment_id": g.id, "detail": "Bu kiyim sizga katta: koʻkrak 4 sm keng.",
                                     "checks": [{"zone": "chest", "garment_cm": 124, "body_cm": 100, "ease_cm": 24,
                                                 "verdict": "too_large", "limit_cm": 120}]}])

    def test_fit_warnings_survive_the_task(self, delay):
        from apps.tryon_engine import tasks
        r = self.post([self.garment(sizes={**TSHIRT, "chest_width": 62})])
        job = Job.objects.get(pk=r.data["job_id"])
        with mock.patch.object(tasks, "_do_warp", return_value={"engine": "mls"}):
            tasks.run_tryon(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, "done")
        self.assertEqual((job.result["engine"], len(job.result["fit_warnings"])), ("mls", 1))
        self.assertEqual(job.result["outfit_id"], r.data["outfit_id"])

    def test_too_small_plus_too_large_is_400_listing_both(self, delay):
        g = self.garment(sizes={**TSHIRT, "chest_width": 47, "shoulder_width": 52})  # chest -6, shoulder +8
        r = self.post([g])
        self.assertEqual((r.status_code, r.data["code"], r.data["garment_id"]), (400, "SIZE_MISMATCH", g.id))
        self.assertEqual([(c["zone"], c["verdict"]) for c in r.data["checks"]],
                         [("chest", "too_small"), ("shoulder", "too_large")])
        self.assertEqual(r.data["detail"].split("\n"), ["Bu kiyim sizga mos emas: koʻkrak 6 sm tor.",
                                                        "Bu kiyim sizga katta: yelka 2 sm keng."])
        self.assert_nothing_created()
        delay.assert_not_called()

    def test_keep_shape_huge_garment_no_warning(self, delay):
        g = self.garment(sizes={"chest_width": 90, "length": 100, "shoulder_width": 70}, fit_mode="keep_shape")
        r = self.post([g])
        self.assertEqual(r.status_code, 202, r.data)
        self.assertEqual(Job.objects.get(pk=r.data["job_id"]).result, {"fit_warnings": []})

    def test_garment_size_missing(self, delay):
        g = self.garment(sizes=None)
        r = self.post([g])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data, {"code": "GARMENT_SIZE_MISSING", "garment_id": g.id,
                                  "keys": ["chest_width", "shoulder_width"],
                                  "detail": "Bu kiyimning oʻlchamlari kiritilmagan."})
        self.assert_nothing_created()

    def test_avatar_missing_shoulder_width_is_body_size_missing(self, delay):
        self.avatar.measurements = {k: v for k, v in AVATAR_M.items() if k != "shoulder_width"}
        self.avatar.save()
        r = self.post([self.garment()], measurements={"shoulder_width": 44})  # request sizes do not help
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data, {"code": "BODY_SIZE_MISSING", "keys": ["shoulder_width"],
                                  "detail": "Kiyimni tekshirish uchun oʻlchamlaringizni kiriting."})
        self.assert_nothing_created()

    def test_avatar_base_uses_the_avatar_sizes_request_ignored(self, delay):
        g = self.garment(sizes={**TSHIRT, "chest_width": 47})  # too small for the avatar's chest 100
        r = self.post([g], measurements={"chest": 90, "shoulder_width": 44, "height_cm": 175})
        self.assertEqual((r.status_code, r.data["code"]), (400, "SIZE_MISMATCH"))
        ok = self.garment()
        r = self.post([ok], measurements={"chest": 1000, "waist": "x"})  # ignored, not even validated
        self.assertEqual(r.status_code, 202, r.data)

    def test_first_failing_garment_in_garment_ids_order(self, delay):
        small_tshirt = self.garment(sizes={**TSHIRT, "chest_width": 40})
        no_size_pants = self.garment("pants", sizes=None)
        r = self.post([no_size_pants, small_tshirt])
        self.assertEqual((r.data["code"], r.data["garment_id"]), ("GARMENT_SIZE_MISSING", no_size_pants.id))
        r = self.post([small_tshirt, no_size_pants])
        self.assertEqual((r.data["code"], r.data["garment_id"]), ("SIZE_MISMATCH", small_tshirt.id))
        big_tshirt = self.garment(sizes={**TSHIRT, "chest_width": 62})  # a warning does not stop the check
        r = self.post([big_tshirt, no_size_pants])
        self.assertEqual((r.data["code"], r.data["garment_id"]), ("GARMENT_SIZE_MISSING", no_size_pants.id))
        self.assert_nothing_created()

    def test_gender_mismatch_comes_before_the_fit_gate(self, delay):
        r = self.post([self.garment(sizes=None, gender="female")])
        self.assertEqual(r.data["code"], "GENDER_MISMATCH")

    @override_settings(DEMO_MODE=True)
    def test_fit_gate_runs_before_the_demo_short_circuit(self, delay):
        with mock.patch("apps.tryon_engine.demo.lookup", return_value=None) as lookup:
            r = self.post([self.garment(sizes={**TSHIRT, "chest_width": 40})])
            self.assertEqual(r.data["code"], "SIZE_MISMATCH")
            lookup.assert_not_called()
            self.assertEqual(self.post([self.garment()]).status_code, 202)
            lookup.assert_called_once()

    def test_body_base_uses_body_sizes(self, delay):
        self.body(measurements={"shoulder": 116, "chest": 100, "shoulder_width": 44})
        g = self.garment()
        self.assertEqual(self.post([g], base="body", measurements={"chest": 1000}).status_code, 202)
        Body.objects.filter(user=self.user).update(measurements={"chest": 100, "shoulder": 116})
        r = self.post([g], base="body")
        self.assertEqual((r.data["code"], r.data["keys"]), ("BODY_SIZE_MISSING", ["shoulder_width"]))

    def test_body_base_pants_use_height_for_inseam(self, delay):
        self.body(measurements={"waist": 80, "hip": 100}, height_cm=180)  # 81 vs 81: ok
        self.assertEqual(self.post([self.garment("pants")], base="body").status_code, 202)


@override_settings(FIT_CHECK_ENABLED=False)
@mock.patch("apps.tryon_engine.views.run_tryon.delay")
class FlagOffTests(FitBase):
    def test_flag_off_is_the_old_behaviour(self, delay):
        for g in (self.garment(sizes=None), self.garment(sizes={**TSHIRT, "chest_width": 30})):
            with self.subTest(garment=g.id):
                r = self.post([g], measurements={"chest": 10})  # accepted and ignored
                self.assertEqual(r.status_code, 202)
                self.assertIsNone(Job.objects.get(pk=r.data["job_id"]).result)  # no fit_warnings


class FitCheckEndpointTests(FitBase):
    URL = "/api/tryon/fit-check/"

    def get(self, garments, base="avatar", **extra):
        params = {"base": base, "garment_ids": ",".join(str(g.id) for g in garments), **extra}
        if base == "avatar":
            params.setdefault("avatar_id", self.avatar.id)
        return self.client.get(self.URL, params)

    @override_settings(FIT_CHECK_ENABLED=False)
    def test_results_regardless_of_flag(self):
        ok = self.garment()
        small = self.garment("pants", sizes={**PANTS, "waist_width": 30})
        big = self.garment(sizes={**TSHIRT, "chest_width": 62})
        missing = self.garment(sizes=None)
        r = self.get([ok, small, big, missing])
        self.assertEqual(r.status_code, 200, r.data)
        res = r.data["results"]
        self.assertEqual([x["garment_id"] for x in res], [ok.id, small.id, big.id, missing.id])
        self.assertEqual((res[0]["fits"], res[0]["warnings"], res[0]["warning_detail"]), (True, [], ""))
        self.assertNotIn("code", res[0])
        self.assertEqual((res[1]["fits"], res[1]["checks"][0]["verdict"]), (False, "too_small"))
        self.assertTrue(res[2]["fits"])  # too_large only: fits, with a warning
        self.assertEqual([c["zone"] for c in res[2]["warnings"]], ["chest"])
        self.assertEqual(res[2]["warning_detail"], "Bu kiyim sizga katta: koʻkrak 4 sm keng.")
        self.assertEqual(res[3], {"garment_id": missing.id, "fits": False, "checks": [], "warnings": [],
                                  "warning_detail": "", "code": "GARMENT_SIZE_MISSING",
                                  "keys": ["chest_width", "shoulder_width"]})

    def test_avatar_sizes_used_query_sizes_ignored(self):
        g = self.garment(sizes={**TSHIRT, "chest_width": 47})
        r = self.get([g], chest="80", shoulder_width="abc")  # neither used nor validated
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["results"][0]["fits"])

    def test_avatar_missing_key_result(self):
        self.avatar.measurements = {"chest": 100}
        self.avatar.save()
        res = self.get([self.garment("pants")]).data["results"][0]
        self.assertEqual((res["code"], res["keys"]), ("BODY_SIZE_MISSING", ["waist", "hip"]))

    def test_same_answer_as_post(self):
        g = self.garment(sizes={**TSHIRT, "chest_width": 47})
        res = self.get([g]).data["results"][0]
        with override_settings(FIT_CHECK_ENABLED=True), mock.patch("apps.tryon_engine.views.run_tryon.delay"):
            post = self.post([g]).data
        self.assertEqual(res["checks"], post["checks"])

    def test_body_base(self):
        self.body(measurements={"chest": 100, "shoulder_width": 44})
        r = self.get([self.garment()], base="body", chest="10")
        self.assertTrue(r.data["results"][0]["fits"])

    def test_bad_params_are_400(self):
        g = self.garment()
        for params, code in (
            ({"base": "x", "garment_ids": str(g.id)}, "BAD_BASE"),
            ({"base": "avatar", "avatar_id": self.avatar.id}, "BAD_GARMENT_IDS"),
            ({"base": "avatar", "avatar_id": self.avatar.id, "garment_ids": "1,a"}, "BAD_GARMENT_IDS"),
            ({"base": "avatar", "garment_ids": str(g.id)}, "BAD_AVATAR_ID"),
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
        self.assertEqual((r.status_code, r.data["code"]), (400, "BODY_NOT_CONFIRMED"))  # docs/09 #130
        self.assertEqual(r.data["detail"], "Avval tanangizni tasdiqlang.")


class ConfigFlagTests(MediaTestCase):
    def test_config_exposes_the_fit_check_flag(self):
        for flag in (True, False):
            with override_settings(FIT_CHECK_ENABLED=flag):
                r = self.client.get("/api/config/")
            self.assertEqual((r.status_code, r.data["fit_check_enabled"]), (200, flag))


@override_settings(FIT_CHECK_ENABLED=True)
@mock.patch("apps.tryon_engine.views.run_tryon.delay")
@mock.patch("apps.bodies.views.run_body_validation.delay")
class OwnBodyFitGateTests(FitBase):
    """docs/09 #130: upload -> confirm with sizes (shoulder_width computed) -> POST tryon/ base=body through the gate."""

    def setUp(self):
        super().setUp()
        from apps.avatars.tests_staff import full_landmarks
        from apps.testing import upload
        with mock.patch("apps.bodies.views.run_body_validation.delay"):
            self.client.post("/api/body/", {"photo": upload(), "is_adult_confirmed": "true", "sex": "male"},
                             format="multipart")
        r = self.client.post("/api/body/confirm/", {"landmarks": full_landmarks(), "height_cm": 178,
                                                     "measurements": {"chest": 100, "waist": 80, "hip": 100}},
                             format="json")
        assert r.status_code == 200, r.data
        self.sw = r.data["measurements"]["shoulder_width"]  # computed: estimated
        assert r.data["shoulder_width_estimated"] is True

    def tshirt(self, **sizes):
        return self.garment(sizes={"chest_width": 55, "length": 70, "shoulder_width": round(self.sw) + 1, **sizes})

    def test_fitting_garments_render(self, _upload, delay):
        r = self.post([self.tshirt(), self.garment("pants")], base="body")
        self.assertEqual(r.status_code, 202, r.data)
        self.assertEqual(Job.objects.get(pk=r.data["job_id"]).result, {"fit_warnings": []})
        self.assertEqual(Outfit.objects.get(pk=r.data["outfit_id"]).body.user, self.user)
        delay.assert_called_once()

    def test_too_small_is_size_mismatch_and_nothing_is_created(self, _upload, delay):
        g = self.tshirt(chest_width=45)  # 90 vs body 100
        r = self.post([g], base="body")
        self.assertEqual((r.status_code, r.data["code"], r.data["garment_id"]), (400, "SIZE_MISMATCH", g.id))
        self.assertEqual(r.data["detail"], "Bu kiyim sizga mos emas: koʻkrak 10 sm tor.")
        self.assert_nothing_created()
        delay.assert_not_called()

    def test_too_large_only_is_rendered_with_fit_warnings(self, _upload, delay):
        g = self.tshirt(chest_width=62)  # 124 vs limit 120: 4 cm big
        r = self.post([g], base="body")
        self.assertEqual(r.status_code, 202, r.data)
        warnings = Job.objects.get(pk=r.data["job_id"]).result["fit_warnings"]
        self.assertEqual([(w["garment_id"], w["detail"]) for w in warnings],
                         [(g.id, "Bu kiyim sizga katta: koʻkrak 4 sm keng.")])

    def test_fit_check_endpoint_gives_the_same_answers(self, _upload, delay):
        ok, small, big = self.tshirt(), self.tshirt(chest_width=45), self.tshirt(chest_width=62)
        r = self.client.get("/api/tryon/fit-check/", {"base": "body", "garment_ids": f"{ok.id},{small.id},{big.id}"})
        self.assertEqual(r.status_code, 200, r.data)
        got = [(x["garment_id"], x["fits"], bool(x["warnings"])) for x in r.data["results"]]
        self.assertEqual(got, [(ok.id, True, False), (small.id, False, False), (big.id, True, True)])
