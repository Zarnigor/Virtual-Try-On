"""Shared body-photo pipeline: own body (step 4), staff avatar upload and seed_avatars all use it.

    process_body_photo(bytes) -> ProcessedBody(png, landmarks, warnings, scale)

Order (docs/09 #26, code checks first, no AI here): EXIF strip (decode + re-encode from pixels, metadata dropped,
orientation applied) -> rembg mask (u2net_human_seg) -> code checks (no person, head/feet cut, figure clipped) ->
normalize to 600x1200 RGBA (figure top y=50, axis x=300, one uniform scale) -> auto landmarks with edge points.
Raises BodyPhotoRejected(code). The AI check (prompt 02) is NOT part of this module: the own-body job runs it after
this step when BODY_AI_CHECK_ENABLED; staff avatars never call the AI (staff choose the photos).
"""
from dataclasses import dataclass, field
from io import BytesIO

from PIL import Image, ImageOps

from apps.avatars.prep import NormalizeError, detect_landmarks, landmark_warnings, normalize

MESSAGES = {
    "NO_PERSON": "Rasmda odam topilmadi.",
    "HEAD_OR_FEET_CUT": "Bosh yoki oyoqlar rasmga sigʻmagan. Butun gavda koʻrinsin.",
    "FIGURE_CLIPPED": "Gavdani 600x1200 maydonga joylab boʻlmadi. Qoʻllar va oyoqlar rasm ichida boʻlsin.",
    "CORRUPT_FILE": "Rasm fayli buzilgan yoki toʻliq yuklanmagan. Boshqa rasm tanlang.",
}


class BodyPhotoRejected(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = MESSAGES.get(code, code)
        self.internal = detail


@dataclass
class ProcessedBody:
    png: bytes  # 600x1200 RGBA
    landmarks: dict
    scale: float
    warnings: list = field(default_factory=list)


def strip_exif(data: bytes) -> Image.Image:
    """Decoded RGB pixels with the EXIF orientation applied; no metadata survives."""
    try:
        with Image.open(BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im)
            return Image.frombytes("RGB", im.size, im.convert("RGB").tobytes())
    except Exception as e:
        raise BodyPhotoRejected("CORRUPT_FILE", type(e).__name__)


def process_body_photo(data: bytes, session=None) -> ProcessedBody:
    src = strip_exif(data)
    try:
        norm = normalize(src, session=session)
    except NormalizeError as e:
        raise BodyPhotoRejected(e.code, str(e))
    lm = detect_landmarks(norm.mask, norm.gray)
    buf = BytesIO()
    norm.image.save(buf, format="PNG")
    try:
        warns = landmark_warnings(lm)
    except (KeyError, TypeError):
        warns = ["landmarks incomplete"]
    return ProcessedBody(buf.getvalue(), lm, norm.scale, warns)
