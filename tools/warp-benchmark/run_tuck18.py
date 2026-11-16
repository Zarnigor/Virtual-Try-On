"""Benchmark round 18: pants tucked under an MLS T-shirt (docs/06 "Pants under the T-shirt, round 18").

    docker compose exec -T backend rm -rf /tmp/warp_benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/run_tuck18.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

Outfits (T-shirt id + pants id) x every avatar through warp.render_tryon with the settings flags; columns off
(pants_tuck=False) | tuck (pants_tuck=True; adapt T-shirts only, keep_shape is not touched). Metrics: wing px = pants px (alpha >= 128) drawn left / right of the
T-shirt's torso run on the rows above the T-shirt's bottom row; uncovered = figure px covered by a garment layer in
"off" and by none in "tuck" (gate: 0). Writes out/table_tuck18.md and out/sheet_tuck18_<tshirt>_<pants>.png.
"""
import os

import cv2
import numpy as np

from apps.avatars.models import Avatar
from apps.garments.landmark_checks import engine_landmarks
from apps.garments.models import Garment
from apps.tryon_engine import warp
from apps.tryon_engine.flags import render_flags

OUTFITS = [tuple(int(v) for v in o.split("+")) for o in
           os.environ.get("OUTFITS", "28+51,43+48,40+49,44+18,45+51").split(",")]
H, W = 1200, 600
OUT = "/tmp/warp_benchmark"
os.makedirs(OUT, exist_ok=True)
flags = {k: v for k, v in render_flags("avatar").items() if k != "pants_tuck"}


def load(path):
    return cv2.imread(path, cv2.IMREAD_UNCHANGED)


def wing_px(dbg):
    shirt = dbg["final_layers"]["tshirt"][:, :, 3] >= 128
    pants = dbg["final_layers"]["pants"][:, :, 3] >= 128
    ax = int(round(warp._crotch_x(dbg["_lm"])))
    n = 0
    for y in np.where(shirt.any(axis=1))[0]:
        run = next((q for q in warp._runs(shirt[y]) if q[0] <= ax <= q[1]), None)
        if run:
            n += int(pants[y, :run[0]].sum() + pants[y, run[1] + 1:].sum())
    return n


rows, fails = [], 0
avatars = list(Avatar.objects.order_by("id"))
for tid, pid in OUTFITS:
    t, p = Garment.objects.get(id=tid), Garment.objects.get(id=pid)
    garments = [(g.type, load(g.image.path), engine_landmarks(g.type, g.landmarks)) for g in (t, p)]
    fit = {"tshirt": t.fit_mode, "pants": p.fit_mode}
    cells, tot = [], {"off": 0, "tuck": 0, "unc": 0}
    for av in avatars:
        base = load(av.image.path)
        res = {}
        for name, on in (("off", False), ("tuck", True)):
            img, _, dbg = warp.render_tryon(base, av.landmarks, garments, H, W, fit_modes=fit, pants_tuck=on, **flags)
            dbg["_lm"] = av.landmarks
            res[name] = (img, dbg)
            cv2.putText(img, f"#{tid}+#{pid} {av.sex[0]}-{av.build} {name}", (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1,
                        cv2.LINE_AA)
        cov = {n: np.maximum(d["final_layers"]["tshirt"][:, :, 3], d["final_layers"]["pants"][:, :, 3]) >= 128
               for n, (_, d) in res.items()}
        mask = warp.figure_mask(cv2.resize(warp._bgra(base), (W, H)))
        unc = int((cov["off"] & ~cov["tuck"] & mask).sum())
        tot["off"] += wing_px(res["off"][1]); tot["tuck"] += wing_px(res["tuck"][1]); tot["unc"] += unc
        fails += unc > 0
        cells.append(np.hstack([res["off"][0], res["tuck"][0]]))
    sheet = np.vstack([np.hstack(cells[:3]), np.hstack(cells[3:])]) if len(cells) == 6 else np.vstack(cells)
    cv2.imwrite(f"{OUT}/sheet_tuck18_{tid}_{pid}.png", sheet)
    rows.append(f"| #{tid} + #{pid} | {len(avatars)} | {tot['off']} | {tot['tuck']} | {tot['unc']} |")
table = "\n".join(["| outfit | runs | wing px off | wing px tuck | figure px uncovered |", "|---|---|---|---|---|", *rows,
                   "", f"GATE (figure px uncovered 0): {fails} runs fail"])
open(f"{OUT}/table_tuck18.md", "w").write(table + "\n")
print(table)
