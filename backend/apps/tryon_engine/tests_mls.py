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
        self.assertEqual(parse_tryon_warp(None), "mls")  # the default since docs/09 #105
        self.assertEqual(parse_tryon_warp(""), "mls")
        self.assertEqual(parse_tryon_warp("parts"), "parts")
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
            report = tasks._do_warp(outfit)
            self.assertIsInstance(report.pop("render_ms"), int)
            cfg = report.pop("tshirt_config")
            self.assertEqual(report, {"engine": "mls", "quality_warnings": [], "neck_hole": {gid: False},
                                      "finish": "r17"})  # the settings default (docs/09 #107)
            self.assertEqual(list(cfg), [gid])
            want = {"fit_mode": mode, "engine": "mls", "sleeve": None, "tube": False, "side_floor": "off",
                    "armpit": "off", "hem": "mls", "cuff": "chord", "fringe": "keep"}
            if mode == "adapt":  # the settings defaults (docs/09 #105, #106)
                want.update(sleeve="C", tube=True, side_floor="mask", armpit="r14", hem="garment", cuff="hem",
                            fringe="drop", tube_clip="arm")  # tube_clip: docs/09 #113
            else:  # docs/09 #112, #121
                want["keep_scale"] = "fit"
                self.assertGreaterEqual(cfg[gid]["keep_neck_dy"], 0)
                want["keep_neck_dy"] = cfg[gid]["keep_neck_dy"]
            self.assertEqual(cfg[gid], want)
            self.assertEqual(self._result_shape(outfit), (1200, 600))

    @override_settings(TRYON_WARP="mls")
    def test_incomplete_landmarks_fall_back(self):
        outfit = self._outfit(complete=False)
        with mock.patch("apps.tryon_engine.mls.tshirt_layer") as layer:
            report = tasks._do_warp(outfit)
        layer.assert_not_called()  # mls_ready is false: MLS is not attempted
        gid = str(outfit.garments.get().pk)
        self.assertIsInstance(report.pop("render_ms"), int)
        self.assertEqual(report, {"engine": "parts", "quality_warnings": ["mls_fallback"], "neck_hole": {gid: False},
                                  "tshirt_config": {gid: {"fit_mode": "adapt", "engine": "parts"}},
                                  "finish": "r17"})
        self.assertEqual(self._result_shape(outfit), (1200, 600))

    @override_settings(TRYON_WARP="parts")
    def test_parts_default(self):
        outfit = self._outfit()
        gid = str(outfit.garments.get().pk)
        report = tasks._do_warp(outfit)
        self.assertIsInstance(report.pop("render_ms"), int)
        self.assertEqual(report, {"engine": "parts", "quality_warnings": [], "neck_hole": {gid: False},
                                  "tshirt_config": {gid: {"fit_mode": "adapt", "engine": "parts"}},
                                  "finish": "r17"})

    @override_settings(TRYON_FINISH="off")
    def test_finish_off_is_reported(self):
        report = tasks._do_warp(self._outfit())
        self.assertEqual(report["finish"], "off")

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


class TubeSleeveTests(SimpleTestCase):
    """Round 11 benchmark (docs/06 "Tube sleeve, round 11"): sleeve_mode mls | tube, keyword only, default mls;
    adapt only (a no-op in keep_shape); render_tryon never passes it."""

    def test_default_is_mls_and_unknown_is_an_error(self):
        a, ia, _, _ = _layer("C")
        b, ib, _, _ = _layer("C", sleeve_mode="mls")
        np.testing.assert_array_equal(a, b)
        self.assertNotIn("tube", ia)
        with self.assertRaises(ValueError):
            _layer("C", sleeve_mode="cone")

    def test_render_tryon_does_not_pass_it(self):
        base, lm = body()
        g, glm = shirt()
        with mock.patch("apps.tryon_engine.mls.tshirt_layer", wraps=mls.tshirt_layer) as spy:
            warp.render_tryon(base, lm, [("tshirt", g, eng(glm))], warp_engine="mls")
        self.assertNotIn("sleeve_mode", spy.call_args.kwargs)

    def _r10(self):
        for gid in ("28", "44", "45"):
            g = cv2.imread(str(R10_FIXTURE / "garments" / f"{gid}.png"), cv2.IMREAD_UNCHANGED)
            glm = json.loads((R10_FIXTURE / "garments" / f"{gid}.json").read_text())
            for pk in (1, 4):
                base = cv2.imread(str(R10_FIXTURE / "avatars" / f"{pk}.png"), cv2.IMREAD_UNCHANGED)
                blm = json.loads((R10_FIXTURE / "avatars" / f"{pk}.json").read_text())
                yield gid, pk, g, glm, blm, warp.figure_mask(base)

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_keep_shape_tube_is_identical_to_mls(self):
        n = 0
        for gid, pk, g, glm, blm, mask in self._r10():
            if gid == "28":
                continue
            with self.subTest(garment=gid, avatar=pk):
                kw = dict(sleeve_variant="C", side_floor=True)
                a, _ = mls.tshirt_layer(g, glm, blm, mask, "keep_shape", 1200, 600, **kw)
                for mode in ("tube", "tube_perp"):
                    b, ib = mls.tshirt_layer(g, glm, blm, mask, "keep_shape", 1200, 600, sleeve_mode=mode, **kw)
                    self.assertEqual(int((a != b).any(2).sum()), 0)
                    self.assertNotIn("tube", ib)
                n += 1
        self.assertEqual(n, 4)

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_tube_never_clears_torso_px(self):
        """Inward of both body armhole lines and farther than the blend zone from them, tube = mls (alpha); both
        tube modes."""
        for (gid, pk, g, glm, blm, mask), mode in [(r, m) for r in self._r10() for m in ("tube", "tube_perp")]:
            if gid != "28":
                continue
            with self.subTest(avatar=pk, mode=mode):
                kw = dict(sleeve_variant="C", side_floor=True)
                a, _ = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, **kw)
                b, ib = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, sleeve_mode=mode, **kw)
                Y, X = np.mgrid[0:1200, 0:600]
                torso = np.ones((1200, 600), bool)
                for side in ("left", "right"):
                    rep = ib["tube"][side]
                    self.assertNotIn("skipped", rep)
                    B0, B1 = (np.array(p, float) for p in rep["armhole_body"])
                    ax1 = np.array(rep["axis_body"][1], float)
                    nrm = np.array([-(B1 - B0)[1], (B1 - B0)[0]])
                    if (ax1 - B0) @ nrm < 0:
                        nrm = -nrm
                    nrm /= np.linalg.norm(nrm)
                    torso &= ((X - B0[0]) * nrm[0] + (Y - B0[1]) * nrm[1]) < -(mls.TUBE_BLEND_PX + 2)
                diff = (a[:, :, 3] != b[:, :, 3]) & torso & (a[:, :, 3] > 0)
                self.assertEqual(int(diff.sum()), 0)

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_arm_floor_and_cuff_on_the_mls_cuff(self):
        """Fix 1: the body axis ends on the midpoint of the MLS cuff targets (the cuff segment is perpendicular to
        the axis there, outer / inner widths may differ); fix 2: after t = 0 every output half-width is at
        least the arm extent x CUFF_ARM_EASE and at least the ramped garment width."""
        for gid, pk, g, glm, blm, mask in self._r10():
            if gid != "28":
                continue
            for mode in ("tube", "tube_perp"):
                _, info = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, sleeve_variant="C",
                                           side_floor=True, sleeve_mode=mode)
                for side, sx in (("left", "_l"), ("right", "_r")):
                    with self.subTest(avatar=pk, mode=mode, side=side):
                        rep = info["tube"][side]
                        cm = (np.array(info["pairs"]["cuff_out" + sx][1]) + np.array(info["pairs"]["cuff_in" + sx][1])) / 2
                        np.testing.assert_allclose(rep["axis_body"][1], cm, atol=0.06)  # the axis ends there
                        for w in rep["widths"][1:]:
                            ao, ai = w["arm_out_in"]
                            self.assertGreaterEqual(w["out_in"][0] + 0.05, ao * mls.CUFF_ARM_EASE)
                            self.assertGreaterEqual(w["out_in"][1] + 0.05, ai * mls.CUFF_ARM_EASE)
                        self.assertEqual(rep["widths"][-1]["out_in"][0],
                                         max(rep["widths"][-1]["garment_x_s"][0],
                                             round(rep["widths"][-1]["arm_out_in"][0] * mls.CUFF_ARM_EASE, 1)))

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_no_new_holes_in_the_shoulder_armpit_sleeve_zone(self):
        """Owner 2026-11-13 (#40 underarm): figure px uncovered by the garment in the shoulder / armpit / sleeve zone
        (outward of the reference body armhole line above the lower cuff target + 10 px, plus 15 px around the
        armhole segment) must not increase vs the reference (sleeve C + side_floor). Both tube modes, #28 and #40."""
        for gid in ("28", "40"):
            g = cv2.imread(str(R10_FIXTURE / "garments" / f"{gid}.png"), cv2.IMREAD_UNCHANGED)
            glm = json.loads((R10_FIXTURE / "garments" / f"{gid}.json").read_text())
            for pk in range(1, 7):
                base = cv2.imread(str(R10_FIXTURE / "avatars" / f"{pk}.png"), cv2.IMREAD_UNCHANGED)
                blm = json.loads((R10_FIXTURE / "avatars" / f"{pk}.json").read_text())
                mask = warp.figure_mask(base)
                kw = dict(sleeve_variant="C", side_floor=True)
                ref, ri = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, **kw)
                zone = tube_zone(ri["pairs"], blm)
                for mode in ("tube", "tube_perp"):
                    with self.subTest(garment=gid, avatar=pk, mode=mode):
                        lay, _ = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, sleeve_mode=mode, **kw)
                        new = zone & mask & (lay[:, :, 3] < 128) & (ref[:, :, 3] >= 128)
                        self.assertEqual(int(new.sum()), 0)


def tube_zone(pairs, blm, H=1200, W=600, around=15):
    """Shoulder / armpit / sleeve zone of round 11 (both sides), from the reference pairs."""
    Y, X = np.mgrid[0:H, 0:W]
    P = np.stack([X, Y], -1).astype(np.float32)
    zone = np.zeros((H, W), bool)
    for side, sx in (("left", "_l"), ("right", "_r")):
        B0 = np.array(pairs["shoulder" + sx][1], float)
        B1 = np.array(pairs["armpit" + sx][1], float) if "armpit" + sx in pairs else \
            np.array([float(blm["armpit"][f"{side}_x"]), float(blm["armpit"]["y"])])
        cm = (np.array(pairs["cuff_out" + sx][1]) + np.array(pairs["cuff_in" + sx][1])) / 2
        ba = np.array([-(B1 - B0)[1], (B1 - B0)[0]])
        if (cm - B0) @ ba < 0:
            ba = -ba
        ylow = max(pairs["cuff_out" + sx][1][1], pairs["cuff_in" + sx][1][1]) + 10
        seg = B1 - B0
        t = np.clip(((P - B0) @ seg) / float(seg @ seg), 0, 1)
        near = np.linalg.norm(P - (B0 + t[..., None] * seg), axis=-1) <= around
        zone |= ((((P - B0) @ ba) > 0) & (Y <= ylow)) | near
    return zone


class SideFloorMaskTests(SimpleTestCase):
    """Round 12 benchmark (docs/06 "Side coverage, round 12"): side_floor_mode landmarks | mask, keyword only, default
    landmarks; only with side_floor, adapt; a no-op in keep_shape; render_tryon never passes it."""

    def test_default_and_unknown(self):
        a, _, _, _ = _layer("C", side_floor=True)
        b, _, _, _ = _layer("C", side_floor=True, side_floor_mode="landmarks")
        np.testing.assert_array_equal(a, b)
        c, _, _, _ = _layer("C")
        d, _, _, _ = _layer("C", side_floor_mode="mask")  # side_floor off: ignored
        np.testing.assert_array_equal(c, d)
        with self.assertRaises(ValueError):
            _layer("C", side_floor=True, side_floor_mode="rows")

    def test_render_tryon_does_not_pass_it(self):
        base, lm = body()
        g, glm = shirt()
        with mock.patch("apps.tryon_engine.mls.tshirt_layer", wraps=mls.tshirt_layer) as spy:
            warp.render_tryon(base, lm, [("tshirt", g, eng(glm))], warp_engine="mls")
        self.assertNotIn("side_floor_mode", spy.call_args.kwargs)

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_keep_shape_is_identical_and_adapt_reports(self):
        """keep_shape: "mask" = "landmarks", 0 px (#44, #45). adapt: the report exists; new holes are a benchmark
        METRIC (run_side12.py), not asserted: round 12 found the hem rising 5-7 px between the hem pairs."""
        for gid in ("44", "45", "28"):
            g = cv2.imread(str(R10_FIXTURE / "garments" / f"{gid}.png"), cv2.IMREAD_UNCHANGED)
            glm = json.loads((R10_FIXTURE / "garments" / f"{gid}.json").read_text())
            for pk in (1, 3, 6):
                base = cv2.imread(str(R10_FIXTURE / "avatars" / f"{pk}.png"), cv2.IMREAD_UNCHANGED)
                blm = json.loads((R10_FIXTURE / "avatars" / f"{pk}.json").read_text())
                mask = warp.figure_mask(base)
                kw = dict(sleeve_variant="C", side_floor=True, sleeve_mode="tube")
                mode = "keep_shape" if gid in ("44", "45") else "adapt"
                with self.subTest(garment=gid, avatar=pk, mode=mode):
                    a, _ = mls.tshirt_layer(g, glm, blm, mask, mode, 1200, 600, **kw)
                    b, ib = mls.tshirt_layer(g, glm, blm, mask, mode, 1200, 600, side_floor_mode="mask", **kw)
                    if mode == "keep_shape":
                        self.assertEqual(int((a != b).any(2).sum()), 0)
                        self.assertNotIn("side_floor_mask", ib)
                    else:
                        rows = ib["side_floor_mask"]["rows"]
                        self.assertTrue(rows)
                        self.assertTrue(all(r["src"] in ("mask", "interp", None) for r in rows))
                        for k, (q, pt, w) in ib["pairs"].items():  # a mask pair sits outward of its torso edge
                            if k.startswith("sfm"):
                                y, sd = int(k[3:-2]), ("left" if k.endswith("_l") else "right")
                                e = next(r["edge"] for r in rows if r["y"] == y and r["side"] == sd)
                                self.assertAlmostEqual(pt[0], e - 2 if sd == "left" else e + 2, delta=0.06)


class HemSmoothTests(SimpleTestCase):
    """Round 12 benchmark: hem_mode off | smooth (keyword only, default off, adapt only; render_tryon never passes it);
    the "mask" floor skips the hem band."""

    def test_default_unknown_and_not_passed(self):
        a, _, _, _ = _layer("C")
        b, _, _, _ = _layer("C", hem_mode="off")
        np.testing.assert_array_equal(a, b)
        with self.assertRaises(ValueError):
            _layer("C", hem_mode="wavy")
        base, lm = body()
        g, glm = shirt()
        with mock.patch("apps.tryon_engine.mls.tshirt_layer", wraps=mls.tshirt_layer) as spy:
            warp.render_tryon(base, lm, [("tshirt", g, eng(glm))], warp_engine="mls")
        self.assertNotIn("hem_mode", spy.call_args.kwargs)

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_keep_shape_noop_smooth_never_uncovers_the_figure_and_hem_band_rows(self):
        kw = dict(sleeve_variant="C", side_floor=True, sleeve_mode="tube", side_floor_mode="mask")
        for gid in ("44", "45", "28", "40"):
            g = cv2.imread(str(R10_FIXTURE / "garments" / f"{gid}.png"), cv2.IMREAD_UNCHANGED)
            glm = json.loads((R10_FIXTURE / "garments" / f"{gid}.json").read_text())
            for pk in (1, 4, 6):
                base = cv2.imread(str(R10_FIXTURE / "avatars" / f"{pk}.png"), cv2.IMREAD_UNCHANGED)
                blm = json.loads((R10_FIXTURE / "avatars" / f"{pk}.json").read_text())
                mask = warp.figure_mask(base)
                mode = "keep_shape" if gid in ("44", "45") else "adapt"
                with self.subTest(garment=gid, avatar=pk, mode=mode):
                    a, ia = mls.tshirt_layer(g, glm, blm, mask, mode, 1200, 600, **kw)
                    b, ib = mls.tshirt_layer(g, glm, blm, mask, mode, 1200, 600, hem_mode="smooth", **kw)
                    if mode == "keep_shape":
                        self.assertEqual(int((a != b).any(2).sum()), 0)
                        continue
                    self.assertEqual(int((mask & (b[:, :, 3] < 128) & (a[:, :, 3] >= 128)).sum()), 0)
                    hem_y = ia["pairs"]["hem_l"][1][1]
                    band = mls.SIDE_FLOOR_HEM_BAND * (hem_y - float(blm["shoulder"]["y"]))
                    removed = ia["side_floor_mask"]["hem_band_removed_rows"]
                    self.assertTrue(all(y >= hem_y - band for y in removed))
                    self.assertFalse(any(k.startswith("sfm") and int(k[3:-2]) >= hem_y - band for k in ia["pairs"]))


def _r10_case(gid, pk):
    g = cv2.imread(str(R10_FIXTURE / "garments" / f"{gid}.png"), cv2.IMREAD_UNCHANGED)
    glm = json.loads((R10_FIXTURE / "garments" / f"{gid}.json").read_text())
    base = cv2.imread(str(R10_FIXTURE / "avatars" / f"{pk}.png"), cv2.IMREAD_UNCHANGED)
    blm = json.loads((R10_FIXTURE / "avatars" / f"{pk}.json").read_text())
    return g, glm, blm, warp.figure_mask(base)


R12B = dict(sleeve_variant="C", side_floor=True, sleeve_mode="tube", side_floor_mode="mask")


class Round12bKeywordTests(SimpleTestCase):
    """Round 12b benchmark (docs/06 "Hem and tube, round 12b"): tube_arm r11 | fit, hem_mode garment, hem_c_pair;
    keyword only, defaults = before (pixel-identical), render_tryon never passes them."""

    def test_defaults_unknown_and_not_passed(self):
        a, _, _, _ = _layer("C")
        for kw in ({"tube_arm": "r11"}, {"hem_c_pair": False}, {"tube_arm": "fit"}):  # fit without a tube: ignored
            b, _, _, _ = _layer("C", **kw)
            np.testing.assert_array_equal(a, b)
        with self.assertRaises(ValueError):
            _layer("C", tube_arm="wide")
        base, lm = body()
        g, glm = shirt()
        with mock.patch("apps.tryon_engine.mls.tshirt_layer", wraps=mls.tshirt_layer) as spy:
            warp.render_tryon(base, lm, [("tshirt", g, eng(glm))], warp_engine="mls")
        for k in ("tube_arm", "hem_c_pair", "hem_mode"):
            self.assertNotIn(k, spy.call_args.kwargs)

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_keep_shape_is_identical_on_44_45(self):
        for gid in ("44", "45"):
            for pk in (1, 6):
                g, glm, blm, mask = _r10_case(gid, pk)
                with self.subTest(garment=gid, avatar=pk):
                    a, _ = mls.tshirt_layer(g, glm, blm, mask, "keep_shape", 1200, 600, **R12B)
                    for kw in ({"tube_arm": "fit"}, {"hem_mode": "garment"}, {"hem_c_pair": True}):
                        b, ib = mls.tshirt_layer(g, glm, blm, mask, "keep_shape", 1200, 600, **R12B, **kw)
                        self.assertEqual(int((a != b).any(2).sum()), 0)
                        self.assertNotIn("hem_garment", ib)
                        self.assertNotIn("hem_c", ib)


class TubeArmFitTests(SimpleTestCase):
    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_widths_clamped_to_the_arm(self):
        """After t = 0 every half-width with a measured arm is in [arm x CUFF_ARM_EASE, arm x TUBE_ARM_MAX]; the
        cleared px beyond the cuff are reported."""
        for gid in ("28", "40"):
            for pk in (1, 6):
                g, glm, blm, mask = _r10_case(gid, pk)
                _, info = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, tube_arm="fit", **R12B)
                for side in ("left", "right"):
                    with self.subTest(garment=gid, avatar=pk, side=side):
                        rep = info["tube"][side]
                        self.assertNotIn("skipped", rep)
                        self.assertIn("cleared_beyond_cuff_px", rep)
                        for w in rep["widths"][1:]:
                            for i in (0, 1):
                                arm = w["arm_out_in"][i]
                                if not arm:
                                    continue
                                tol = 0.05 + 0.05 * mls.TUBE_ARM_MAX  # both report values are rounded to 0.1 px
                                self.assertGreaterEqual(w["out_in"][i] + tol, arm * mls.CUFF_ARM_EASE)
                                self.assertLessEqual(w["out_in"][i] - tol, arm * mls.TUBE_ARM_MAX)


class SideFloorMaskNoNewHolesTests(SimpleTestCase):
    """Owner 2026-11-15 (round 12b): side_floor_mode="mask" must not uncover any figure px the landmark floor layer
    (same tube keywords) covers (the hard rule), except the arm px a fit tube clears beyond its cuff on purpose."""

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_mask_never_uncovers_the_landmark_floor_layer(self):
        for gid in ("28", "43", "40"):
            for pk in range(1, 7):
                g, glm, blm, mask = _r10_case(gid, pk)
                kw = dict(sleeve_variant="C", side_floor=True, sleeve_mode="tube")
                for arm in ("r11", "fit"):  # vs the landmark floor layer with the SAME tube (round 13 fix 4)
                    ref, _ = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, tube_arm=arm, **kw)
                    with self.subTest(garment=gid, avatar=pk, tube_arm=arm):
                        lay, info = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, side_floor_mode="mask",
                                                     tube_arm=arm, **kw)
                        new = mask & (ref[:, :, 3] >= 128) & (lay[:, :, 3] < 128)
                        for side in ("left", "right"):
                            z = info["tube"][side].get("beyond_cuff_zone")
                            if z is not None:
                                new &= ~z
                        self.assertEqual(int(new.sum()), 0)
                        rep = info["side_floor_mask"]
                        self.assertEqual(rep["blend_residual_px"], 0)
                        self.assertIn("patched_px", rep)


class HemGarmentTests(SimpleTestCase):
    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_never_uncovers_the_figure_and_reports_the_stretch(self):
        for gid in ("28", "40"):
            for pk in (1, 4, 6):
                g, glm, blm, mask = _r10_case(gid, pk)
                with self.subTest(garment=gid, avatar=pk):
                    a, _ = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, **R12B)
                    b, ib = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, hem_mode="garment", **R12B)
                    self.assertEqual(int((mask & (b[:, :, 3] < 128) & (a[:, :, 3] >= 128)).sum()), 0)
                    rep = ib["hem_garment"]
                    self.assertNotIn("skipped", rep)
                    self.assertGreaterEqual(rep["band_px"], 2 * rep["max_move_px"] - 1e-6)
                    self.assertEqual(rep["stretch_warn"], rep["max_stretch"] > mls.HEM_GARMENT_WARN_STRETCH)

    def test_garment_hem_offsets_are_zero_at_the_ends(self):
        alpha = np.zeros((100, 120), np.uint8)
        alpha[10:60, 10:110] = 255
        alpha[60:66, 50:70] = 255  # a 6 px dip in the middle of the hem
        gxs, off = mls.garment_hem_offsets(alpha, {"hem": {"left_x": 10, "right_x": 109, "y": 59}})
        self.assertEqual(off[0], 0)
        self.assertEqual(off[-1], 0)
        self.assertEqual(off.max(), 6)


class HemCPairTests(SimpleTestCase):
    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_replaces_the_hem_c_pair_with_the_garment_hem_centre(self):
        g, glm, blm, mask = _r10_case("28", 4)
        _, ia = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, **R12B)
        _, ib = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, hem_c_pair=True, **R12B)
        q, p, w = ib["pairs"]["hem_c"]
        hl, hr = ib["pairs"]["hem_l"][1], ib["pairs"]["hem_r"][1]
        self.assertAlmostEqual(p[0], (hl[0] + hr[0]) / 2)
        self.assertAlmostEqual(p[1], (hl[1] + hr[1]) / 2)
        gx = int(round((float(glm["hem"]["left_x"]) + float(glm["hem"]["right_x"])) / 2))
        self.assertEqual(q, (float(gx), float(mls.hem_bottom(g[:, :, 3], gx, gx)[0])))
        self.assertEqual(ib["hem_c"]["replaced"][0], [round(v, 1) for v in ia["pairs"]["hem_c"][0]])


R13 = dict(sleeve_variant="C", side_floor=True, side_floor_mode="mask", hem_mode="garment")


class TubeFinishedTests(SimpleTestCase):
    """Round 13 benchmark (docs/06 "Tube sleeve finished, round 13"): tube_arm "finished" (rules a + b) and
    "finished_a" (rule a only, the gate fallback); keyword only, adapt only."""

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_keep_shape_is_identical_on_44_45(self):
        for gid in ("44", "45"):
            g, glm, blm, mask = _r10_case(gid, 3)
            a, _ = mls.tshirt_layer(g, glm, blm, mask, "keep_shape", 1200, 600, **R13)
            for arm in ("finished", "finished_a"):
                with self.subTest(garment=gid, tube_arm=arm):
                    b, ib = mls.tshirt_layer(g, glm, blm, mask, "keep_shape", 1200, 600, sleeve_mode="tube",
                                             tube_arm=arm, **R13)
                    self.assertEqual(int((a != b).any(2).sum()), 0)
                    self.assertNotIn("tube", ib)

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_fallback_has_no_new_holes_and_the_underarm_zone_is_kept(self):
        """Both modes: no figure px covered without the tube is lost (the gate; the arm below the cuff line excluded),
        nothing is cleared in the protected underarm zone and a px covered there without the tube stays covered.
        finished (round 13b): the rule (b) cut is kept out of remove_halo; no enclosed hole is left in the sleeve
        zone (rule #63, filled_px reported)."""
        for gid in ("28", "40"):
            for pk in (1, 4, 6):
                g, glm, blm, mask = _r10_case(gid, pk)
                a, _ = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, **R13)
                c0 = a[:, :, 3] >= 128
                for arm in ("finished_a", "finished"):
                    with self.subTest(garment=gid, avatar=pk, tube_arm=arm):
                        b, ib = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, sleeve_mode="tube",
                                                 tube_arm=arm, debug_map=True, **R13)
                        c1 = b[:, :, 3] >= 128
                        below = np.zeros_like(mask)
                        for side in ("left", "right"):
                            rep = ib["tube"][side]
                            self.assertNotIn("skipped", rep)
                            self.assertGreater(rep["protected_px"], 0)
                            below |= rep["below_cuff_zone"]
                            prot = rep["protected_zone"]
                            self.assertEqual(int((prot & (ib["map"][0] < 0) & c0).sum()), 0)
                            self.assertEqual(int((prot & c0 & ~c1).sum()), 0)
                        self.assertEqual(int((mask & c0 & ~c1 & ~below).sum()), 0)
                        if arm == "finished_a":
                            self.assertNotIn("cleared_below_cuff_px", ib["tube"]["left"])
                            continue
                        self.assertIn("filled_px", ib["tube"])
                        free = np.ones((1202, 602), np.uint8)
                        free[1:-1, 1:-1] = ~c1
                        cv2.floodFill(free, None, (0, 0), 2)
                        zone = mls.sleeve_zone(ib["pairs"], blm, 1200, 600)
                        self.assertEqual(int(((free[1:-1, 1:-1] == 1) & zone).sum()), 0)


R14 = dict(sleeve_mode="tube", tube_arm="finished", **R13)


def _arm_at_cuff(mask, blm, hems, margin):
    """Arm px on the arm-touch rows (arm side of `mls.arm_torso_boundary`) from `margin` px above the cuff line down."""
    Y, X = np.mgrid[0:mask.shape[0], 0:mask.shape[1]]
    out = np.zeros_like(mask)
    for side in ("left", "right"):
        rows, _ = mls.arm_torso_boundary(mask, blm, side)
        a, b, sh = (np.asarray(v, float) for v in hems[side])
        n = np.array([-(b - a)[1], (b - a)[0]])
        n = n / np.linalg.norm(n)
        n = -n if (sh - a) @ n > 0 else n
        below = ((X - a[0]) * n[0] + (Y - a[1]) * n[1]) > -margin
        for y, e in rows.items():
            out[y] = mask[y] & ((X[y] < e) if side == "left" else (X[y] >= e)) & below[y]
    return out


class ArmpitWedgeTests(SimpleTestCase):
    """Round 14 benchmark (docs/06 "Armpit wedge, round 14"): armpit_mode="r14" pins the garment's torso side seam to
    the arm/torso boundary from the cuff row down to the crease, in a local window; keyword only, adapt only,
    default "off"; render_tryon never passes it."""

    def test_unknown_mode_raises(self):
        for bad in ("r15", "r13c"):  # round 13c was deleted (docs/09 #105)
            with self.assertRaises(ValueError):
                _layer(armpit_mode=bad)

    def test_default_is_off(self):
        a = _layer()[0]
        b = _layer(armpit_mode="off")[0]
        self.assertEqual(int((a != b).any(2).sum()), 0)

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_finished_tube_default_is_round_13b_again(self):
        """tube_arm "finished" without the keyword = armpit_mode "off" (round 13b): no armpit report."""
        g, glm, blm, mask = _r10_case("28", 6)
        _, info = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, **R14)
        self.assertNotIn("armpit_zone", info["tube"]["left"])
        self.assertNotIn("armpit_inpaint_px", info["tube"])
        self.assertNotIn("armpit", info)

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_keep_shape_is_identical_on_44_45(self):
        for gid in ("44", "45"):
            g, glm, blm, mask = _r10_case(gid, 3)
            a, _ = mls.tshirt_layer(g, glm, blm, mask, "keep_shape", 1200, 600, **R14)
            for mode in ("r14",):
                with self.subTest(garment=gid, armpit_mode=mode):
                    b, ib = mls.tshirt_layer(g, glm, blm, mask, "keep_shape", 1200, 600, armpit_mode=mode, **R14)
                    self.assertEqual(int((a != b).any(2).sum()), 0)
                    self.assertNotIn("armpit", ib)

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_without_side_floor_it_is_a_no_op(self):
        g, glm, blm, mask = _r10_case("28", 1)
        a, _ = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, sleeve_variant="C")
        b, ib = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, sleeve_variant="C", armpit_mode="r14")
        self.assertEqual(int((a != b).any(2).sum()), 0)
        self.assertNotIn("armpit", ib)

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_wedge_closed_nothing_lost_arm_and_neck_untouched(self):
        """#28 and #40: the wedge is <= 5 px per side (torso side: 0-5), no detached garment fragment in the armpit
        box, no figure px the "off" layer covers is lost (arm skin at / below the cuff line apart: it is cut on the
        boundary on purpose), no arm px more than 1 px below the cuff line is newly covered, nothing changes outside
        the two armpit windows (the neck opening included)."""
        for gid, pks in (("28", (1, 3, 5, 6)), ("40", (3, 6))):
            for pk in pks:
                g, glm, blm, mask = _r10_case(gid, pk)
                a, ia = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, **R14)
                b, ib = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, armpit_mode="r14", **R14)
                with self.subTest(garment=gid, avatar=pk):
                    c0, c1 = a[:, :, 3] >= 128, b[:, :, 3] >= 128
                    w0 = mls.armpit_wedge(a, mask, blm, ia["sleeve_hems"])
                    w1 = mls.armpit_wedge(b, mask, blm, ib["sleeve_hems"])
                    rag = mls.armpit_ragged(b, mask, blm)
                    for side in ("left", "right"):
                        self.assertNotIn("skipped", ib["armpit"][side])
                        self.assertLessEqual(w1[side]["torso_px"], 5)
                        if gid == "28":  # #40: arm skin under its own wavy cuff stays (docs/06), torso side only
                            self.assertLessEqual(w1[side]["px"], 5)
                        self.assertLessEqual(w1[side]["px"], w0[side]["px"])
                        self.assertEqual(rag[side]["fragment_px"], 0)
                    self.assertGreater(w0["left"]["px"] + w0["right"]["px"], 20)  # the defect is there without it
                    self.assertEqual(int((mask & c0 & ~c1 & ~_arm_at_cuff(mask, blm, ia["sleeve_hems"],
                                                                         mls.WEDGE_CUFF_MARGIN)).sum()), 0)
                    self.assertEqual(int((c1 & ~c0 & _arm_at_cuff(mask, blm, ib["sleeve_hems"], -1.0)).sum()), 0)
                    far = np.ones_like(mask)
                    for side in ("left", "right"):
                        rows, crease = mls.arm_torso_boundary(mask, blm, side)
                        x = int(crease[0])
                        far[min(rows) - 40:int(crease[1]) + 90, max(x - 70, 0):x + 70] = False
                    self.assertEqual(int(((a != b).any(2) & far).sum()), 0)

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_boundary_and_notch_helpers(self):
        g, glm, blm, mask = _r10_case("28", 6)
        for side in ("left", "right"):
            rows, crease = mls.arm_torso_boundary(mask, blm, side)
            self.assertGreater(len(rows), 20)  # f-plus: the arm touches the torso for 80-90 rows
            self.assertEqual(min(rows), int(float(blm["armpit"]["y"])))
            self.assertEqual(max(rows) + 1, int(crease[1]))
            notch = mls.garment_notch(g[:, :, 3], glm, side)
            self.assertIsNotNone(notch)
            self.assertGreater(notch[1], float(glm["armpit"]["y"]))  # the alpha notch lies below the marked armpit


R15 = dict(armpit_mode="r14", **R14)


class CuffHemTests(SimpleTestCase):
    """Round 15 benchmark (docs/06 "Cuff hem, round 15"): cuff_mode="hem" lands the garment's real sleeve hem on the
    body cuff line (tube sleeves only); keyword only, default "chord"; render_tryon never passes it."""

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            _layer(cuff_mode="curve")

    def test_default_is_chord(self):
        a = _layer()[0]
        b = _layer(cuff_mode="chord")[0]
        self.assertEqual(int((a != b).any(2).sum()), 0)

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_tube_default_is_round_14_again(self):
        g, glm, blm, mask = _r10_case("43", 3)
        a, ia = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, **R15)
        b, _ = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, cuff_mode="chord", **R15)
        self.assertEqual(int((a != b).any(2).sum()), 0)
        for side in ("left", "right"):
            self.assertNotIn("cuff_hem", ia["tube"][side])
            self.assertNotIn("cuff_cut_px", ia["tube"][side])

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_without_a_tube_and_in_keep_shape_it_is_a_no_op(self):
        g, glm, blm, mask = _r10_case("43", 1)
        a, _ = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, sleeve_variant="C")
        b, ib = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, sleeve_variant="C", cuff_mode="hem")
        self.assertEqual(int((a != b).any(2).sum()), 0)
        self.assertNotIn("tube", ib)
        for gid in ("44", "45"):
            g, glm, blm, mask = _r10_case(gid, 3)
            a, _ = mls.tshirt_layer(g, glm, blm, mask, "keep_shape", 1200, 600, **R15)
            b, _ = mls.tshirt_layer(g, glm, blm, mask, "keep_shape", 1200, 600, cuff_mode="hem", **R15)
            with self.subTest(garment=gid):
                self.assertEqual(int((a != b).any(2).sum()), 0)

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_no_skin_above_the_cuff_nothing_lost_rest_untouched(self):
        """#43, #40, #28: no arm skin above the cuff line beside the boundary, never more wedge px than "chord", no
        fragment, no figure px the "chord" layer covers is lost (arm skin at / below the cuff line apart), no arm px
        more than 1 px below the cuff line newly covered, nothing changes outside the sleeve zone (+ 12 px)."""
        for gid, pks in (("43", (1, 3, 5, 6)), ("40", (3, 6)), ("28", (1, 6))):
            for pk in pks:
                g, glm, blm, mask = _r10_case(gid, pk)
                a, ia = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, **R15)
                b, ib = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, cuff_mode="hem", **R15)
                with self.subTest(garment=gid, avatar=pk):
                    c0, c1 = a[:, :, 3] >= 128, b[:, :, 3] >= 128
                    w0 = mls.armpit_wedge(a, mask, blm, ia["sleeve_hems"])
                    w1 = mls.armpit_wedge(b, mask, blm, ib["sleeve_hems"])
                    rag = mls.armpit_ragged(b, mask, blm)
                    for side in ("left", "right"):
                        self.assertIn("rise_max_body_px", ib["tube"][side]["cuff_hem"])
                        self.assertEqual(w1[side]["arm_px"], 0)
                        self.assertLessEqual(w1[side]["px"], w0[side]["px"])
                        self.assertEqual(rag[side]["fragment_px"], 0)
                        self.assertEqual(ia["tube"][side]["cuff"], ib["tube"][side]["cuff"])  # the body cuff line stays
                    self.assertEqual(int((mask & c0 & ~c1 & ~_arm_at_cuff(mask, blm, ia["sleeve_hems"],
                                                                         mls.WEDGE_CUFF_MARGIN)).sum()), 0)
                    self.assertEqual(int((c1 & ~c0 & _arm_at_cuff(mask, blm, ib["sleeve_hems"], -1.0)).sum()), 0)
                    zone = cv2.dilate(mls.sleeve_zone(ia["pairs"], blm, 1200, 600).astype(np.uint8),
                                      np.ones((25, 25), np.uint8)) > 0
                    self.assertEqual(int(((a != b).any(2) & ~zone).sum()), 0)

    def test_hem_half_width_follows_a_hem_behind_the_chord(self):
        fabric = np.zeros((60, 60), bool)
        fabric[10:30, 5:55] = True  # the hem (row 29) lies 3 px above the chord row 32 beyond x = 33
        fabric[30:34, 5:34] = True
        g_in = lambda q: bool(fabric[int(round(q[1])), int(round(q[0]))])  # noqa: E731
        c, d, back = np.array([30.0, 32.0]), np.array([1.0, 0.0]), np.array([0.0, 1.0])
        self.assertLess(mls._march(g_in, c, d, 40), 5)
        self.assertEqual(mls._hem_half_width(g_in, c, d, back, 20.0, 6.0), 20.0)
        self.assertEqual(mls._hem_half_width(g_in, c, d, back, 40.0, 6.0), 24.5)  # the fabric ends at x = 54
        self.assertLess(mls._hem_half_width(g_in, c, d, back, 20.0, 1.0), 5)  # the hem is farther than max_r


class TubeFringeTests(SimpleTestCase):
    """Round 16 benchmark (docs/06 "Tube fringe, round 16"): tube_fringe="drop" does not draw the tube's photo-fringe
    px over solid MLS fabric (the faint line along the sleeve's inner edge); keyword only, default "keep"."""

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            _layer(tube_fringe="erode")

    def test_default_is_keep(self):
        a = _layer()[0]
        b = _layer(tube_fringe="keep")[0]
        self.assertEqual(int((a != b).any(2).sum()), 0)

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_without_a_tube_and_in_keep_shape_it_is_a_no_op(self):
        g, glm, blm, mask = _r10_case("28", 2)
        a, _ = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, sleeve_variant="C")
        b, ib = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, sleeve_variant="C", tube_fringe="drop")
        self.assertEqual(int((a != b).any(2).sum()), 0)
        self.assertNotIn("tube", ib)
        g, glm, blm, mask = _r10_case("44", 3)
        a, _ = mls.tshirt_layer(g, glm, blm, mask, "keep_shape", 1200, 600, **R15)
        b, _ = mls.tshirt_layer(g, glm, blm, mask, "keep_shape", 1200, 600, tube_fringe="drop", **R15)
        self.assertEqual(int((a != b).any(2).sum()), 0)

    @skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
    def test_fringe_px_not_drawn_nothing_lost_rest_untouched(self):
        """#28, #43, #40: the fringe px are reported in both modes; with "drop" no figure px the "keep" layer covers
        is lost and nothing visible changes farther than 3 px from a fringe px."""
        for gid, pk in (("28", 2), ("28", 4), ("43", 4), ("40", 1)):
            g, glm, blm, mask = _r10_case(gid, pk)
            a, ia = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, cuff_mode="hem", **R15)
            b, ib = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, cuff_mode="hem", tube_fringe="drop", **R15)
            with self.subTest(garment=gid, avatar=pk):
                zone = ia["tube"]["fringe_zone"]
                self.assertGreater(ia["tube"]["fringe_px"], 0)
                self.assertEqual(ia["tube"]["fringe_px"], int(zone.sum()))
                self.assertEqual((ia["tube"]["fringe_mode"], ib["tube"]["fringe_mode"]), ("keep", "drop"))
                self.assertEqual(int((mask & (a[:, :, 3] >= 128) & (b[:, :, 3] < 128)).sum()), 0)
                near = cv2.dilate(zone.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
                changed = (a != b).any(2) & ((a[:, :, 3] > 0) | (b[:, :, 3] > 0))
                self.assertGreater(int(changed.sum()), 0)
                self.assertEqual(int((changed & ~near).sum()), 0)


ON = dict(warp_engine="mls", mls_sleeve="C", mls_tube=True, mls_side_floor="mask", mls_armpit="r14", mls_hem="garment",
          mls_cuff="hem", mls_fringe="drop")
BENCH = dict(sleeve_variant="C", side_floor=True, side_floor_mode="mask", hem_mode="garment", sleeve_mode="tube",
             tube_arm="finished", armpit_mode="r14", cuff_mode="hem",
             tube_fringe="drop")  # the benchmark call (docs/06 rounds 14, 15, 16)


def _prod_layer(gid, pk, mode="adapt", **flags):
    g, glm, blm, mask = _r10_case(gid, pk)
    base = cv2.imread(str(R10_FIXTURE / "avatars" / f"{pk}.png"), cv2.IMREAD_UNCHANGED)
    _, _, dbg = warp.render_tryon(base, blm, [("tshirt", g, glm)], 1200, 600, hem_rule=True,
                                  fit_modes={"tshirt": mode}, **flags)
    return dbg["tshirt_layer"], dbg, (g, glm, blm, mask)


@skipUnless((R10_FIXTURE / "expected").is_dir(), "round 10 fixture missing (see MlsSideFloorOffRegressionTests)")
class ProductionTshirtConfigTests(SimpleTestCase):
    """docs/09 #105: render_tryon gives adapt T-shirts sleeve C + tube "finished" + armpit r14 + side floor "mask" +
    hem "garment" (+ docs/09 #106: cuff "hem" + fringe "drop"); flags TRYON_MLS_TUBE / _SIDE_FLOOR / _ARMPIT / _HEM /
    _CUFF / _FRINGE, each off value = the behaviour before."""

    def test_production_is_the_benchmark_call_on_28_43_40(self):
        for gid in ("28", "43", "40"):
            for pk in range(1, 7):
                with self.subTest(garment=gid, avatar=pk):
                    layer, dbg, (g, glm, blm, mask) = _prod_layer(gid, pk, **ON)
                    want, _ = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, (0.35, 10.0), **BENCH)
                    self.assertEqual(int((layer != want).any(2).sum()), 0)
                    self.assertEqual(dbg["engine"], "mls")
                    self.assertEqual(dbg["tshirt_config"], {"fit_mode": "adapt", "engine": "mls", "sleeve": "C",
                                                            "tube": True, "side_floor": "mask", "armpit": "r14",
                                                            "hem": "garment", "cuff": "hem", "fringe": "drop"})
                    self.assertNotIn("tube_fallback", dbg["quality_warnings"])

    def test_keep_shape_is_unchanged_on_44_45(self):
        for gid in ("44", "45"):
            for pk in (1, 3, 6):
                with self.subTest(garment=gid, avatar=pk):
                    a, da, _ = _prod_layer(gid, pk, "keep_shape", warp_engine="mls")
                    b, db, _ = _prod_layer(gid, pk, "keep_shape", **ON)
                    self.assertEqual(int((a != b).any(2).sum()), 0)
                    self.assertEqual(db["tshirt_config"], {"fit_mode": "keep_shape", "engine": "mls", "sleeve": None,
                                                           "tube": False, "side_floor": "off", "armpit": "off",
                                                           "hem": "mls", "cuff": "chord", "fringe": "keep",
                                                           "keep_neck_dy": db["tshirt_config"]["keep_neck_dy"]})
                    self.assertGreaterEqual(db["tshirt_config"]["keep_neck_dy"], 0)  # docs/09 #121
                    self.assertEqual(da["tshirt_config"], db["tshirt_config"])

    def test_all_flags_off_is_the_previous_production_call(self):
        for gid, pk in (("28", 1), ("43", 5), ("40", 6)):
            with self.subTest(garment=gid, avatar=pk):
                layer, dbg, (g, glm, blm, mask) = _prod_layer(gid, pk, warp_engine="mls", mls_sleeve="C",
                                                              mls_tube=False, mls_side_floor="off", mls_armpit="off",
                                                              mls_hem="mls")
                want, _ = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, (0.35, 10.0), sleeve_variant="C")
                self.assertEqual(int((layer != want).any(2).sum()), 0)
                self.assertEqual(dbg["tshirt_config"], {"fit_mode": "adapt", "engine": "mls", "sleeve": "C",
                                                        "tube": False, "side_floor": "off", "armpit": "off",
                                                        "hem": "mls", "cuff": "chord", "fringe": "keep"})
        a = _prod_layer("28", 1, warp_engine="mls")[0]  # a direct call without the new arguments = the same
        self.assertEqual(int((a != _prod_layer("28", 1, warp_engine="mls", mls_tube=False)[0]).any(2).sum()), 0)

    def test_each_flag_off_switches_only_that_feature_off(self):
        """One flag off = the benchmark call without that keyword. The armpit mode needs the tube and the side floor:
        without one of them it is off and tshirt_config says so."""
        cases = {
            "tube": (dict(mls_tube=False), ("sleeve_mode", "tube_arm", "armpit_mode", "cuff_mode", "tube_fringe"),
                     dict(tube=False, armpit="off", cuff="chord", fringe="keep")),
            "side_floor": (dict(mls_side_floor="off"), ("side_floor", "side_floor_mode", "armpit_mode"),
                           dict(side_floor="off", armpit="off")),
            "armpit": (dict(mls_armpit="off"), ("armpit_mode",), dict(armpit="off")),
            "hem": (dict(mls_hem="mls"), ("hem_mode",), dict(hem="mls")),
            "cuff": (dict(mls_cuff="chord"), ("cuff_mode",), dict(cuff="chord")),
            "fringe": (dict(mls_fringe="keep"), ("tube_fringe",), dict(fringe="keep")),
        }
        on_cfg = {"fit_mode": "adapt", "engine": "mls", "sleeve": "C", "tube": True, "side_floor": "mask",
                  "armpit": "r14", "hem": "garment", "cuff": "hem", "fringe": "drop"}
        for name, (off, drop, cfg) in cases.items():
            with self.subTest(flag=name):
                layer, dbg, (g, glm, blm, mask) = _prod_layer("28", 3, **{**ON, **off})
                kw = {k: v for k, v in BENCH.items() if k not in drop}
                want, _ = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, (0.35, 10.0), **kw)
                self.assertEqual(int((layer != want).any(2).sum()), 0)
                self.assertEqual(dbg["tshirt_config"], {**on_cfg, **cfg})

    def test_tube_that_skips_a_side_falls_back_to_mls_sleeves(self):
        real = mls.tube_sleeves

        def one_side_fails(*a, **kw):
            rep = real(*a, **kw)
            rep["left"] = {"mode": "tube", "skipped": "shoulder or cuff pair dropped"}
            return rep

        with mock.patch("apps.tryon_engine.mls.tube_sleeves", side_effect=one_side_fails) as tube:
            layer, dbg, (g, glm, blm, mask) = _prod_layer("28", 1, **ON)
        self.assertEqual(tube.call_count, 2)  # the layer and the "mask" guard's reference layer; none in the re-render
        self.assertEqual(dbg["quality_warnings"], ["tube_fallback"])
        self.assertEqual((dbg["tshirt_config"]["tube"], dbg["tshirt_config"]["armpit"]), (False, "off"))
        self.assertEqual((dbg["tshirt_config"]["cuff"], dbg["tshirt_config"]["fringe"]), ("chord", "keep"))
        self.assertEqual(dbg["engine"], "mls")
        want, _ = mls.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, (0.35, 10.0), sleeve_variant="C",
                                   side_floor=True, side_floor_mode="mask", hem_mode="garment")
        self.assertEqual(int((layer != want).any(2).sum()), 0)

    def test_unknown_option_raises(self):
        base, lm = body()
        for bad in (dict(mls_side_floor="landmarks"), dict(mls_armpit="r13c"), dict(mls_hem="smooth"),
                    dict(mls_cuff="curve"), dict(mls_fringe="erode")):
            with self.assertRaises(ValueError):
                warp.render_tryon(base, lm, [], warp_engine="mls", **bad)

    def test_settings_and_flags(self):
        from django.core.exceptions import ImproperlyConfigured
        from tryon_studio.settings.base import parse_mls_choice
        for name, (first, second) in (("TRYON_MLS_TUBE", ("1", "0")), ("TRYON_MLS_SIDE_FLOOR", ("mask", "off")),
                                      ("TRYON_MLS_ARMPIT", ("r14", "off")), ("TRYON_MLS_HEM", ("garment", "mls")),
                                      ("TRYON_MLS_CUFF", ("hem", "chord")), ("TRYON_MLS_FRINGE", ("drop", "keep"))):
            self.assertEqual(parse_mls_choice(name, None), first)
            self.assertEqual(parse_mls_choice(name, f" {second.upper()} "), second)
            with self.assertRaises(ImproperlyConfigured):
                parse_mls_choice(name, "r13c")
        flags = render_flags("avatar")
        self.assertEqual({k: flags[k] for k in ("mls_tube", "mls_side_floor", "mls_armpit", "mls_hem")},
                         {"mls_tube": True, "mls_side_floor": "mask", "mls_armpit": "r14", "mls_hem": "garment"})
        self.assertEqual((flags["mls_cuff"], flags["mls_fringe"]), ("hem", "drop"))
        with override_settings(TRYON_MLS_TUBE=False, TRYON_MLS_HEM="mls"):
            flags = render_flags("body")
            self.assertEqual((flags["mls_tube"], flags["mls_hem"]), (False, "mls"))


class KeepNeckTests(SimpleTestCase):
    """docs/09 #121: keep_shape T-shirts move down so the collar line reaches the row regular T-shirts use."""

    def setUp(self):
        self.base, self.lm = body()
        self.mask = warp.figure_mask(self.base)
        self.g, self.glm = shirt()

    def layers(self, **kw):
        old, oi = mls.tshirt_layer(self.g, self.glm, self.lm, self.mask, "keep_shape", **kw)
        new, ni = mls.tshirt_layer(self.g, self.glm, self.lm, self.mask, "keep_shape", keep_neck=True, **kw)
        return old, oi, new, ni

    def target(self):
        ny = self.lm["neck"]["y"]
        return ny + mls.KEEP_NECK_T * (self.lm["shoulder"]["y"] - ny)

    def test_collar_line_lands_on_the_target_and_dy_is_never_negative(self):
        for raise_px in (0, 30):  # as aligned, and a garment whose collar sits 30 px higher on itself
            glm = {**self.glm, "collar": {**self.glm["collar"], "y": self.glm["collar"]["y"] - raise_px}}
            new, ni = mls.tshirt_layer(self.g, glm, self.lm, self.mask, "keep_shape", keep_neck=True)
            dy = ni["keep_neck_dy"]
            self.assertGreaterEqual(dy, 0)
            collar = (ni["pairs"]["neck_l"][1][1] + ni["pairs"]["neck_r"][1][1]) / 2
            if dy > 0:
                self.assertLessEqual(abs(collar - self.target()), 3)
            else:
                self.assertGreaterEqual(collar, self.target() - 0.5)  # already at or below: never moved up

    def test_shoulders_are_bound_to_the_body_and_everything_else_moves_down(self):
        glm = {**self.glm, "collar": {**self.glm["collar"], "y": self.glm["collar"]["y"] - 30}}  # collar rides high
        _, oi = mls.tshirt_layer(self.g, glm, self.lm, self.mask, "keep_shape")
        new, ni = mls.tshirt_layer(self.g, glm, self.lm, self.mask, "keep_shape", keep_neck=True)
        dy = ni["keep_neck_dy"]
        self.assertGreater(dy, 0)
        for k in ("shoulder_l", "shoulder_r"):
            self.assertAlmostEqual(ni["pairs"][k][1][1], self.lm["shoulder"]["y"])
            self.assertAlmostEqual(ni["pairs"][k][1][0], oi["pairs"][k][1][0])
        for k in ("neck_l", "neck_r", "neck_c", "chest_l", "waist_r", "hem_l"):
            self.assertAlmostEqual(ni["pairs"][k][1][1], oi["pairs"][k][1][1] + dy)
        if "neck_opening" in oi:
            self.assertAlmostEqual(ni["neck_opening"]["y0"], oi["neck_opening"]["y0"] + dy)
        # the shoulders stay covered: the garment's top near the shoulder points is on the body's shoulder row, up to
        # the outer-contour halo erosion (HALO_ERODE) and the 1-2 px slope of the line from the collar
        a = new[:, :, 3] >= 128
        for x in (int(self.lm["shoulder"]["left_x"]) + 8, int(self.lm["shoulder"]["right_x"]) - 8):
            self.assertLessEqual(int(np.argmax(a[:, x])), self.lm["shoulder"]["y"] + warp.HALO_ERODE + 2)

    def test_adapt_is_untouched_and_render_tryon_uses_it_for_keep_shape_only(self):
        a0, _ = mls.tshirt_layer(self.g, self.glm, self.lm, self.mask, "adapt")
        a1, ai = mls.tshirt_layer(self.g, self.glm, self.lm, self.mask, "adapt", keep_neck=True)
        np.testing.assert_array_equal(a0, a1)
        self.assertNotIn("keep_neck_dy", ai)
        _, _, d = warp.render_tryon(self.base, self.lm, [("tshirt", self.g, self.glm)], warp_engine="mls",
                                    fit_modes={"tshirt": "keep_shape"})
        self.assertIn("keep_neck_dy", d["tshirt_config"])
        _, _, d = warp.render_tryon(self.base, self.lm, [("tshirt", self.g, self.glm)], warp_engine="mls")
        self.assertNotIn("keep_neck_dy", d["tshirt_config"])
