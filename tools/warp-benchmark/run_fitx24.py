"""Benchmark round 24: rows pants, before (off) vs A = fit_x (production, docs/09 #118); HANG=1 adds A+B = + hang_straight.

    git show HEAD:backend/apps/tryon_engine/warp.py > backend/apps/tryon_engine/warp_before.py   # off gate
    docker compose exec -T backend rm -rf /tmp/warp_benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/run_fitx24.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/
    rm backend/apps/tryon_engine/warp_before.py

GARMENTS (default 18, 48, 49, 51) x every avatar, production flags with pants_engine rows, pants alone and with the
T-shirt TSHIRT (default 43). Per variant, summed / max over the 6 avatars:
  off vs HEAD   px different from the engine before round 23 (gate: 0);
  new holes     figure px (waist + 6 .. ankle - 6, arms excluded; with the T-shirt: where no T-shirt px) covered
                by off and not by the variant;
  kinks         per outer leg edge (crotch + 10 .. ankle - 6) the sum of |second difference| of the edge x (blur 2);
  step          the largest summed outward step of an outer edge from the crotch to the mid-thigh, px (hip bulge);
  bend          per leg: the drawn leg's centre x per row (crotch + 20 .. ankle - 6) vs its straight line through
                the first and last row, max |deviation| px, max over legs (the leg bowing towards the knee);
  warnings      pants warnings.
Writes out/table_fitx24.md and out/sheet_fitx24_<id>.png (per avatar: off | A [| A+B]; pants alone).
"""
import importlib.util
import os

import cv2
import numpy as np

from apps.avatars.models import Avatar
from apps.garments.landmark_checks import engine_landmarks
from apps.garments.models import Garment
from apps.tryon_engine import warp
from apps.tryon_engine.flags import render_flags

GARMENTS = [int(v) for v in os.environ.get("GARMENTS", "18,48,49,51").split(",")]
TSHIRT = int(os.environ.get("TSHIRT", "43"))
H, W = 1200, 600
OUT = "/tmp/warp_benchmark"
os.makedirs(OUT, exist_ok=True)
base_flags = {k: v for k, v in render_flags("avatar").items()
              if k not in ("pants_engine", "pants_smooth", "pants_fit_x", "pants_hang")}
base_flags["pants_engine"] = "rows"
VARIANTS = {"off": {"pants_fit_x": False}, "A": {"pants_fit_x": True}}
if os.environ.get("HANG"):
    VARIANTS["A+B"] = {"pants_fit_x": True, "pants_hang": True}
avatars = sorted(Avatar.objects.all(), key=lambda a: a.pk)
BEFORE = "/app/apps/tryon_engine/warp_before.py"
before = None
if os.path.exists(BEFORE):
    spec = importlib.util.spec_from_file_location("apps.tryon_engine.warp_before", BEFORE)
    before = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(before)


def load(gid):
    g = Garment.objects.get(pk=gid)
    return (g.type, cv2.imread(g.image.path, cv2.IMREAD_UNCHANGED), engine_landmarks(g.type, g.landmarks))


def metrics(a, lm):
    ax = int(round(warp._crotch_x(lm)))
    y0, y1 = int(lm["crotch"]["y"]) + 10, int(min(lm["ankle"][k]["y"] for k in ("left_leg", "right_leg"))) - 6
    ym = int((lm["knee"]["y"] - lm["crotch"]["y"]) / 2)
    kinks, step, bend = 0.0, 0.0, 0.0
    for side in ("left", "right"):
        outer, centre = [], []
        for y in range(y0, y1):
            xs = np.where(a[y, :ax] if side == "left" else a[y, ax:])[0]
            if len(xs):
                lo, hi = (xs[0], xs[-1]) if side == "left" else (ax + xs[0], ax + xs[-1])
                outer.append(lo if side == "left" else hi)
                if y >= y0 + 10:
                    centre.append((y, (lo + hi) / 2))
        e = np.asarray(outer, np.float32)
        if len(e) > 4:
            gb = cv2.GaussianBlur(e.reshape(-1, 1), (1, 0), 2)[:, 0]
            kinks += float(np.abs(np.diff(gb, 2)).sum())
            top = e[:max(ym, 2)]
            out = -np.diff(top) if side == "left" else np.diff(top)
            step = max(step, float(out.clip(0).sum()))
        if len(centre) > 4:
            (ya, xa), (yb, xb) = centre[0], centre[-1]
            dev = [abs(x - (xa + (xb - xa) * (y - ya) / max(yb - ya, 1))) for y, x in centre]
            bend = max(bend, float(max(dev)))
    return kinks, step, bend


T = load(TSHIRT)
lines = ["| garment | worn | variant | off vs HEAD px | new holes | edge kinks (sum) | hip step px (max) | "
         "leg bend px (max) | pants warnings | sx / s or fx (mean) |", "|---|---|---|---|---|---|---|---|---|---|"]
for gid in GARMENTS:
    P = load(gid)
    cells = []
    for worn, gs in (("alone", [P]), (f"+T{TSHIRT}", [T, P])):
        tot = {v: {"diff": 0, "holes": 0, "kinks": 0.0, "step": 0.0, "bend": 0.0, "warn": 0, "k": []} for v in VARIANTS}
        for av in avatars:
            base = cv2.imread(av.image.path, cv2.IMREAD_UNCHANGED)
            lm = av.landmarks
            mask = warp.figure_mask(cv2.resize(warp._bgra(base), (W, H)))
            fm = {"tshirt": "adapt", "pants": "adapt"}
            ya = int(lm["waist"]["y"]) + 6
            yb = int(min(lm["ankle"][k]["y"] for k in ("left_leg", "right_leg"))) - 6
            cov, row = {}, []
            for v, kw in VARIANTS.items():
                out, warns, d = warp.render_tryon(base, lm, gs, H, W, fit_modes=fm, **base_flags, **kw)
                a = d["final_layers"]["pants"][:, :, 3] >= 128
                cov[v] = a
                t = tot[v]
                kinks, step, bend = metrics(a, lm)
                t["kinks"] += kinks; t["step"] = max(t["step"], step); t["bend"] = max(t["bend"], bend)
                t["warn"] += len([w for w in warns if w.startswith("pants")])
                if "pants_fit_x" in d:
                    t["k"].append(d["pants_fit_x"]["ratio"])
                if v == "off" and before is not None:
                    ref, _, _ = before.render_tryon(base, lm, gs, H, W, fit_modes=fm, **base_flags)
                    t["diff"] += int((np.abs(ref.astype(int) - out.astype(int)).max(2) > 0).sum())
                if v != "off":
                    nh = mask[ya:yb] & cov["off"][ya:yb] & ~a[ya:yb] & ~d["arm_mask"][ya:yb]
                    if worn != "alone":
                        tl = d["final_layers"].get("tshirt")
                        if tl is not None:
                            nh &= ~(tl[ya:yb, :, 3] >= 128)
                    t["holes"] += int(nh.sum())
                    if nh.any():
                        yy = np.where(nh.any(1))[0] + ya
                        print(f"  #{gid} {worn} {v} avatar {av.pk}: {int(nh.sum())} px, rows {yy.min()}..{yy.max()}")
                if worn == "alone":
                    y0 = int(lm["waist"]["y"]) - 40
                    cell = np.full((800, 400, 3), 255, np.uint8)
                    crop = out[y0:y0 + 800, 100:500]
                    cell[:crop.shape[0]] = crop
                    cv2.putText(cell, f"av{av.pk} {v}", (8, 24), 0, 0.7, (0, 0, 255), 2)
                    row.append(cell)
            cells += row
        for v in VARIANTS:
            t = tot[v]
            lines.append(f"| #{gid} | {worn} | {v} | {t['diff'] if v == 'off' and before else '-'} | "
                         f"{t['holes'] if v != 'off' else '-'} | {t['kinks']:.0f} | {t['step']:.0f} | {t['bend']:.1f} | "
                         f"{t['warn']} | {np.mean(t['k']):.2f} |" if t["k"] else
                         f"| #{gid} | {worn} | {v} | {t['diff'] if v == 'off' and before else '-'} | "
                         f"{t['holes'] if v != 'off' else '-'} | {t['kinks']:.0f} | {t['step']:.0f} | {t['bend']:.1f} | "
                         f"{t['warn']} | - |")
    cv2.imwrite(f"{OUT}/sheet_fitx24_{gid}.png", np.hstack(cells))
open(f"{OUT}/table_fitx24.md", "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
