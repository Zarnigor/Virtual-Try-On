"""Garment gender in the try-on flow (docs/09 #97): male base -> male + unisex, female base -> female + unisex."""
from unittest import mock

from django.core.files.base import ContentFile
from django.utils import timezone

from apps.avatars.models import Avatar
from apps.bodies.models import Body
from apps.garments.models import Garment
from apps.testing import MediaTestCase, png_bytes, upload
from apps.tryon_engine.views import garment_fits_sex

LM = {"shoulder": {"y": 5, "left_x": 5, "right_x": 55}}


class GenderRuleTests(MediaTestCase):
    def test_matrix(self):
        for gender, sex, ok in (("male", "male", True), ("female", "female", True), ("unisex", "male", True),
                                ("unisex", "female", True), ("male", "female", False), ("female", "male", False)):
            self.assertEqual(garment_fits_sex(gender, sex), ok, (gender, sex))


@mock.patch("apps.tryon_engine.views.run_tryon.delay")
class TryOnGenderTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.login(self.user)
        self.male = Avatar.objects.create(sex="male", build="average")
        self.female = Avatar.objects.create(sex="female", build="average")
        self.g = {gen: self._garment(gen) for gen in ("male", "female", "unisex")}

    def _garment(self, gender, gtype="tshirt"):
        g = Garment(owner=self.user, type=gtype, landmarks=LM, gender=gender)
        g.image.save("g.png", ContentFile(png_bytes()), save=False)
        g.save()
        return g

    def _tryon(self, garment, **base):
        return self.client.post("/api/tryon/", {**base, "garment_ids": [garment.id]}, format="json")

    def test_matching_and_unisex_pass(self, _):
        for avatar, gender in ((self.male, "male"), (self.female, "female"), (self.male, "unisex"),
                               (self.female, "unisex")):
            r = self._tryon(self.g[gender], base="avatar", avatar_id=avatar.id)
            self.assertEqual(r.status_code, 202, (avatar.sex, gender))

    def test_mismatch_is_gender_mismatch(self, delay):
        for avatar, gender in ((self.male, "female"), (self.female, "male")):
            r = self._tryon(self.g[gender], base="avatar", avatar_id=avatar.id)
            self.assertEqual((r.status_code, r.data["code"]), (400, "GENDER_MISMATCH"))
            self.assertEqual((r.data["garment_gender"], r.data["base_sex"]), (gender, avatar.sex))
        delay.assert_not_called()

    def test_mismatch_in_a_pair_rejects_the_whole_tryon(self, delay):
        pants = self._garment("female", gtype="pants")
        r = self.client.post("/api/tryon/", {"base": "avatar", "avatar_id": self.male.id,
                                             "garment_ids": [self.g["male"].id, pants.id]}, format="json")
        self.assertEqual((r.status_code, r.data["code"], r.data["garment_id"]), (400, "GENDER_MISMATCH", pants.id))
        delay.assert_not_called()

    def _body(self, sex):
        b = Body(user=self.user, landmarks={"shoulder": {"y": 1}}, sex=sex, confirmed_at=timezone.now())
        b.image.save("b.png", ContentFile(png_bytes()), save=False)
        b.save()
        return b

    def test_own_body_uses_the_chosen_sex(self, _):
        self._body("male")
        self.assertEqual(self._tryon(self.g["male"], base="body").status_code, 202)
        self.assertEqual(self._tryon(self.g["unisex"], base="body").status_code, 202)
        r = self._tryon(self.g["female"], base="body")
        self.assertEqual((r.status_code, r.data["code"]), (400, "GENDER_MISMATCH"))

    def test_body_without_sex_must_choose_first(self, delay):
        self._body(None)
        r = self._tryon(self.g["unisex"], base="body")
        self.assertEqual((r.status_code, r.data["code"]), (400, "BODY_SEX_REQUIRED"))
        delay.assert_not_called()


@mock.patch("apps.bodies.views.run_body_validation.delay")
class BodySexTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.login(self.user)

    def _upload(self, **extra):
        return self.client.post("/api/body/", {"photo": upload(), "is_adult_confirmed": "true", **extra},
                                format="multipart")

    def test_sex_required_and_validated_on_upload(self, _):
        self.assertEqual(self._upload().status_code, 400)
        self.assertEqual(self._upload(sex="other").status_code, 400)
        self.assertFalse(Body.objects.exists())
        r = self._upload(sex="male")
        self.assertEqual((r.status_code, r.data["body"]["sex"]), (201, "male"))

    def test_existing_body_without_sex_chooses_once(self, _):
        b = Body(user=self.user, landmarks={})
        b.image.save("b.png", ContentFile(png_bytes()), save=False)
        b.save()
        self.assertIsNone(self.client.get("/api/body/").data["sex"])  # never guessed
        r = self.client.patch("/api/body/sex/", {"sex": "x"}, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (400, "BAD_SEX"))
        r = self.client.patch("/api/body/sex/", {"sex": "female"}, format="json")
        self.assertEqual((r.status_code, r.data["sex"]), (200, "female"))
        r = self.client.patch("/api/body/sex/", {"sex": "male"}, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (409, "SEX_ALREADY_SET"))
        b.refresh_from_db()
        self.assertEqual(b.sex, "female")

    def test_other_users_body_is_not_reachable(self, _):
        other = self.make_user("o@test.uz")
        b = Body(user=other, landmarks={})
        b.image.save("b.png", ContentFile(png_bytes()), save=False)
        b.save()
        r = self.client.patch("/api/body/sex/", {"sex": "male"}, format="json")
        self.assertEqual(r.status_code, 404)
        b.refresh_from_db()
        self.assertIsNone(b.sex)


class GarmentForSexFilterTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.owner = self.make_user("shop@test.uz")
        self.login(self.user)
        self.ids = {}
        for gen in ("male", "female", "unisex"):
            g = Garment(owner=self.owner, type="tshirt", landmarks=LM, gender=gen, visibility="public",
                        status="approved")
            g.image.save("g.png", ContentFile(png_bytes()), save=False)
            g.save()
            self.ids[gen] = g.id

    def _ids(self, query):
        r = self.client.get(f"/api/garments/?scope=catalog{query}")
        self.assertEqual(r.status_code, 200)
        return {x["id"] for x in r.data}

    def test_for_sex(self):
        self.assertEqual(self._ids("&for_sex=male"), {self.ids["male"], self.ids["unisex"]})
        self.assertEqual(self._ids("&for_sex=female"), {self.ids["female"], self.ids["unisex"]})
        self.assertEqual(self._ids("&for_sex=all"), set(self.ids.values()))
        self.assertEqual(self.client.get("/api/garments/?scope=catalog&for_sex=kids").status_code, 400)

    def test_catalog_default_uses_avatar_then_body_sex(self):
        self.assertEqual(self._ids(""), set(self.ids.values()))  # no body, no avatar: unknown, no filter
        b = Body(user=self.user, landmarks={}, sex="female")
        b.image.save("b.png", ContentFile(png_bytes()), save=False)
        b.save()
        self.assertEqual(self._ids(""), {self.ids["female"], self.ids["unisex"]})
        male = Avatar.objects.create(sex="male", build="slim")
        self.assertEqual(self._ids(f"&avatar_id={male.id}"), {self.ids["male"], self.ids["unisex"]})
        self.assertEqual(self._ids("&for_sex=all"), set(self.ids.values()))  # the toggle turns it off

    def test_own_scope_has_no_default_filter(self):
        b = Body(user=self.user, landmarks={}, sex="female")
        b.image.save("b.png", ContentFile(png_bytes()), save=False)
        b.save()
        r = self.client.get("/api/garments/?scope=mine")
        self.assertEqual(r.status_code, 200)
