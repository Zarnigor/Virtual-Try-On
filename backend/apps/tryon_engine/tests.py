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
