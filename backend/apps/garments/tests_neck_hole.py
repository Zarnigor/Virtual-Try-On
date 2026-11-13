"""Neckline hole polygon (docs/09 #102): landmark_checks rules, neck_complete, PATCH round trip, permissions."""
import copy
import json
from io import BytesIO
from pathlib import Path
from unittest import skipUnless

import numpy as np
from django.core.files.base import ContentFile
from django.test import SimpleTestCase
from PIL import Image

from apps.garments.landmark_checks import (
    LandmarksInvalid, alpha_stats, landmarks_complete, mls_ready, neck_complete, neck_hole_problem,
    validate_garment_landmarks,
)
from apps.garments.models import Garment
from apps.garments.tests_landmarks import FULL, PANTS, H, W, with_value, _DELETE
from apps.testing import MediaTestCase

# A crew-neck hole along the collar of FULL (collar y 190, x 200..280, collar_bottom 240, 230).
HOLE = [[200, 186], [280, 186], [270, 210], [240, 228], [210, 210]]
WITH_HOLE = {**copy.deepcopy(FULL), "neck_hole": {"polygon": HOLE}}
FIXTURE = Path(__file__).resolve().parents[1] / "tryon_engine" / "testdata" / "tryon_neck"


def problem(poly, area=None, bbox=None):
    return neck_hole_problem({"polygon": poly}, W, H, area, bbox)


class NeckHoleRuleTests(SimpleTestCase):
    """Each rejection reason; the full-image defaults (no alpha) are the image size."""

    def test_valid(self):
        self.assertIsNone(problem(HOLE))
        self.assertEqual(validate_garment_landmarks("tshirt", WITH_HOLE, W, H), [])

    def test_points_count_and_shape(self):
        self.assertEqual(problem(HOLE[:2]), "hole_points")
        self.assertEqual(problem([[200 + i, 190 + i % 2] for i in range(65)]), "hole_points")
        self.assertEqual(problem([[200, 190], [280, 190], [240]]), "hole_points")
        self.assertEqual(problem([[200, 190], [280, 190], [240, float("nan")]]), "hole_points")
        self.assertEqual(problem([[200, 190], [280, 190], [240, True]]), "hole_points")
        self.assertEqual(problem("x"), "hole_points")
        self.assertEqual(neck_hole_problem({"no_polygon": 1}, W, H), "hole_points")
        self.assertEqual(neck_hole_problem([1, 2], W, H), "hole_points")

    def test_inside_the_image(self):
        self.assertEqual(problem([[200, 190], [481, 190], [240, 210]]), "bounds")
        self.assertEqual(problem([[-1, 190], [280, 190], [240, 210]]), "bounds")

    def test_self_intersection_and_repeated_vertex(self):
        self.assertEqual(problem([[200, 190], [280, 210], [280, 190], [200, 210]]), "hole_self")  # bow tie
        self.assertEqual(problem([[200, 190], [280, 190], [240, 210], [280, 190]]), "hole_self")
        self.assertEqual(problem([[200, 190], [280, 190], [240, 210], [260, 190]]), "hole_self")  # touches an edge

    def test_area(self):
        self.assertEqual(problem([[200, 190], [240, 190], [280, 190]]), "hole_empty")
        big = [[100, 100], [380, 100], [380, 250], [100, 250]]  # 42 000 px
        self.assertEqual(problem(big, area=160000), "hole_area")  # > 25 % of 160 000
        self.assertIsNone(problem(big, area=168000))  # exactly 25 %
        self.assertIsNone(problem(big))  # no alpha: the whole image (307 200 px)

    def test_top_40_percent_of_the_alpha_box(self):
        bbox = (18, 186, 462, 490)  # h 305: top = 186 + 122 = 308
        self.assertIsNone(problem([[200, 183], [280, 183], [240, 308]], bbox=bbox))  # 3 px above the box: accepted
        self.assertEqual(problem([[200, 182], [280, 183], [240, 300]], bbox=bbox), "hole_top")
        self.assertEqual(problem([[200, 190], [280, 190], [240, 309]], bbox=bbox), "hole_top")

    def test_validator_names_the_group_in_uzbek(self):
        bad = with_value(WITH_HOLE, "neck_hole.polygon", [[200, 190], [280, 210], [280, 190], [200, 210]])
        with self.assertRaises(LandmarksInvalid) as cm:
            validate_garment_landmarks("tshirt", bad, W, H)
        self.assertEqual((cm.exception.reason, cm.exception.group), ("hole_self", "neck_hole"))
        self.assertIn("«Yoqa teshigi»", cm.exception.detail)
        self.assertEqual(validate_garment_landmarks("tshirt", {**FULL, "neck_hole": None}, W, H), [])

    def test_alpha_stats(self):
        a = np.zeros((10, 20), np.uint8)
        a[2:5, 3:9] = 255
        a[6, 10] = 100  # visible, not solid
        self.assertEqual(alpha_stats(a), ((3, 2, 10, 6), 18))
        self.assertEqual(alpha_stats(np.zeros((4, 4), np.uint8)), (None, 0))


class CompletenessTests(SimpleTestCase):
    def test_main_set_and_neck(self):
        self.assertTrue(landmarks_complete("tshirt", FULL))
        self.assertTrue(landmarks_complete("tshirt", with_value(FULL, "collar", _DELETE)))
        self.assertFalse(neck_complete("tshirt", FULL))  # no polygon yet
        self.assertTrue(neck_complete("tshirt", WITH_HOLE))
        self.assertFalse(neck_complete("tshirt", with_value(WITH_HOLE, "collar_bottom", _DELETE)))
        self.assertFalse(neck_complete("tshirt", {**FULL, "neck_hole": None}))
        self.assertFalse(neck_complete("tshirt", {}))
        self.assertIsNone(neck_complete("pants", PANTS))

    def test_mls_ready_needs_the_collar_points_not_the_polygon(self):
        self.assertTrue(mls_ready("tshirt", FULL))
        self.assertFalse(mls_ready("tshirt", with_value(FULL, "collar", _DELETE)))
        self.assertFalse(mls_ready("pants", PANTS))


class NeckHoleEndpointTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user()
        self.login(self.owner)

    def garment(self, png=None, owner=None):
        g = Garment(owner=owner or self.owner, type="tshirt")
        if png is None:
            buf = BytesIO()
            Image.new("RGBA", (W, H), (90, 120, 160, 255)).save(buf, format="PNG")
            png = buf.getvalue()
        g.image.save("g.png", ContentFile(png), save=False)
        g.save()
        return g

    def patch(self, g, landmarks):
        return self.client.patch(f"/api/garments/{g.id}/landmarks/", {"landmarks": landmarks}, format="json")

    def test_round_trip_and_flags(self):
        g = self.garment()
        r = self.patch(g, WITH_HOLE)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["landmarks_complete"], r.data["neck_complete"]), (True, True))
        g.refresh_from_db()
        self.assertEqual(g.landmarks, WITH_HOLE)
        got = self.client.get(f"/api/garments/{g.id}/").data
        self.assertEqual(got["landmarks"]["neck_hole"], {"polygon": HOLE})
        # step 1 sends the full object back: collar + neck_hole survive untouched
        step1 = with_value(got["landmarks"], "chest.y", 330)
        r = self.patch(g, step1)
        self.assertEqual(r.status_code, 200, r.data)
        g.refresh_from_db()
        self.assertEqual(g.landmarks["neck_hole"], {"polygon": HOLE})
        self.assertEqual(g.landmarks["collar"], FULL["collar"])
        # null = no hole: not stored
        r = self.patch(g, {**FULL, "neck_hole": None})
        self.assertEqual((r.status_code, r.data["neck_complete"]), (200, False))
        g.refresh_from_db()
        self.assertNotIn("neck_hole", g.landmarks)

    def test_invalid_polygon_is_400_and_nothing_saved(self):
        g = self.garment()
        self.patch(g, FULL)
        for poly in ([[200, 190], [280, 210], [280, 190], [200, 210]], HOLE[:2], [[200, 190], [280, 190], [240, 300]]):
            r = self.patch(g, {**FULL, "neck_hole": {"polygon": poly}})
            self.assertEqual((r.status_code, r.data["code"]), (400, "LANDMARKS_INVALID"))
            self.assertIn("«Yoqa teshigi»", r.data["detail"])
        g.refresh_from_db()
        self.assertEqual(g.landmarks, FULL)

    def test_area_rule_uses_the_real_alpha(self):
        img = np.zeros((H, W, 4), np.uint8)
        img[180:500, 100:380] = (90, 120, 160, 255)  # solid 89 600 px, box y 180..499
        buf = BytesIO()
        Image.fromarray(img).save(buf, format="PNG")
        g = self.garment(buf.getvalue())
        big = [[110, 180], [370, 180], [370, 300], [110, 300]]  # 31 200 px > 25 % of 89 600
        r = self.patch(g, {**FULL, "neck_hole": {"polygon": big}})
        self.assertEqual((r.status_code, r.data["code"]), (400, "LANDMARKS_INVALID"))
        self.assertIn("25 %", r.data["detail"])
        r = self.patch(g, WITH_HOLE)
        self.assertEqual(r.status_code, 200, r.data)

    def test_other_users_get_404(self):
        other = self.make_user("b@test.uz")
        g = self.garment(owner=other)
        r = self.patch(g, WITH_HOLE)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.client.get(f"/api/garments/{g.id}/").status_code, 404)

    @skipUnless((FIXTURE / "polygons").is_dir(), "tryon_neck fixture missing: tools/warp-benchmark/export_neck_hole_regression.py")
    def test_owner_polygons_28_40_47_are_accepted(self):
        for gid in ("28", "40", "47"):
            with self.subTest(garment=gid):
                g = self.garment((FIXTURE / "garments" / f"{gid}.png").read_bytes())
                lm = json.loads((FIXTURE / "garments" / f"{gid}.json").read_text())
                poly = json.loads((FIXTURE / "polygons" / f"{gid}.json").read_text())["polygon"]
                r = self.patch(g, {**lm, "neck_hole": {"polygon": poly}})
                self.assertEqual(r.status_code, 200, r.data)
                self.assertTrue(r.data["neck_complete"])
