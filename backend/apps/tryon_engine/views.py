from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
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
        garments.append(g)

    # prevent duplicate garment types
    types = [g.type for g in garments]
    if len(types) != len(set(types)):
        return Response({"detail": "Duplicate garment types"}, status=400)

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
