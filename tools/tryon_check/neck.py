"""Neck before/after crops (3x zoom): garment x 6 avatars, top row TRYON_NECK_FIX off, bottom row on.

    docker compose exec -T backend python manage.py shell < tools/tryon_check/neck.py
    docker compose cp backend:/tmp/tryon_neck/. tools/tryon_check/out/neck/

Garments: every T-shirt with landmarks in the DB (ids in NECK_IDS, default 28,34,17; missing ids are skipped) plus
`white28`: garment 28 recoloured to a white T-shirt IN MEMORY (never saved; the inner back stays darker than the ring).
Crop: 110 x 90 px around the avatar's neck landmark, upscaled 3x (Lanczos).
"""
import os

import cv2
import numpy as np

from apps.avatars.models import Avatar
from apps.garments.models import Garment
from apps.tryon_engine import warp

OUT = "/tmp/tryon_neck"
os.makedirs(OUT, exist_ok=True)
ZOOM, CW, CH = 3, 110, 90


def read(path):
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    return cv2.cvtColor(img, cv2.COLOR_BGR2BGRA) if img.shape[2] == 3 else img


def white_variant(img):
    out = img.copy()
    lum = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY).astype(np.float32)
    v = np.clip(165 + 3 * lum, 150, 252).astype(np.uint8)
    out[:, :, :3] = v[:, :, None]
    return out


def garments():
    ids = [int(x) for x in os.environ.get("NECK_IDS", "28,34,17").split(",")]
    out = []
    for pk in ids:
        g = Garment.objects.filter(pk=pk, type="tshirt").exclude(landmarks={}).first()
        if g is None:
            print(f"garment {pk}: not in the database, skipped")
            continue
        out.append((f"t{pk}", read(g.image.path), g.landmarks))
        if pk == 28:
            out.append(("white28", white_variant(read(g.image.path)), g.landmarks))
    return out


def label(img, text):
    cv2.putText(img, text, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 3, cv2.LINE_AA)
    cv2.putText(img, text, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)


def crop(rgb, lm):
    n = lm["neck"]
    cx, cy = int((n["left_x"] + n["right_x"]) / 2), int(n["y"]) - 15
    x0, y0 = max(cx - CW // 2, 0), max(cy, 0)
    c = np.ascontiguousarray(rgb[y0:y0 + CH, x0:x0 + CW])
    return cv2.resize(c, None, fx=ZOOM, fy=ZOOM, interpolation=cv2.INTER_LANCZOS4)


for name, gimg, glm in garments():
    rows = {False: [], True: []}
    for av in Avatar.objects.order_by("pk"):
        base = read(av.image.path)
        for fix in (False, True):
            rgb, warns, _ = warp.render_tryon(base, av.landmarks, [("tshirt", gimg, glm)], neck_fix=fix)
            cell = crop(rgb, av.landmarks)
            label(cell, f"{av.pk} {av.sex} {av.build} {'AFTER' if fix else 'before'}")
            rows[fix].append(cell)
    cv2.imwrite(f"{OUT}/{name}.png", np.vstack([np.hstack(rows[False]), np.hstack(rows[True])]))
    print("sheet", name)
