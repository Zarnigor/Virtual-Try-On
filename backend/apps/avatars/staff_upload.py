"""POST /api/staff/avatars/ (staff only): new avatar photo through the shared body pipeline, then the editor.

Multipart: sex, build, photo, height_cm, shoulder, chest, waist, hip (nominal circumferences, cm), shoulder_width?
(cm, a width; default: computed from the new landmarks, docs/09 #129). One avatar per
(sex, build): uploading an existing pair replaces its photo and landmarks and resets landmarks_confirmed_at (200);
a new pair returns 201. Runs synchronously (rembg, a few seconds); no AI call.
"""
from django.core.files.base import ContentFile
from rest_framework import serializers
from rest_framework.response import Response

from apps.bodies.pipeline import BodyPhotoRejected, process_body_photo
from apps.images import ImageRejected, validate_image_upload

from .models import Avatar
from apps.sizing.body_sizes import with_shoulder_width

MIN_SIDE_PX = 600


class AvatarUploadSerializer(serializers.Serializer):
    sex = serializers.ChoiceField(choices=["male", "female"])
    build = serializers.ChoiceField(choices=["slim", "average", "plus"])
    photo = serializers.ImageField()
    height_cm = serializers.FloatField(min_value=100, max_value=250)
    shoulder = serializers.FloatField(min_value=20, max_value=300)
    chest = serializers.FloatField(min_value=20, max_value=300)
    waist = serializers.FloatField(min_value=20, max_value=300)
    hip = serializers.FloatField(min_value=20, max_value=300)
    shoulder_width = serializers.FloatField(min_value=20, max_value=300, required=False)


def save_processed(avatar: Avatar, processed, name: str) -> None:
    """Store a pipeline result on the avatar (old file removed) and reset the confirmation."""
    if avatar.image and avatar.image.name:
        avatar.image.storage.delete(avatar.image.name)
    avatar.image.save(name, ContentFile(processed.png), save=False)
    avatar.landmarks = processed.landmarks
    avatar.landmarks_confirmed_at = None


def create_avatar(request):
    from .staff import _data

    s = AvatarUploadSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    d = s.validated_data
    photo = d["photo"]
    try:
        validate_image_upload(photo, min_side=MIN_SIDE_PX)
    except ImageRejected as e:
        return Response({"code": e.code, "detail": e.detail}, status=400)
    try:
        processed = process_body_photo(photo.read())
    except BodyPhotoRejected as e:
        return Response({"code": e.code, "detail": e.detail}, status=400)

    avatar, created = Avatar.objects.get_or_create(sex=d["sex"], build=d["build"])
    save_processed(avatar, processed, f"avatar_{d['sex']}_{d['build']}.png")
    avatar.height_cm = d["height_cm"]
    avatar.measurements = with_shoulder_width({k: d[k] for k in ("shoulder", "chest", "waist", "hip")},
                                              avatar.landmarks, avatar.height_cm, d.get("shoulder_width"))
    avatar.save()
    return Response({**_data(avatar, request), "warnings": processed.warnings}, status=201 if created else 200)
