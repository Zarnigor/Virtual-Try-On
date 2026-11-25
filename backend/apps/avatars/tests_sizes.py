"""Avatar shoulder width for the fit check (docs/09 #129)."""
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase

from apps.avatars.models import Avatar
from apps.avatars.sizes import shoulder_width_cm
from apps.avatars.tests_staff import full_landmarks
from apps.testing import MediaTestCase

LM = {"head_top": {"y": 50}, "foot_bottom": {"y": 1150}, "shoulder": {"y": 260, "left_x": 170, "right_x": 430}}


class ShoulderWidthTests(SimpleTestCase):
    def test_formula(self):  # 260 px x 176 cm / 1100 px = 41.6
        self.assertEqual(shoulder_width_cm(LM, 176), 41.6)
        self.assertEqual(shoulder_width_cm({**LM, "shoulder": {"width": 220}}, 165), 33.0)

    def test_none_without_data(self):
        self.assertIsNone(shoulder_width_cm(LM, None))
        self.assertIsNone(shoulder_width_cm({"shoulder": LM["shoulder"]}, 170))
        self.assertIsNone(shoulder_width_cm({**LM, "foot_bottom": {"y": 40}}, 170))
        self.assertIsNone(shoulder_width_cm(None, 170))


class FillCommandTests(MediaTestCase):
    def run_cmd(self, *args):
        out = StringIO()
        call_command("fill_avatar_shoulder_width", *args, stdout=out)
        return out.getvalue()

    def test_fills_missing_never_overwrites_and_dry_run(self):
        a = Avatar.objects.create(sex="male", build="slim", height_cm=176, landmarks=LM, measurements={"chest": 90})
        b = Avatar.objects.create(sex="male", build="plus", height_cm=176, landmarks=LM,
                                  measurements={"shoulder_width": 50})
        c = Avatar.objects.create(sex="female", build="slim", height_cm=None, landmarks=LM, measurements={})
        out = self.run_cmd("--dry-run")
        self.assertIn("would set 41.6", out)
        a.refresh_from_db()
        self.assertEqual(a.measurements, {"chest": 90})
        out = self.run_cmd()
        for x in (a, b, c):
            x.refresh_from_db()
        self.assertEqual(a.measurements, {"chest": 90, "shoulder_width": 41.6})
        self.assertEqual(b.measurements, {"shoulder_width": 50})  # kept
        self.assertEqual(c.measurements, {})  # no height: skipped
        self.assertIn("kept 50", out)
        self.assertIn("skipped", out)


class StaffLandmarkSaveTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.staff = self.make_user("staff@test.uz")
        self.staff.is_staff = True
        self.staff.save()
        self.login(self.staff)
        self.avatar = Avatar.objects.create(sex="male", build="average", height_cm=170,
                                            measurements={"chest": 98, "shoulder_width": 99})

    def patch(self, **data):
        return self.client.patch(f"/api/staff/avatars/{self.avatar.id}/landmarks/",
                                 {"landmarks": full_landmarks(), **data}, format="json")

    def test_recomputed_on_landmark_save(self):
        r = self.patch(height_cm=180)
        self.assertEqual(r.status_code, 200, r.data)
        self.avatar.refresh_from_db()
        expected = shoulder_width_cm(self.avatar.landmarks, 180)
        self.assertIsNotNone(expected)
        self.assertEqual(self.avatar.measurements, {"chest": 98, "shoulder_width": expected})

    def test_explicit_value_wins(self):
        r = self.patch(measurements={"shoulder_width": 45})
        self.assertEqual(r.status_code, 200, r.data)
        self.avatar.refresh_from_db()
        self.assertEqual(self.avatar.measurements["shoulder_width"], 45)
