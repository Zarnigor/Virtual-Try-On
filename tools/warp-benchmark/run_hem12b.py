"""MLS benchmark round 12b: hem tongue, garment hem, hem_c, tube arm fit, no new holes (docs/06 "Hem and tube, round
12b", NOT production).

    docker compose exec -T backend rm -rf /tmp/warp-benchmark /tmp/warp_benchmark
    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T -e EXPORT_ROOT=/tmp/warp-benchmark/data/side12 backend python manage.py shell \
        < tools/warp-benchmark/export_sleeve8b.py          # the round 8b exporter, current DB -> data/side12/
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/run_hem12b.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

#28, #43, #40 x 6 avatars, adapt. Every variant: sleeve C + side_floor + sleeve_mode "tube" + collar_floor + the
neck_hole polygon. Columns (sheets): reference = + side_floor_mode "mask" (with the round 12b blend back to the
landmark floor map) + tube_arm "fit" | + hem smooth | + hem garment | + hem_c (hem_c_pair). Not columns: r12ref = the
round 12 reference (landmark floor, tube r11): the reference must not uncover any figure px it covered; tube_r11 =
reference with tube_arm "r11" (the #40 before / after of the tube width clamp, sheet_tube12b_40.png).
New holes = figure px covered (alpha >= 128) by the base and not by the variant, whole canvas; base = r12ref for the
reference, the reference for the three hem columns. The px the reference tube cleared beyond its cuff line (engine
report "beyond_cuff_zone", grown by the remove_halo reach) are NOT counted for the reference vs r12ref: clearing the
jagged MLS cuff px there uncovers the arm by design; they are reported as beyond_cuff_px. Any run with new holes > 0
is FAIL; the script exits with status 1 after writing
everything. Metrics: hem_tongue_px, hem_wave_px (run_side12.hem_metrics), max band stretch (hem garment), side strip
L / R (run_side12.strips), tube balloon / arm-band skin / cuff width (reference vs tube_r11).
Writes out/table_hem12b.md, out/results_hem12b.json, out/sheet_hem12b_<id>.png (FULL whole T-shirt, clean),
out/sheet_tube12b_40.png.
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
BASE = {"side_floor_mode": "mask", "tube_arm": "fit"}
VARIANTS = [("r12ref", {}), ("tube_r11", {"side_floor_mode": "mask"}), ("reference", BASE),
            ("+smooth", {**BASE, "hem_mode": "smooth"}), ("+garment", {**BASE, "hem_mode": "garment"}),
            ("+hem_c", {**BASE, "hem_c_pair": True})]
COLUMNS = ["reference", "+smooth", "+garment", "+hem_c"]
H, W = 1200, 600
OUT = "/tmp/warp_benchmark"
DATA = "/tmp/warp-benchmark/data/side12"
HEM_BAND = 20  # px above the hem target: side strips stop there (as round 12)
BALLOON_EASE = 3  # as round 11
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


def hem_metrics(layer, pairs, near=60):
    """= run_side12.hem_metrics: (hem_tongue_px, hem_wave_px)."""
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
    """= run_side12.strips (all rows only)."""
    out = {}
    for side in ("left", "right"):
        tot = 0
        for y, e, _ in edges[side]:
            if e is None or y >= y_end:
                continue
            x0, x1 = (int(np.ceil(e)), int(axis)) if side == "left" else (int(axis) + 1, int(np.floor(e)) - 1)
            if x1 >= x0:
                tot += int((mask[y, x0:x1 + 1] & ~cover[y, x0:x1 + 1]).sum())
        out[side] = tot
    return out


def beyond_cuff(info):
    """The px the reference tube cleared beyond its cuff line (engine report "beyond_cuff_zone": those px grown by the
    remove_halo erosion reach), both sides."""
    z = np.zeros((H, W), bool)
    for side in ("left", "right"):
        zz = info.get("tube", {}).get(side, {}).get("beyond_cuff_zone")
        if zz is not None:
            z |= zz
    return z


def sleeve_zones(rp, blm):
    """Round 11 sleeve zones (outward of the reference armhole line, above the lower cuff target + 10 px)."""
    zones = {}
    for side, sx in (("left", "_l"), ("right", "_r")):
        B0 = np.array(rp["shoulder" + sx][1], float)
        B1 = np.array(rp["armpit" + sx][1], float) if "armpit" + sx in rp else \
            np.array([float(blm["armpit"][f"{side}_x"]), float(blm["armpit"]["y"])])
        cm = (np.array(rp["cuff_out" + sx][1]) + np.array(rp["cuff_in" + sx][1])) / 2
        ba = np.array([-(B1 - B0)[1], (B1 - B0)[0]])
        if (cm - B0) @ ba < 0:
            ba = -ba
        ylow = max(rp["cuff_out" + sx][1][1], rp["cuff_in" + sx][1][1]) + 10
        zones[side] = (((PX - B0) @ ba) > 0) & (Y <= ylow)
    return zones


avatars = []
for pk in sorted(int(f[:-5]) for f in os.listdir(f"{DATA}/avatars") if f.endswith(".json")):
    d = json.load(open(f"{DATA}/avatars/{pk}.json"))
    base = cv2.imread(f"{DATA}/avatars/{pk}.png", cv2.IMREAD_UNCHANGED)
    avatars.append((pk, f"{d['sex'][0]}-{d['build']}", d["landmarks"], base, warp.figure_mask(base)))

results, fails = [], []
tube_rows = []
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
        edges = pm.torso_side_edges(mask, blm, list(range(a_y + 2, hem_y)), axis)
        cov = {n: runs[n][0][:, :, 3] >= 128 for n, _ in VARIANTS}
        bc = beyond_cuff(runs["reference"][1])
        zones = sleeve_zones(rp, blm)
        near = cv2.dilate(mask.astype(np.uint8), np.ones((2 * BALLOON_EASE + 1,) * 2, np.uint8)) > 0
        quads = mf.arm_band_quads(rp, blm)
        cells = []
        for name, _ in VARIANTS:
            layer, info = runs[name]
            c = cov[name]
            if name == "reference":
                new = mask & cov["r12ref"] & ~c
                new_counted = new & ~bc
                beyond = int((new & bc).sum())
            elif name in COLUMNS:
                new_counted = mask & cov["reference"] & ~c
                beyond = None
            else:
                new_counted, beyond = None, None
            st = strips(mask, c, edges, axis, hem_y - HEM_BAND)
            tongue, wave = hem_metrics(layer, info["pairs"])
            sfm = info.get("side_floor_mask") or {}
            hg = info.get("hem_garment") or {}
            band = mf.arm_band_skin_px(layer, mask, quads)
            rec = {"garment": gid, "avatar": pk, "who": who, "variant": name,
                   "hem_tongue_px": tongue, "hem_wave_px": wave,
                   "max_band_stretch": hg.get("max_stretch"), "stretch_warn": hg.get("stretch_warn"),
                   "hem_garment": hg or None, "hem_smooth": info.get("hem_smooth"), "hem_c": info.get("hem_c"),
                   "hem_c_present": "hem_c" in info["pairs"],
                   "strip_l": st["left"], "strip_r": st["right"],
                   "new_holes": None if new_counted is None else int(new_counted.sum()),
                   "new_holes_where": None if new_counted is None or not new_counted.any() else
                   [int(Y[new_counted].min()), int(Y[new_counted].max()), int(X[new_counted].min()),
                    int(X[new_counted].max())],
                   "beyond_cuff_px": beyond,
                   "blend_px": sfm.get("blend_px"), "blend_rounds": sfm.get("blend_rounds"),
                   "blend_residual_px": sfm.get("blend_residual_px"), "patched_px": sfm.get("patched_px"),
                   "hem_band_removed": sfm.get("hem_band_removed_rows"),
                   "balloon_l": int((zones["left"] & c & ~near).sum()),
                   "balloon_r": int((zones["right"] & c & ~near).sum()),
                   "arm_band_l": band["left"], "arm_band_r": band["right"],
                   "fold": round(bm.metrics(layer, info, blm)["fold"], 5), "runtime_s": round(info["runtime"], 3)}
            for side in ("left", "right"):
                rep = info.get("tube", {}).get(side, {})
                w = (rep.get("widths") or [{}])[-1]
                rec[f"cuff_{side[0]}"] = {"out_in": w.get("out_in"), "arm": w.get("arm_out_in"),
                                          "garment_x_s": w.get("garment_x_s")}
                rec[f"max_ratio_{side[0]}"] = max(
                    [round((ww["out_in"][0] + ww["out_in"][1]) / max((ww["arm_out_in"][0] or 0) +
                                                                     (ww["arm_out_in"][1] or 0), 1e-6), 2)
                     for ww in (rep.get("widths") or [])[1:] if ww["arm_out_in"][0] is not None] or [None])
                rec[f"cleared_beyond_cuff_{side[0]}"] = rep.get("cleared_beyond_cuff_px")
            if rec["new_holes"]:
                fails.append(f"#{gid} {who} {name}: {rec['new_holes']} new hole px at y/x {rec['new_holes_where']}")
            results.append(rec)
            print(json.dumps({k: v for k, v in rec.items() if k not in ("hem_garment", "hem_smooth", "hem_c")},
                             default=str))
            rgb = bm.composite(base, layer, blm, info)
            fy0, fy1 = max(int(blm["neck"]["y"]) - 30, 0), min(hem_y + 60, H)
            big = cv2.resize(rgb[fy0:fy1], None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
            if name in COLUMNS:
                cells.append(label(big, f"{name} #{gid} {who}"))
            if gid == 40 and name in ("tube_r11", "reference"):
                tube_rows.append((who, name, label(big.copy(), f"{'tube r11' if name == 'tube_r11' else 'tube fit'} "
                                                              f"#{gid} {who}")))
        rows.append(hstack(cells))
    cv2.imwrite(f"{OUT}/sheet_hem12b_{gid}.png", vstack(rows))
by_who = {}
for who, name, img in tube_rows:
    by_who.setdefault(who, {})[name] = img
cv2.imwrite(f"{OUT}/sheet_tube12b_40.png", vstack([hstack([v["tube_r11"], v["reference"]]) for v in by_who.values()]))
with open(f"{OUT}/results_hem12b.json", "w") as fh:
    json.dump({"runs": results, "fails": fails}, fh, indent=1, default=str)


def S(rs, k):
    return sum((r[k] or 0) for r in rs)


def M(rs, k):
    v = [r[k] for r in rs if r[k] is not None]
    return max(v) if v else "-"


lines = ["| garment | variant | hem tongue px (max) | hem wave px (max) | max band stretch | side strip L / R | "
         "new holes | beyond cuff px | balloon L / R | arm-band skin L / R | fold (max) | runtime s (max) |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
for g in GARMENTS + ["all"]:
    for name, _ in VARIANTS:
        rs = [r for r in results if r["variant"] == name and (g == "all" or r["garment"] == g)]
        nh = "-" if name in ("r12ref", "tube_r11") else S(rs, "new_holes")
        lines.append(f"| {'#' + str(g) if g != 'all' else 'all'} | {name} | {M(rs, 'hem_tongue_px')} | "
                     f"{M(rs, 'hem_wave_px')} | {M(rs, 'max_band_stretch')} | {S(rs, 'strip_l')} / {S(rs, 'strip_r')} | "
                     f"{nh} | {S(rs, 'beyond_cuff_px') if name == 'reference' else '-'} | {S(rs, 'balloon_l')} / "
                     f"{S(rs, 'balloon_r')} | {S(rs, 'arm_band_l')} / {S(rs, 'arm_band_r')} | {M(rs, 'fold'):.5f} | "
                     f"{M(rs, 'runtime_s')} |")
lines += ["", "Per run, hem tongue px: r12ref | reference | + smooth | + garment | + hem_c; new holes (reference vs r12ref, "
              "columns vs reference); garment hem: max stretch / clamped columns / band px", "",
          "| garment | avatar | r12ref | reference | + smooth | + garment | + hem_c | new holes ref / smooth / garment / "
          "hem_c | beyond cuff px | stretch / clamped / band | hem-band rows removed |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
idx = {(r["garment"], r["who"], r["variant"]): r for r in results}
for gid in GARMENTS:
    for pk, who, *_ in avatars:
        R = {n: idx[(gid, who, n)] for n, _ in VARIANTS}
        hg = R["+garment"]["hem_garment"] or {}
        lines.append(f"| #{gid} | {who} | " + " | ".join(str(R[n]["hem_tongue_px"]) for n in
                                                        ("r12ref", "reference", "+smooth", "+garment", "+hem_c")) +
                     f" | {' / '.join(str(R[n]['new_holes']) for n in COLUMNS)} | {R['reference']['beyond_cuff_px']} | "
                     f"{hg.get('max_stretch')} / {hg.get('clamped')} / {hg.get('band_px')} | "
                     f"{R['reference']['hem_band_removed'] or '-'} |")
lines += ["", "#40 tube before / after (tube_r11 -> reference = tube_arm fit): cuff out / in px (arm out / in), "
              "max (out + in) / arm ratio, balloon, arm-band skin, cleared beyond cuff px", "",
          "| avatar | side | cuff r11 | cuff fit | arm | ratio r11 / fit | balloon r11 / fit | arm-band skin r11 / fit | "
          "cleared beyond cuff px |", "|---|---|---|---|---|---|---|---|---|"]
for pk, who, *_ in avatars:
    a, b = idx[(40, who, "tube_r11")], idx[(40, who, "reference")]
    for side in ("l", "r"):
        lines.append(f"| {who} | {side} | {a[f'cuff_{side}']['out_in']} | {b[f'cuff_{side}']['out_in']} | "
                     f"{b[f'cuff_{side}']['arm']} | {a[f'max_ratio_{side}']} / {b[f'max_ratio_{side}']} | "
                     f"{a[f'balloon_{side}']} / {b[f'balloon_{side}']} | {a[f'arm_band_{side}']} / "
                     f"{b[f'arm_band_{side}']} | {b[f'cleared_beyond_cuff_{side}']} |")
lines += ["", f"FAIL runs (new holes > 0): {len(fails)}"] + [f"- {f}" for f in fails]
with open(f"{OUT}/table_hem12b.md", "w") as fh:
    fh.write("\n".join(lines) + "\n")
print("\n".join(lines))
if fails:
    sys.exit(1)
