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


class UploadKeepsShoulderWidthTests(MediaTestCase):
    """POST staff/avatars/ and seed_avatars set shoulder_width from the new landmarks (docs/09 #129)."""

    def setUp(self):
        super().setUp()
        self.staff = self.make_user("staff@test.uz")
        self.staff.is_staff = True
        self.staff.save()
        self.login(self.staff)

    def post(self, **over):
        from unittest import mock
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.bodies.tests_pipeline import body_photo
        data, mask = body_photo()
        form = {"sex": "female", "build": "slim", "height_cm": 165, "shoulder": 96, "chest": 82, "waist": 64,
                "hip": 90, "photo": SimpleUploadedFile("f.jpg", data, content_type="image/jpeg"), **over}
        with mock.patch("rembg.remove", return_value=mask), mock.patch("rembg.new_session"):
            return self.client.post("/api/staff/avatars/", form, format="multipart")

    def test_reupload_keeps_a_computed_shoulder_width(self):
        self.assertEqual(self.post().status_code, 201)
        a = Avatar.objects.get()
        first = a.measurements["shoulder_width"]
        self.assertEqual(first, shoulder_width_cm(a.landmarks, 165))
        r = self.post(waist=66, height_cm=170)  # re-upload of the same (sex, build)
        self.assertEqual(r.status_code, 200, r.data)
        a.refresh_from_db()
        self.assertEqual(a.measurements["shoulder_width"], shoulder_width_cm(a.landmarks, 170))
        self.assertEqual(a.measurements["waist"], 66)

    def test_explicit_value_wins(self):
        self.assertEqual(self.post(shoulder_width=37.5).status_code, 201)
        self.assertEqual(Avatar.objects.get().measurements["shoulder_width"], 37.5)

    def test_seed_from_photos_sets_it(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        from apps.bodies.tests_pipeline import body_photo
        folder = Path(tempfile.mkdtemp())
        data, mask = body_photo()
        (folder / "female_slim.jpg").write_bytes(data)
        Avatar.objects.create(sex="female", build="slim", height_cm=165, measurements={"chest": 82})
        with mock.patch("rembg.remove", return_value=mask), mock.patch("rembg.new_session"):
            call_command("seed_avatars", src=str(folder), stdout=StringIO())
        a = Avatar.objects.get(sex="female", build="slim")
        self.assertEqual(a.measurements, {"chest": 82, "shoulder_width": shoulder_width_cm(a.landmarks, 165)})
