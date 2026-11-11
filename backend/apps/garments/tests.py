from unittest import mock

from django.core.files.base import ContentFile

from apps.avatars.models import Avatar
from apps.garments.models import Garment
from apps.testing import MediaTestCase, png_bytes

TSHIRT_LM = {"shoulder": {"y": 5, "left_x": 5, "right_x": 55}}


class GarmentRulesTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user()
        self.other = self.make_user("b@test.uz")

    def _garment(self, owner=None, **kw):
        g = Garment(owner=owner or self.owner, type="tshirt", landmarks=TSHIRT_LM, **kw)
        g.image.save("g.png", ContentFile(png_bytes()), save=False)
        g.original_image.save("o.png", ContentFile(png_bytes()), save=False)
        g.save()
        return g

    def test_owner_sees_new_garment_immediately(self):
        g = self._garment(visibility="public", status="pending")
        self.login(self.owner)
        self.assertEqual(self.client.get(f"/api/garments/{g.id}/").status_code, 200)
        ids = [x["id"] for x in self.client.get("/api/garments/?scope=mine").data]
        self.assertEqual(ids, [g.id])

    def test_visibility_to_other_users(self):
        private = self._garment()
        pending = self._garment(visibility="public", status="pending")
        approved = self._garment(visibility="public", status="approved")
        self.login(self.other)
        self.assertEqual(self.client.get(f"/api/garments/{private.id}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/garments/{pending.id}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/garments/{approved.id}/").status_code, 200)
        catalog = [x["id"] for x in self.client.get("/api/garments/?scope=catalog").data]
        self.assertEqual(catalog, [approved.id])

    def test_other_user_cannot_change_or_delete(self):
        g = self._garment()
        self.login(self.other)
        self.assertEqual(self.client.delete(f"/api/garments/{g.id}/").status_code, 404)
        r = self.client.patch(f"/api/garments/{g.id}/landmarks/", {"landmarks": {"x": 1}}, format="json")
        self.assertEqual(r.status_code, 404)
        r = self.client.patch(f"/api/garments/{g.id}/visibility/", {"visibility": "public"}, format="json")
        self.assertEqual(r.status_code, 404)
        self.assertTrue(Garment.objects.filter(pk=g.pk).exists())

    def test_no_image_update_endpoint(self):
        g = self._garment()
        before = (g.image.name, g.image.read())
        self.login(self.owner)
        self.assertEqual(self.client.put(f"/api/garments/{g.id}/", {"name": "x"}, format="json").status_code, 405)
        # PATCH only edits fit_mode / gender: anything else, the image above all, is rejected and nothing is saved
        for payload in ({"name": "x"}, {"landmarks": {}}, {"fit_mode": "keep_shape", "image": "x.png"}):
            r = self.client.patch(f"/api/garments/{g.id}/", payload, format="json")
            self.assertEqual((r.status_code, r.data["code"]), (400, "FIELD_NOT_EDITABLE"), payload)
        r = self.client.patch(f"/api/garments/{g.id}/", {"image": ContentFile(png_bytes(10, 10), name="n.png")},
                              format="multipart")
        self.assertEqual(r.status_code, 400)
        g.refresh_from_db()
        self.assertEqual((g.image.name, g.image.read()), before)
        self.assertEqual((g.name, g.fit_mode), ("", "adapt"))

    def test_delete_removes_files(self):
        g = self._garment()
        files = [g.image, g.original_image]
        self.login(self.owner)
        self.assertEqual(self.client.delete(f"/api/garments/{g.id}/").status_code, 204)
        self.assertFalse(any(f.storage.exists(f.name) for f in files))

    @mock.patch("apps.tryon_engine.views.run_tryon.delay")
    def test_tryon_rejects_other_users_unapproved_garment(self, _):
        avatar = Avatar.objects.create(sex="male", build="average")
        pending = self._garment(visibility="public", status="pending")
        approved = self._garment(visibility="public", status="approved")
        self.login(self.other)
        body = {"base": "avatar", "avatar_id": avatar.id}
        r = self.client.post("/api/tryon/", {**body, "garment_ids": [pending.id]}, format="json")
        self.assertEqual(r.status_code, 404)
        r = self.client.post("/api/tryon/", {**body, "garment_ids": [approved.id]}, format="json")
        self.assertEqual(r.status_code, 202)


def _image_bytes(fmt, w=400, h=500):
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (w, h), (20, 90, 160)).save(buf, format=fmt)
    return buf.getvalue()


@mock.patch("apps.garments.views.run_garment_cleaning.delay")
class GarmentUploadValidationTests(MediaTestCase):
    """Server-side upload checks (apps/images.py): decided from the bytes, clear {code, detail} errors."""

    def setUp(self):
        super().setUp()
        self.login(self.make_user())

    def _post(self, data, name="g.jpg", content_type="image/jpeg"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        photo = SimpleUploadedFile(name, data, content_type=content_type)
        return self.client.post("/api/garments/", {"photo": photo, "type": "tshirt"}, format="multipart")

    def _assert_rejected(self, r, code):
        self.assertEqual(r.status_code, 400, r.data)
        self.assertEqual(r.data["code"], code)
        self.assertTrue(r.data["detail"])
        self.assertFalse(Garment.objects.exists())

    def test_valid_jpeg_and_png_are_accepted_and_stored_untouched(self, delay):
        for fmt, ctype in (("JPEG", "image/jpeg"), ("PNG", "image/png")):
            raw = _image_bytes(fmt)
            r = self._post(raw, content_type=ctype)
            self.assertEqual(r.status_code, 201, r.data)
            g = Garment.objects.get(pk=r.data["garment"]["id"])
            with g.original_image.open("rb") as f:
                self.assertEqual(f.read(), raw)  # original bytes untouched, never re-encoded
        self.assertEqual(delay.call_count, 2)

    def test_truncated_file_is_corrupt(self, delay):
        raw = _image_bytes("JPEG", 800, 1000)
        self._assert_rejected(self._post(raw[: len(raw) * 6 // 10]), "CORRUPT_FILE")
        delay.assert_not_called()

    def test_not_an_image(self, delay):
        self._assert_rejected(self._post(b"hello, not an image"), "BAD_FILE_TYPE")

    def test_other_formats_even_with_a_jpeg_name_and_header(self, delay):
        for fmt in ("GIF", "WEBP", "BMP"):
            self._assert_rejected(self._post(_image_bytes(fmt)), "BAD_FILE_TYPE")

    def test_too_small(self, delay):
        self._assert_rejected(self._post(_image_bytes("PNG", 299, 900), content_type="image/png"), "IMAGE_TOO_SMALL")

    def test_too_many_pixels(self, delay):
        with self.settings(MAX_IMAGE_PIXELS=400 * 500 - 1):
            self._assert_rejected(self._post(_image_bytes("JPEG")), "IMAGE_TOO_LARGE")

    def test_file_too_large(self, delay):
        with self.settings(MAX_UPLOAD_MB=0):
            self._assert_rejected(self._post(_image_bytes("JPEG")), "FILE_TOO_LARGE")


@mock.patch("apps.garments.views.run_garment_cleaning.delay")
class GarmentCleaningStateTests(MediaTestCase):
    """Until the cleaning job has run, the garment has no image (the contract: image_url = cleaned PNG)."""

    def setUp(self):
        super().setUp()
        self.login(self.make_user())

    def _upload(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        photo = SimpleUploadedFile("g.jpg", _image_bytes("JPEG"), content_type="image/jpeg")
        return self.client.post("/api/garments/", {"photo": photo, "type": "tshirt"}, format="multipart")

    def test_upload_does_not_expose_the_uncleaned_photo_as_image(self, delay):
        r = self._upload()
        self.assertEqual(r.status_code, 201)
        g = r.data["garment"]
        self.assertEqual((g["image_url"], g["thumb_url"], g["width"], g["height"]), (None, None, None, None))
        self.assertIsNotNone(g["original_preview_url"])
        self.assertIsNone(self.client.get(f"/api/garments/{g['id']}/").data["image_url"])
        delay.assert_called_once()

    def test_landmarks_wait_for_the_cleaned_image(self, delay):
        gid = self._upload().data["garment"]["id"]
        r = self.client.patch(f"/api/garments/{gid}/landmarks/", {"landmarks": TSHIRT_LM}, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (409, "GARMENT_NOT_READY"))
        self.assertEqual(Garment.objects.get(pk=gid).landmarks, {})


class GarmentFitAndGenderTests(MediaTestCase):
    """Per-garment fit_mode (adapt | keep_shape) and gender (female | male | unisex), docs/09 #93."""

    def setUp(self):
        super().setUp()
        self.owner = self.make_user()
        self.other = self.make_user("b@test.uz")
        self.login(self.owner)

    def _garment(self, owner=None, **kw):
        return GarmentRulesTests._garment(self, owner, **kw)

    def test_defaults_on_existing_and_new_garments(self):
        g = self._garment()
        g.refresh_from_db()
        self.assertEqual((g.fit_mode, g.gender), ("adapt", "unisex"))
        data = self.client.get(f"/api/garments/{g.id}/").data
        self.assertEqual((data["fit_mode"], data["gender"]), ("adapt", "unisex"))
        # existing rows: the migration adds both columns with these defaults
        import importlib
        m = importlib.import_module("apps.garments.migrations.0005_garment_fit_mode_gender")
        defaults = {op.name: op.field.default for op in m.Migration.operations}
        self.assertEqual(defaults, {"fit_mode": "adapt", "gender": "unisex"})

    def test_patch_both_fields(self):
        g = self._garment()
        r = self.client.patch(f"/api/garments/{g.id}/", {"fit_mode": "keep_shape"}, format="json")
        self.assertEqual((r.status_code, r.data["fit_mode"], r.data["gender"]), (200, "keep_shape", "unisex"))
        r = self.client.patch(f"/api/garments/{g.id}/", {"fit_mode": "adapt", "gender": "female"}, format="json")
        self.assertEqual((r.status_code, r.data["fit_mode"], r.data["gender"]), (200, "adapt", "female"))
        g.refresh_from_db()
        self.assertEqual((g.fit_mode, g.gender), ("adapt", "female"))

    def test_invalid_values_rejected(self):
        g = self._garment()
        for payload, code in (({"fit_mode": "tight"}, "BAD_FIT_MODE"), ({"gender": "kids"}, "BAD_GENDER"),
                              ({"gender": None}, "BAD_GENDER"), ({"fit_mode": "keep_shape", "gender": "x"}, "BAD_GENDER"),
                              ({}, "FIELD_NOT_EDITABLE")):
            r = self.client.patch(f"/api/garments/{g.id}/", payload, format="json")
            self.assertEqual((r.status_code, r.data["code"]), (400, code), payload)
        g.refresh_from_db()
        self.assertEqual((g.fit_mode, g.gender), ("adapt", "unisex"))  # nothing saved, not even the valid half

    def test_only_the_owner_can_patch(self):
        g = self._garment()
        self.login(self.other)
        r = self.client.patch(f"/api/garments/{g.id}/", {"gender": "male"}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_gender_filter_includes_unisex(self):
        f = self._garment(gender="female")
        m = self._garment(gender="male")
        u = self._garment()
        ids = lambda q: sorted(x["id"] for x in self.client.get(f"/api/garments/?scope=mine{q}").data)  # noqa: E731
        self.assertEqual(ids("&gender=female"), sorted([f.id, u.id]))
        self.assertEqual(ids("&gender=male"), sorted([m.id, u.id]))
        self.assertEqual(ids("&gender=unisex"), [u.id])
        self.assertEqual(ids(""), sorted([f.id, m.id, u.id]))
        self.assertEqual(ids("&gender=other"), sorted([f.id, m.id, u.id]))  # unknown filter value: ignored

    def test_fit_mode_is_passed_to_the_engine_and_ignored(self):
        import numpy as np
        from apps.tryon_engine import warp
        from apps.tryon_engine.tests import avatar, tshirt
        base, lm = avatar()
        g, glm = tshirt()
        a = warp.render_tryon(base, lm, [("tshirt", g, glm)])[0]
        for mode in ("adapt", "keep_shape"):
            b = warp.render_tryon(base, lm, [("tshirt", g, glm)], fit_modes={"tshirt": mode})[0]
            np.testing.assert_array_equal(a, b)
        # the try-on task hands each garment's fit_mode to the engine
        from unittest import mock
        from apps.tryon_engine import tasks
        with mock.patch("apps.tryon_engine.warp.render_tryon", return_value=(a, [], {})) as rt:
            outfit = mock.Mock(body=None)
            outfit.avatar.image.path = self._garment().image.path
            outfit.avatar.landmarks = lm
            outfit.garments.all.return_value = [self._garment(fit_mode="keep_shape")]
            tasks._do_warp(outfit)
        self.assertEqual(rt.call_args.kwargs["fit_modes"], {"tshirt": "keep_shape"})
