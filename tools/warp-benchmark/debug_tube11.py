"""Round 11 debug (docs/06 "Tube sleeve, round 11"): where does each tube variant put the sleeve? #28 / m-average
(avatar 2), both sides, reference config (sleeve C + side_floor + collar_floor + hole). Read-only.

    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/debug_tube11.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

Per variant (tube, tube_perp) and side: body axis (start, angle, length) vs the reference cuff; the arm centre from
the straight fit through the separated arm rows (`mls._arm_at`, the mask's arm is merged with the torso above
y ~ 392 on this avatar, so a cross-line march is not used); garment axis (start, angle, length x s); per
cross-section garment outer / inner x s, arm outer / inner (x CUFF_ARM_EASE), output outer / inner.
Writes out/debug_tube_28_m-average_<variant>.png (4x): body mask (blue tint), reference MLS sleeve outline (green),
tube sleeve outline (red), cleared px not re-covered (magenta), body axis (yellow), _arm_at fit line (cyan),
sections (grey), t = 0 segment (orange).
"""
import json
import math
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, "/tmp/warp-benchmark")
from apps.tryon_engine import mls as pm  # noqa: E402
from apps.tryon_engine import warp  # noqa: E402

DATA, OUT, GID, PK = "/tmp/warp-benchmark/data/tube11", "/tmp/warp_benchmark", 28, 2
os.makedirs(OUT, exist_ok=True)
g = cv2.imread(f"{DATA}/garments/{GID}.png", cv2.IMREAD_UNCHANGED)
glm = json.load(open(f"{DATA}/garments/{GID}.json"))["landmarks"]
d = json.load(open(f"{DATA}/avatars/{PK}.json"))
blm = d["landmarks"]
base = cv2.imread(f"{DATA}/avatars/{PK}.png", cv2.IMREAD_UNCHANGED)
mask = warp.figure_mask(base)
arms = warp.find_arms(mask, blm)
poly = (glm.get("neck_hole") or {}).get("polygon")
kw = dict(sleeve_variant="C", side_floor=True, debug_map=True,
          **({"neckline_variant": "hole", "neck_hole_polygon": poly} if poly else {}))
ref, ri = pm.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, **kw)
H, W = mask.shape
Y, X = np.mgrid[0:H, 0:W]
P = np.stack([X, Y], -1).astype(np.float32)
ang = lambda v: round(math.degrees(math.atan2(v[1], v[0])), 1)  # noqa: E731
ref_cov = ref[:, :, 3] >= 128
for mode in ("tube", "tube_perp"):
    tub, ti = pm.tshirt_layer(g, glm, blm, mask, "adapt", 1200, 600, sleeve_mode=mode, **kw)
    s = ti["s"]
    tub_cov = tub[:, :, 3] >= 128
    over = cv2.resize(warp._bgra(base), (W, H))[:, :, :3].copy()
    over[mask] = (0.6 * over[mask] + 0.4 * np.array([255, 160, 60])).astype(np.uint8)
    print(f"\n===== {mode}  #{GID} {d['sex']} {d['build']}  s = {s:.4f}")
    for side, sx in (("left", "_l"), ("right", "_r")):
        rep = ti["tube"][side]
        O0, Mb1 = (np.array(p, float) for p in rep["axis_body"])
        G0, Mg1 = (np.array(p, float) for p in rep["axis_garment"])
        B0, B1 = (np.array(p, float) for p in rep["armhole_body"])
        cm = (np.array(ri["pairs"]["cuff_out" + sx][1]) + np.array(ri["pairs"]["cuff_in" + sx][1])) / 2
        fit = pm._arm_at(arms, side, Mb1[1])
        print(f"--- {side}: body axis start {O0.round(1).tolist()} angle {ang(Mb1 - O0)} len {np.linalg.norm(Mb1 - O0):.1f} "
              f"end {Mb1.round(1).tolist()} (reference cuff mid {cm.round(1).tolist()}); _arm_at at the cuff row: "
              f"x {fit[0]:.1f} -> dx {Mb1[0] - fit[0]:+.1f}")
        print(f"    garment axis start {G0.round(1).tolist()} angle {ang(Mg1 - G0)} len {np.linalg.norm(Mg1 - G0):.1f} "
              f"x s = {np.linalg.norm(Mg1 - G0) * s:.1f} (output {np.linalg.norm(Mb1 - O0):.1f}); axis_dev_max "
              f"{rep['axis_dev_max']}; cleared {rep['cleared_px']}")
        print("    t    | garment o/i x s | arm o/i (x1.1)        | output o/i")
        for w in rep["widths"]:
            ao, ai = w["arm_out_in"]
            arm = "-" if ao is None else f"{ao:.1f}/{ai:.1f} ({ao * 1.1:.1f}/{ai * 1.1:.1f})"
            print(f"    {w['t']:.2f} | {w['garment_x_s'][0]:.1f}/{w['garment_x_s'][1]:.1f} | {arm:21} | "
                  f"{w['out_in'][0]:.1f}/{w['out_in'][1]:.1f}")
        for a_, b_ in rep["sections"]:
            cv2.line(over, tuple(np.round(a_).astype(int)), tuple(np.round(b_).astype(int)), (160, 160, 160), 1)
        cv2.line(over, tuple(np.round(rep["t0_body"][0]).astype(int)), tuple(np.round(rep["t0_body"][1]).astype(int)),
                 (0, 140, 255), 1)
        cv2.line(over, tuple(np.round(O0).astype(int)), tuple(np.round(Mb1).astype(int)), (0, 220, 255), 1)
        f0, f1 = pm._arm_at(arms, side, B0[1]), pm._arm_at(arms, side, Mb1[1] + 60)
        cv2.line(over, (int(f0[0]), int(B0[1])), (int(f1[0]), int(Mb1[1] + 60)), (255, 255, 0), 1)
        ba = np.array([-(B1 - B0)[1], (B1 - B0)[0]])
        if (Mb1 - B0) @ ba < 0:
            ba = -ba
        zone = ((P - B0) @ ba) > 0
        cleared = zone & ref_cov & ~tub_cov
        print(f"    outward zone: ref sleeve px {int((zone & ref_cov).sum())}, tube px {int((zone & tub_cov).sum())}, "
              f"cleared not re-covered {int(cleared.sum())} (over the arm {int((cleared & mask).sum())}), "
              f"over background tube {int((zone & tub_cov & ~mask).sum())} vs ref {int((zone & ref_cov & ~mask).sum())}")
        over[cleared] = (0.4 * over[cleared] + 0.6 * np.array([220, 40, 220])).astype(np.uint8)
        for cov, col in ((zone & ref_cov, (40, 200, 40)), (zone & tub_cov, (40, 40, 230))):
            cs, _ = cv2.findContours(cov.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            cv2.drawContours(over, cs, -1, col, 1)
    y0, y1 = int(blm["neck"]["y"]) - 20, int(blm["armpit"]["y"]) + 120
    img = cv2.resize(over[y0:y1], None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
    for i, (txt, col) in enumerate(((f"{mode}", (0, 0, 0)), ("body mask (blue tint)", (255, 160, 60)),
                                    ("reference MLS sleeve outline", (40, 200, 40)), ("tube sleeve outline", (40, 40, 230)),
                                    ("cleared, not re-covered", (220, 40, 220)), ("body arm axis", (0, 220, 255)),
                                    ("_arm_at fit line", (255, 255, 0)), ("cross-sections", (160, 160, 160)),
                                    ("t = 0 segment", (0, 140, 255)))):
        cv2.putText(img, txt, (12, 30 + 26 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, txt, (12, 30 + 26 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 1, cv2.LINE_AA)
    ok = cv2.imwrite(f"{OUT}/debug_tube_28_m-average_{mode}.png", img)
    print("wrote" if ok else "WRITE FAILED", f"debug_tube_28_m-average_{mode}.png")
