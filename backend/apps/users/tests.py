import time

from django.core.files.base import ContentFile
from django.test import override_settings

from apps.bodies.models import Body
from apps.garments.models import Garment
from apps.outfits.models import Outfit
from apps.testing import MediaTestCase, png_bytes
from apps.users.media_views import _make_sig
from apps.users.models import User


class AccountDeletionTests(MediaTestCase):
    def test_delete_account_removes_everything(self):
        user = self.make_user()
        body = Body(user=user, landmarks={})
        body.image.save("b.png", ContentFile(png_bytes()), save=True)
        garment = Garment(owner=user, type="pants", visibility="public", status="approved")
        garment.image.save("g.png", ContentFile(png_bytes()), save=True)
        outfit = Outfit.objects.create(user=user, body=body)
        outfit.result_image.save("r.png", ContentFile(png_bytes()), save=True)
        files = [body.image, garment.image, outfit.result_image]

        self.login(user)
        self.assertEqual(self.client.delete("/api/auth/me/").status_code, 204)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())
        self.assertFalse(Body.objects.exists())
        self.assertFalse(Garment.objects.exists())  # not left behind without an owner
        self.assertFalse(Outfit.objects.exists())
        self.assertFalse(any(f.storage.exists(f.name) for f in files))


class SignedMediaTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        user = self.make_user()
        body = Body(user=user, landmarks={})
        body.image.save("b.png", ContentFile(png_bytes()), save=True)
        self.path = body.image.name

    def _get(self, path, sig, exp):
        return self.client.get(f"/api/media/signed/{path}/?sig={sig}&exp={exp}")

    def test_valid_signature_serves_file(self):
        exp = int(time.time()) + 60
        r = self._get(self.path, _make_sig(self.path, exp), exp)
        self.assertEqual(r.status_code, 200)

    def test_tampered_or_expired_signature_is_404(self):
        exp = int(time.time()) + 60
        self.assertEqual(self._get(self.path, "0" * 24, exp).status_code, 404)
        old = int(time.time()) - 1
        self.assertEqual(self._get(self.path, _make_sig(self.path, old), old).status_code, 404)

    @override_settings(DEBUG=True)
    def test_no_open_media_route(self):
        self.assertEqual(self.client.get(f"/media/{self.path}").status_code, 404)


class AuthTests(MediaTestCase):
    def test_register_requires_adult_confirmation(self):
        r = self.client.post("/api/auth/register/", {"email": "x@test.uz", "password": "secret123",
                                                     "is_adult_confirmed": False}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_register_and_login(self):
        r = self.client.post("/api/auth/register/", {"email": "x@test.uz", "password": "secret123",
                                                     "is_adult_confirmed": True}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertIn("access", r.data)
        r = self.client.post("/api/auth/login/", {"email": "x@test.uz", "password": "wrong"}, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (400, "BAD_CREDENTIALS"))
        r = self.client.post("/api/auth/login/", {"email": "x@test.uz", "password": "secret123"}, format="json")
        self.assertEqual(r.status_code, 200)
