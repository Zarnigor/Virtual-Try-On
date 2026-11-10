"""Warp engine tests on synthetic figures (no media, no DB): sleeves, hands above the garment, lengths."""
import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.tryon_engine import warp

H, W = 1200, 600
SKIN = (90, 120, 200, 255)  # BGRA
SHIRT = (40, 160, 40, 255)
PANTS = (160, 60, 30, 255)


def avatar(opaque_white=False):
    """A-pose figure with arms separated below the armpit, on transparent (or opaque white) background."""
    img = np.zeros((H, W, 4), np.uint8)
    if opaque_white:
        img[:] = (255, 255, 255, 255)
    poly = lambda pts: cv2.fillPoly(img, [np.array(pts, np.int32)], SKIN)  # noqa: E731
    cv2.circle(img, (300, 130), 70, SKIN, -1)
    poly([(270, 190), (330, 190), (330, 260), (270, 260)])  # neck
    poly([(200, 260), (400, 260), (390, 380), (380, 480), (395, 640), (395, 670), (205, 670), (205, 640),
          (220, 480), (210, 380)])  # torso
    poly([(205, 660), (298, 660), (275, 1040), (275, 1150), (230, 1150), (230, 1040)])  # left leg
    poly([(302, 660), (395, 660), (370, 1040), (370, 1150), (325, 1150), (325, 1040)])  # right leg
    poly([(200, 260), (180, 265), (120, 700), (150, 705), (205, 330)])  # left arm
    poly([(400, 260), (420, 265), (480, 700), (450, 705), (395, 330)])  # right arm
    lm = {
        "head_top": {"y": 60}, "neck": {"y": 220, "left_x": 270, "right_x": 330},
        "shoulder": {"y": 260, "left_x": 200, "right_x": 400}, "armpit": {"y": 345},
        "chest": {"y": 380, "left_x": 210, "right_x": 390}, "waist": {"y": 480, "left_x": 220, "right_x": 380},
        "hip": {"y": 640, "left_x": 205, "right_x": 395}, "crotch": {"y": 670, "center_x": 300},
        "knee": {"y": 860, "left_leg": {"left_x": 218, "right_x": 287}, "right_leg": {"left_x": 313, "right_x": 383}},
        "ankle": {"left_leg": {"y": 1040, "left_x": 230, "right_x": 275},
                  "right_leg": {"y": 1040, "left_x": 325, "right_x": 370}},
        "foot_bottom": {"y": 1150},
    }
    return img, lm


def tshirt(sleeve_end_y=110, hem_y=320):
    img = np.zeros((hem_y + 10, 300, 4), np.uint8)
    cv2.fillPoly(img, [np.array([(70, 30), (230, 30), (230, hem_y), (70, hem_y)], np.int32)], SHIRT)
    cv2.fillPoly(img, [np.array([(70, 30), (8, sleeve_end_y), (40, sleeve_end_y + 25), (75, 100)], np.int32)], SHIRT)
    cv2.fillPoly(img, [np.array([(230, 30), (292, sleeve_end_y), (260, sleeve_end_y + 25), (225, 100)], np.int32)], SHIRT)
    lm = {"shoulder": {"y": 30, "left_x": 70, "right_x": 230}, "chest": {"y": 100, "left_x": 75, "right_x": 225},
          "waist": {"y": 200, "left_x": 75, "right_x": 225}, "hem": {"y": hem_y, "left_x": 70, "right_x": 230},
          "sleeve_end": {"left": {"x": 10, "y": sleeve_end_y}, "right": {"x": 290, "y": sleeve_end_y}}}
    return img, lm


def pants(hem_y=590, flare=40):
    img = np.zeros((hem_y + 10, 280, 4), np.uint8)
    cv2.fillPoly(img, [np.array([(60, 10), (220, 10), (230, 100), (230, 180), (50, 180), (50, 100)], np.int32)], PANTS)
    cv2.fillPoly(img, [np.array([(50, 180), (138, 180), (120, hem_y), (60 - flare, hem_y)], np.int32)], PANTS)
    cv2.fillPoly(img, [np.array([(142, 180), (230, 180), (220 + flare, hem_y), (160, hem_y)], np.int32)], PANTS)
    knee_y = 180 + (hem_y - 180) // 2
    lm = {"waist": {"y": 10, "left_x": 60, "right_x": 220, "center_x": 140},
          "hip": {"y": 100, "left_x": 50, "right_x": 230}, "crotch": {"y": 180, "center_x": 140},
          "knee": {"y": knee_y, "left_leg": {"left_x": 40, "right_x": 129}, "right_leg": {"left_x": 151, "right_x": 240}},
          "hem": {"left_leg": {"y": hem_y - 2, "left_x": 60 - flare, "right_x": 120},
                  "right_leg": {"y": hem_y - 2, "left_x": 160, "right_x": 220 + flare}}}
    return img, lm


def color_rows(rgb, color, x0, x1):
    m = (np.abs(rgb[:, x0:x1].astype(int) - np.array(color[:3])).max(axis=2) < 30).any(axis=1)
    return np.where(m)[0]


class FigureTests(SimpleTestCase):
    def test_mask_from_alpha_and_from_white(self):
        for opaque in (False, True):
            img, _ = avatar(opaque)
            m = warp.figure_mask(img)
            self.assertTrue(m[400, 300])
            self.assertFalse(m[20, 20])

    def test_arms_found_with_outward_slope(self):
        img, lm = avatar()
        arms = warp.find_arms(warp.figure_mask(img), lm)
        self.assertLess(arms["left"]["slope"], 0)
        self.assertGreater(arms["right"]["slope"], 0)
        self.assertGreater(arms["left"]["end_y"], 680)


class TshirtTests(SimpleTestCase):
    def test_canvas_and_short_sleeves_follow_the_arm(self):
        base, lm = avatar()
        g, glm = tshirt(sleeve_end_y=75)
        rgb, warns, dbg = warp.render_tryon(base, lm, [("tshirt", g, glm)])
        self.assertEqual(rgb.shape, (H, W, 3))
        left_arm = dbg["arms"]["left"]
        arm_len = left_arm["end_y"] - lm["shoulder"]["y"]
        sleeve_rows = color_rows(rgb, SHIRT, 100, 190)  # outside the torso, on the left arm
        self.assertTrue(len(sleeve_rows))
        self.assertLess(sleeve_rows.max() - lm["shoulder"]["y"], 0.5 * arm_len)
        self.assertFalse([w for w in warns if "shortened" in w], warns)

    def test_long_sleeve_end_is_clamped_with_a_warning(self):
        base, lm = avatar()
        g, glm = tshirt(sleeve_end_y=300)
        rgb, warns, dbg = warp.render_tryon(base, lm, [("tshirt", g, glm)])
        self.assertTrue([w for w in warns if "sleeve left: shortened" in w], warns)
        arm_len = dbg["arms"]["left"]["end_y"] - lm["shoulder"]["y"]
        self.assertLess(color_rows(rgb, SHIRT, 100, 190).max() - lm["shoulder"]["y"], 0.56 * arm_len)

    def test_hands_and_forearms_stay_above_the_garment(self):
        base, lm = avatar()
        g, glm = tshirt(sleeve_end_y=300)
        p, plm = pants()
        rgb, _, dbg = warp.render_tryon(base, lm, [("tshirt", g, glm), ("pants", p, plm)])
        for side in ("left", "right"):
            rows = dbg["arms"][side]["rows"]
            for y, l, r in rows[len(rows) // 2:]:  # forearm + hand
                np.testing.assert_array_equal(rgb[y, l:r + 1], base[y, l:r + 1, :3])

    def test_hem_follows_the_garment_length(self):
        base, lm = avatar()
        ends = []
        for hem_y in (230, 320):
            g, glm = tshirt(hem_y=hem_y)
            rgb, _, _ = warp.render_tryon(base, lm, [("tshirt", g, glm)])
            ends.append(color_rows(rgb, SHIRT, 290, 310).max())
        self.assertLess(ends[0] + 40, ends[1])  # shorter garment, shorter on the body
        self.assertLess(ends[0], lm["hip"]["y"])

    def test_collar_above_the_shoulder_line_is_kept(self):
        base, lm = avatar()
        g, glm = tshirt()
        g[5:30, 120:180] = SHIRT  # collar above the shoulder landmark
        rgb, _, _ = warp.render_tryon(base, lm, [("tshirt", g, glm)])
        self.assertLess(color_rows(rgb, SHIRT, 280, 320).min(), lm["shoulder"]["y"])


class PantsTests(SimpleTestCase):
    def test_full_length_ends_at_the_ankle_and_keeps_the_flare(self):
        base, lm = avatar()
        p, plm = pants(flare=40)
        rgb, warns, _ = warp.render_tryon(base, lm, [("pants", p, plm)])
        rows = color_rows(rgb, PANTS, 200, 300)
        self.assertLessEqual(abs(rows.max() - lm["ankle"]["left_leg"]["y"]), 3)
        y = int(lm["ankle"]["left_leg"]["y"]) - 2
        cols = np.where((np.abs(rgb[y].astype(int) - np.array(PANTS[:3])).max(axis=1) < 30))[0]
        left = cols[cols < 300]
        ankle_w = lm["ankle"]["left_leg"]["right_x"] - lm["ankle"]["left_leg"]["left_x"]
        self.assertGreater(left.max() - left.min(), 1.3 * ankle_w)  # not squeezed to the ankle
        self.assertFalse([w for w in warns if "leg" in w and "distorted" in w], warns)

    def test_short_pants_end_above_the_knee(self):
        base, lm = avatar()
        p, plm = pants(hem_y=300, flare=0)
        rgb, _, _ = warp.render_tryon(base, lm, [("pants", p, plm)])
        self.assertLess(color_rows(rgb, PANTS, 200, 300).max(), lm["knee"]["y"])

    def test_pants_drawn_under_the_tshirt(self):
        base, lm = avatar()
        g, glm = tshirt(hem_y=320)
        p, plm = pants()
        rgb, _, _ = warp.render_tryon(base, lm, [("pants", p, plm), ("tshirt", g, glm)])
        y = int(lm["waist"]["y"]) + 20
        np.testing.assert_allclose(rgb[y, 300], SHIRT[:3], atol=30)


def scale_x(lm, k):
    """Landmarks with every *_x multiplied by k."""
    return {key: scale_x(v, k) if isinstance(v, dict) else (v * k if key.endswith("_x") else v) for key, v in lm.items()}


class PantsWidthTests(SimpleTestCase):
    def test_loose_garment_keeps_its_own_width(self):
        self.assertEqual(warp.pants_width(150, 100), 150)

    def test_tight_garment_gets_body_plus_ease(self):
        self.assertAlmostEqual(warp.pants_width(80, 100), 100 * (1 + warp.PANTS_EASE))

    def test_cap_at_body_multiple(self):
        self.assertAlmostEqual(warp.pants_width(300, 100), 100 * warp.PANTS_MAX_BODY)

    def test_cuff_below_the_knee_is_capped_by_the_knee_not_the_ankle(self):
        self.assertAlmostEqual(warp.pants_width(120, 30), 54)  # capped by the thin ankle row itself
        self.assertEqual(warp.pants_width(120, 30, cap_ref=70), 120)  # knee reference: the cuff keeps its width
        self.assertAlmostEqual(warp.pants_width(300, 30, cap_ref=70), 126)

    def test_waist_blend_goes_from_body_fit_to_garment(self):
        self.assertAlmostEqual(warp.waist_blend_width(150, 100, 0), 104)
        self.assertAlmostEqual(warp.waist_blend_width(150, 100, 1), 150)
        mid = warp.waist_blend_width(150, 100, 0.5)
        self.assertTrue(104 < mid < 150)
        self.assertAlmostEqual(warp.waist_blend_width(150, 100, -1), 104)  # clamped

    def test_loose_pants_stay_wider_than_the_leg(self):
        base, lm = avatar()
        p, plm = pants(flare=0)
        p = cv2.resize(p, (p.shape[1] * 2, p.shape[0]), interpolation=cv2.INTER_NEAREST)  # twice as wide
        plm = scale_x(plm, 2)
        rgb, _, _ = warp.render_tryon(base, lm, [("pants", p, plm)])
        y = int(lm["knee"]["y"])
        cols = np.where((np.abs(rgb[y].astype(int) - np.array(PANTS[:3])).max(axis=1) < 30))[0]
        left = cols[cols < 300]
        knee_w = lm["knee"]["left_leg"]["right_x"] - lm["knee"]["left_leg"]["left_x"]
        self.assertGreater(left.max() - left.min(), 1.15 * knee_w)

    def test_tight_pants_hug_the_leg(self):
        base, lm = avatar()
        p, plm = pants(flare=0)
        plm["knee"]["left_leg"] = {"left_x": 55, "right_x": 129}  # on the drawn edges (fixture lm are wider)
        plm["knee"]["right_leg"] = {"left_x": 151, "right_x": 225}
        rgb, _, _ = warp.render_tryon(base, lm, [("pants", p, plm)])
        y = int(lm["knee"]["y"])
        skin = (np.abs(rgb[y].astype(int) - np.array(SKIN[:3])).max(axis=1) < 30)
        self.assertFalse(skin[200:400].any())  # no skin shows at the knee
        cols = np.where((np.abs(rgb[y].astype(int) - np.array(PANTS[:3])).max(axis=1) < 30))[0]
        left = cols[cols < 300]
        knee_w = lm["knee"]["left_leg"]["right_x"] - lm["knee"]["left_leg"]["left_x"]
        self.assertLess(left.max() - left.min(), 1.25 * knee_w)


class ShadingTests(SimpleTestCase):
    def test_shading_map_range_and_flat_is_neutral(self):
        base, _ = avatar()
        rng = np.random.default_rng(0)
        base[:, :, :3] = np.clip(base[:, :, :3].astype(int) + rng.integers(-80, 80, base[:, :, :3].shape), 0, 255)
        region = np.zeros((H, W), bool)
        region[500:900, 200:400] = True
        shade = warp.shading_map(base, region)
        lo, hi = warp.SHADING_RANGE
        self.assertGreaterEqual(shade.min(), lo - 1e-6)
        self.assertLessEqual(shade.max(), hi + 1e-6)
        self.assertTrue((shade[~region] == 1.0).all())
        flat = np.full((H, W, 4), 128, np.uint8)
        np.testing.assert_allclose(warp.shading_map(flat, region)[region], 1.0, atol=1e-3)

    def test_shading_never_changes_alpha(self):
        layer = np.zeros((H, W, 4), np.uint8)
        layer[100:200, 100:200] = (100, 150, 200, 180)
        shade = np.full((H, W), 0.8, np.float32)
        out = warp.apply_shading(layer, shade)
        np.testing.assert_array_equal(out[:, :, 3], layer[:, :, 3])
        self.assertLess(out[150, 150, 0], 100)
        np.testing.assert_array_equal(warp.apply_shading(layer, shade, strength=0)[:, :, :3], layer[:, :, :3])


class PantsCenterlineTests(SimpleTestCase):
    def outer_edges(self, garment_scale, flare=40):
        base, lm = avatar()
        lm["knee"]["left_leg"] = {"left_x": 238, "right_x": 296}  # knee inward of the thigh (male_plus shape)
        lm["knee"]["right_leg"] = {"left_x": 304, "right_x": 362}
        p, plm = pants(flare=flare)
        if garment_scale != 1:
            p = cv2.resize(p, (int(p.shape[1] * garment_scale), p.shape[0]), interpolation=cv2.INTER_NEAREST)
            plm = scale_x(plm, garment_scale)
        rgb, _, _ = warp.render_tryon(base, lm, [("pants", p, plm)])
        is_pants = (np.abs(rgb.astype(int) - np.array(PANTS[:3])).max(axis=2) < 40)
        ky = lm["knee"]["y"]
        left, right = [], []
        for y in range(ky - 100, ky + 101, 2):
            cols = np.where(is_pants[y])[0]
            left.append(cols[cols < 300].min())
            right.append(cols[cols >= 300].max())
        return np.diff(left), np.diff(right)

    def assert_monotonic(self, d):
        """Edge positions never reverse by more than 1 px in total (a slow bulge counts, not just steps)."""
        e = np.concatenate([[0], np.cumsum(d)])
        up = (np.maximum.accumulate(e) - e).max()
        down = (e - np.minimum.accumulate(e)).max()
        self.assertLessEqual(min(up, down), 1, e.tolist())

    def test_loose_pants_edges_are_monotonic_across_an_inward_knee(self):
        dl, dr = self.outer_edges(2)
        self.assert_monotonic(dl)
        self.assert_monotonic(dr)

    def test_smooth_centerline_limits_the_knee_pull(self):
        x = [warp.leg_centerline(y, (670, 252), (860, 267), (1040, 252), 0.25) for y in range(670, 1041, 10)]
        self.assertLessEqual(max(x) - 252, 0.25 * 15 + 0.5)
        x_full = warp.leg_centerline(860, (670, 252), (860, 267), (1040, 252), 1.0)
        self.assertAlmostEqual(x_full, 267, delta=0.5)  # tight: through the knee
        mono = [warp.leg_centerline(y, (670, 240), (860, 275), (1040, 260), 0.25) for y in range(670, 1041, 5)]
        self.assertTrue(all(b >= a - 1e-6 for a, b in zip(mono, mono[1:])))

    def test_looseness_is_one_smooth_weight_per_garment(self):
        self.assertEqual(warp.pants_looseness([1.0, 1.02])["t"], 0)
        self.assertEqual(warp.pants_looseness([1.2, 1.3])["t"], 1)
        mid = warp.pants_looseness([1.12, 1.16])
        self.assertAlmostEqual(mid["ratio"], 1.14)
        self.assertTrue(0 < mid["t"] < 1 and warp.LOOSE_KNEE_PULL < mid["knee_pull"] < 1 and 0.5 < mid["hang"] < 1)

    def test_male_plus_like_ratios_give_equal_weights_for_both_legs(self):
        base, lm = avatar()
        p, plm = pants(flare=0)
        s = (1040 - 480) / (plm["hem"]["left_leg"]["y"] - plm["waist"]["y"])
        mask = warp.figure_mask(base)
        widths = []
        for side, ratio in (("left", 1.12), ("right", 1.16)):
            k = lm["knee"][f"{side}_leg"]
            run = warp._leg_run(mask, lm["knee"]["y"], side, 300, (k["left_x"] + k["right_x"]) / 2)
            widths.append(ratio * (run[1] - run[0]) / s)
        plm["knee"]["left_leg"] = {"left_x": 128 - widths[0], "right_x": 128}
        plm["knee"]["right_leg"] = {"left_x": 152, "right_x": 152 + widths[1]}
        _, _, dbg = warp.render_tryon(base, lm, [("pants", p, plm)])
        legs = dbg["pants_fit"]["legs"]
        self.assertAlmostEqual(legs["left"]["ratio"], 1.12, delta=0.01)
        self.assertAlmostEqual(legs["right"]["ratio"], 1.16, delta=0.01)
        self.assertEqual(legs["left"]["knee_pull"], legs["right"]["knee_pull"])
        self.assertEqual(legs["left"]["hang"], legs["right"]["hang"])


def interior_holes(layer):
    """Pixels inside the largest silhouette (minus its 1 px edge) that are not fully opaque."""
    sil = warp._largest_silhouette(layer[:, :, 3])
    inner = cv2.erode(sil.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    return inner & (layer[:, :, 3] < 255)


class OpaqueGarmentTests(SimpleTestCase):
    def holed_pants(self):
        p, plm = pants()
        for x, y in ((140, 60), (90, 300), (190, 450)):  # rembg-like holes: alpha 0, garment colour kept
            p[y - 6:y + 6, x - 6:x + 6, 3] = 0
        return p, plm

    def test_holes_are_filled_in_the_source_and_after_warping(self):
        p, _ = self.holed_pants()
        self.assertTrue(interior_holes(p).any())
        filled = warp.fill_alpha_holes(p, warp.opening_mask(p, warp.background_color(p)))
        self.assertFalse(interior_holes(filled).any())
        base, lm = avatar()
        mask = warp.figure_mask(base)
        p, plm = self.holed_pants()
        layer, _ = warp.garment_layer("pants", p, plm, lm, H, W, warp.find_arms(mask, lm), {}, mask)
        self.assertFalse(interior_holes(layer).any())

    def test_background_coloured_hole_stays_open(self):
        g, _ = tshirt()
        g[60:80, 140:160] = (0, 0, 0, 0)  # same colour as the transparent background around the garment
        keep = warp.opening_mask(g, warp.background_color(g))
        self.assertTrue(keep[70, 150])
        self.assertEqual(warp.fill_alpha_holes(g, keep)[70, 150, 3], 0)

    def test_all_flags_off_leaves_rgb_untouched(self):
        base, lm = avatar()
        rng = np.random.default_rng(1)
        base[:, :, :3] = np.clip(base[:, :, :3].astype(int) + rng.integers(-60, 60, base[:, :, :3].shape), 0, 255)
        p, plm = pants()
        rgb, _, dbg = warp.render_tryon(base, lm, [("pants", p, plm)])
        mask = warp.figure_mask(base)
        layer, _ = warp.garment_layer("pants", p, plm, lm, H, W, warp.find_arms(mask, lm), {}, mask)
        solid = (layer[:, :, 3] == 255) & ~dbg["arm_mask"]
        self.assertTrue((rgb[solid] == np.array(PANTS[:3])).all())  # no shading
        far = mask & ~(cv2.dilate((layer[:, :, 3] > 0).astype(np.uint8), np.ones((15, 15), np.uint8)) > 0)
        self.assertTrue((rgb[far] == base[:, :, :3][far]).all())  # no contact shadow on the avatar
        shaded, _, _ = warp.render_tryon(base, lm, [("pants", p, plm)], shading=True, contact_shadows=True)
        self.assertFalse((shaded[solid] == np.array(PANTS[:3])).all())
