from django.conf import settings
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Garment
from .serializers import GarmentSerializer, GarmentUploadSerializer
from apps.images import ImageRejected, validate_image_upload
from apps.jobs.models import Job
from apps.jobs.tasks import run_garment_cleaning


def _visible_to(user):
    """Owner always; others only public + approved."""
    return Q(owner=user) | Q(visibility="public", status="approved")


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def garments_root(request):
    """GET /api/garments/?scope=mine|catalog&type=  |  POST /api/garments/ (multipart upload)."""
    if request.method == "POST":
        return _upload_garment(request)

    scope = request.query_params.get("scope", "mine")
    gtype = request.query_params.get("type")

    if scope == "mine":
        qs = Garment.objects.filter(owner=request.user)
    elif scope == "catalog":
        qs = Garment.objects.filter(visibility="public", status="approved")
    else:
        qs = Garment.objects.filter(_visible_to(request.user))

    if gtype:
        qs = qs.filter(type=gtype)

    qs = qs.order_by("-created_at")
    return Response(GarmentSerializer(qs, many=True, context={"request": request}).data)


def _upload_garment(request):
    s = GarmentUploadSerializer(data=request.data)
    s.is_valid(raise_exception=True)

    photo = s.validated_data["photo"]
    try:
        validate_image_upload(photo, min_side=settings.GARMENT_MIN_SIDE_PX)
    except ImageRejected as e:
        return Response({"code": e.code, "detail": e.detail}, status=400)

    garment = Garment.objects.create(
        owner=request.user,
        type=s.validated_data["type"],
        name=s.validated_data.get("name", ""),
        # `image` is the cleaned PNG only (contract: image_url = cleaned). It stays empty, so image_url,
        # width and height are null, until the cleaning job has written it from original_image.
        original_image=photo,
    )

    job = Job.objects.create(user=request.user, kind="garment_clean", target_id=garment.pk)
    run_garment_cleaning.delay(job.pk)

    return Response({
        "garment": GarmentSerializer(garment, context={"request": request}).data,
        "job_id": job.pk,
    }, status=201)


@api_view(["GET", "DELETE"])
@permission_classes([IsAuthenticated])
def garment_detail(request, pk):
    """GET /api/garments/{id}/ (owner or public+approved)  |  DELETE (owner only)."""
    if request.method == "DELETE":
        try:
            g = Garment.objects.get(pk=pk, owner=request.user)
        except Garment.DoesNotExist:
            return Response(status=404)
        g.delete()  # files removed by post_delete signal
        return Response(status=204)

    try:
        g = Garment.objects.get(_visible_to(request.user), pk=pk)
    except Garment.DoesNotExist:
        return Response(status=404)
    return Response(GarmentSerializer(g, context={"request": request}).data)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def update_landmarks(request, pk):
    """PATCH /api/garments/{id}/landmarks/ {landmarks}."""
    try:
        g = Garment.objects.get(pk=pk, owner=request.user)
    except Garment.DoesNotExist:
        return Response(status=404)
    if not g.image:  # landmarks are pixels of the cleaned (cropped) PNG; it does not exist yet
        return Response(
            {"code": "GARMENT_NOT_READY", "detail": "Kiyim hali tayyorlanmoqda. Biroz kuting."}, status=409,
        )
    landmarks = request.data.get("landmarks")
    if not isinstance(landmarks, dict) or not landmarks:
        return Response({"code": "LANDMARKS_REQUIRED", "detail": "Chiziqlarni belgilang."}, status=400)
    g.landmarks = landmarks
    g.save(update_fields=["landmarks"])
    return Response(GarmentSerializer(g, context={"request": request}).data)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def update_visibility(request, pk):
    """PATCH /api/garments/{id}/visibility/ {visibility: private|public}."""
    try:
        g = Garment.objects.get(pk=pk, owner=request.user)
    except Garment.DoesNotExist:
        return Response(status=404)
    vis = request.data.get("visibility")
    if vis not in ("private", "public"):
        return Response({"code": "BAD_VISIBILITY", "detail": "private yoki public."}, status=400)
    g.visibility = vis
    # Public garments wait for moderation (P2) before others can see them.
    g.save(update_fields=["visibility"])
    return Response(GarmentSerializer(g, context={"request": request}).data)
