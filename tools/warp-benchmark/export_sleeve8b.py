"""Round 8b export (docs/06): avatars + #28, #43, #40 with the CURRENT DB landmarks (re-marked 2026-11-12).

    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/export_sleeve8b.py
    docker compose cp backend:/tmp/warp-benchmark/data/sleeve8b/. tools/warp-benchmark/data/sleeve8b/

Writes data/sleeve8b/ (gitignored, avatar photos): avatars/<pk>.png (600x1200 BGRA as render_tryon resizes it),
avatars/<pk>.json {sex, build, landmarks}, garments/<id>.png (cleaned PNG), garments/<id>.json
{name, landmarks: engine_landmarks(...)}. Read-only on the DB; the regression fixtures in testdata/ are untouched.
"""
import json
import os

import cv2

from apps.avatars.models import Avatar
from apps.garments.landmark_checks import engine_landmarks
from apps.garments.models import Garment
from apps.tryon_engine import warp

GARMENTS = [28, 43, 40]
ROOT = os.environ.get("EXPORT_ROOT", "/tmp/warp-benchmark/data/sleeve8b")  # neck run: data/neck
for d in ("avatars", "garments"):
    os.makedirs(f"{ROOT}/{d}", exist_ok=True)
for av in Avatar.objects.order_by("pk"):
    base = cv2.resize(warp._bgra(cv2.imread(av.image.path, cv2.IMREAD_UNCHANGED)), (600, 1200))
    cv2.imwrite(f"{ROOT}/avatars/{av.pk}.png", base)
    with open(f"{ROOT}/avatars/{av.pk}.json", "w") as fh:
        json.dump({"sex": av.sex, "build": av.build, "landmarks": av.landmarks}, fh)
for gid in GARMENTS:
    g = Garment.objects.get(pk=gid)
    cv2.imwrite(f"{ROOT}/garments/{gid}.png", cv2.imread(g.image.path, cv2.IMREAD_UNCHANGED))
    with open(f"{ROOT}/garments/{gid}.json", "w") as fh:
        json.dump({"name": g.name, "landmarks": engine_landmarks(g.type, g.landmarks)}, fh)
print("exported", Avatar.objects.count(), "avatars,", len(GARMENTS), "garments")
