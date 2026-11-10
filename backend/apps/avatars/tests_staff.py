"""Staff avatar editor API: permissions, landmark checks, saved landmarks reach the try-on engine."""
import copy
from unittest import mock

import cv2
import numpy as np
from django.core.files.base import ContentFile
from django.test import SimpleTestCase

from apps.avatars.models import Avatar
from apps.avatars.prep import fill_missing_edges
from apps.bodies.landmark_checks import BodyLandmarksInvalid, complete_body_landmarks, validate_body_landmarks
from apps.testing import MediaTestCase
from apps.tryon_engine.tests import avatar as synthetic_avatar


def full_landmarks():
    """The synthetic avatar's landmarks with edge points on every line."""
    _, lm = synthetic_avatar()
    lm = copy.deepcopy(lm)
    lm["head_top"].update(left_x=280, right_x=320)
    lm["armpit"].update(left_x=215, right_x=385)
    lm["crotch"].update(left_x=205, right_x=395)
    lm["foot_bottom"].update(left_x=230, right_x=370)
    return lm


class BodyLandmarkCheckTests(SimpleTestCase):
    def test_valid_landmarks_pass(self):
        validate_body_landmarks(full_landmarks())

    def broken(self, mutate, line):
        lm = full_landmarks()
        mutate(lm)
        with self.assertRaises(BodyLandmarksInvalid) as cm:
            validate_body_landmarks(lm)
        self.assertEqual(cm.exception.line, line)
        self.assertIn("chizigʻi", cm.exception.detail)

    def test_rules(self):
        self.broken(lambda lm: lm["head_top"].pop("left_x"), "head_top")
        self.broken(lambda lm: lm["waist"].update(left_x=390), "waist")
        self.broken(lambda lm: lm["hip"].update(y=470), "hip")  # above the waist
        self.broken(lambda lm: lm["crotch"].update(center_x=100), "crotch")
        self.broken(lambda lm: lm["knee"]["left_leg"].update(right_x=320), "knee")  # legs overlap
        self.broken(lambda lm: lm["ankle"]["right_leg"].update(y=1160), "ankle")  # below foot_bottom
        self.broken(lambda lm: lm["neck"].update(y=float("nan")), "neck")
        self.broken(lambda lm: lm["shoulder"].update(right_x=601), "shoulder")

    def test_armpit_may_equal_chest(self):
        lm = full_landmarks()
        lm["chest"]["y"] = lm["armpit"]["y"]
        validate_body_landmarks(lm)

    def test_complete_recomputes_widths(self):
        lm = full_landmarks()
        lm["waist"]["width"] = 999
        out = complete_body_landmarks(lm)
        self.assertEqual(out["waist"]["width"], 160)
        self.assertEqual(out["waist"]["center_x"], 300)
        self.assertEqual(out["knee"]["left_leg"]["width"], 69)
        self.assertEqual(out["knee"]["right_leg"]["y"], 860)
        self.assertEqual(lm["waist"]["width"], 999)  # input untouched

    def test_edges_are_filled_from_the_mask(self):
        img, lm = synthetic_avatar()
        out = fill_missing_edges(copy.deepcopy(lm), img[:, :, 3] > 128)
        for line in ("head_top", "armpit", "crotch", "foot_bottom"):
            self.assertLess(out[line]["left_x"], out[line]["right_x"], line)
        self.assertAlmostEqual(out["crotch"]["left_x"], 205, delta=3)
        self.assertAlmostEqual(out["crotch"]["right_x"], 395, delta=3)
        validate_body_landmarks(out)


class StaffAvatarApiTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        img, lm = synthetic_avatar()
        _, buf = cv2.imencode(".png", img)
        self.avatar = Avatar(sex="male", build="slim", landmarks=lm, measurements={"chest": 90})
        self.avatar.image.save("a.png", ContentFile(buf.tobytes()), save=True)
        self.staff = self.make_user("staff@test.uz")
        self.staff.is_staff = True
        self.staff.save()
        self.user = self.make_user("user@test.uz")

    def url(self, suffix=""):
        return f"/api/staff/avatars/{self.avatar.pk}/{suffix}"

    def test_non_staff_gets_404_and_anonymous_401(self):
        self.login(self.user)
        self.assertEqual(self.client.get("/api/staff/avatars/").status_code, 404)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        r = self.client.patch(self.url("landmarks/"), {"landmarks": full_landmarks()}, format="json")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.client.post("/api/staff/avatars/", {}).status_code, 404)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/staff/avatars/").status_code, 401)

    def test_list_and_detail_start_from_auto_detected_landmarks_with_edges(self):
        self.login(self.staff)
        r = self.client.get("/api/staff/avatars/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data[0]["status"], "auto")
        r = self.client.get(self.url())
        self.assertIn("left_x", r.data["landmarks"]["head_top"])
        self.avatar.refresh_from_db()
        self.assertNotIn("left_x", self.avatar.landmarks["head_top"])  # GET never writes

    def test_save_confirms_and_stores_measurements(self):
        self.login(self.staff)
        r = self.client.patch(self.url("landmarks/"), {
            "landmarks": full_landmarks(), "height_cm": 178, "measurements": {"waist": 80},
        }, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["status"], "confirmed")
        self.avatar.refresh_from_db()
        self.assertIsNotNone(self.avatar.landmarks_confirmed_at)
        self.assertEqual(self.avatar.height_cm, 178)
        self.assertEqual(self.avatar.measurements, {"chest": 90, "waist": 80})
        self.assertEqual(self.avatar.landmarks["waist"]["width"], 160)

    def test_invalid_landmarks_are_rejected(self):
        self.login(self.staff)
        lm = full_landmarks()
        lm["waist"]["left_x"] = 390
        r = self.client.patch(self.url("landmarks/"), {"landmarks": lm}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["code"], "LANDMARKS_INVALID")
        r = self.client.patch(self.url("landmarks/"), {"landmarks": full_landmarks(), "measurements": {"neck": 40}},
                              format="json")
        self.assertEqual(r.status_code, 400)
        self.avatar.refresh_from_db()
        self.assertIsNone(self.avatar.landmarks_confirmed_at)

    def test_try_on_uses_the_saved_landmarks(self):
        from apps.garments.models import Garment
        from apps.outfits.models import Outfit
        from apps.tryon_engine import tasks
        from apps.tryon_engine.tests import tshirt

        self.login(self.staff)
        lm = full_landmarks()
        lm["waist"]["left_x"] = 230  # an edit the auto-detection would not make
        self.assertEqual(self.client.patch(self.url("landmarks/"), {"landmarks": lm}, format="json").status_code, 200)

        g_img, g_lm = tshirt()
        _, buf = cv2.imencode(".png", g_img)
        g = Garment(owner=self.user, type="tshirt", landmarks=g_lm)
        g.image.save("g.png", ContentFile(buf.tobytes()), save=True)
        outfit = Outfit.objects.create(user=self.user, avatar=self.avatar)
        outfit.garments.add(g)

        seen = {}

        def fake_render(base, body_lm, garments, *a, **k):
            seen["lm"] = body_lm
            return np.zeros((1200, 600, 3), np.uint8), [], None

        with mock.patch("apps.tryon_engine.warp.render_tryon", side_effect=fake_render):
            tasks._do_warp(Outfit.objects.get(pk=outfit.pk))  # as the worker loads it
        self.assertEqual(seen["lm"]["waist"]["left_x"], 230)
        self.assertEqual(seen["lm"]["waist"]["width"], 150)
