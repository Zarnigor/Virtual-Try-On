"""create_staff_user and promote_garments management commands."""
import os
from io import StringIO
from unittest import mock

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.garments.models import Garment
from apps.testing import MediaTestCase, png_bytes
from apps.users.models import User


class CreateStaffUserTests(MediaTestCase):
    def call(self, **env):
        with mock.patch.dict(os.environ, env):
            call_command("create_staff_user", email="Staff@Test.uz", stdout=StringIO())

    def test_password_from_env_creates_a_staff_user(self):
        self.call(STAFF_PASSWORD="a-long-pass-123")
        u = User.objects.get()
        self.assertTrue(u.is_staff)
        self.assertFalse(u.is_superuser)
        self.assertTrue(u.check_password("a-long-pass-123"))

    def test_password_from_prompt_and_promotion(self):
        user = self.make_user("staff@test.uz")
        with mock.patch.dict(os.environ, {}, clear=False), mock.patch("getpass.getpass", side_effect=["p4ss-word-xyz"] * 2):
            os.environ.pop("STAFF_PASSWORD", None)
            call_command("create_staff_user", email="staff@test.uz", stdout=StringIO())
        user.refresh_from_db()
        self.assertTrue(user.is_staff)
        self.assertTrue(user.check_password("p4ss-word-xyz"))
        self.assertEqual(User.objects.count(), 1)

    def test_mismatch_or_short_password_fails(self):
        os.environ.pop("STAFF_PASSWORD", None)
        with mock.patch("getpass.getpass", side_effect=["one-password", "two-password"]), self.assertRaises(CommandError):
            call_command("create_staff_user", email="x@test.uz", stdout=StringIO())
        with self.assertRaises(CommandError):
            self.call(STAFF_PASSWORD="short")
        self.assertFalse(User.objects.exists())


class PromoteGarmentsTests(MediaTestCase):
    def garment(self, landmarks=True):
        g = Garment(owner=self.make_user(f"o{Garment.objects.count()}@test.uz"), type="tshirt",
                    landmarks={"shoulder": {}} if landmarks else {})
        g.image.save("g.png", ContentFile(png_bytes()), save=True)
        return g

    def test_catalog_makes_garments_public_and_approved(self):
        a, b = self.garment(), self.garment()
        call_command("promote_garments", ids=[a.pk], catalog=True, stdout=StringIO())
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((a.visibility, a.status), ("public", "approved"))
        self.assertEqual((b.visibility, b.status), ("private", "pending"))

    def test_missing_or_unmarked_garments_change_nothing(self):
        a, unmarked = self.garment(), self.garment(landmarks=False)
        for ids in ([a.pk, 9999], [a.pk, unmarked.pk]):
            with self.assertRaises(CommandError):
                call_command("promote_garments", ids=ids, catalog=True, stdout=StringIO())
        a.refresh_from_db()
        self.assertEqual(a.visibility, "private")
        with self.assertRaises(CommandError):
            call_command("promote_garments", ids=[a.pk], stdout=StringIO())  # --catalog is required

    def test_list(self):
        a = self.garment()
        out = StringIO()
        call_command("promote_garments", list=True, stdout=out)
        self.assertIn(f"{a.pk:>5}  tshirt", out.getvalue())
