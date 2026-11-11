"""MLS single-field benchmark: garments x avatars, metrics + two contact sheets (MLS, production) in one layout.

    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/run.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

Env: BENCH_GARMENTS (default 39,36,28,17), BENCH_ALPHAS (default 1.0,1.5; the sheet uses the first),
BENCH_CROP = "garment,avatar,alpha": writes crop_<...>.png (shoulders/armpits, 600x400) for that case.
Reads the DB and media only; writes nothing to the DB.
"""
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, "/tmp/warp-benchmark")
import mls  # noqa: E402

from apps.avatars.models import Avatar  # noqa: E402
from apps.garments.models import Garment  # noqa: E402
from apps.tryon_engine import warp as prod  # noqa: E402
from apps.tryon_engine.flags import render_flags  # noqa: E402

OUT = "/tmp/warp_benchmark"
os.makedirs(OUT, exist_ok=True)
H, W = 1200, 600


def rd(path):
    i = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    return cv2.cvtColor(i, cv2.COLOR_BGR2BGRA) if i.shape[2] == 3 else i


def label(img, text):
    cv2.putText(img, text, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 3, cv2.LINE_AA)
    cv2.putText(img, text, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)


gids = [int(x) for x in os.environ.get("BENCH_GARMENTS", "39,36,28,17").split(",")]
alphas = [float(x) for x in os.environ.get("BENCH_ALPHAS", "1.0,1.5").split(",")]
crop = os.environ.get("BENCH_CROP", "")
avatars = list(Avatar.objects.order_by("pk"))
bases = {a.pk: rd(a.image.path) for a in avatars}
rows_mls, rows_prod, results = [], [], []
for gid in gids:
    g = Garment.objects.get(pk=gid)
    gimg = rd(g.image.path)
    if not g.landmarks:
        print(f"garment {gid}: no landmarks, skipped (auto-detection of the base landmarks is not attempted)")
        continue
    cells_m, cells_p = [], []
    for av in avatars:
        for alpha in alphas:
            layer, info = mls.warp(gimg, g.landmarks, av.landmarks, (W, H), base=bases[av.pk], alpha=alpha)
            if layer is None:
                print(f"garment {gid} avatar {av.pk}: skipped, auto {info['auto']}")
                break
            m = mls.metrics(layer, info, av.landmarks)
            rec = {"garment": gid, "avatar": av.pk, "alpha": alpha, "runtime": round(info["runtime"], 2),
                   "auto": info["auto"], "rejected": info["rejected"], **m}
            results.append(rec)
            print(json.dumps(rec, default=str))
            if alpha == alphas[0]:
                rgb = mls.composite(bases[av.pk], layer, av.landmarks, info)
                cell = cv2.resize(rgb, (300, 600), interpolation=cv2.INTER_AREA)
                label(cell, f"MLS #{gid} av{av.pk} {av.sex[0]}-{av.build}")
                cells_m.append(cell)
            if crop == f"{gid},{av.pk},{alpha}":
                rgb = mls.composite(bases[av.pk], layer, av.landmarks, info)
                y0 = int(av.landmarks["shoulder"]["y"]) - 60
                cv2.imwrite(f"{OUT}/crop_{gid}_{av.pk}_{alpha}.png",
                            cv2.resize(rgb[y0:y0 + 200, 100:500], (600, 300), interpolation=cv2.INTER_CUBIC))
        else:
            rgb, _, _ = prod.render_tryon(bases[av.pk], av.landmarks, [("tshirt", gimg, g.landmarks)], H, W,
                                          **render_flags("avatar"))
            cell = cv2.resize(rgb, (300, 600), interpolation=cv2.INTER_AREA)
            label(cell, f"prod #{gid} av{av.pk} {av.sex[0]}-{av.build}")
            cells_p.append(cell)
            continue
        cells_m, cells_p = [], []
        break
    if cells_m:
        rows_mls.append(np.hstack(cells_m))
        rows_prod.append(np.hstack(cells_p))
if rows_mls:
    cv2.imwrite(f"{OUT}/sheet_mls.png", np.vstack(rows_mls))
    cv2.imwrite(f"{OUT}/sheet_production.png", np.vstack(rows_prod))
with open(f"{OUT}/results.json", "w") as fh:
    json.dump(results, fh, default=str, indent=1)
print("done", len(results))
