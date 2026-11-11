"""MLS single-field benchmark, round 2 (marked landmarks + fit strength k): docs/06. Benchmark only.

    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/run_landmarks.py
    docker compose cp backend:/tmp/warp-benchmark/data/. tools/warp-benchmark/data/
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

1. Export (DB read-only): data/<id>.png (cleaned garment) + data/<id>.json (landmarks, type, gender, name).
2. Runs from those files: every garment x the 6 avatars at alpha 1.0, k 1.0; OVERSIZED also at alpha 1.5 (k 1.0)
   and k 0.5 (alpha 1.0). A garment missing any required landmark is skipped and listed (never filled in).
3. out/sheet_mls_k1.png and out/sheet_production.png (same layout, cells 300x600), out/sheet_k05_vs_k1.png
   (oversized, 3 avatars), out/crop_worst.png (shoulders/armpits 600x400 of the worst fold), out/results2.json.
"""
import json
import os
import shutil
import sys

import cv2
import numpy as np

sys.path.insert(0, "/tmp/warp-benchmark")
import mls  # noqa: E402
import mls_landmarks as ml  # noqa: E402

from apps.avatars.models import Avatar  # noqa: E402
from apps.garments.models import Garment  # noqa: E402
from apps.garments.landmark_checks import engine_landmarks  # noqa: E402
from apps.tryon_engine import warp as prod  # noqa: E402
from apps.tryon_engine.flags import render_flags  # noqa: E402

GARMENTS = [28, 45, 44, 43, 40]
OVERSIZED = [45, 44]
SMALL_AVATARS = 3  # first, middle and last avatar for the k sheet
DATA, OUT = "/tmp/warp-benchmark/data", "/tmp/warp_benchmark"
H, W = 1200, 600
os.makedirs(DATA, exist_ok=True)
os.makedirs(OUT, exist_ok=True)


def rd(path):
    i = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    return cv2.cvtColor(i, cv2.COLOR_BGR2BGRA) if i.shape[2] == 3 else i


def label(img, text):
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(img, text, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, col, th, cv2.LINE_AA)


def cell(rgb, text):
    c = cv2.resize(rgb, (300, 600), interpolation=cv2.INTER_AREA)
    label(c, text)
    return c


# 1. export (read-only)
for gid in GARMENTS:
    g = Garment.objects.get(pk=gid)
    shutil.copyfile(g.image.path, f"{DATA}/{gid}.png")
    with open(f"{DATA}/{gid}.json", "w") as fh:
        json.dump({"id": gid, "name": g.name, "type": g.type, "gender": g.gender, "landmarks": g.landmarks}, fh,
                  indent=1, ensure_ascii=False)

avatars = list(Avatar.objects.order_by("pk"))
bases = {a.pk: rd(a.image.path) for a in avatars}
small = [avatars[0], avatars[len(avatars) // 2], avatars[-1]][:SMALL_AVATARS]
results, skipped, rows_m, rows_p, k_rows = [], {}, [], [], []
worst = None
for gid in GARMENTS:
    gimg = rd(f"{DATA}/{gid}.png")
    with open(f"{DATA}/{gid}.json") as fh:
        glm = json.load(fh)["landmarks"] or {}
    miss = ml.missing_landmarks(glm)
    if miss:
        skipped[gid] = miss
        print(f"garment {gid}: skipped, missing {miss}")
        continue
    cases = [(1.0, 1.0)] + ([(1.5, 1.0), (1.0, 0.5)] if gid in OVERSIZED else [])
    cm, cp, k1, k05 = [], [], [], []
    for av in avatars:
        tag = f"av{av.pk} {av.sex[0]}-{av.build}"
        for alpha, k in cases:
            info = {}
            layer = ml.warp(gimg, glm, av.landmarks, (W, H), alpha=alpha, k=k, base=bases[av.pk], info=info)
            m = mls.metrics(layer, info, av.landmarks)
            rec = {"garment": gid, "avatar": av.pk, "alpha": alpha, "k": k, "runtime": round(info["runtime"], 2),
                   "rejected": info["rejected"], **m}
            if gid in OVERSIZED:
                rec["scale_at"] = ml.scale_at(info, ("armpit_l", "armpit_r", "cuff_in_l", "cuff_in_r"))
            results.append(rec)
            print(json.dumps(rec, default=str))
            if (alpha, k) == (1.0, 1.0):
                rgb = mls.composite(bases[av.pk], layer, av.landmarks, info)
                cm.append(cell(rgb, f"MLS k1 #{gid} {tag}"))
                if worst is None or m["fold"] > worst[0]:
                    worst = (m["fold"], gid, av, rgb)
                if gid in OVERSIZED and av in small:
                    k1.append(cell(rgb, f"k1.0 #{gid} {tag}"))
            if (alpha, k) == (1.0, 0.5) and av in small:
                k05.append(cell(mls.composite(bases[av.pk], layer, av.landmarks, info), f"k0.5 #{gid} {tag}"))
        rgb, _, _ = prod.render_tryon(bases[av.pk], av.landmarks, [("tshirt", gimg, engine_landmarks("tshirt", glm))], H, W,
                                      **render_flags("avatar"))
        cp.append(cell(rgb, f"prod #{gid} {tag}"))
    rows_m.append(np.hstack(cm))
    rows_p.append(np.hstack(cp))
    if k1:
        k_rows.append(np.hstack(k05 + k1))

cv2.imwrite(f"{OUT}/sheet_mls_k1.png", np.vstack(rows_m))
cv2.imwrite(f"{OUT}/sheet_production.png", np.vstack(rows_p))
if k_rows:
    cv2.imwrite(f"{OUT}/sheet_k05_vs_k1.png", cv2.resize(np.vstack(k_rows), None, fx=0.6, fy=0.6,
                                                         interpolation=cv2.INTER_AREA))
if worst:
    fold, gid, av, rgb = worst
    y0 = max(int(av.landmarks["shoulder"]["y"]) - 80, 0)
    crop = rgb[y0:y0 + 400, :].copy()
    label(crop, f"worst fold {fold:.4f}: #{gid} av{av.pk} {av.sex[0]}-{av.build} (k1, alpha 1)")
    cv2.imwrite(f"{OUT}/crop_worst.png", crop)
with open(f"{OUT}/results2.json", "w") as fh:
    json.dump({"skipped": skipped, "runs": results}, fh, default=str, indent=1)
print("done", len(results), "skipped", skipped)
