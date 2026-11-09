"""Minimal Gemini client over plain httpx (docs/09 #23). No Google SDK.

Only `generateContent` with one image and a JSON response schema, which is all the validation prompts need.
The model name comes from settings.GEMINI_VALIDATION_MODEL (env), never from code.

Errors:
- AIUnavailable: the AI could not answer (missing key/model, timeout, network error, 429/5xx after one retry,
  other non-200). Not billed, does not count toward the daily limit.
- A 200 reply whose text is missing or unusable returns "" so the caller's fail-closed parser reports
  AI_RESPONSE_INVALID (billed, counts).

Logging: model, HTTP status, attempt and elapsed time only. Never the prompt, the image or the reply text.
"""
import base64
import logging
import time

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}


class AIUnavailable(Exception):
    pass


def _transport() -> httpx.BaseTransport | None:
    """Tests replace this with an httpx.MockTransport. None = the default network transport."""
    return None


def clean_schema(schema: dict) -> dict:
    """Drop Pydantic's `title` keys: they carry no meaning for the model and only add tokens."""
    if isinstance(schema, dict):
        return {k: clean_schema(v) for k, v in schema.items() if k != "title"}
    if isinstance(schema, list):
        return [clean_schema(v) for v in schema]
    return schema


def generate_json(prompt: str, image_jpeg: bytes, response_schema: dict) -> str:
    """Send prompt + one JPEG, return the model's reply text ("" when the 200 reply has no usable text)."""
    key, model = settings.GEMINI_API_KEY, settings.GEMINI_VALIDATION_MODEL
    if not key or not model:
        raise AIUnavailable("GEMINI_API_KEY or GEMINI_VALIDATION_MODEL is not set")

    url = f"{settings.GEMINI_API_BASE}/models/{model}:generateContent"
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": prompt},
                {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(image_jpeg).decode("ascii")}},
            ],
        }],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseJsonSchema": clean_schema(response_schema),
        },
    }
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}

    with httpx.Client(transport=_transport(), timeout=settings.GEMINI_TIMEOUT_S) as client:
        for attempt in (1, 2):
            started = time.monotonic()
            try:
                resp = client.post(url, json=payload, headers=headers)
            except httpx.TimeoutException:
                logger.warning("gemini model=%s attempt=%d timeout", model, attempt)
                raise AIUnavailable("timeout")
            except httpx.HTTPError as e:
                logger.warning("gemini model=%s attempt=%d network error %s", model, attempt, type(e).__name__)
                if attempt == 1:
                    time.sleep(settings.GEMINI_RETRY_BACKOFF_S)
                    continue
                raise AIUnavailable("network error")
            elapsed = time.monotonic() - started
            logger.info("gemini model=%s attempt=%d status=%d %.1fs", model, attempt, resp.status_code, elapsed)
            if resp.status_code == 200:
                return _reply_text(resp)
            if resp.status_code in RETRY_STATUSES and attempt == 1:
                time.sleep(settings.GEMINI_RETRY_BACKOFF_S)
                continue
            raise AIUnavailable(f"HTTP {resp.status_code}")
    raise AIUnavailable("no reply")  # not reached


def _reply_text(resp: httpx.Response) -> str:
    """Join the text parts of the first candidate. A blocked or empty reply gives ""."""
    try:
        parts = resp.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    except (ValueError, KeyError, IndexError, TypeError):
        return ""
