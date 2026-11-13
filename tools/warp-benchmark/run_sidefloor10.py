"""MLS benchmark round 10: side coverage floor, off vs on, adapt k 1.0 and keep_shape preset A (docs/06, NOT production).

    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/run_sidefloor10.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

Production apps.tryon_engine.mls.tshirt_layer(..., mode, side_floor=off|on, debug_map=True); #28, #43, #40 (fitted)
and #44, #45 (oversized) x all avatars. Metrics: side_strip_px (mls_fitted; armpit row -> the run's hem target row), uncovered / excess / hem curve
(coverage_metrics), fold (mls.metrics), print distortion (#44 only, mls_landmarks), runtime; per off/on pair the
garment alpha px that changed. Writes out/results10.json, out/table10.md (every run), out/sheet_sidefloor_<id>.png
(rows = avatars; adapt off | adapt on | keep_shape off | keep_shape on; armpit-to-hem crop at 0.6x, grey dots = the
floor) and out/crop_sidefloor_worst_<mode>.png (2x, off | on for the run with the most side-strip px with the floor ON).
"""
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, "/tmp/warp-benchmark")
import mls as bm  # noqa: E402
import mls_fitted as mf  # noqa: E402
import mls_landmarks as ml  # noqa: E402

from apps.avatars.models import Avatar  # noqa: E402
from apps.garments.landmark_checks import engine_landmarks  # noqa: E402
from apps.garments.models import Garment  # noqa: E402
from apps.tryon_engine import mls as pm  # noqa: E402
from apps.tryon_engine import warp  # noqa: E402

GARMENTS = [28, 43, 40, 44, 45]
OVERSIZED = {44, 45}
MODES = ["adapt", "keep_shape"]
H, W = 1200, 600
OUT = "/tmp/warp_benchmark"
os.makedirs(OUT, exist_ok=True)


def label(img, text, scale=0.5, y=18):
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(img, text, (6, y), cv2.FONT_HERSHEY_SIMPLEX, scale, col, th, cv2.LINE_AA)
    return img


def crop_rows(blm):
    y0 = max(int(blm["armpit"]["y"]) - 90, 0)
    return y0, min(int(pm.body_hem_y(blm)) + 60, H)


def floor_dots(rgb, mask, blm):
    axis = warp._crotch_x(blm)
    for y in range(int(blm["armpit"]["y"]), int(pm.body_hem_y(blm)) + 1, 8):
        for x in pm._torso_floor(mask, blm, y, axis):
            cv2.circle(rgb, (int(round(x)), y), 1, (110, 110, 110), -1)
    return rgb


avatars = list(Avatar.objects.order_by("pk"))
bases, masks = {}, {}
for av in avatars:
    bases[av.pk] = cv2.resize(warp._bgra(cv2.imread(av.image.path, cv2.IMREAD_UNCHANGED)), (W, H))
    masks[av.pk] = warp.figure_mask(bases[av.pk])

results, worst = [], {}
for gid in GARMENTS:
    g = Garment.objects.get(pk=gid)
    gimg = cv2.imread(g.image.path, cv2.IMREAD_UNCHANGED)
    glm = engine_landmarks(g.type, g.landmarks)
    pbox = ml.print_bbox(gimg) if gid == 44 else None
    rows = []
    for av in avatars:
        blm, mask = av.landmarks, masks[av.pk]
        y0, y1 = crop_rows(blm)
        cells = []
        for mode in MODES:
            pair_imgs, alphas = {}, {}
            for on in (False, True):
                layer, info = pm.tshirt_layer(gimg, glm, blm, mask, mode, H, W, side_floor=on, debug_map=True)
                strip = mf.side_strip_px(layer, mask, blm, info["pairs"])
                cov = mf.coverage_metrics(layer, mask, info, blm)
                rec = {"garment": gid, "oversized": gid in OVERSIZED, "avatar": av.pk, "who": f"{av.sex[0]}-{av.build}",
                       "mode": mode, "side_floor": on, "side_strip_px": strip["total"],
                       "uncovered_px": cov["uncovered_px"], "excess_px": cov["excess_px"],
                       "fold": round(bm.metrics(layer, info, blm)["fold"], 5),
                       "print_distortion": ml.print_distortion(layer, info, pbox) if pbox else None,
                       "hem_curve_px": cov["hem_curve_px"], "runtime_s": round(info["runtime"], 3),
                       "side_pairs": sorted(k for k in info["pairs"] if k.startswith("side_")),
                       "rejected": info["rejected"]}
                alphas[on] = layer[:, :, 3] >= 128
                if on:
                    rec["changed_px"] = int((alphas[True] != alphas[False]).sum())
                    rec["changed_pct"] = round(100 * rec["changed_px"] / max(int(alphas[False].sum()), 1), 2)
                results.append(rec)
                print(json.dumps(rec, default=str))
                rgb = floor_dots(bm.composite(bases[av.pk], layer, blm, info), mask, blm)
                pair_imgs[on] = rgb[y0:y1].copy()
                small = cv2.resize(pair_imgs[on], None, fx=0.6, fy=0.6, interpolation=cv2.INTER_AREA)
                cells.append(label(small, f"{mode} {'on' if on else 'off'} #{gid} {rec['who']} strip {strip['total']}",
                                   0.4, 14))
                if on and (mode not in worst or strip["total"] > worst[mode][0]):
                    worst[mode] = (strip["total"], gid, rec["who"], None)
            if worst[mode][1] == gid and worst[mode][2] == f"{av.sex[0]}-{av.build}":
                worst[mode] = worst[mode][:3] + (np.hstack([pair_imgs[False], pair_imgs[True]]),)
        hmax = max(c.shape[0] for c in cells)
        rows.append(np.hstack([cv2.copyMakeBorder(c, 0, hmax - c.shape[0], 0, 0, cv2.BORDER_CONSTANT,
                                                  value=(255, 255, 255)) for c in cells]))
    wmax = max(r.shape[1] for r in rows)
    cv2.imwrite(f"{OUT}/sheet_sidefloor_{gid}.png", np.vstack(rows))
for mode, (n, gid, who, img) in worst.items():
    big = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    label(big, f"worst {mode} with floor ON: {n} side-strip px, #{gid} {who}   (left: off | right: on)", 0.9, 30)
    cv2.imwrite(f"{OUT}/crop_sidefloor_worst_{mode}.png", big)

with open(f"{OUT}/results10.json", "w") as fh:
    json.dump(results, fh, default=str, indent=1)

lines = ["## Summary (sum over the 6 avatars; fold = max; print distortion #44 = max; runtime = max)", "",
         "| garment | mode | floor | side strip px | uncovered px | excess px | fold | print dist | hem curve px (max) | "
         "changed px (on vs off) | runtime s |", "|---|---|---|---|---|---|---|---|---|---|---|"]
for gid in GARMENTS:
    for mode in MODES:
        for on in (False, True):
            rs = [r for r in results if r["garment"] == gid and r["mode"] == mode and r["side_floor"] == on]
            pd = [r["print_distortion"] for r in rs if r["print_distortion"] is not None]
            hc = [r["hem_curve_px"] for r in rs if r["hem_curve_px"] is not None]
            lines.append(
                f"| #{gid}{' (oversized)' if gid in OVERSIZED else ''} | {mode} | {'on' if on else 'off'} | "
                f"{sum(r['side_strip_px'] for r in rs)} | {sum(r['uncovered_px'] for r in rs)} | "
                f"{sum(r['excess_px'] for r in rs)} | {max(r['fold'] for r in rs):.4f} | "
                f"{max(pd) if pd else '-'} | {max(hc) if hc else '-'} | "
                f"{(str(sum(r['changed_px'] for r in rs)) + ' (max ' + str(max(r['changed_pct'] for r in rs)) + ' %)') if on else '-'} | "
                f"{max(r['runtime_s'] for r in rs):.2f} |")
lines += ["", "## Every run", "",
          "| garment | avatar | mode | floor | side strip | uncovered | excess | fold | print dist | hem curve | "
          "changed px (%) | runtime s | side pairs | dropped side pairs |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
for r in results:
    drop = [x for x in r["rejected"] if x.startswith("side_")]
    lines.append(f"| #{r['garment']} | {r['who']} | {r['mode']} | {'on' if r['side_floor'] else 'off'} | "
                 f"{r['side_strip_px']} | {r['uncovered_px']} | {r['excess_px']} | {r['fold']:.4f} | "
                 f"{r['print_distortion'] if r['print_distortion'] is not None else '-'} | {r['hem_curve_px']} | "
                 f"{(str(r['changed_px']) + ' (' + str(r['changed_pct']) + ')') if r['side_floor'] else '-'} | "
                 f"{r['runtime_s']} | {len(r['side_pairs'])} | {', '.join(drop) or '-'} |")
with open(f"{OUT}/table10.md", "w") as fh:
    fh.write("\n".join(lines) + "\n")
print("\n".join(lines[:24]))
print("done", len(results))
