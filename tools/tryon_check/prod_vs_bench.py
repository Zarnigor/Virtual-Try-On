"""Gate for docs/09 #105: the production T-shirt layer (render_tryon with the settings flags, as the worker calls
it) against the approved benchmark call of mls.tshirt_layer, on the DB garments and avatars.

    docker compose exec -T backend python manage.py shell < tools/tryon_check/prod_vs_bench.py

Adapt garments ADAPT (default 28, 43, 40) x every avatar: diff px must be 0. keep_shape garments KEEP (default 44,
45) x every avatar: production with the flags on against production with every flag off: 0 px. The gender rule of
POST tryon/ is not applied here (the engine is called directly). Exit status 1 when a pair differs.
"""
import os
import sys
import time

import cv2

from apps.avatars.models import Avatar
from apps.garments.landmark_checks import engine_landmarks
from apps.garments.models import Garment
from apps.tryon_engine import mls, warp
from apps.tryon_engine.flags import render_flags

ADAPT = [int(v) for v in os.environ.get("ADAPT", "28,43,40").split(",")]
KEEP = [int(v) for v in os.environ.get("KEEP", "44,45").split(",")]
BENCH = dict(sleeve_variant="C", side_floor=True, side_floor_mode="mask", hem_mode="garment", sleeve_mode="tube",
             tube_arm="finished", armpit_mode="r14", cuff_mode="hem", tube_fringe="drop")  # docs/09 #105, #106
OFF = dict(mls_tube=False, mls_side_floor="off", mls_armpit="off", mls_hem="mls", mls_cuff="chord", mls_fringe="keep")
flags = render_flags("avatar")
print("flags:", {k: flags[k] for k in ("warp_engine", "mls_sleeve", "mls_tube", "mls_side_floor", "mls_armpit",
                                       "mls_hem", "mls_cuff", "mls_fringe", "neck_hole", "hem_rule")})
bad, times = 0, []
for gid in ADAPT + KEEP:
    g = Garment.objects.get(pk=gid)
    g_img = cv2.imread(g.image.path, cv2.IMREAD_UNCHANGED)
    glm = engine_landmarks(g.type, g.landmarks)
    for a in sorted(Avatar.objects.all(), key=lambda a: a.pk):
        base = cv2.imread(a.image.path, cv2.IMREAD_UNCHANGED)
        t0 = time.perf_counter()
        _, _, dbg = warp.render_tryon(base, a.landmarks, [("tshirt", g_img, glm)], 1200, 600,
                                      fit_modes={"tshirt": g.fit_mode}, **flags)
        ms = int((time.perf_counter() - t0) * 1000)
        if gid in ADAPT:
            mask = warp.figure_mask(cv2.resize(warp._bgra(base), (600, 1200)))
            hole = warp._neck_hole_kwargs(g_img, glm, flags["neck_hole"], {"quality_warnings": []})
            want, _ = mls.tshirt_layer(g_img, glm, a.landmarks, mask, "adapt", 1200, 600,
                                       (flags["hem_hip_fraction"], flags["hem_crotch_margin"]), **BENCH, **hole)
            times.append(ms)
        else:
            _, _, d2 = warp.render_tryon(base, a.landmarks, [("tshirt", g_img, glm)], 1200, 600,
                                         fit_modes={"tshirt": g.fit_mode}, **{**flags, **OFF})
            want = d2["tshirt_layer"]
        diff = int((dbg["tshirt_layer"] != want).any(2).sum())
        bad += diff > 0
        print(f"#{gid} {g.fit_mode} {a.sex[0]}-{a.build}: diff {diff} px, render {ms} ms, config {dbg.get('tshirt_config')}, "
              f"warnings {dbg['quality_warnings']}")
print(f"pairs that differ: {bad}; adapt render_tryon ms min / mean / max: {min(times)} / "
      f"{sum(times) // len(times)} / {max(times)}")
if bad:
    sys.exit(1)
