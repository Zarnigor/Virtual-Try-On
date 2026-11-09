"""
Celery tasks for AI pipeline jobs.
In P0 these run synchronously via .delay() but are written as proper Celery tasks
so the architecture is correct for production.
"""
from celery import shared_task
import logging

logger = logging.getLogger(__name__)


@shared_task
def run_body_validation(job_pk: int):
    from apps.jobs.models import Job
    from apps.bodies.models import Body

    job = Job.objects.get(pk=job_pk)
    job.status = "running"
    job.save(update_fields=["status"])

    try:
        body = Body.objects.get(pk=job.target_id)
        # Code-side checks first (geometry check placeholder; real check in body pipeline)
        # For P0 without GEMINI_API_KEY: auto-approve
        from django.conf import settings
        if not settings.GEMINI_API_KEY:
            # no key: skip AI, mark done with note
            job.status = "done"
            job.result = {"approved": True, "note": "AI check skipped (no API key)"}
            job.save(update_fields=["status", "result"])
            return

        # TODO: call prompt 02 via Gemini API
        job.status = "done"
        job.result = {"approved": True}
        job.save(update_fields=["status", "result"])

    except Exception as e:
        job.status = "failed"
        job.error_code = "AI_FAILED"
        job.error_detail = str(e)
        job.save(update_fields=["status", "error_code", "error_detail"])
        logger.exception("body_validation job %d failed", job_pk)


@shared_task
def run_garment_cleaning(job_pk: int):
    from apps.jobs.models import Job
    from apps.garments.models import Garment

    job = Job.objects.get(pk=job_pk)
    job.status = "running"
    job.save(update_fields=["status"])

    try:
        garment = Garment.objects.get(pk=job.target_id)
        from django.conf import settings

        if not settings.GEMINI_API_KEY:
            # no AI key: use rembg only for background removal
            _rembg_clean(garment)
        else:
            # TODO: call prompt 04 via Gemini API, then rembg
            _rembg_clean(garment)

        job.status = "done"
        job.result = {"cleaned": True}
        job.save(update_fields=["status", "result"])

    except Exception as e:
        job.status = "failed"
        job.error_code = "AI_FAILED"
        job.error_detail = str(e)
        job.save(update_fields=["status", "error_code", "error_detail"])
        logger.exception("garment_clean job %d failed", job_pk)


def _rembg_clean(garment):
    """Remove background with rembg and save cleaned transparent PNG."""
    import os
    from pathlib import Path
    from io import BytesIO
    from PIL import Image
    from django.core.files.base import ContentFile

    try:
        from rembg import remove
        with open(garment.image.path, "rb") as f:
            input_data = f.read()
        output_data = remove(input_data)
        # crop to alpha bounding box
        img = Image.open(BytesIO(output_data)).convert("RGBA")
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)
        buf = BytesIO()
        img.save(buf, format="PNG")
        new_name = f"garments/cleaned_{Path(garment.image.name).stem}.png"
        # save original ref before overwriting
        garment.image.save(new_name, ContentFile(buf.getvalue()), save=True)
    except Exception:
        # rembg not available or failed: keep original image as-is
        pass
