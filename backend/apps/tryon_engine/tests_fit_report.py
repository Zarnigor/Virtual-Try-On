"""Fit check calibration report (apps/tryon_engine/fit_report.py, tools/fit_check/matrix.py)."""
from django.core.files.base import ContentFile

from apps.avatars.models import Avatar
from apps.garments.models import Garment
from apps.testing import MediaTestCase, png_bytes
from apps.tryon_engine import fit_report

M = {"shoulder": 116, "chest": 100, "waist": 80, "hip": 100, "shoulder_width": 44}


class FitReportTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.male = Avatar.objects.create(sex="male", build="average", height_cm=178, measurements=dict(M))
        self.female = Avatar.objects.create(sex="female", build="slim", height_cm=165,
                                            measurements={"chest": 82, "waist": 64, "hip": 90})  # no shoulder_width
        self.ok = self.garment("tshirt", {"chest_width": 55, "length": 70, "shoulder_width": 46}, gender="male")
        self.big = self.garment("tshirt", {"chest_width": 62, "length": 70, "shoulder_width": 46}, gender="male")
        self.small = self.garment("tshirt", {"chest_width": 40, "length": 70, "shoulder_width": 46}, gender="male")
        self.pants = self.garment("pants", {"waist_width": 41, "hip_width": 55, "inseam": 81})  # unisex
        self.none = self.garment("tshirt", None)
        self.partial = self.garment("pants", {"waist_width": 40})

    def garment(self, gtype, sizes, **kw):
        g = Garment(owner=None, type=gtype, sizes=sizes, **kw)
        g.image.save("g.png", ContentFile(png_bytes()), save=False)
        g.save()
        return g

    def report(self):
        return fit_report.build_matrix(Garment.objects.order_by("pk"), Avatar.objects.order_by("pk"))

    def cell(self, report, g, a):
        return next((c for c in report["cells"] if c["garment_id"] == g.pk and c["avatar_id"] == a.pk), None)

    def test_matrix_cells(self):
        r = self.report()
        self.assertEqual([g["id"] for g in r["garments"]], [self.ok.pk, self.big.pk, self.small.pk, self.pants.pk])
        c = self.cell(r, self.ok, self.male)
        self.assertEqual((c["overall"], c["text"]), ("fits", "chest +10.0 ok | shoulder +2.0 ok"))
        self.assertEqual(self.cell(r, self.big, self.male)["overall"], "katta")
        self.assertEqual(self.cell(r, self.small, self.male)["overall"], "mos emas")
        self.assertEqual(self.cell(r, self.pants, self.male)["overall"], "fits")  # inseam 178 x 0.45 = 80.1

    def test_gender_filter_and_missing_avatar_sizes(self):
        r = self.report()
        self.assertIsNone(self.cell(r, self.ok, self.female))  # male T-shirt: not shown for the female avatar
        c = self.cell(r, self.pants, self.female)  # unisex pants: shown; the female avatar has the pants keys
        self.assertEqual(c["overall"], "katta")  # waist 82 vs 64: +18 > +6
        self.assertTrue(c["text"].startswith("waist +18.0 too_large"))
        self.assertEqual(r["skipped_avatars"], [{"avatar_id": self.female.pk, "reason": "missing shoulder_width"}])
        self.female.measurements = {}
        self.female.save()
        c = self.cell(self.report(), self.pants, self.female)
        self.assertEqual((c["overall"], c["text"]), ("BODY_SIZE_MISSING", "BODY_SIZE_MISSING: waist, hip"))

    def test_skipped_garments(self):
        r = self.report()
        self.assertEqual(r["skipped_garments"], [{"garment_id": self.none.pk, "reason": "no sizes"},
                                                 {"garment_id": self.partial.pk, "reason": "sizes incomplete"}])

    def test_markdown(self):
        md = fit_report.render_md(self.report())
        self.assertIn(f"| #{self.ok.pk} tshirt male adapt | **fits**: chest +10.0 ok | shoulder +2.0 ok | — |", md)
        self.assertIn(f"- garment #{self.none.pk}: no sizes", md)
        self.assertIn(f"- avatar #{self.female.pk}: missing shoulder_width", md)

    def test_cases_height_zones_only(self):
        by_id = {g.pk: g for g in Garment.objects.all()}
        cases = fit_report.check_cases([
            {"garment": self.pants.pk, "model_height_cm": 180, "worn_size": "M", "expected": "fits"},  # 81 vs 81
            {"garment": self.pants.pk, "model_height_cm": 192, "worn_size": "M", "expected": "fits"},  # 81 vs 86.4
            {"garment": self.ok.pk, "model_height_cm": 185, "worn_size": "L", "expected": "fits"},
            {"garment": 99999, "model_height_cm": 180, "worn_size": "M", "expected": "fits"},
        ], by_id)
        self.assertFalse(cases[0]["failed"])
        self.assertEqual([z["zone"] for z in cases[0]["checks"]], ["inseam"])  # only the height zone
        self.assertEqual((cases[1]["failed"], cases[1]["failed_zones"]), (True, ["inseam"]))
        self.assertEqual(cases[1]["checks"][0]["body_cm"], 86.4)
        self.assertEqual((cases[2]["checks"], cases[2]["length_cm"], cases[2]["failed"]), ([], 70, False))
        self.assertEqual(cases[3]["error"], "garment not found")
        md = fit_report.render_md(self.report(), cases)
        self.assertIn("model 192 cm, worn M, expected fits: inseam 81 vs 86.4 (-5.4 too_small) **FAILS on inseam**", md)
        self.assertIn("no height zone; length 70 cm (info, not a rule)", md)
        self.assertIn("ERROR garment not found", md)
