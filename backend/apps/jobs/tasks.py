"""
Celery tasks for the AI pipeline. Fail closed (docs/02 #17): no valid AI verdict = rejected.

Garment check (prompt 01) is wired: cache by image hash -> daily-limit slot -> Gemini over httpx -> strict parse.
Body check (prompt 02, step 4) is not wired yet: `_ask_body_validation` returns None ("AI unavailable").
settings.AI_DEV_BYPASS (local DEBUG only) skips the AI step and marks result["ai_skipped"] = True
(and Garment.ai_skipped, so the frontend shows a dev warning).
A rejected or failed upload is deleted so the user can upload again.
"""
import logging
from io import BytesIO

from celery import shared_task
from django.conf import settings

from . import ai_cache, gemini, limits
from .ai_schemas import (
    BODY_ISSUES, PROMPT_GARMENT_TYPE, BodyValidation, GarmentValidation,
    garment_response_schema, judge_garment, parse_garment_validation, parse_validation,
)

logger = logging.getLogger(__name__)


class JobRejected(Exception):
    def __init__(self, code: str, detail: str = "", codes: list[str] | None = None):
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.codes = codes or [code]


# ---------- AI calls ----------

def _ask_body_validation(body):
    """Return the raw JSON text from prompt 02, or None if the AI is unavailable. TODO step 4."""
    return None


def load_prompt(filename: str, **values: str) -> str:
    """Read a prompt from prompts/ and fill its {PLACEHOLDER}s (str.replace: the prompts contain JSON braces)."""
    text = (settings.PROMPTS_DIR / filename).read_text(encoding="utf-8")
    for name, value in values.items():
        text = text.replace("{" + name + "}", value)
    return text


def garment_prompt(declared: str) -> str:
    return load_prompt("01-garment-validation.txt", GARMENT_TYPE=PROMPT_GARMENT_TYPE[declared])


def _check_garment_with_ai(job, garment) -> dict:
    """Run prompt 01 on the garment's original. Returns {"ai_cached": bool}; raises JobRejected on any rejection.

    Order: cache hit (no AI call, no slot) -> poison-pill guard -> reserve a daily slot -> Gemini -> strict parse.
    """
    from apps.images import ai_jpeg

    with garment.original_image.open("rb") as f:
        original = f.read()
    declared = garment.type
    prompt = garment_prompt(declared)
    image = ai_jpeg(original)  # prepared before a slot is reserved, so a bad file never holds a slot
    key = ai_cache.validation_key("garment", ai_cache.sha256_hex(original), declared, prompt)

    cached = ai_cache.get(key)
    if cached is not None:
        try:
            verdict = judge_garment(GarmentValidation.model_validate(cached), declared)
        except Exception:  # an old or damaged entry: ignore it and ask again
            verdict = None
        if verdict is not None:
            logger.info("garment job %d: cache hit", job.pk)
            _raise_if_rejected(verdict)
            return {"ai_cached": True}

    if job.ai_called:  # redelivered after a crash mid-request: never send a second request (docs/09 #30)
        raise JobRejected("AI_UNAVAILABLE", "slot already used by an earlier attempt")
    if not limits.reserve_ai_slot(job):
        raise JobRejected("AI_LIMIT", "daily AI limit reached")

    try:
        raw = gemini.generate_json(prompt, image, garment_response_schema())
    except Exception as e:  # AIUnavailable, or any client bug: no usable reply, so the slot is freed
        limits.set_outcome(job, "unavailable")
        if not isinstance(e, gemini.AIUnavailable):
            logger.exception("garment job %d: gemini client error", job.pk)
        raise JobRejected("AI_UNAVAILABLE", str(e) if isinstance(e, gemini.AIUnavailable) else type(e).__name__)

    verdict = parse_garment_validation(raw, declared)
    limits.set_outcome(job, "invalid" if verdict.data is None else "responded")
    if verdict.cacheable:
        ai_cache.put(key, verdict.data.model_dump())
    logger.info("garment job %d: ai %s %s", job.pk, "accepted" if verdict.accepted else "rejected", verdict.codes)
    _raise_if_rejected(verdict)
    return {"ai_cached": False}


def _raise_if_rejected(verdict):
    if not verdict.accepted:
        raise JobRejected(verdict.codes[0], codes=verdict.codes)


def _ai_verdict(raw, schema, known) -> bool:
    """True if the AI accepted; False if AI was skipped (dev bypass). Raises JobRejected otherwise."""
    if raw is None:
        if settings.AI_DEV_BYPASS:
            return False
        raise JobRejected("AI_UNAVAILABLE", "AI not available; failing closed")
    verdict = parse_validation(raw, schema, known)
    if not verdict.accepted:
        raise JobRejected(verdict.codes[0], codes=verdict.codes)
    return True


# ---------- helpers ----------

def _start(job_pk):
    """Mark the job running. Returns None if it is already finalized (no-op on redelivery, docs/09 #35)."""
    from apps.jobs.models import Job
    job = Job.objects.get(pk=job_pk)
    if job.status in ("done", "failed"):
        return None
    job.status = "running"
    job.save(update_fields=["status"])
    return job


def _done(job, result):
    job.status = "done"
    job.result = result
    job.save(update_fields=["status", "result"])


def _fail(job, code, detail="", codes=None):
    job.status = "failed"
    job.error_code = code
    job.error_detail = detail[:500]
    job.result = {"codes": codes or [code]}
    job.save(update_fields=["status", "error_code", "error_detail", "result"])


# ---------- tasks ----------

@shared_task
def run_body_validation(job_pk: int):
    from apps.bodies.models import Body

    job = _start(job_pk)
    if job is None:
        return
    body = Body.objects.filter(pk=job.target_id, confirmed_at__isnull=True).first()
    if body is None:
        _fail(job, "BODY_NOT_FOUND")
        return
    try:
        # TODO step 4: code checks (geometry) and normalization run before the AI call.
        ai_checked = _ai_verdict(_ask_body_validation(body), BodyValidation, BODY_ISSUES)
        _done(job, {"approved": True, "ai_skipped": not ai_checked})
    except JobRejected as e:
        _fail(job, e.code, e.detail, e.codes)
        body.delete()  # unconfirmed and rejected: let the user upload again
    except Exception as e:
        logger.exception("body_validation job %d failed", job_pk)
        _fail(job, "AI_FAILED", str(e))
        body.delete()


@shared_task
def run_garment_cleaning(job_pk: int):
    from apps.garments.models import Garment

    job = _start(job_pk)
    if job is None:
        return
    garment = Garment.objects.filter(pk=job.target_id).first()
    if garment is None:
        _fail(job, "GARMENT_NOT_FOUND")
        return
    try:
        if settings.AI_CLEANING_ENABLED:
            # Checked before prompt 01 so a misconfiguration never spends an AI call or a daily slot.
            _ai_clean_not_built()
        if settings.AI_DEV_BYPASS:  # local dev only: always skips the AI call, cache and slot (docs/09 #24)
            ai = {"ai_skipped": True, "ai_cached": False}
            garment.ai_skipped = True
            garment.save(update_fields=["ai_skipped"])
        else:
            ai = {"ai_skipped": False, **_check_garment_with_ai(job, garment)}
        # AI_CLEANING_ENABLED=0 (default, docs/09 #55): no prompt 04, rembg only. Hangers are NOT removed.
        # TODO step 6: when prompt 04 is built, run it here (before rembg) if settings.AI_CLEANING_ENABLED.
        _rembg_clean(garment)
        _done(job, {"cleaned": True, **ai})
    except JobRejected as e:
        _fail(job, e.code, e.detail, e.codes)
        garment.delete()
    except Exception as e:
        logger.exception("garment_clean job %d failed", job_pk)
        _fail(job, "CLEAN_FAILED", str(e))
        garment.delete()


def _ai_clean_not_built():
    """Stub for prompt 04 (AI garment cleaning). Raises so an enabled flag never silently skips the cleaning."""
    raise NotImplementedError(
        "AI_CLEANING_ENABLED=1 but prompt 04 (AI garment cleaning) is not built yet; set AI_CLEANING_ENABLED=0"
    )


def _rembg_clean(garment):
    """Remove the background with rembg, crop to the alpha bounding box, save as the garment image.

    Quality: rembg is asked for the MASK only. Its own cutout composites onto (0,0,0,0), which stores
    colour * alpha in a straight-alpha PNG, so every soft edge pixel was darkened twice (dark fringes).
    Here the source pixels are kept exactly and only alpha is added. EXIF orientation is applied in
    memory (rembg ignores it), the stored original is never rewritten, and the result is saved once as
    lossless PNG. Raises on any failure (never keeps the uncleaned photo silently).
    """
    from pathlib import Path
    from PIL import Image, ImageChops, ImageOps
    from django.core.files.base import ContentFile
    from rembg import remove

    # Always from the untouched original: `image` stays empty until this step has produced the cleaned PNG.
    with garment.original_image.open("rb") as f:
        src = ImageOps.exif_transpose(Image.open(f))
        src.load()
    rgb = src.convert("RGB")
    mask = remove(rgb, only_mask=True).convert("L")
    if "A" in src.getbands() or "transparency" in src.info:  # a PNG that already has transparency keeps it
        mask = ImageChops.darker(mask, src.convert("RGBA").getchannel("A"))
    img = rgb.convert("RGBA")
    img.putalpha(mask)
    bbox = mask.getbbox()
    if not bbox:
        raise JobRejected("NO_GARMENT", "rembg left nothing")
    img = img.crop(bbox)
    # Opaque inside the silhouette: rembg holes are filled, background-coloured openings stay (docs/09 #63).
    import numpy as np
    from apps.tryon_engine.warp import background_color, fill_alpha_holes, opening_mask
    arr = np.array(img)
    img = Image.fromarray(fill_alpha_holes(arr, opening_mask(arr, background_color(arr))), "RGBA")
    buf = BytesIO()
    img.save(buf, format="PNG")

    # upload_to already adds "garments/". original_image stays until Save/Cancel (step 6).
    garment.image.save(f"cleaned_{Path(garment.original_image.name).stem}.png", ContentFile(buf.getvalue()), save=True)
