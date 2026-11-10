"""Try-on contact sheets: every avatar x every garment set, one image per garment set (6 avatars side by side).

Runs inside the backend container (reads the DB and media, writes nothing to the DB):
    docker compose exec -T backend python manage.py shell < tools/tryon_check/matrix.py
    docker compose cp backend:/tmp/tryon_matrix/. tools/tryon_check/out/matrix/

Garment sets: each T-shirt and each pants with saved landmarks alone, then every T-shirt + pants pair.
Env: MATRIX_TSHIRTS / MATRIX_PANTS = comma-separated garment ids (default: all with landmarks);
     MATRIX_ONLY = comma-separated sheet names to render (e.g. "t28+p18,t17");
     MATRIX_CROP = "x0,y0": each cell is the 300x600 window of the result at that offset, at full resolution
     (a zoomed sheet for edges and seams; the file gets the suffix _x0_y0).
Each cell is the 600x1200 result downscaled to 300x600 (INTER_AREA), labelled with the avatar.
`garments.png` shows the source garments with their landmarks (to tell which id is which).
"""
import os

import cv2
import numpy as np
from django.conf import settings

from apps.avatars.models import Avatar
from apps.garments.models import Garment
from apps.tryon_engine import warp
from apps.tryon_engine.flags import render_flags

OUT = "/tmp/tryon_matrix"
os.makedirs(OUT, exist_ok=True)
H, W = settings.CANVAS_H, settings.CANVAS_W
CELL = (300, 600)
CROP = [int(v) for v in os.environ.get("MATRIX_CROP", "").split(",") if v.strip()]


def read_rgba(path):
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"cannot read {path}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2BGRA) if img.shape[2] == 3 else img


def ids(env):
    v = os.environ.get(env, "")
    return [int(x) for x in v.split(",") if x.strip()]


def garments_of(gtype, env):
    qs = Garment.objects.filter(type=gtype).exclude(landmarks={}).order_by("pk")
    if ids(env):
        qs = qs.filter(pk__in=ids(env))
    return [(g.pk, gtype, read_rgba(g.image.path), g.landmarks) for g in qs]


def label(img, text):
    cv2.putText(img, text, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 3, cv2.LINE_AA)
    cv2.putText(img, text, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)


def garment_sheet(gs):
    cells = []
    for pk, gtype, img, lm in gs:
        h, w = img.shape[:2]
        k = min(CELL[0] / w, CELL[1] / h)
        small = cv2.resize(img, (max(int(w * k), 1), max(int(h * k), 1)), interpolation=cv2.INTER_AREA)
        cell = np.full((CELL[1], CELL[0], 3), 200, np.uint8)
        a = small[:, :, 3:4] / 255.0
        sh, sw = small.shape[:2]
        cell[:sh, :sw] = (small[:, :, :3] * a + cell[:sh, :sw] * (1 - a)).astype(np.uint8)

        def dot(x, y):
            cv2.circle(cell, (int(x * k), int(y * k)), 3, (0, 0, 255), -1)

        for name, v in lm.items():
            if "left_x" in v:
                dot(v["left_x"], v["y"]); dot(v["right_x"], v["y"])
            for sub in v.values():
                if isinstance(sub, dict):
                    if "x" in sub:
                        dot(sub["x"], sub["y"])
                    elif "left_x" in sub:
                        dot(sub["left_x"], sub.get("y", v.get("y", 0))); dot(sub["right_x"], sub.get("y", v.get("y", 0)))
        label(cell, f"#{pk} {gtype} {w}x{h}")
        cells.append(cell)
    if cells:
        cv2.imwrite(f"{OUT}/garments.png", np.hstack(cells))


def run():
    tshirts, pants = garments_of("tshirt", "MATRIX_TSHIRTS"), garments_of("pants", "MATRIX_PANTS")
    garment_sheet(tshirts + pants)
    sets = [[t] for t in tshirts] + [[p] for p in pants] + [[t, p] for t in tshirts for p in pants]
    only = [x for x in os.environ.get("MATRIX_ONLY", "").split(",") if x]
    avatars = list(Avatar.objects.order_by("pk"))
    bases = {av.pk: read_rgba(av.image.path) for av in avatars}
    for gset in sets:
        name = "+".join(f"{g[1][0]}{g[0]}" for g in gset)
        if only and name not in only:
            continue
        cells = []
        for av in avatars:
            try:
                rgb, warns, _ = warp.render_tryon(bases[av.pk], av.landmarks, [(g[1], g[2], g[3]) for g in gset],
                                                  H, W, **render_flags("avatar"))
            except Exception as e:  # a failed cell is shown, not hidden
                rgb, warns = np.full((H, W, 3), (200, 200, 255), np.uint8), [f"ERROR {e!r}"]
                print(f"FAIL {name} avatar {av.pk}: {e!r}")
            if CROP:
                cell = np.ascontiguousarray(rgb[CROP[1]:CROP[1] + CELL[1], CROP[0]:CROP[0] + CELL[0]])
            else:
                cell = cv2.resize(rgb, CELL, interpolation=cv2.INTER_AREA)
            label(cell, f"{av.pk} {av.sex} {av.build}")
            cells.append(cell)
            if warns:
                print(f"{name} avatar {av.pk}: {warns}")
        suffix = f"_{CROP[0]}_{CROP[1]}" if CROP else ""
        cv2.imwrite(f"{OUT}/{name}{suffix}.png", np.hstack(cells))
        print("sheet", name)


run()
