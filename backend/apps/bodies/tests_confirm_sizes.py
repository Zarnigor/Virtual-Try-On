"""POST body/confirm/ requires the sizes; shoulder_width is computed from the landmarks when missing (docs/09 #130)."""
from unittest import mock

from apps.avatars.tests_staff import full_landmarks
from apps.bodies.landmark_checks import complete_body_landmarks
from apps.bodies.models import Body
from apps.sizing.body_sizes import shoulder_width_cm
from apps.testing import MediaTestCase, upload

HEIGHT = 175
REQUIRED = {"chest": 98, "waist": 86, "hip": 98}


def estimate(height=HEIGHT):
    return shoulder_width_cm(complete_body_landmarks(full_landmarks()), height)


@mock.patch("apps.bodies.views.run_body_validation.delay")
class ConfirmSizesTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.login(self.user)
        self.client.post("/api/body/", {"photo": upload(), "is_adult_confirmed": "true", "sex": "male"},
                         format="multipart")

    def confirm(self, height_cm=HEIGHT, measurements=None, drop=()):
        payload = {"landmarks": full_landmarks(), "height_cm": height_cm,
                   "measurements": {**REQUIRED, **(measurements or {})}}
        for key in drop:
            payload.pop(key, None) if key == "height_cm" else payload["measurements"].pop(key)
        return self.client.post("/api/body/confirm/", payload, format="json")

    def body(self):
        return Body.objects.get(user=self.user)

    def test_each_required_size_missing_or_null_is_400_naming_it(self, _):
        names = {"height_cm": "Boʻy", "chest": "Koʻkrak", "waist": "Bel", "hip": "Son"}
        for key, name in names.items():
            for how in (("missing", "null") if key == "height_cm" else ("missing",)):
                with self.subTest(key=key, how=how):
                    r = self.confirm(height_cm=None) if how == "null" else self.confirm(drop=(key,))
                    self.assertEqual((r.status_code, r.data["code"], r.data["field"]),
                                     (400, "MEASUREMENTS_INVALID", key))
                    self.assertEqual(r.data["detail"], f"{name}: kiriting.")
                    self.assertIsNone(self.body().confirmed_at)  # nothing locked
        r = self.client.post("/api/body/confirm/", {"landmarks": full_landmarks()}, format="json")
        self.assertEqual((r.status_code, r.data["field"]), (400, "height_cm"))
        r = self.confirm(measurements={"chest": None})  # null inside measurements: the serializer refuses it
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(self.body().confirmed_at)

    def test_all_required_confirms_and_inseam_is_optional(self, _):
        r = self.confirm()
        self.assertEqual(r.status_code, 200, r.data)
        b = self.body()
        self.assertIsNotNone(b.confirmed_at)
        self.assertEqual(b.height_cm, HEIGHT)
        self.assertNotIn("inseam", b.measurements)

    def test_missing_shoulder_width_is_computed_from_the_landmarks(self, _):
        self.assertIsNotNone(estimate())
        r = self.confirm()
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.body().measurements, {**REQUIRED, "shoulder_width": estimate()})
        self.assertTrue(self.body().shoulder_width_estimated)
        self.assertIs(r.data["shoulder_width_estimated"], True)
        self.assertEqual(r.data["measurements"]["shoulder_width"], estimate())

    def test_given_shoulder_width_is_kept(self, _):
        r = self.confirm(measurements={"shoulder_width": 47.5, "inseam": 80})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.body().measurements, {**REQUIRED, "shoulder_width": 47.5, "inseam": 80})
        self.assertFalse(self.body().shoulder_width_estimated)
        self.assertIs(r.data["shoulder_width_estimated"], False)

    def test_get_body_carries_the_flag(self, _):
        self.assertIs(self.client.get("/api/body/").data["shoulder_width_estimated"], False)  # before confirm
        self.confirm()
        self.assertIs(self.client.get("/api/body/").data["shoulder_width_estimated"], True)


@mock.patch("apps.bodies.views.run_body_validation.delay")
class EstimatedShoulderPatchTests(MediaTestCase):
    """PATCH body/measurements/ recomputes an ESTIMATED shoulder_width when height_cm changes (docs/09 #130)."""

    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.login(self.user)

    def confirmed(self, shoulder_width=None):
        self.client.post("/api/body/", {"photo": upload(), "is_adult_confirmed": "true", "sex": "male"},
                         format="multipart")
        m = {**REQUIRED, **({"shoulder_width": shoulder_width} if shoulder_width else {})}
        r = self.client.post("/api/body/confirm/", {"landmarks": full_landmarks(), "height_cm": HEIGHT,
                                                     "measurements": m}, format="json")
        assert r.status_code == 200, r.data

    def patch(self, payload):
        return self.client.patch("/api/body/measurements/", payload, format="json")

    def body(self):
        return Body.objects.get(user=self.user)

    def test_height_change_recomputes_an_estimated_value_and_keeps_the_flag(self, _):
        self.confirmed()
        r = self.patch({"height_cm": 190})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertNotEqual(estimate(190), estimate())
        self.assertEqual(self.body().measurements["shoulder_width"], estimate(190))
        self.assertTrue(self.body().shoulder_width_estimated)
        self.assertIsNotNone(self.body().measurements_changed_at)  # a value changed: the yearly lock starts

    def test_user_entered_value_is_never_recomputed(self, _):
        self.confirmed(shoulder_width=44)
        self.assertEqual(self.patch({"height_cm": 190}).status_code, 200)
        self.assertEqual(self.body().measurements["shoulder_width"], 44)
        self.assertFalse(self.body().shoulder_width_estimated)

    def test_sent_shoulder_width_wins_and_clears_the_flag(self, _):
        self.confirmed()
        self.assertEqual(self.patch({"height_cm": 190, "measurements": {"shoulder_width": 45}}).status_code, 200)
        self.assertEqual((self.body().measurements["shoulder_width"], self.body().height_cm), (45, 190))
        self.assertFalse(self.body().shoulder_width_estimated)

    def test_other_keys_keep_the_estimate_and_the_flag(self, _):
        self.confirmed()
        self.assertEqual(self.patch({"measurements": {"chest": 100}}).status_code, 200)
        self.assertEqual(self.body().measurements["shoulder_width"], estimate())
        self.assertTrue(self.body().shoulder_width_estimated)

    def test_sending_the_estimate_itself_clears_the_flag_without_the_lock(self, _):
        self.confirmed()
        r = self.patch({"measurements": {"shoulder_width": estimate()}})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(self.body().shoulder_width_estimated)
        self.assertIsNone(self.body().measurements_changed_at)  # no value changed (docs/09 #127)
        self.assertTrue(r.data["can_change_measurements"])
