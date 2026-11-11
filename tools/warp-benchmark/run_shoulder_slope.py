"""MLS keep_shape benchmark, round 4: closing the bare-shoulder triangle (docs/06). Base = preset A.

    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/run_shoulder_slope.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

Variants: A | V1 = A + shoulder_slope pair | V2 = A + alignment tweak | V3 = both (mls_landmarks). Inputs: the export in
tools/warp-benchmark/data/ (run_landmarks.py); a garment missing a required landmark is skipped and listed.
Writes out/results4.json, out/sheet_shoulder_slope.png (rows = garments, columns = A | V1 | V2 | V3 x male slim, male
plus, female slim) and out/crop_shoulder_slope_worst.png (most bare-shoulder px among V1-V3, 600x400).
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
SHEET_AVATARS = [("male", "slim"), ("male", "plus"), ("female", "slim")]
VARIANTS = [("A", False, False), ("V1", True, False), ("V2", False, True), ("V3", True, True)]
DATA, OUT = "/tmp/warp-benchmark/data", "/tmp/warp_benchmark"
H, W = 1200, 600
os.makedirs(OUT, exist_ok=True)


def rd(path):
    i = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    return cv2.cvtColor(i, cv2.COLOR_BGR2BGRA) if i.shape[2] == 3 else i


def label(img, text):
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(img, text, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, col, th, cv2.LINE_AA)


avatars = list(Avatar.objects.order_by("pk"))
bases = {a.pk: rd(a.image.path) for a in avatars}
masks = {a.pk: mls.prod.figure_mask(cv2.resize(mls.prod._bgra(bases[a.pk]), (W, H))) for a in avatars}
results, skipped, rows, worst = [], {}, [], None
for gid in GARMENTS:
    with open(f"{DATA}/{gid}.json") as fh:
        glm = json.load(fh)["landmarks"] or {}
    miss = ml.missing_landmarks(glm)
    if miss:
        skipped[gid] = f"missing {miss}"
        print(f"garment {gid}: skipped, missing {miss}")
        continue
    gimg = rd(f"{DATA}/{gid}.png")
    pbox = ml.print_bbox(gimg) if gid == 44 else None
    cells = []
    for name, slope, tweak in VARIANTS:
        for av in avatars:
            info = {}
            layer = ml.warp(gimg, glm, av.landmarks, (W, H), k_map=ml.PRESETS["A"], base=bases[av.pk], info=info,
                            slope_pair=slope, align_tweak=tweak)
            m = mls.metrics(layer, info, av.landmarks)
            rec = {"garment": gid, "avatar": av.pk, "variant": name, "runtime": round(info["runtime"], 2),
                   "rejected": info["rejected"], **m,
                   "chest": "used" if "chest_l" in info["pairs"] and "chest_r" in info["pairs"] else "chest not used",
                   "bare_shoulder_px": ml.bare_shoulder_px(layer, masks[av.pk], info, av.landmarks),
                   "excess_px": ml.excess_px(layer, masks[av.pk], av.landmarks),
                   "print_distortion": ml.print_distortion(layer, info, pbox) if pbox else None,
                   "slope_pairs": [n for n in ("slope_l", "slope_r") if n in info["pairs"]]}
            results.append(rec)
            print(json.dumps(rec, default=str))
            rgb = None
            if (av.sex, av.build) in SHEET_AVATARS:
                rgb = mls.composite(bases[av.pk], layer, av.landmarks, info)
                c = cv2.resize(rgb, (300, 600), interpolation=cv2.INTER_AREA)
                label(c, f"{name} #{gid} {av.sex[0]}-{av.build}")
                cells.append(c)
            if name != "A" and (worst is None or rec["bare_shoulder_px"] > worst[0]):
                rgb = rgb if rgb is not None else mls.composite(bases[av.pk], layer, av.landmarks, info)
                worst = (rec["bare_shoulder_px"], gid, name, av, rgb)
    rows.append(np.hstack(cells))
if rows:
    cv2.imwrite(f"{OUT}/sheet_shoulder_slope.png", np.vstack(rows))
if worst:
    bare, gid, name, av, rgb = worst
    y0 = max(int(av.landmarks["shoulder"]["y"]) - 80, 0)
    crop = rgb[y0:y0 + 400, :].copy()
    label(crop, f"worst V1-V3: {bare} bare px, #{gid} {name} {av.sex[0]}-{av.build}")
    cv2.imwrite(f"{OUT}/crop_shoulder_slope_worst.png", crop)
with open(f"{OUT}/results4.json", "w") as fh:
    json.dump({"skipped": skipped, "runs": results}, fh, default=str, indent=1)
print("done", len(results), "skipped", skipped)
