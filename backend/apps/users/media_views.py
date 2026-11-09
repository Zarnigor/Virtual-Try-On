"""Signed URL verification for private media files."""
import time
import hmac
import hashlib
from django.conf import settings
from django.http import FileResponse, Http404
from pathlib import Path


def _make_sig(path: str, expires: int) -> str:
    msg = f"{path}:{expires}".encode()
    return hmac.new(settings.SIGNED_URL_SECRET.encode(), msg, hashlib.sha256).hexdigest()[:24]


def make_signed_url(request, media_path: str) -> str:
    """Generate a signed URL for a media file. Called from serializers."""
    expires = int(time.time()) + settings.SIGNED_URL_TTL
    sig = _make_sig(media_path, expires)
    return request.build_absolute_uri(f"/api/media/signed/{media_path}?sig={sig}&exp={expires}")


def signed_media(request, path: str):
    sig = request.GET.get("sig", "")
    exp = request.GET.get("exp", "0")
    try:
        exp_int = int(exp)
    except ValueError:
        raise Http404
    if time.time() > exp_int:
        raise Http404
    expected = _make_sig(path, exp_int)
    if not hmac.compare_digest(sig, expected):
        raise Http404
    full_path = Path(settings.MEDIA_ROOT) / path
    if not full_path.exists():
        raise Http404
    return FileResponse(open(full_path, "rb"))
