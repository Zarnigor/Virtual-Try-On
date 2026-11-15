"""MLS benchmark round 12: full torso side coverage (docs/06 "Side coverage, round 12", NOT production).

    docker compose exec -T -e EXPORT_ROOT=/tmp/warp-benchmark/data/side12 backend python manage.py shell \
        < tools/warp-benchmark/export_sleeve8b.py          # the round 8b exporter, current DB -> data/side12/
    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/run_side12.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

#28, #43, #40 x 6 avatars, adapt. reference = sleeve C + side_floor (landmark rows) + sleeve_mode="tube" (layering fix)
+ collar_floor + the neck_hole polygon; mask = the same + side_floor_mode="mask". Metrics, L / R:
side_strip_px = figure px not covered between the torso edge (`mls.torso_side_edges`: mask, or interpolated on
arm-touch rows) and the body axis, rows armpit + 2 -> HEM_BAND px above the hem target (the hem itself is a later
round); new holes split into side rows and the hem band; the arm-touch (interpolated) rows also
separately (side_strip_touch); excess over the background; hem_curve_px; fold; new_holes (figure px the reference
covers and the variant does not, rows armpit -> hem target + 20, plus the round 11 shoulder / sleeve zone);
newly_covered; runtime. #28 f-plus per-row table (every 12 px): torso edge x and source, garment edge x (alpha >=
HARD_EDGE) and uncovered px per side, reference vs mask. Sheets: reference | mask, 3x side crops (both sides).
Writes out/table_side12.md, out/results_side12.json, out/sheet_side12_<id>.png, out/crop_side12_worst.png.
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
VARIANTS = [("reference", {}), ("mask", {"side_floor_mode": "mask"}),
            ("mask+smooth", {"side_floor_mode": "mask", "hem_mode": "smooth"})]
H, W = 1200, 600
OUT = "/tmp/warp_benchmark"
DATA = "/tmp/warp-benchmark/data/side12"
ZOOM = 3
FULL = os.environ.get("FULL", "0") == "1"  # 1 = the whole T-shirt (neck -> below the hem, full width, 2x), short label
HEM_BAND = 20  # px above the hem target: side strips stop there; new holes are split side rows / hem band
os.makedirs(OUT, exist_ok=True)


def label(img, text, y=18, scale=0.5):
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(img, text, (6, y), cv2.FONT_HERSHEY_SIMPLEX, scale, col, th, cv2.LINE_AA)
    return img


def hstack(cells):
    h = max(c.shape[0] for c in cells)
    return np.hstack([np.pad(c, ((0, h - c.shape[0]), (0, 0), (0, 0)), constant_values=255) for c in cells])


def hem_metrics(layer, pairs, near=60):
    """(hem_tongue_px, hem_wave_px), measured only on the columns between the hem targets whose bottom edge (alpha >=
    HARD_EDGE) lies within `near` px of the hem target row (columns where the torso hem exists; the corners = the first
    and last such columns). tongue = max drop of the bottom edge in the middle 20 % of those columns below the straight
    line between the two corners; wave = max |bottom - its Gaussian low-pass (sigma = HEM_SMOOTH_WAVE x width / 3)|."""
    hl, hr = pairs["hem_l"][1], pairs["hem_r"][1]
    x0, x1 = int(np.floor(hl[0])), int(np.ceil(hr[0]))
    b = pm.hem_bottom(layer[:, :, 3], x0, x1).astype(float)
    xs = np.arange(x0, x1 + 1)
    ok = (b >= 0) & (np.abs(b - hl[1]) <= near)
    if ok.sum() < 10:
        return None, None
    i0, i1 = np.nonzero(ok)[0][[0, -1]]
    xs, b, ok = xs[i0:i1 + 1], b[i0:i1 + 1], ok[i0:i1 + 1]
    bf = np.interp(xs, xs[ok], b[ok])
    line = bf[0] + (bf[-1] - bf[0]) * (xs - xs[0]) / max(xs[-1] - xs[0], 1)
    mid = (xs >= xs[0] + 0.4 * (xs[-1] - xs[0])) & (xs <= xs[0] + 0.6 * (xs[-1] - xs[0]))
    tongue = float(np.max(bf[mid] - line[mid]))
    wave = float(np.max(np.abs(bf - pm._gauss1d(bf, pm.HEM_SMOOTH_WAVE * (xs[-1] - xs[0]) / 3.0))))
    return round(tongue, 1), round(wave, 1)


def strips(mask, cover, edges, axis, y_end):
    """side strip px per side (all rows / interpolated rows only) from per-row torso edges (every row)."""
    out = {}
    for side in ("left", "right"):
        tot = touch = 0
        for y, e, src in edges[side]:
            if e is None or y >= y_end:
                continue
            x0, x1 = (int(np.ceil(e)), int(axis)) if side == "left" else (int(axis) + 1, int(np.floor(e)) - 1)
            if x1 < x0:
                continue
            seg = mask[y, x0:x1 + 1] & ~cover[y, x0:x1 + 1]
            n = int(seg.sum())
            tot += n
            if src == "interp":
                touch += n
        out[side] = (tot, touch)
    return out


avatars = []
for pk in sorted(int(f[:-5]) for f in os.listdir(f"{DATA}/avatars") if f.endswith(".json")):
    d = json.load(open(f"{DATA}/avatars/{pk}.json"))
    base = cv2.imread(f"{DATA}/avatars/{pk}.png", cv2.IMREAD_UNCHANGED)
    avatars.append((pk, f"{d['sex'][0]}-{d['build']}", d["landmarks"], base, warp.figure_mask(base)))

Y, X = np.mgrid[0:H, 0:W]
results, row_tables, worst = [], [], None
for gid in GARMENTS:
    gimg = cv2.imread(f"{DATA}/garments/{gid}.png", cv2.IMREAD_UNCHANGED)
    glm = json.load(open(f"{DATA}/garments/{gid}.json"))["landmarks"]
    poly = (glm.get("neck_hole") or {}).get("polygon")
    hole_kw = {"neckline_variant": "hole", "neck_hole_polygon": poly} if poly else {}
    rows = []
    for pk, who, blm, base, mask in avatars:
        runs = {n: pm.tshirt_layer(gimg, glm, blm, mask, "adapt", H, W, sleeve_variant="C", side_floor=True,
                                   sleeve_mode="tube", debug_map=True, **kw, **hole_kw) for n, kw in VARIANTS}
        rp = runs["reference"][1]["pairs"]
        axis = warp._crotch_x(blm)
        a_y, hem_y = int(blm["armpit"]["y"]), int(rp["hem_l"][1][1])
        all_rows = list(range(a_y + 2, hem_y))
        edges = pm.torso_side_edges(mask, blm, all_rows, axis)
        hz = np.zeros((H, W), bool)
        hz[a_y:hem_y + 20] = True
        ref_cover = runs["reference"][0][:, :, 3] >= 128
        cells = []
        for name, _ in VARIANTS:
            layer, info = runs[name]
            cover = layer[:, :, 3] >= 128
            st = strips(mask, cover, edges, axis, hem_y - HEM_BAND)
            cov = mf.coverage_metrics(layer, mask, info, blm)
            new = hz & mask & ~cover & ref_cover
            side_rows = Y < hem_y - HEM_BAND
            gain = hz & mask & cover & ~ref_cover
            rec = {"garment": gid, "avatar": pk, "who": who, "variant": name,
                   "strip_l": st["left"][0], "strip_r": st["right"][0],
                   "strip_touch_l": st["left"][1], "strip_touch_r": st["right"][1],
                   "excess_px": cov["excess_px"], "hem_curve_px": cov["hem_curve_px"],
                   "fold": round(bm.metrics(layer, info, blm)["fold"], 5),
                   "new_holes_l": int((new & side_rows & (X < axis)).sum()),
                   "new_holes_r": int((new & side_rows & (X >= axis)).sum()),
                   "new_holes_hem": int((new & ~side_rows).sum()),
                   "newly_covered": int(gain.sum()), "runtime_s": round(info["runtime"], 3),
                   "hem_tongue_px": hem_metrics(layer, info["pairs"])[0], "hem_wave_px": hem_metrics(layer, info["pairs"])[1],
                   "hem_band_removed": (info.get("side_floor_mask") or {}).get("hem_band_removed_rows"),
                   "hem_smooth": info.get("hem_smooth"),
                   "mask_pairs": sorted(k for k in info["pairs"] if k.startswith("sfm")),
                   "touch_rows": sum(1 for r in edges["left"] + edges["right"] if r[2] == "interp")}
            results.append(rec)
            print(json.dumps({k: v for k, v in rec.items() if k != "mask_pairs"}))
            rgb = bm.composite(base, layer, blm, info)
            if FULL:
                fy0, fy1 = max(int(blm["neck"]["y"]) - 30, 0), min(hem_y + 60, H)
                cells.append(label(cv2.resize(rgb[fy0:fy1], None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST),
                                   f"{name} #{gid} {who}"))
            crops = []
            for side in ("left", "right"):
                es = [e for _, e, _ in edges[side] if e is not None]
                ex = int(np.median(es)) if es else (150 if side == "left" else 450)
                x0 = max(ex - 45, 0)
                crops.append(cv2.resize(rgb[a_y - 30:hem_y + 30, x0:x0 + 90], None, fx=ZOOM, fy=ZOOM,
                                        interpolation=cv2.INTER_NEAREST))
            if not FULL:
                cells.append(label(np.hstack(crops), f"{name} #{gid} {who} strip {rec['strip_l']}/{rec['strip_r']} "
                                                    f"new {rec['new_holes_l']}/{rec['new_holes_r']}", scale=0.45))
            if gid == 28 and who == "f-plus":
                tab = []
                for i, y in enumerate(all_rows):
                    if (y - all_rows[0]) % 12:
                        continue
                    row = [y]
                    for side in ("left", "right"):
                        _, e, src = edges[side][i]
                        run = next((q for q in warp._runs(layer[y, :, 3] >= pm.HARD_EDGE) if q[0] <= axis <= q[1]),
                                   None)
                        ge = None if run is None else (run[0] if side == "left" else run[1])
                        n = 0
                        if e is not None:
                            x0, x1 = (int(np.ceil(e)), int(axis)) if side == "left" else (int(axis) + 1,
                                                                                         int(np.floor(e)) - 1)
                            n = int((mask[y, x0:x1 + 1] & ~cover[y, x0:x1 + 1]).sum()) if x1 >= x0 else 0
                        row += [None if e is None else round(e, 1), src, ge, n]
                    tab.append(row)
                row_tables.append((name, tab, sorted(k for k in info["pairs"] if k.startswith(("sfm", "side_")))))
        rows.append(hstack(cells))
        r_mask = results[-2]
        tot = r_mask["strip_l"] + r_mask["strip_r"]
        if worst is None or tot > worst[0]:
            worst = (tot, gid, who, rows[-1])
    wmax = max(r.shape[1] for r in rows)
    cv2.imwrite(f"{OUT}/sheet_side12_{gid}.png", np.vstack(
        [np.pad(r, ((0, 0), (0, wmax - r.shape[1]), (0, 0)), constant_values=255) for r in rows]))
n, gid, who, img = worst
cv2.imwrite(f"{OUT}/crop_side12_worst.png", label(img.copy(), f"worst mask side strip {n} px: #{gid} {who} "
                                                               f"(left reference, right mask)", y=img.shape[0] - 10))
with open(f"{OUT}/results_side12.json", "w") as fh:
    json.dump({"runs": results, "rows_28_f-plus": row_tables}, fh, indent=1, default=str)


def S(rs, k):
    return sum((r[k] or 0) for r in rs)


lines = ["| garment | variant | side strip L / R | of it arm-touch rows L / R | new holes side rows L / R | new holes hem band | newly covered | "
         "hem tongue px (max) | hem wave px (max) | excess | fold (max) | runtime s (max) |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
for g in GARMENTS + ["all"]:
    for name, _ in VARIANTS:
        rs = [r for r in results if r["variant"] == name and (g == "all" or r["garment"] == g)]
        lines.append(f"| {'#' + str(g) if g != 'all' else 'all'} | {name} | {S(rs, 'strip_l')} / {S(rs, 'strip_r')} | "
                     f"{S(rs, 'strip_touch_l')} / {S(rs, 'strip_touch_r')} | {S(rs, 'new_holes_l')} / "
                     f"{S(rs, 'new_holes_r')} | {S(rs, 'new_holes_hem')} | {S(rs, 'newly_covered')} | "
                     f"{max((r['hem_tongue_px'] or 0) for r in rs)} | {max((r['hem_wave_px'] or 0) for r in rs)} | "
                     f"{S(rs, 'excess_px')} | {max(r['fold'] for r in rs):.5f} | "
                     f"{max(r['runtime_s'] for r in rs)} |")
lines += ["", "| garment | avatar | variant | strip L / R | touch rows strip L / R | new holes side L / R | new holes hem | "
          "newly covered | hem tongue | hem wave | excess | fold | runtime s | mask pairs | hem-band rows removed |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
for r in results:
    lines.append(f"| #{r['garment']} | {r['who']} | {r['variant']} | {r['strip_l']} / {r['strip_r']} | "
                 f"{r['strip_touch_l']} / {r['strip_touch_r']} | {r['new_holes_l']} / {r['new_holes_r']} | "
                 f"{r['new_holes_hem']} | "
                 f"{r['newly_covered']} | {r['hem_tongue_px']} | {r['hem_wave_px']} | {r['excess_px']} | {r['fold']:.4f} | "
                 f"{r['runtime_s']} | {len(r['mask_pairs'])} | {r['hem_band_removed'] or '-'} |")
for name, tab, prs in row_tables:
    lines += ["", f"#28 f-plus, {name}: per row (torso edge x / source / garment edge x at alpha >= HARD_EDGE / "
                  f"uncovered px), pairs: {', '.join(prs) or '-'}", "",
              "| row | L edge | L src | L garment | L uncovered | R edge | R src | R garment | R uncovered |",
              "|---|---|---|---|---|---|---|---|---|"]
    lines += [f"| {' | '.join(str(v) for v in row)} |" for row in tab]
with open(f"{OUT}/table_side12.md", "w") as fh:
    fh.write("\n".join(lines) + "\n")
print("\n".join(lines[:2 + 2 * (len(GARMENTS) + 1)]))
