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
        self.login(self.owner)
        for method in ("put", "patch"):
            r = getattr(self.client, method)(f"/api/garments/{g.id}/", {"name": "x"}, format="json")
            self.assertEqual(r.status_code, 405, method)

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
