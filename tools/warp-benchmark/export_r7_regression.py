"""Export the MLS r7 regression fixture (round 8, docs/06): run BEFORE changing mls.py, never after.

    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/export_r7_regression.py

Writes backend/apps/tryon_engine/testdata/mls_r7/ (gitignored: avatar photos):
  avatars/<pk>.png   the avatar resized to 600x1200 BGRA exactly as render_tryon does, <pk>.json its landmarks
  garments/<id>.png  the cleaned garment, <id>.json engine_landmarks(...) as the try-on task passes them
  expected/<id>_<pk>.png  mls.tshirt_layer(..., "adapt") with the code at export time (lossless BGRA)
Read by tests_mls.MlsR7RegressionTests: sleeve_variant="r7" (the default) must stay pixel-identical.
"""
import json
import os

import cv2

from apps.avatars.models import Avatar
from apps.garments.landmark_checks import engine_landmarks
from apps.garments.models import Garment
from apps.tryon_engine import mls, warp

GARMENTS = [28, 43, 40]
H, W = 1200, 600
ROOT = "/app/apps/tryon_engine/testdata/mls_r7"
for d in ("avatars", "garments", "expected"):
    os.makedirs(f"{ROOT}/{d}", exist_ok=True)

avatars = list(Avatar.objects.order_by("pk"))
for av in avatars:
    base = cv2.resize(warp._bgra(cv2.imread(av.image.path, cv2.IMREAD_UNCHANGED)), (W, H))
    cv2.imwrite(f"{ROOT}/avatars/{av.pk}.png", base)
    with open(f"{ROOT}/avatars/{av.pk}.json", "w") as fh:
        json.dump(av.landmarks, fh)
for gid in GARMENTS:
    g = Garment.objects.get(pk=gid)
    img = cv2.imread(g.image.path, cv2.IMREAD_UNCHANGED)
    cv2.imwrite(f"{ROOT}/garments/{gid}.png", img)
    glm = engine_landmarks(g.type, g.landmarks)
    with open(f"{ROOT}/garments/{gid}.json", "w") as fh:
        json.dump(glm, fh)
    for av in avatars:
        base = cv2.imread(f"{ROOT}/avatars/{av.pk}.png", cv2.IMREAD_UNCHANGED)
        layer, info = mls.tshirt_layer(img, glm, av.landmarks, warp.figure_mask(base), "adapt", H, W)
        cv2.imwrite(f"{ROOT}/expected/{gid}_{av.pk}.png", layer)
        print(gid, av.pk, av.sex, av.build, "rejected", info["rejected"], f"{info['runtime']:.2f}s")
print("done")
