"""Garment AI check (prompt 01): strict parsing, the worker flow over httpx.MockTransport, cache, limit, bypass.

Fixtures are written by hand from the prompt 01 output schema. No real image is sent anywhere: the test runner
blocks every real HTTP call (tryon_studio/test_runner.py).
"""
import base64
import json
import re
import threading
from io import BytesIO
from unittest import mock

import httpx
from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from PIL import Image

from apps.garments.models import Garment
from apps.garments.serializers import GarmentSerializer
from apps.jobs import gemini, limits, tasks
from apps.jobs.ai_schemas import (
    AI_RESPONSE_INVALID, WRONG_GARMENT_TYPE, GarmentValidation, garment_response_schema, parse_garment_validation,
)
from apps.jobs.models import Job
from apps.jobs.serializers import JobSerializer
from apps.testing import MediaTestCase, png_bytes
from apps.users.models import User
from tryon_studio.test_runner import RealHTTPBlocked

TSHIRT = {
    "ok": True, "garment_count": 1, "detected_type": "top", "sleeve_length": "short", "view": "front",
    "presentation": "hanger", "visible_fraction": 0.95, "quality": "good", "is_clothing_photo": True,
    "issues": [], "confidence": 0.93,
}
PANTS = {**TSHIRT, "detected_type": "pants", "sleeve_length": "not_applicable", "presentation": "flat"}
# A T-shirt photo declared as pants, answered honestly by the model.
TSHIRT_AS_PANTS = {**TSHIRT, "ok": False, "issues": ["WRONG_TYPE"]}

KIND = "garment_clean"
AI_SETTINGS = dict(
    AI_DEV_BYPASS=False, GEMINI_API_KEY="test-key", GEMINI_VALIDATION_MODEL="test-model",
    GEMINI_RETRY_BACKOFF_S=0, AI_GARMENT_DAILY_LIMIT=5,
)


def verdict(data, declared="tshirt"):
    raw = data if isinstance(data, str) or data is None else json.dumps(data)
    return parse_garment_validation(raw, declared)


def gemini_reply(fields_or_text, status=200):
    text = fields_or_text if isinstance(fields_or_text, str) else json.dumps(fields_or_text)
    return httpx.Response(status, json={"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}}]})


class FakeGemini:
    """An httpx.MockTransport that answers from a list of responses and records the requests."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def handler(self, request):
        self.requests.append(request)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def __enter__(self):
        self._patch = mock.patch.object(gemini, "_transport", lambda: httpx.MockTransport(self.handler))
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()


# ---------- parsing (no worker) ----------

class GarmentParsingTests(SimpleTestCase):
    def test_matching_types_pass(self):
        self.assertTrue(verdict(TSHIRT, "tshirt").accepted)
        self.assertTrue(verdict({**TSHIRT, "sleeve_length": "none"}, "tshirt").accepted)  # sleeveless
        self.assertTrue(verdict(PANTS, "pants").accepted)
        self.assertTrue(verdict({**TSHIRT, "visible_fraction": 1}, "tshirt").accepted)  # JSON 1 is a valid float

    def test_wrong_type_is_rejected_with_the_new_code(self):
        self.assertEqual(verdict(TSHIRT_AS_PANTS, "pants").codes, [WRONG_GARMENT_TYPE])
        self.assertEqual(verdict({**PANTS, "ok": False, "issues": ["WRONG_TYPE"]}, "tshirt").codes,
                         [WRONG_GARMENT_TYPE])
        self.assertEqual(verdict({**TSHIRT, "ok": False, "detected_type": "other", "issues": ["WRONG_TYPE"]}).codes,
                         [WRONG_GARMENT_TYPE])

    def test_ok_true_with_contradicting_fields_is_rejected(self):
        cases = [
            ({**TSHIRT}, "pants", [WRONG_GARMENT_TYPE]),  # says ok, but detected a top for "pants"
            ({**PANTS}, "tshirt", [WRONG_GARMENT_TYPE]),
            ({**TSHIRT, "sleeve_length": "long"}, "tshirt", [WRONG_GARMENT_TYPE]),  # long-sleeve top is no T-shirt
            ({**TSHIRT, "sleeve_length": "three_quarter"}, "tshirt", [WRONG_GARMENT_TYPE]),
            ({**TSHIRT, "garment_count": 2}, "tshirt", ["MULTIPLE_GARMENTS"]),
            ({**TSHIRT, "garment_count": 0, "detected_type": "none"}, "tshirt", ["NO_GARMENT"]),
            ({**TSHIRT, "view": "back"}, "tshirt", ["NOT_FRONT_VIEW"]),
            ({**TSHIRT, "visible_fraction": 0.5}, "tshirt", ["GARMENT_CUT_OFF"]),
            ({**TSHIRT, "quality": "blurry"}, "tshirt", ["LOW_QUALITY"]),
            ({**TSHIRT, "is_clothing_photo": False}, "tshirt", ["NOT_A_CLOTHING_PHOTO"]),
            ({**TSHIRT, "issues": ["WRONG_TYPE"]}, "tshirt", [WRONG_GARMENT_TYPE]),  # ok: true but lists an issue
        ]
        for data, declared, codes in cases:
            v = verdict(data, declared)
            self.assertEqual((v.accepted, v.codes), (False, codes), data)

    def test_codes_are_merged_and_ordered(self):
        v = verdict({**TSHIRT, "ok": False, "view": "side", "quality": "too_dark", "issues": ["LOW_QUALITY"]})
        self.assertEqual(v.codes, ["NOT_FRONT_VIEW", "LOW_QUALITY"])

    def test_invalid_or_empty_json_fails_closed(self):
        missing = dict(TSHIRT)
        del missing["sleeve_length"]
        bad = [
            None, "", "   ", "not json", "[]", "{}", "null", json.dumps(missing),
            json.dumps({**TSHIRT, "ok": "yes"}),  # strict: no string -> bool
            json.dumps({**TSHIRT, "garment_count": "1"}),
            json.dumps({**TSHIRT, "detected_type": "tshirt"}),  # our word, not the prompt's
            json.dumps({**TSHIRT, "confidence": 1.5}),
            json.dumps({**TSHIRT, "garment_count": -1}),
            '```json\n' + json.dumps(TSHIRT) + '\n```',  # markdown fence
        ]
        for raw in bad:
            v = parse_garment_validation(raw, "tshirt")
            self.assertEqual((v.accepted, v.codes, v.cacheable), (False, [AI_RESPONSE_INVALID], False), raw)

    def test_self_contradicting_rejection_is_invalid(self):
        # ok: false with no failing field and no known issue: no honest reason to show the user
        v = verdict({**TSHIRT, "ok": False, "issues": ["HACKED"]})
        self.assertEqual((v.accepted, v.codes, v.cacheable), (False, [AI_RESPONSE_INVALID], False))

    def test_only_supported_types(self):
        with self.assertRaises(ValueError):
            verdict(TSHIRT, "dress")

    def test_schema_matches_the_prompt_json_block(self):
        prompt = (settings.PROMPTS_DIR / "01-garment-validation.txt").read_text()
        block = prompt[prompt.index("Return ONLY this JSON"):]
        prompt_keys = set(re.findall(r'"(\w+)":', block))
        schema = garment_response_schema()
        self.assertEqual(prompt_keys, set(schema["properties"]))
        self.assertEqual(set(schema["required"]), prompt_keys)
        self.assertEqual(set(GarmentValidation.model_fields), prompt_keys)

    def test_real_http_is_blocked_in_tests(self):
        with self.assertRaises(RealHTTPBlocked):
            httpx.get("https://generativelanguage.googleapis.com/")


# ---------- worker flow ----------

def image_bytes(color=(200, 40, 40)):
    buf = BytesIO()
    Image.new("RGB", (400, 500), color).save(buf, format="JPEG")
    return buf.getvalue()


def rembg_mask():
    m = Image.new("L", (400, 500), 0)
    m.paste(255, (50, 50, 350, 450))
    return m


@override_settings(**AI_SETTINGS)
class GarmentAIJobTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()  # cached verdicts must not leak between tests
        self.user = self.make_user()
        self._rembg = mock.patch("rembg.remove", side_effect=lambda *a, **k: rembg_mask())
        self._rembg.start()

    def tearDown(self):
        self._rembg.stop()
        super().tearDown()

    def upload(self, gtype="tshirt", data=None, user=None):
        user = user or self.user
        g = Garment(owner=user, type=gtype)
        g.original_image.save("o.jpg", ContentFile(data or image_bytes()), save=False)
        g.save()
        job = Job.objects.create(user=user, kind="garment_clean", target_id=g.pk)
        return g, job

    def run_job(self, job):
        tasks.run_garment_cleaning(job.pk)
        job.refresh_from_db()
        return job

    # --- matching type passes; the request is what we expect ---

    def test_matching_type_passes(self):
        g, job = self.upload("tshirt")
        with FakeGemini(gemini_reply(TSHIRT)) as fake:
            job = self.run_job(job)
        self.assertEqual(job.status, "done", job.error_code)
        self.assertEqual(job.result, {"cleaned": True, "ai_skipped": False, "ai_cached": False})
        self.assertEqual((job.ai_called, job.ai_outcome), (True, "responded"))
        g.refresh_from_db()
        self.assertTrue(g.image.name)
        self.assertFalse(g.ai_skipped)

        req = fake.requests[0]
        self.assertEqual(req.url.path, "/v1beta/models/test-model:generateContent")
        self.assertEqual(req.headers["x-goog-api-key"], "test-key")
        self.assertNotIn("key", req.url.params)  # never in the URL (logs, proxies)
        self.assertGreaterEqual(req.extensions["timeout"]["read"], 60)
        body = json.loads(req.content)
        parts = body["contents"][0]["parts"]
        self.assertIn("DECLARED TYPE: top", parts[0]["text"])
        self.assertNotIn("{GARMENT_TYPE}", parts[0]["text"])
        sent = Image.open(BytesIO(base64.b64decode(parts[1]["inlineData"]["data"])))
        self.assertEqual((sent.format, parts[1]["inlineData"]["mimeType"]), ("JPEG", "image/jpeg"))
        self.assertFalse(sent.getexif())
        cfg = body["generationConfig"]
        self.assertEqual((cfg["temperature"], cfg["responseMimeType"]), (0, "application/json"))
        self.assertIn("sleeve_length", cfg["responseJsonSchema"]["properties"])
        self.assertNotIn("title", json.dumps(cfg["responseJsonSchema"]))

    def test_pants_prompt_and_pass(self):
        g, job = self.upload("pants", image_bytes((20, 20, 90)))
        with FakeGemini(gemini_reply(PANTS)) as fake:
            job = self.run_job(job)
        self.assertEqual(job.status, "done")
        self.assertIn("DECLARED TYPE: pants", json.loads(fake.requests[0].content)["contents"][0]["parts"][0]["text"])

    # --- rejections ---

    def test_wrong_type_is_rejected_and_the_garment_deleted(self):
        g, job = self.upload("pants")
        with FakeGemini(gemini_reply(TSHIRT_AS_PANTS)):
            job = self.run_job(job)
        self.assertEqual((job.status, job.error_code), ("failed", WRONG_GARMENT_TYPE))
        self.assertFalse(Garment.objects.filter(pk=g.pk).exists())
        self.assertEqual(JobSerializer(job).data["error_message"],
                         "Rasmdagi kiyim tanlangan turga mos emas. Futbolka yoki shim turini toʻgʻri tanlang.")
        self.assertEqual(job.ai_outcome, "responded")  # a billed answer: counts (docs/09 #20, #28)
        self.assertEqual(limits.counted_today(self.user.pk, KIND), 1)

    def test_ok_true_with_contradicting_fields_is_rejected(self):
        g, job = self.upload("tshirt")
        with FakeGemini(gemini_reply({**TSHIRT, "sleeve_length": "long"})):
            job = self.run_job(job)
        self.assertEqual((job.status, job.error_code), ("failed", WRONG_GARMENT_TYPE))
        self.assertFalse(Garment.objects.filter(pk=g.pk).exists())

    def test_invalid_or_empty_reply_fails_closed(self):
        replies = [
            gemini_reply("not json"),
            gemini_reply(""),
            httpx.Response(200, json={"promptFeedback": {"blockReason": "OTHER"}}),  # blocked: no candidates
            httpx.Response(200, text="<html>"),
        ]
        for i, reply in enumerate(replies):
            g, job = self.upload("tshirt", image_bytes((i, 0, 0)))
            with FakeGemini(reply):
                job = self.run_job(job)
            self.assertEqual((job.status, job.error_code, job.ai_outcome), ("failed", AI_RESPONSE_INVALID, "invalid"))
            self.assertFalse(Garment.objects.filter(pk=g.pk).exists())
            # "try again later", never "photo rejected" (docs/09 #28)
            self.assertIn("Keyinroq qayta urinib", JobSerializer(job).data["error_message"])
        self.assertEqual(limits.counted_today(self.user.pk, KIND), len(replies))  # invalid replies count

    # --- AI unavailable: one retry, then AI_UNAVAILABLE, not counted ---

    def test_retry_then_ai_unavailable(self):
        g, job = self.upload("tshirt")
        with FakeGemini(httpx.Response(503), httpx.Response(429)) as fake:
            job = self.run_job(job)
        self.assertEqual(len(fake.requests), 2)
        self.assertEqual((job.status, job.error_code, job.ai_outcome), ("failed", "AI_UNAVAILABLE", "unavailable"))
        self.assertFalse(Garment.objects.filter(pk=g.pk).exists())
        self.assertEqual(limits.counted_today(self.user.pk, KIND), 0)
        self.assertIn("Keyinroq qayta urinib", JobSerializer(job).data["error_message"])

    def test_one_retry_recovers(self):
        g, job = self.upload("tshirt")
        with FakeGemini(httpx.Response(500), gemini_reply(TSHIRT)) as fake:
            job = self.run_job(job)
        self.assertEqual((len(fake.requests), job.status), (2, "done"))

    def test_no_retry_on_other_errors_and_timeouts(self):
        for i, reply in enumerate([httpx.Response(400), httpx.ReadTimeout("slow")]):
            g, job = self.upload("tshirt", image_bytes((0, i, 0)))
            with FakeGemini(reply) as fake:
                job = self.run_job(job)
            self.assertEqual((len(fake.requests), job.error_code), (1, "AI_UNAVAILABLE"))
        self.assertEqual(limits.counted_today(self.user.pk, KIND), 0)

    def test_network_error_is_retried_once(self):
        g, job = self.upload("tshirt")
        with FakeGemini(httpx.ConnectError("down"), httpx.ConnectError("down")) as fake:
            job = self.run_job(job)
        self.assertEqual((len(fake.requests), job.error_code), (2, "AI_UNAVAILABLE"))

    @override_settings(GEMINI_API_KEY="")
    def test_missing_key_is_unavailable_without_a_request(self):
        g, job = self.upload("tshirt")
        with FakeGemini() as fake:
            job = self.run_job(job)
        self.assertEqual((len(fake.requests), job.error_code), (0, "AI_UNAVAILABLE"))

    # --- cache ---

    def test_cache_hit_makes_no_ai_call_and_uses_no_slot(self):
        data = image_bytes()
        _, first = self.upload("tshirt", data)
        with FakeGemini(gemini_reply(TSHIRT)):
            self.run_job(first)
        g2, second = self.upload("tshirt", data)  # same bytes, same declared type
        with FakeGemini() as fake:
            second = self.run_job(second)
        self.assertEqual(len(fake.requests), 0)
        self.assertEqual(second.status, "done")
        self.assertTrue(second.result["ai_cached"])
        self.assertFalse(second.ai_called)
        self.assertEqual(limits.counted_today(self.user.pk, KIND), 1)

    def test_cached_rejection_still_rejects(self):
        data = image_bytes()
        _, first = self.upload("pants", data)
        with FakeGemini(gemini_reply(TSHIRT_AS_PANTS)):
            self.run_job(first)
        g2, second = self.upload("pants", data)
        with FakeGemini() as fake:
            second = self.run_job(second)
        self.assertEqual((len(fake.requests), second.error_code), (0, WRONG_GARMENT_TYPE))
        self.assertFalse(Garment.objects.filter(pk=g2.pk).exists())

    def test_cache_key_includes_the_declared_type_and_skips_bad_replies(self):
        data = image_bytes()
        _, first = self.upload("tshirt", data)
        with FakeGemini(gemini_reply("not json")):
            self.run_job(first)  # invalid: not cached
        _, second = self.upload("tshirt", data)
        with FakeGemini(gemini_reply(TSHIRT)) as fake:
            self.run_job(second)
        self.assertEqual(len(fake.requests), 1)
        _, third = self.upload("pants", data)  # same image, other declared type: asks again
        with FakeGemini(gemini_reply(TSHIRT_AS_PANTS)) as fake:
            third = self.run_job(third)
        self.assertEqual((len(fake.requests), third.error_code), (1, WRONG_GARMENT_TYPE))

    def test_cache_error_is_a_miss(self):
        g, job = self.upload("tshirt")
        with mock.patch("apps.jobs.ai_cache.cache.get", side_effect=ConnectionError), \
                mock.patch("apps.jobs.ai_cache.cache.set", side_effect=ConnectionError), \
                FakeGemini(gemini_reply(TSHIRT)):
            job = self.run_job(job)
        self.assertEqual(job.status, "done")

    # --- bypass ---

    @override_settings(AI_DEV_BYPASS=True)
    def test_bypass_skips_the_ai_and_marks_the_garment(self):
        g, job = self.upload("pants")
        with FakeGemini() as fake:
            job = self.run_job(job)
        self.assertEqual(len(fake.requests), 0)
        self.assertEqual(job.result, {"cleaned": True, "ai_skipped": True, "ai_cached": False})
        self.assertFalse(job.ai_called)
        g.refresh_from_db()
        self.assertTrue(g.ai_skipped)
        request = mock.Mock(user=self.user, build_absolute_uri=lambda u: u)
        self.assertTrue(GarmentSerializer(g, context={"request": request}).data["ai_skipped"])
        self.assertEqual(limits.counted_today(self.user.pk, KIND), 0)

    # --- AI cleaning flag (prompt 04, docs/09 #55) ---

    @override_settings(AI_CLEANING_ENABLED=False)
    def test_cleaning_off_uses_rembg_only(self):
        g, job = self.upload("tshirt", image_bytes((200, 30, 30)))
        with FakeGemini(gemini_reply(TSHIRT)) as fake:
            job = self.run_job(job)
        self.assertEqual(job.status, "done", job.error_code)
        self.assertEqual(len(fake.requests), 1)  # prompt 01 only, no image-model call
        g.refresh_from_db()
        with g.image.open("rb") as f:
            out = Image.open(f)
            out.load()
        self.assertEqual((out.format, out.mode), ("PNG", "RGBA"))  # alpha channel added
        self.assertEqual(out.size, (300, 400))  # cropped to the mask bounding box
        with g.original_image.open("rb") as f:
            src = Image.open(f).convert("RGB")
        self.assertEqual(out.getpixel((150, 200)), (*src.getpixel((200, 250)), 255))  # original pixels kept

    @override_settings(AI_CLEANING_ENABLED=True)
    def test_cleaning_on_fails_clearly_without_spending_ai(self):
        g, job = self.upload("tshirt")
        with FakeGemini() as fake, self.assertLogs("apps.jobs.tasks", "ERROR"):
            job = self.run_job(job)
        self.assertEqual((job.status, job.error_code), ("failed", "CLEAN_FAILED"))
        self.assertIn("AI_CLEANING_ENABLED", job.error_detail)
        self.assertEqual(len(fake.requests), 0)
        self.assertEqual(limits.counted_today(self.user.pk, KIND), 0)
        self.assertFalse(Garment.objects.filter(pk=g.pk).exists())

    @override_settings(GEMINI_VALIDATION_MODEL="model-from-env")
    def test_model_name_comes_only_from_the_setting(self):
        g, job = self.upload("tshirt")
        with FakeGemini(gemini_reply(TSHIRT)) as fake:
            self.run_job(job)
        self.assertEqual(fake.requests[0].url.path, "/v1beta/models/model-from-env:generateContent")

    # --- daily limit ---

    @override_settings(AI_GARMENT_DAILY_LIMIT=1)
    def test_rejections_count_and_the_limit_stops_the_next_call(self):
        _, first = self.upload("pants", image_bytes((1, 1, 1)))
        with FakeGemini(gemini_reply(TSHIRT_AS_PANTS)):
            self.run_job(first)
        g2, second = self.upload("pants", image_bytes((2, 2, 2)))
        with FakeGemini() as fake:
            second = self.run_job(second)
        self.assertEqual((len(fake.requests), second.error_code), (0, "AI_LIMIT"))
        self.assertFalse(second.ai_called)
        self.assertFalse(Garment.objects.filter(pk=g2.pk).exists())

    @override_settings(AI_GARMENT_DAILY_LIMIT=1)
    def test_unavailable_does_not_use_the_slot(self):
        _, first = self.upload("tshirt", image_bytes((1, 1, 1)))
        with FakeGemini(httpx.Response(503), httpx.Response(503)):
            self.run_job(first)
        _, second = self.upload("tshirt", image_bytes((2, 2, 2)))
        with FakeGemini(gemini_reply(TSHIRT)):
            second = self.run_job(second)
        self.assertEqual(second.status, "done")

    def test_limit_is_per_user(self):
        other = self.make_user("b@test.uz")
        with override_settings(AI_GARMENT_DAILY_LIMIT=1):
            _, j1 = self.upload("tshirt", image_bytes((1, 1, 1)), user=other)
            with FakeGemini(gemini_reply(TSHIRT)):
                self.run_job(j1)
            _, j2 = self.upload("tshirt", image_bytes((2, 2, 2)))
            with FakeGemini(gemini_reply(TSHIRT)):
                self.assertEqual(self.run_job(j2).status, "done")

    @override_settings(AI_GARMENT_DAILY_LIMIT=1, AI_DAILY_LIMIT=1)
    def test_limits_are_separate_per_job_kind(self):
        from django.utils import timezone
        # a used body slot today does not block the garment check
        Job.objects.create(user=self.user, kind="body_validation", ai_called=True, ai_called_at=timezone.now(),
                           ai_outcome="responded")
        _, job = self.upload("tshirt")
        with FakeGemini(gemini_reply(TSHIRT)):
            self.assertEqual(self.run_job(job).status, "done")
        self.assertEqual(limits.counted_today(self.user.pk, "body_validation"), 1)
        self.assertEqual(limits.counted_today(self.user.pk, KIND), 1)

    @override_settings(AI_GARMENT_DAILY_LIMIT=3)
    def test_garment_limit_comes_from_its_own_setting(self):
        self.assertEqual((limits.limit_for(KIND), limits.limit_for("body_validation")), (3, settings.AI_DAILY_LIMIT))

    # --- redelivery guards ---

    def test_finalized_job_is_a_no_op(self):
        g, job = self.upload("tshirt")
        Job.objects.filter(pk=job.pk).update(status="failed", error_code="AI_UNAVAILABLE")
        with FakeGemini() as fake:
            self.run_job(job)
        self.assertEqual(len(fake.requests), 0)
        self.assertTrue(Garment.objects.filter(pk=g.pk).exists())

    def test_redelivery_after_a_sent_request_never_calls_again(self):
        g, job = self.upload("tshirt")
        Job.objects.filter(pk=job.pk).update(ai_called=True, status="running")
        with FakeGemini() as fake:
            job = self.run_job(job)
        self.assertEqual((len(fake.requests), job.error_code), (0, "AI_UNAVAILABLE"))

    # --- privacy ---

    def test_logs_never_contain_image_bytes_prompt_or_reply(self):
        data = image_bytes((123, 45, 67))
        g, job = self.upload("tshirt", data)
        reply = {**TSHIRT, "confidence": 0.8123456}
        with self.assertLogs(level="DEBUG") as logs, FakeGemini(gemini_reply(reply)) as fake:
            self.run_job(job)
            _, bad = self.upload("tshirt", image_bytes((9, 9, 9)))
            fake.responses.append(gemini_reply('{"ok": "SECRET-REPLY-TEXT"}'))
            self.run_job(bad)
        sent_b64 = json.loads(fake.requests[0].content)["contents"][0]["parts"][1]["inlineData"]["data"]
        text = "\n".join(logs.output)
        for needle in (sent_b64[:40], base64.b64encode(data)[:40].decode(), "0.8123456", "SECRET-REPLY-TEXT",
                       "You validate ONE clothing photo", "test-key"):
            self.assertNotIn(needle, text)
        self.assertIn("garment job", text)  # the useful lines are still there


@override_settings(**{**AI_SETTINGS, "AI_GARMENT_DAILY_LIMIT": 1})
class DailyLimitRaceTests(TransactionTestCase):
    """Two workers race for the last slot on real PostgreSQL row locks: exactly one wins."""

    def test_two_jobs_race_for_the_last_slot(self):
        user = User.objects.create_user(email="race@test.uz", password="secret123", is_adult_confirmed=True)
        jobs = [Job.objects.create(user=user, kind="garment_clean") for _ in range(2)]
        barrier = threading.Barrier(2)
        results = []

        def worker(job):
            try:
                barrier.wait()
                results.append(limits.reserve_ai_slot(job))
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(j,)) for j in jobs]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(Job.objects.filter(ai_called=True).count(), 1)
