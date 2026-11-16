"""Warp engine tests on synthetic figures (no media, no DB): sleeves, hands above the garment, lengths."""
import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.tryon_engine import warp
from apps.tryon_engine.flags import render_flags


def flags_render_source(source):
    return render_flags(source)["source"]

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


class FinishR17Tests(SimpleTestCase):
    """Benchmark round 17 (docs/06 "Finish pass, round 17"): finish="r17", off by default."""

    def blob(self):
        solid = np.zeros((H, W), bool)
        solid[300:500, 200:400] = True
        for i in range(60):  # a 1 px stair-stepped slanted edge and a sharp corner
            solid[300 + i, 400:400 + i] = True
        return solid

    def test_soft_coverage_uncovers_nothing_and_softens_the_step(self):
        solid = self.blob()
        soft = warp.soft_coverage(solid)
        self.assertTrue((soft[solid] >= 128 / 255.0).all())
        self.assertTrue((soft[~solid] < 128 / 255.0).all())
        self.assertLess(soft[400, 199], 0.5)  # just outside a straight edge: partly covered, not 0
        self.assertGreater(soft[400, 199], 0.05)
        self.assertEqual(soft[400, 300], 1.0)
        self.assertEqual(soft[100, 100], 0.0)

    def test_smooth_edges_keeps_coverage_and_grows_colour(self):
        layer = np.zeros((H, W, 4), np.uint8)
        layer[self.blob()] = (10, 200, 30, 255)
        out = warp.smooth_edges(layer)
        self.assertFalse(((layer[:, :, 3] >= 128) & (out[:, :, 3] < 128)).any())
        self.assertFalse(((layer[:, :, 3] < 128) & (out[:, :, 3] >= 128)).any())
        fringe = (out[:, :, 3] > 0) & (layer[:, :, 3] == 0)
        self.assertTrue(fringe.any())
        self.assertTrue((out[fringe][:, :3] == np.array([10, 200, 30])).all())  # no dark halo under the feather
        empty = np.zeros((H, W, 4), np.uint8)
        self.assertIs(warp.smooth_edges(empty), empty)

    def test_form_shading_map_range_and_shape(self):
        alpha = np.where(self.blob(), 255, 0).astype(np.uint8)
        shade = warp.form_shading_map(alpha)
        self.assertTrue((shade[alpha == 0] == 1.0).all())
        self.assertGreaterEqual(shade.min(), 1 - warp.FORM_SHADE - 1e-6)
        self.assertLessEqual(shade.max(), 1.0 + 1e-6)
        self.assertLess(shade[400, 201], shade[400, 300])  # darker at the outline than in the middle
        self.assertAlmostEqual(float(shade[400, 201]), float(shade[400, 398]), places=3)  # left = right
        self.assertGreater(shade[400, 300], 0.995)

    def test_default_finish_is_unchanged_and_unknown_is_rejected(self):
        base, lm = avatar()
        g, glm = tshirt()
        kw = dict(edge_feather=True, shading=True, contact_shadows=True)
        a, _, _ = warp.render_tryon(base, lm, [("tshirt", g, glm)], **kw)
        b, _, _ = warp.render_tryon(base, lm, [("tshirt", g, glm)], finish="r60", **kw)
        self.assertTrue((a == b).all())
        with self.assertRaises(ValueError):
            warp.render_tryon(base, lm, [("tshirt", g, glm)], finish="nope")
        off, _, d0 = warp.render_tryon(base, lm, [("tshirt", g, glm)])
        same, _, d1 = warp.render_tryon(base, lm, [("tshirt", g, glm)], finish="r17")  # no effect is on
        self.assertTrue((off == same).all())
        self.assertTrue((d0["tshirt_final"] == d0["tshirt_layer"]).all())

    def test_r17_render_uncovers_nothing(self):
        base, lm = avatar()
        g, glm = tshirt()
        _, _, d0 = warp.render_tryon(base, lm, [("tshirt", g, glm)])
        rgb, _, d1 = warp.render_tryon(base, lm, [("tshirt", g, glm)], edge_feather=True, shading=True,
                                       contact_shadows=True, finish="r17")
        c0, c1 = d0["tshirt_final"][:, :, 3] >= 128, d1["tshirt_final"][:, :, 3] >= 128
        self.assertTrue((c0 == c1).all())
        self.assertLessEqual(d1["arm_weight"].max(), 1.0)
        self.assertTrue((d1["arm_weight"][d1["arm_mask"]] >= 128 / 255.0).all())
        self.assertEqual(rgb.shape, (H, W, 3))


class FinishWiringTests(SimpleTestCase):
    """docs/09 #107, #108: TRYON_FINISH = r17 (default) | off; TRYON_FINISH_PANTS = 1 (default) | 0."""

    def test_flags_default_r17_and_off_is_the_three_flags(self):
        from django.test import override_settings
        f = render_flags("avatar")
        self.assertEqual((f["finish"], f["edge_feather"], f["shading"], f["contact_shadows"], f["finish_pants"]),
                         ("r17", True, True, True, True))
        with override_settings(TRYON_FINISH_PANTS=False):
            self.assertFalse(render_flags("avatar")["finish_pants"])
        with override_settings(TRYON_FINISH="off"):
            f = render_flags("avatar")
            self.assertEqual((f["finish"], f["edge_feather"], f["shading"], f["contact_shadows"], f["finish_pants"]),
                             ("r60", False, False, False, False))
            with override_settings(TRYON_SHADING=True):
                self.assertTrue(render_flags("avatar")["shading"])

    def test_invalid_setting_value_is_rejected(self):
        from django.conf import settings
        from django.core.exceptions import ImproperlyConfigured
        from tryon_studio.settings.base import parse_mls_choice
        self.assertEqual(parse_mls_choice("TRYON_FINISH_PANTS", None), "1")
        with self.assertRaises(ImproperlyConfigured):
            parse_mls_choice("TRYON_FINISH_PANTS", "yes")
        self.assertEqual(parse_mls_choice("TRYON_FINISH", None), "r17")
        self.assertEqual(parse_mls_choice("TRYON_FINISH", "OFF"), "off")
        with self.assertRaises(ImproperlyConfigured):
            parse_mls_choice("TRYON_FINISH", "r60")
        self.assertIn(settings.TRYON_FINISH, ("r17", "off"))

    def test_pants_alone_are_untouched_and_report_off_without_finish_pants(self):
        base, lm = avatar()
        p, plm = pants()
        plain, _, d0 = warp.render_tryon(base, lm, [("pants", p, plm)])
        r17, _, d1 = warp.render_tryon(base, lm, [("pants", p, plm)], edge_feather=True, shading=True,
                                       contact_shadows=True, finish="r17")
        self.assertTrue((plain == r17).all())
        self.assertEqual((d0["finish"], d1["finish"]), ("off", "off"))

    def test_finish_pants_keyword_finishes_the_pants_and_uncovers_nothing(self):
        base, lm = avatar()
        p, plm = pants()
        kw = dict(edge_feather=True, shading=True, contact_shadows=True, finish="r17")
        plain, _, d0 = warp.render_tryon(base, lm, [("pants", p, plm)])
        fin, _, d1 = warp.render_tryon(base, lm, [("pants", p, plm)], finish_pants=True, **kw)
        self.assertEqual(d1["finish"], "r17")
        self.assertTrue((plain != fin).any())
        c0, c1 = d0["final_layers"]["pants"][:, :, 3] >= 128, d1["final_layers"]["pants"][:, :, 3] >= 128
        self.assertTrue((c0 == c1).all())
        same, _, _ = warp.render_tryon(base, lm, [("pants", p, plm)], finish_pants=True)  # no effect is on
        self.assertTrue((plain == same).all())

    def test_with_a_tshirt_the_pants_px_away_from_it_are_untouched(self):
        base, lm = avatar()
        g, glm = tshirt()
        p, plm = pants()
        both = [("tshirt", g, glm), ("pants", p, plm)]
        plain, _, d0 = warp.render_tryon(base, lm, both)
        r17, _, d1 = warp.render_tryon(base, lm, both, edge_feather=True, shading=True, contact_shadows=True,
                                       finish="r17")
        self.assertEqual(d1["finish"], "r17")
        far = ~(cv2.dilate((d0["tshirt_final"][:, :, 3] > 0).astype(np.uint8), np.ones((49, 49), np.uint8)) > 0)
        self.assertTrue((plain[far] == r17[far]).all())
        self.assertTrue((plain != r17).any())
        c0, c1 = d0["tshirt_final"][:, :, 3] >= 128, d1["tshirt_final"][:, :, 3] >= 128
        self.assertTrue((c0 == c1).all())  # nothing uncovered


class TshirtFitTests(SimpleTestCase):
    def layer(self, g, glm, lm=None):
        base, lm0 = avatar()
        lm = lm or lm0
        mask = warp.figure_mask(base)
        info = {}
        out, warns = warp.warp_tshirt(lm, glm, g, H, W, arms=warp.find_arms(mask, lm), info=info, mask=mask)
        return out, info, lm, warns

    def test_rows_never_narrower_than_body_plus_ease(self):
        for narrow in (False, True):
            g, glm = tshirt()
            if narrow:  # a slim-fit body: torso much narrower than the shoulders
                for k in ("chest", "waist", "hem"):
                    glm[k]["left_x"], glm[k]["right_x"] = 105, 195
            _, info, lm, _ = self.layer(g, glm)
            for y, l, r in info["tshirt_rows"]:
                bl, br = warp.body_span(lm, y)
                self.assertGreaterEqual(r - l, (br - bl) * (1 + warp.TSHIRT_EASE) - 1, (narrow, y))
                self.assertLessEqual(r - l, (br - bl) * warp.PANTS_MAX_BODY + 1)

    def test_symmetric_garment_gives_symmetric_result(self):
        g, glm = tshirt()
        out, _, _, _ = self.layer(g, glm)
        m = out[:, :, 3] > 128
        best = max((m & np.roll(m[:, ::-1], k, axis=1)).sum() / (m | np.roll(m[:, ::-1], k, axis=1)).sum()
                   for k in (0, 1, 2))
        self.assertGreater(best, 0.97)

    def test_sleeve_overlaps_the_torso_without_a_gap(self):
        g, glm = tshirt()
        out, _, lm, _ = self.layer(g, glm)
        s = (lm["shoulder"]["right_x"] - lm["shoulder"]["left_x"]) * (1 + warp.TSHIRT_EASE) / 160
        y1 = int(lm["shoulder"]["y"] + (glm["chest"]["y"] - glm["shoulder"]["y"]) * s) - 4
        a = out[:, :, 3] > 128
        for y in range(int(lm["shoulder"]["y"]) + 2, y1):
            xs = np.nonzero(a[y])[0]
            self.assertTrue(a[y, xs.min():300].all(), f"gap left at y={y}")
            self.assertTrue(a[y, 300:xs.max() + 1].all(), f"gap right at y={y}")

    def test_head_and_neck_stay_above_a_high_collar(self):
        base, lm = avatar()
        lm["neck"]["y"] = 240  # the collar (dst y ~221..260) reaches above it
        g, glm = tshirt()
        g[0:30, 110:190] = SHIRT  # ghost-mannequin back collar above the shoulder line
        rgb, _, _ = warp.render_tryon(base, lm, [("tshirt", g, glm)])
        np.testing.assert_allclose(rgb[228, 300], SKIN[:3], atol=2)  # neck shows, not the collar
        np.testing.assert_allclose(rgb[262, 300], SHIRT[:3], atol=2)  # below the collar arc: the garment
        np.testing.assert_allclose(rgb[228, 344], SHIRT[:3], atol=2)  # outside neck width + margin: collar
        w = warp.head_neck_overlay(warp.figure_mask(base), lm)
        self.assertLess(w[262, 300], 0.01)
        self.assertGreater(w[100, 300], 0.99)
        self.assertTrue(0 < w[254, 300] < 1)  # feathered edge

    def test_neck_overlay_lower_edge_is_a_curve(self):
        base, lm = avatar()
        w = warp.head_neck_overlay(warp.figure_mask(base), lm)
        n = lm["neck"]
        bottoms = {x: int(np.nonzero(w[:, x] > 0.5)[0].max()) for x in range(n["left_x"], n["right_x"] + 1, 5)}
        centre, side = bottoms[300], bottoms[n["left_x"]]
        self.assertGreater(len(set(bottoms.values())), 3)  # not a straight horizontal edge
        self.assertGreater(centre - side, 0.15 * (n["right_x"] - n["left_x"]))  # dips at the centre

    def collared_tshirt(self):
        """T-shirt whose top edge rises from the shoulder tips to two collar peaks beside a scooped neckline."""
        g, glm = tshirt()
        cv2.fillPoly(g, [np.array([(70, 30), (115, 8), (150, 22), (185, 8), (230, 30)], np.int32)], SHIRT)
        return g, glm

    def test_shoulder_cap_covers_the_skin_between_collar_and_shoulder_only(self):
        base, lm = avatar()
        trap = np.array([(272, 205), (328, 205), (398, 258), (202, 258)], np.int32)  # sloping trapezius
        cv2.fillPoly(base, [trap], SKIN)
        g, glm = self.collared_tshirt()
        rgb, _, dbg = warp.render_tryon(base, lm, [("tshirt", g, glm)])
        cap = dbg["shoulder_cap"][:, :, 3] > 0
        self.assertGreater(int(cap.sum()), 20)  # the trapezius does rise above the garment's shoulder slope
        tshirt_a = dbg["tshirt_parts"]["torso"][:, :, 3] >= 250
        cols = np.nonzero(tshirt_a.any(axis=0))[0]
        top = tshirt_a.argmax(axis=0)
        peak_l = min((x for x in cols if x < 300), key=lambda x: top[x])
        peak_r = min((x for x in cols if x >= 300), key=lambda x: top[x])
        y_top = min(top[peak_l], top[peak_r])
        ys, xs = np.nonzero(cap)
        # clipped to its own region: never above the collar top, never inside the neckline, never deep, never
        # outside the figure, never beyond the shoulder points
        self.assertGreaterEqual(ys.min(), y_top - 2)
        self.assertFalse(cap[:, peak_l + 3:peak_r - 2].any())
        self.assertLessEqual(ys.max() - ys.min(), warp.CAP_MAX_DEPTH * 1090 + 3)
        self.assertFalse((cap & ~cv2.dilate(warp.figure_mask(base).astype(np.uint8), np.ones((3, 3))).astype(bool)).any())
        sl, sr = dbg["tshirt_shoulders"]
        self.assertTrue(sl - 2 <= xs.min() and xs.max() <= sr + 2)
        # and it does its job: below the collar top, between the collar peaks and the shoulders, no skin is left
        band = np.zeros((H, W), bool)
        band[y_top + 2:lm["shoulder"]["y"] + 30, int(sl) + 3:peak_l] = True
        band[y_top + 2:lm["shoulder"]["y"] + 30, peak_r + 1:int(sr) - 2] = True
        band &= warp.figure_mask(base) & ~dbg["arm_mask"]
        skin = (np.abs(rgb.astype(int) - np.array(SKIN[:3])).max(axis=2) < 25) & band
        self.assertEqual(int(skin.sum()), 0)

    def test_shoulder_cap_flag_off_draws_nothing(self):
        base, lm = avatar()
        cv2.fillPoly(base, [np.array([(272, 205), (328, 205), (398, 258), (202, 258)], np.int32)], SKIN)
        g, glm = self.collared_tshirt()
        _, _, dbg = warp.render_tryon(base, lm, [("tshirt", g, glm)], shoulder_cap=False)
        self.assertNotIn("shoulder_cap", dbg)

    def test_wide_pants_never_reach_above_their_waist(self):
        base, lm = avatar()
        p, plm = pants()
        p = cv2.resize(p, (int(p.shape[1] * 1.7), p.shape[0]), interpolation=cv2.INTER_NEAREST)
        plm = scale_x(plm, 1.7)
        rgb, _, dbg = warp.render_tryon(base, lm, [("pants", p, plm)])
        is_pants = (np.abs(rgb.astype(int) - np.array(PANTS[:3])).max(axis=2) < 40)
        self.assertFalse(is_pants[:int(np.ceil(dbg["pants_waist_y"]))].any())
        self.assertTrue(is_pants[int(dbg["pants_waist_y"]) + 20].any())

    def test_hem_just_above_the_waist_is_snapped_over_the_waistband(self):
        base, lm = avatar()
        g, glm = tshirt(hem_y=193)  # hem lands ~8 px above the body (= pants) waist
        g[150:, :, 1] = np.clip(160 - (np.arange(150, g.shape[0]) - 150) * 2, 0, 255)[:, None]  # vertical gradient
        g[:, :, 1] *= (g[:, :, 3] > 0)
        p, plm = pants()
        rgb, _, dbg = warp.render_tryon(base, lm, [("pants", p, plm), ("tshirt", g, glm)])
        alone, _, dbg_alone = warp.render_tryon(base, lm, [("tshirt", g, glm)])
        self.assertTrue(0 < dbg["pants_waist_y"] - dbg_alone["tshirt_hem"][0] <= warp.HEM_GAP_MAX)
        hem_y, l, r = dbg["tshirt_hem"]
        self.assertGreaterEqual(hem_y, dbg["pants_waist_y"] + warp.HEM_OVER_WAISTBAND)  # over the waistband
        # stretched, not repeated: the gradient keeps changing down to the hem (a repeated row would be flat)
        col = rgb[int(hem_y) - 14:int(hem_y) - 1, 300, 1].astype(int)
        self.assertGreaterEqual(len(set(col.tolist())), 8)
        self.assertTrue((np.diff(col) <= 0).all())
        # no gap ROW between the hem and the pants top over the columns that have pants below
        cols = [x for x in range(int(l) + 10, int(r) - 10, 3)
                if np.abs(rgb[int(hem_y) + 2:int(hem_y) + 25, x].astype(int)
                          - np.array(PANTS[:3])).max(axis=1).min() < 30]
        self.assertGreater(len(cols), 30)
        for y in range(int(dbg_alone["tshirt_hem"][0]) - 5, int(hem_y) + 3):
            row = rgb[y, cols].astype(int)
            bad = (np.abs(row - np.array(SKIN[:3])).max(axis=1) < 25) | (row > 245).all(axis=1)
            self.assertLess(bad.mean(), 0.5, f"gap row at y={y}")
        off, _, dbg_off = warp.render_tryon(base, lm, [("pants", p, plm), ("tshirt", g, glm)], hem_snap=False)
        self.assertAlmostEqual(dbg_off["tshirt_hem"][0], dbg_alone["tshirt_hem"][0])  # flag off: the gap stays

    def test_crop_top_with_pants_is_unchanged(self):
        base, lm = avatar()
        g, glm = tshirt(hem_y=150)  # hem ~60 px above the waist: the midriff shows
        p, plm = pants()
        rgb, _, dbg = warp.render_tryon(base, lm, [("pants", p, plm), ("tshirt", g, glm)])
        alone, _, _ = warp.render_tryon(base, lm, [("tshirt", g, glm)])
        y0, y1 = int(dbg["tshirt_hem"][0]) + 3, int(dbg["pants_waist_y"]) - 3
        np.testing.assert_array_equal(rgb[y0:y1], alone[y0:y1])
        np.testing.assert_allclose(rgb[y0 + 5, 300], base[y0 + 5, 300, :3], atol=1)


class SolidColourTests(SimpleTestCase):
    def test_flags_off_keep_solid_colours_exactly(self):
        base, lm = avatar()
        rng = np.random.default_rng(2)
        base[:, :, :3] = np.clip(base[:, :, :3].astype(int) + rng.integers(-60, 60, base[:, :, :3].shape), 0, 255)
        g, glm = tshirt(hem_y=260)
        p, plm = pants()
        rgb, _, dbg = warp.render_tryon(base, lm, [("pants", p, plm), ("tshirt", g, glm)])
        mask = warp.figure_mask(base)
        info = {}
        layers = [warp.garment_layer(t, i, l, lm, H, W, warp.find_arms(mask, lm), info, mask)[0]
                  for t, i, l in (("pants", p, plm), ("tshirt", g, glm))]
        k = np.ones((7, 7), np.uint8)
        head = warp.head_neck_overlay(mask, lm) > 0.001
        for layer, colour in zip(layers, (PANTS, SHIRT)):
            inner = (cv2.erode((layer[:, :, 3] == 255).astype(np.uint8), k) > 0) & ~dbg["arm_mask"] & ~head
            if colour is PANTS:  # under the T-shirt the pants are hidden
                inner &= ~(layers[1][:, :, 3] > 0)
            self.assertTrue(inner.sum() > 1000)
            self.assertTrue((rgb[inner] == np.array(colour[:3])).all(), colour)


class PantsSilhouetteTests(SimpleTestCase):
    def balloon_pants(self):
        """Legs 80 px wide down to the knee, +25 % balloon below it (100), cuff 40 % narrower than the balloon (60)."""
        img = np.zeros((600, 280, 4), np.uint8)
        cv2.fillPoly(img, [np.array([(60, 10), (220, 10), (230, 100), (230, 180), (50, 180), (50, 100)], np.int32)],
                     PANTS)
        half = [(40, 180), (40, 385), (50, 470), (50, 520), (30, 585)]
        for x0 in (60, 220):
            pts = [(x0 - dx, y) for dx, y in half] + [(x0 + dx, y) for dx, y in reversed(half)]
            cv2.fillPoly(img, [np.array(pts, np.int32)], PANTS)
        lm = {"waist": {"y": 10, "left_x": 60, "right_x": 220, "center_x": 140},
              "hip": {"y": 100, "left_x": 50, "right_x": 230}, "crotch": {"y": 180, "center_x": 140},
              "knee": {"y": 385, "left_leg": {"left_x": 20, "right_x": 100}, "right_leg": {"left_x": 180, "right_x": 260}},
              "hem": {"left_leg": {"y": 584, "left_x": 30, "right_x": 90},
                      "right_leg": {"y": 584, "left_x": 190, "right_x": 250}}}
        return img, lm

    def test_balloon_and_cuff_are_kept(self):
        base, lm = avatar()
        p, plm = self.balloon_pants()
        _, _, dbg = warp.render_tryon(base, lm, [("pants", p, plm)])
        s = (1040 - 480) / (584 - 10)  # uniform scale of this garment on this avatar
        knee_y = 480 + (385 - 10) * s
        for side in ("left", "right"):
            rows = dbg["pants_leg_rows"][side]
            w = {y: r - l for y, l, r in rows}
            knee_w = w[min(w, key=lambda y: abs(y - knee_y))]
            bulge = max(v for y, v in w.items() if y >= knee_y)
            cuff = rows[-1][2] - rows[-1][1]
            self.assertAlmostEqual(knee_w, 80 * s, delta=0.05 * 80 * s)  # knee: the garment's own width
            self.assertAlmostEqual(bulge / knee_w, 100 / 80, delta=0.05 * 100 / 80)
            self.assertAlmostEqual(cuff / bulge, 60 / 100, delta=0.05 * 60 / 100)
            ys = [y for y, _, _ in rows]  # one uniform vertical scale below the knee: evenly spaced rows
            self.assertLessEqual(max(np.diff(ys)), 6.01)


MARK = (0, 0, 255, 255)  # pure red (BGRA): appears nowhere else


class SleeveOnceTests(SimpleTestCase):
    def marked_tshirt(self):
        """Real-like T-shirt (shoulder landmarks at the sleeve tips, like garment #28) with a red stitch line on
        each cuff and one across each upper sleeve near the shoulder seam."""
        img = np.zeros((410, 340, 4), np.uint8)
        col = (20, 20, 20, 255)
        cv2.fillPoly(img, [np.array([(75, 40), (265, 40), (262, 400), (72, 400)], np.int32)], col)
        cv2.fillPoly(img, [np.array([(95, 40), (22, 62), (0, 162), (45, 195), (74, 122)], np.int32)], col)
        cv2.fillPoly(img, [np.array([(245, 40), (318, 62), (339, 162), (295, 195), (266, 122)], np.int32)], col)
        for sign, x0 in ((1, 0), (-1, 339)):
            cv2.line(img, (x0 + sign * 6, 160), (x0 + sign * 44, 186), MARK, 2)  # cuff stitch
            cv2.line(img, (x0 + sign * 45, 62), (x0 + sign * 80, 52), MARK, 2)  # upper-sleeve stitch
        lm = {"shoulder": {"y": 62, "left_x": 22, "right_x": 318}, "chest": {"y": 122, "left_x": 74, "right_x": 266},
              "waist": {"y": 270, "left_x": 72, "right_x": 264}, "hem": {"y": 396, "left_x": 72, "right_x": 262},
              "sleeve_end": {"left": {"x": 0, "y": 162}, "right": {"x": 339, "y": 162}}}
        return img, lm

    def test_each_marker_line_appears_exactly_once_per_sleeve(self):
        base, lm = avatar()
        g, glm = self.marked_tshirt()
        # halo off: its edge ring takes the nearest interior colour, which smears a stitch lying at the edge
        rgb, _, _ = warp.render_tryon(base, lm, [("tshirt", g, glm)], halo_removal=False)
        red = (rgb[:, :, 2] > 150) & (rgb[:, :, 1] < 90) & (rgb[:, :, 0] < 90)
        src_red = (g[:, :, 2] == 255) & (g[:, :, 1] == 0)
        glm_n, _ = warp.normalize_tshirt_landmarks(glm, g[:, :, 3] > 128)
        s2 = warp.tshirt_scale(glm_n, lm) ** 2
        split_dst, split_src = 320, 110  # between the upper-sleeve stitch and the cuff stitch
        for half in ("left", "right"):
            cols, src_cols = (slice(0, 300), slice(0, 170)) if half == "left" else (slice(300, W), slice(170, 340))
            for rows, src_rows in ((slice(0, split_dst), slice(0, split_src)), (slice(split_dst, H), slice(split_src, None))):
                area, once = int(red[rows, cols].sum()), float(src_red[src_rows, src_cols].sum()) * s2
                # drawn once: about the scaled source area (a line drawn twice would be ~2x); a line crossing the
                # shoulder join may lose a few px to the outer edge fix, the cuff may be shortened
                self.assertLess(area, 1.3 * once, (half, rows, area, once))
                self.assertGreater(area, 0.35 * once, (half, rows, area, once))


class RowWarpTests(SimpleTestCase):
    """_warp_rows: one clipped, sub-pixel layer."""

    def src(self):
        img = np.zeros((20, 40, 4), np.uint8)
        img[:, 10:30] = (10, 200, 90, 255)
        return img

    def test_nothing_outside_the_rows_and_colour_kept_inside(self):
        out = warp._warp_rows(self.src(), [(0, 10, 30), (19, 10, 30)], [(100, 50, 110), (160, 50, 110)], 300, 200)
        a = out[:, :, 3]
        self.assertFalse(a[:100].any() or a[161:].any())
        self.assertFalse(a[:, :48].any() or a[:, 112:].any())
        inner = out[105:155, 55:105]
        self.assertTrue((inner[:, :, 3] == 255).all())
        self.assertTrue((inner[:, :, :3] == np.array([10, 200, 90])).all())

    def test_edges_are_sub_pixel(self):
        rows_src = [(0, 10, 30), (19, 10, 30)]
        whole = warp._warp_rows(self.src(), rows_src, [(100, 50.0, 70.0), (160, 50.0, 70.0)], 300, 200)
        half = warp._warp_rows(self.src(), rows_src, [(100, 50.5, 70.5), (160, 50.5, 70.5)], 300, 200)
        self.assertEqual(whole[130, 50, 3], 255)
        self.assertEqual(whole[130, 49, 3], 0)
        self.assertTrue(90 < half[130, 50, 3] < 165)  # half a pixel covered: about half the alpha
        self.assertTrue(90 < half[130, 70, 3] < 165)
        np.testing.assert_allclose(half[130, 50, :3], [10, 200, 90], atol=1)  # the colour is not darkened

    def test_width_follows_the_rows_between_control_rows(self):
        out = warp._warp_rows(self.src(), [(0, 10, 30), (19, 10, 30)], [(100, 50, 110), (160, 20, 140)], 300, 200)
        widths = (out[:, :, 3] > 128).sum(axis=1)[100:161]
        self.assertTrue((np.diff(widths) >= 0).all())
        self.assertAlmostEqual(int(widths[30]), 90, delta=2)


class HaloTests(SimpleTestCase):
    def test_edge_is_eroded_and_recoloured_from_the_interior(self):
        img = np.zeros((60, 60, 4), np.uint8)
        img[10:50, 10:50] = (255, 255, 255, 255)  # white photo fringe ...
        img[13:47, 13:47] = (40, 30, 200, 255)  # ... around the garment colour
        out = warp.remove_halo(img)
        self.assertFalse(out[10:12, :, 3].any() or out[:, 10:12, 3].any())  # 2 px gone
        self.assertTrue((out[12:48, 12:48, 3] == 255).all())
        visible = out[out[:, :, 3] > 0][:, :3]
        self.assertTrue((visible == np.array([40, 30, 200])).all())  # no white left
        np.testing.assert_array_equal(out[20:40, 20:40], img[20:40, 20:40])  # interior untouched

    def test_flag_off_keeps_the_garment_as_cleaned(self):
        base, lm = avatar()
        g, glm = tshirt()
        on, _, _ = warp.render_tryon(base, lm, [("tshirt", g, glm)])
        off, _, _ = warp.render_tryon(base, lm, [("tshirt", g, glm)], halo_removal=False)
        is_shirt = lambda rgb: (np.abs(rgb.astype(int) - np.array(SHIRT[:3])).max(axis=2) < 30)  # noqa: E731
        self.assertGreater(int(is_shirt(off).sum()), int(is_shirt(on).sum()))


class TshirtLayerTests(SimpleTestCase):
    """The T-shirt's pieces: torso and two rigid sleeves, every garment pixel in exactly one of them."""

    def joined_tshirt(self):
        """Sleeves that hang down along the torso and stay joined to it below the armpit row (no gap)."""
        img = np.zeros((330, 300, 4), np.uint8)
        cv2.fillPoly(img, [np.array([(70, 30), (230, 30), (230, 320), (70, 320)], np.int32)], SHIRT)
        cv2.fillPoly(img, [np.array([(70, 30), (30, 60), (20, 160), (70, 160)], np.int32)], SHIRT)
        cv2.fillPoly(img, [np.array([(230, 30), (270, 60), (280, 160), (230, 160)], np.int32)], SHIRT)
        lm = {"shoulder": {"y": 30, "left_x": 70, "right_x": 230}, "chest": {"y": 100, "left_x": 70, "right_x": 230},
              "waist": {"y": 200, "left_x": 70, "right_x": 230}, "hem": {"y": 320, "left_x": 70, "right_x": 230},
              "sleeve_end": {"left": {"x": 20, "y": 160}, "right": {"x": 280, "y": 160}}}
        return img, lm

    def regions(self, g, glm):
        alpha = g[:, :, 3] > 128
        rows = [(glm[k]["y"], glm[k]["left_x"], glm[k]["right_x"]) for k in ("shoulder", "chest", "waist", "hem")]
        return alpha, {side: warp.sleeve_regions(alpha, glm, side, rows) for side in ("left", "right")}

    def test_sleeve_regions_are_disjoint_and_overlap_the_torso_by_a_few_px(self):
        for g, glm in (tshirt(), self.joined_tshirt()):
            alpha, reg = self.regions(g, glm)
            self.assertFalse((reg["left"][0] & reg["right"][0] & alpha).any())
            for side in ("left", "right"):
                own, draw = reg[side]
                self.assertGreater(int((own & alpha).sum()), 500)
                self.assertTrue((draw | ~own).all())  # draw contains own
                extra = draw & ~own & alpha
                self.assertLessEqual(int(extra.sum(axis=1).max()), 2 * warp.SLEEVE_OVERLAP + 2)

    def test_joined_sleeve_is_split_from_the_torso_below_the_armpit(self):
        g, glm = self.joined_tshirt()
        alpha, reg = self.regions(g, glm)
        torso = alpha & ~reg["left"][0] & ~reg["right"][0]
        for y in range(105, 158, 5):  # rows where sleeve and torso are one run in the image
            xs = np.nonzero(torso[y])[0]
            self.assertTrue(66 <= xs.min() <= 74 and 226 <= xs.max() <= 234, (y, xs.min(), xs.max()))
            self.assertTrue(reg["left"][0][y, 40] and reg["right"][0][y, 260])
        self.assertFalse(reg["left"][0][250:, :].any() and (reg["left"][0][250:] & alpha[250:]).any())

    def test_torso_layer_stays_inside_its_rows_and_sleeves_on_their_side(self):
        base, lm = avatar()
        g, glm = tshirt()
        mask = warp.figure_mask(base)
        info = {}
        warp.warp_tshirt(lm, glm, g, H, W, arms=warp.find_arms(mask, lm), info=info, mask=mask)
        parts = info["tshirt_parts"]
        self.assertEqual(set(parts), {"torso", "sleeve_left", "sleeve_right"})
        torso = parts["torso"][:, :, 3] > 0
        for y, l, r in info["tshirt_rows"]:
            xs = np.nonzero(torso[int(y)])[0]
            self.assertTrue(len(xs) and xs.min() >= l - 3 and xs.max() <= r + 3, (y, l, r))
        self.assertFalse(torso[int(info["tshirt_hem"][0]) + 12:].any())
        self.assertFalse((parts["sleeve_left"][:, 300:, 3] > 0).any())
        self.assertFalse((parts["sleeve_right"][:, :300, 3] > 0).any())

    def test_shoulder_landmarks_on_the_sleeves_are_moved_to_the_armholes(self):
        g, glm = tshirt()
        same, changed = warp.normalize_tshirt_landmarks(glm, g[:, :, 3] > 128)
        self.assertFalse(changed)
        self.assertIs(same, glm)
        wide = {**glm, "shoulder": {"y": 60, "left_x": 20, "right_x": 280}}  # marked at the sleeve tips
        fixed, changed = warp.normalize_tshirt_landmarks(wide, g[:, :, 3] > 128)
        self.assertTrue(changed)
        chest_w = glm["chest"]["right_x"] - glm["chest"]["left_x"]
        self.assertAlmostEqual(fixed["shoulder"]["left_x"], glm["chest"]["left_x"] - warp.SHOULDER_OVER_CHEST * chest_w)
        self.assertLess(fixed["shoulder"]["y"], glm["chest"]["y"])

    def test_layer_order_is_explicit(self):
        self.assertEqual(warp.LAYER_ORDER, ("avatar", "pants", "tshirt_torso", "tshirt_sleeves", "shoulder_cap",
                                            "neck_gap_fill", "head_neck", "hands_forearms"))


class TshirtCompositingTests(SimpleTestCase):
    """One test per defect of the T-shirt compositing round (docs/09, docs/06 "Layer order")."""

    def render(self, shirt=SHIRT, skin=SKIN, g=None, glm=None, base=None, lm=None, **kw):
        if base is None:
            base, lm = avatar()
            base[base[:, :, 3] > 0] = skin
        if g is None:
            g, glm = tshirt()
            g[g[:, :, 3] > 0] = shirt
        return warp.render_tryon(base, lm, [("tshirt", g, glm)], **kw), lm

    def test_sleeve_top_never_above_the_shoulder_line(self):
        g, glm = tshirt()
        g[g[:, :, 3] > 0] = SHIRT
        # a sleeve whose top corner rises above the armhole top: the rigid rotation lifts it further
        cv2.fillPoly(g, [np.array([(70, 30), (40, 18), (8, 110), (75, 100)], np.int32)], SHIRT)
        cv2.fillPoly(g, [np.array([(230, 30), (260, 18), (292, 110), (225, 100)], np.int32)], SHIRT)
        (_, _, dbg), _ = self.render(g=g, glm=glm)
        for side in ("left", "right"):
            m, c = dbg["shoulder_lines"][side]
            a = dbg["tshirt_parts"][f"sleeve_{side}"][:, :, 3]
            ys, xs = np.nonzero(a > 0)
            self.assertGreater(len(ys), 500)
            above = (ys + 0.5) - (m * (xs + 0.5) + c)  # < 0: above the line
            self.assertGreaterEqual(float(above.min()), -1.0, side)
            # and the line is the torso's own slope (not a flat cut at some other height)
            t = dbg["tshirt_parts"]["torso"][:, :, 3] >= 128
            x = int(dbg["tshirt_shoulders"][0 if side == "left" else 1] + (25 if side == "left" else -25))
            self.assertLessEqual(abs(int(np.argmax(t[:, x])) - (m * (x + 0.5) + c)), 2.5)

    def seam_profile(self, shirt, skin):
        (rgb, _, dbg), lm = self.render(shirt=shirt, skin=skin)
        # internal pixels only: at least 4 px inside the union's outer contour (the contour itself is soft)
        filled = (dbg["tshirt_layer"][:, :, 3] > 0).astype(np.uint8)
        inside = cv2.distanceTransform(filled, cv2.DIST_L2, 3) >= 4
        bad = []
        for side, (p0, p1) in dbg["armhole_lines"].items():
            y0, y1 = sorted((float(p0[1]), float(p1[1])))
            for y in range(int(y0) + 2, int(y1) - 2):
                t = (y - p0[1]) / (p1[1] - p0[1])
                x = int(round(p0[0] + t * (p1[0] - p0[0])))
                band = rgb[y, x - 6:x + 7].astype(int)[inside[y, x - 6:x + 7]]
                if len(band):
                    bad.append(int(np.abs(band - np.array(shirt[:3])).max()))
        return bad

    def test_no_seam_lightness_dip_dark_on_dark(self):
        bad = self.seam_profile((30, 30, 30, 255), (70, 70, 70, 255))
        self.assertGreater(len(bad), 40)
        self.assertLessEqual(max(bad), 2)

    def test_no_seam_lightness_dip_light_on_light(self):
        bad = self.seam_profile((235, 235, 235, 255), (200, 200, 200, 255))
        self.assertGreater(len(bad), 40)
        self.assertLessEqual(max(bad), 2)

    def test_sleeve_outer_contour_is_drawn_once(self):
        (_, _, dbg), _ = self.render()
        parts = dbg["tshirt_parts"]
        torso = parts["torso"][:, :, 3] > 0
        for side in ("left", "right"):
            sleeve = parts[f"sleeve_{side}"][:, :, 3]
            self.assertFalse((torso & (sleeve >= 250)).any(), side)  # under an opaque sleeve pixel: no torso
            # outward of the join (8 px past the armhole line) only the sleeve exists: its contour is drawn once
            p0, p1 = dbg["armhole_lines"][side]
            for y in range(int(p0[1]) + 2, int(p1[1])):
                x = p0[0] + (y - p0[1]) / (p1[1] - p0[1]) * (p1[0] - p0[0])
                out = torso[y, :max(int(x) - 8, 0)] if side == "left" else torso[y, int(x) + 9:]
                self.assertFalse(out.any(), (side, y))
        # one edge ramp across the outer sleeve edge: alpha never rises again after it starts falling
        layer = dbg["tshirt_layer"][:, :, 3].astype(int)
        y = int(dbg["armhole_lines"]["left"][1][1]) - 10
        row = layer[y, :300]
        first = int(np.nonzero(row > 0)[0][0])
        ramp = row[first:first + 8]
        self.assertTrue((np.diff(ramp) >= 0).all(), ramp)

    def test_cap_fill_colour_equals_the_neighbouring_garment_colour(self):
        base, lm = avatar()
        cv2.fillPoly(base, [np.array([(272, 205), (328, 205), (398, 258), (202, 258)], np.int32)], SKIN)
        g, glm = TshirtFitTests().collared_tshirt()
        top_colour = (200, 90, 150, 255)
        g[:45][g[:45, :, 3] > 0] = top_colour  # the shoulder rows differ from the body of the garment
        (rgb, _, dbg), _ = self.render(g=g, glm=glm, base=base, lm=lm)
        cap = dbg["shoulder_cap"]
        drawn = (cap[:, :, 3] > 0) & (dbg["tshirt_layer"][:, :, 3] > 0)
        self.assertGreater(int(drawn.sum()), 20)
        diff = np.abs(cap[:, :, :3][cap[:, :, 3] > 0].astype(int) - np.array(top_colour[:3])).max()
        self.assertLessEqual(int(diff), 3)  # the adjacent shoulder row, never skin or black
        visible = (cap[:, :, 3] == 255) & (dbg["tshirt_layer"][:, :, 3] == 255) & ~(dbg["head_overlay"] > 0.01)
        self.assertLessEqual(int(np.abs(rgb[visible].astype(int) - np.array(top_colour[:3])).max()), 3)

    def test_no_grey_tank_collar_between_neck_and_collar_band(self):
        base, lm = avatar()
        grey = (128, 128, 128, 255)
        tank = np.array([(250, 238), (350, 238), (420, 270), (180, 270)], np.int32)  # sits above the collar
        cv2.fillPoly(base, [tank], grey)
        cv2.fillPoly(base, [np.array([(280, 255), (320, 255), (320, 270), (280, 270)], np.int32)], SKIN)
        g, glm = NeckFixTests().crew_tshirt()
        (rgb, _, dbg), _ = self.render(g=g, glm=glm, base=base, lm=lm, source="avatar")
        is_grey = (np.abs(rgb.astype(int) - np.array(grey[:3])).max(axis=2) <= 12)
        n = lm["neck"]
        self.assertEqual(int(is_grey[150:lm["shoulder"]["y"] + 5, n["left_x"] - 10:n["right_x"] + 11].sum()), 0)
        self.assertTrue((dbg["neck_gap"] > 0.5).any())  # it was the fill, not the garment, that hid it
        # the collar band (garment pixels under the opening) stays visible
        op = dbg["neck_opening"]
        y = int(op["y0"] + op["depth"]) + 4
        np.testing.assert_allclose(rgb[y, int(op["cx"])], SHIRT[:3], atol=3)
        off, _ = self.render(g=g, glm=glm, base=base, lm=lm, neck_gap_fill=False, source="avatar")
        self.assertGreater(int((np.abs(off[0].astype(int) - np.array(grey[:3])).max(axis=2) <= 12)
                               [150:lm["shoulder"]["y"] + 5, n["left_x"] - 10:n["right_x"] + 11].sum()), 0)

    def test_neck_gap_fill_runs_for_avatars_only_never_for_an_own_body(self):
        base, lm = avatar()
        cv2.fillPoly(base, [np.array([(250, 238), (350, 238), (420, 270), (180, 270)], np.int32)], (128, 128, 128, 255))
        g, glm = NeckFixTests().crew_tshirt()
        (rgb_av, _, dbg_av), _ = self.render(g=g, glm=glm, base=base, lm=lm, source="avatar")
        self.assertTrue((dbg_av["neck_gap"] > 0.5).any())  # avatar: the fill may run
        no_fill, _ = self.render(g=g, glm=glm, base=base, lm=lm, neck_gap_fill=False, source="avatar")
        for kw in ({"source": "body"}, {"source": "body", "neck_gap_fill": True}, {}):  # {}: default = own body
            (rgb, _, dbg), _ = self.render(g=g, glm=glm, base=base, lm=lm, **kw)
            self.assertNotIn("neck_gap", dbg, kw)  # own body: never, whatever the flag
            np.testing.assert_array_equal(rgb, no_fill[0])
        self.assertEqual(flags_render_source("body"), "body")
        self.assertEqual(flags_render_source("avatar"), "avatar")
        with self.assertRaises(ValueError):
            flags_render_source("user")

    def test_neck_mask_lower_edge_is_curved_without_steps(self):
        base, lm = avatar()
        w = warp.head_neck_overlay(warp.figure_mask(base), lm, warp.NECK_FEATHER_FIX)
        n = lm["neck"]
        cols = range(n["left_x"] - warp.NECK_MARGIN - 15, n["right_x"] + warp.NECK_MARGIN + 16)
        bottom = np.array([int(np.nonzero(w[:400, x] > 0.5)[0].max()) for x in cols])
        self.assertGreater(len(set(bottom.tolist())), 10)  # a curve, not a flat edge
        inner = bottom[warp.NECK_MARGIN + 15 + 5:-(warp.NECK_MARGIN + 15 + 5)]  # inside the neck: a smooth arc
        self.assertLessEqual(int(np.abs(np.diff(inner)).max()), 3)
        self.assertGreater(int(bottom.max()) - int(bottom[0]), 0.3 * (n["right_x"] - n["left_x"]))
        # no vertical wall: at the neck sides the edge keeps rising outward, it never drops straight to the top
        self.assertTrue((np.diff(bottom[:len(bottom) // 2]) >= 0).all())
        self.assertTrue((np.diff(bottom[len(bottom) // 2:]) <= 0).all())


INNER = (20, 20, 20, 255)  # the inner back collar of the synthetic crew-neck T-shirt


class NeckFixTests(SimpleTestCase):
    """TRYON_NECK_FIX: transparent inner back collar, crisp head/neck edge, smooth shoulder alpha, neck zone only."""

    def crew_tshirt(self):
        """T-shirt with a flat back rim (x 120..180 at y 8), sloping shoulders and a dark inner back collar."""
        g, glm = tshirt()
        g[:] = 0
        cv2.fillPoly(g, [np.array([(120, 8), (180, 8), (230, 30), (230, 320), (70, 320), (70, 30)], np.int32)], SHIRT)
        cv2.fillPoly(g, [np.array([(70, 30), (8, 110), (40, 135), (75, 100)], np.int32)], SHIRT)
        cv2.fillPoly(g, [np.array([(230, 30), (292, 110), (260, 135), (225, 100)], np.int32)], SHIRT)
        yy, xx = np.mgrid[0:g.shape[0], 0:g.shape[1]]
        inner = (((xx - 150) / 24.0) ** 2 + ((yy - 8) / 18.0) ** 2 <= 1) & (yy >= 8)
        g[inner] = INNER
        return g, glm

    def layers(self, fix):
        base, lm = avatar()
        g, glm = self.crew_tshirt()
        _, _, dbg = warp.render_tryon(base, lm, [("tshirt", g, glm)], neck_fix=fix)
        return dbg["tshirt_layer"][:, :, 3], dbg, lm

    def test_inner_back_collar_is_transparent_and_the_ring_stays(self):
        on, dbg, lm = self.layers(True)
        off, _, _ = self.layers(False)
        op = dbg["neck_opening"]
        cx, y0, hw = int(op["cx"]), int(op["y0"]), op["hw"]
        self.assertEqual(int(off[y0 + 10, cx]), 255)  # flag off: the dark inner back is drawn
        self.assertEqual(int(on[y0 + 10, cx]), 0)  # flag on: transparent, the avatar's neck shows
        self.assertEqual(int(on[y0 + 4, cx - int(hw) + 6]), 0)
        self.assertEqual(int(on[y0 + 10, cx + int(hw) + 6]), 255)  # the collar ring beside it is untouched
        below = int(y0 + op["depth"]) + 6
        self.assertEqual(int(on[below, cx]), 255)  # and the ring under it (the front neckline)

    def test_nothing_changes_outside_the_neck_zone(self):
        on, _, lm = self.layers(True)
        off, _, _ = self.layers(False)
        z0, z1 = warp.neck_zone_rows(lm, H)
        np.testing.assert_array_equal(on[:z0], off[:z0])
        np.testing.assert_array_equal(on[z1 + 1:], off[z1 + 1:])
        self.assertTrue((on[z0:z1 + 1] != off[z0:z1 + 1]).any())

    def test_the_head_never_gets_the_opening_or_the_skin_repainted(self):
        base, lm = avatar()
        g, glm = self.crew_tshirt()
        rgb_on, _, _ = warp.render_tryon(base, lm, [("tshirt", g, glm)], neck_fix=True)
        # the avatar's pixels in the opening are the avatar's own (the base image), not painted
        op = warp.render_tryon(base, lm, [("tshirt", g, glm)])[2]["neck_opening"]
        y, x = int(op["y0"]) + 12, int(op["cx"])
        np.testing.assert_allclose(rgb_on[y, x], SKIN[:3], atol=1)

    def test_v_neck_or_wide_rim_is_left_alone(self):
        base, lm = avatar()
        g, glm = tshirt()  # flat top as wide as the shoulders: not a crew neck
        _, _, dbg = warp.render_tryon(base, lm, [("tshirt", g, glm)])
        self.assertNotIn("neck_opening", dbg)
        self.assertIsNone(warp.back_collar_geometry(g[:, :, 3] > 128, glm))

    def test_a_solid_block_without_a_darker_inner_back_is_left_alone(self):
        base, lm = avatar()
        g, glm = self.crew_tshirt()
        g[(g[:, :, :3] == np.array(INNER[:3])).all(axis=2)] = SHIRT  # inner back painted like the ring
        _, _, dbg = warp.render_tryon(base, lm, [("tshirt", g, glm)])
        self.assertNotIn("neck_opening", dbg)

    def test_edge_ramp_is_about_3_px(self):
        base, lm = avatar()
        mask = warp.figure_mask(base)
        w = warp.head_neck_overlay(mask, lm, warp.NECK_FEATHER_FIX)[:, 300]  # down the neck centre
        ramp = int(((w > 0.1) & (w < 0.9)).sum())  # 10-90 % width of the lower edge
        self.assertTrue(2 <= ramp <= 4, ramp)

    def test_shoulder_alpha_is_smoothed_and_the_interior_untouched(self):
        _, lm = avatar()
        layer = np.zeros((H, W, 4), np.uint8)
        layer[:, :, :3] = SHIRT[:3]
        rng = np.random.default_rng(3)
        edge = (300 + 0.4 * (np.arange(H) - 230)).astype(int) + rng.integers(-1, 2, H)  # jittery slope
        for y in range(230, 300):
            layer[y, :edge[y], 3] = 255
        out = warp.smooth_shoulder_alpha(layer, lm)

        def position(a):  # sub-pixel edge x per row = coverage
            return (a[240:290, :, 3].astype(float) / 255).sum(axis=1)  # away from the block's own end rows

        roughness = lambda p: float(np.abs(np.diff(p, 2)).sum())  # noqa: E731
        self.assertLess(roughness(position(out)), 0.6 * roughness(position(layer)))
        solid = cv2.erode((layer[:, :, 3] == 255).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        np.testing.assert_array_equal(out[solid], layer[solid])
        z0, z1 = warp.neck_zone_rows(lm, H)
        self.assertTrue(z0 <= 230 and 300 <= z1)
        # colour of newly visible edge pixels is the garment's, never black
        vis = (out[:, :, 3] > 0) & (layer[:, :, 3] == 0)
        self.assertTrue(vis.any())
        self.assertTrue((out[vis][:, :3] == np.array(SHIRT[:3])).all())


class HaloOuterOnlyTests(SimpleTestCase):
    def test_outer_contour_eroded_hole_left_alone(self):
        img = np.zeros((60, 60, 4), np.uint8)
        img[10:50, 10:50] = (40, 30, 200, 255)
        img[25:35, 25:35, 3] = 0  # a real opening inside
        out = warp.remove_halo(img, outer_only=True)
        self.assertFalse(out[10:12, :, 3].any() or out[:, 10:12, 3].any())  # outer contour: 2 px gone
        np.testing.assert_array_equal(out[23:37, 23:37, 3], img[23:37, 23:37, 3])  # the hole's edge untouched


class DroppedShoulderTests(SimpleTestCase):
    """TRYON_DROPPED_SHOULDER_SINGLE: a dropped-shoulder T-shirt (#36-like) is warped as one piece."""

    def dropped(self):
        """Boxy T-shirt: flat top far out (x 90..210 of shoulders 70..230), sleeves hanging from the seam."""
        img = np.zeros((330, 300, 4), np.uint8)
        cv2.fillPoly(img, [np.array([(70, 36), (90, 30), (210, 30), (230, 36), (230, 320), (70, 320)], np.int32)], SHIRT)
        cv2.fillPoly(img, [np.array([(70, 36), (22, 60), (10, 130), (45, 140), (72, 110)], np.int32)], SHIRT)
        cv2.fillPoly(img, [np.array([(230, 36), (278, 60), (290, 130), (255, 140), (228, 110)], np.int32)], SHIRT)
        lm = {"shoulder": {"y": 36, "left_x": 70, "right_x": 230}, "chest": {"y": 110, "left_x": 72, "right_x": 228},
              "waist": {"y": 210, "left_x": 72, "right_x": 228}, "hem": {"y": 320, "left_x": 70, "right_x": 230},
              "sleeve_end": {"left": {"x": 26, "y": 136}, "right": {"x": 274, "y": 136}}}
        return img, lm

    def sloped(self):
        """Set-in sleeves: the top slopes down from a narrow collar (not dropped)."""
        g, glm = self.dropped()
        g[:, :, 3] = 0
        cv2.fillPoly(g, [np.array([(70, 50), (120, 26), (180, 26), (230, 50), (230, 320), (70, 320)], np.int32)], SHIRT)
        cv2.fillPoly(g, [np.array([(70, 50), (22, 70), (10, 130), (45, 140), (72, 110)], np.int32)], SHIRT)
        cv2.fillPoly(g, [np.array([(230, 50), (278, 70), (290, 130), (255, 140), (228, 110)], np.int32)], SHIRT)
        glm = {**glm, "shoulder": {"y": 50, "left_x": 70, "right_x": 230}}
        return g, glm

    def render(self, g, glm, flag=True):
        base, lm = avatar()
        rgb, _, dbg = warp.render_tryon(base, lm, [("tshirt", g, glm)], dropped_shoulder_single=flag)
        return rgb, dbg, lm

    def test_no_pixel_above_the_shoulder_line_outside_the_shoulder(self):
        g, glm = self.dropped()
        self.assertGreater(warp.dropped_shoulder_ratio(g[:, :, 3] > 128, glm), warp.DROPPED_SHOULDER_RATIO)
        _, dbg, lm = self.render(g, glm)
        self.assertTrue(dbg["dropped_shoulder"]["single"])
        a = dbg["tshirt_layer"][:, :, 3] > 128
        ys, xs = np.nonzero(a)
        for side in ("left", "right"):
            m, c = dbg["shoulder_lines"][side]
            sx = lm["shoulder"][f"{side}_x"]
            out = (xs < sx - 4) if side == "left" else (xs > sx + 4)
            above = (m * (xs + 0.5) + c) - (ys + 0.5) > 1
            self.assertEqual(int((out & above).sum()), 0, side)

    def test_no_tab_at_the_sleeve_inner_bottom_corner(self):
        g, glm = self.dropped()
        _, dbg, _ = self.render(g, glm)
        a = dbg["tshirt_layer"][:, :, 3] > 128
        rows = {int(round(y)): (l, r) for y, l, r in dbg["tshirt_rows"]}
        ys_known = np.array(sorted(rows))
        alpha = g[:, :, 3] > 128
        g_rows = [(glm[k]["y"], glm[k]["left_x"], glm[k]["right_x"]) for k in ("shoulder", "chest", "waist", "hem")]
        for side, corner in (("left", (72, 110)), ("right", (228, 110))):
            own, _ = warp.sleeve_regions(alpha, glm, side, g_rows)
            M = dbg["sleeve_transforms"][side]
            sleeve = cv2.warpAffine((own & alpha).astype(np.float32), M, (W, H)) >= 0.5
            cx, cy = (M @ np.array([corner[0], corner[1], 1.0])).round().astype(int)
            for y in range(cy - 4, cy + 4):
                yk = ys_known[np.argmin(np.abs(ys_known - y))]
                l, r = rows[yk]
                for x in range(cx - 4, cx + 4):
                    if a[y, x]:
                        self.assertTrue(l - 2 <= x <= r + 2 or sleeve[y, x], (side, x, y))

    def test_normal_shoulders_render_unchanged(self):
        g, glm = self.sloped()
        self.assertLess(warp.dropped_shoulder_ratio(g[:, :, 3] > 128, glm), warp.DROPPED_SHOULDER_RATIO)
        on, dbg, _ = self.render(g, glm, True)
        off, _, _ = self.render(g, glm, False)
        self.assertFalse(dbg["dropped_shoulder"]["single"])
        self.assertEqual(int((on != off).sum()), 0)



class HemRuleTests(SimpleTestCase):
    """TRYON_HEM_RULE: the T-shirt hem lands on hip + 0.35 x (crotch - hip), at most crotch - 10 px."""

    VARIANTS = ((640, 670), (600, 670), (620, 700), (560, 650), (640, 720), (655, 668))  # (hip, crotch); last: clamped

    def bottom(self, layer, lm):
        cx = int(lm["crotch"]["center_x"])
        rows = np.nonzero((layer[:, :, 3] > 128)[:, cx - 20:cx + 21].any(axis=1))[0]
        return int(rows.max())

    def test_hem_lands_on_the_body_hem_row_for_any_garment_length(self):
        self.assertAlmostEqual(warp.body_hem_y({"hip": {"y": 655}, "crotch": {"y": 668}}, 0.35, 10), 658)
        for name, hem in (("normal", 320), ("very long", 560), ("very short", 150)):
            g, glm = tshirt(hem_y=hem)
            for hip, crotch in self.VARIANTS:
                base, lm = avatar()
                lm["hip"]["y"], lm["crotch"]["y"] = hip, crotch
                _, _, dbg = warp.render_tryon(base, lm, [("tshirt", g, glm)], hem_rule=True)
                target = warp.body_hem_y(lm, 0.35, 10)
                got = self.bottom(dbg["tshirt_layer"], lm)
                self.assertLessEqual(abs(got - target), 3, (name, hip, crotch, got, target))
                self.assertLess(got, crotch, (name, hip, crotch))

    def test_flag_off_keeps_the_garment_length(self):
        g, glm = tshirt(hem_y=150)
        base, lm = avatar()
        _, _, dbg = warp.render_tryon(base, lm, [("tshirt", g, glm)], hem_rule=False)
        self.assertLess(self.bottom(dbg["tshirt_layer"], lm), warp.body_hem_y(lm, 0.35, 10) - 50)  # crop top stays short

    def test_pants_render_unchanged(self):
        base, lm = avatar()
        p, plm = pants()
        on, _, _ = warp.render_tryon(base, lm, [("pants", p, plm)], hem_rule=True)
        off, _, _ = warp.render_tryon(base, lm, [("pants", p, plm)], hem_rule=False)
        self.assertEqual(int((on != off).sum()), 0)
        g, glm = tshirt(hem_y=560)
        both, _, dbg = warp.render_tryon(base, lm, [("pants", p, plm), ("tshirt", g, glm)], hem_rule=True)
        y = int(warp.body_hem_y(lm, 0.35, 10)) + 6  # below the T-shirt: the pants exactly as drawn alone
        np.testing.assert_array_equal(both[y:], on[y:])
