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
    """GET /api/config/: public flags the frontend needs before login (demo label)."""
    from django.conf import settings
    return Response({"demo_mode": settings.DEMO_MODE})


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
    body: { base: "body" | "avatar", avatar_id?: int, garment_ids: [int, ...] }
    Returns the job id for polling.
    """
    data = request.data
    base_type = data.get("base", "body")
    garment_ids = data.get("garment_ids", [])

    if not garment_ids:
        return Response({"detail": "garment_ids required"}, status=400)
    if len(garment_ids) > 2:
        return Response({"detail": "max 2 garments per try-on"}, status=400)

    body_obj = None
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

    return Response({"job_id": job.pk, "outfit_id": outfit.pk}, status=202)
