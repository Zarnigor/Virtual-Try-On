"""Body measurements use the shared fit-check validator (docs/11, docs/09 #126)."""
from datetime import timedelta
from unittest import mock

from django.utils import timezone

from apps.avatars.tests_staff import full_landmarks
from apps.bodies.models import Body
from apps.sizing.measurements import RANGES
from apps.testing import MediaTestCase, upload


@mock.patch("apps.bodies.views.run_body_validation.delay")
class BodyMeasurementRangeTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.login(self.user)

    def _upload(self):
        self.client.post("/api/body/", {"photo": upload(), "is_adult_confirmed": "true", "sex": "male"},
                         format="multipart")

    def _confirm(self, **extra):
        return self.client.post("/api/body/confirm/", {"landmarks": full_landmarks(), **extra}, format="json")

    @staticmethod
    def _payload(key, value):
        return {"height_cm": value} if key == "height_cm" else {"measurements": {key: value}}

    def test_confirm_each_key_min_max_outside(self, _):
        for key, (lo, hi) in RANGES.items():
            for value, ok in ((lo, True), (hi, True), (lo - 0.5, False), (hi + 0.5, False)):
                with self.subTest(key=key, value=value):
                    Body.objects.filter(user=self.user).delete()
                    self._upload()
                    r = self._confirm(**self._payload(key, value))
                    body = Body.objects.get(user=self.user)
                    if ok:
                        self.assertEqual(r.status_code, 200, r.data)
                    else:
                        self.assertEqual((r.status_code, r.data["code"], r.data["field"]),
                                         (400, "MEASUREMENTS_INVALID", key))
                        self.assertIsNone(body.confirmed_at)  # nothing locked

    def test_confirm_stores_shoulder_width_and_keeps_circumference_shoulder(self, _):
        self._upload()
        m = {"shoulder": 116, "chest": 98, "shoulder_width": 44, "inseam": 80}
        r = self._confirm(measurements=m, height_cm=175)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Body.objects.get(user=self.user).measurements, m)

    def test_patch_each_key_min_max_outside(self, _):
        self._upload()
        self.assertEqual(self._confirm().status_code, 200)
        for key, (lo, hi) in RANGES.items():
            for value, ok in ((lo, True), (hi, True), (lo - 0.5, False), (hi + 0.5, False)):
                with self.subTest(key=key, value=value):
                    Body.objects.filter(user=self.user).update(measurements_changed_at=None)
                    r = self.client.patch("/api/body/measurements/", self._payload(key, value), format="json")
                    if ok:
                        self.assertEqual(r.status_code, 200, r.data)
                    else:
                        self.assertEqual((r.status_code, r.data["code"]), (400, "MEASUREMENTS_INVALID"))

    def test_invalid_patch_does_not_start_the_lock_and_lock_still_applies(self, _):
        self._upload()
        self._confirm()
        r = self.client.patch("/api/body/measurements/", {"measurements": {"shoulder_width": 80}}, format="json")
        self.assertEqual(r.status_code, 400)
        body = Body.objects.get(user=self.user)
        self.assertIsNone(body.measurements_changed_at)
        r = self.client.patch("/api/body/measurements/", {"measurements": {"shoulder_width": 44}}, format="json")
        self.assertEqual(r.status_code, 200)
        r = self.client.patch("/api/body/measurements/", {"measurements": {"shoulder_width": 45}}, format="json")
        self.assertEqual((r.status_code, r.data["code"]), (403, "MEASUREMENTS_LOCKED"))
        Body.objects.filter(user=self.user).update(measurements_changed_at=timezone.now() - timedelta(days=366))
        r = self.client.patch("/api/body/measurements/", {"measurements": {"shoulder_width": 45}}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Body.objects.get(user=self.user).measurements, {"shoulder_width": 45})


@mock.patch("apps.bodies.views.run_body_validation.delay")
class BodyMeasurementMergeTests(MediaTestCase):
    """PATCH body/measurements/ merges (docs/09 #127)."""

    START = {"shoulder": 116, "chest": 98, "waist": 86, "hip": 98, "shoulder_width": 44}

    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.login(self.user)
        self.client.post("/api/body/", {"photo": upload(), "is_adult_confirmed": "true", "sex": "male"},
                         format="multipart")
        r = self.client.post("/api/body/confirm/", {"landmarks": full_landmarks(), "height_cm": 175,
                                                     "measurements": self.START}, format="json")
        assert r.status_code == 200, r.data

    def patch(self, payload):
        return self.client.patch("/api/body/measurements/", payload, format="json")

    def body(self):
        return Body.objects.get(user=self.user)

    def test_partial_patch_keeps_other_keys_and_shoulder_width_survives(self, _):
        r = self.patch({"measurements": {"chest": 100}})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.body().measurements, {**self.START, "chest": 100})
        self.assertEqual(self.body().measurements["shoulder_width"], 44)
        self.assertEqual(self.body().height_cm, 175)  # height not sent: unchanged
        self.assertIsNotNone(self.body().measurements_changed_at)

    def test_height_only_keeps_measurements(self, _):
        self.assertEqual(self.patch({"height_cm": 180}).status_code, 200)
        self.assertEqual((self.body().height_cm, self.body().measurements), (180, self.START))

    def test_identical_patch_does_not_lock(self, _):
        for payload in ({"measurements": {"chest": 98}}, {"height_cm": 175}, {},
                        {"height_cm": 175, "measurements": dict(self.START)}):
            with self.subTest(payload=payload):
                r = self.patch(payload)
                self.assertEqual(r.status_code, 200, r.data)
                self.assertIsNone(self.body().measurements_changed_at)
                self.assertTrue(r.data["can_change_measurements"])

    def test_locked_body_is_still_403(self, _):
        self.assertEqual(self.patch({"measurements": {"chest": 100}}).status_code, 200)
        for payload in ({"measurements": {"chest": 101}}, {"measurements": {"chest": 100}}):
            r = self.patch(payload)
            self.assertEqual((r.status_code, r.data["code"]), (403, "MEASUREMENTS_LOCKED"))

    def test_null_is_rejected(self, _):
        for payload, field in (({"measurements": {"chest": None}}, "chest"), ({"height_cm": None}, "height_cm"),
                               ({"measurements": None}, "measurements")):
            with self.subTest(payload=payload):
                r = self.patch(payload)
                self.assertEqual((r.status_code, r.data["code"], r.data["field"]),
                                 (400, "MEASUREMENTS_INVALID", field))
        body = self.body()
        self.assertEqual((body.measurements, body.height_cm), (self.START, 175))
        self.assertIsNone(body.measurements_changed_at)
