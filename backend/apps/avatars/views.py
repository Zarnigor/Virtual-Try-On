import math
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Avatar
from .serializers import AvatarSerializer


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_avatars(request):
    avatars = Avatar.objects.all()
    return Response(AvatarSerializer(avatars, many=True, context={"request": request}).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def nearest_avatar(request):
    """
    Find the nearest avatar by sex + measurements (circumference in cm).
    Required: sex and shoulder, chest, waist, hip (all circumference cm, 20..300); else 400 MEASUREMENTS_REQUIRED.
    Converts circumference to front-width (÷π) for matching against landmark widths.
    """
    sex = request.query_params.get("sex")
    if sex not in ("male", "female"):
        return Response({"code": "SEX_REQUIRED", "detail": "Jinsni tanlang."}, status=400)

    def circ_to_front(cm):
        """Circumference in cm → front-view width in cm."""
        return float(cm) / math.pi if cm else None

    # Model (avatar) path: every measurement is required (docs/02; CLAUDE.md "Decisions already made").
    measurements, missing = {}, []
    for field in ("shoulder", "chest", "waist", "hip"):
        try:
            val = float(request.query_params.get(field, ""))
        except (ValueError, TypeError):
            val = None
        if val is None or not math.isfinite(val) or not 20 <= val <= 300:
            missing.append(field)
        else:
            measurements[field] = circ_to_front(val)
    if missing:
        return Response({"code": "MEASUREMENTS_REQUIRED", "fields": missing,
                         "detail": "Barcha oʻlchamlarni kiriting (20 dan 300 sm gacha)."}, status=400)

    avatars = Avatar.objects.filter(sex=sex)
    if not avatars.exists():
        return Response({"code": "AVATAR_NOT_FOUND", "detail": "Avatar topilmadi."}, status=404)

    best = None
    best_score = float("inf")
    for av in avatars:
        ref = av.measurements or {}
        score = 0
        count = 0
        for field, user_val in measurements.items():
            ref_val = ref.get(field)
            if ref_val is not None and user_val is not None:
                score += (user_val - circ_to_front(ref_val)) ** 2
                count += 1
        if count > 0:
            score = score / count
            if score < best_score:
                best_score = score
                best = av

    if best is None:
        best = avatars.first()

    return Response(AvatarSerializer(best, context={"request": request}).data)
