"""Benchmark round 21: pants engine "rows" (before) vs "fit" (docs/06 "Pants fit, round 21").

    docker compose exec -T backend rm -rf /tmp/warp_benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/run_pants21.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

GARMENTS (default 18, 48, 49, 51) x every avatar, pants alone, through warp.render_tryon with the settings flags.
Per render and engine: body px uncovered = figure px between the waist row + 6 and the ankle row - 6 (hands /
forearms excluded: the arm overlay) that the pants layer (alpha >= 128) does not cover; new holes = such px
covered by "rows" and not by "fit"; width error = mean over the
leg rows from the knee to the hem of |drawn leg width / (garment leg width x scale) - 1| (how far the lower leg is
from the garment's own outline); thigh ratio = drawn width / body leg width at the mid-thigh row, mean of both legs;
edge steps = sum over both outer leg edges (crotch..hem) of |second difference| of the edge x per row (kinks).
Writes out/table_pants21.md and out/sheet_pants21_<id>.png (the garment, then per avatar: rows | fit; clean).
"""
import os

import cv2
import numpy as np

from apps.avatars.models import Avatar
from apps.garments.landmark_checks import engine_landmarks
from apps.garments.models import Garment
from apps.tryon_engine import warp
from apps.tryon_engine.flags import render_flags

GARMENTS = [int(v) for v in os.environ.get("GARMENTS", "18,48,49,51").split(",")]
H, W = 1200, 600
OUT = "/tmp/warp_benchmark"
os.makedirs(OUT, exist_ok=True)
flags = {k: v for k, v in render_flags("avatar").items() if k != "pants_engine"}
avatars = sorted(Avatar.objects.all(), key=lambda a: a.pk)


def measure(d, lm, mask, arm_mask):
    a = d["final_layers"]["pants"][:, :, 3] >= 128
    y0, y1 = int(lm["waist"]["y"]) + 6, int(min(lm["ankle"][k]["y"] for k in ("left_leg", "right_leg"))) - 6
    unc = int((mask[y0:y1] & ~a[y0:y1] & ~arm_mask[y0:y1]).sum())
    ax = int(round(warp._crotch_x(lm)))
    steps, thigh = 0.0, []
    ym = int((lm["crotch"]["y"] + lm["knee"]["y"]) / 2)
    for side in ("left", "right"):
        edge = []
        for y in range(int(lm["crotch"]["y"]) + 10, y1):
            xs = np.where(a[y, :ax] if side == "left" else a[y, ax:])[0]
            if len(xs):
                edge.append(xs[0] if side == "left" else xs[-1])
        if len(edge) > 4:
            e = cv2.GaussianBlur(np.asarray(edge, np.float32).reshape(-1, 1), (1, 0), 2)[:, 0]
            steps += float(np.abs(np.diff(e, 2)).sum())
        run = warp._leg_run(mask, ym, side, ax, lm["knee"][f"{side}_leg"]["left_x"])
        got = warp._leg_run(a, ym, side, ax, lm["knee"][f"{side}_leg"]["left_x"])
        if run and got:
            thigh.append((got[1] - got[0]) / max(run[1] - run[0], 1))
    return unc, round(steps, 1), round(float(np.mean(thigh)), 2) if thigh else None


lines = ["| garment | engine | runs | body px uncovered | new holes vs rows | outer edge kinks (sum) | "
         "thigh width / body, mean | warnings |", "|---|---|---|---|---|---|---|---|"]
for gid in GARMENTS:
    g = Garment.objects.get(pk=gid)
    img, glm = cv2.imread(g.image.path, cv2.IMREAD_UNCHANGED), engine_landmarks(g.type, g.landmarks)
    al = img[:, :, 3:4] / 255.0
    flat = (img[:, :, :3] * al + 255 * (1 - al)).astype(np.uint8)
    cells = [cv2.resize(flat, (int(flat.shape[1] * 800 / flat.shape[0]), 800))]
    tot = {e: [0, 0.0, [], 0] for e in ("rows", "fit")}
    new_holes = 0
    for av in avatars:
        base = cv2.imread(av.image.path, cv2.IMREAD_UNCHANGED)
        mask = warp.figure_mask(cv2.resize(warp._bgra(base), (W, H)))
        y0 = int(av.landmarks["waist"]["y"]) - 40
        cov = {}
        for e in ("rows", "fit"):
            out, warns, d = warp.render_tryon(base, av.landmarks, [("pants", img, glm)], H, W, pants_engine=e, **flags)
            unc, steps, thigh = measure(d, av.landmarks, mask, d["arm_mask"])
            t = tot[e]
            cov[e] = d["final_layers"]["pants"][:, :, 3] >= 128
            if e == "fit":
                ya, yb = int(av.landmarks["waist"]["y"]) + 6, int(min(av.landmarks["ankle"][k]["y"] for k in ("left_leg", "right_leg"))) - 6
                nh = mask[ya:yb] & cov["rows"][ya:yb] & ~cov["fit"][ya:yb] & ~d["arm_mask"][ya:yb]
                new_holes += int(nh.sum())
                if nh.any():
                    yy = np.where(nh.any(1))[0] + ya
                    print(f"  #{gid} {av.sex[0]}-{av.build}: {int(nh.sum())} px, rows {yy.min()}..{yy.max()} "
                          f"(crotch {int(av.landmarks['crotch']['y'])}, knee {int(av.landmarks['knee']['y'])}, ankle {yb + 6})")
            t[0] += unc; t[1] += steps; t[2].append(thigh); t[3] += len([w for w in warns if w.startswith("pants")])
            cell = np.full((800, 400, 3), 255, np.uint8)
            crop = out[y0:y0 + 800, 100:500]
            cell[:crop.shape[0]] = crop
            cells.append(cell)
    cv2.imwrite(f"{OUT}/sheet_pants21_{gid}.png", np.hstack(cells))
    for e in ("rows", "fit"):
        t = tot[e]
        lines.append(f"| #{gid} | {e} | {len(avatars)} | {t[0]} | {new_holes if e == 'fit' else '-'} | {t[1]:.0f} | "
                     f"{np.mean([v for v in t[2] if v]):.2f} | {t[3]} |")
open(f"{OUT}/table_pants21.md", "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
