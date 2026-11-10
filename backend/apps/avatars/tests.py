"""Avatar prep: file name mapping, normalization without stretching, initial landmarks from the mask."""
from unittest import mock

import cv2
import numpy as np
from django.test import SimpleTestCase
from PIL import Image

from apps.avatars import prep
from apps.avatars.management.commands.seed_avatars import map_name
from apps.tryon_engine.tests import avatar


class NameMappingTests(SimpleTestCase):
    def test_aliases(self):
        self.assertEqual(map_name("man_slim"), ("male", "slim"))
        self.assertEqual(map_name("male_plus_size"), ("male", "plus"))
        self.assertEqual(map_name("woman_average"), ("female", "average"))
        self.assertEqual(map_name("Female-Plus"), ("female", "plus"))

    def test_ambiguous_or_unknown_names_are_rejected(self):
        for stem in ("slim", "man", "man_woman_slim", "male_slim_average", "photo1"):
            self.assertIsNone(map_name(stem), stem)


def landscape_photo(fig_w, fig_h, left_arm=0):
    """2000x1500 grey photo with a figure (head, torso, legs, optional long left arm) and its mask."""
    W, H = 2000, 1500
    img = np.full((H, W, 3), 225, np.uint8)
    m = np.zeros((H, W), np.uint8)
    x0, y0 = 1000 - fig_w // 2, (H - fig_h) // 2
    for target in (img, m):
        col = (80, 90, 100) if target is img else 255
        cv2.rectangle(target, (x0, y0), (x0 + fig_w, y0 + fig_h), col, -1)
        if left_arm:
            cv2.rectangle(target, (x0 - left_arm, y0 + fig_h // 4), (x0, y0 + fig_h // 4 + 40), col, -1)
    return Image.fromarray(img), Image.fromarray(m)


class NormalizeTests(SimpleTestCase):
    def run_normalize(self, photo, mask):
        with mock.patch("rembg.remove", return_value=mask), mock.patch("rembg.new_session"):
            return prep.normalize(photo, session=object())

    def test_landscape_photo_is_scaled_uniformly_and_padded(self):
        photo, mask = landscape_photo(300, 1000)
        n = self.run_normalize(photo, mask)
        self.assertEqual(n.image.size, (600, 1200))
        ys, xs = np.nonzero(n.mask)
        self.assertEqual((ys.min(), ys.max() + 1), (50, 1150))  # figure y 50..1150
        self.assertAlmostEqual((xs.min() + xs.max() + 1) / 2, 300, delta=1)  # axis x = 300
        w, h = xs.max() + 1 - xs.min(), ys.max() + 1 - ys.min()
        self.assertAlmostEqual(w / h, 300 / 1000, delta=0.005)  # never stretched
        self.assertTrue((np.array(n.image)[0, 0] == 0).all())  # transparent background

    def test_wide_arms_shrink_the_figure_instead_of_clipping(self):
        photo, mask = landscape_photo(300, 1000, left_arm=500)  # widest half from the axis: 650 px
        n = self.run_normalize(photo, mask)
        ys, xs = np.nonzero(n.mask)
        self.assertGreaterEqual(xs.min(), prep.MARGIN - 1)
        self.assertLess(ys.max() + 1 - ys.min(), 1100)  # width-limited scale
        self.assertEqual(ys.min(), 50)

    def test_empty_mask_fails_loudly(self):
        photo, _ = landscape_photo(300, 1000)
        with self.assertRaises(prep.NormalizeError):
            self.run_normalize(photo, Image.new("L", photo.size, 0))


class DetectTests(SimpleTestCase):
    def test_landmarks_from_a_synthetic_figure(self):
        img, ref = avatar()
        mask = img[:, :, 3] > 128
        gray = np.where(mask, 150, 255).astype(np.uint8)
        lm = prep.detect_landmarks(mask, gray)
        ys = [lm[k]["y"] for k in prep.ORDER]
        self.assertEqual(ys, sorted(ys))
        self.assertAlmostEqual(lm["crotch"]["y"], 671, delta=3)  # the torso polygon ends at y 670, legs split below
        self.assertAlmostEqual(lm["waist"]["left_x"], ref["waist"]["left_x"], delta=6)
        for leg in ("left_leg", "right_leg"):
            self.assertLess(lm["ankle"][leg]["width"], lm["knee"][leg]["width"])
