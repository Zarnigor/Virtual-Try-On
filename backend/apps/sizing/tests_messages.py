from django.test import SimpleTestCase

from apps.sizing import messages
from apps.sizing.fit import check_fit
from apps.sizing.measurements import RANGES, MeasurementsInvalid, validate_measurements

TBODY = {"height_cm": 175, "chest": 100, "waist": 86, "hip": 100, "shoulder_width": 44}
PBODY = {"height_cm": 175, "chest": 100, "waist": 80, "hip": 100, "inseam": 80}


class MessageTests(SimpleTestCase):
    def test_format_cm(self):
        self.assertEqual(messages.format_cm(6.0), "6")
        self.assertEqual(messages.format_cm(6), "6")
        self.assertEqual(messages.format_cm(2.5), "2.5")
        self.assertEqual(messages.format_cm(0.04), "0")

    def test_tor_and_keng(self):
        r = check_fit("tshirt", {"chest_width": 47, "length": 70, "shoulder_width": 46}, False, "adapt", TBODY)
        self.assertEqual(messages.size_mismatch_detail(r), "Bu kiyim sizga mos emas: koʻkrak 6 sm tor.")
        r = check_fit("tshirt", {"chest_width": 61.25, "length": 70, "shoulder_width": 46}, False, "adapt", TBODY)
        self.assertEqual(messages.size_mismatch_detail(r), "Bu kiyim sizga mos emas: koʻkrak 2.5 sm keng.")

    def test_inseam_qisqa_and_uzun(self):
        pants = {"waist_width": 41, "hip_width": 55}
        r = check_fit("pants", {**pants, "inseam": 70}, False, "adapt", PBODY)  # limit 75
        self.assertEqual(messages.size_mismatch_detail(r), "Bu kiyim sizga mos emas: uzunlik 5 sm qisqa.")
        r = check_fit("pants", {**pants, "inseam": 90}, False, "adapt", PBODY)  # limit 88
        self.assertEqual(messages.size_mismatch_detail(r), "Bu kiyim sizga mos emas: uzunlik 2 sm uzun.")

    def test_several_zones_one_line_each_in_zone_order(self):
        r = check_fit("pants", {"waist_width": 30, "hip_width": 70, "inseam": 60}, False, "adapt", PBODY)
        self.assertEqual(messages.size_mismatch_detail(r).split("\n"), [
            "Bu kiyim sizga mos emas: bel 16 sm tor.",  # 60 vs limit 76
            "Bu kiyim sizga mos emas: son 20 sm keng.",  # 140 vs limit 120
            "Bu kiyim sizga mos emas: uzunlik 15 sm qisqa.",  # 60 vs limit 75
        ])

    def test_fixed_texts(self):
        self.assertEqual(messages.GARMENT_SIZE_MISSING, "Bu kiyimning oʻlchamlari kiritilmagan.")
        self.assertEqual(messages.BODY_SIZE_MISSING, "Kiyimni tekshirish uchun oʻlchamlaringizni kiriting.")


class MeasurementValidatorTests(SimpleTestCase):
    def test_every_key_min_max_outside(self):
        for key, (lo, hi) in RANGES.items():
            with self.subTest(key=key):
                self.assertEqual(validate_measurements({key: lo}), {key: lo})
                self.assertEqual(validate_measurements({key: hi}), {key: hi})
                for bad in (lo - 0.1, hi + 0.1):
                    with self.assertRaises(MeasurementsInvalid) as cm:
                        validate_measurements({key: bad})
                    self.assertEqual(cm.exception.key, key)
                    self.assertIn(messages.FIELD_NAMES[key], cm.exception.detail)

    def test_all_optional_and_none_dropped(self):
        self.assertEqual(validate_measurements({}), {})
        self.assertEqual(validate_measurements(None), {})
        self.assertEqual(validate_measurements({"chest": None, "waist": 80}), {"waist": 80})

    def test_wrong_type_and_unknown_key(self):
        for bad in ("90", True, float("nan"), float("inf"), [90]):
            with self.assertRaises(MeasurementsInvalid):
                validate_measurements({"chest": bad})
        with self.assertRaises(MeasurementsInvalid) as cm:
            validate_measurements({"shoulder": 110})  # the circumference is not a fit-check key
        self.assertEqual(cm.exception.key, "shoulder")
        with self.assertRaises(MeasurementsInvalid):
            validate_measurements([1])
