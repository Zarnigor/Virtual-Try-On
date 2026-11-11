"""MLS benchmark round 7: fitted T-shirts, torso side ease + floor, underarm order, mid-sleeve pairs (docs/06).

    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/run_fitted7.py
    docker compose cp backend:/tmp/warp-benchmark/data/. tools/warp-benchmark/data/
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

Re-exports #28, #43, #40 from the DB (read-only, overwrites data/<id>.*). Before = round 6 (mls_fitted.warp,
round7=False, k 1.0); after = mls_fitted.warp(round7=True) at k 1.0 and 0.7. All avatars.
Writes out/results7.json, out/sheet_fitted7_k1_before_after.png (rows = garments; left block = round 6, right block =
round 7, k 1.0; 6 avatars each), out/sheet_fitted7_k.png (rows = garments; k 1.0 | 0.7 x male slim, male plus,
female plus) and out/crop_fitted7_worst.png (most uncovered body px among the after runs, shoulders/armpits 600x400).
"""
import json
import os
import shutil
import sys

import cv2
import numpy as np

sys.path.insert(0, "/tmp/warp-benchmark")
import mls  # noqa: E402
import mls_fitted as mf  # noqa: E402
import mls_landmarks as ml  # noqa: E402

from apps.avatars.models import Avatar  # noqa: E402
from apps.garments.models import Garment  # noqa: E402

GARMENTS = [28, 43, 40]
KS = [1.0, 0.7]
SHEET2_AVATARS = [("male", "slim"), ("male", "plus"), ("female", "plus")]
DATA, OUT = "/tmp/warp-benchmark/data", "/tmp/warp_benchmark"
H, W = 1200, 600
os.makedirs(OUT, exist_ok=True)
os.makedirs(DATA, exist_ok=True)
for gid in GARMENTS:
    g = Garment.objects.get(pk=gid)
    shutil.copyfile(g.image.path, f"{DATA}/{gid}.png")
    with open(f"{DATA}/{gid}.json", "w") as fh:
        json.dump({"id": gid, "name": g.name, "type": g.type, "gender": g.gender, "fit_mode": g.fit_mode,
                   "landmarks": g.landmarks}, fh, indent=1, ensure_ascii=False)


def rd(path):
    i = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    return cv2.cvtColor(i, cv2.COLOR_BGR2BGRA) if i.shape[2] == 3 else i


def cell(rgb, text):
    c = cv2.resize(rgb, (300, 600), interpolation=cv2.INTER_AREA)
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(c, text, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, col, th, cv2.LINE_AA)
    return c


avatars = list(Avatar.objects.order_by("pk"))
bases = {a.pk: rd(a.image.path) for a in avatars}
masks = {a.pk: mls.prod.figure_mask(cv2.resize(mls.prod._bgra(bases[a.pk]), (W, H))) for a in avatars}
results, skipped, rows1, rows2, worst = [], {}, [], [], None
for gid in GARMENTS:
    with open(f"{DATA}/{gid}.json") as fh:
        glm = json.load(fh)["landmarks"] or {}
    miss = ml.missing_landmarks(glm)
    if miss:
        skipped[gid] = f"missing {miss}"
        print(f"garment {gid}: skipped, missing {miss}")
        continue
    gimg = rd(f"{DATA}/{gid}.png")
    before, after, kcells = [], [], {}
    for av in avatars:
        tag = f"#{gid} {av.sex[0]}-{av.build}"
        runs = [("before", 1.0)] + [("after", k) for k in KS]
        for stage, k in runs:
            info = {}
            if stage == "before":
                layer = mf.warp(gimg, glm, av.landmarks, (W, H), k=1.0, base=bases[av.pk], info=info)
            else:
                layer = mf.warp(gimg, glm, av.landmarks, (W, H), k=k, base=bases[av.pk], info=info, round7=True)
            m = mls.metrics(layer, info, av.landmarks)
            rec = {"garment": gid, "avatar": av.pk, "stage": stage, "k": k, "runtime": round(info["runtime"], 2),
                   "rejected": info["rejected"], **m, **mf.coverage_metrics(layer, masks[av.pk], info, av.landmarks)}
            results.append(rec)
            print(json.dumps(rec, default=str))
            rgb = mls.composite(bases[av.pk], layer, av.landmarks, info)
            if stage == "before":
                before.append(cell(rgb, f"r6 k1 {tag}"))
            elif k == 1.0:
                after.append(cell(rgb, f"r7 k1 {tag}"))
            if stage == "after" and (av.sex, av.build) in SHEET2_AVATARS:
                kcells.setdefault(k, []).append(cell(rgb, f"k{k} {tag}"))
            if stage == "after" and (worst is None or rec["uncovered_px"] > worst[0]):
                worst = (rec["uncovered_px"], gid, k, av, rgb)
    rows1.append(np.hstack(before + after))
    rows2.append(np.hstack([c for k in KS for c in kcells[k]]))
if rows1:
    cv2.imwrite(f"{OUT}/sheet_fitted7_k1_before_after.png", np.vstack(rows1))
    cv2.imwrite(f"{OUT}/sheet_fitted7_k.png", np.vstack(rows2))
if worst:
    unc, gid, k, av, rgb = worst
    y0 = max(int(av.landmarks["shoulder"]["y"]) - 80, 0)
    crop = rgb[y0:y0 + 400, :].copy()
    cv2.putText(crop, f"worst after: {unc} uncovered px, #{gid} k{k} {av.sex[0]}-{av.build}", (6, 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.imwrite(f"{OUT}/crop_fitted7_worst.png", crop)
with open(f"{OUT}/results7.json", "w") as fh:
    json.dump({"skipped": skipped, "runs": results}, fh, default=str, indent=1)
print("done", len(results), "skipped", skipped)
