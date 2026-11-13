"""Owner-drawn neckline hole in the try-on (docs/09 #102): render_tryon wiring, flag, render-time validation, job result.

The pixel tests read testdata/tryon_neck/ (gitignored: real avatar photos), exported BEFORE the wiring by
tools/warp-benchmark/export_neck_hole_regression.py: render_tryon RGB for #28, #40, #43, #44, #45, #47 x 6 avatars x
(mls adapt, mls keep_shape, parts) with render_flags("avatar").
"""
import json
from pathlib import Path
from unittest import mock, skipUnless

import cv2
import numpy as np
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, override_settings

from apps.avatars.models import Avatar
from apps.garments.landmark_checks import engine_landmarks
from apps.garments.models import Garment
from apps.outfits.models import Outfit
from apps.testing import MediaTestCase
from apps.tryon_engine import tasks
from apps.tryon_engine.flags import render_flags
from apps.tryon_engine.warp import render_tryon

FIXTURE = Path(__file__).resolve().parent / "testdata" / "tryon_neck"
GARMENTS = ("28", "40", "43", "44", "45", "47")
WITH_POLYGON = ("28", "40", "47")
AVATARS = range(1, 7)
BAD = [[200, 40], [300, 60], [300, 40], [200, 60]]  # bow tie: self-intersecting


def _fixture():
    av = {pk: (cv2.imread(str(FIXTURE / "avatars" / f"{pk}.png"), cv2.IMREAD_UNCHANGED),
               json.loads((FIXTURE / "avatars" / f"{pk}.json").read_text())) for pk in AVATARS}
    gm = {gid: (cv2.imread(str(FIXTURE / "garments" / f"{gid}.png"), cv2.IMREAD_UNCHANGED),
                json.loads((FIXTURE / "garments" / f"{gid}.json").read_text())) for gid in GARMENTS}
    polys = {gid: json.loads((FIXTURE / "polygons" / f"{gid}.json").read_text())["polygon"] for gid in WITH_POLYGON}
    return av, gm, polys


def _render(base, blm, g, glm, mode="adapt", engine="mls", **over):
    flags = {**render_flags("avatar"), "warp_engine": engine, **over}
    return render_tryon(base, blm, [("tshirt", g, engine_landmarks("tshirt", glm))], 1200, 600,
                        fit_modes={"tshirt": mode}, **flags)


def _want(engine, mode, gid, pk):
    return cv2.imread(str(FIXTURE / "expected" / f"{engine}_{mode}_{gid}_{pk}.png"), cv2.IMREAD_UNCHANGED)


@skipUnless((FIXTURE / "expected").is_dir(),
            "tryon_neck fixture missing (real avatars, not in git): run "
            "tools/warp-benchmark/export_neck_hole_regression.py on the code before the neck-hole wiring")
class NeckHoleRegressionTests(SimpleTestCase):
    """Nothing changes without a (used) polygon: 0 px against the pre-wiring export."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.av, cls.gm, cls.polys = _fixture()

    def _diff(self, got, want):
        return int((got != want).any(2).sum())

    def test_no_polygon_is_pixel_identical(self):  # 6 garments x 6 avatars x (mls adapt, mls keep_shape, parts)
        n = 0
        for gid in GARMENTS:
            g, glm = self.gm[gid]
            for pk in AVATARS:
                base, blm = self.av[pk]
                for engine, mode in (("mls", "adapt"), ("mls", "keep_shape"), ("parts", "adapt")):
                    with self.subTest(garment=gid, avatar=pk, engine=engine, mode=mode):
                        rgb, _, dbg = _render(base, blm, g, glm, mode, engine)
                        self.assertEqual(self._diff(rgb, _want(engine, mode, gid, pk)), 0)
                        self.assertFalse(dbg["neck_hole"])
                        n += 1
        self.assertEqual(n, 108)

    def test_polygon_is_ignored_by_keep_shape_parts_and_the_flag(self):
        for gid in WITH_POLYGON:
            g, glm = self.gm[gid]
            lm = {**glm, "neck_hole": {"polygon": self.polys[gid]}}
            for pk in AVATARS:
                base, blm = self.av[pk]
                for engine, mode, over in (("mls", "keep_shape", {}), ("parts", "adapt", {}),
                                           ("mls", "adapt", {"neck_hole": False})):
                    with self.subTest(garment=gid, avatar=pk, engine=engine, mode=mode, **over):
                        rgb, _, dbg = _render(base, blm, g, lm, mode, engine, **over)
                        self.assertEqual(self._diff(rgb, _want(engine, mode, gid, pk)), 0)
                        self.assertFalse(dbg["neck_hole"])

    def test_invalid_polygon_is_dropped_with_a_warning(self):
        g, glm = self.gm["28"]
        for poly in (BAD, [[10, 10], [20, 10]], [[100, 300], [200, 300], [150, 380]]):  # self / points / below 40 %
            for pk in (1, 4):
                base, blm = self.av[pk]
                with self.subTest(poly=poly, avatar=pk):
                    rgb, _, dbg = _render(base, blm, g, {**glm, "neck_hole": {"polygon": poly}})
                    self.assertIn("neck_hole_invalid", dbg["quality_warnings"])
                    self.assertFalse(dbg["neck_hole"])
                    self.assertEqual(dbg["engine"], "mls")  # no fallback to parts
                    self.assertEqual(self._diff(rgb, _want("mls", "adapt", "28", pk)), 0)

    def test_40_with_owner_polygon_v2_on_6_avatars(self):
        """docs/09 #101: fabric left in the warped hole <= 5 px, band px removed 0, changes outside the neck zone 0."""
        g, glm = self.gm["40"]
        lm = {**glm, "neck_hole": {"polygon": self.polys["40"]}}
        for pk in AVATARS:
            base, blm = self.av[pk]
            with self.subTest(avatar=pk):
                on_rgb, _, on = _render(base, blm, g, lm)
                off_rgb, _, off = _render(base, blm, g, glm)
                self.assertTrue(on["neck_hole"])
                self.assertEqual(on["mls"]["neckline"]["variant"], "hole")
                w = on["mls"]["neck_weight"]
                a_on, a_off = on["tshirt_layer"][:, :, 3], off["tshirt_layer"][:, :, 3]
                fabric = int(((a_on >= 128) & (w >= 0.5)).sum())
                band = int(((a_off >= 128) & (a_on < 128) & (w < 0.5)).sum())
                zone = cv2.dilate((w > 0).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
                outside = int(((on_rgb != off_rgb).any(2) & ~zone).sum())
                self.assertLessEqual(fabric, 5)
                self.assertEqual(band, 0)
                self.assertEqual(outside, 0)
                self.assertGreater(int((on_rgb != off_rgb).any(2).sum()), 0)  # the hole did change the neck

    def test_hole_keywords_and_never_neck_clip(self):
        g, glm = self.gm["47"]
        base, blm = self.av[1]
        from apps.tryon_engine import mls
        real = mls.tshirt_layer
        with mock.patch("apps.tryon_engine.mls.tshirt_layer", side_effect=real) as layer:
            _render(base, blm, g, {**glm, "neck_hole": {"polygon": self.polys["47"]}})
            _render(base, blm, g, glm)
        with_poly, without = layer.call_args_list
        self.assertEqual(with_poly.kwargs["neckline_variant"], "hole")
        self.assertEqual(with_poly.kwargs["neck_hole_polygon"], self.polys["47"])
        self.assertNotIn("neck_clip", with_poly.kwargs)
        self.assertEqual(without.kwargs, {})  # called exactly as before


@skipUnless((FIXTURE / "expected").is_dir(), "tryon_neck fixture missing (see NeckHoleRegressionTests)")
class NeckHoleTaskTests(MediaTestCase):
    """The worker path: job result neck_hole per garment, quality warning neck_hole_invalid."""

    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.avatar = Avatar(sex="male", build="average",
                             landmarks=json.loads((FIXTURE / "avatars" / "2.json").read_text()))
        self.avatar.image.save("a.png", ContentFile((FIXTURE / "avatars" / "2.png").read_bytes()), save=True)

    def _outfit(self, poly):
        lm = json.loads((FIXTURE / "garments" / "40.json").read_text())
        if poly is not None:
            lm["neck_hole"] = {"polygon": poly}
        g = Garment(owner=self.user, type="tshirt", landmarks=lm, fit_mode="adapt", gender="unisex")
        g.image.save("g.png", ContentFile((FIXTURE / "garments" / "40.png").read_bytes()), save=True)
        outfit = Outfit.objects.create(user=self.user, avatar=self.avatar)
        outfit.garments.add(g)
        return Outfit.objects.get(pk=outfit.pk), str(g.pk)

    @override_settings(TRYON_WARP="mls")
    def test_job_result_reports_the_hole(self):
        poly = json.loads((FIXTURE / "polygons" / "40.json").read_text())["polygon"]
        outfit, gid = self._outfit(poly)
        self.assertEqual(tasks._do_warp(outfit), {"engine": "mls", "quality_warnings": [], "neck_hole": {gid: True}})
        outfit, gid = self._outfit(BAD)
        self.assertEqual(tasks._do_warp(outfit),
                         {"engine": "mls", "quality_warnings": ["neck_hole_invalid"], "neck_hole": {gid: False}})

    @override_settings(TRYON_WARP="mls", TRYON_NECK_HOLE=False)
    def test_flag_off(self):
        poly = json.loads((FIXTURE / "polygons" / "40.json").read_text())["polygon"]
        outfit, gid = self._outfit(poly)
        self.assertEqual(tasks._do_warp(outfit), {"engine": "mls", "quality_warnings": [], "neck_hole": {gid: False}})

    @override_settings(TRYON_WARP="parts")
    def test_parts_ignores_it(self):
        poly = json.loads((FIXTURE / "polygons" / "40.json").read_text())["polygon"]
        outfit, gid = self._outfit(poly)
        self.assertEqual(tasks._do_warp(outfit), {"engine": "parts", "quality_warnings": [], "neck_hole": {gid: False}})
