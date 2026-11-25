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
        report = _do_warp(outfit)
        job.status = "done"
        job.result = {**(job.result or {}), "outfit_id": outfit.pk, **report}  # keeps fit_warnings (docs/09 #128)
        job.save(update_fields=["status", "result"])

    except Exception as e:
        job.status = "failed"
        job.error_code = "WARP_FAILED"
        job.error_detail = str(e)
        job.save(update_fields=["status", "error_code", "error_detail"])
        logger.exception("tryon job %d failed", job_pk)


def _do_warp(outfit):
    """Renders and saves the result. Returns {engine: "parts" | "mls", quality_warnings: [...], neck_hole: {garment
    id: bool}, tshirt_config: {garment id: {...}}, finish, render_ms} for the job result (neck_hole: the owner
    polygon was used, debug, docs/09 #102; tshirt_config: what the T-shirt render actually used, docs/09 #105;
    finish: "r17" when a garment got the round 17 finish, else "off", docs/09 #107, #108; render_ms: the render_tryon
    call, without file I/O)."""
    import time
    import cv2
    from django.core.files.base import ContentFile
    from django.conf import settings
    from apps.garments.landmark_checks import engine_landmarks, mls_ready
    from apps.tryon_engine.flags import render_flags
    from apps.tryon_engine.warp import render_tryon

    base_path = outfit.body.image.path if outfit.body else outfit.avatar.image.path
    base_lm = outfit.body.landmarks if outfit.body else outfit.avatar.landmarks
    base_img = cv2.imread(base_path, cv2.IMREAD_UNCHANGED)
    if base_img is None:
        raise ValueError(f"Cannot read base image: {base_path}")

    garments, fit_modes, quality = [], {}, []
    flags = render_flags("body" if outfit.body else "avatar")
    for garment in outfit.garments.all():
        g_img = cv2.imread(garment.image.path, cv2.IMREAD_UNCHANGED)
        if g_img is None:
            raise ValueError(f"Cannot read garment image {garment.pk}")
        garments.append((garment.type, g_img, engine_landmarks(garment.type, garment.landmarks)))
        fit_modes[garment.type] = garment.fit_mode
        if garment.type == "tshirt" and flags.get("warp_engine") == "mls" and \
                not mls_ready(garment.type, garment.landmarks):
            flags["warp_engine"] = "parts"  # MLS needs the main set + the collar points (docs/09 #98, #102)
            quality.append("mls_fallback")

    t0 = time.perf_counter()
    final_bgr, warns, debug = render_tryon(base_img, base_lm, garments, settings.CANVAS_H, settings.CANVAS_W,
                                           fit_modes=fit_modes, **flags)
    render_ms = int(round((time.perf_counter() - t0) * 1000))
    debug = debug or {}
    if warns:
        logger.warning("Warp warnings for outfit %d: %s", outfit.pk, warns)

    _, buf = cv2.imencode(".png", final_bgr)
    outfit.result_image.save(f"result_{outfit.pk}.png", ContentFile(buf.tobytes()), save=True)
    quality += [w for w in debug.get("quality_warnings", []) if w not in quality]
    used = bool(debug.get("neck_hole"))
    cfg = debug.get("tshirt_config")
    return {"engine": debug.get("engine", "parts"), "quality_warnings": quality,
            "neck_hole": {str(g.pk): used and g.type == "tshirt" for g in outfit.garments.all()},
            "tshirt_config": {str(g.pk): cfg for g in outfit.garments.all() if g.type == "tshirt" and cfg},
            "finish": debug.get("finish", "off"), "render_ms": render_ms}
