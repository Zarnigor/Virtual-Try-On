"""End-to-end check of the own-body path through the real API and worker (docs/08 definition of done).

    docker compose exec -T backend python manage.py shell < tools/tryon_check/own_body_path.py
    docker compose cp backend:/tmp/own_body/. tools/tryon_check/out/own_body/

A temporary user: POST body/ (PHOTO, default /avatars/male_average.jpg) -> job -> GET body/ (600x1200, auto
landmarks) -> POST body/confirm/ -> second upload 409 -> avatars/nearest/ (400 without measurements, 200 with) ->
POST tryon/ base=body with copies of GARMENTS (default 28, 49; the copies get COPY_SIZES) -> outfit image -> GET outfits/ -> garment upload
(clean job, original deleted, 404 for another user). The user and
everything it owns is deleted at the end. Prints one line per check; exit status 1 when one fails.
"""
import os
import sys
import time

import cv2
import httpx
import numpy as np
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from rest_framework_simplejwt.tokens import RefreshToken

from apps.garments.models import Garment

API = "http://localhost:8000/api"
PHOTO = os.environ.get("PHOTO", "/avatars/male_average.jpg")
SEX = os.environ.get("SEX", "male")
GARMENTS = [int(v) for v in os.environ.get("GARMENTS", "28,49").split(",")]
SIZES = {  # valid placeholder sizes for the upload check only (docs/11)
    "tshirt": '{"chest_width": 52, "length": 70, "shoulder_width": 46}',
    "pants": '{"waist_width": 40, "hip_width": 50, "inseam": 78}',
}
COPY_SIZES = {  # sizes that fit BODY_SIZES (docs/11), so the path also runs with FIT_CHECK_ENABLED=1
    "tshirt": {"chest_width": 56, "length": 72, "shoulder_width": 46},
    "pants": {"waist_width": 44, "hip_width": 56, "inseam": 80},
}
BODY_SIZES = {"height_cm": 178, "measurements": {"chest": 100, "waist": 86, "hip": 100}}  # confirm (docs/09 #130)
OUT = "/tmp/own_body"
os.makedirs(OUT, exist_ok=True)
fails = []


def check(name, ok, note=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  [{note}]" if note else ""))
    if not ok:
        fails.append(name)


def fetch(url, flags=cv2.IMREAD_UNCHANGED):
    """Decode a signed image URL (relative or absolute, any host: the path is asked from the backend itself)."""
    path = "/" + url.split("://", 1)[-1].split("/", 1)[-1] if "://" in url else url
    r = httpx.get("http://localhost:8000" + path, timeout=60, follow_redirects=True)
    if r.status_code != 200 or not r.content:
        print(f"     fetch {r.status_code} {path[:60]}")
        return None
    return cv2.imdecode(np.frombuffer(r.content, np.uint8), flags)


def poll(c, job_id, limit=120):
    for _ in range(limit):
        j = c.get(f"/jobs/{job_id}/").json()
        if j["status"] in ("done", "failed"):
            return j
        time.sleep(1)
    return j


User = get_user_model()
User.objects.filter(email__startswith="own-body-check").delete()
user = User.objects.create_user(email="own-body-check@example.com", password="x-check-only-1")
try:
    c = httpx.Client(base_url=API, timeout=60,
                     headers={"Authorization": f"Bearer {RefreshToken.for_user(user).access_token}"})
    with open(PHOTO, "rb") as fh:
        r = c.post("/body/", files={"photo": ("p.jpg", fh.read(), "image/jpeg")},
                   data={"is_adult_confirmed": "true", "sex": SEX})
    check("upload 201", r.status_code == 201, str(r.status_code))
    job = poll(c, r.json()["job_id"])
    check("body job done", job["status"] == "done", f"{job.get('error_code')} {job.get('result')}")
    body = c.get("/body/").json()
    img = fetch(body["image_url"])
    check("body image 600x1200", img is not None and img.shape[:2] == (1200, 600), str(None if img is None else img.shape))
    check("auto landmarks", len(body["landmarks"]) >= 10, ", ".join(sorted(body["landmarks"])))
    r = c.post("/tryon/", json={"base": "body", "garment_ids": [GARMENTS[0]]})  # body checked before garments
    check("tryon on an unconfirmed body 400 BODY_NOT_CONFIRMED", r.json().get("code") == "BODY_NOT_CONFIRMED", r.text[:120])
    r = c.post("/body/confirm/", json={"landmarks": {"head_top": {"y": 50}}, **BODY_SIZES})
    check("confirm with broken landmarks 400", r.status_code == 400 and r.json().get("code") == "LANDMARKS_INVALID")
    r = c.post("/body/confirm/", json={"landmarks": body["landmarks"]})
    check("confirm without sizes 400 (docs/09 #130)",
          r.status_code == 400 and (r.json().get("code"), r.json().get("field")) == ("MEASUREMENTS_INVALID", "height_cm"))
    r = c.post("/body/confirm/", json={"landmarks": body["landmarks"], **BODY_SIZES})
    check("confirm 200", r.status_code == 200, r.text[:200])
    if r.status_code == 200:
        sw = r.json()["measurements"].get("shoulder_width")
        check("shoulder_width estimated from the landmarks", r.json()["shoulder_width_estimated"] is True and sw,
              f"{sw} cm")
    with open(PHOTO, "rb") as fh:
        r = c.post("/body/", files={"photo": ("p.jpg", fh.read(), "image/jpeg")},
                   data={"is_adult_confirmed": "true", "sex": SEX})
    check("upload over a confirmed body 409", r.status_code == 409)
    r = c.get("/avatars/nearest/", params={"sex": SEX, "chest": 100})
    check("nearest without all measurements 400", r.status_code == 400 and r.json()["code"] == "MEASUREMENTS_REQUIRED")
    r = c.get("/avatars/nearest/", params={"sex": SEX, "shoulder": 115, "chest": 100, "waist": 85, "hip": 100})
    check("nearest 200", r.status_code == 200, str(r.json().get("build")))
    avatar_id = r.json().get("id")
    ids = []
    for gid in GARMENTS:  # private copies for the temporary user
        g = Garment.objects.get(pk=gid)
        mine = Garment(owner=user, name=f"check {gid}", type=g.type, landmarks=g.landmarks, status=g.status,
                       fit_mode=g.fit_mode, gender="unisex", sizes=COPY_SIZES[g.type])
        mine.image.save(f"check_{gid}.png", ContentFile(g.image.read()), save=True)
        ids.append(mine.pk)
    for base, extra in (("body", {}), ("avatar", {"avatar_id": avatar_id})):
        r = c.post("/tryon/", json={"base": base, "garment_ids": ids, **extra})
        check(f"tryon {base} accepted", r.status_code in (200, 201, 202), r.text[:200])
        if r.status_code >= 300:
            continue
        job = poll(c, r.json()["job_id"])
        check(f"tryon {base} job done", job["status"] == "done", f"{job.get('error_code')} {job.get('result')}")
        outfit = c.get(f"/outfits/{r.json()['outfit_id']}/").json()
        res = fetch(outfit["result_url"], cv2.IMREAD_COLOR)
        check(f"tryon {base} result 600x1200", res is not None and res.shape[:2] == (1200, 600))
        if res is not None:
            cv2.imwrite(f"{OUT}/tryon_{base}.png", res)
    other = User.objects.create_user(email="own-body-check-2@example.com", password="x-check-only-2")
    c2 = httpx.Client(base_url=API, timeout=30,
                      headers={"Authorization": f"Bearer {RefreshToken.for_user(other).access_token}"})
    check("outfits listed", len(c.get("/outfits/").json()) == 2)
    src = Garment.objects.get(pk=GARMENTS[0])  # garment upload: clean job, original deleted, landmarks saved
    r = c.post("/garments/", files={"photo": ("g.png", src.image.read(), "image/png")}, data={"type": src.type, "sizes": SIZES[src.type]})
    check("garment upload 201", r.status_code == 201, r.text[:200])
    if r.status_code == 201:
        gid = r.json()["garment"]["id"] if "garment" in r.json() else r.json()["id"]
        job = poll(c, r.json()["job_id"])
        check("garment job done", job["status"] == "done", f"{job.get('error_code')} {job.get('result')}")
        up = Garment.objects.get(pk=gid)
        check("garment cleaned image stored, original deleted", bool(up.image) and not up.original_image)
        check("another user gets 404 for the garment", c2.get(f"/garments/{gid}/").status_code == 404)
    check("another user sees no body (404)", c2.get("/body/").status_code == 404)
    other.delete()
    check("body delete 204", c.delete("/body/").status_code in (200, 204))
    check("outfit of the body gone, avatar outfit kept", len(c.get("/outfits/").json()) == 1)
finally:
    user.delete()
print("FAILED: " + ", ".join(fails) if fails else "ALL OK")
sys.exit(1 if fails else 0)
