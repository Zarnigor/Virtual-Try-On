"""TRYON_WARP = parts | mls (docs/09 #98): flag parsing, engine selection, fallback, fit_mode -> k, output size."""
import json
from pathlib import Path
from unittest import mock, skipUnless

import cv2
import numpy as np
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, override_settings

from apps.avatars.models import Avatar
from apps.garments.landmark_checks import engine_landmarks
from apps.garments.models import Garment
from apps.outfits.models import Outfit
from apps.testing import MediaTestCase
from apps.tryon_engine import mls, tasks, warp
from apps.tryon_engine.flags import render_flags
from apps.tryon_engine.tests import avatar as synthetic_avatar
from tryon_studio.settings.base import parse_tryon_warp

SHIRT = (40, 160, 40, 255)


def body():
    base, lm = synthetic_avatar()
    lm["armpit"].update(left_x=215, right_x=385)  # edge points, as a marked avatar has them
    return base, lm


def shirt(complete=True):
    """V-neck T-shirt with the full landmark set (docs/09 #92), 400 x 440, body-like proportions."""
    img = np.zeros((440, 400, 4), np.uint8)
    cv2.fillPoly(img, [np.array([(120, 30), (175, 30), (200, 60), (225, 30), (280, 30), (280, 420), (120, 420)],
                                np.int32)], SHIRT)
    cv2.fillPoly(img, [np.array([(120, 30), (58, 125), (90, 150), (120, 115)], np.int32)], SHIRT)
    cv2.fillPoly(img, [np.array([(280, 30), (342, 125), (310, 150), (280, 115)], np.int32)], SHIRT)
    lm = {"collar": {"y": 30, "left_x": 175, "right_x": 225}, "collar_bottom": {"x": 200, "y": 60},
          "shoulder": {"y": 30, "left_x": 120, "right_x": 280}, "armpit": {"y": 115, "left_x": 120, "right_x": 280},
          "chest": {"y": 150, "left_x": 120, "right_x": 280}, "waist": {"y": 250, "left_x": 120, "right_x": 280},
          "hem": {"y": 420, "left_x": 120, "right_x": 280},
          "sleeve_cuff_outer": {"left": {"x": 58, "y": 125}, "right": {"x": 342, "y": 125}},
          "sleeve_cuff_inner": {"left": {"x": 90, "y": 150}, "right": {"x": 310, "y": 150}}}
    if not complete:
        del lm["collar"]
    return img, lm


class FlagTests(SimpleTestCase):
    def test_default_is_parts_and_invalid_fails(self):
        self.assertEqual(parse_tryon_warp(None), "parts")
        self.assertEqual(parse_tryon_warp(""), "parts")
        self.assertEqual(parse_tryon_warp(" MLS "), "mls")
        for bad in ("mesh", "1", "part"):
            with self.assertRaises(ImproperlyConfigured):
                parse_tryon_warp(bad)

    def test_flag_reaches_render_flags(self):
        with override_settings(TRYON_WARP="parts"):
            self.assertEqual(render_flags("avatar")["warp_engine"], "parts")
        with override_settings(TRYON_WARP="mls"):
            self.assertEqual(render_flags("body")["warp_engine"], "mls")

    def test_render_rejects_an_unknown_engine(self):
        base, lm = body()
        with self.assertRaises(ValueError):
            warp.render_tryon(base, lm, [], warp_engine="mesh")


def eng(glm):
    """What the try-on task hands to render_tryon (adds sleeve_end for the parts engine; MLS ignores it)."""
    return engine_landmarks("tshirt", glm)


class EngineTests(SimpleTestCase):
    def test_parts_is_the_default_and_ignores_fit_mode(self):
        base, lm = body()
        g, glm = shirt()
        rgb, _, dbg = warp.render_tryon(base, lm, [("tshirt", g, eng(glm))], fit_modes={"tshirt": "keep_shape"})
        self.assertEqual(dbg["engine"], "parts")
        self.assertEqual(rgb.shape, (1200, 600, 3))

    def test_mls_selected_for_a_complete_tshirt(self):
        base, lm = body()
        g, glm = shirt()
        rgb, _, dbg = warp.render_tryon(base, lm, [("tshirt", g, eng(glm))], warp_engine="mls")
        self.assertEqual((dbg["engine"], dbg["quality_warnings"]), ("mls", []))
        self.assertEqual(rgb.shape, (1200, 600, 3))
        parts, _, _ = warp.render_tryon(base, lm, [("tshirt", g, eng(glm))])
        self.assertFalse((rgb == parts).all())

    def test_incomplete_landmarks_fall_back_with_a_warning(self):
        base, lm = body()
        g, glm = shirt(complete=False)
        rgb, warns, dbg = warp.render_tryon(base, lm, [("tshirt", g, eng(glm))], warp_engine="mls")
        self.assertEqual((dbg["engine"], dbg["quality_warnings"]), ("parts", ["mls_fallback"]))
        self.assertTrue(any("mls fallback" in w for w in warns))
        parts, _, _ = warp.render_tryon(base, lm, [("tshirt", g, eng(glm))])
        np.testing.assert_array_equal(rgb, parts)  # exactly the parts result

    def test_failed_pair_validation_falls_back(self):
        base, lm = body()
        g, glm = shirt()
        glm["waist"].update(left_x=300, right_x=100)  # left/right swapped: the waist pairs are rejected
        _, _, dbg = warp.render_tryon(base, lm, [("tshirt", g, eng(glm))], warp_engine="mls")
        self.assertEqual((dbg["engine"], dbg["quality_warnings"]), ("parts", ["mls_fallback"]))

    def test_fit_mode_maps_to_k(self):
        self.assertEqual(mls.k_map_for("keep_shape"), mls.PRESET_A)
        self.assertEqual(mls.k_of(mls.k_map_for("keep_shape"), "shoulder"), (0.5, 1.0))
        self.assertEqual({mls.k_of(mls.k_map_for("adapt"), g) for g in ("neck", "shoulder", "armpit", "chest", "waist",
                                                                         "hem", "cuff")}, {(1.0, 1.0)})
        base, lm = body()
        g, glm = shirt()
        out = {}
        for mode in ("adapt", "keep_shape"):
            rgb, _, dbg = warp.render_tryon(base, lm, [("tshirt", g, eng(glm))], fit_modes={"tshirt": mode},
                                            warp_engine="mls")
            self.assertEqual((dbg["mls"]["fit_mode"], rgb.shape), (mode, (1200, 600, 3)))
            out[mode] = (rgb, dbg["mls"]["pairs"])
        self.assertIn("hem_c", out["adapt"][1])  # the fitted targets
        self.assertNotIn("hem_c", out["keep_shape"][1])  # preset A: no fitted retargeting
        self.assertFalse((out["adapt"][0] == out["keep_shape"][0]).all())

    def test_chest_above_armpit_is_not_used_in_keep_shape(self):
        base, lm = body()
        g, glm = shirt()
        glm["chest"]["y"] = 100  # above the armpit (115): oversized marking
        _, _, dbg = warp.render_tryon(base, lm, [("tshirt", g, eng(glm))], fit_modes={"tshirt": "keep_shape"},
                                      warp_engine="mls")
        self.assertEqual(dbg["engine"], "mls")
        self.assertNotIn("chest_l", dbg["mls"]["pairs"])
        self.assertIn("chest_l", dbg["mls"]["rejected"])

    def test_pants_are_untouched(self):
        from apps.tryon_engine.tests import pants
        base, lm = body()
        p, plm = pants()
        a, _, da = warp.render_tryon(base, lm, [("pants", p, plm)])
        b, _, db = warp.render_tryon(base, lm, [("pants", p, plm)], warp_engine="mls")
        np.testing.assert_array_equal(a, b)
        self.assertEqual((da["engine"], db["engine"]), ("parts", "parts"))


class TaskTests(MediaTestCase):
    """The worker path: the job result carries the engine and quality_warnings; the image is 600 x 1200."""

    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        base, lm = body()
        _, buf = cv2.imencode(".png", base)
        self.avatar = Avatar(sex="male", build="average", landmarks=lm)
        self.avatar.image.save("a.png", ContentFile(buf.tobytes()), save=True)

    def _outfit(self, complete=True, fit_mode="adapt"):
        g_img, g_lm = shirt(complete)
        _, buf = cv2.imencode(".png", g_img)
        g = Garment(owner=self.user, type="tshirt", landmarks=g_lm, fit_mode=fit_mode)
        g.image.save("g.png", ContentFile(buf.tobytes()), save=True)
        outfit = Outfit.objects.create(user=self.user, avatar=self.avatar)
        outfit.garments.add(g)
        return Outfit.objects.get(pk=outfit.pk)

    def _result_shape(self, outfit):
        outfit.refresh_from_db()
        img = cv2.imdecode(np.frombuffer(outfit.result_image.read(), np.uint8), cv2.IMREAD_UNCHANGED)
        return img.shape[:2]

    @override_settings(TRYON_WARP="mls")
    def test_mls_complete_tshirt(self):
        for mode in ("adapt", "keep_shape"):
            outfit = self._outfit(fit_mode=mode)
            gid = str(outfit.garments.get().pk)
            self.assertEqual(tasks._do_warp(outfit), {"engine": "mls", "quality_warnings": [], "neck_hole": {gid: False}})
            self.assertEqual(self._result_shape(outfit), (1200, 600))

    @override_settings(TRYON_WARP="mls")
    def test_incomplete_landmarks_fall_back(self):
        outfit = self._outfit(complete=False)
        with mock.patch("apps.tryon_engine.mls.tshirt_layer") as layer:
            report = tasks._do_warp(outfit)
        layer.assert_not_called()  # mls_ready is false: MLS is not attempted
        self.assertEqual(report, {"engine": "parts", "quality_warnings": ["mls_fallback"],
                                  "neck_hole": {str(outfit.garments.get().pk): False}})
        self.assertEqual(self._result_shape(outfit), (1200, 600))

    @override_settings(TRYON_WARP="parts")
    def test_parts_default(self):
        outfit = self._outfit()
        self.assertEqual(tasks._do_warp(outfit), {"engine": "parts", "quality_warnings": [],
                                                  "neck_hole": {str(outfit.garments.get().pk): False}})

    @mock.patch("apps.tryon_engine.views.run_tryon.delay")
    def test_response_names_the_engine(self, _):
        self.login(self.user)
        g = self._outfit().garments.first()
        for flag in ("mls", "parts"):
            with override_settings(TRYON_WARP=flag):
                r = self.client.post("/api/tryon/", {"base": "avatar", "avatar_id": self.avatar.id,
                                                     "garment_ids": [g.id]}, format="json")
            self.assertEqual((r.status_code, r.data["engine"]), (202, flag))


def _layer(variant=None, **kw):
    base, lm = body()
    g, glm = shirt()
    mask = warp.figure_mask(cv2.resize(warp._bgra(base), (600, 1200)))
    extra = {} if variant is None else {"sleeve_variant": variant}
    layer, info = mls.tshirt_layer(g, glm, lm, mask, "adapt", **extra, **kw)
    return layer, info, mask, lm


class SleeveVariantTests(SimpleTestCase):
    """Benchmark round 8 (docs/06): sleeve_variant r7 | A | B | C, keyword only, default r7."""

    def test_default_is_r7_and_unknown_is_an_error(self):
        a, ia, _, _ = _layer()
        b, ib, _, _ = _layer("r7")
        np.testing.assert_array_equal(a, b)
        self.assertEqual(ia["pairs"], ib["pairs"])
        with self.assertRaises(ValueError):  # never a silent fallback to parts
            _layer("D")

    def test_render_tryon_passes_the_setting_default_c(self):  # docs/09 #104
        base, lm = body()
        g, glm = shirt()
        with mock.patch("apps.tryon_engine.mls.tshirt_layer", wraps=mls.tshirt_layer) as spy:
            warp.render_tryon(base, lm, [("tshirt", g, eng(glm))], warp_engine="mls")
            self.assertEqual(spy.call_args.kwargs["sleeve_variant"], "C")
            warp.render_tryon(base, lm, [("tshirt", g, eng(glm))], warp_engine="mls", mls_sleeve="r7")
            self.assertEqual(spy.call_args.kwargs["sleeve_variant"], "r7")
        self.assertEqual(render_flags("avatar")["mls_sleeve"], "C")
        with override_settings(TRYON_MLS_SLEEVE="B"):
            self.assertEqual(render_flags("avatar")["mls_sleeve"], "B")

    def test_setting_is_validated(self):
        from tryon_studio.settings.base import parse_mls_sleeve
        self.assertEqual(parse_mls_sleeve(None), "C")
        self.assertEqual(parse_mls_sleeve(" r7 "), "r7")
        with self.assertRaises(ImproperlyConfigured):
            parse_mls_sleeve("D")

    def test_c_in_render_tryon_equals_the_layer_and_keep_shape_ignores_it(self):
        base, lm = body()
        g, glm = shirt()
        mask = warp.figure_mask(cv2.resize(warp._bgra(base), (600, 1200)))
        _, _, dbg = warp.render_tryon(base, lm, [("tshirt", g, eng(glm))], warp_engine="mls")
        layer, _ = mls.tshirt_layer(g, eng(glm), lm, mask, "adapt", 1200, 600, sleeve_variant="C")
        np.testing.assert_array_equal(dbg["tshirt_layer"], layer)
        a, _ = mls.tshirt_layer(g, glm, lm, mask, "keep_shape", sleeve_variant="C")
        b, _ = mls.tshirt_layer(g, glm, lm, mask, "keep_shape", sleeve_variant="r7")
        np.testing.assert_array_equal(a, b)

    def test_a_has_no_mid_sleeve_pairs(self):
        _, r7, _, _ = _layer("r7")
        _, a, _, _ = _layer("A")
        self.assertIn("smid_out_l", r7["pairs"])
        self.assertFalse([k for k in a["pairs"] if k.startswith("smid")])
        self.assertEqual({k: v for k, v in r7["pairs"].items() if not k.startswith("smid")}, a["pairs"])

    def test_b_moves_smid_out_to_the_outer_edge_only(self):
        _, r7, _, _ = _layer("r7")
        _, b, mask, _ = _layer("B")
        for sx, side, out in (("_l", "left", -1), ("_r", "right", 1)):
            p = b["pairs"]["smid_out" + sx][1]
            edge = mls._outer_edge_x(mask, p[1], side)
            self.assertIsNotNone(edge)
            self.assertLessEqual(abs(p[0] - edge), 6)  # the edge + a small CUFF_ARM_EASE share, never the centre line
            self.assertGreaterEqual((p[0] - edge) * out, -1)  # outward of (or on) the deltoid edge
            self.assertEqual(b["pairs"]["smid_in" + sx], r7["pairs"]["smid_in" + sx])
        same = lambda pr: {k: v for k, v in pr.items() if not k.startswith("smid_out")}  # noqa: E731
        self.assertEqual(same(r7["pairs"]), same(b["pairs"]))

    def test_c_adds_a_valid_cuff_mid_pair(self):
        _, b, _, _ = _layer("B")
        _, c, _, _ = _layer("C")
        for sx in ("_l", "_r"):
            q, p, w = c["pairs"]["cuff_mid" + sx]
            o, i = c["pairs"]["cuff_out" + sx], c["pairs"]["cuff_in" + sx]
            for j, pt in ((0, q), (1, p)):
                self.assertLess(min(o[j][0], i[j][0]), pt[0])
                self.assertLess(pt[0], max(o[j][0], i[j][0]))
                np.testing.assert_allclose(pt, (np.array(o[j]) + np.array(i[j])) / 2)
            self.assertFalse(mls._order_flips(c["pairs"], "armpit" + sx, "cuff_mid" + sx))
        self.assertEqual({k: v for k, v in c["pairs"].items() if not k.startswith("cuff_mid")}, b["pairs"])

    def test_cuff_mid_dropped_when_it_crosses_the_armpit_or_is_degenerate(self):
        pairs = {"armpit_l": ((100, 100), (200, 200), 1.0),
                 "cuff_out_l": ((60, 140), (190, 260), 1.0), "cuff_in_l": ((120, 150), (230, 270), 1.0),
                 "cuff_out_r": ((300, 140), (400, 260), 1.0), "cuff_in_r": ((301, 140), (400.5, 260), 1.0)}
        rejected = []
        mls._add_cuff_mid(pairs, rejected)  # left: garment mid 90 < armpit 100, body mid 210 > 200 -> crossing
        self.assertEqual(sorted(rejected), ["cuff_mid_l", "cuff_mid_r"])  # right: corners < 2 px apart
        self.assertFalse([k for k in pairs if k.startswith("cuff_mid")])

    def test_runtime_and_debug_map(self):
        for v in mls.SLEEVE_VARIANTS:
            layer, info, _, _ = _layer(v)
            self.assertLess(info["runtime"], 2.0)
            self.assertEqual(layer.shape, (1200, 600, 4))
            self.assertNotIn("map", info)
        _, info, _, _ = _layer("C", debug_map=True)
        self.assertEqual([m.shape for m in info["map"]], [(1200, 600), (1200, 600)])


R7_FIXTURE = Path(__file__).resolve().parent / "testdata" / "mls_r7"


@skipUnless((R7_FIXTURE / "expected").is_dir(),
            "r7 fixture missing (real avatars, not in git): run tools/warp-benchmark/export_r7_regression.py "
            "on the code before the round 8 change")
class MlsR7RegressionTests(SimpleTestCase):
    """Frozen snapshot (collar_floor_on=False: the fixtures predate the collar floor, docs/09 #100).
    Default sleeve_variant (r7) is pixel-identical to the layer exported before round 8: #28, #43, #40 x 6
    avatars, adapt (fitted, k 1.0). The fixture holds the 600x1200 avatars, their landmarks, the garments and the
    engine_landmarks the try-on task passes."""

    def test_r7_is_pixel_identical(self):
        expected = sorted((R7_FIXTURE / "expected").glob("*.png"))
        self.assertEqual(len(expected), 18)
        for path in expected:
            gid, pk = path.stem.split("_")
            base = cv2.imread(str(R7_FIXTURE / "avatars" / f"{pk}.png"), cv2.IMREAD_UNCHANGED)
            blm = json.loads((R7_FIXTURE / "avatars" / f"{pk}.json").read_text())
            g = cv2.imread(str(R7_FIXTURE / "garments" / f"{gid}.png"), cv2.IMREAD_UNCHANGED)
            glm = json.loads((R7_FIXTURE / "garments" / f"{gid}.json").read_text())
            want = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            mask = warp.figure_mask(base)
            for kw in ({}, {"sleeve_variant": "r7"}):
                with self.subTest(garment=gid, avatar=pk, **kw):
                    got, _ = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, collar_floor_on=False, **kw)
                    np.testing.assert_array_equal(got, want)


R10_FIXTURE = Path(__file__).resolve().parent / "testdata" / "mls_r10"


@skipUnless((R10_FIXTURE / "expected").is_dir(),
            "round 10 fixture missing (real avatars, not in git): run tools/warp-benchmark/export_r10_regression.py "
            "on the code before the side_floor change")
class MlsSideFloorOffRegressionTests(SimpleTestCase):
    """side_floor=False (the default) is pixel-identical to the layers exported before round 10: #28, #43, #40, #44,
    #45 x 6 avatars x adapt and keep_shape."""

    def test_off_is_pixel_identical(self):
        expected = sorted((R10_FIXTURE / "expected").glob("*.png"))
        self.assertEqual(len(expected), 60)
        for path in expected:
            mode, gid, pk = path.stem.rsplit("_", 2)
            base = cv2.imread(str(R10_FIXTURE / "avatars" / f"{pk}.png"), cv2.IMREAD_UNCHANGED)
            blm = json.loads((R10_FIXTURE / "avatars" / f"{pk}.json").read_text())
            g = cv2.imread(str(R10_FIXTURE / "garments" / f"{gid}.png"), cv2.IMREAD_UNCHANGED)
            glm = json.loads((R10_FIXTURE / "garments" / f"{gid}.json").read_text())
            want = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            mask = warp.figure_mask(base)
            for kw in ({}, {"side_floor": False}):
                with self.subTest(mode=mode, garment=gid, avatar=pk, **kw):
                    got, _ = mls.tshirt_layer(g, glm, blm, mask, mode, 1200, 600, collar_floor_on=False, **kw)
                    np.testing.assert_array_equal(got, want)


@skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
class OversizedPreRound10Tests(SimpleTestCase):
    """#44 and #45 (oversized) x 6 avatars x adapt + keep_shape: the default (side_floor off) is 0 px from the
    pre-round-10 export (24 renders). keep_shape with side_floor=True is 0 px too (12 renders: disabled for keep_shape,
    owner 2026-11-12). adapt with side_floor=True is NOT covered: still open with the owner (8 of 12 differ)."""

    def _renders(self):
        for gid in ("44", "45"):
            g = cv2.imread(str(R10_FIXTURE / "garments" / f"{gid}.png"), cv2.IMREAD_UNCHANGED)
            glm = json.loads((R10_FIXTURE / "garments" / f"{gid}.json").read_text())
            for pk in range(1, 7):
                base = cv2.imread(str(R10_FIXTURE / "avatars" / f"{pk}.png"), cv2.IMREAD_UNCHANGED)
                blm = json.loads((R10_FIXTURE / "avatars" / f"{pk}.json").read_text())
                yield gid, pk, g, glm, blm, warp.figure_mask(base)

    def _want(self, mode, gid, pk):
        return cv2.imread(str(R10_FIXTURE / "expected" / f"{mode}_{gid}_{pk}.png"), cv2.IMREAD_UNCHANGED)

    def test_default_is_0_px(self):
        n = 0
        for gid, pk, g, glm, blm, mask in self._renders():
            for mode in ("adapt", "keep_shape"):
                with self.subTest(garment=gid, avatar=pk, mode=mode):
                    got, _ = mls.tshirt_layer(g, glm, blm, mask, mode, 1200, 600, collar_floor_on=False)
                    self.assertEqual(int((got != self._want(mode, gid, pk)).any(2).sum()), 0)
                    n += 1
        self.assertEqual(n, 24)

    def test_keep_shape_with_side_floor_is_0_px(self):
        n = 0
        for gid, pk, g, glm, blm, mask in self._renders():
            with self.subTest(garment=gid, avatar=pk):
                got, _ = mls.tshirt_layer(g, glm, blm, mask, "keep_shape", 1200, 600, side_floor=True,
                                          collar_floor_on=False)
                self.assertEqual(int((got != self._want("keep_shape", gid, pk)).any(2).sum()), 0)
                n += 1
        self.assertEqual(n, 12)


def narrow_shirt():
    """shirt() with the torso narrowed to 120 px (garment narrower than the body after the shoulder scale)."""
    img, lm = shirt()
    img[:, :, :] = 0
    cv2.fillPoly(img, [np.array([(120, 30), (175, 30), (200, 60), (225, 30), (280, 30), (260, 115), (260, 420),
                                 (140, 420), (140, 115)], np.int32)], SHIRT)
    cv2.fillPoly(img, [np.array([(120, 30), (58, 125), (90, 150), (140, 115)], np.int32)], SHIRT)
    cv2.fillPoly(img, [np.array([(280, 30), (342, 125), (310, 150), (260, 115)], np.int32)], SHIRT)
    for r in ("armpit", "chest", "waist", "hem"):
        lm[r].update(left_x=140, right_x=260)
    return img, lm


def oversized_shirt():
    """shirt() with a 260 px torso (1.6x the shoulder span): wider than the body + ease after the shoulder scale."""
    img, lm = shirt()
    img[:, :, :] = 0
    cv2.fillPoly(img, [np.array([(120, 30), (175, 30), (200, 60), (225, 30), (280, 30), (330, 115), (330, 420),
                                 (70, 420), (70, 115)], np.int32)], SHIRT)
    cv2.fillPoly(img, [np.array([(120, 30), (40, 150), (75, 170), (70, 115)], np.int32)], SHIRT)
    cv2.fillPoly(img, [np.array([(280, 30), (360, 150), (325, 170), (330, 115)], np.int32)], SHIRT)
    for r in ("armpit", "chest", "waist", "hem"):
        lm[r].update(left_x=70, right_x=330)
    lm["sleeve_cuff_outer"] = {"left": {"x": 40, "y": 150}, "right": {"x": 360, "y": 150}}
    lm["sleeve_cuff_inner"] = {"left": {"x": 75, "y": 170}, "right": {"x": 325, "y": 170}}
    return img, lm


class SideFloorTests(SimpleTestCase):
    """Benchmark round 10 (docs/06): side_floor keyword, default False."""

    def _run(self, g, glm, mode, on):
        base, lm = body()
        mask = warp.figure_mask(cv2.resize(warp._bgra(base), (600, 1200)))
        layer, info = mls.tshirt_layer(g, glm, lm, mask, mode, side_floor=on)
        return layer, info, mask, lm

    def test_render_tryon_does_not_pass_it(self):
        base, lm = body()
        g, glm = shirt()
        with mock.patch("apps.tryon_engine.mls.tshirt_layer", wraps=mls.tshirt_layer) as spy:
            warp.render_tryon(base, lm, [("tshirt", g, eng(glm))], warp_engine="mls", fit_modes={"tshirt": "keep_shape"})
        self.assertNotIn("side_floor", spy.call_args.kwargs)

    def test_side_targets_never_inside_the_floor(self):
        g, glm = narrow_shirt()
        for mode in ("adapt",):
            _, info, mask, lm = self._run(g, glm, mode, True)
            axis = warp._crotch_x(lm)
            new = [k for k in info["pairs"] if k.startswith("side_")]
            self.assertTrue(new, mode)
            for k in new:
                if k not in info["pairs"]:
                    continue
                x, y = info["pairs"][k][1]
                fl, fr = mls._torso_floor(mask, lm, y, axis)
                with self.subTest(mode=mode, pair=k):
                    if k.endswith("_l"):
                        self.assertLessEqual(x, fl + 1e-6)
                    else:
                        self.assertGreaterEqual(x, fr - 1e-6)

    def test_keep_shape_is_a_no_op(self):  # disabled for keep_shape for now (owner, 2026-11-12)
        for g, glm in (narrow_shirt(), oversized_shirt(), shirt()):
            off, _, _, _ = self._run(g, glm, "keep_shape", False)
            on, info, _, _ = self._run(g, glm, "keep_shape", True)
            np.testing.assert_array_equal(on, off)
            self.assertFalse([k for k in info["pairs"] if k.startswith("side_")])
        self.assertEqual(mls.k_map_for("keep_shape"), mls.PRESET_A)  # preset A untouched

    def test_adapt_floor_widens_a_narrow_garment(self):
        g, glm = narrow_shirt()
        off, _, mask, lm = self._run(g, glm, "adapt", False)
        on, info, _, _ = self._run(g, glm, "adapt", True)
        y = int(lm["waist"]["y"])
        axis = warp._crotch_x(lm)
        width = lambda layer: np.count_nonzero(layer[y, :, 3] >= 128)  # noqa: E731
        self.assertGreater(width(on), width(off))
        fl, fr = mls._torso_floor(mask, lm, y, axis)
        cov = np.nonzero(on[y, :, 3] >= 128)[0]
        # the visible edge lands up to ~4 px inside the target: the outer-contour halo fix and the alpha boundary
        self.assertLessEqual(cov.min(), fl + 5)
        self.assertGreaterEqual(cov.max(), fr - 5)

    def test_no_pair_where_the_garment_already_covers(self):
        g, glm = oversized_shirt()  # wider than body + ease on every side row in adapt's first solve too
        off, _, _, _ = self._run(g, glm, "adapt", False)
        on, info, _, _ = self._run(g, glm, "adapt", True)
        self.assertFalse([k for k in info["pairs"] if k.startswith("side_")])
        np.testing.assert_array_equal(on, off)  # no pair -> no second solve -> the same output

    def test_validation_drops_a_crossing_new_pair(self):
        pairs = {"waist_l": ((100, 200), (150, 600), 1.0), "waist_r": ((300, 200), (450, 600), 1.0),
                 "side_a_l": ((100, 250), (150, 550), 1.0), "side_a_r": ((300, 250), (450, 650), 1.0),
                 "side_b_l": ((310, 300), (150, 700), 1.0), "side_b_r": ((300, 300), (450, 700), 1.0)}
        rejected = []
        mls._validate_side_floor(pairs, rejected)
        self.assertNotIn("side_a_l", pairs)  # garment below the waist, body above it
        self.assertIn("side_a_r", pairs)
        self.assertFalse({"side_b_l", "side_b_r"} & set(pairs))  # left/right swapped in the garment
        self.assertEqual(set(pairs) - {"side_a_r"}, {"waist_l", "waist_r"})

    def test_runtime(self):
        g, glm = narrow_shirt()
        for mode in ("adapt",):
            _, info, _, _ = self._run(g, glm, mode, True)
            self.assertLess(info["runtime"], 2.0)


class NecklineVariantTests(SimpleTestCase):
    """Benchmark (docs/06 "V-neck opening"): neckline_variant r7 | clear | clear_skin, keyword only, default r7."""

    def _run(self, **kw):
        base, lm = body()
        base = cv2.resize(warp._bgra(base), (600, 1200))
        g, glm = shirt()  # V neck: depth 30 / width 50 = 0.6 >= NECKLINE_V_RATIO
        mask = warp.figure_mask(base)
        layer, info = mls.tshirt_layer(g, glm, lm, mask, "adapt", base=base, **kw)
        return layer, info, base, mask, glm

    def test_default_is_r7_and_unknown_is_an_error(self):
        a, _, _, _, _ = self._run()
        b, _, _, _, _ = self._run(neckline_variant="r7")
        np.testing.assert_array_equal(a, b)
        with self.assertRaises(ValueError):
            self._run(neckline_variant="scoop")

    def test_render_tryon_does_not_pass_it(self):
        base, lm = body()
        g, glm = shirt()
        with mock.patch("apps.tryon_engine.mls.tshirt_layer", wraps=mls.tshirt_layer) as spy:
            warp.render_tryon(base, lm, [("tshirt", g, eng(glm))], warp_engine="mls", source="avatar")
        self.assertFalse({"neckline_variant", "source", "base"} & set(spy.call_args.kwargs))

    def test_clear_opens_the_v_and_changes_nothing_else(self):
        r7, _, _, _, _ = self._run()
        clear, info, _, _, glm = self._run(neckline_variant="clear")
        self.assertEqual(info["neckline"]["shape"], "v")
        w, meta = mls.neckline_opening(info["pairs"], glm, 1200, 600)
        self.assertTrue((w >= 1).any())
        self.assertEqual(int((clear[:, :, 3][w >= 1] > 0).sum()), 0)  # no fabric left deep inside the opening
        np.testing.assert_array_equal(clear[w == 0], r7[w == 0])  # outside the opening: identical
        np.testing.assert_array_equal(clear[:, :, :3], r7[:, :, :3])  # alpha only
        self.assertNotIn("neck_fill", info)

    def test_clear_skin_is_clear_for_an_own_body(self):
        a, ia, _, _, _ = self._run(neckline_variant="clear")
        for source in ("body", "unknown"):
            b, ib, _, _, _ = self._run(neckline_variant="clear_skin", source=source)
            np.testing.assert_array_equal(a, b)
            self.assertNotIn("neck_fill", ib)
            self.assertEqual(ib["neckline"]["variant"], "clear")

    def test_clear_skin_fills_only_inside_the_opening_on_avatars(self):
        clear, _, _, _, _ = self._run(neckline_variant="clear")
        layer, info, _, mask, glm = self._run(neckline_variant="clear_skin", source="avatar")
        np.testing.assert_array_equal(layer, clear)  # the garment layer is the same; the fill is a separate overlay
        w, _ = mls.neckline_opening(info["pairs"], glm, 1200, 600)
        fill = info.get("neck_fill")
        if fill is not None:
            on = fill[:, :, 3] > 0
            self.assertFalse((on & (w == 0)).any())
            self.assertFalse((on & ~mask).any())

    def test_bad_neck_targets_do_nothing(self):
        pairs = {"neck_l": ((0, 0), (250, 200), 5.0), "neck_r": ((0, 0), (350, 200), 5.0),
                 "neck_c": ((0, 0), (300, 190), 5.0)}  # collar_bottom above the collar line
        w, why = mls.neckline_opening(pairs, shirt()[1], 1200, 600)
        self.assertIsNone(w)
        self.assertEqual(why, "neck targets out of order")
        del pairs["neck_c"]
        self.assertIsNone(mls.neckline_opening(pairs, shirt()[1], 1200, 600)[0])

    def test_runtime(self):
        for v in mls.NECKLINE_VARIANTS:
            _, info, _, _, _ = self._run(neckline_variant=v, source="avatar")
            self.assertLess(info["runtime"], 2.0)


class NeckClipTests(SimpleTestCase):
    """Benchmark: neck_clip keyword (default False) clips the neck/shoulder box to the dilated figure mask."""

    def _run(self, **kw):
        base, lm = body()
        base = cv2.resize(warp._bgra(base), (600, 1200))
        g, glm = shirt()
        mask = warp.figure_mask(base)
        layer, info = mls.tshirt_layer(g, glm, lm, mask, "adapt", neckline_variant="clear", **kw)
        return layer, info, mask, lm

    def test_default_off_and_not_passed_by_render_tryon(self):
        a, _, _, _ = self._run()
        b, _, _, _ = self._run(neck_clip=False)
        np.testing.assert_array_equal(a, b)
        base, lm = body()
        g, glm = shirt()
        with mock.patch("apps.tryon_engine.mls.tshirt_layer", wraps=mls.tshirt_layer) as spy:
            warp.render_tryon(base, lm, [("tshirt", g, eng(glm))], warp_engine="mls")
        self.assertNotIn("neck_clip", spy.call_args.kwargs)

    def test_clip_only_inside_the_box_and_never_over_the_figure(self):
        off, _, mask, lm = self._run()
        on, info, _, _ = self._run(neck_clip=True)
        box = mls.neck_clip_box(info["pairs"], lm, 1200, 600)
        np.testing.assert_array_equal(on[~box], off[~box])
        np.testing.assert_array_equal(on[mask], off[mask])
        np.testing.assert_array_equal(on[:, :, :3], off[:, :, :3])  # alpha only
        k = 2 * mls.NECK_CLIP_DILATE + 1
        ring = cv2.dilate(mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
        self.assertFalse(((on[:, :, 3] >= 128) & box & ~ring).any())
        self.assertLess(info["runtime"], 2.0)


class NeckHoleTests(SimpleTestCase):
    """Benchmark: neckline_variant hole / hole_skin (GrabCut or an owner-drawn polygon in garment px)."""

    def _run(self, **kw):
        base, lm = body()
        base = cv2.resize(warp._bgra(base), (600, 1200))
        g, glm = shirt()
        mask = warp.figure_mask(base)
        return mls.tshirt_layer(g, glm, lm, mask, "adapt", base=base, **kw)

    def test_polygon_hole_clears_only_its_warped_area(self):
        r7, _ = self._run()
        poly = [[185, 32], [215, 32], [200, 52]]  # inside the synthetic V (collar 175..225 at y 30, bottom 200, 60)
        layer, info = self._run(neckline_variant="hole", neck_hole_polygon=poly)
        w = info["neck_weight"]
        self.assertEqual(info["neckline"]["source"], "polygon")
        self.assertTrue((w >= 1).any())
        self.assertEqual(int((layer[:, :, 3][w >= 1] > 0).sum()), 0)
        np.testing.assert_array_equal(layer[w == 0], r7[w == 0])
        np.testing.assert_array_equal(layer[:, :, :3], r7[:, :, :3])

    def test_hole_skin_is_hole_for_an_own_body_and_empty_polygon_is_r7(self):
        poly = [[185, 32], [215, 32], [200, 52]]
        a, _ = self._run(neckline_variant="hole", neck_hole_polygon=poly)
        b, ib = self._run(neckline_variant="hole_skin", neck_hole_polygon=poly, source="body")
        np.testing.assert_array_equal(a, b)
        self.assertNotIn("neck_fill", ib)
        r7, _ = self._run()
        c, ic = self._run(neckline_variant="hole", neck_hole_polygon=[[10, 10], [10, 10], [10, 10]])
        self.assertIn("skipped", ic["neckline"])
        np.testing.assert_array_equal(c, r7)


class CollarFloorTests(SimpleTestCase):
    """docs/09 #100: neck_l / neck_r targets below the body's shoulder contour are raised onto it (default on)."""

    @staticmethod
    def _mask(top=100):
        m = np.zeros((300, 200), bool)
        m[top:, :] = True  # shoulder contour at y = top in every column
        return m

    @staticmethod
    def _pairs(y):
        return {"neck_l": ((0, 0), (60.0, float(y)), 5.0), "neck_r": ((0, 0), (140.0, float(y)), 5.0)}

    blm = {"neck": {"y": 50}}

    def test_below_the_contour_is_raised_to_margin_above_it(self):
        pairs = self._pairs(110)
        raised = mls.collar_floor(pairs, self.blm, self._mask(100))
        self.assertEqual(pairs["neck_l"][1], (60.0, 100.0 - mls.COLLAR_FLOOR_MARGIN))
        self.assertEqual(set(raised), {"neck_l", "neck_r"})

    def test_above_the_contour_is_never_lowered(self):
        pairs = self._pairs(90)
        self.assertEqual(mls.collar_floor(pairs, self.blm, self._mask(100)), {})
        self.assertEqual(pairs["neck_l"][1], (60.0, 90.0))

    def test_raise_is_capped(self):
        pairs = self._pairs(100 + mls.COLLAR_FLOOR_MAX + 5)
        self.assertEqual(mls.collar_floor(pairs, self.blm, self._mask(100)), {})

    def test_contour_is_searched_below_the_neck_row_only(self):
        m = self._mask(100)
        m[0:40, :] = True  # head/hair above the neck row: ignored
        pairs = self._pairs(110)
        mls.collar_floor(pairs, self.blm, m)
        self.assertEqual(pairs["neck_r"][1][1], 100.0 - mls.COLLAR_FLOOR_MARGIN)

    def test_default_on_and_off_keeps_the_old_targets(self):
        _, on, _, _ = _layer()
        _, off, _, _ = _layer(collar_floor_on=False)
        self.assertIn("collar_floor", on)
        self.assertNotIn("collar_floor", off)
        for name in ("neck_l", "neck_r"):
            self.assertLessEqual(on["pairs"][name][1][1], off["pairs"][name][1][1])


class ShoulderLineTests(SimpleTestCase):
    """Benchmark round 9 (docs/06 "Shoulder line fit, round 9"): shoulder_variant off | line, keyword only, default
    off; adapt only (a no-op in keep_shape)."""

    def test_default_is_off_and_unknown_is_an_error(self):
        a, ia, _, _ = _layer()
        b, ib, _, _ = _layer(shoulder_variant="off")
        np.testing.assert_array_equal(a, b)
        self.assertEqual(ia["pairs"], ib["pairs"])
        self.assertNotIn("shoulder_line", ia)
        with self.assertRaises(ValueError):
            _layer(shoulder_variant="curve")

    def test_render_tryon_does_not_pass_it(self):
        base, lm = body()
        g, glm = shirt()
        with mock.patch("apps.tryon_engine.mls.tshirt_layer", wraps=mls.tshirt_layer) as spy:
            warp.render_tryon(base, lm, [("tshirt", g, eng(glm))], warp_engine="mls")
        self.assertNotIn("shoulder_variant", spy.call_args.kwargs)

    def test_line_adds_three_pairs_per_side_on_the_shoulder_edge(self):
        _, info, mask, lm = _layer("C", shoulder_variant="line")
        names = sorted(k for k in info["pairs"] if k.startswith("sline"))
        self.assertEqual(names, ["sline25_l", "sline25_r", "sline50_l", "sline50_r", "sline75_l", "sline75_r"])
        for side, sx in (("left", "_l"), ("right", "_r")):
            self.assertNotIn("skipped", info["shoulder_line"][side])
            for k in names:
                if not k.endswith(sx):
                    continue
                (_, _), (px, py), w = info["pairs"][k]
                self.assertEqual(w, mls.SHOULDER_LINE_WEIGHT)
                col = mask[:, int(px)]
                self.assertFalse(col[int(py)])  # SHOULDER_LINE_EASE px above the edge: background
                self.assertTrue(col[int(py) + mls.SHOULDER_LINE_EASE])  # the edge itself: figure

    def test_side_without_collar_or_edge_is_skipped_and_reported(self):
        base, lm = body()
        g, glm = shirt()
        mask = warp.figure_mask(cv2.resize(warp._bgra(base), (600, 1200)))
        pairs = {}
        no_collar = {k: v for k, v in glm.items() if k != "collar"}
        rep = mls.shoulder_line(pairs, no_collar, lm, mask, warp._bgra(g)[:, :, 3])
        self.assertEqual(pairs, {})
        self.assertEqual(rep["left"]["skipped"], "collar or neck point missing")
        rep = mls.shoulder_line(pairs, glm, lm, mask, np.zeros(warp._bgra(g).shape[:2], np.uint8))
        self.assertEqual(pairs, {})
        self.assertTrue(rep["right"]["skipped"].startswith("no garment edge"))

    def test_keep_shape_line_is_identical_to_off(self):  # same other keywords (collar_floor_on default)
        base, lm = body()
        g, glm = shirt()
        mask = warp.figure_mask(cv2.resize(warp._bgra(base), (600, 1200)))
        a, ia = mls.tshirt_layer(g, glm, lm, mask, "keep_shape", sleeve_variant="C", shoulder_variant="line")
        b, _ = mls.tshirt_layer(g, glm, lm, mask, "keep_shape", sleeve_variant="C", shoulder_variant="off")
        np.testing.assert_array_equal(a, b)
        self.assertNotIn("shoulder_line", ia)

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_keep_shape_line_is_identical_to_off_on_44_45(self):
        n = 0
        for gid in ("44", "45"):
            g = cv2.imread(str(R10_FIXTURE / "garments" / f"{gid}.png"), cv2.IMREAD_UNCHANGED)
            glm = json.loads((R10_FIXTURE / "garments" / f"{gid}.json").read_text())
            for pk in range(1, 7):
                base = cv2.imread(str(R10_FIXTURE / "avatars" / f"{pk}.png"), cv2.IMREAD_UNCHANGED)
                blm = json.loads((R10_FIXTURE / "avatars" / f"{pk}.json").read_text())
                mask = warp.figure_mask(base)
                for sv in ("C", "r7"):
                    with self.subTest(garment=gid, avatar=pk, sleeve=sv):
                        off, _ = mls.tshirt_layer(g, glm, blm, mask, "keep_shape", 1200, 600, sleeve_variant=sv)
                        line, _ = mls.tshirt_layer(g, glm, blm, mask, "keep_shape", 1200, 600, sleeve_variant=sv,
                                                   shoulder_variant="line")
                        self.assertEqual(int((off != line).any(2).sum()), 0)
                        n += 1
        self.assertEqual(n, 24)


class ShoulderFractionsTests(SimpleTestCase):
    """Round 9: shoulder_fractions picks which line pairs exist (benchmark keyword, default 25 / 50 / 75 %)."""

    def test_default_equals_explicit_and_50_75_drops_the_25_pair(self):
        a, ia, _, _ = _layer("C", shoulder_variant="line")
        b, ib, _, _ = _layer("C", shoulder_variant="line", shoulder_fractions=mls.SHOULDER_LINE_FRACTIONS)
        np.testing.assert_array_equal(a, b)
        _, ic, _, _ = _layer("C", shoulder_variant="line", shoulder_fractions=(0.5, 0.75))
        self.assertEqual(sorted(k for k in ic["pairs"] if k.startswith("sline")),
                         ["sline50_l", "sline50_r", "sline75_l", "sline75_r"])
        off, _, _, _ = _layer("C")
        off2, _, _, _ = _layer("C", shoulder_fractions=(0.5, 0.75))  # ignored when the variant is off
        np.testing.assert_array_equal(off, off2)


class ShoulderEdgeAlphaEaseTests(SimpleTestCase):
    """Round 9b: shoulder_ease / shoulder_edge_alpha (benchmark keywords): defaults = round 9, ignored when off."""

    def test_defaults_and_off(self):
        a, _, _, _ = _layer("C", shoulder_variant="line")
        b, _, _, _ = _layer("C", shoulder_variant="line", shoulder_ease=mls.SHOULDER_LINE_EASE, shoulder_edge_alpha=128)
        np.testing.assert_array_equal(a, b)
        off, _, _, _ = _layer("C")
        off2, _, _, _ = _layer("C", shoulder_ease=4, shoulder_edge_alpha=mls.HARD_EDGE - 1)
        np.testing.assert_array_equal(off, off2)

    def test_hard_edge_and_ease_move_the_pairs(self):
        _, i128, _, _ = _layer("C", shoulder_variant="line")
        _, ihard, _, _ = _layer("C", shoulder_variant="line", shoulder_ease=4, shoulder_edge_alpha=mls.HARD_EDGE - 1)
        for k in ("sline50_l", "sline50_r"):
            self.assertGreaterEqual(ihard["pairs"][k][0][1], i128["pairs"][k][0][1])  # garment edge never higher
            self.assertEqual(ihard["pairs"][k][1][1], i128["pairs"][k][1][1] - 2)  # ease 4 vs 2: 2 px higher
