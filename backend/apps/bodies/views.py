from django.conf import settings
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Body
from .serializers import (
    BodySerializer, BodyUploadSerializer, MeasurementsSerializer, BodyConfirmSerializer,
)
from apps.jobs.models import Job
from apps.jobs.tasks import run_body_validation


ERROR_CODES = {
    "FILE_TOO_LARGE": "Fayl hajmi juda katta. 20 MB dan kichik rasm yuklang.",
    "BAD_FILE_TYPE": "Faqat JPG yoki PNG formatidagi rasmlar qabul qilinadi.",
    "IMAGE_TOO_SMALL": "Rasm juda kichik. Kamida 600px balandlikdagi rasm yuklang.",
    "BODY_EXISTS": "Tanangiz allaqachon saqlangan. Avval uni oʻchiring.",
    "BODY_NOT_FOUND": "Tana topilmadi.",
    "BODY_CONFIRMED": "Tasdiqlangan tanani oʻzgartirib boʻlmaydi.",
    "MEASUREMENTS_LOCKED": "Oʻlchamlarni yiliga bir marta oʻzgartirish mumkin.",
    "AI_LIMIT": "Bugunlik tekshiruv limitiga yetdingiz. Ertaga qayta urinib koʻring.",
}


def _err(code, status, **extra):
    return Response({"code": code, "detail": ERROR_CODES[code], **extra}, status=status)


def _own_body(request):
    # Query every time: request.user.body can be a stale cached object.
    return Body.objects.filter(user=request.user).first()


@api_view(["GET", "POST", "DELETE"])
@permission_classes([IsAuthenticated])
def body_root(request):
    """GET /api/body/ (own body), POST /api/body/ (multipart upload), DELETE /api/body/."""
    if request.method == "POST":
        return _upload_body(request)

    body = _own_body(request)
    if body is None:
        return _err("BODY_NOT_FOUND", 404)

    if request.method == "DELETE":
        body.delete()  # cascades to its outfits; files removed by post_delete signals
        return Response(status=204)

    return Response(BodySerializer(body, context={"request": request}).data)


def _upload_body(request):
    if _own_body(request) is not None:
        return _err("BODY_EXISTS", 409)

    s = BodyUploadSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    photo = s.validated_data["photo"]

    if photo.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
        return _err("FILE_TOO_LARGE", 400)
    if photo.content_type not in ("image/jpeg", "image/png"):
        return _err("BAD_FILE_TYPE", 400)

    body = Body.objects.create(user=request.user, image=photo, landmarks={})

    job = Job.objects.create(user=request.user, kind="body_validation", target_id=body.pk)
    run_body_validation.delay(job.pk)

    return Response({
        "body": BodySerializer(body, context={"request": request}).data,
        "job_id": job.pk,
    }, status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def confirm_body(request):
    """POST /api/body/confirm/ {landmarks, height_cm?, measurements?}: locks photo + landmarks."""
    body = _own_body(request)
    if body is None:
        return _err("BODY_NOT_FOUND", 404)
    if body.is_confirmed:
        return _err("BODY_CONFIRMED", 409)

    s = BodyConfirmSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    data = s.validated_data

    body.landmarks = data["landmarks"]
    if "height_cm" in data:
        body.height_cm = data["height_cm"]
    if "measurements" in data:
        body.measurements = data["measurements"]
    # First entry of measurements does not start the 365-day lock.
    body.confirmed_at = timezone.now()
    body.save(update_fields=["landmarks", "height_cm", "measurements", "confirmed_at"])
    return Response(BodySerializer(body, context={"request": request}).data)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def update_measurements(request):
    """PATCH /api/body/measurements/ {height_cm?, measurements?}: once per 365 days."""
    body = _own_body(request)
    if body is None:
        return _err("BODY_NOT_FOUND", 404)
    if not body.can_change_measurements:
        return _err("MEASUREMENTS_LOCKED", 403, unlock_at=body.measurements_unlock_at)

    s = MeasurementsSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    if "height_cm" in s.validated_data:
        body.height_cm = s.validated_data["height_cm"]
    if "measurements" in s.validated_data:
        body.measurements = s.validated_data["measurements"]
    body.measurements_changed_at = timezone.now()
    body.save(update_fields=["height_cm", "measurements", "measurements_changed_at"])
    return Response(BodySerializer(body, context={"request": request}).data)
