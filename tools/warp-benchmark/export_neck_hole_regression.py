"""Export the neck-hole wiring regression fixture (docs/09 #102): run BEFORE wiring the hole into render_tryon.

    docker compose cp tools/warp-benchmark/data/neck_hole backend:/tmp/neck_hole
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/export_neck_hole_regression.py

Writes backend/apps/tryon_engine/testdata/tryon_neck/ (gitignored: avatar photos):
  avatars/<pk>.png   the avatar photo as stored, <pk>.json its landmarks
  garments/<id>.png  the cleaned garment, <id>.json its stored landmarks (no neck_hole), <id>.fit the stored fit_mode
  polygons/<id>.json owner polygons in cleaned-garment px (28, 40 = 40-2.json, 47)
  expected/<engine>_<mode>_<id>_<pk>.png  render_tryon(...) RGB with render_flags("avatar"), code at export time
Read by tests_neck_hole: garments without a polygon (and keep_shape) must stay pixel-identical.
"""
import json
import os
import shutil

import cv2

from apps.avatars.models import Avatar
from apps.garments.landmark_checks import engine_landmarks
from apps.garments.models import Garment
from apps.tryon_engine.flags import render_flags
from apps.tryon_engine.warp import render_tryon

GARMENTS = [28, 40, 43, 44, 45, 47]
POLYGONS = {28: "28.json", 40: "40-2.json", 47: "47.json"}
ROOT = "/app/apps/tryon_engine/testdata/tryon_neck"
for d in ("avatars", "garments", "polygons", "expected"):
    os.makedirs(f"{ROOT}/{d}", exist_ok=True)

avatars = list(Avatar.objects.order_by("pk"))
for av in avatars:
    shutil.copy(av.image.path, f"{ROOT}/avatars/{av.pk}.png")
    with open(f"{ROOT}/avatars/{av.pk}.json", "w") as fh:
        json.dump(av.landmarks, fh)
for gid, name in POLYGONS.items():
    shutil.copy(f"/tmp/neck_hole/{name}", f"{ROOT}/polygons/{gid}.json")
n = 0
for gid in GARMENTS:
    g = Garment.objects.get(pk=gid)
    shutil.copy(g.image.path, f"{ROOT}/garments/{gid}.png")
    lm = {k: v for k, v in g.landmarks.items() if k != "neck_hole"}
    with open(f"{ROOT}/garments/{gid}.json", "w") as fh:
        json.dump(lm, fh)
    with open(f"{ROOT}/garments/{gid}.fit", "w") as fh:
        fh.write(g.fit_mode)
    img = cv2.imread(g.image.path, cv2.IMREAD_UNCHANGED)
    for av in avatars:
        base = cv2.imread(av.image.path, cv2.IMREAD_UNCHANGED)
        for engine, modes in (("mls", ("adapt", "keep_shape")), ("parts", ("adapt",))):
            for mode in modes:
                flags = {**render_flags("avatar"), "warp_engine": engine}
                rgb, _, _ = render_tryon(base, av.landmarks, [("tshirt", img, engine_landmarks("tshirt", lm))],
                                         1200, 600, fit_modes={"tshirt": mode}, **flags)
                cv2.imwrite(f"{ROOT}/expected/{engine}_{mode}_{gid}_{av.pk}.png", rgb)
                n += 1
print("exported", n, "renders to", ROOT)
