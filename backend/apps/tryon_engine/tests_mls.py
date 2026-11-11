"""TRYON_WARP = parts | mls (docs/09 #98): flag parsing, engine selection, fallback, fit_mode -> k, output size."""
from unittest import mock

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
            self.assertEqual(tasks._do_warp(outfit), {"engine": "mls", "quality_warnings": []})
            self.assertEqual(self._result_shape(outfit), (1200, 600))

    @override_settings(TRYON_WARP="mls")
    def test_incomplete_landmarks_fall_back(self):
        outfit = self._outfit(complete=False)
        with mock.patch("apps.tryon_engine.mls.tshirt_layer") as layer:
            report = tasks._do_warp(outfit)
        layer.assert_not_called()  # landmarks_complete is false: MLS is not attempted
        self.assertEqual(report, {"engine": "parts", "quality_warnings": ["mls_fallback"]})
        self.assertEqual(self._result_shape(outfit), (1200, 600))

    @override_settings(TRYON_WARP="parts")
    def test_parts_default(self):
        outfit = self._outfit()
        self.assertEqual(tasks._do_warp(outfit), {"engine": "parts", "quality_warnings": []})

    @mock.patch("apps.tryon_engine.views.run_tryon.delay")
    def test_response_names_the_engine(self, _):
        self.login(self.user)
        g = self._outfit().garments.first()
        for flag in ("mls", "parts"):
            with override_settings(TRYON_WARP=flag):
                r = self.client.post("/api/tryon/", {"base": "avatar", "avatar_id": self.avatar.id,
                                                     "garment_ids": [g.id]}, format="json")
            self.assertEqual((r.status_code, r.data["engine"]), (202, flag))
