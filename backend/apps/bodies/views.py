from django.conf import settings
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.sizing.measurements import MeasurementsInvalid, validate_measurements

from .models import Body
from .serializers import (
    BodySerializer, BodyUploadSerializer, MeasurementsSerializer, BodyConfirmSerializer,
)
from apps.jobs.models import Job
from apps.bodies.landmark_checks import BodyLandmarksInvalid, complete_body_landmarks, validate_body_landmarks
from apps.jobs.tasks import run_body_validation


ERROR_CODES = {
    "FILE_TOO_LARGE": "Fayl hajmi juda katta. 20 MB dan kichik rasm yuklang.",
    "BAD_FILE_TYPE": "Faqat JPG yoki PNG formatidagi rasmlar qabul qilinadi.",
    "IMAGE_TOO_SMALL": "Rasm juda kichik. Kamida 600px balandlikdagi rasm yuklang.",
    "BODY_EXISTS": "Tanangiz allaqachon saqlangan. Avval uni oʻchiring.",
    "BODY_NOT_FOUND": "Tana topilmadi.",
    "BAD_SEX": "Jinsni tanlang: erkak yoki ayol.",
    "SEX_ALREADY_SET": "Tananing jinsi allaqachon tanlangan. Oʻzgartirish uchun tanani oʻchirib, qayta yarating.",
    "BODY_CONFIRMED": "Tasdiqlangan tanani oʻzgartirib boʻlmaydi.",
    "MEASUREMENTS_LOCKED": "Oʻlchamlarni yiliga bir marta oʻzgartirish mumkin.",
    "AI_LIMIT": "Bugunlik tekshiruv limitiga yetdingiz. Ertaga qayta urinib koʻring.",
}


def _err(code, status, **extra):
    return Response({"code": code, "detail": ERROR_CODES[code], **extra}, status=status)


def _measurements_problem(data):
    """docs/11 ranges (apps/sizing/measurements.py) for height_cm and the fit-check keys; the circumference
    `shoulder` keeps its old rule (> 0). A Response (400 MEASUREMENTS_INVALID) or None."""
    fit_part = {k: v for k, v in (data.get("measurements") or {}).items() if k != "shoulder"}
    if data.get("height_cm") is not None:
        fit_part["height_cm"] = data["height_cm"]
    try:
        validate_measurements(fit_part)
    except MeasurementsInvalid as e:
        return Response({"code": "MEASUREMENTS_INVALID", "detail": e.detail, "field": e.key}, status=400)
    return None


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
    existing = _own_body(request)
    if existing is not None and existing.is_confirmed:
        return _err("BODY_EXISTS", 409)

    s = BodyUploadSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    photo = s.validated_data["photo"]

    if photo.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
        return _err("FILE_TOO_LARGE", 400)
    if photo.content_type not in ("image/jpeg", "image/png"):
        return _err("BAD_FILE_TYPE", 400)

    if existing is not None:  # an upload replaces an unconfirmed body (docs/09 #33)
        existing.delete()
    body = Body.objects.create(user=request.user, image=photo, landmarks={}, sex=s.validated_data["sex"])

    job = Job.objects.create(user=request.user, kind="body_validation", target_id=body.pk)
    run_body_validation.delay(job.pk)

    return Response({
        "body": BodySerializer(body, context={"request": request}).data,
        "job_id": job.pk,
    }, status=201)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def set_body_sex(request):
    """PATCH /api/body/sex/ {sex}: one-time choice for a body created before sex was required (sex is null).
    Once set it does not change (409 SEX_ALREADY_SET): delete the body and create a new one instead."""
    body = _own_body(request)
    if body is None:
        return _err("BODY_NOT_FOUND", 404)
    sex = request.data.get("sex")
    if sex not in dict(Body.SEX_CHOICES):
        return _err("BAD_SEX", 400)
    if body.sex is not None:
        return _err("SEX_ALREADY_SET", 409)
    body.sex = sex
    body.save(update_fields=["sex"])
    return Response(BodySerializer(body, context={"request": request}).data)


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
    bad = _measurements_problem(data)
    if bad is not None:
        return bad

    try:  # docs/03 "Body landmark checks": the same rules as the staff avatar editor
        validate_body_landmarks(data["landmarks"])
    except BodyLandmarksInvalid as e:
        return Response({"code": "LANDMARKS_INVALID", "detail": e.detail}, status=400)
    body.landmarks = complete_body_landmarks(data["landmarks"])
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
    """PATCH /api/body/measurements/ {height_cm?, measurements?}: MERGE (docs/09 #127). Sent keys replace the stored
    values, keys not sent stay; null is rejected (no key removal). Once per 365 days; the lock starts only when at
    least one value actually changes."""
    body = _own_body(request)
    if body is None:
        return _err("BODY_NOT_FOUND", 404)
    if not body.can_change_measurements:
        return _err("MEASUREMENTS_LOCKED", 403, unlock_at=body.measurements_unlock_at)

    null_field = _null_field(request.data)
    if null_field is not None:
        return Response({"code": "MEASUREMENTS_INVALID", "detail": "Oʻlchamni oʻchirib boʻlmaydi: qiymat kiriting.",
                         "field": null_field}, status=400)
    s = MeasurementsSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    bad = _measurements_problem(s.validated_data)
    if bad is not None:
        return bad
    height = s.validated_data.get("height_cm", body.height_cm)
    merged = {**(body.measurements or {}), **s.validated_data.get("measurements", {})}
    if height == body.height_cm and merged == (body.measurements or {}):
        return Response(BodySerializer(body, context={"request": request}).data)  # nothing changed: no lock
    body.height_cm = height
    body.measurements = merged
    body.measurements_changed_at = timezone.now()
    body.save(update_fields=["height_cm", "measurements", "measurements_changed_at"])
    return Response(BodySerializer(body, context={"request": request}).data)


def _null_field(data):
    """The first null in a PATCH body/measurements/ payload ("height_cm", "measurements" or a measurement key)."""
    if not hasattr(data, "get"):
        return None
    for key in ("height_cm", "measurements"):
        if key in data and data.get(key) is None:
            return key
    m = data.get("measurements")
    if isinstance(m, dict):
        for key, value in m.items():
            if value is None:
                return key
    return None
