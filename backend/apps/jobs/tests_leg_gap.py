"""Pants background clean-up between the legs (docs/09 #123): the model keeps the black photo background as fabric."""
import numpy as np
from django.test import SimpleTestCase

from .tasks import clear_background_between_legs

H, W = 400, 300


def white_pants_on_black(gap_closed_at_hem=False):
    rgb = np.zeros((H, W, 3), np.uint8)
    mask = np.zeros((H, W), np.uint8)
    rgb[20:200, 80:220] = 235  # waist block
    mask[20:200, 80:220] = 255
    for x0, x1 in ((80, 140), (160, 220)):  # two legs below the crotch row 200
        rgb[200:380, x0:x1] = 235
        mask[200:380, x0:x1] = 255
    # the model keeps the black wedge between the legs (rows 150..380) as foreground
    mask[150:380, 140:160] = 255
    if gap_closed_at_hem:
        rgb[370:380, 140:160] = 235
    return rgb, mask


class LegGapTests(SimpleTestCase):
    def test_black_gap_becomes_transparent_and_fabric_is_kept(self):
        rgb, mask = white_pants_on_black()
        out = clear_background_between_legs(rgb, mask)
        self.assertEqual(int((out[200:370, 145:155] > 128).sum()), 0)
        self.assertTrue((out[20:200, 85:215] == 255).all())  # fabric untouched
        self.assertTrue((out[210:370, 85:135] == 255).all())
        self.assertTrue((out <= mask).all())  # alpha only goes down, nothing is filled

    def test_dark_garment_on_black_is_untouched(self):
        rgb, mask = white_pants_on_black()
        rgb[mask > 0] = 25  # near-black pants: no contrast with the background
        self.assertTrue((clear_background_between_legs(rgb, mask) == mask).all())

    def test_black_print_inside_the_fabric_is_kept(self):
        rgb, mask = white_pants_on_black()
        rgb[60:100, 100:140] = 0  # a black patch on the waist block, not connected to the outside
        out = clear_background_between_legs(rgb, mask)
        self.assertTrue((out[60:100, 100:140] == 255).all())

    def test_no_background_border_returns_mask(self):
        rgb = np.full((H, W, 3), 235, np.uint8)
        mask = np.full((H, W), 255, np.uint8)
        self.assertTrue((clear_background_between_legs(rgb, mask) == mask).all())
