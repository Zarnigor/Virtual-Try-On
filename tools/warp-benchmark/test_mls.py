"""MLS benchmark pairing tests (synthetic figures, no DB). Run (docs/06 "MLS single-field benchmark"):

    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T -w /tmp/warp-benchmark -e PYTHONPATH=/app:/tmp/warp-benchmark backend \
        python -m unittest test_mls
"""
import hashlib
import unittest

import cv2
import numpy as np

import mls
from apps.tryon_engine import warp as prod

SHIRT = (40, 160, 40, 255)
# sha256 of the layers rendered BEFORE the chest-drop rule (2026-11-11): normal garments must stay pixel-identical.
NORMAL_MLS_SHA = "6a2af02699f638ef0b2bf668638bc3781efca1a0d9ba03736fb3ddda83ce46fe"
NORMAL_PROD_SHA = "d8a0a251429fe4ffa1e81a807a33fe5d6da2cc3f21ed31e822d2cbd513c5cd23"


def avatar():
    from apps.tryon_engine.tests import avatar as synthetic
    base, lm = synthetic()
    lm["armpit"].update(left_x=215, right_x=385)  # edge points, as a marked avatar has them
    return base, lm


def garment(armpit_y, chest_y, shoulder_drop=0):
    """V-neck T-shirt, 400 x 440, centre x 200 (body-like proportions: shoulder -> hem 390 px). The sleeve joins
    the torso at armpit_y (the underarm corner); shoulder_drop moves the shoulder seam outward (oversized, dropped
    shoulder)."""
    img = np.zeros((440, 400, 4), np.uint8)
    l, r = 120 - shoulder_drop, 280 + shoulder_drop
    torso = [(l, 30), (175, 30), (200, 60), (225, 30), (r, 30), (r, 420), (l, 420)]
    cv2.fillPoly(img, [np.array(torso, np.int32)], SHIRT)
    cv2.fillPoly(img, [np.array([(l, 30), (l - 62, armpit_y + 10), (l - 30, armpit_y + 35), (l, armpit_y)],
                                np.int32)], SHIRT)
    cv2.fillPoly(img, [np.array([(r, 30), (r + 62, armpit_y + 10), (r + 30, armpit_y + 35), (r, armpit_y)],
                                np.int32)], SHIRT)
    lm = {"shoulder": {"y": 30, "left_x": l, "right_x": r},
          "armpit": {"y": armpit_y, "left_x": l, "right_x": r},
          "chest": {"y": chest_y, "left_x": l, "right_x": r},
          "waist": {"y": 250, "left_x": l, "right_x": r}, "hem": {"y": 420, "left_x": l, "right_x": r},
          "sleeve_end": {"left": {"x": l - 46, "y": armpit_y + 22}, "right": {"x": r + 46, "y": armpit_y + 22}}}
    return img, lm


def sha(a):
    return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


class ChestPairTests(unittest.TestCase):
    def test_oversized_garment_drops_the_chest_pair_without_folds(self):
        base, blm = avatar()
        img, glm = garment(armpit_y=150, chest_y=140, shoulder_drop=40)  # armpit below the chest line
        layer, info = mls.warp(img, glm, blm, base=base)
        self.assertIsNotNone(layer)
        self.assertNotIn("chest_l", info["pairs"])
        self.assertNotIn("chest_r", info["pairs"])
        self.assertIn("chest_l", info["rejected"])
        self.assertEqual(mls.metrics(layer, info, blm)["fold"], 0.0)

    def test_chest_pair_is_dropped_when_only_the_marked_armpit_says_so(self):
        pairs = {"armpit_l": ((80, 100), (215, 345), 1.0), "chest_l": ((80, 140), (210, 380), 1.0)}
        self.assertEqual(mls.drop_crossing_chest(pairs, {"armpit": {"y": 150}}), ["chest_l"])
        self.assertNotIn("chest_l", pairs)

    def test_chest_pair_is_dropped_when_its_order_differs_from_the_body(self):
        pairs = {"waist_l": ((80, 200), (220, 480), 1.0), "chest_l": ((80, 210), (210, 380), 1.0)}
        self.assertEqual(mls.drop_crossing_chest(pairs, {}), ["chest_l"])
        pairs = {"waist_l": ((80, 200), (220, 480), 1.0), "chest_l": ((80, 150), (210, 380), 1.0)}
        self.assertEqual(mls.drop_crossing_chest(pairs, {"armpit": {"y": 100}}), [])

    def test_normal_garment_keeps_the_chest_pair_and_renders_as_before(self):
        base, blm = avatar()
        img, glm = garment(armpit_y=115, chest_y=150)
        layer, info = mls.warp(img, glm, blm, base=base)
        self.assertIn("chest_l", info["pairs"])
        self.assertIn("chest_r", info["pairs"])
        self.assertEqual(mls.metrics(layer, info, blm)["fold"], 0.0)
        self.assertEqual(sha(layer), NORMAL_MLS_SHA)
        rgb, _, _ = prod.render_tryon(base, blm, [("tshirt", img, glm)])
        self.assertEqual(sha(rgb), NORMAL_PROD_SHA)


class LandmarkMlsTests(unittest.TestCase):
    """mls_landmarks: marked landmarks only, fit strength k."""

    def full(self):
        img, glm = garment(armpit_y=115, chest_y=150)
        glm = dict(glm)
        glm.pop("sleeve_end")
        glm["collar"] = {"y": 30, "left_x": 175, "right_x": 225}
        glm["collar_bottom"] = {"x": 200, "y": 60}
        glm["sleeve_cuff_outer"] = {"left": {"x": 58, "y": 125}, "right": {"x": 342, "y": 125}}
        glm["sleeve_cuff_inner"] = {"left": {"x": 90, "y": 150}, "right": {"x": 310, "y": 150}}
        return img, glm

    def test_missing_landmark_is_reported_never_filled(self):
        import mls_landmarks as ml
        img, glm = self.full()
        self.assertEqual(ml.missing_landmarks(glm), [])
        glm.pop("collar")
        info = {}
        self.assertIsNone(ml.warp(img, glm, avatar()[1], info=info))
        self.assertEqual(info["missing"], ["collar"])

    def test_k_zero_is_the_aligned_garment_and_k_one_reaches_the_body(self):
        import mls_landmarks as ml
        base, blm = avatar()
        img, glm = self.full()
        mask = prod.figure_mask(base)
        p0, _, s = ml.control_points(glm, blm, mask, k=0.0)
        p1, _, _ = ml.control_points(glm, blm, mask, k=1.0)
        q = np.array(p0["waist_l"][0]) * s
        self.assertTrue(np.allclose(np.array(p0["waist_l"][1]) - q, np.array(p0["shoulder_l"][1]) -
                                    np.array(p0["shoulder_l"][0]) * s))  # one translation for every point
        self.assertEqual(p1["waist_l"][1], (220.0, 480.0))
        self.assertEqual(p0["neck_c"][1], p1["neck_c"][1])  # anchors never move off the alignment
        info = {}
        layer = ml.warp(img, glm, blm, base=base, info=info)
        self.assertEqual(layer.shape, (1200, 600, 4))


class KeepShapeTests(unittest.TestCase):
    """Round 3: per-point, per-axis k (k_map), bare-shoulder and print-distortion metrics."""
    full = LandmarkMlsTests.full

    def test_k_map_is_per_point_and_per_axis_and_falls_back_to_k(self):
        import mls_landmarks as ml
        base, blm = avatar()
        img, glm = self.full()
        mask = prod.figure_mask(base)
        p0, _, s = ml.control_points(glm, blm, mask, k=0.0)
        p1, _, _ = ml.control_points(glm, blm, mask, k=1.0)
        pa, _, _ = ml.control_points(glm, blm, mask, k_map=ml.PRESETS["A"])
        a0, a1, got = (np.array(p["shoulder_l"][1]) for p in (p0, p1, pa))
        self.assertTrue(np.allclose(got, a0 + np.array([0.5, 1.0]) * (a1 - a0)))  # shoulder x 0.5, y 1.0
        a0, a1, got = (np.array(p["waist_l"][1]) for p in (p0, p1, pa))
        self.assertTrue(np.allclose(got, a0 + 0.3 * (a1 - a0)))
        self.assertEqual(ml.k_of({"chest": 0.3}, "waist", 0.7), (0.7, 0.7))  # unnamed group -> k
        self.assertEqual(pa["neck_c"][1], p1["neck_c"][1])

    def test_bare_shoulder_counts_uncovered_figure_pixels_in_the_band(self):
        import mls_landmarks as ml
        base, blm = avatar()
        mask = prod.figure_mask(base)
        info = {"pairs": {"neck_l": (None, (270.0, 250.0), 5.0), "neck_r": (None, (330.0, 250.0), 5.0)}}
        covered = np.zeros((1200, 600, 4), np.uint8)
        covered[:, :, 3] = 255
        self.assertEqual(ml.bare_shoulder_px(covered, mask, info, blm), 0)
        self.assertGreater(ml.bare_shoulder_px(np.zeros_like(covered), mask, info, blm), 500)

    def test_print_distortion_is_zero_for_a_uniform_move(self):
        import mls_landmarks as ml
        img = np.zeros((200, 200, 4), np.uint8)
        img[:, :] = (40, 160, 40, 255)
        img[60:140, 50:150] = (230, 230, 230, 255)
        box = ml.print_bbox(img)
        self.assertEqual(box, (50, 60, 149, 139))
        yy, xx = np.mgrid[0:300, 0:300].astype(np.float32)
        layer = np.zeros((300, 300, 4), np.uint8)
        layer[:, :, 3] = 255
        self.assertEqual(ml.print_distortion(layer, {"map": (xx / 1.5, yy / 1.5)}, box), 0.0)
        self.assertGreater(ml.print_distortion(layer, {"map": (xx ** 1.3 / 6, yy / 1.5)}, box), 0.05)


class ShoulderSlopeTests(unittest.TestCase):
    """Round 4: shoulder_slope pair, alignment tweak, excess metric."""
    full = LandmarkMlsTests.full

    def test_body_slope_point_is_raised_to_the_figure_never_lowered(self):
        import mls_landmarks as ml
        base, blm = avatar()
        mask = prod.figure_mask(base)
        x, y = ml.body_slope_point(mask, blm, "left")
        line_y = blm["neck"]["y"] + 0.5 * (blm["shoulder"]["y"] - blm["neck"]["y"])
        self.assertAlmostEqual(x, 235.0)
        self.assertLessEqual(y, line_y - prod.HALO_ERODE - 1)
        empty = np.zeros_like(mask)
        self.assertAlmostEqual(ml.body_slope_point(empty, blm, "left")[1], line_y - prod.HALO_ERODE - 1)

    def test_slope_pair_and_alignment_tweak(self):
        import mls_landmarks as ml
        base, blm = avatar()
        img, glm = self.full()
        mask = prod.figure_mask(base)
        alpha = img[:, :, 3] > 128
        self.assertEqual(ml.garment_top_edge(alpha, glm, "left"), (148.0, 30.0))
        p, _, s0 = ml.control_points(glm, blm, mask, k_map=ml.PRESETS["A"], alpha=alpha, slope_pair=True)
        self.assertEqual(p["slope_l"][1], ml.body_slope_point(mask, blm, "left"))  # k 1.0
        al = {}
        _, _, s1 = ml.control_points(glm, blm, mask, alpha=alpha, align_tweak=True, align_out=al)
        self.assertAlmostEqual(s1, ml.ALIGN_SCALE_UP * s0)
        self.assertLessEqual(al["dy"], 0.0)  # only ever moved up
        bad = {"neck_l": ((175, 30), (270, 220), 5.0), "shoulder_l": ((120, 30), (200, 260), 1.0),
               "slope_l": ((100, 30), (235, 238), 1.0)}  # garment slope x outside collar..shoulder
        self.assertEqual(ml.validate_slope(bad), ["slope_l"])

    def test_excess_counts_garment_over_background_above_the_shoulder(self):
        import mls_landmarks as ml
        base, blm = avatar()
        mask = prod.figure_mask(base)
        layer = np.zeros((1200, 600, 4), np.uint8)
        self.assertEqual(ml.excess_px(layer, mask, blm), 0)
        layer[200:262, 200:400, 3] = 255
        self.assertGreater(ml.excess_px(layer, mask, blm), 100)


def ml_warp_plain(img, glm, blm, base, info):
    import mls_landmarks as ml
    return ml.warp(img, glm, blm, base=base, info=info)


class FittedTests(unittest.TestCase):
    """Round 6 (mls_fitted): cuffs on the arm, hem from the silhouette + centre, acromion, hard edge, metrics."""
    full = LandmarkMlsTests.full

    def test_k_map_anchors_neck_and_shoulder(self):
        import mls_fitted as mf
        km = mf.k_map_for(0.5)
        self.assertEqual((km["neck"], km["shoulder"]), (1.0, 1.0))
        self.assertEqual({km[g] for g in ("armpit", "chest", "waist", "hem", "cuff")}, {0.5})

    def test_arm_centre_is_extrapolated_above_the_separated_rows(self):
        import mls_fitted as mf
        rows = [(400 + i, 150 - 0.5 * i, 180 - 0.5 * i) for i in range(20)]
        c, w = mf._arm_at({"left": {"rows": rows}}, "left", 380)
        self.assertAlmostEqual(c, 175.0)
        self.assertAlmostEqual(w, 30.0)
        self.assertIsNone(mf._arm_at({"left": {"rows": rows[:3]}}, "left", 380))

    def test_fitted_warp_hard_edge_hem_centre_and_cuffs_on_the_arm(self):
        import mls_fitted as mf
        base, blm = avatar()
        img, glm = self.full()
        info = {}
        layer = mf.warp(img, glm, blm, base=base, info=info)
        a = layer[:, :, 3]
        self.assertFalse(((a > 0) & (a < mf.HARD_EDGE)).any())  # no soft specks
        self.assertIn("hem_c", info["pairs"])
        hl, hc, hr = (info["pairs"][n][1] for n in ("hem_l", "hem_c", "hem_r"))
        self.assertAlmostEqual(hc[1], hl[1])
        self.assertTrue(hl[0] < hc[0] < hr[0])
        mask = prod.figure_mask(base)
        w_cuff = np.linalg.norm(np.subtract(info["pairs"]["cuff_out_l"][1], info["pairs"]["cuff_in_l"][1]))
        arm = mf._arm_at(prod.find_arms(mask, blm), "left", info["pairs"]["cuff_out_l"][1][1])
        self.assertLessEqual(w_cuff, arm[1] * mf.CUFF_ARM_EASE + 1e-6)  # never wider than the arm + ease
        m = mf.coverage_metrics(layer, mask, info, blm)
        self.assertEqual(set(m), {"uncovered_px", "excess_px", "gap_px", "hem_curve_px"})
        plain = {}
        before = mf.coverage_metrics(ml_warp_plain(img, glm, blm, base, plain), mask, plain, blm)
        self.assertLess(m["hem_curve_px"], before["hem_curve_px"] / 2)  # 3 hem points: about half the sag


class FittedRound7Tests(unittest.TestCase):
    """Round 7: side floor, inner-cuff clamp at the armpit (the #43 notch), mid-sleeve pairs."""
    full = LandmarkMlsTests.full

    def test_side_x_is_never_inside_edge_plus_ease(self):
        import mls_fitted as mf
        self.assertEqual(mf._floor_x((215.0, 380.0), 207.0, "left"), (207.0, 380.0))
        self.assertEqual(mf._floor_x((200.0, 380.0), 207.0, "left"), (200.0, 380.0))
        self.assertEqual(mf._floor_x((385.0, 380.0), 393.0, "right"), (393.0, 380.0))

    def test_inner_cuff_crossing_the_armpit_is_clamped_not_dropped(self):
        import mls_fitted as mf
        # #43 on male slim: garment cuff_in outward of the armpit, body target inward of it (crossing)
        pairs = {"armpit_l": ((100, 248), (209, 337), 1.0), "cuff_in_l": ((85, 265), (213, 369), 1.0),
                 "smid_in_l": ((92, 256), (211, 353), 1.0), "smid_out_l": ((30, 140), (174, 313), 1.0),
                 "shoulder_l": ((55, 65), (181, 259), 1.0), "cuff_out_l": ((5, 206), (165, 368), 1.0)}
        ctx = {"rejected": []}
        mf.validate_round7(pairs, ctx)
        self.assertIn("armpit_l", pairs)
        self.assertEqual(pairs["cuff_in_l"][1], (209 - mf.UNDERARM_CLAMP, 369))
        self.assertEqual(pairs["smid_in_l"][1], ((209 + 209 - mf.UNDERARM_CLAMP) / 2, (337 + 369) / 2))
        self.assertFalse(mf._order_flips(pairs, "armpit_l", "cuff_in_l"))

    def test_round7_warp_runs_and_round6_is_unchanged_by_default(self):
        import mls_fitted as mf
        base, blm = avatar()
        img, glm = self.full()
        i6, i7 = {}, {}
        l6 = mf.warp(img, glm, blm, base=base, info=i6)
        l7 = mf.warp(img, glm, blm, base=base, info=i7, round7=True)
        self.assertEqual(l7.shape, (1200, 600, 4))
        self.assertFalse(any(n.startswith("smid") for n in i6["pairs"]))
        self.assertFalse((l6 == l7).all())


if __name__ == "__main__":
    unittest.main()
