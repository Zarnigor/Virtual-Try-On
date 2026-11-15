"""MLS benchmark round 11: tube sleeves for adapt T-shirts (docs/06 "Tube sleeve, round 11", NOT production).

    docker compose exec -T -e EXPORT_ROOT=/tmp/warp-benchmark/data/tube11 backend python manage.py shell \
        < tools/warp-benchmark/export_sleeve8b.py          # the round 8b exporter, current DB -> data/tube11/
    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/run_tube11.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

#28, #43, #40 x 6 avatars, adapt. reference = sleeve C + side_floor (on in every variant; render_tryon does not pass
side_floor yet) + collar_floor + the garment's neck_hole polygon (no neck_clip). tube = sleeve_mode "tube" (ruled
strip, fixes 1-3), tube_perp = sleeve_mode "tube_perp" (cross-sections perpendicular to the axis). Metrics, L / R,
measured in the SAME zones for every variant, built from the reference pairs: arm_band_skin_px (reference arm-band
quads), cuff_wave_px (reference: its cuff pairs; tubes: their cuff segment), balloon_px (garment px over the
background outward of the reference body armhole line, above the lower reference cuff target + 10 px, beyond the figure
dilated by BALLOON_EASE px), armhole_seam_px (uncovered figure px within SEAM_PX of the body armhole segment),
cleared_px, axis_dev (max |axis x - _arm_at fit x| over the sections with t >= 0.5, the straight fit through the
separated arm rows), gap, excess, fold, runtime. Sheets: reference | tube | tube_perp, 3x; yellow = body arm axis,
grey = cross-sections, orange = the t = 0 segment, red = cuff, cyan = the _arm_at fit line.
Writes out/table_tube.md, out/results_tube.json, out/sheet_tube_<id>.png, out/crop_tube_armhole_worst.png,
out/crop_tube_worst.png.
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
VARIANTS = [("reference", {}), ("tube", {"sleeve_mode": "tube"}), ("tube_perp", {"sleeve_mode": "tube_perp"})]
TUBES = [n for n, _ in VARIANTS if n != "reference"]
H, W = 1200, 600
OUT = "/tmp/warp_benchmark"
DATA = "/tmp/warp-benchmark/data/tube11"
ZOOM = 3
BALLOON_EASE = 3
SEAM_PX = 12
AXIS_WARN = 5.0
CLEAN = os.environ.get("CLEAN", "0") == "1"  # 1 = sheets as the user sees the result: no axes, sections or numbers
os.makedirs(OUT, exist_ok=True)


def label(img, text, y=18, scale=0.5):
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(img, text, (6, y), cv2.FONT_HERSHEY_SIMPLEX, scale, col, th, cv2.LINE_AA)
    return img


def seg_dist(P, a, b):
    seg = b - a
    t = np.clip(((P - a) @ seg) / max(float(seg @ seg), 1e-9), 0, 1)
    return np.linalg.norm(P - (a + t[..., None] * seg), axis=-1)


def hstack(cells):
    h = max(c.shape[0] for c in cells)
    return np.hstack([np.pad(c, ((0, h - c.shape[0]), (0, 0), (0, 0)), constant_values=255) for c in cells])


Y, X = np.mgrid[0:H, 0:W]
PX = np.stack([X, Y], -1).astype(np.float32)
avatars = []
for pk in sorted(int(f[:-5]) for f in os.listdir(f"{DATA}/avatars") if f.endswith(".json")):
    with open(f"{DATA}/avatars/{pk}.json") as fh:
        d = json.load(fh)
    base = cv2.imread(f"{DATA}/avatars/{pk}.png", cv2.IMREAD_UNCHANGED)
    avatars.append((pk, f"{d['sex'][0]}-{d['build']}", d["landmarks"], base, warp.figure_mask(base)))

results, notes = [], []
worst, worst_seam = {}, None
for gid in GARMENTS:
    gimg = cv2.imread(f"{DATA}/garments/{gid}.png", cv2.IMREAD_UNCHANGED)
    with open(f"{DATA}/garments/{gid}.json") as fh:
        glm = json.load(fh)["landmarks"]
    poly = (glm.get("neck_hole") or {}).get("polygon")
    hole_kw = {"neckline_variant": "hole", "neck_hole_polygon": poly} if poly else {}
    rows = []
    for pk, who, blm, base, mask in avatars:
        runs = {name: pm.tshirt_layer(gimg, glm, blm, mask, "adapt", H, W, sleeve_variant="C", side_floor=True,
                                      debug_map=True, **kw, **hole_kw) for name, kw in VARIANTS}
        rp = runs["reference"][1]["pairs"]
        arms = warp.find_arms(mask, blm)
        quads = mf.arm_band_quads(rp, blm)
        near = cv2.dilate(mask.astype(np.uint8), np.ones((2 * BALLOON_EASE + 1,) * 2, np.uint8)) > 0
        zones, seams, armholes, holezone = {}, {}, {}, {}
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
            seams[side] = seg_dist(PX, B0, B1) <= SEAM_PX
            holezone[side] = zones[side] | (seg_dist(PX, B0, B1) <= 15)  # = tests_mls.tube_zone, one side
            armholes[side] = (B0, B1)
        cells = {}
        ref_cover = runs["reference"][0][:, :, 3] >= 128
        for name, _ in VARIANTS:
            layer, info = runs[name]
            rep_all = info.get("tube", {})
            cover = layer[:, :, 3] >= 128
            band = mf.arm_band_skin_px(layer, mask, quads)
            cov = mf.coverage_metrics(layer, mask, info, blm)
            rec = {"garment": gid, "avatar": pk, "who": who, "variant": name,
                   "fold": round(bm.metrics(layer, info, blm)["fold"], 5), "gap_px": cov["gap_px"],
                   "excess_px": cov["excess_px"], "runtime_s": round(info["runtime"], 3), "rejected": info["rejected"]}
            for side, sx in (("left", "_l"), ("right", "_r")):
                k = side[0]
                rep = rep_all.get(side, {})
                if rep.get("skipped"):
                    notes.append(f"#{gid} {who} {name} {side}: skipped ({rep['skipped']})")
                rec[f"arm_band_{k}"] = band[side]
                if "cuff" in rep:
                    a_, b_ = rep["cuff"]
                    cp = {"cuff_out" + sx: (None, tuple(a_), 1.0), "cuff_in" + sx: (None, tuple(b_), 1.0),
                          "shoulder" + sx: info["pairs"]["shoulder" + sx]}
                else:
                    cp = {kk: v for kk, v in info["pairs"].items() if kk in ("cuff_out" + sx, "cuff_in" + sx,
                                                                            "shoulder" + sx)}
                rec[f"cuff_wave_{k}"] = mf.cuff_wave_px(layer, cp)
                rec[f"balloon_{k}"] = int((zones[side] & cover & ~near).sum())
                rec[f"seam_{k}"] = int((seams[side] & mask & ~cover).sum())
                rec[f"new_holes_{k}"] = int((holezone[side] & mask & ~cover & ref_cover).sum())
                rec[f"cleared_{k}"] = rep.get("cleared_px")
                rec[f"axis_dev_{k}"] = rep.get("axis_dev_max")
                if rep.get("axis_dev_max") is not None and rep["axis_dev_max"] > AXIS_WARN:
                    notes.append(f"#{gid} {who} {name} {side}: axis -> arm fit {rep['axis_dev_max']} px (> {AXIS_WARN})")
            results.append(rec)
            print(json.dumps({kk: v for kk, v in rec.items() if kk != "rejected"}, default=str))
            rgb = bm.composite(base, layer, blm, info)
            y0 = max(int(blm["neck"]["y"]) - 20, 0)
            y1 = min(int(max(rp["cuff_in_l"][1][1], rp["cuff_in_r"][1][1])) + 60, H)
            big = cv2.resize(rgb[y0:y1], None, fx=ZOOM, fy=ZOOM, interpolation=cv2.INTER_NEAREST)
            S = lambda p: (int(round(p[0] * ZOOM)), int(round((p[1] - y0) * ZOOM)))  # noqa: E731
            for side in ([] if CLEAN else ("left", "right")):
                f0, f1 = pm._arm_at(arms, side, y0 + 40), pm._arm_at(arms, side, y1)
                if f0 and f1:
                    cv2.line(big, S((f0[0], y0 + 40)), S((f1[0], y1)), (255, 220, 0), 1, cv2.LINE_AA)
                rep = rep_all.get(side, {})
                if "axis_body" not in rep:
                    continue
                for a_, b_ in rep["sections"]:
                    cv2.line(big, S(a_), S(b_), (150, 150, 150), 1, cv2.LINE_AA)
                cv2.line(big, S(rep["t0_body"][0]), S(rep["t0_body"][1]), (0, 140, 255), 2, cv2.LINE_AA)
                cv2.line(big, S(rep["axis_body"][0]), S(rep["axis_body"][1]), (0, 220, 255), 2, cv2.LINE_AA)
                cv2.line(big, S(rep["cuff"][0]), S(rep["cuff"][1]), (40, 40, 230), 2, cv2.LINE_AA)
            under = []  # underarm crops, both sides, 4x
            for side in ("left", "right"):
                B1 = armholes[side][1]
                ux0, uy0 = max(int(B1[0]) - 40, 0), max(int(B1[1]) - 40, 0)
                under.append(cv2.resize(rgb[uy0:uy0 + 80, ux0:ux0 + 80], None, fx=4, fy=4,
                                        interpolation=cv2.INTER_NEAREST))
            ustrip = label(np.hstack(under), f"underarm L | R  new holes {rec['new_holes_l']} / {rec['new_holes_r']}")
            if ustrip.shape[1] < big.shape[1]:
                ustrip = np.pad(ustrip, ((0, 0), (0, big.shape[1] - ustrip.shape[1]), (0, 0)), constant_values=255)
            big = np.vstack([big, ustrip[:, :big.shape[1]]])
            cells[name] = label(big, f"{name} #{gid} {who}") if CLEAN else label(big, f"{name} #{gid} {who} arm {rec['arm_band_l']}/{rec['arm_band_r']} balloon "
                                     f"{rec['balloon_l']}/{rec['balloon_r']} seam {rec['seam_l']}/{rec['seam_r']} "
                                     f"wave {rec['cuff_wave_l']}/{rec['cuff_wave_r']}")
            if name in TUBES:
                tot = sum((rec[kk] or 0) for kk in ("arm_band_l", "arm_band_r", "balloon_l", "balloon_r"))
                if name not in worst or tot > worst[name][0]:
                    worst[name] = (tot, gid, who, pk)
                for side, k in (("left", "l"), ("right", "r")):
                    if worst_seam is None or rec[f"seam_{k}"] > worst_seam[0]:
                        worst_seam = (rec[f"seam_{k}"], gid, who, side, name,
                                      {n: bm.composite(base, runs[n][0], blm, runs[n][1]) for n, _ in VARIANTS},
                                      armholes[side])
        rows.append(hstack([cells[n] for n, _ in VARIANTS]))
        for name in TUBES:
            if worst.get(name) and worst[name][1] == gid and worst[name][3] == pk:
                worst[name] = worst[name][:4] + (hstack([cells[n] for n, _ in VARIANTS]),)
    wmax = max(r.shape[1] for r in rows)
    cv2.imwrite(f"{OUT}/sheet_tube_{gid}.png", np.vstack(
        [np.pad(r, ((0, 0), (0, wmax - r.shape[1]), (0, 0)), constant_values=255) for r in rows]))

imgs = []
for name in TUBES:
    n, gid, who, pk, img = worst[name]
    imgs.append(label(img.copy(), f"worst {name} (arm band + balloon {n} px): #{gid} {who}  [reference | tube | "
                                  f"tube_perp]", y=img.shape[0] - 12, scale=0.8))
wmax = max(i.shape[1] for i in imgs)
cv2.imwrite(f"{OUT}/crop_tube_worst.png", np.vstack(
    [np.pad(i, ((0, 0), (0, wmax - i.shape[1]), (0, 0)), constant_values=255) for i in imgs]))
n, gid, who, side, name, rgbs, (B0, B1) = worst_seam
c = (B0 + B1) / 2
x0, y0, x1, y1 = max(int(c[0]) - 50, 0), max(int(c[1]) - 55, 0), min(int(c[0]) + 50, W), min(int(c[1]) + 55, H)
crops = [label(cv2.resize(rgbs[v][y0:y1, x0:x1], None, fx=5, fy=5, interpolation=cv2.INTER_NEAREST), v)
         for v, _ in VARIANTS]
img = hstack(crops)
cv2.imwrite(f"{OUT}/crop_tube_armhole_worst.png", label(img, f"worst armhole seam {n} px ({name}): #{gid} {who} {side}",
                                                        y=img.shape[0] - 10, scale=0.7))
with open(f"{OUT}/results_tube.json", "w") as fh:
    json.dump({"runs": results, "notes": notes}, fh, default=str, indent=1)


def agg(rs, k, how):
    v = [r[k] for r in rs if r[k] is not None]
    if not v:
        return "-"
    return sum(v) if how == "sum" else (round(float(np.median(v)), 1) if how == "median" else max(v))


lines = ["| garment | variant | arm-band skin L / R | cuff wave median / max L, R | balloon L / R | armhole seam L / R | new holes L / R | "
         "cleared L / R | gap | excess | fold (max) | axis dev max L / R | runtime s (max) |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
for gid in GARMENTS + ["all"]:
    for name, _ in VARIANTS:
        rs = [r for r in results if r["variant"] == name and (gid == "all" or r["garment"] == gid)]
        lines.append(
            f"| {'#' + str(gid) if gid != 'all' else 'all'} | {name} | {agg(rs, 'arm_band_l', 'sum')} / "
            f"{agg(rs, 'arm_band_r', 'sum')} | {agg(rs, 'cuff_wave_l', 'median')} / {agg(rs, 'cuff_wave_l', 'max')}, "
            f"{agg(rs, 'cuff_wave_r', 'median')} / {agg(rs, 'cuff_wave_r', 'max')} | {agg(rs, 'balloon_l', 'sum')} / "
            f"{agg(rs, 'balloon_r', 'sum')} | {agg(rs, 'seam_l', 'sum')} / {agg(rs, 'seam_r', 'sum')} | "
            f"{agg(rs, 'new_holes_l', 'sum')} / {agg(rs, 'new_holes_r', 'sum')} | "
            f"{agg(rs, 'cleared_l', 'sum')} / {agg(rs, 'cleared_r', 'sum')} | {agg(rs, 'gap_px', 'sum')} | "
            f"{agg(rs, 'excess_px', 'sum')} | {agg(rs, 'fold', 'max')} | {agg(rs, 'axis_dev_l', 'max')} / "
            f"{agg(rs, 'axis_dev_r', 'max')} | {agg(rs, 'runtime_s', 'max')} |")
lines += ["", "| garment | avatar | variant | arm L / R | wave L / R | balloon L / R | seam L / R | new holes L / R | cleared L / R | "
          "gap | excess | fold | axis dev L / R | runtime s |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
for r in results:
    lines.append(f"| #{r['garment']} | {r['who']} | {r['variant']} | {r['arm_band_l']} / {r['arm_band_r']} | "
                 f"{r['cuff_wave_l']} / {r['cuff_wave_r']} | {r['balloon_l']} / {r['balloon_r']} | {r['seam_l']} / "
                 f"{r['seam_r']} | {r['new_holes_l']} / {r['new_holes_r']} | {r['cleared_l']} / {r['cleared_r']} | {r['gap_px']} | {r['excess_px']} | "
                 f"{r['fold']:.4f} | {r['axis_dev_l']} / {r['axis_dev_r']} | {r['runtime_s']} |")
by = {(r["garment"], r["avatar"], r["variant"]): r for r in results}
M = [("arm_band_l", "arm L"), ("arm_band_r", "arm R"), ("cuff_wave_l", "wave L"), ("cuff_wave_r", "wave R"),
     ("balloon_l", "balloon L"), ("balloon_r", "balloon R"), ("seam_l", "seam L"), ("seam_r", "seam R"),
     ("new_holes_l", "new holes L"), ("new_holes_r", "new holes R"),
     ("gap_px", "gap"), ("excess_px", "excess"), ("fold", "fold")]
for name in TUBES:
    part = []
    for gid in GARMENTS:
        for pk, who, *_ in avatars:
            a, b = by[(gid, pk, "reference")], by[(gid, pk, name)]
            bad = [f"{lab} {a[k]} -> {b[k]}" for k, lab in M if a[k] is not None and b[k] is not None and b[k] > a[k]]
            if bad:
                part.append(f"- #{gid} {who}: {'; '.join(bad)}")
    lines += ["", f"{name} worse than reference (any metric but runtime): {len(part)} / "
                  f"{len(GARMENTS) * len(avatars)} runs"] + (part or ["- none"])
lines += ["", "Notes:"] + ([f"- {n}" for n in notes] or ["- none"])
with open(f"{OUT}/table_tube.md", "w") as fh:
    fh.write("\n".join(lines) + "\n")
print("\n".join(lines[:2 + 3 * (len(GARMENTS) + 1)]))
print(f"notes: {len(notes)}")
