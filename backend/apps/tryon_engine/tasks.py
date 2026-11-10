"""Celery task: run the try-on warp and produce the result image."""
from celery import shared_task
import logging

logger = logging.getLogger(__name__)


@shared_task
def run_tryon(job_pk: int):
    from apps.jobs.models import Job
    from apps.outfits.models import Outfit

    job = Job.objects.get(pk=job_pk)
    job.status = "running"
    job.save(update_fields=["status"])

    try:
        outfit = Outfit.objects.get(pk=job.target_id)
        _do_warp(outfit)
        job.status = "done"
        job.result = {"outfit_id": outfit.pk}
        job.save(update_fields=["status", "result"])

    except Exception as e:
        job.status = "failed"
        job.error_code = "WARP_FAILED"
        job.error_detail = str(e)
        job.save(update_fields=["status", "error_code", "error_detail"])
        logger.exception("tryon job %d failed", job_pk)


def _do_warp(outfit):
    import cv2
    from django.core.files.base import ContentFile
    from django.conf import settings
    from apps.tryon_engine.flags import render_flags
    from apps.tryon_engine.warp import render_tryon

    base_path = outfit.body.image.path if outfit.body else outfit.avatar.image.path
    base_lm = outfit.body.landmarks if outfit.body else outfit.avatar.landmarks
    base_img = cv2.imread(base_path, cv2.IMREAD_UNCHANGED)
    if base_img is None:
        raise ValueError(f"Cannot read base image: {base_path}")

    garments = []
    for garment in outfit.garments.all():
        g_img = cv2.imread(garment.image.path, cv2.IMREAD_UNCHANGED)
        if g_img is None:
            raise ValueError(f"Cannot read garment image {garment.pk}")
        garments.append((garment.type, g_img, garment.landmarks))

    final_bgr, warns, _ = render_tryon(base_img, base_lm, garments, settings.CANVAS_H, settings.CANVAS_W, **render_flags("body" if outfit.body else "avatar"))
    if warns:
        logger.warning("Warp warnings for outfit %d: %s", outfit.pk, warns)

    _, buf = cv2.imencode(".png", final_bgr)
    outfit.result_image.save(f"result_{outfit.pk}.png", ContentFile(buf.tobytes()), save=True)
