"""Staff-only avatar API (docs/04 "Staff"): list, detail, landmark editor save, new avatar upload.

Non-staff users get 404 (the endpoints do not exist for them), anonymous users 401.
The try-on engine reads Avatar.landmarks, so what staff save here is what the engine uses.
"""
import numpy as np
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from apps.bodies.landmark_checks import BodyLandmarksInvalid, complete_body_landmarks, validate_body_landmarks

from .models import Avatar
from .serializers import AvatarSerializer

MEASUREMENT_KEYS = ("shoulder", "chest", "waist", "hip")


class IsStaffOr404(BasePermission):
    def has_permission(self, request, view):
        if request.user and request.user.is_authenticated and not request.user.is_staff:
            raise NotFound()
        return True


STAFF = [IsAuthenticated, IsStaffOr404]


class StaffAvatarSerializer(AvatarSerializer):
    status = serializers.SerializerMethodField()

    class Meta(AvatarSerializer.Meta):
        fields = AvatarSerializer.Meta.fields + ("height_cm", "landmarks_confirmed_at", "status")

    def get_status(self, obj):
        return "confirmed" if obj.landmarks_confirmed_at else "auto"


class MeasurementsField(serializers.DictField):
    child = serializers.FloatField(min_value=20, max_value=300)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        unknown = set(value) - set(MEASUREMENT_KEYS)
        if unknown:
            raise serializers.ValidationError(f"unknown keys: {', '.join(sorted(unknown))}")
        return value


class LandmarksSaveSerializer(serializers.Serializer):
    landmarks = serializers.DictField()
    height_cm = serializers.FloatField(min_value=100, max_value=250, required=False, allow_null=True)
    measurements = MeasurementsField(required=False)


def _with_edges(avatar) -> dict:
    """Landmarks as a starting point for the editor: lines saved without edge points get them from the mask."""
    lm = avatar.landmarks or {}
    if avatar.landmarks_confirmed_at or not avatar.image:
        return lm
    try:
        from PIL import Image
        from apps.avatars.prep import fill_missing_edges
        with avatar.image.open("rb") as f:
            img = Image.open(f)
            img.load()
        if "A" not in img.getbands():
            return lm
        mask = np.array(img.getchannel("A")) > 128
        return fill_missing_edges(dict(lm), mask)
    except Exception:  # a broken file must not hide the avatar; the editor uses its defaults
        return lm


def _data(avatar, request):
    data = StaffAvatarSerializer(avatar, context={"request": request}).data
    data["landmarks"] = _with_edges(avatar)
    return data


@api_view(["GET", "POST"])
@permission_classes(STAFF)
def staff_avatars(request):
    """GET /api/staff/avatars/ | POST /api/staff/avatars/ (multipart: sex, build, photo, height_cm, measurements)."""
    if request.method == "POST":
        from .staff_upload import create_avatar
        return create_avatar(request)
    avatars = Avatar.objects.order_by("sex", "build")
    return Response(StaffAvatarSerializer(avatars, many=True, context={"request": request}).data)


@api_view(["GET"])
@permission_classes(STAFF)
def staff_avatar_detail(request, pk):
    avatar = Avatar.objects.filter(pk=pk).first()
    if avatar is None:
        raise NotFound()
    return Response(_data(avatar, request))


@api_view(["PATCH"])
@permission_classes(STAFF)
def staff_avatar_landmarks(request, pk):
    """PATCH /api/staff/avatars/{id}/landmarks/ {landmarks, height_cm?, measurements?}: sets landmarks_confirmed_at."""
    avatar = Avatar.objects.filter(pk=pk).first()
    if avatar is None:
        raise NotFound()
    s = LandmarksSaveSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    lm = s.validated_data["landmarks"]
    try:
        validate_body_landmarks(lm)
    except BodyLandmarksInvalid as e:
        return Response({"code": "LANDMARKS_INVALID", "detail": e.detail}, status=400)
    avatar.landmarks = complete_body_landmarks(lm)
    avatar.landmarks_confirmed_at = timezone.now()
    fields = ["landmarks", "landmarks_confirmed_at"]
    if "height_cm" in s.validated_data:
        avatar.height_cm = s.validated_data["height_cm"]
        fields.append("height_cm")
    if "measurements" in s.validated_data:
        avatar.measurements = {**(avatar.measurements or {}), **s.validated_data["measurements"]}
        fields.append("measurements")
    avatar.save(update_fields=fields)
    return Response(_data(avatar, request))
