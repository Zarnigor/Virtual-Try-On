from datetime import timedelta
from unittest import mock

from django.core.files.base import ContentFile
from django.utils import timezone

from apps.bodies.models import Body
from apps.outfits.models import Outfit
from apps.testing import MediaTestCase, png_bytes, upload

LANDMARKS = {"head_top": {"y": 50}, "shoulder": {"y": 230, "left_x": 200, "right_x": 400}}


@mock.patch("apps.bodies.views.run_body_validation.delay")
class BodyRulesTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.login(self.user)

    def _upload(self, adult="true", sex="female"):
        data = {"photo": upload(), "is_adult_confirmed": adult}
        if sex is not None:
            data["sex"] = sex
        return self.client.post("/api/body/", data, format="multipart")

    def _confirmed_body(self, **extra):
        self._upload()
        return self.client.post("/api/body/confirm/", {"landmarks": LANDMARKS, **extra}, format="json")

    # --- upload / one body per user ---
    def test_upload_requires_adult_confirmation(self, _):
        self.assertEqual(self._upload(adult="false").status_code, 400)
        self.assertFalse(Body.objects.exists())

    def test_second_upload_fails(self, _):
        self.assertEqual(self._upload().status_code, 201)
        r = self._upload()
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data["code"], "BODY_EXISTS")
        self.assertEqual(Body.objects.filter(user=self.user).count(), 1)

    # --- immutability ---
    def test_confirm_requires_landmarks(self, _):
        self._upload()
        r = self.client.post("/api/body/confirm/", {"landmarks": {}}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(Body.objects.get(user=self.user).confirmed_at)

    def test_confirmed_body_cannot_be_changed(self, _):
        self.assertEqual(self._confirmed_body().status_code, 200)
        r = self.client.post("/api/body/confirm/", {"landmarks": {"head_top": {"y": 1}}}, format="json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(Body.objects.get(user=self.user).landmarks, LANDMARKS)

    def test_no_update_endpoints_for_photo_or_landmarks(self, _):
        self._confirmed_body()
        for method in ("put", "patch"):
            r = getattr(self.client, method)("/api/body/", {"landmarks": {}}, format="json")
            self.assertEqual(r.status_code, 405, method)
        self.assertEqual(self.client.post("/api/body/landmarks/", {}, format="json").status_code, 404)

    # --- yearly measurements ---
    def test_measurements_at_confirm_do_not_start_the_lock(self, _):
        self._confirmed_body(measurements={"chest": 96})
        body = Body.objects.get(user=self.user)
        self.assertEqual(body.measurements, {"chest": 96})
        self.assertTrue(body.can_change_measurements)

    def test_measurements_change_once_per_365_days(self, _):
        self._confirmed_body()
        r = self.client.patch("/api/body/measurements/", {"measurements": {"waist": 80}}, format="json")
        self.assertEqual(r.status_code, 200)
        r = self.client.patch("/api/body/measurements/", {"measurements": {"waist": 82}}, format="json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data["code"], "MEASUREMENTS_LOCKED")

        body = Body.objects.get(user=self.user)
        body.measurements_changed_at = timezone.now() - timedelta(days=366)
        body.save()
        r = self.client.patch("/api/body/measurements/", {"measurements": {"waist": 82}}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_measurements_reject_unknown_keys(self, _):
        self._confirmed_body()
        r = self.client.patch("/api/body/measurements/", {"measurements": {"neck": 40}}, format="json")
        self.assertEqual(r.status_code, 400)

    # --- deletion cascade ---
    def test_delete_body_deletes_its_outfits_and_files(self, _):
        self._confirmed_body()
        body = Body.objects.get(user=self.user)
        outfit = Outfit.objects.create(user=self.user, body=body)
        outfit.result_image.save("r.png", ContentFile(png_bytes()), save=True)
        files = [body.image, outfit.result_image]
        self.assertTrue(all(self.exists(f) for f in files))

        self.assertEqual(self.client.delete("/api/body/").status_code, 204)
        self.assertFalse(Body.objects.exists())
        self.assertFalse(Outfit.objects.exists())
        self.assertFalse(any(f.storage.exists(f.name) for f in files))
        # and a new body can be created afterwards
        self.assertEqual(self._upload().status_code, 201)

    # --- privacy ---
    def test_other_user_cannot_see_body(self, _):
        self._confirmed_body()
        self.login(self.make_user("b@test.uz"))
        self.assertEqual(self.client.get("/api/body/").status_code, 404)
        self.assertEqual(self.client.delete("/api/body/").status_code, 404)
        self.assertTrue(Body.objects.filter(user=self.user).exists())

    def test_requires_login(self, _):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/body/").status_code, 401)
