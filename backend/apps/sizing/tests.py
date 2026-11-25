import copy

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from apps.sizing.fit import FitResult, SizesMissing, ZoneCheck, check_fit

# Bodies chosen so every zone starts well inside its window.
TBODY = {"height_cm": 175, "chest": 100, "waist": 86, "hip": 100, "shoulder_width": 44}
PBODY = {"height_cm": 175, "chest": 100, "waist": 80, "hip": 100, "inseam": 80}
TSHIRT = {"chest_width": 55, "length": 70, "shoulder_width": 46}  # chest ease +10, shoulder +2
PANTS = {"waist_width": 41, "hip_width": 55, "inseam": 81}  # waist +2, hip +10, inseam +1


def zone(result, name):
    return next(c for c in result.checks if c.zone == name)


class ZoneThresholdTests(SimpleTestCase):
    """Each zone: just inside, exactly on, just outside both limits (adapt, no stretch)."""

    # (type, zone, garment key, body, base garment, x2 (flat width), min_ease, max_ease)
    CASES = [
        ("tshirt", "chest", "chest_width", TBODY, TSHIRT, True, 0, 20),
        ("tshirt", "shoulder", "shoulder_width", TBODY, TSHIRT, False, -2, 6),
        ("pants", "waist", "waist_width", PBODY, PANTS, True, -4, 6),
        ("pants", "hip", "hip_width", PBODY, PANTS, True, 0, 20),
        ("pants", "inseam", "inseam", PBODY, PANTS, False, -5, 8),
    ]
    BODY_KEY = {"chest": "chest", "shoulder": "shoulder_width", "waist": "waist", "hip": "hip", "inseam": "inseam"}

    def test_boundaries(self):
        for gtype, zname, gkey, body, base, x2, lo, hi in self.CASES:
            with self.subTest(zone=zname):
                b = body[self.BODY_KEY[zname]]
                for ease, verdict, limit in (
                    (lo + 0.2, "ok", None), (lo, "ok", None), (lo - 0.2, "too_small", b + lo),
                    (hi - 0.2, "ok", None), (hi, "ok", None), (hi + 0.2, "too_large", b + hi),
                ):
                    g_cm = b + ease
                    sizes = {**base, gkey: g_cm / 2 if x2 else g_cm}
                    c = zone(check_fit(gtype, sizes, False, "adapt", body), zname)
                    self.assertEqual(c.verdict, verdict, (zname, ease))
                    self.assertEqual(c.limit_cm, limit, (zname, ease))
                    self.assertEqual(c.ease_cm, round(ease, 1))
                    self.assertEqual(c.body_cm, b)
                    self.assertEqual(c.garment_cm, round(g_cm, 1))

    def test_float_noise_on_the_limit_passes(self):
        # 2 x 45.1 = 90.2 (float 90.19999...) on a chest of 90.2: ease exactly 0
        r = check_fit("tshirt", {**TSHIRT, "chest_width": 45.1}, False, "adapt", {**TBODY, "chest": 90.2})
        self.assertEqual(zone(r, "chest").verdict, "ok")

    def test_compare_before_rounding(self):
        # ease -0.04 rounds to -0.0 / 0.0 but is below min_ease 0: too_small
        r = check_fit("tshirt", {**TSHIRT, "chest_width": 49.98}, False, "adapt", TBODY)
        c = zone(r, "chest")
        self.assertEqual(c.verdict, "too_small")
        self.assertEqual(c.ease_cm, 0.0)
        self.assertEqual(c.garment_cm, 100.0)


class StretchTests(SimpleTestCase):
    def test_stretch_shifts_min_for_chest_waist_hip(self):
        # chest ease -3: too_small without stretch, ok with (limit -4); -4 exactly ok, -4.2 too_small
        for gtype, body, base, gkey, zname, b, stretch_lo in (
            ("tshirt", TBODY, TSHIRT, "chest_width", "chest", 100, -4),
            ("pants", PBODY, PANTS, "waist_width", "waist", 80, -8),
            ("pants", PBODY, PANTS, "hip_width", "hip", 100, -4),
        ):
            with self.subTest(zone=zname):
                mid = {**base, gkey: (b + stretch_lo + 1) / 2}
                self.assertEqual(zone(check_fit(gtype, mid, False, "adapt", body), zname).verdict, "too_small")
                self.assertEqual(zone(check_fit(gtype, mid, True, "adapt", body), zname).verdict, "ok")
                on = {**base, gkey: (b + stretch_lo) / 2}
                self.assertEqual(zone(check_fit(gtype, on, True, "adapt", body), zname).verdict, "ok")
                out = {**base, gkey: (b + stretch_lo - 0.2) / 2}
                c = zone(check_fit(gtype, out, True, "adapt", body), zname)
                self.assertEqual((c.verdict, c.limit_cm), ("too_small", b + stretch_lo))

    def test_stretch_does_not_move_other_limits(self):
        # shoulder / inseam: same min with stretch; max limits unchanged everywhere
        r = check_fit("tshirt", {**TSHIRT, "shoulder_width": 41.8}, True, "adapt", TBODY)  # -2.2
        self.assertEqual(zone(r, "shoulder").verdict, "too_small")
        r = check_fit("pants", {**PANTS, "inseam": 74.8}, True, "adapt", PBODY)  # -5.2
        self.assertEqual(zone(r, "inseam").verdict, "too_small")
        r = check_fit("tshirt", {**TSHIRT, "chest_width": 60.1}, True, "adapt", TBODY)  # +20.2
        self.assertEqual(zone(r, "chest").verdict, "too_large")


class KeepShapeTests(SimpleTestCase):
    def test_huge_garment_fits(self):
        r = check_fit("tshirt", {"chest_width": 90, "length": 100, "shoulder_width": 70}, False, "keep_shape", TBODY)
        self.assertTrue(r.fits)
        r = check_fit("pants", {"waist_width": 90, "hip_width": 90, "inseam": 100}, False, "keep_shape", PBODY)
        self.assertTrue(r.fits)
        self.assertEqual(r.warnings, [])  # keep_shape: no too_large check, no warning
        # the same garments get warnings on adapt but still fit (docs/09 #128)
        r = check_fit("tshirt", {"chest_width": 90, "length": 100, "shoulder_width": 70}, False, "adapt", TBODY)
        self.assertEqual([c.verdict for c in r.checks], ["too_large", "too_large"])
        self.assertTrue(r.fits)
        self.assertEqual([c.zone for c in r.warnings], ["chest", "shoulder"])

    def test_too_small_still_fails(self):
        r = check_fit("tshirt", {**TSHIRT, "chest_width": 45}, False, "keep_shape", TBODY)
        self.assertFalse(r.fits)
        self.assertEqual(zone(r, "chest").verdict, "too_small")


class InseamTests(SimpleTestCase):
    def test_estimated_from_height(self):
        body = {k: v for k, v in PBODY.items() if k != "inseam"}  # 175 x 0.45 = 78.75
        c = zone(check_fit("pants", PANTS, False, "adapt", body), "inseam")
        self.assertEqual(c.body_cm, 78.8)
        self.assertEqual(c.ease_cm, round(81 - 78.75, 1))

    def test_given_inseam_wins(self):
        c = zone(check_fit("pants", PANTS, False, "adapt", {**PBODY, "inseam": 70}), "inseam")
        self.assertEqual(c.body_cm, 70)
        self.assertEqual(c.verdict, "too_large")

    def test_tshirt_needs_no_height(self):
        body = {k: v for k, v in TBODY.items() if k != "height_cm"}
        self.assertTrue(check_fit("tshirt", TSHIRT, False, "adapt", body).fits)


class WarningTests(SimpleTestCase):
    def test_fits_means_no_too_small(self):
        r = check_fit("tshirt", {**TSHIRT, "chest_width": 61}, False, "adapt", TBODY)  # +22: too_large
        self.assertTrue(r.fits)
        self.assertEqual([(c.zone, c.verdict) for c in r.warnings], [("chest", "too_large")])
        r = check_fit("tshirt", {**TSHIRT, "chest_width": 40, "shoulder_width": 60}, False, "adapt", TBODY)
        self.assertFalse(r.fits)
        self.assertEqual([c.zone for c in r.warnings], ["shoulder"])
        self.assertEqual(check_fit("tshirt", TSHIRT, False, "adapt", TBODY).warnings, [])


class ReportTests(SimpleTestCase):
    def test_all_ok(self):
        r = check_fit("tshirt", TSHIRT, False, "adapt", TBODY)
        self.assertIsInstance(r, FitResult)
        self.assertTrue(r.fits)
        self.assertTrue(all(isinstance(c, ZoneCheck) and c.limit_cm is None for c in r.checks))

    def test_several_failing_zones_in_fixed_order(self):
        r = check_fit("tshirt", {**TSHIRT, "chest_width": 40, "shoulder_width": 60}, False, "adapt", TBODY)
        self.assertFalse(r.fits)
        self.assertEqual([(c.zone, c.verdict) for c in r.checks], [("chest", "too_small"), ("shoulder", "too_large")])
        r = check_fit("pants", {"waist_width": 30, "hip_width": 70, "inseam": 60}, False, "adapt", PBODY)
        self.assertEqual([(c.zone, c.verdict) for c in r.checks],
                         [("waist", "too_small"), ("hip", "too_large"), ("inseam", "too_small")])

    def test_optional_garment_fields_ignored(self):
        r = check_fit("tshirt", {**TSHIRT, "waist_width": 20, "sleeve_length": 5}, False, "adapt", TBODY)
        self.assertEqual([c.zone for c in r.checks], ["chest", "shoulder"])
        r = check_fit("pants", {**PANTS, "thigh_width": 15, "leg_opening": 8}, False, "adapt", PBODY)
        self.assertEqual([c.zone for c in r.checks], ["waist", "hip", "inseam"])

    def test_result_is_frozen(self):
        r = check_fit("tshirt", TSHIRT, False, "adapt", TBODY)
        with self.assertRaises(Exception):
            r.fits = False
        with self.assertRaises(Exception):
            r.checks[0].verdict = "too_small"


class MissingAndErrorTests(SimpleTestCase):
    def test_missing_garment_key(self):
        with self.assertRaises(SizesMissing) as cm:
            check_fit("tshirt", {"length": 70}, False, "adapt", TBODY)
        self.assertEqual((cm.exception.side, cm.exception.keys), ("garment", ["chest_width", "shoulder_width"]))
        with self.assertRaises(SizesMissing) as cm:
            check_fit("pants", {**PANTS, "inseam": None}, False, "adapt", PBODY)
        self.assertEqual((cm.exception.side, cm.exception.keys), ("garment", ["inseam"]))

    def test_garment_checked_before_body(self):
        with self.assertRaises(SizesMissing) as cm:
            check_fit("tshirt", None, False, "adapt", None)
        self.assertEqual((cm.exception.side, cm.exception.keys), ("garment", ["chest_width", "shoulder_width"]))

    def test_none_body(self):
        with self.assertRaises(SizesMissing) as cm:
            check_fit("pants", PANTS, False, "adapt", None)
        self.assertEqual((cm.exception.side, cm.exception.keys), ("body", ["waist", "hip", "inseam"]))

    def test_missing_body_key(self):
        with self.assertRaises(SizesMissing) as cm:
            check_fit("tshirt", TSHIRT, False, "adapt", {"chest": 100})
        self.assertEqual((cm.exception.side, cm.exception.keys), ("body", ["shoulder_width"]))
        # the circumference `shoulder` (Body/Avatar.measurements) is NOT used as a width
        with self.assertRaises(SizesMissing) as cm:
            check_fit("tshirt", TSHIRT, False, "adapt", {"chest": 100, "shoulder": 116})
        self.assertEqual(cm.exception.keys, ["shoulder_width"])
        # pants: no inseam and no height -> inseam missing
        with self.assertRaises(SizesMissing) as cm:
            check_fit("pants", PANTS, False, "adapt", {"waist": 80, "hip": 100})
        self.assertEqual((cm.exception.side, cm.exception.keys), ("body", ["inseam"]))

    def test_non_numbers_count_as_missing(self):
        for bad in ("50", True, float("nan"), float("inf")):
            with self.assertRaises(SizesMissing):
                check_fit("tshirt", {**TSHIRT, "chest_width": bad}, False, "adapt", TBODY)
            with self.assertRaises(SizesMissing):
                check_fit("tshirt", TSHIRT, False, "adapt", {**TBODY, "chest": bad})

    def test_unknown_type_or_fit_mode(self):
        with self.assertRaises(ValueError):
            check_fit("shoes", TSHIRT, False, "adapt", TBODY)
        with self.assertRaises(ValueError):
            check_fit("tshirt", TSHIRT, False, "tight", TBODY)


class RulesTests(SimpleTestCase):
    def test_settings_are_the_default(self):
        self.assertIn("tshirt", settings.FIT_RULES)
        custom = copy.deepcopy(settings.FIT_RULES)
        custom["tshirt"]["chest"]["max_ease"] = 5
        with override_settings(FIT_RULES=custom):
            r = check_fit("tshirt", TSHIRT, False, "adapt", TBODY)  # chest ease +10
        self.assertEqual(zone(r, "chest").verdict, "too_large")

    def test_custom_rules_override_settings(self):
        custom = copy.deepcopy(settings.FIT_RULES)
        custom["tshirt"]["chest"]["max_ease"] = 5
        custom["BODY_INSEAM_HEIGHT_RATIO"] = 0.5
        r = check_fit("tshirt", TSHIRT, False, "adapt", TBODY, rules=custom)
        self.assertEqual((zone(r, "chest").verdict, zone(r, "chest").limit_cm), ("too_large", 105))
        self.assertTrue(check_fit("tshirt", TSHIRT, False, "adapt", TBODY).fits)  # settings untouched
        body = {k: v for k, v in PBODY.items() if k != "inseam"}
        self.assertEqual(zone(check_fit("pants", PANTS, False, "adapt", body, rules=custom), "inseam").body_cm, 87.5)
