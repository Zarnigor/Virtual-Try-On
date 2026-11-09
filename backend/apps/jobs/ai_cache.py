"""Cache of AI validation answers, keyed by image hash (never by user or file name).

Key = sha256 of (original image bytes hash, declared type, prompt text hash, model). A changed prompt or model
gives a new key, so stale answers are never reused. The value is the parsed reply fields (no image, no raw
text); the decision rules are re-run in code on every hit, so a rule change in code applies to cached answers too.
A cache error is treated as a miss: the cache is an optimisation, never a reason to fail a job.
"""
import hashlib
import json
import logging

from django.core.cache import cache
from django.conf import settings

logger = logging.getLogger(__name__)


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def validation_key(kind: str, image_hash: str, declared: str, prompt: str) -> str:
    material = json.dumps([image_hash, declared, sha256_hex(prompt), settings.GEMINI_VALIDATION_MODEL])
    return f"aiv:{kind}:{sha256_hex(material)}"


def get(key: str) -> dict | None:
    try:
        value = cache.get(key)
    except Exception as e:  # Redis down etc.
        logger.warning("ai cache get failed: %s", type(e).__name__)
        return None
    return value if isinstance(value, dict) else None


def put(key: str, fields: dict) -> None:
    try:
        cache.set(key, fields, timeout=settings.AI_CACHE_TTL_S)
    except Exception as e:
        logger.warning("ai cache set failed: %s", type(e).__name__)
