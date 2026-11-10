"""Shared body pipeline (apps/bodies/pipeline.py): EXIF strip, code checks, 600x1200 canvas, landmarks with edges."""
from io import BytesIO
from unittest import mock

import numpy as np
from django.test import SimpleTestCase
from PIL import Image

from apps.bodies.landmark_checks import validate_body_landmarks
from apps.bodies.pipeline import BodyPhotoRejected, process_body_photo
from apps.tryon_engine.tests import avatar as synthetic_avatar


def body_photo(crop_top=0, fmt="JPEG", exif=False):
    """A 1000x1600 photo with the synthetic A-pose figure; returns (bytes, rembg mask)."""
    fig, _ = synthetic_avatar()
    photo = np.full((1600, 1000, 3), 225, np.uint8)
    mask = np.zeros((1600, 1000), np.uint8)
    a = fig[:, :, 3] > 128
    y0, x0 = 200, 200
    region = (slice(y0, y0 + 1200), slice(x0, x0 + 600))
    photo[region][a] = fig[:, :, :3][a]
    mask[region][a] = 255
    photo, mask = photo[crop_top:], mask[crop_top:]
    buf = BytesIO()
    img = Image.fromarray(photo)
    kw = {}
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "SecretCam"  # Make
        kw["exif"] = ex.tobytes()
    img.save(buf, format=fmt, **kw)
    return buf.getvalue(), Image.fromarray(mask)


def run(data, mask):
    with mock.patch("rembg.remove", return_value=mask), mock.patch("rembg.new_session"):
        return process_body_photo(data, session=object())


class PipelineTests(SimpleTestCase):
    def test_canvas_landmarks_and_no_metadata(self):
        data, mask = body_photo(exif=True)
        out = run(data, mask)
        img = Image.open(BytesIO(out.png))
        self.assertEqual((img.size, img.mode), ((600, 1200), "RGBA"))
        self.assertNotIn("exif", img.info)
        alpha = np.array(img.getchannel("A")) > 128
        ys = np.nonzero(alpha.any(axis=1))[0]
        self.assertEqual(ys[0], 50)
        validate_body_landmarks(out.landmarks)  # auto landmarks are a valid editor starting point

    def test_head_or_feet_cut(self):
        data, mask = body_photo(crop_top=300)  # the head starts at y 260: cut by the photo's top edge
        with self.assertRaises(BodyPhotoRejected) as cm:
            run(data, mask)
        self.assertEqual(cm.exception.code, "HEAD_OR_FEET_CUT")

    def test_no_person(self):
        data, _ = body_photo()
        with self.assertRaises(BodyPhotoRejected) as cm:
            run(data, Image.new("L", (1000, 1600), 0))
        self.assertEqual(cm.exception.code, "NO_PERSON")

    def test_corrupt_file(self):
        with self.assertRaises(BodyPhotoRejected) as cm:
            process_body_photo(b"not an image")
        self.assertEqual(cm.exception.code, "CORRUPT_FILE")
