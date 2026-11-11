"""Garment landmark validation: the pure checker and PATCH garments/{id}/landmarks/."""
import copy

from django.core.files.base import ContentFile
from django.test import SimpleTestCase

from apps.garments.landmark_checks import (
    LandmarksInvalid, engine_landmarks, for_storage, landmarks_complete, validate_garment_landmarks,
)
from apps.garments.models import Garment
from apps.testing import MediaTestCase, png_bytes

W, H = 480, 640

# Same records as frontend geometry.test.ts (480 x 640). `chest.width` is an extra key that must be kept.
TSHIRT = {
    "shoulder": {"y": 198, "left_x": 124, "right_x": 356},
    "chest": {"y": 326, "left_x": 140, "right_x": 340, "width": 200},
    "waist": {"y": 416, "left_x": 150, "right_x": 330},
    "hem": {"y": 488, "left_x": 142, "right_x": 338},
    "sleeve_cuff_outer": {"left": {"x": 20, "y": 270}, "right": {"x": 460, "y": 270}},
    "sleeve_cuff_inner": {"left": {"x": 60, "y": 310}, "right": {"x": 420, "y": 310}},
}
# Marked before 2026-11-11: one sleeve_end point per side instead of the cuff corners (accepted on read only).
LEGACY = {**{k: v for k, v in TSHIRT.items() if not k.startswith("sleeve_cuff")},
          "sleeve_end": {"left": {"x": 20, "y": 290}, "right": {"x": 460, "y": 290}}}
# Every point of the new set (docs/09 #92).
FULL = {**TSHIRT, "armpit": {"y": 300, "left_x": 130, "right_x": 350},
        "collar": {"y": 190, "left_x": 200, "right_x": 280}, "collar_bottom": {"x": 240, "y": 230}}
PANTS = {
    "waist": {"y": 30, "left_x": 120, "right_x": 360, "center_x": 240},
    "hip": {"y": 160, "left_x": 110, "right_x": 370},
    "crotch": {"y": 250, "center_x": 238},
    "knee": {
        "y": 420,
        "left_leg": {"left_x": 80, "right_x": 200, "y": 420},
        "right_leg": {"left_x": 280, "right_x": 400, "y": 420},
    },
    "hem": {
        "left_leg": {"left_x": 90, "right_x": 190, "y": 610},
        "right_leg": {"left_x": 290, "right_x": 390, "y": 610},
    },
}


def with_value(record, path, value):
    out = copy.deepcopy(record)
    *parents, last = path.split(".")
    cur = out
    for k in parents:
        cur = cur[k]
    if value is _DELETE:
        del cur[last]
    else:
        cur[last] = value
    return out


_DELETE = object()


class LandmarkCheckTests(SimpleTestCase):
    def check(self, gtype, record):
        validate_garment_landmarks(gtype, record, W, H)

    def assertInvalid(self, gtype, record, reason, group_name):
        with self.assertRaises(LandmarksInvalid) as ctx:
            self.check(gtype, record)
        self.assertEqual(ctx.exception.reason, reason)
        self.assertIn(f"«{group_name}»", ctx.exception.detail)
        return ctx.exception

    def test_valid_records_pass(self):
        self.check("tshirt", TSHIRT)
        self.check("pants", PANTS)
        self.check("tshirt", with_value(TSHIRT, "shoulder.left_x", 124.5))  # floats are fine

    def test_old_record_with_a_small_gap_is_accepted(self):
        # the editor keeps 4 px, the backend only needs a strict "<": 1-3 px gaps from old records pass
        for gap in (1, 2, 3):
            self.check("tshirt", with_value(TSHIRT, "shoulder.right_x", 124 + gap))
            self.check("pants", with_value(PANTS, "knee.right_leg.left_x", 200 + gap))
            self.check("pants", with_value(PANTS, "hip.y", 30 + gap))

    def test_keys_of_the_other_type_are_rejected(self):
        self.assertInvalid("pants", TSHIRT, "missing", "Bel")  # no waist.center_x, no hip ...
        self.assertInvalid("tshirt", PANTS, "missing", "Yelka")

    def test_partial_payload_names_the_missing_group(self):
        self.assertInvalid("tshirt", with_value(TSHIRT, "hem", _DELETE), "missing", "Pastki")
        self.assertInvalid("tshirt", with_value(TSHIRT, "sleeve_cuff_inner.right.y", _DELETE), "missing",
                           "Yeng uchi (ichki)")
        self.assertInvalid("pants", with_value(PANTS, "crotch.center_x", _DELETE), "missing", "Qoʻshilish")
        self.assertInvalid("pants", with_value(PANTS, "knee.y", _DELETE), "missing", "Tizza")
        self.assertInvalid("pants", with_value(PANTS, "hem.right_leg", _DELETE), "missing", "Pocha")
        self.assertInvalid("tshirt", {}, "missing", "Yelka")

    def test_values_must_be_finite_numbers(self):
        for bad in (float("nan"), float("inf"), float("-inf"), "120", None, True, False, [120], {"v": 1}):
            self.assertInvalid("tshirt", with_value(TSHIRT, "chest.left_x", bad), "missing", "Koʻkrak")
        self.assertInvalid("pants", with_value(PANTS, "knee.left_leg", "x"), "missing", "Tizza")

    def test_out_of_bounds(self):
        self.check("tshirt", with_value(TSHIRT, "sleeve_cuff_outer.right.x", W))  # edges are inside
        self.check("tshirt", with_value(TSHIRT, "sleeve_cuff_outer.left.x", 0))
        self.assertInvalid("tshirt", with_value(TSHIRT, "sleeve_cuff_outer.right.x", W + 1), "bounds",
                           "Yeng uchi (tashqi)")
        self.assertInvalid("tshirt", with_value(TSHIRT, "shoulder.y", -1), "bounds", "Yelka")
        self.assertInvalid("pants", with_value(PANTS, "hem.left_leg.y", H + 0.5), "bounds", "Pocha")

    def test_reversed_x(self):
        self.assertInvalid("tshirt", with_value(TSHIRT, "waist.left_x", 335), "x_order", "Bel")
        self.assertInvalid("tshirt", with_value(TSHIRT, "chest.right_x", 140), "x_order", "Koʻkrak")  # equal
        self.assertInvalid("tshirt", with_value(TSHIRT, "sleeve_cuff_outer.left.x", 470), "cuff_side",
                           "Yeng uchi (tashqi)")
        self.assertInvalid("pants", with_value(PANTS, "hip.left_x", 380), "x_order", "Son")
        self.assertInvalid("pants", with_value(PANTS, "hem.right_leg.right_x", 280), "x_order", "Pocha")

    def test_legs_must_not_overlap(self):
        self.assertInvalid("pants", with_value(PANTS, "knee.left_leg.right_x", 285), "legs", "Tizza")
        self.assertInvalid("pants", with_value(PANTS, "hem.right_leg.left_x", 190), "legs", "Pocha")  # equal

    def test_waist_center_between_waist_points(self):
        self.assertInvalid("pants", with_value(PANTS, "waist.center_x", 120), "center", "Bel")  # left side
        self.assertInvalid("pants", with_value(PANTS, "waist.center_x", 361), "center", "Bel")  # right side

    def test_waist_center_inside_the_hip_by_5_px(self):
        # waist wider than hip so only the hip rule fails
        wide = with_value(with_value(PANTS, "waist.left_x", 50), "waist.right_x", 430)
        self.check("pants", with_value(wide, "waist.center_x", 116))  # 110 + 5 < 116
        self.check("pants", with_value(wide, "waist.center_x", 364))  # 364 < 370 - 5
        e = self.assertInvalid("pants", with_value(wide, "waist.center_x", 115), "center_hip", "Bel")
        self.assertIn("«Son»", e.detail)
        self.assertInvalid("pants", with_value(wide, "waist.center_x", 365), "center_hip", "Bel")

    def test_reversed_y(self):
        e = self.assertInvalid("tshirt", with_value(TSHIRT, "chest.y", 190), "y_order", "Koʻkrak")
        self.assertIn("«Yelka»", e.detail)
        self.assertInvalid("tshirt", with_value(TSHIRT, "hem.y", 416), "y_order", "Pastki")  # equal
        self.assertInvalid("tshirt", with_value(TSHIRT, "sleeve_cuff_outer.right.y", 198), "y_order",
                           "Yeng uchi (tashqi)")
        self.assertInvalid("pants", with_value(PANTS, "crotch.y", 150), "y_order", "Qoʻshilish")
        self.assertInvalid("pants", with_value(PANTS, "knee.y", 240), "y_order", "Tizza")

    def test_pants_hem_order_uses_the_lower_leg(self):
        # one hem leg above the knee is fine while the other is below (the larger y counts)
        self.check("pants", with_value(PANTS, "hem.left_leg.y", 400))
        both_up = with_value(with_value(PANTS, "hem.left_leg.y", 400), "hem.right_leg.y", 410)
        self.assertInvalid("pants", both_up, "y_order", "Pocha")


class LandmarkEndpointTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.owner = self.make_user()
        self.login(self.owner)

    def garment(self, gtype="tshirt", ready=True):
        g = Garment(owner=self.owner, type=gtype)
        g.original_image.save("o.png", ContentFile(png_bytes(W, H)), save=False)
        if ready:
            g.image.save("g.png", ContentFile(png_bytes(W, H)), save=False)
        g.save()
        return g

    def patch(self, g, landmarks):
        return self.client.patch(f"/api/garments/{g.id}/landmarks/", {"landmarks": landmarks}, format="json")

    def test_valid_payload_is_saved_unchanged(self):
        for gtype, record in (("tshirt", TSHIRT), ("pants", PANTS)):
            g = self.garment(gtype)
            payload = {**copy.deepcopy(record), "note": {"source": "editor"}}  # unknown keys survive
            r = self.patch(g, payload)
            self.assertEqual(r.status_code, 200, r.data)
            g.refresh_from_db()
            self.assertEqual(g.landmarks, payload)
            self.assertEqual(r.data["landmarks"], payload)

    def test_invalid_payload_is_rejected_and_nothing_is_saved(self):
        g = self.garment("tshirt")
        cases = [
            (PANTS, "Yelka"),  # keys of the wrong type
            (with_value(TSHIRT, "hem", _DELETE), "Pastki"),  # partial
            (with_value(TSHIRT, "chest.left_x", "140"), "Koʻkrak"),  # string
            (with_value(TSHIRT, "chest.left_x", True), "Koʻkrak"),  # bool
            (with_value(TSHIRT, "sleeve_cuff_outer.right.x", W + 1), "Yeng uchi (tashqi)"),  # out of bounds
            (with_value(TSHIRT, "waist.left_x", 335), "Bel"),  # reversed x
            (with_value(TSHIRT, "chest.y", 190), "Koʻkrak"),  # reversed y
        ]
        for record, group in cases:
            r = self.patch(g, record)
            self.assertEqual((r.status_code, r.data["code"]), (400, "LANDMARKS_INVALID"), record)
            self.assertIn(f"«{group}»", r.data["detail"])
            self.assertEqual(set(r.data), {"code", "detail"})
        g.refresh_from_db()
        self.assertEqual(g.landmarks, {})

    def test_pants_center_rules_through_the_api(self):
        g = self.garment("pants")
        r = self.patch(g, with_value(PANTS, "waist.center_x", 112))
        self.assertEqual((r.status_code, r.data["code"]), (400, "LANDMARKS_INVALID"))
        self.assertEqual(r.data["detail"], "«Bel»: markaz nuqtasi chap va oʻng nuqtalar orasida boʻlsin.")

    def test_nan_in_json_is_rejected(self):
        g = self.garment("tshirt")
        body = '{"landmarks": {"shoulder": {"y": NaN, "left_x": 124, "right_x": 356}}}'
        r = self.client.patch(f"/api/garments/{g.id}/landmarks/", body, content_type="application/json")
        self.assertEqual(r.status_code, 400)
        g.refresh_from_db()
        self.assertEqual(g.landmarks, {})

    def test_not_ready_still_wins(self):
        g = self.garment("tshirt", ready=False)
        r = self.patch(g, TSHIRT)  # a valid payload, but there is no cleaned image yet
        self.assertEqual((r.status_code, r.data["code"]), (409, "GARMENT_NOT_READY"))

    def test_bounds_come_from_the_cleaned_png(self):
        g = Garment(owner=self.owner, type="tshirt")
        g.original_image.save("o.png", ContentFile(png_bytes(W, H)), save=False)
        g.image.save("g.png", ContentFile(png_bytes(300, H)), save=False)  # cropped narrower than the original
        g.save()
        r = self.patch(g, TSHIRT)  # sleeve_cuff_outer.right.x = 460 > 300
        self.assertEqual((r.status_code, r.data["code"]), (400, "LANDMARKS_INVALID"))


class TshirtSetTests(SimpleTestCase):
    """The extended T-shirt set (docs/09 #92): schema, each sanity check (pass + fail), legacy sleeve_end, flag."""

    def check(self, record, mode="write", bbox=None):
        return validate_garment_landmarks("tshirt", record, W, H, bbox=bbox, mode=mode)

    def invalid(self, record, reason, group, mode="write"):
        with self.assertRaises(LandmarksInvalid) as ctx:
            self.check(record, mode)
        self.assertEqual(ctx.exception.reason, reason)
        self.assertIn(f"«{group}»", ctx.exception.detail)

    # schema
    def test_new_points_are_optional_and_each_group_is_all_or_nothing(self):
        self.assertEqual(self.check(TSHIRT), [])  # required only
        self.assertEqual(self.check(FULL), [])  # every point
        for g in ("armpit", "collar", "collar_bottom"):
            self.check(with_value(FULL, g, _DELETE))  # each optional group may be missing
        self.invalid(with_value(FULL, "armpit.left_x", _DELETE), "missing", "Qoʻltiq")  # but never half of it
        self.invalid(with_value(FULL, "collar_bottom.y", "1"), "missing", "Yoqa pasti")
        self.invalid(with_value(TSHIRT, "sleeve_cuff_outer", _DELETE), "missing", "Yeng uchi (tashqi)")  # required
        self.invalid(with_value(FULL, "collar.right_x", W + 1), "bounds", "Yoqa")

    # order checks (errors)
    def test_collar_bottom_below_the_collar_edges(self):
        self.check(with_value(FULL, "collar_bottom.y", 191))
        self.invalid(with_value(FULL, "collar_bottom.y", 190), "y_order", "Yoqa pasti")
        self.invalid(with_value(FULL, "collar_bottom.x", 199), "center", "Yoqa pasti")
        self.invalid(with_value(FULL, "collar.left_x", 290), "x_order", "Yoqa")

    def test_armpit_below_the_shoulder(self):
        self.check(with_value(FULL, "armpit.y", 199))
        self.invalid(with_value(FULL, "armpit.y", 198), "y_order", "Qoʻltiq")

    def test_oversized_armpit_below_the_chest_passes(self):
        # docs/09 #94: oversized T-shirts have the underarm below the chest line
        self.check(with_value(FULL, "armpit.y", 326))
        self.check(with_value(FULL, "armpit.y", 360))
        self.check(with_value(FULL, "armpit.y", 415))  # still above the waist: no rule ties it to the chest
        self.invalid(with_value(FULL, "armpit.left_x", 360), "x_order", "Qoʻltiq")

    def test_chest_waist_hem_order(self):
        self.check(with_value(FULL, "waist.y", 327))
        self.invalid(with_value(FULL, "waist.y", 326), "y_order", "Bel")
        self.invalid(with_value(FULL, "hem.y", 416), "y_order", "Pastki")

    def test_cuff_corners_on_their_own_sleeve(self):
        self.check(with_value(FULL, "sleeve_cuff_inner.left.x", 239))  # still left of the centre (240)
        self.invalid(with_value(FULL, "sleeve_cuff_inner.left.x", 240), "cuff_side", "Yeng uchi (ichki)")
        self.invalid(with_value(FULL, "sleeve_cuff_outer.right.x", 200), "cuff_side", "Yeng uchi (tashqi)")
        self.invalid(with_value(FULL, "sleeve_cuff_inner.right.y", 198), "y_order", "Yeng uchi (ichki)")

    def test_outer_and_inner_cuff_corners_not_swapped(self):
        swapped = with_value(with_value(FULL, "sleeve_cuff_outer.left", {"x": 60, "y": 310}),
                             "sleeve_cuff_inner.left", {"x": 20, "y": 270})
        self.invalid(swapped, "cuff_order", "Yeng uchi (tashqi)")
        right = with_value(with_value(FULL, "sleeve_cuff_outer.right", {"x": 420, "y": 310}),
                           "sleeve_cuff_inner.right", {"x": 460, "y": 270})
        self.invalid(right, "cuff_order", "Yeng uchi (tashqi)")
        # independent of the optional armpit
        self.check(with_value(FULL, "armpit", _DELETE))
        self.invalid(with_value(swapped, "armpit", _DELETE), "cuff_order", "Yeng uchi (tashqi)")

    # range checks (warnings, never errors)
    def test_collar_near_the_shoulder_line(self):
        self.assertEqual(self.check(with_value(FULL, "collar.y", 198 - 34)), [])  # 34 < 0.15 x 232
        w = self.check(with_value(FULL, "collar.y", 198 - 40))
        self.assertEqual([x["code"] for x in w], ["collar_far"])
        self.assertIn("«Yoqa»", w[0]["detail"])

    def test_points_inside_the_garment_bounding_box(self):
        self.assertEqual(self.check(FULL, bbox=(18, 188, 462, 490)), [])
        self.assertEqual(self.check(FULL, bbox=(20, 190, 460, 488)), [])  # on the edge
        w = self.check(FULL, bbox=(40, 188, 462, 490))  # left cuff outer at x 20 is outside
        self.assertEqual([(x["code"], x["group"]) for x in w], [("outside_garment", "sleeve_cuff_outer")])

    # legacy sleeve_end
    def test_legacy_sleeve_end_is_read_but_never_written(self):
        self.check(LEGACY, mode="read")
        self.invalid(LEGACY, "missing", "Yeng uchi (tashqi)", mode="write")
        self.invalid(with_value(LEGACY, "sleeve_end.left.x", 470), "x_order", "Yeng", mode="read")
        stored = for_storage("tshirt", {**FULL, "sleeve_end": LEGACY["sleeve_end"]})
        self.assertNotIn("sleeve_end", stored)
        self.assertEqual(stored, FULL)
        self.assertIs(for_storage("pants", PANTS), PANTS)

    def test_engine_gets_a_sleeve_end_from_the_cuffs(self):
        lm = engine_landmarks("tshirt", TSHIRT)
        self.assertEqual(lm["sleeve_end"], {"left": {"x": 40, "y": 290}, "right": {"x": 440, "y": 290}})
        self.assertNotIn("sleeve_end", TSHIRT)  # nothing written back
        self.assertIs(engine_landmarks("tshirt", LEGACY), LEGACY)

    # flag
    def test_landmarks_complete(self):
        self.assertTrue(landmarks_complete("tshirt", FULL))
        self.assertFalse(landmarks_complete("tshirt", TSHIRT))
        self.assertFalse(landmarks_complete("tshirt", LEGACY))
        self.assertFalse(landmarks_complete("tshirt", with_value(FULL, "collar_bottom.x", _DELETE)))
        self.assertFalse(landmarks_complete("tshirt", {}))
        self.assertTrue(landmarks_complete("pants", PANTS))


class TshirtSetEndpointTests(MediaTestCase):
    """PATCH stores the new set without sleeve_end, returns warnings; GET exposes landmarks_complete."""

    def setUp(self):
        super().setUp()
        self.owner = self.make_user()
        self.login(self.owner)

    garment = LandmarkEndpointTests.garment
    patch = LandmarkEndpointTests.patch

    def test_flag_and_warnings_through_the_api(self):
        g = self.garment("tshirt")
        self.assertFalse(self.client.get(f"/api/garments/{g.id}/").data["landmarks_complete"])
        r = self.patch(g, TSHIRT)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data["landmarks_complete"])
        self.assertEqual(r.data["landmark_warnings"], [])
        r = self.patch(g, with_value(FULL, "collar.y", 150))  # far above the shoulder line: saved, with a warning
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["landmarks_complete"])
        self.assertEqual([w["code"] for w in r.data["landmark_warnings"]], ["collar_far"])
        self.assertTrue(self.client.get(f"/api/garments/{g.id}/").data["landmarks_complete"])
        p = self.garment("pants")
        self.patch(p, PANTS)
        self.assertTrue(self.client.get(f"/api/garments/{p.id}/").data["landmarks_complete"])

    def test_legacy_sleeve_end_is_not_written(self):
        g = self.garment("tshirt")
        r = self.patch(g, LEGACY)  # an old client sending only sleeve_end: the cuffs are required now
        self.assertEqual((r.status_code, r.data["code"]), (400, "LANDMARKS_INVALID"))
        r = self.patch(g, {**FULL, "sleeve_end": LEGACY["sleeve_end"]})
        self.assertEqual(r.status_code, 200, r.data)
        g.refresh_from_db()
        self.assertNotIn("sleeve_end", g.landmarks)
        self.assertEqual(g.landmarks, FULL)

    def test_stored_legacy_record_still_reads(self):
        g = self.garment("tshirt")
        Garment.objects.filter(pk=g.pk).update(landmarks=LEGACY)  # marked before the change
        r = self.client.get(f"/api/garments/{g.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["landmarks"], LEGACY)
        self.assertFalse(r.data["landmarks_complete"])

