from django.conf import settings
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .landmark_checks import LandmarksInvalid, for_storage, validate_garment_landmarks
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
    """GET /api/garments/?scope=mine|catalog|all&type=&gender=&for_sex=male|female|all&avatar_id=  |
    POST /api/garments/ (multipart upload).
    for_sex (try-on rule, docs/09 #97): male -> male + unisex, female -> female + unisex, all -> no filter. Without
    for_sex, scope=catalog defaults to the sex of avatar_id (if given) or of the user's own body (if it has one)."""
    if request.method == "POST":
        return _upload_garment(request)

    scope = request.query_params.get("scope", "mine")
    gtype = request.query_params.get("type")
    gender = request.query_params.get("gender")
    for_sex = request.query_params.get("for_sex")

    if scope == "mine":
        qs = Garment.objects.filter(owner=request.user)
    elif scope == "catalog":
        qs = Garment.objects.filter(visibility="public", status="approved")
    else:
        qs = Garment.objects.filter(_visible_to(request.user))

    if gtype:
        qs = qs.filter(type=gtype)
    if gender in ("female", "male"):  # unisex garments match every gender filter
        qs = qs.filter(gender__in=[gender, "unisex"])
    elif gender == "unisex":
        qs = qs.filter(gender="unisex")
    if for_sex is None and scope == "catalog":
        for_sex = _default_sex(request)
    if for_sex in ("female", "male"):
        qs = qs.filter(gender__in=[for_sex, "unisex"])
    elif for_sex not in (None, "all"):
        return Response({"code": "BAD_SEX", "detail": "for_sex: male, female yoki all."}, status=400)

    qs = qs.order_by("-created_at")
    return Response(GarmentSerializer(qs, many=True, context={"request": request}).data)


def _default_sex(request):
    """Catalog default: the sex of ?avatar_id= if given, else of the user's own body; None when unknown."""
    from apps.avatars.models import Avatar
    from apps.bodies.models import Body
    avatar_id = request.query_params.get("avatar_id")
    if avatar_id and str(avatar_id).isdigit():
        avatar = Avatar.objects.filter(pk=int(avatar_id)).first()
        if avatar is not None:
            return avatar.sex
    body = Body.objects.filter(user=request.user).first()
    return body.sex if body is not None else None


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


# Fields PATCH garments/{id}/ may change (owner only). Nothing else is editable here: the image never is.
EDITABLE_CHOICES = {"fit_mode": dict(Garment.FIT_CHOICES), "gender": dict(Garment.GENDER_CHOICES)}


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def garment_detail(request, pk):
    """GET /api/garments/{id}/ (owner or public+approved)  |  PATCH {fit_mode?, gender?} (owner only)  |
    DELETE (owner only)."""
    if request.method == "PATCH":
        return _update_settings(request, pk)
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
    try:
        warnings = validate_garment_landmarks(g.type, landmarks, g.image.width, g.image.height,
                                              bbox=_alpha_bbox(g), mode="write")
    except LandmarksInvalid as e:  # detail is our own fixed Uzbek message, never an exception text
        return Response({"code": "LANDMARKS_INVALID", "detail": e.detail}, status=400)
    g.landmarks = for_storage(g.type, landmarks)  # as sent (extra keys kept), legacy sleeve_end never written
    g.save(update_fields=["landmarks"])
    return Response({**GarmentSerializer(g, context={"request": request}).data, "landmark_warnings": warnings})


def _alpha_bbox(g):
    """(x0, y0, x1, y1) of the cleaned PNG's visible pixels (alpha > 0), or None (no alpha / unreadable)."""
    try:
        from PIL import Image
        with Image.open(g.image.path) as im:
            if im.mode not in ("RGBA", "LA"):
                return None
            box = im.getchannel("A").getbbox()
    except Exception:
        return None
    return (box[0], box[1], box[2] - 1, box[3] - 1) if box else None


def _update_settings(request, pk):
    """PATCH /api/garments/{id}/ {fit_mode?, gender?}: same style as visibility. Any other key (image, name,
    landmarks, ...) is rejected and nothing is saved; the garment image is never updatable."""
    try:
        g = Garment.objects.get(pk=pk, owner=request.user)
    except Garment.DoesNotExist:
        return Response(status=404)
    data = request.data
    keys = set(data.keys()) if hasattr(data, "keys") else set()
    if not keys or keys - set(EDITABLE_CHOICES):
        return Response({"code": "FIELD_NOT_EDITABLE",
                         "detail": "Faqat moslashish va kim uchun ekanini oʻzgartirish mumkin."}, status=400)
    for field, choices in EDITABLE_CHOICES.items():
        if field in keys and data.get(field) not in choices:
            return Response({"code": f"BAD_{field.upper()}", "detail": f"{field}: {' | '.join(choices)}."}, status=400)
    for field in keys:
        setattr(g, field, data.get(field))
    g.save(update_fields=sorted(keys))
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
