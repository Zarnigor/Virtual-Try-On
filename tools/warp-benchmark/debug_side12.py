"""Round 12 step 1 (docs/06 "Side coverage, round 12"): where does side_floor take the body edge from, which rows get
floor pairs, and what is left uncovered beside the torso? #28 / f-plus (avatar 6), adapt, the round 11 reference
config + tube (sleeve C + side_floor + collar_floor + hole + sleeve_mode="tube"). Read-only.

    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/debug_side12.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

Per row armpit -> hem (every 12 px), per side: the torso edge side_floor uses (`mls._torso_edges`: the mask run through
the body axis, or the landmark span when that run is > 1.3x the span = an arm touching), whether it fell back, the
garment layer's edge on that row (the covered run through the axis), and the uncovered figure px of the torso run on
that side. Writes out/debug_side12_28_f-plus.png (3x): mask (blue tint), garment outline (green), uncovered torso px
(magenta), floor pair targets (orange), main side pair targets (yellow), rows sampled (thin grey).
"""
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, "/tmp/warp-benchmark")
from apps.tryon_engine import mls as pm  # noqa: E402
from apps.tryon_engine import warp  # noqa: E402

DATA, OUT, GID, PK = "/tmp/warp-benchmark/data/tube11", "/tmp/warp_benchmark", 28, 6
os.makedirs(OUT, exist_ok=True)
g = cv2.imread(f"{DATA}/garments/{GID}.png", cv2.IMREAD_UNCHANGED)
glm = json.load(open(f"{DATA}/garments/{GID}.json"))["landmarks"]
d = json.load(open(f"{DATA}/avatars/{PK}.json"))
blm = d["landmarks"]
base = cv2.imread(f"{DATA}/avatars/{PK}.png", cv2.IMREAD_UNCHANGED)
mask = warp.figure_mask(base)
poly = (glm.get("neck_hole") or {}).get("polygon")
kw = dict(sleeve_variant="C", side_floor=True, sleeve_mode="tube",
          **({"neckline_variant": "hole", "neck_hole_polygon": poly} if poly else {}))
layer, info = pm.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, **kw)
cover = layer[:, :, 3] >= 128
pairs = info["pairs"]
axis = warp._crotch_x(blm)
a_y, hem_y = float(blm["armpit"]["y"]), float(pairs["hem_l"][1][1])
print(f"#{GID} {d['sex']} {d['build']}  axis x {axis:.1f}  armpit y {a_y}  hem target y {hem_y:.1f}  s {info['s']:.3f}")
print("side pairs (garment q -> body p):")
for k in sorted(pairs):
    if k.split("_")[0] in ("armpit", "chest", "waist", "hem") or k.startswith(("side_a", "side_b", "side_hip")):
        q, p, w = pairs[k]
        print(f"  {k:11} q ({q[0]:.0f}, {q[1]:.0f}) -> p ({p[0]:.1f}, {p[1]:.1f})")
print("rejected:", info["rejected"])
print("\n row | mask torso run (side_floor edge, src)       | garment edge L / R | uncovered torso px L / R")
tot = [0, 0]
for y in range(int(a_y) + 2, int(hem_y), 12):
    bl, br = warp.body_span(blm, y)
    run = pm._torso_run(mask, y, axis)
    el, er = pm._torso_edges(mask, blm, y, axis)
    src = "mask" if run and run[1] - run[0] <= 1.3 * (br - bl) else "landmarks (run > 1.3x span or none)"
    grun = next((q for q in warp._runs(cover[y]) if q[0] <= axis <= q[1]), None)
    gl, gr = (grun[0], grun[1] + 1) if grun else (None, None)
    unc = [0, 0]
    if run:
        xs = np.arange(run[0], run[1] + 1)
        miss = xs[~cover[y, xs]]
        unc = [int((miss < axis).sum()), int((miss >= axis).sum())]
        tot[0] += unc[0]
        tot[1] += unc[1]
    print(f" {y:4d} | run {run} -> floor edge {el:.0f}/{er:.0f} ({src}) | {gl} / {gr} | {unc[0]} / {unc[1]}")
# all rows (not only the sampled ones)
full = np.zeros_like(mask)
for y in range(int(a_y) + 2, int(hem_y) + 1):
    run = pm._torso_run(mask, y, axis)
    if run:
        full[y, run[0]:run[1] + 1] = True
unc_all = full & ~cover
left = unc_all & (np.arange(600)[None, :] < axis)
print(f"\nuncovered torso px armpit -> hem, every row: L {int(left.sum())} / R {int((unc_all & ~left).sum())}")
over = cv2.resize(warp._bgra(base), (600, 1200))[:, :, :3].copy()
over[mask] = (0.65 * over[mask] + 0.35 * np.array([255, 160, 60])).astype(np.uint8)
over[unc_all] = (0.3 * over[unc_all] + 0.7 * np.array([220, 40, 220])).astype(np.uint8)
cs, _ = cv2.findContours(cover.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
cv2.drawContours(over, cs, -1, (40, 200, 40), 1)
for y in range(int(a_y) + 2, int(hem_y), 12):
    cv2.line(over, (0, y), (599, y), (200, 200, 200), 1)
for k, (q, p, w) in pairs.items():
    if k.startswith(("side_a", "side_b", "side_hip")):
        cv2.circle(over, (int(round(p[0])), int(round(p[1]))), 3, (0, 140, 255), -1)
    elif k.split("_")[0] in ("armpit", "chest", "waist", "hem"):
        cv2.circle(over, (int(round(p[0])), int(round(p[1]))), 3, (0, 220, 255), -1)
y0, y1 = int(a_y) - 60, int(hem_y) + 40
img = cv2.resize(over[y0:y1], None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
for i, (txt, col) in enumerate((("mask (blue tint)", (255, 160, 60)), ("garment outline", (40, 200, 40)),
                                ("uncovered torso px", (220, 40, 220)), ("side_a / side_b / side_hip targets", (0, 140, 255)),
                                ("armpit / chest / waist / hem targets", (0, 220, 255)), ("sampled rows", (200, 200, 200)))):
    cv2.putText(img, txt, (12, 30 + 26 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, txt, (12, 30 + 26 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 1, cv2.LINE_AA)
ok = cv2.imwrite(f"{OUT}/debug_side12_28_f-plus.png", img)
print("wrote" if ok else "WRITE FAILED", "debug_side12_28_f-plus.png")
