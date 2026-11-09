"""Server-side checks for uploaded images. The client check is only for UX; this one is the rule.

Everything is decided from the file's bytes, never from the client's filename or Content-Type.
The file is only read, never re-encoded: the caller stores the original bytes untouched.
"""
from django.conf import settings
from PIL import Image, UnidentifiedImageError

ALLOWED_FORMATS = {"JPEG", "PNG"}


class ImageRejected(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(code)
        self.code = code
        self.detail = detail


def _reject(code: str, **fmt) -> ImageRejected:
    messages = {
        "FILE_TOO_LARGE": "Fayl hajmi juda katta. {mb} MB dan kichik rasm yuklang.",
        "BAD_FILE_TYPE": "Faqat JPG yoki PNG formatidagi rasmlar qabul qilinadi.",
        "CORRUPT_FILE": "Rasm fayli buzilgan yoki toʻliq yuklanmagan. Boshqa rasm tanlang.",
        "IMAGE_TOO_SMALL": "Rasm juda kichik. Rasmning har bir tomoni kamida {px} px boʻlsin.",
        "IMAGE_TOO_LARGE": "Rasm oʻlchami juda katta. Kichikroq rasm yuklang.",
    }
    return ImageRejected(code, messages[code].format(**fmt))


def validate_image_upload(f, *, min_side: int) -> tuple[int, int]:
    """Check size, real format, pixel count, full decode and minimum resolution. Returns (w, h).

    Raises ImageRejected with a code and an Uzbek message. Leaves the file position at 0.
    """
    if f.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise _reject("FILE_TOO_LARGE", mb=settings.MAX_UPLOAD_MB)
    f.seek(0)
    try:
        with Image.open(f) as im:  # reads the header only
            if im.format not in ALLOWED_FORMATS:
                raise _reject("BAD_FILE_TYPE")
            w, h = im.size
            if w * h > settings.MAX_IMAGE_PIXELS:  # checked before decoding (decompression bombs)
                raise _reject("IMAGE_TOO_LARGE")
            im.load()  # full decode: truncated or corrupt pixel data fails here, not later in the worker
    except ImageRejected:
        raise
    except UnidentifiedImageError:
        raise _reject("BAD_FILE_TYPE")
    except Image.DecompressionBombError:
        raise _reject("IMAGE_TOO_LARGE")
    except (OSError, SyntaxError, ValueError, EOFError):
        raise _reject("CORRUPT_FILE")
    finally:
        f.seek(0)
    if min(w, h) < min_side:
        raise _reject("IMAGE_TOO_SMALL", px=min_side)
    return w, h
