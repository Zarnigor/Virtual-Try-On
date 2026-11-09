import json
from unittest import mock

from django.core.files.base import ContentFile
from django.test import SimpleTestCase, override_settings

from apps.bodies.models import Body
from apps.garments.models import Garment
from apps.jobs import tasks
from apps.jobs.ai_schemas import (
    BODY_ISSUES, GARMENT_ISSUES, BodyValidation, GarmentValidation, parse_validation,
)
from apps.jobs.models import Job
from apps.testing import MediaTestCase, png_bytes

GOOD_BODY = {
    "ok": True, "person_count": 1, "full_body_visible": True, "front_facing": True, "upright": True,
    "arms_away": True, "legs_apart": True, "clothing": "tight", "sleeves": "short",
    "held_objects_or_accessories": False, "lighting": "good", "sharpness": "good", "is_real_photo": True,
    "apparent_age": "adult", "issues": [], "confidence": 0.9,
}
GOOD_GARMENT = {
    "ok": True, "garment_count": 1, "detected_type": "tshirt", "matches_declared_type": True, "view": "front",
    "presentation": "hanger", "visible_fraction": 0.95, "quality": "good", "is_clothing_photo": True,
    "issues": [], "confidence": 0.9,
}


def body_verdict(data):
    raw = data if isinstance(data, str) or data is None else json.dumps(data)
    return parse_validation(raw, BodyValidation, BODY_ISSUES)


class FailClosedParsingTests(SimpleTestCase):
    def test_valid_good_reply_is_accepted(self):
        self.assertTrue(body_verdict(GOOD_BODY).accepted)
        g = parse_validation(json.dumps(GOOD_GARMENT), GarmentValidation, GARMENT_ISSUES)
        self.assertTrue(g.accepted)

    def test_empty_invalid_or_incomplete_is_rejected(self):
        for raw in (None, "", "not json", "[]", "{}", json.dumps({**GOOD_BODY, "ok": "yes"})):
            v = body_verdict(raw)
            self.assertFalse(v.accepted, raw)
            self.assertEqual(v.codes, ["INVALID_AI_RESPONSE"])
        missing = dict(GOOD_BODY)
        del missing["apparent_age"]
        self.assertFalse(body_verdict(missing).accepted)

    def test_rejection_returns_known_codes(self):
        v = body_verdict({**GOOD_BODY, "ok": False, "sleeves": "long", "issues": ["LONG_SLEEVES", "HACKED"]})
        self.assertEqual((v.accepted, v.codes), (False, ["LONG_SLEEVES"]))

    def test_rules_are_rechecked_in_code(self):
        # the model says ok, but a field breaks a rule: still rejected
        self.assertFalse(body_verdict({**GOOD_BODY, "apparent_age": "minor_suspected"}).accepted)
        self.assertFalse(body_verdict({**GOOD_BODY, "clothing": "loose"}).accepted)
        g = {**GOOD_GARMENT, "visible_fraction": 0.5}
        self.assertFalse(parse_validation(json.dumps(g), GarmentValidation, GARMENT_ISSUES).accepted)


class BodyJobTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.body = Body(user=self.user, landmarks={})
        self.body.image.save("b.png", ContentFile(png_bytes()), save=True)
        self.job = Job.objects.create(user=self.user, kind="body_validation", target_id=self.body.pk)

    @override_settings(AI_DEV_BYPASS=False)
    def test_no_ai_fails_closed_and_frees_the_slot(self):
        tasks.run_body_validation(self.job.pk)
        self.job.refresh_from_db()
        self.assertEqual((self.job.status, self.job.error_code), ("failed", "AI_UNAVAILABLE"))
        self.assertFalse(Body.objects.exists())

    @override_settings(AI_DEV_BYPASS=True)
    def test_dev_bypass_is_marked(self):
        tasks.run_body_validation(self.job.pk)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "done")
        self.assertTrue(self.job.result["ai_skipped"])

    @override_settings(AI_DEV_BYPASS=True)
    def test_invalid_ai_reply_is_rejected_even_with_bypass(self):
        with mock.patch.object(tasks, "_ask_body_validation", return_value="garbage"):
            tasks.run_body_validation(self.job.pk)
        self.job.refresh_from_db()
        self.assertEqual((self.job.status, self.job.error_code), ("failed", "INVALID_AI_RESPONSE"))

    @override_settings(AI_DEV_BYPASS=False)
    def test_ai_rejection_code_reaches_the_job(self):
        reply = json.dumps({**GOOD_BODY, "ok": False, "sleeves": "long", "issues": ["LONG_SLEEVES"]})
        with mock.patch.object(tasks, "_ask_body_validation", return_value=reply):
            tasks.run_body_validation(self.job.pk)
        self.job.refresh_from_db()
        self.assertEqual(self.job.error_code, "LONG_SLEEVES")

    @override_settings(AI_DEV_BYPASS=False)
    def test_ai_accept_marks_done(self):
        with mock.patch.object(tasks, "_ask_body_validation", return_value=json.dumps(GOOD_BODY)):
            tasks.run_body_validation(self.job.pk)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "done")
        self.assertFalse(self.job.result["ai_skipped"])


@override_settings(AI_DEV_BYPASS=True)
class GarmentJobTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.garment = Garment(owner=self.user, type="tshirt")
        self.garment.image.save("g.png", ContentFile(png_bytes()), save=False)
        self.garment.original_image.save("o.png", ContentFile(png_bytes()), save=False)
        self.garment.save()
        self.job = Job.objects.create(user=self.user, kind="garment_clean", target_id=self.garment.pk)

    def test_cleaning_failure_fails_the_job(self):
        with mock.patch("rembg.remove", side_effect=RuntimeError("boom")):
            tasks.run_garment_cleaning(self.job.pk)
        self.job.refresh_from_db()
        self.assertEqual((self.job.status, self.job.error_code), ("failed", "CLEAN_FAILED"))
        self.assertFalse(Garment.objects.exists())

    @staticmethod
    def _mask(size, box, value=255):
        from PIL import Image
        m = Image.new("L", size, 0)
        m.paste(value, box)
        return m

    def _set_image(self, data, name="g.jpg"):
        self.garment.image.save(name, ContentFile(data), save=True)

    def test_cleaning_crops_to_the_garment(self):
        # png_bytes() is 60x120; rembg returns the mask only
        with mock.patch("rembg.remove", return_value=self._mask((60, 120), (10, 20, 40, 100))) as rm:
            tasks.run_garment_cleaning(self.job.pk)
        self.assertTrue(rm.call_args.kwargs.get("only_mask"))
        self.job.refresh_from_db()
        self.garment.refresh_from_db()
        self.assertEqual(self.job.status, "done")
        self.assertEqual((self.garment.image.width, self.garment.image.height), (30, 80))

    def test_soft_edges_keep_the_source_colour(self):
        """rembg's own cutout stored colour * alpha (dark fringes). The source RGB must stay exact."""
        from io import BytesIO
        from PIL import Image
        src = BytesIO()
        Image.new("RGB", (60, 120), (200, 120, 40)).save(src, format="PNG")
        self._set_image(src.getvalue(), "g.png")
        mask = self._mask((60, 120), (0, 0, 60, 120), 255)
        mask.paste(64, (0, 0, 60, 10))  # soft edge, alpha 64
        with mock.patch("rembg.remove", return_value=mask):
            tasks.run_garment_cleaning(self.job.pk)
        self.garment.refresh_from_db()
        out = Image.open(self.garment.image.path)
        self.assertEqual(out.format, "PNG")
        self.assertEqual(out.getpixel((5, 5)), (200, 120, 40, 64))     # not (50, 30, 10, 64)
        self.assertEqual(out.getpixel((5, 60)), (200, 120, 40, 255))

    def test_exif_orientation_is_applied_and_the_original_is_untouched(self):
        from io import BytesIO
        from PIL import Image
        img = Image.new("RGB", (80, 40), (10, 200, 10))
        exif = Image.Exif()
        exif[0x0112] = 6  # rotate 90 CW when displayed: a phone photo held upright
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=95, exif=exif)
        raw = buf.getvalue()
        self._set_image(raw)
        self.garment.original_image.save("o.jpg", ContentFile(raw), save=True)
        seen = {}

        def fake_remove(image, **kw):
            seen["size"] = image.size
            return self._mask(image.size, (0, 0) + image.size)

        with mock.patch("rembg.remove", side_effect=fake_remove):
            tasks.run_garment_cleaning(self.job.pk)
        self.garment.refresh_from_db()
        self.assertEqual(seen["size"], (40, 80))  # upright, as the user sees it
        self.assertEqual((self.garment.image.width, self.garment.image.height), (40, 80))
        with self.garment.original_image.open("rb") as f:
            self.assertEqual(f.read(), raw)
