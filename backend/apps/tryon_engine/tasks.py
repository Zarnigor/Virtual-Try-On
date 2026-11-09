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
    import numpy as np
    import cv2
    from io import BytesIO
    from django.core.files.base import ContentFile
    from django.conf import settings
    from apps.tryon_engine.warp import warp_tshirt, warp_pants

    H = settings.CANVAS_H
    W = settings.CANVAS_W

    # load base image (body or avatar)
    base_path = outfit.body.image.path if outfit.body else outfit.avatar.image.path
    base_lm = outfit.body.landmarks if outfit.body else outfit.avatar.landmarks
    base_img = cv2.imread(base_path, cv2.IMREAD_UNCHANGED)
    if base_img is None:
        raise ValueError(f"Cannot read base image: {base_path}")
    if base_img.shape[2] == 3:
        base_img = cv2.cvtColor(base_img, cv2.COLOR_BGR2BGRA)
    base_img = cv2.resize(base_img, (W, H))

    canvas = base_img.copy()

    for garment in outfit.garments.all():
        g_img = cv2.imread(garment.image.path, cv2.IMREAD_UNCHANGED)
        if g_img is None:
            continue
        if g_img.shape[2] == 3:
            g_img = cv2.cvtColor(g_img, cv2.COLOR_BGR2BGRA)

        g_lm = garment.landmarks
        if garment.type == "tshirt":
            warped, warns = warp_tshirt(base_lm, g_lm, g_img, H, W)
        elif garment.type == "pants":
            warped, warns = warp_pants(base_lm, g_lm, g_img, H, W)
        else:
            continue

        if warns:
            logger.warning("Warp warnings for garment %d: %s", garment.pk, warns)

        # alpha-composite warped garment onto canvas
        from apps.tryon_engine.warp import _alpha_composite
        canvas = _alpha_composite(canvas, warped)

    # flatten canvas to RGB on white background
    white = np.full((H, W, 3), 255, dtype=np.uint8)
    alpha = canvas[:, :, 3:4].astype(np.float32) / 255.0
    rgb = (canvas[:, :, :3].astype(np.float32) * alpha + white * (1 - alpha)).astype(np.uint8)
    final_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    _, buf = cv2.imencode(".png", final_bgr)
    outfit.result_image.save(
        f"outfits/result_{outfit.pk}.png",
        ContentFile(buf.tobytes()),
        save=True,
    )
