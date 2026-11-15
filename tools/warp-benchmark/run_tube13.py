"""MLS benchmark round 13: finished tube sleeves (docs/06 "Tube sleeve finished, round 13", NOT production).

    docker compose exec -T backend rm -rf /tmp/warp-benchmark /tmp/warp_benchmark
    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T -e EXPORT_ROOT=/tmp/warp-benchmark/data/side12 backend python manage.py shell \
        < tools/warp-benchmark/export_sleeve8b.py          # the round 8b exporter, current DB -> data/side12/
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/run_tube13.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

#28, #43, #40 x 6 avatars, adapt. Base (every column): sleeve C + side_floor_mode "mask" + hem_mode "garment" +
collar_floor + the neck_hole polygon. Columns: no tube | tube finished (sleeve_mode "tube", tube_arm "finished").
Round 13b: columns no tube | tube a+b fixed (the cut edge kept out of remove_halo, enclosed sleeve-zone holes filled,
"filled_px" per run); WITH_A=1 adds the round 13 fallback column tube_a = tube_arm "finished_a" (rule (a) only).
new holes (GATE) = figure px covered (alpha >= 128) in "no tube" and not in the tube column, ALL px (enclosed or
open), except the arm px below the tube cuff line (engine zone "below_cuff_zone": beyond the cuff segment in the axis
direction, cuff-width strip x TUBE_ARM_MAX, outward of the armhole line), which are reported as arm_below_cuff_px.
holes (enclosed) = figure px not covered inside the layer's filled outer contour, in the sleeve / underarm zone
(tests_mls.tube_zone), per column. arm_band_skin_px, cuff_wave_px (mls_fitted), balloon_px (garment px in the sleeve
zone beyond the figure + 3 px), runtime. Exit status 1 when the tube column has new holes > 0 in any run.
Writes out/table_tube13.md, out/results_tube13.json, out/sheet_tube13_<id>.png (per avatar: no tube | tube a+b
[| tube a], whole T-shirt 2x, then 3x crops underarm L / cuff L / underarm R / cuff R per column; clean, short labels).
"""
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, "/tmp/warp-benchmark")
import mls as bm  # noqa: E402
import mls_fitted as mf  # noqa: E402

from apps.tryon_engine import mls as pm  # noqa: E402
from apps.tryon_engine import warp  # noqa: E402

GARMENTS = [28, 43, 40]
BASE = {"sleeve_variant": "C", "side_floor": True, "side_floor_mode": "mask", "hem_mode": "garment"}
VARIANTS = [("no tube", {}), ("tube", {"sleeve_mode": "tube", "tube_arm": "finished"})]
if os.environ.get("WITH_A", "0") == "1":  # round 13 fallback column (rule a only)
    VARIANTS.append(("tube_a", {"sleeve_mode": "tube", "tube_arm": "finished_a"}))
H, W = 1200, 600
OUT = "/tmp/warp_benchmark"
DATA = "/tmp/warp-benchmark/data/side12"
BALLOON_EASE = 3
CROP, ZOOM = 40, 3
LABELS = {"no tube": "no tube", "tube": "tube a+b fixed", "tube_a": "tube a only (fallback)"}
os.makedirs(OUT, exist_ok=True)
Y, X = np.mgrid[0:H, 0:W]
PX = np.stack([X, Y], -1).astype(np.float32)


def label(img, text, y=18, scale=0.5):
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(img, text, (6, y), cv2.FONT_HERSHEY_SIMPLEX, scale, col, th, cv2.LINE_AA)
    return img


def hstack(cells):
    h = max(c.shape[0] for c in cells)
    return np.hstack([np.pad(c, ((0, h - c.shape[0]), (0, 0), (0, 0)), constant_values=255) for c in cells])


def vstack(rows):
    w = max(r.shape[1] for r in rows)
    return np.vstack([np.pad(r, ((0, 0), (0, w - r.shape[1]), (0, 0)), constant_values=255) for r in rows])


def zones_of(rp, blm, around=15):
    """Per side: the round 11 sleeve zone (outward of the armhole line above the lower cuff target + 10) and that zone
    + 15 px around the armhole segment (= tests_mls.tube_zone, one side)."""
    out = {}
    for side, sx in (("left", "_l"), ("right", "_r")):
        B0 = np.array(rp["shoulder" + sx][1], float)
        B1 = np.array(rp["armpit" + sx][1], float) if "armpit" + sx in rp else \
            np.array([float(blm["armpit"][f"{side}_x"]), float(blm["armpit"]["y"])])
        cm = (np.array(rp["cuff_out" + sx][1]) + np.array(rp["cuff_in" + sx][1])) / 2
        ba = np.array([-(B1 - B0)[1], (B1 - B0)[0]])
        if (cm - B0) @ ba < 0:
            ba = -ba
        ylow = max(rp["cuff_out" + sx][1][1], rp["cuff_in" + sx][1][1]) + 10
        sl = (((PX - B0) @ ba) > 0) & (Y <= ylow)
        seg = B1 - B0
        t = np.clip(((PX - B0) @ seg) / float(seg @ seg), 0, 1)
        near = np.linalg.norm(PX - (B0 + t[..., None] * seg), axis=-1) <= around
        out[side] = (sl, sl | near, B1, cm)
    return out


def enclosed(cover):
    """Px not covered and not reachable from the canvas border through uncovered px (holes inside the layer)."""
    free = np.ones((H + 2, W + 2), np.uint8)  # a 1 px uncovered frame: the fill starts outside the canvas
    free[1:-1, 1:-1] = ~cover
    cv2.floodFill(free, None, (0, 0), 2)
    return free[1:-1, 1:-1] == 1


def crop(img, c):
    x, y = int(round(c[0])), int(round(c[1]))
    x0, y0 = min(max(x - CROP, 0), W - 2 * CROP), min(max(y - CROP, 0), H - 2 * CROP)
    return cv2.resize(img[y0:y0 + 2 * CROP, x0:x0 + 2 * CROP], None, fx=ZOOM, fy=ZOOM, interpolation=cv2.INTER_NEAREST)


avatars = []
for pk in sorted(int(f[:-5]) for f in os.listdir(f"{DATA}/avatars") if f.endswith(".json")):
    d = json.load(open(f"{DATA}/avatars/{pk}.json"))
    base = cv2.imread(f"{DATA}/avatars/{pk}.png", cv2.IMREAD_UNCHANGED)
    avatars.append((pk, f"{d['sex'][0]}-{d['build']}", d["landmarks"], base, warp.figure_mask(base)))

results, fails = [], []
for gid in GARMENTS:
    gimg = cv2.imread(f"{DATA}/garments/{gid}.png", cv2.IMREAD_UNCHANGED)
    glm = json.load(open(f"{DATA}/garments/{gid}.json"))["landmarks"]
    poly = (glm.get("neck_hole") or {}).get("polygon")
    hole_kw = {"neckline_variant": "hole", "neck_hole_polygon": poly} if poly else {}
    rows = []
    for pk, who, blm, base, mask in avatars:
        runs = {n: pm.tshirt_layer(gimg, glm, blm, mask, "adapt", H, W, debug_map=True, **BASE, **kw, **hole_kw)
                for n, kw in VARIANTS}
        rp = runs["no tube"][1]["pairs"]
        zs = zones_of(rp, blm)
        quads = mf.arm_band_quads(rp, blm)
        near = cv2.dilate(mask.astype(np.uint8), np.ones((2 * BALLOON_EASE + 1,) * 2, np.uint8)) > 0
        c0 = runs["no tube"][0][:, :, 3] >= 128
        full, crops = [], []
        for name, _ in VARIANTS:
            layer, info = runs[name]
            c = layer[:, :, 3] >= 128
            below = np.zeros((H, W), bool)
            for side in ("left", "right"):
                z = (info.get("tube") or {}).get(side, {}).get("below_cuff_zone")
                if z is not None:
                    below |= z
            lost = mask & c0 & ~c
            band = mf.arm_band_skin_px(layer, mask, quads)
            hol = enclosed(c) & mask
            rec = {"garment": gid, "avatar": pk, "who": who, "variant": name,
                   "new_holes": None if name == "no tube" else int((lost & ~below).sum()),
                   "new_holes_where": None if name == "no tube" or not (lost & ~below).any() else
                   [int(Y[lost & ~below].min()), int(Y[lost & ~below].max()), int(X[lost & ~below].min()),
                    int(X[lost & ~below].max())],
                   "arm_below_cuff_px": None if name == "no tube" else int((lost & below).sum()),
                   "patched_px": (info.get("side_floor_mask") or {}).get("patched_px"),
                   "runtime_s": round(info["runtime"], 3),
                   "fold": round(bm.metrics(layer, info, blm)["fold"], 5)}
            for side, sx in (("left", "_l"), ("right", "_r")):
                k = side[0]
                sl, zone, B1, cm = zs[side]
                rep = (info.get("tube") or {}).get(side, {})
                rec[f"holes_enclosed_{k}"] = int((hol & zone).sum())
                rec[f"arm_band_{k}"] = band[side]
                if "cuff" in rep:
                    a_, b_ = rep["cuff"]
                    cp = {"cuff_out" + sx: (None, tuple(a_), 1.0), "cuff_in" + sx: (None, tuple(b_), 1.0),
                          "shoulder" + sx: info["pairs"]["shoulder" + sx]}
                else:
                    cp = {kk: v for kk, v in info["pairs"].items() if kk in ("cuff_out" + sx, "cuff_in" + sx,
                                                                            "shoulder" + sx)}
                rec[f"cuff_wave_{k}"] = mf.cuff_wave_px(layer, cp)
                rec[f"balloon_{k}"] = int((sl & c & ~near).sum())
                rec[f"protected_{k}"] = rep.get("protected_px")
                rec[f"cleared_below_cuff_{k}"] = rep.get("cleared_below_cuff_px")
                if "skipped" in rep:
                    rec[f"skipped_{k}"] = rep["skipped"]
            rec["filled_px"] = (info.get("tube") or {}).get("filled_px")
            if name == "tube" and rec["new_holes"]:
                fails.append(f"#{gid} {who}: {rec['new_holes']} new hole px at y/x {rec['new_holes_where']}")
            results.append(rec)
            print(json.dumps(rec, default=str))
            rgb = bm.composite(base, layer, blm, info)
            fy0, fy1 = max(int(blm["neck"]["y"]) - 30, 0), min(int(rp["hem_l"][1][1]) + 60, H)
            full.append(label(cv2.resize(rgb[fy0:fy1], None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST),
                              f"{LABELS[name]} #{gid} {who}"))
            cs = []
            for side in ("left", "right"):
                _, _, B1, cm = zs[side]
                cs += [crop(rgb, B1 + np.array([0.0, 12.0])), crop(rgb, cm)]
            crops.append(label(np.hstack(cs), f"{LABELS[name]}: underarm L | cuff L | underarm R | cuff R"))
        rows.append(hstack(full))
        rows.append(vstack(crops))
    cv2.imwrite(f"{OUT}/sheet_tube13_{gid}.png", vstack(rows))
with open(f"{OUT}/results_tube13.json", "w") as fh:
    json.dump({"runs": results, "fails": fails}, fh, indent=1, default=str)


def S(rs, k):
    return sum((r.get(k) or 0) for r in rs)


def M(rs, k, how=max, nd=1):
    v = [r[k] for r in rs if r.get(k) is not None]
    return round(how(v), nd) if v else "-"


lines = ["| garment | variant | new holes | arm uncovered below cuff | holes enclosed L / R | arm-band skin L / R | "
         "cuff wave max L / R | balloon L / R | fold (max) | runtime s (max) |",
         "|---|---|---|---|---|---|---|---|---|---|"]
for g in GARMENTS + ["all"]:
    for name, _ in VARIANTS:
        rs = [r for r in results if r["variant"] == name and (g == "all" or r["garment"] == g)]
        lines.append(f"| {'#' + str(g) if g != 'all' else 'all'} | {name} | "
                     f"{'-' if name == 'no tube' else S(rs, 'new_holes')} | "
                     f"{'-' if name == 'no tube' else S(rs, 'arm_below_cuff_px')} | "
                     f"{S(rs, 'holes_enclosed_l')} / {S(rs, 'holes_enclosed_r')} | {S(rs, 'arm_band_l')} / "
                     f"{S(rs, 'arm_band_r')} | {M(rs, 'cuff_wave_l')} / {M(rs, 'cuff_wave_r')} | {S(rs, 'balloon_l')} / "
                     f"{S(rs, 'balloon_r')} | {M(rs, 'fold', nd=5):.5f} | {M(rs, 'runtime_s')} |")
lines += ["", "| garment | avatar | variant | new holes (where y0, y1, x0, x1) | arm below cuff | holes enclosed L / R | "
          "arm-band L / R | cuff wave L / R | balloon L / R | protected L / R | cleared below cuff L / R | filled | patched | "
          "runtime s |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
for r in results:
    lines.append(f"| #{r['garment']} | {r['who']} | {r['variant']} | {r['new_holes']} {r['new_holes_where'] or ''} | "
                 f"{r['arm_below_cuff_px']} | {r['holes_enclosed_l']} / {r['holes_enclosed_r']} | {r['arm_band_l']} / "
                 f"{r['arm_band_r']} | {r['cuff_wave_l']} / {r['cuff_wave_r']} | {r['balloon_l']} / {r['balloon_r']} | "
                 f"{r['protected_l']} / {r['protected_r']} | {r['cleared_below_cuff_l']} / {r['cleared_below_cuff_r']} | "
                 f"{r['filled_px']} | {r['patched_px']} | {r['runtime_s']} |")
lines += ["", f"GATE (tube column, new holes > 0): {len(fails)} / {len(GARMENTS) * len(avatars)} runs fail"]
lines += [f"- {f}" for f in fails]
with open(f"{OUT}/table_tube13.md", "w") as fh:
    fh.write("\n".join(lines) + "\n")
print("\n".join(lines))
if fails:
    sys.exit(1)
