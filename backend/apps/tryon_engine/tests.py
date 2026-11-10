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
        rgb, _, _ = warp.render_tryon(base, lm, [("tshirt", g, glm)])
        red = ((rgb[:, :, 2] > 150) & (rgb[:, :, 1] < 90) & (rgb[:, :, 0] < 90)).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(red, connectivity=8)
        lines = [stats[i] for i in range(1, n) if stats[i][cv2.CC_STAT_AREA] >= 8]
        for half in ("left", "right"):
            mine = [st for st in lines if (st[cv2.CC_STAT_LEFT] < 300) == (half == "left")]
            self.assertEqual(len(mine), 2, (half, [tuple(st) for st in mine]))  # one cuff + one upper stitch


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
        self.assertEqual(warp.LAYER_ORDER, ("avatar", "pants", "shoulder_cap", "tshirt_torso", "tshirt_sleeves",
                                            "head_neck", "hands_forearms"))
