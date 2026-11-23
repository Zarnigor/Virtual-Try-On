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


def _process_body(body):
    """The shared body pipeline on the uploaded original. A code-check rejection becomes JobRejected(code)."""
    from apps.bodies.pipeline import BodyPhotoRejected, process_body_photo
    with body.image.open("rb") as fh:
        data = fh.read()
    try:
        return process_body_photo(data)
    except BodyPhotoRejected as e:
        raise JobRejected(e.code, e.detail)


def _store_processed_body(body, processed):
    """The normalized 600x1200 PNG and the auto landmarks replace the original; the original file is deleted."""
    from django.core.files.base import ContentFile
    original = body.image.name
    body.image.save("body.png", ContentFile(processed.png), save=False)
    body.landmarks = processed.landmarks
    body.save(update_fields=["image", "landmarks"])
    if original and original != body.image.name:
        try:
            body.image.storage.delete(original)
        except Exception:
            logger.warning("could not delete the original of body %d", body.pk)


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
        processed = _process_body(body)  # code checks first (docs/09 #26): EXIF strip, rembg, framing, 600x1200
        if not settings.BODY_AI_CHECK_ENABLED:  # DEBUG only (settings): prompt 02 skipped, marked for the UI
            ai_checked = False
        else:
            ai_checked = _ai_verdict(_ask_body_validation(body), BodyValidation, BODY_ISSUES)
        _store_processed_body(body, processed)
        _done(job, {"approved": True, "ai_skipped": not ai_checked, "warnings": processed.warnings})
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


_REMBG_SESSIONS: dict = {}


def _rembg_session():
    """One rembg session per process for settings.REMBG_MODEL (loading a model takes seconds)."""
    from rembg import new_session
    name = settings.REMBG_MODEL
    if name not in _REMBG_SESSIONS:
        _REMBG_SESSIONS[name] = new_session(name)
    return _REMBG_SESSIONS[name]


def _dump_masks(garment, raw_mask, final_mask):
    """Debug only (GARMENT_MASK_DEBUG_DIR, DEBUG): the raw model mask and the final mask as PNGs."""
    folder = settings.GARMENT_MASK_DEBUG_DIR
    if not folder:
        return
    import os
    os.makedirs(folder, exist_ok=True)
    raw_mask.save(os.path.join(folder, f"garment_{garment.pk}_1_raw_mask.png"))
    final_mask.save(os.path.join(folder, f"garment_{garment.pk}_2_final_mask.png"))


LEG_GAP_MIN_CONTRAST = 90.0  # RGB distance fabric <-> photo background below which the clean-up does nothing
LEG_GAP_BAND = 0.15  # the clean-up band reaches this share of a leg's width beyond the gap
LEG_GAP_FEATHER_PX = 3  # px (kernel <= 5): the soft edge kept next to the cleared gap


def clear_background_between_legs(rgb, mask):
    """Pants: alpha 0 for the photo background the model kept as fabric between the legs.

    rgb: HxWx3 uint8 original photo; mask: HxW uint8 model alpha. Returns the new alpha (same shape). Nothing is
    filled: the alpha only goes down. Applies only when the fabric is clearly unlike the background (white pants on
    black), only inside the columns of the gap (measured on the lowest rows, where the legs are apart) and only for
    pixels that are nearer the background colour than the fabric and connected to the outside background.
    A pixel's alpha is capped by the share of fabric colour in it (a soft edge, no black fringe)."""
    import cv2
    import numpy as np

    solid = mask >= 128
    outside = ~solid
    # background colour: the median of the outside pixels on the image border
    border = np.zeros(mask.shape, bool)
    border[[0, -1], :] = True
    border[:, [0, -1]] = True
    ob = outside & border
    if ob.sum() < 20 or solid.sum() < 500:
        return mask
    bg = np.median(rgb[ob].astype(np.float32), axis=0)
    inner = cv2.erode(solid.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    if inner.sum() < 200:
        return mask
    fabric = np.median(rgb[inner].astype(np.float32), axis=0)
    axis = fabric - bg
    span = float(np.linalg.norm(axis))
    if span < LEG_GAP_MIN_CONTRAST:
        return mask
    # t = share of fabric colour in a pixel (0 = background, 1 = fabric): projection on the bg -> fabric axis
    t = ((rgb.astype(np.float32) - bg) @ axis) / (span * span)
    # the gap columns: the legs are apart on the lowest rows. Found by colour, because the model may keep the gap
    # as foreground all the way to the hem
    legs = solid & (t >= 0.5)
    ys = np.where(legs.any(axis=1))[0]
    top, bot = int(ys[0]), int(ys[-1])
    gap = None
    for y in range(bot - max(int(0.03 * (bot - top)), 2), top + int(0.5 * (bot - top)), -1):
        d = np.diff(np.concatenate([[0], legs[y].astype(np.int8), [0]]))
        starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
        if len(starts) >= 2:
            k = int(np.argmax(starts[1:] - ends[:-1]))  # the widest hole between runs
            gap = (int(ends[k]), int(starts[k + 1]), int(ends[k] - starts[k]), int(ends[k + 1] - starts[k + 1]))
            break
    if gap is None:
        return mask
    left_end, right_start, wl, wr = gap
    x0 = max(left_end - int(LEG_GAP_BAND * wl), 0)
    x1 = min(right_start + int(LEG_GAP_BAND * wr), mask.shape[1])
    band = np.zeros(mask.shape, bool)
    band[top:, x0:x1] = True  # to the image edge: the gap is open to the background below the hem
    cand = (t < 0.5) & band & (mask > 0)
    # keep only the candidates connected to the outside background
    n, lab = cv2.connectedComponents((cand | (outside & band)).astype(np.uint8), connectivity=4)
    touching = np.unique(lab[outside & band & (mask < 128)])
    reach = np.isin(lab, touching[touching > 0]) & cand
    if not reach.any():
        return mask
    k = 2 * LEG_GAP_FEATHER_PX + 1
    zone = cv2.dilate(reach.astype(np.uint8), np.ones((k, k), np.uint8)) > 0
    cap = np.clip((t - 0.3) / 0.4, 0.0, 1.0) * 255.0
    out = mask.astype(np.float32)
    out[zone] = np.minimum(out[zone], cap[zone])
    out[reach] = 0
    return np.rint(out).astype(np.uint8)


def _rembg_clean(garment):
    """Remove the background with rembg, crop to the alpha bounding box, save as the garment image.

    Quality: rembg is asked for the MASK only. Its own cutout composites onto (0,0,0,0), which stores
    colour * alpha in a straight-alpha PNG, so every soft edge pixel was darkened twice (dark fringes).
    Here the source pixels are kept exactly and only alpha is added. EXIF orientation is applied in
    memory (rembg ignores it), the stored original is never rewritten, and the result is saved once as
    lossless PNG. Raises on any failure (never keeps the uncleaned photo silently).
    """
    from pathlib import Path
    import numpy as np
    from PIL import Image, ImageChops, ImageOps
    from django.core.files.base import ContentFile
    from rembg import remove

    # Always from the untouched original: `image` stays empty until this step has produced the cleaned PNG.
    with garment.original_image.open("rb") as f:
        src = ImageOps.exif_transpose(Image.open(f))
        src.load()
    rgb = src.convert("RGB")
    mask = remove(rgb, session=_rembg_session(), only_mask=True).convert("L")
    raw_mask = mask
    if garment.type == "pants":  # the model keeps the photo background between the legs as fabric (docs/09 #123)
        mask = Image.fromarray(clear_background_between_legs(np.array(rgb), np.array(mask)), "L")
    if "A" in src.getbands() or "transparency" in src.info:  # a PNG that already has transparency keeps it
        mask = ImageChops.darker(mask, src.convert("RGBA").getchannel("A"))
    img = rgb.convert("RGBA")  # original RGB + the final alpha, never the rembg cutout colours
    img.putalpha(mask)
    _dump_masks(garment, raw_mask, mask)
    bbox = mask.getbbox()
    if not bbox:
        raise JobRejected("NO_GARMENT", "rembg left nothing")
    img = img.crop(bbox)
    # Opaque inside the silhouette: rembg holes are filled, background-coloured openings stay (docs/09 #63).
    from apps.tryon_engine.warp import background_color, fill_alpha_holes, opening_mask
    arr = np.array(img)
    arr = fill_alpha_holes(arr, opening_mask(arr, background_color(arr)))
    if settings.GARMENT_FLATTEN_LIGHTING:  # near-solid garments: flatten the photo lighting once (docs/09 #67)
        from apps.garments.lighting import flatten_lighting
        flat = flatten_lighting(arr)
        garment.lighting_flattened = flat is not arr
        arr = flat
    img = Image.fromarray(arr, "RGBA")
    buf = BytesIO()
    img.save(buf, format="PNG")

    # upload_to already adds "garments/". The original is deleted once the cleaned image is stored (docs/02
    # "originals are deleted after processing"; there is no Save / Cancel preview, docs/09 #111).
    original = garment.original_image.name
    garment.image.save(f"cleaned_{Path(original).stem}.png", ContentFile(buf.getvalue()), save=False)
    garment.original_image = None
    garment.save()
    try:
        garment.image.storage.delete(original)
    except Exception:
        logger.warning("could not delete the original of garment %d", garment.pk)
