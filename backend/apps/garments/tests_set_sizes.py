"""manage.py set_garment_sizes (docs/11 "Calibration")."""
import json
import tempfile
from io import StringIO

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.garments.models import Garment
from apps.testing import MediaTestCase, png_bytes

TSHIRT = {"chest_width": 52, "length": 70, "shoulder_width": 46}
PANTS = {"waist_width": 40, "hip_width": 50, "inseam": 78}


class SetGarmentSizesTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.t = self.garment("tshirt", owner=self.user)
        self.p = self.garment("pants", owner=None, visibility="public", status="approved")  # catalog / demo

    def garment(self, gtype, **kw):
        g = Garment(type=gtype, **kw)
        g.image.save("g.png", ContentFile(png_bytes()), save=False)
        g.save()
        return g

    def run_cmd(self, data, *args):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(data, f)
        out = StringIO()
        call_command("set_garment_sizes", "--file", f.name, *args, stdout=out)
        return out.getvalue()

    def test_valid_file_incl_catalog_garment(self):
        out = self.run_cmd({str(self.t.pk): {**TSHIRT, "stretch": True}, str(self.p.pk): PANTS})
        self.t.refresh_from_db()
        self.p.refresh_from_db()
        self.assertEqual((self.t.sizes, self.t.stretch), (TSHIRT, True))
        self.assertEqual((self.p.sizes, self.p.stretch), (PANTS, False))  # stretch omitted: unchanged
        self.assertIn("before: sizes=None", out)
        self.assertIn("catalog", out)
        self.assertIn("2 garment(s) updated", out)

    def test_full_replace(self):
        self.t.sizes = {**TSHIRT, "sleeve_length": 20}
        self.t.save()
        self.run_cmd({str(self.t.pk): TSHIRT})
        self.t.refresh_from_db()
        self.assertEqual(self.t.sizes, TSHIRT)

    def test_any_invalid_entry_writes_nothing_and_lists_all_errors(self):
        bad = {str(self.t.pk): TSHIRT, str(self.p.pk): {**PANTS, "inseam": 5}, "99999": PANTS, "x": PANTS}
        with self.assertRaises(CommandError) as cm:
            self.run_cmd(bad)
        msg = str(cm.exception)
        self.assertIn("nothing written", msg)
        for part in (f"{self.p.pk} (pants)", "99999: garment not found", "x: garment id"):
            self.assertIn(part, msg)
        self.t.refresh_from_db()
        self.assertIsNone(self.t.sizes)  # the valid entry was not written either
        with self.assertRaises(CommandError):
            self.run_cmd({str(self.t.pk): {**TSHIRT, "stretch": "yes"}})

    def test_dry_run_writes_nothing(self):
        out = self.run_cmd({str(self.t.pk): TSHIRT}, "--dry-run")
        self.t.refresh_from_db()
        self.assertIsNone(self.t.sizes)
        self.assertIn("after:  sizes=", out)
        self.assertIn("dry run", out)
