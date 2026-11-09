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
