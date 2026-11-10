"""Lighting flattening of near-solid garments (apps/garments/lighting.py)."""
import cv2
import numpy as np
from django.test import SimpleTestCase

from apps.garments import lighting


def garment(fill):
    img = np.zeros((320, 220, 4), np.uint8)
    cv2.rectangle(img, (10, 10), (209, 309), (255, 255, 255, 255), -1)
    inside = img[:, :, 3] > 0
    ys = np.arange(320)[:, None].repeat(220, axis=1)
    xs = np.arange(220)[None, :].repeat(320, axis=0)
    img[:, :, :3][inside] = fill(ys, xs)[inside]
    return img


def luma(img):
    m = img[:, :, 3] >= 250
    return cv2.cvtColor(np.ascontiguousarray(img[:, :, :3]), cv2.COLOR_RGB2GRAY)[m].astype(float)


class FlattenTests(SimpleTestCase):
    def test_solid_garment_with_a_vertical_gradient_is_flattened(self):
        base = np.array([40, 90, 170], float)  # one blue, lit from above
        img = garment(lambda ys, xs: np.clip(base[None, None] * (0.6 + 0.8 * ys[..., None] / 320), 0, 255)
                      .astype(np.uint8))
        self.assertTrue(lighting.is_near_solid(img))
        out = lighting.flatten_lighting(img)
        before, after = np.ptp(luma(img)), np.ptp(luma(out))
        self.assertLessEqual(after, 0.3 * before, (before, after))
        np.testing.assert_array_equal(out[:, :, 3], img[:, :, 3])

    def test_high_frequency_texture_is_kept(self):
        img = garment(lambda ys, xs: np.where(((ys // 40) % 2 == 0)[..., None] & (xs % 50 == 0)[..., None],
                                              np.uint8(90), np.uint8(110)) * np.ones((1, 1, 3), np.uint8))
        out = lighting.flatten_lighting(img)
        self.assertLess(out[100, 50, 0], out[100, 52, 0])  # a stitch line stays darker than its neighbour

    def test_two_colour_garment_is_unchanged(self):
        img = garment(lambda ys, xs: np.where((xs < 110)[..., None], np.array([200, 30, 30], np.uint8),
                                              np.array([30, 30, 200], np.uint8)))
        self.assertFalse(lighting.is_near_solid(img))
        np.testing.assert_array_equal(lighting.flatten_lighting(img), img)

    def test_printed_garment_is_unchanged(self):
        rng = np.random.default_rng(0)
        noise = rng.integers(0, 2, (320, 220))[..., None] * 120 + 60  # black/grey print, same hue
        img = garment(lambda ys, xs: (noise * np.ones((1, 1, 3))).astype(np.uint8))
        np.testing.assert_array_equal(lighting.flatten_lighting(img), img)
