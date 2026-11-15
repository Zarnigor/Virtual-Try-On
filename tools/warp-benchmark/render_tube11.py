"""Round 11: full try-on renders as the user would see them (docs/06 "Tube sleeve, round 11"). NOT production:
production code is unchanged; this script only wraps mls.tshirt_layer inside this process to add the benchmark
keywords (side_floor=True and sleeve_mode) and then calls the real warp.render_tryon with render_flags("avatar")
(TRYON_WARP=mls, sleeve C, neck hole from the garment's polygon, head / neck / hands overlays).

    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/render_tube11.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

Writes out/render_tube_<id>.png: rows = avatars, columns = reference | tube | tube_perp, full 600 x 1200 renders.
"""
import json
import os
from unittest import mock

import cv2
import numpy as np

from apps.tryon_engine import mls
from apps.tryon_engine.flags import render_flags
from apps.tryon_engine.warp import render_tryon

DATA, OUT = "/tmp/warp-benchmark/data/tube11", "/tmp/warp_benchmark"
os.makedirs(OUT, exist_ok=True)
VARIANTS = [("reference", {}), ("tube", {"sleeve_mode": "tube"}), ("tube_perp", {"sleeve_mode": "tube_perp"})]
_real = mls.tshirt_layer


def label(img, text):
    for col, th in (((255, 255, 255), 4), ((0, 0, 0), 1)):
        cv2.putText(img, text, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, th, cv2.LINE_AA)
    return img


avatars = []
for pk in sorted(int(f[:-5]) for f in os.listdir(f"{DATA}/avatars") if f.endswith(".json")):
    d = json.load(open(f"{DATA}/avatars/{pk}.json"))
    avatars.append((pk, f"{d['sex'][0]}-{d['build']}", d["landmarks"],
                    cv2.imread(f"{DATA}/avatars/{pk}.png", cv2.IMREAD_UNCHANGED)))
flags = {**render_flags("avatar"), "warp_engine": "mls"}
for gid in (28, 43, 40):
    g = cv2.imread(f"{DATA}/garments/{gid}.png", cv2.IMREAD_UNCHANGED)
    glm = json.load(open(f"{DATA}/garments/{gid}.json"))["landmarks"]  # engine_landmarks, incl. neck_hole
    rows = []
    for pk, who, blm, base in avatars:
        cells = []
        for name, extra in VARIANTS:
            def wrapped(*a, _extra=extra, **k):
                return _real(*a, **{**k, "side_floor": True, **_extra})
            with mock.patch("apps.tryon_engine.mls.tshirt_layer", side_effect=wrapped):
                rgb, warns, dbg = render_tryon(base, blm, [("tshirt", g, glm)], 1200, 600,
                                               fit_modes={"tshirt": "adapt"}, **flags)
            assert dbg["engine"] == "mls", (gid, pk, name, dbg.get("quality_warnings"))
            cells.append(label(rgb.copy(), f"{name}  #{gid} {who}"))
        rows.append(np.hstack(cells))
        print(f"#{gid} {who} done")
    cv2.imwrite(f"{OUT}/render_tube_{gid}.png", np.vstack(rows))
print("wrote render_tube_28/43/40.png")
