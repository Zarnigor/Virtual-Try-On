"""
Celery tasks for the AI pipeline. Fail closed (docs/02 #17): no valid AI verdict = rejected.

The Gemini calls are not wired yet (step 4: prompt 02, step 6: prompts 01 + 04). Until then
`_ask_*` return None ("AI unavailable"), which fails the job, unless settings.AI_DEV_BYPASS
(local DEBUG only) lets the job continue with result["ai_skipped"] = True.
A rejected or failed upload is deleted so the user can upload again.
"""
import logging
from io import BytesIO

from celery import shared_task
from django.conf import settings

from .ai_schemas import (
    BODY_ISSUES, GARMENT_ISSUES, BodyValidation, GarmentValidation, parse_validation,
)

logger = logging.getLogger(__name__)


class JobRejected(Exception):
    def __init__(self, code: str, detail: str = "", codes: list[str] | None = None):
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.codes = codes or [code]


# ---------- AI calls (not wired yet) ----------

def _ask_body_validation(body):
    """Return the raw JSON text from prompt 02, or None if the AI is unavailable. TODO step 4."""
    return None


def _ask_garment_validation(garment):
    """Return the raw JSON text from prompt 01, or None if the AI is unavailable. TODO step 6."""
    return None


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
    from apps.jobs.models import Job
    job = Job.objects.get(pk=job_pk)
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
    garment = Garment.objects.filter(pk=job.target_id).first()
    if garment is None:
        _fail(job, "GARMENT_NOT_FOUND")
        return
    try:
        ai_checked = _ai_verdict(_ask_garment_validation(garment), GarmentValidation, GARMENT_ISSUES)
        # TODO step 6: prompt 04 (AI cleaning, removes hangers) runs before rembg; until then rembg only.
        _rembg_clean(garment)
        _done(job, {"cleaned": True, "ai_skipped": not ai_checked})
    except JobRejected as e:
        _fail(job, e.code, e.detail, e.codes)
        garment.delete()
    except Exception as e:
        logger.exception("garment_clean job %d failed", job_pk)
        _fail(job, "CLEAN_FAILED", str(e))
        garment.delete()


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
    buf = BytesIO()
    img.save(buf, format="PNG")

    # upload_to already adds "garments/". original_image stays until Save/Cancel (step 6).
    garment.image.save(f"cleaned_{Path(garment.original_image.name).stem}.png", ContentFile(buf.getvalue()), save=True)
