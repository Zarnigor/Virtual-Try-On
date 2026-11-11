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


if __name__ == "__main__":
    unittest.main()
