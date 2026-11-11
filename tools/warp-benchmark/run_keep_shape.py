"""MLS single-field benchmark, round 3: `keep_shape` proposal = per-point, per-axis fit strength (docs/06).

    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/run_keep_shape.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

Inputs: the round-2 export (tools/warp-benchmark/data/<id>.png + .json, run_landmarks.py) for the oversized
garments. Gate (never invented): a garment missing any required landmark, or with its chest marked above its armpit,
is skipped and listed. Runs on all avatars: k 1.0 | uniform k 0.5 | preset A | preset B (mls_landmarks.PRESETS).
Writes out/results3.json; out/sheet_keep_shape.png (rows = garments, columns = the 4 variants x 3 avatars) and
out/crop_keep_shape_worst.png (worst fold among A/B, shoulders/armpits 600x400) only when a garment ran.
"""
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, "/tmp/warp-benchmark")
import mls  # noqa: E402
import mls_landmarks as ml  # noqa: E402

from apps.avatars.models import Avatar  # noqa: E402

GARMENTS = [44, 45]
SHEET_AVATARS = [("male", "slim"), ("male", "plus"), ("female", "average")]
VARIANTS = [("k1.0", 1.0, None), ("k0.5", 0.5, None), ("A", 1.0, ml.PRESETS["A"]), ("B", 1.0, ml.PRESETS["B"])]
DATA, OUT = "/tmp/warp-benchmark/data", "/tmp/warp_benchmark"
H, W = 1200, 600
os.makedirs(OUT, exist_ok=True)


def rd(path):
    i = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    return cv2.cvtColor(i, cv2.COLOR_BGR2BGRA) if i.shape[2] == 3 else i


def label(img, text):
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(img, text, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, col, th, cv2.LINE_AA)


def gate(glm):
    miss = ml.missing_landmarks(glm)
    if miss:
        return f"missing {miss}"
    if float(glm["chest"]["y"]) <= float(glm["armpit"]["y"]):
        return f"chest y {glm['chest']['y']} above armpit y {glm['armpit']['y']}"
    return None


avatars = list(Avatar.objects.order_by("pk"))
bases = {a.pk: rd(a.image.path) for a in avatars}
masks = {a.pk: mls.prod.figure_mask(cv2.resize(mls.prod._bgra(bases[a.pk]), (W, H))) for a in avatars}
results, skipped, rows, worst = [], {}, [], None
for gid in GARMENTS:
    path = f"{DATA}/{gid}.json"
    if not os.path.exists(path):
        skipped[gid] = "not exported (run run_landmarks.py first)"
        continue
    with open(path) as fh:
        glm = json.load(fh)["landmarks"] or {}
    why = gate(glm)
    if why:
        skipped[gid] = why
        print(f"garment {gid}: skipped, {why}")
        continue
    gimg = rd(f"{DATA}/{gid}.png")
    pbox = ml.print_bbox(gimg) if gid == 44 else None
    cells = []
    for name, k, k_map in VARIANTS:
        for av in avatars:
            info = {}
            layer = ml.warp(gimg, glm, av.landmarks, (W, H), k=k, k_map=k_map, base=bases[av.pk], info=info)
            m = mls.metrics(layer, info, av.landmarks)
            rec = {"garment": gid, "avatar": av.pk, "variant": name, "runtime": round(info["runtime"], 2),
                   "rejected": info["rejected"], **m,
                   "bare_shoulder_px": ml.bare_shoulder_px(layer, masks[av.pk], info, av.landmarks),
                   "print_distortion": ml.print_distortion(layer, info, pbox) if pbox else None,
                   "scale_at": ml.scale_at(info, ("armpit_l", "armpit_r", "cuff_in_l", "cuff_in_r"))}
            results.append(rec)
            print(json.dumps(rec, default=str))
            rgb = None
            if (av.sex, av.build) in SHEET_AVATARS:
                rgb = mls.composite(bases[av.pk], layer, av.landmarks, info)
                c = cv2.resize(rgb, (300, 600), interpolation=cv2.INTER_AREA)
                label(c, f"{name} #{gid} {av.sex[0]}-{av.build}")
                cells.append(c)
            if name in ("A", "B") and (worst is None or m["fold"] > worst[0]):
                rgb = rgb if rgb is not None else mls.composite(bases[av.pk], layer, av.landmarks, info)
                worst = (m["fold"], gid, name, av, rgb)
    rows.append(np.hstack(cells))
if rows:
    cv2.imwrite(f"{OUT}/sheet_keep_shape.png", np.vstack(rows))
if worst:
    fold, gid, name, av, rgb = worst
    y0 = max(int(av.landmarks["shoulder"]["y"]) - 80, 0)
    crop = rgb[y0:y0 + 400, :].copy()
    label(crop, f"worst A/B fold {fold:.4f}: #{gid} {name} {av.sex[0]}-{av.build}")
    cv2.imwrite(f"{OUT}/crop_keep_shape_worst.png", crop)
with open(f"{OUT}/results3.json", "w") as fh:
    json.dump({"skipped": skipped, "runs": results}, fh, default=str, indent=1)
print("done", len(results), "skipped", skipped)
