import json

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from unittest import mock

from apps.garments.models import Garment
from apps.garments.size_checks import RANGES, REQUIRED, SizesInvalid, sizes_complete, validate_sizes
from apps.testing import MediaTestCase, png_bytes

TSHIRT = {"chest_width": 52, "length": 70, "shoulder_width": 46}
PANTS = {"waist_width": 40, "hip_width": 50, "inseam": 78}
BASE = {"tshirt": TSHIRT, "pants": PANTS}


class SizeChecksTests(SimpleTestCase):
    def test_valid_required_only_and_with_optional(self):
        self.assertEqual(validate_sizes("tshirt", TSHIRT), TSHIRT)
        full = {**TSHIRT, "waist_width": 48, "sleeve_length": 20}
        self.assertEqual(validate_sizes("tshirt", full), full)
        full = {**PANTS, "thigh_width": 30, "leg_opening": 20}
        self.assertEqual(validate_sizes("pants", full), full)

    def test_every_key_boundaries(self):
        for gtype, ranges in RANGES.items():
            for key, (lo, hi) in ranges.items():
                for ok in (lo, hi, float(lo) + 0.5):
                    validate_sizes(gtype, {**BASE[gtype], key: ok})
                for bad in (lo - 0.01, hi + 0.01):
                    with self.assertRaises(SizesInvalid, msg=f"{gtype}.{key}={bad}") as cm:
                        validate_sizes(gtype, {**BASE[gtype], key: bad})
                    self.assertTrue(cm.exception.detail)

    def test_wrong_type_and_non_finite(self):
        for bad in ("50", None, True, [50], {"a": 1}, float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(SizesInvalid, msg=repr(bad)):
                validate_sizes("tshirt", {**TSHIRT, "chest_width": bad})
        for bad in (None, [], "x", 5):
            with self.assertRaises(SizesInvalid):
                validate_sizes("tshirt", bad)

    def test_missing_required(self):
        for gtype, keys in REQUIRED.items():
            for key in keys:
                sizes = {k: v for k, v in BASE[gtype].items() if k != key}
                with self.assertRaises(SizesInvalid) as cm:
                    validate_sizes(gtype, sizes)
                self.assertIn("kiritilmagan", cm.exception.detail)
        with self.assertRaises(SizesInvalid):
            validate_sizes("tshirt", {})

    def test_unknown_key_and_other_type_key(self):
        with self.assertRaises(SizesInvalid):
            validate_sizes("tshirt", {**TSHIRT, "foo": 1})
        with self.assertRaises(SizesInvalid):  # inseam belongs to pants
            validate_sizes("tshirt", {**TSHIRT, "inseam": 70})
        with self.assertRaises(SizesInvalid):
            validate_sizes("shoes", TSHIRT)

    def test_sizes_complete(self):
        self.assertTrue(sizes_complete("tshirt", TSHIRT))
        self.assertFalse(sizes_complete("tshirt", {"chest_width": 50}))
        self.assertFalse(sizes_complete("tshirt", None))
        self.assertFalse(sizes_complete("pants", TSHIRT))


@mock.patch("apps.garments.views.run_garment_cleaning.delay")
class GarmentSizesApiTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.other = self.make_user("b@test.uz")
        self.login(self.user)

    def _photo(self):
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.new("RGB", (400, 400), (200, 30, 30)).save(buf, "JPEG")
        return SimpleUploadedFile("g.jpg", buf.getvalue(), content_type="image/jpeg")

    def _post(self, **extra):
        data = {"photo": self._photo(), "type": "tshirt", **extra}
        return self.client.post("/api/garments/", data, format="multipart")

    def _garment(self, owner=None, gtype="tshirt", **kw):
        g = Garment(owner=owner or self.user, type=gtype, **kw)
        g.image.save("g.png", ContentFile(png_bytes()), save=False)
        g.save()
        return g

    def test_upload_with_sizes_and_stretch(self, delay):
        r = self._post(sizes=json.dumps(TSHIRT), stretch="true")
        self.assertEqual(r.status_code, 201, r.data)
        g = r.data["garment"]
        self.assertEqual(g["sizes"], TSHIRT)
        self.assertIs(g["stretch"], True)
        self.assertIs(g["sizes_complete"], True)
        self.assertEqual(Garment.objects.get(pk=g["id"]).sizes, TSHIRT)

    def test_stretch_false_string_is_false_and_default(self, delay):
        r = self._post(sizes=json.dumps(TSHIRT), stretch="false")
        self.assertIs(r.data["garment"]["stretch"], False)
        r = self._post(sizes=json.dumps(TSHIRT))
        self.assertIs(r.data["garment"]["stretch"], False)

    def test_upload_without_or_bad_sizes_is_400_and_creates_nothing(self, delay):
        bad = ["", "not json", "{", "[1]", "null", json.dumps({**TSHIRT, "chest_width": 5}),
               json.dumps({**TSHIRT, "x": 1}), json.dumps({"chest_width": 50})]
        for sizes in bad:
            r = self._post(sizes=sizes)
            self.assertEqual(r.status_code, 400, (sizes, r.data))
            self.assertEqual(r.data["code"], "SIZES_INVALID", sizes)
        r = self._post()  # field absent
        self.assertEqual((r.status_code, r.data["code"]), (400, "SIZES_INVALID"))
        self.assertEqual(Garment.objects.count(), 0)
        delay.assert_not_called()

    def test_patch_sizes_owner_full_replace(self, delay):
        g = self._garment(sizes={**TSHIRT, "sleeve_length": 20})
        new = {"chest_width": 55, "length": 72, "shoulder_width": 47}
        r = self.client.patch(f"/api/garments/{g.id}/sizes/", {"sizes": new, "stretch": "true"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["sizes"], new)  # sleeve_length gone: replace, not merge
        self.assertIs(r.data["stretch"], True)
        g.refresh_from_db()
        self.assertEqual(g.sizes, new)
        # stretch omitted keeps the stored value
        r = self.client.patch(f"/api/garments/{g.id}/sizes/", {"sizes": new}, format="json")
        self.assertIs(r.data["stretch"], True)

    def test_patch_sizes_invalid_changes_nothing(self, delay):
        g = self._garment(sizes=TSHIRT)
        for payload in ({"sizes": {**TSHIRT, "length": 1}}, {"sizes": {"length": 70}}, {}, {"sizes": "{"},
                        {"sizes": TSHIRT, "stretch": "maybe"}):
            r = self.client.patch(f"/api/garments/{g.id}/sizes/", payload, format="json")
            self.assertEqual((r.status_code, r.data["code"]), (400, "SIZES_INVALID"), payload)
        g.refresh_from_db()
        self.assertEqual((g.sizes, g.stretch), (TSHIRT, False))

    def test_patch_sizes_other_user_is_404(self, delay):
        g = self._garment(sizes=TSHIRT)
        self.login(self.other)
        r = self.client.patch(f"/api/garments/{g.id}/sizes/", {"sizes": TSHIRT}, format="json")
        self.assertEqual(r.status_code, 404)
        g.visibility, g.status = "public", "approved"  # visible to others, still not editable
        g.save()
        r = self.client.patch(f"/api/garments/{g.id}/sizes/", {"sizes": TSHIRT}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_patch_garment_still_refuses_sizes(self, delay):
        g = self._garment(sizes=TSHIRT)
        for payload in ({"sizes": TSHIRT}, {"stretch": True}):
            r = self.client.patch(f"/api/garments/{g.id}/", payload, format="json")
            self.assertEqual((r.status_code, r.data["code"]), (400, "FIELD_NOT_EDITABLE"))

    def test_orm_garment_without_sizes_saves_and_serializes(self, delay):
        g = self._garment()  # build_demo / staff path
        g.refresh_from_db()
        self.assertIsNone(g.sizes)
        r = self.client.get(f"/api/garments/{g.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data["sizes"])
        self.assertIs(r.data["stretch"], False)
        self.assertIs(r.data["sizes_complete"], False)

    def test_sizes_complete_false_when_required_key_missing_in_db(self, delay):
        g = self._garment(sizes={"chest_width": 50})  # legacy / partial data
        self.assertIs(self.client.get(f"/api/garments/{g.id}/").data["sizes_complete"], False)
