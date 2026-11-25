from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from apps.jobs.models import Job
from apps.outfits.models import Outfit
from apps.outfits.serializers import OutfitSerializer
from apps.bodies.models import Body
from apps.avatars.models import Avatar
from apps.garments.models import Garment
from .tasks import run_tryon
from . import fit_gate
from apps.sizing.measurements import MeasurementsInvalid, RANGES as MEASUREMENT_RANGES, validate_measurements
import logging

logger = logging.getLogger(__name__)

GENDER_MISMATCH_DETAIL = "Bu kiyim boshqa jins uchun moʻljallangan. Mos kiyim yoki boshqa asos tanlang."
BODY_SEX_REQUIRED_DETAIL = "Avval tanangiz jinsini tanlang."


def garment_fits_sex(garment_gender: str, sex: str) -> bool:
    """docs/09 #97: male sees male + unisex, female sees female + unisex; unisex always passes."""
    return garment_gender == "unisex" or garment_gender == sex


@api_view(["GET"])
@permission_classes([AllowAny])
def app_config(request):
    """GET /api/config/: public flags the frontend needs before login (demo label, fit check gate)."""
    from django.conf import settings
    return Response({"demo_mode": settings.DEMO_MODE, "fit_check_enabled": settings.FIT_CHECK_ENABLED})


def _serve_demo(request, avatar_obj, garments):
    """DEMO_MODE: a precomputed result for this exact (avatar, garments) pair, as a finished job. None if absent."""
    from pathlib import Path
    from django.conf import settings
    from django.core.files.base import ContentFile
    from . import demo

    rel = demo.lookup(avatar_obj.pk, [g.pk for g in garments])
    if rel is None:
        return None
    outfit = Outfit.objects.create(user=request.user, avatar=avatar_obj)
    outfit.garments.set(garments)
    # A copy, not a reference: deleting the outfit deletes its file and must not break the demo set.
    data = (Path(settings.MEDIA_ROOT) / rel).read_bytes()
    outfit.result_image.save(f"result_{outfit.pk}.png", ContentFile(data), save=True)
    job = Job.objects.create(user=request.user, kind="tryon", target_id=outfit.pk, status="done",
                             result={"outfit_id": outfit.pk, "demo": True})
    return Response({"job_id": job.pk, "outfit_id": outfit.pk}, status=202)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def start_tryon(request):
    """
    POST /api/tryon/
    body: { base: "body" | "avatar", avatar_id?: int, garment_ids: [int, ...], measurements?: {...} }
    Returns the job id for polling. measurements (base=avatar only, the user's own sizes, docs/11) are always
    validated (400 MEASUREMENTS_INVALID); with FIT_CHECK_ENABLED the fit gate runs after the existing checks and
    before the demo short-circuit (400 GARMENT_SIZE_MISSING | BODY_SIZE_MISSING | SIZE_MISMATCH, nothing created).
    """
    data = request.data
    base_type = data.get("base", "body")
    garment_ids = data.get("garment_ids", [])

    if not garment_ids:
        return Response({"detail": "garment_ids required"}, status=400)
    if len(garment_ids) > 2:
        return Response({"detail": "max 2 garments per try-on"}, status=400)

    body_obj = None
    request_sizes = {}
    avatar_obj = None

    if base_type == "body":
        try:
            body_obj = Body.objects.get(user=request.user)
            if not body_obj.is_confirmed:
                return Response({"detail": "Body not confirmed yet"}, status=400)
        except Body.DoesNotExist:
            return Response({"detail": "No confirmed body found"}, status=404)
        if body_obj.sex is None:  # bodies created before sex was required: the UI asks once, never guessed
            return Response({"code": "BODY_SEX_REQUIRED", "detail": BODY_SEX_REQUIRED_DETAIL}, status=400)
    else:
        avatar_id = data.get("avatar_id")
        if not avatar_id:
            return Response({"detail": "avatar_id required for avatar base"}, status=400)
        try:
            avatar_obj = Avatar.objects.get(pk=avatar_id)
        except Avatar.DoesNotExist:
            return Response(status=404)
        try:  # the user's own sizes, not the avatar's; base=body ignores the field
            request_sizes = validate_measurements(data.get("measurements"))
        except MeasurementsInvalid as e:
            return Response({"code": "MEASUREMENTS_INVALID", "detail": e.detail, "field": e.key}, status=400)

    # validate garments
    garments = []
    for gid in garment_ids:
        try:
            g = Garment.objects.get(pk=gid)
        except Garment.DoesNotExist:
            return Response({"detail": f"Garment {gid} not found"}, status=404)
        # Same rule as GET /garments/{id}/: owner, or public AND approved.
        if g.owner != request.user and not (g.visibility == "public" and g.status == "approved"):
            return Response(status=404)
        if not g.landmarks:
            return Response({"detail": f"Garment {gid} has no landmarks"}, status=400)
        sex = body_obj.sex if body_obj is not None else avatar_obj.sex
        if not garment_fits_sex(g.gender, sex):
            return Response({"code": "GENDER_MISMATCH", "detail": GENDER_MISMATCH_DETAIL, "garment_id": g.pk,
                             "garment_gender": g.gender, "base_sex": sex}, status=400)
        garments.append(g)

    # prevent duplicate garment types
    types = [g.type for g in garments]
    if len(types) != len(set(types)):
        return Response({"detail": "Duplicate garment types"}, status=400)

    from django.conf import settings
    if settings.FIT_CHECK_ENABLED:
        sizes = fit_gate.body_sizes_from_body(body_obj) if body_obj is not None else request_sizes
        failed = fit_gate.first_failure(fit_gate.run_gate(garments, sizes))
        if failed is not None:
            return Response(failed.as_error(), status=400)

    if settings.DEMO_MODE and avatar_obj is not None:
        served = _serve_demo(request, avatar_obj, garments)
        if served is not None:
            return served

    outfit = Outfit.objects.create(
        user=request.user,
        body=body_obj,
        avatar=avatar_obj,
    )
    outfit.garments.set(garments)

    job = Job.objects.create(
        user=request.user,
        kind="tryon",
        target_id=outfit.pk,
    )
    run_tryon.delay(job.pk)

    # engine (debug, docs/09 #98): the T-shirt engine this try-on asks for; the job result has the one actually used
    # ("parts" after an MLS fallback, with quality_warnings ["mls_fallback"]).
    engine = settings.TRYON_WARP if any(g.type == "tshirt" for g in garments) else "parts"
    return Response({"job_id": job.pk, "outfit_id": outfit.pk, "engine": engine}, status=202)


def _query_ids(raw):
    """"1,2" -> [1, 2]; None for anything else (empty, non-integer, more than 10)."""
    parts = [p.strip() for p in (raw or "").split(",")]
    if not parts or len(parts) > 10 or not all(p.isdigit() for p in parts):
        return None
    return [int(p) for p in parts]


def _query_measurements(params):
    """Measurement query params -> numbers (MeasurementsInvalid for a non-number); other params are ignored."""
    out = {}
    for key in MEASUREMENT_RANGES:
        raw = params.get(key)
        if raw is None or raw == "":
            continue
        try:
            out[key] = float(raw)
        except ValueError:
            out[key] = raw  # the validator rejects it with the field's message
    return validate_measurements(out)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def fit_check(request):
    """GET /api/tryon/fit-check/?base=avatar|body&avatar_id=&garment_ids=1,2 (+ height_cm, chest, waist, hip,
    shoulder_width, inseam for base=avatar) -> {results: [{garment_id, fits, checks, code?, keys?}]}.
    Same gate as POST tryon/, regardless of FIT_CHECK_ENABLED. A garment that does not fit is a result, not an error."""
    params = request.query_params
    base = params.get("base")
    if base not in ("avatar", "body"):
        return Response({"code": "BAD_BASE", "detail": "base: avatar yoki body."}, status=400)
    ids = _query_ids(params.get("garment_ids"))
    if ids is None:
        return Response({"code": "BAD_GARMENT_IDS", "detail": "garment_ids: 1,2 koʻrinishida."}, status=400)

    if base == "body":
        body_obj = Body.objects.filter(user=request.user).first()
        if body_obj is None:
            return Response(status=404)
        if not body_obj.is_confirmed:  # same answer as POST tryon/
            return Response({"detail": "Body not confirmed yet"}, status=400)
        sizes = fit_gate.body_sizes_from_body(body_obj)
    else:
        avatar_id = params.get("avatar_id")
        if not avatar_id or not avatar_id.isdigit():
            return Response({"code": "BAD_AVATAR_ID", "detail": "avatar_id kerak."}, status=400)
        if not Avatar.objects.filter(pk=int(avatar_id)).exists():
            return Response(status=404)
        try:
            sizes = _query_measurements(params)
        except MeasurementsInvalid as e:
            return Response({"code": "MEASUREMENTS_INVALID", "detail": e.detail, "field": e.key}, status=400)

    garments = []
    for gid in ids:  # same visibility rule as POST tryon/: owner, or public AND approved
        g = Garment.objects.filter(pk=gid).first()
        if g is None or (g.owner != request.user and not (g.visibility == "public" and g.status == "approved")):
            return Response(status=404)
        garments.append(g)
    return Response({"results": [r.as_result() for r in fit_gate.run_gate(garments, sizes)]})
