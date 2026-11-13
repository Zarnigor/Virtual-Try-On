"""Manual check of the PRODUCTION neck-hole wiring (docs/09 #102): render_tryon with TRYON_WARP=mls, adapt.

    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/run_tryon_neck.py
    docker compose cp backend:/tmp/tryon_neck/. tools/warp-benchmark/out/

Reads backend/apps/tryon_engine/testdata/tryon_neck/ (export_neck_hole_regression.py). For #40, #28, #43, #47 x 6
avatars: before (no polygon) | after (the owner polygon in landmarks.neck_hole; #43 has none, so after = before),
neck-zone crop at 3x. Writes tryon_neck_<id>.png and tryon_neck.md (changed px, fabric left in the hole, runtime).
"""
import json
import os
import time

import cv2
import numpy as np

from apps.garments.landmark_checks import engine_landmarks
from apps.tryon_engine.flags import render_flags
from apps.tryon_engine.warp import render_tryon

FIX = "/app/apps/tryon_engine/testdata/tryon_neck"
OUT = "/tmp/tryon_neck"
os.makedirs(OUT, exist_ok=True)
NAMES = {1: "m-slim", 2: "m-average", 3: "m-plus", 4: "f-slim", 5: "f-average", 6: "f-plus"}


def label(img, text):
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(img, text, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, th, cv2.LINE_AA)
    return img


lines = ["| garment | avatar | polygon | neck_hole used | changed px (after vs before) | fabric left in hole px | "
         "quality warnings | runtime s |", "|---|---|---|---|---|---|---|---|"]
for gid in ("40", "28", "43", "47"):
    g = cv2.imread(f"{FIX}/garments/{gid}.png", cv2.IMREAD_UNCHANGED)
    glm = json.load(open(f"{FIX}/garments/{gid}.json"))
    ppath = f"{FIX}/polygons/{gid}.json"
    poly = json.load(open(ppath))["polygon"] if os.path.exists(ppath) else None
    rows = []
    for pk in range(1, 7):
        base = cv2.imread(f"{FIX}/avatars/{pk}.png", cv2.IMREAD_UNCHANGED)
        blm = json.load(open(f"{FIX}/avatars/{pk}.json"))
        flags = {**render_flags("avatar"), "warp_engine": "mls"}
        outs = {}
        for name, lm in (("before", glm), ("after", {**glm, "neck_hole": {"polygon": poly}} if poly else glm)):
            t0 = time.perf_counter()
            rgb, _, dbg = render_tryon(base, blm, [("tshirt", g, engine_landmarks("tshirt", lm))], 1200, 600,
                                       fit_modes={"tshirt": "adapt"}, **flags)
            outs[name] = (rgb, dbg, time.perf_counter() - t0)
        (b_rgb, _, _), (a_rgb, a_dbg, a_t) = outs["before"], outs["after"]
        w = a_dbg.get("mls", {}).get("neck_weight")
        fab = int(((a_dbg["tshirt_layer"][:, :, 3] >= 128) & (w >= 0.5)).sum()) if w is not None else "-"
        lines.append(f"| #{gid} | {NAMES[pk]} | {'yes' if poly else 'no'} | {a_dbg['neck_hole']} | "
                     f"{int((a_rgb != b_rgb).any(2).sum())} | {fab} | {', '.join(a_dbg['quality_warnings']) or '-'} | "
                     f"{a_t:.2f} |")
        y0, y1 = max(int(blm["neck"]["y"]) - 30, 0), min(int(blm["shoulder"]["y"]) + 130, 1200)
        x0, x1 = max(int(blm["neck"]["left_x"]) - 70, 0), min(int(blm["neck"]["right_x"]) + 70, 600)
        cells = [label(cv2.resize(rgb[y0:y1, x0:x1], None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST),
                       f"{name} #{gid} {NAMES[pk]}") for name, rgb in (("before", b_rgb), ("after", a_rgb))]
        rows.append(np.hstack(cells))
    wmax = max(r.shape[1] for r in rows)
    cv2.imwrite(f"{OUT}/tryon_neck_{gid}.png", np.vstack(
        [np.pad(r, ((0, 0), (0, wmax - r.shape[1]), (0, 0)), constant_values=255) for r in rows]))
open(f"{OUT}/tryon_neck.md", "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
