"""Shared helpers for the test suite."""
import shutil
import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework.test import APITestCase

from apps.users.models import User


def png_bytes(w=60, h=120, color=(90, 120, 160, 255)):
    buf = BytesIO()
    Image.new("RGBA", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def upload(name="photo.png", w=60, h=120):
    return SimpleUploadedFile(name, png_bytes(w, h), content_type="image/png")


class MediaTestCase(APITestCase):
    """API test case with a throw-away MEDIA_ROOT and helpers for users and files."""

    def setUp(self):
        super().setUp()
        self._media = tempfile.mkdtemp()
        self._override = override_settings(MEDIA_ROOT=self._media)
        self._override.enable()

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self._media, ignore_errors=True)
        super().tearDown()

    def make_user(self, email="a@test.uz"):
        return User.objects.create_user(email=email, password="secret123", is_adult_confirmed=True)

    def login(self, user):
        self.client.force_authenticate(user)

    @staticmethod
    def exists(field_file):
        return bool(field_file and field_file.name) and field_file.storage.exists(field_file.name)
