"""Lighting flattening of near-solid garments (apps/garments/lighting.py)."""
from io import StringIO

import cv2
import numpy as np
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import SimpleTestCase

from apps.garments import lighting
from apps.garments.models import Garment
from apps.testing import MediaTestCase


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


def solid_black(ys, xs):
    """Black T-shirt lit from above, with a fine knit texture."""
    rng = np.random.default_rng(3)
    v = 18 + 40 * ys / 320 + rng.normal(0, 3, ys.shape)
    return np.clip(v, 0, 255)[..., None].repeat(3, axis=2).astype(np.uint8)


class TextureThresholdTests(SimpleTestCase):
    """The three kinds of garment the thresholds were chosen for (docs/09 #68)."""

    def test_solid_with_gradient_is_flattened(self):
        img = garment(solid_black)
        m = lighting.texture_measures(img)
        self.assertLess(m["hf_std"], lighting.MAX_DETAIL_STD)
        self.assertTrue(lighting.is_near_solid(img), m)

    def test_solid_with_small_text_is_kept(self):
        img = garment(solid_black)
        for i, word in enumerate(("TRYON", "STUDIO")):  # small chest text, ~3 % of the area
            cv2.putText(img, word, (55, 90 + 28 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (235, 235, 235, 255), 2)
        m = lighting.texture_measures(img)
        self.assertGreater(m["hf_frac"], lighting.MAX_DETAIL_FRAC)
        self.assertFalse(lighting.is_near_solid(img), m)
        np.testing.assert_array_equal(lighting.flatten_lighting(img), img)

    def test_solid_with_large_print_is_kept(self):
        img = garment(solid_black)
        cv2.circle(img, (110, 150), 70, (230, 230, 230, 255), -1)  # big white print on the chest
        cv2.circle(img, (110, 150), 40, (25, 25, 25, 255), 8)
        self.assertFalse(lighting.is_near_solid(img), lighting.texture_measures(img))
        np.testing.assert_array_equal(lighting.flatten_lighting(img), img)


class ReflattenCommandTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()

    def make(self, img):
        g = Garment(owner=self.user, type="tshirt", landmarks={})
        g.image.save("g.png", ContentFile(cv2.imencode(".png", cv2.cvtColor(img, cv2.COLOR_RGBA2BGRA))[1].tobytes()),
                     save=True)
        return g

    def run_cmd(self, *args):
        out = StringIO()
        call_command("reflatten_garments", *args, stdout=out)
        return out.getvalue()

    def pixels(self, g):
        g.refresh_from_db()
        return cv2.imread(g.image.path, cv2.IMREAD_UNCHANGED)

    def test_flattens_solid_once_and_never_touches_prints(self):
        solid = self.make(garment(solid_black))
        printed_img = garment(solid_black)
        cv2.circle(printed_img, (110, 150), 70, (230, 230, 230, 255), -1)
        printed = self.make(printed_img)
        before_print = self.pixels(printed).copy()

        out = self.run_cmd("--all-solid", "--dry-run")
        self.assertIn(f"{solid.pk} tshirt: hf_std", out)
        self.assertIn("would flatten", out)
        solid.refresh_from_db()
        self.assertFalse(solid.lighting_flattened)

        self.run_cmd("--ids", str(solid.pk), str(printed.pk))
        solid.refresh_from_db()
        self.assertTrue(solid.lighting_flattened)
        first = self.pixels(solid).copy()
        np.testing.assert_array_equal(self.pixels(printed), before_print)
        printed.refresh_from_db()
        self.assertFalse(printed.lighting_flattened)

        out = self.run_cmd("--all-solid")  # idempotent
        self.assertIn(f"{solid.pk}: already flattened, skip", out)
        np.testing.assert_array_equal(self.pixels(solid), first)
