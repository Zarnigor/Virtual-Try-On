"""Belly / waist check for the T-shirt drape over pants (docs/09 #119, setting TRYON_DRAPE_BODY_MARGIN).

    docker compose exec -T backend rm -rf /tmp/belly_overlay
    docker compose exec -T backend python manage.py shell < tools/tryon_check/belly_overlay.py
    docker compose cp backend:/tmp/belly_overlay/. tools/tryon_check/out/belly/

Read-only. Each outfit (OUTFITS="tshirt+pants,...") on every avatar is rendered with the settings flags twice:
"before" (drape_body_margin=None) and "after" (the setting's margin, MARGIN=<px> overrides it). Rows: body waist ->
the T-shirt's bottom row. Metrics per avatar and variant:
  over   = T-shirt px past the figure silhouette (both sides, summed over the rows) / the largest per row
  wing   = visible pants px left / right of the T-shirt's torso run (the "pants wing")
  step   = largest x jump of the T-shirt side between two neighbouring rows (stair-steps)
  unc    = figure px covered by a garment in "before" and by none in "after" (gate 0)
  holes  = px inside the T-shirt's outer outline that are transparent in "after" but solid in "before" (gate 0)
Images: out/belly_<tshirt>_<pants>_<avatar>.png = before | after, the result with the figure edge (green), the
figure edge + margin (blue), the T-shirt side (red), the pants wing px (magenta). Table: out/table_belly.md.
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
           os.environ.get("OUTFITS", "28+51,43+48,40+49,47+51,45+51").split(",")]
H, W = 1200, 600
OUT = "/tmp/belly_overlay"
os.makedirs(OUT, exist_ok=True)
flags = render_flags("avatar")
MARGIN = float(os.environ["MARGIN"]) if os.environ.get("MARGIN") else flags["drape_body_margin"]
flags = {k: v for k, v in flags.items() if k != "drape_body_margin"}


def load(path):
    return cv2.imread(path, cv2.IMREAD_UNCHANGED)


def run_at(solid, y, ax):
    return next((r for r in warp._runs(solid[y]) if r[0] <= ax <= r[1]), None)


def metrics(dbg, mask, lm):
    shirt = dbg["final_layers"]["tshirt"][:, :, 3] >= 128
    pants = dbg["final_layers"]["pants"][:, :, 3] >= 128
    ax = int(round(warp._crotch_x(lm)))
    y0, y1 = int(round(float(lm["waist"]["y"]))), int(np.where(shirt.any(axis=1))[0][-1])
    over = over_max = wing = 0
    wing_px = np.zeros_like(shirt)
    edges = {}
    for y in range(y0, y1 + 1):
        s, b = run_at(shirt, y, ax), run_at(mask, y, ax)
        if s is None:
            continue
        edges[y] = s
        if b is not None:
            o = max(b[0] - s[0], 0) + max(s[1] - b[1], 0)
            over += o
            over_max = max(over_max, o)
        wing_px[y, :s[0]] = pants[y, :s[0]]
        wing_px[y, s[1] + 1:] = pants[y, s[1] + 1:]
    wing = int(wing_px.sum())
    ys = sorted(edges)
    step = max((max(abs(edges[a][0] - edges[c][0]), abs(edges[a][1] - edges[c][1]))
                for a, c in zip(ys, ys[1:]) if c == a + 1), default=0)
    return {"over": over, "over_max": over_max, "wing": wing, "step": step, "edges": edges, "wing_px": wing_px,
            "shirt": shirt, "cover": shirt | pants}


def outline_fill(solid):
    cs, _ = cv2.findContours(solid.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    out = np.zeros(solid.shape, np.uint8)
    cv2.drawContours(out, cs, -1, 1, -1)
    return out.astype(bool)


def overlay(img, m, mask, lm, margin):
    o = img.copy()
    ax = int(round(warp._crotch_x(lm)))
    for y, (l, r) in m["edges"].items():
        b = run_at(mask, y, ax)
        if b is not None:
            o[y, b[0]] = o[y, b[1]] = (0, 170, 0)
            if margin is not None:
                for x in (int(round(b[0] - margin)), int(round(b[1] + margin))):
                    if 0 <= x < W:
                        o[y, x] = (255, 90, 0)
        o[y, l] = o[y, r] = (0, 0, 230)
    o[m["wing_px"]] = (200, 0, 200)
    return o


rows, gate_fail = [], 0
avatars = list(Avatar.objects.order_by("id"))
for tid, pid in OUTFITS:
    t, p = Garment.objects.get(id=tid), Garment.objects.get(id=pid)
    garments = [(g.type, load(g.image.path), engine_landmarks(g.type, g.landmarks)) for g in (t, p)]
    fit = {"tshirt": t.fit_mode, "pants": p.fit_mode}
    for av in avatars:
        base = load(av.image.path)
        mask = warp.figure_mask(cv2.resize(warp._bgra(base), (W, H)))
        res = {}
        for name, margin in (("before", None), ("after", MARGIN)):
            img, _, dbg = warp.render_tryon(base, av.landmarks, garments, H, W, fit_modes=fit,
                                            drape_body_margin=margin, **flags)
            res[name] = (img, metrics(dbg, mask, av.landmarks), margin, dbg.get("pants_drape"))
        mb, ma = res["before"][1], res["after"][1]
        unc = int((mb["cover"] & ~ma["cover"] & mask).sum())
        holes = int((outline_fill(ma["shirt"]) & ~ma["shirt"] & mb["shirt"]).sum())
        gate_fail += unc > 0 or holes > 0
        tag = f"{av.sex[0]}-{av.build}"
        cells = []
        for name, (img, m, margin, _) in res.items():
            c = overlay(img, m, mask, av.landmarks, margin)
            cv2.putText(c, f"#{tid}+#{pid} {tag} {name}", (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1,
                        cv2.LINE_AA)
            cells.append(c)
        cv2.imwrite(f"{OUT}/belly_{tid}_{pid}_{tag}.png", np.hstack(cells))
        rows.append(f"| #{tid}({t.fit_mode}) + #{pid} | {tag} | {mb['over']} / {mb['over_max']} | "
                    f"{ma['over']} / {ma['over_max']} | {mb['wing']} | {ma['wing']} | {mb['step']} | {ma['step']} | "
                    f"{res['before'][3]:.2f} / {res['after'][3]:.2f} | {unc} | {holes} |")
table = "\n".join([
    f"margin = {MARGIN} px",
    "",
    "| outfit | avatar | over before (sum / max) | over after | wing before | wing after | step before | step after "
    "| drape k before / after | figure px uncovered | new holes |",
    "|---|---|---|---|---|---|---|---|---|---|---|", *rows,
    "", f"GATE (figure px uncovered 0, new holes 0): {gate_fail} runs fail"])
open(f"{OUT}/table_belly.md", "w").write(table + "\n")
print(table)
