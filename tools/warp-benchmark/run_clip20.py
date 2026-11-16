"""Benchmark round 20: tube sleeves clipped on the arm/torso boundary (docs/06 "Tube clip, round 20").

    docker compose exec -T backend rm -rf /tmp/warp_benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/run_clip20.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

GARMENTS (default 28, 40, 43, 45, 47; rendered as adapt) x every avatar through warp.render_tryon with the settings
flags; columns armhole (mls_tube_clip="armhole", before) | arm. Metrics per render: flap px = T-shirt px (alpha >=
128) that differ between the two finals on the torso side of the arm/torso boundary below the armpit row (what the
tube drew over the chest); new holes = figure px covered by the T-shirt in "armhole" and not in "arm" (gate: 0);
changed elsewhere = final px that differ farther than 40 px from both armpit landmarks' columns band (gate: 0).
Writes out/table_clip20.md and out/sheet_clip20_<id>.png (per avatar: armhole | arm, upper body, clean).
"""
import os

import cv2
import numpy as np

from apps.avatars.models import Avatar
from apps.garments.landmark_checks import engine_landmarks
from apps.garments.models import Garment
from apps.tryon_engine import warp
from apps.tryon_engine.flags import render_flags

GARMENTS = [int(v) for v in os.environ.get("GARMENTS", "28,40,43,45,47").split(",")]
H, W = 1200, 600
OUT = "/tmp/warp_benchmark"
os.makedirs(OUT, exist_ok=True)
flags = {k: v for k, v in render_flags("avatar").items() if k != "mls_tube_clip"}
avatars = sorted(Avatar.objects.all(), key=lambda a: a.pk)
lines, fails = ["| garment | runs | tube px clipped | new holes | px changed outside the sleeve band |", "|---|---|---|---|---|"], 0
for gid in GARMENTS:
    g = Garment.objects.get(pk=gid)
    img, glm = cv2.imread(g.image.path, cv2.IMREAD_UNCHANGED), engine_landmarks(g.type, g.landmarks)
    cells, tot = [], [0, 0, 0]
    for av in avatars:
        base = cv2.imread(av.image.path, cv2.IMREAD_UNCHANGED)
        mask = warp.figure_mask(cv2.resize(warp._bgra(base), (W, H)))
        res = {}
        for clip in ("armhole", "arm"):
            res[clip] = warp.render_tryon(base, av.landmarks, [("tshirt", img, glm)], H, W,
                                          fit_modes={"tshirt": "adapt"}, mls_tube_clip=clip, **flags)
        (r0, _, d0), (r1, _, d1) = res["armhole"], res["arm"]
        c0, c1 = d0["final_layers"]["tshirt"][:, :, 3] >= 128, d1["final_layers"]["tshirt"][:, :, 3] >= 128
        holes = int((mask & c0 & ~c1).sum())
        y0, y1 = int(av.landmarks["shoulder"]["y"]) - 80, int(av.landmarks["hip"]["y"])
        band = np.zeros((H, W), bool)
        band[y0:y1] = True
        outside = int(((r0 != r1).any(2) & ~band).sum())
        clipped = sum(v.get("clip_arm_px", 0) for v in d1["mls"]["tube"].values() if isinstance(v, dict))
        tot[0] += clipped; tot[1] += holes; tot[2] += outside
        fails += (holes > 0) or (outside > 0)
        y = int(av.landmarks["shoulder"]["y"])
        cells.append(np.hstack([r0[y - 60:y + 300, 60:540], r1[y - 60:y + 300, 60:540]]))
    cv2.imwrite(f"{OUT}/sheet_clip20_{gid}.png", np.vstack([np.hstack(cells[:3]), np.hstack(cells[3:])]))
    lines.append(f"| #{gid} | {len(avatars)} | {tot[0]} | {tot[1]} | {tot[2]} |")
lines += ["", f"GATE (new holes 0, changed outside 0): {fails} runs fail"]
open(f"{OUT}/table_clip20.md", "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
