"""MLS benchmark round 9: shoulder LINE fit for adapt T-shirts (docs/06 "Shoulder line fit, round 9", NOT production).

    docker compose exec -T -e EXPORT_ROOT=/tmp/warp-benchmark/data/shoulder9 backend python manage.py shell \
        < tools/warp-benchmark/export_sleeve8b.py          # the round 8b exporter, current DB -> data/shoulder9/
    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/run_shoulder9.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

#28, #43, #40 x 6 avatars, adapt (k 1.0), sleeve_variant "C"; variants: C (reference) and C + line
(`mls.tshirt_layer(..., shoulder_variant="line")`). collar_floor_on stays default (on), side_floor off.
Neckline as in production (owner 2026-11-13): a garment with `neck_hole.polygon` gets neckline_variant="hole" + that
polygon in BOTH variants (no neck_clip); without a polygon r7. NECK_HOLE=0 -> r7 for every garment (first run).
The warped hole (union of both variants) is taken out of the shoulder-top band: the opening is meant to show.
Metrics, L / R: shoulder_top_skin_px (round 8b definition: figure px not covered in neck edge -> acromion, neck row
-> shoulder line + 0.08 x shoulder width, arm band excluded); above_px (garment px OUTSIDE the figure in the same
band: fabric sticking up above the shoulder); arm_band_skin_px; gap, excess, fold; runtime. Both variants use the
C run's bands. Residual: for each line pair (garment point q -> body target p, from the line run) the distance
between p and where q actually lands (forward search in the inverse map around p, canvas px), in BOTH variants; the
same for neck_l / neck_r (collar_floor vs the 25 % pair). Sheets: C | C + line | C + line 50/75 (no 25 % pair), 3x; blue = shoulder-top band,
green dot = body target, magenta dot = where the garment point landed, line between them.
Writes out/results_shoulder9.json, out/table_shoulder9.md, out/sheet_shoulder9_<id>.png, out/crop_shoulder9_worst.png,
out/crop_shoulder9_neck_40.png.
"""
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, "/tmp/warp-benchmark")
import mls as bm  # noqa: E402  (benchmark: metrics, composite)
import mls_fitted as mf  # noqa: E402

from apps.tryon_engine import mls as pm  # noqa: E402  (production module, benchmark keyword)
from apps.tryon_engine import warp  # noqa: E402

GARMENTS = [28, 43, 40]
# (name, shoulder_variant, fractions); C+line50/75 = without the 25 % pair (owner 2026-11-13: the V band kinked there)
VARIANTS = [("C", "off", None), ("C+line", "line", None), ("C+line50/75", "line", (0.5, 0.75))]
LINE = [v for v in VARIANTS if v[1] == "line"]
H, W = 1200, 600
OUT = "/tmp/warp_benchmark"
DATA = "/tmp/warp-benchmark/data/shoulder9"
ZOOM = 3
NECK_HOLE = os.environ.get("NECK_HOLE", "1") == "1"
os.makedirs(OUT, exist_ok=True)


def label(img, text, y=16, scale=0.42):
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(img, text, (6, y), cv2.FONT_HERSHEY_SIMPLEX, scale, col, th, cv2.LINE_AA)
    return img


def landed(q, p, mx, my, r=40):
    """Canvas point where garment point q lands: the px around p whose inverse map is closest to q."""
    x0, x1 = max(int(p[0]) - r, 0), min(int(p[0]) + r + 1, W)
    y0, y1 = max(int(p[1]) - r, 0), min(int(p[1]) + r + 1, H)
    d = (mx[y0:y1, x0:x1] - q[0]) ** 2 + (my[y0:y1, x0:x1] - q[1]) ** 2
    iy, ix = np.unravel_index(int(np.argmin(d)), d.shape)
    return (x0 + ix, y0 + iy), float(np.sqrt(d[iy, ix]))


def residuals(sample_pairs, mx, my):
    out = {}
    for name, (q, p, _) in sample_pairs.items():
        pt, miss = landed(q, p, mx, my)
        out[name] = {"landed": pt, "target": (round(p[0], 1), round(p[1], 1)),
                     "px": round(float(np.hypot(pt[0] - p[0], pt[1] - p[1])), 1), "map_miss": round(miss, 2)}
    return out


avatars = []
for pk in sorted(int(f[:-5]) for f in os.listdir(f"{DATA}/avatars") if f.endswith(".json")):
    with open(f"{DATA}/avatars/{pk}.json") as fh:
        d = json.load(fh)
    base = cv2.imread(f"{DATA}/avatars/{pk}.png", cv2.IMREAD_UNCHANGED)
    avatars.append((pk, f"{d['sex'][0]}-{d['build']}", d["landmarks"], base, warp.figure_mask(base)))

results, notes, worst = [], [], {}
neck_cells = []
for gid in GARMENTS:
    gimg = cv2.imread(f"{DATA}/garments/{gid}.png", cv2.IMREAD_UNCHANGED)
    with open(f"{DATA}/garments/{gid}.json") as fh:
        glm = json.load(fh)["landmarks"]
    poly = (glm.get("neck_hole") or {}).get("polygon") if NECK_HOLE else None
    hole_kw = {"neckline_variant": "hole", "neck_hole_polygon": poly} if poly else {}
    print(f"#{gid}: neckline {'hole (' + str(len(poly)) + ' points)' if poly else 'r7'}")
    rows = []
    for pk, who, blm, base, mask in avatars:
        runs = {}
        for name, sv, fr in VARIANTS:
            layer, info = pm.tshirt_layer(gimg, glm, blm, mask, "adapt", H, W, sleeve_variant="C", debug_map=True,
                                          shoulder_variant=sv, **({"shoulder_fractions": fr} if fr else {}),
                                          **hole_kw)
            runs[name] = (layer, info)
        c_info = runs["C"][1]
        quads = mf.arm_band_quads(c_info["pairs"], blm)
        boxes = mf.shoulder_top_boxes(c_info["pairs"], blm, quads)
        # the intended neckline hole is not "skin to cover": take the union of both variants' warped holes out of
        # the shoulder-top band (identical band for both variants)
        holes = [i.get("neck_weight") for _, i in runs.values() if i.get("neck_weight") is not None]
        if holes:
            hole_union = np.logical_or.reduce([w > 0 for w in holes])
            boxes = {sd: (None if b is None else b & ~hole_union) for sd, b in boxes.items()}
        line_info = runs["C+line"][1]
        report = line_info.get("shoulder_line", {})
        samples = {k: v for k, v in line_info["pairs"].items() if k.startswith("sline")}
        necks = {k: v for k, v in line_info["pairs"].items() if k in ("neck_l", "neck_r")}
        for side in ("left", "right"):
            rep = report.get(side, {})
            if rep.get("skipped"):
                notes.append(f"#{gid} {who} {side}: skipped ({rep['skipped']})")
            if rep.get("head_columns"):
                notes.append(f"#{gid} {who} {side}: head/hair at the neck row in columns {rep['head_columns']}")
            if rep.get("steep"):
                notes.append(f"#{gid} {who} {side}: near-vertical edge at {rep['steep']}")
        cells = []
        for name, _, _ in VARIANTS:
            layer, info = runs[name]
            mx, my = info["map"]
            cover = layer[:, :, 3] >= 128
            top = mf.shoulder_top_skin_px(layer, mask, boxes)
            above = {s: (None if b is None else int((b & cover & ~mask).sum())) for s, b in boxes.items()}
            band = mf.arm_band_skin_px(layer, mask, quads)
            cov = mf.coverage_metrics(layer, mask, info, blm)
            res = residuals(samples, mx, my)
            nres = residuals(necks, mx, my)
            rmax = {s: max([r["px"] for k, r in res.items() if k.endswith(sx)], default=None)
                    for s, sx in (("left", "_l"), ("right", "_r"))}
            rec = {"garment": gid, "avatar": pk, "who": who, "variant": name,
                   "shoulder_top_l": top["left"], "shoulder_top_r": top["right"], "shoulder_top": top["total"],
                   "above_l": above["left"], "above_r": above["right"],
                   "arm_band_l": band["left"], "arm_band_r": band["right"], "arm_band": band["total"],
                   "gap_px": cov["gap_px"], "excess_px": cov["excess_px"],
                   "fold": round(bm.metrics(layer, info, blm)["fold"], 5), "runtime_s": round(info["runtime"], 3),
                   "residual_max_l": rmax["left"], "residual_max_r": rmax["right"], "residuals": res,
                   "neck_residuals": nres, "collar_floor": info.get("collar_floor"),
                   "rejected": info["rejected"], "line_pairs": sorted(samples)}
            results.append(rec)
            print(json.dumps({k: v for k, v in rec.items() if k not in ("residuals", "neck_residuals")}, default=str))
            rgb = bm.composite(base, layer, blm, info)
            y0 = max(int(blm["neck"]["y"]) - 40, 0)
            y1 = min(int(blm["shoulder"]["y"]) + 70, H)
            crop = rgb[y0:y1].copy()
            for box in boxes.values():
                if box is not None:
                    cs, _ = cv2.findContours(box[y0:y1].astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    cv2.drawContours(crop, cs, -1, (200, 120, 40), 1)
            big = cv2.resize(crop, None, fx=ZOOM, fy=ZOOM, interpolation=cv2.INTER_NEAREST)
            for r in list(res.values()) + list(nres.values()):
                t = (int(round(r["target"][0] * ZOOM)), int(round((r["target"][1] - y0) * ZOOM)))
                g = (int(round(r["landed"][0] * ZOOM)), int(round((r["landed"][1] - y0) * ZOOM)))
                cv2.line(big, t, g, (255, 255, 255), 1, cv2.LINE_AA)
                cv2.circle(big, t, 4, (60, 200, 60), -1, cv2.LINE_AA)  # body target: green
                cv2.circle(big, g, 3, (220, 40, 220), -1, cv2.LINE_AA)  # garment point landed: magenta
            cells.append(label(big, f"{name} #{gid} {who} top {top['left']}/{top['right']} above "
                                    f"{above['left']}/{above['right']} res {rmax['left']}/{rmax['right']}"))
            if gid == 40:
                neck_cells.append((pk, name, big))
            if name != "C" and (name not in worst or top["total"] > worst[name][0]):
                worst[name] = (top["total"], gid, who, cells[0], big)
        hmax = max(c.shape[0] for c in cells)
        rows.append(np.hstack([np.pad(c, ((0, hmax - c.shape[0]), (0, 0), (0, 0)), constant_values=255)
                               for c in cells]))
    wmax = max(r.shape[1] for r in rows)
    cv2.imwrite(f"{OUT}/sheet_shoulder9_{gid}.png", np.vstack(
        [np.pad(r, ((0, 0), (0, wmax - r.shape[1]), (0, 0)), constant_values=255) for r in rows]))

for name, (n, gid, who, c_cell, l_cell) in worst.items():
    h = max(c_cell.shape[0], l_cell.shape[0])
    tag = "" if name == "C+line" else "_50_75"
    cv2.imwrite(f"{OUT}/crop_shoulder9_worst{tag}.png", label(np.hstack(
        [np.pad(c, ((0, h - c.shape[0]), (0, 0), (0, 0)), constant_values=255) for c in (c_cell, l_cell)]),
        f"worst {name} shoulder-top skin {n} px: #{gid} {who} (left C, right {name})", y=h - 10, scale=0.6))
# #40 neck crops, both variants: collar_floor vs the 25 % pair
rows = []
for pk in sorted({p for p, _, _ in neck_cells}):
    cs = [c for p, _, c in neck_cells if p == pk]
    cx = cs[0].shape[1] // 2
    rows.append(np.hstack([c[:, max(cx - 330, 0):cx + 330] for c in cs]))  # C | C+line | C+line50/75
cv2.imwrite(f"{OUT}/crop_shoulder9_neck_40.png", np.vstack(rows))

with open(f"{OUT}/results_shoulder9.json", "w") as fh:
    json.dump({"runs": results, "notes": notes}, fh, default=str, indent=1)

# ---------- table ----------
METRICS = [("shoulder_top_l", "top L"), ("shoulder_top_r", "top R"), ("above_l", "above L"), ("above_r", "above R"),
           ("arm_band_l", "arm L"), ("arm_band_r", "arm R"), ("gap_px", "gap"), ("excess_px", "excess"),
           ("fold", "fold"), ("residual_max_l", "res L"), ("residual_max_r", "res R")]
by = {(r["garment"], r["avatar"], r["variant"]): r for r in results}
lines = ["| variant | shoulder-top skin L / R (sum) | above shoulder L / R (sum) | arm-band skin L / R (sum) | "
         "gap (sum) | excess (sum) | fold (max) | line residual px L / R (max) | runtime s (max) |",
         "|---|---|---|---|---|---|---|---|---|"]
for name, _, _ in VARIANTS:
    rs = [r for r in results if r["variant"] == name]
    s = lambda k: sum(r[k] or 0 for r in rs)  # noqa: E731
    mxv = lambda k: max((r[k] for r in rs if r[k] is not None), default=None)  # noqa: E731
    lines.append(f"| {name} | {s('shoulder_top_l')} / {s('shoulder_top_r')} | {s('above_l')} / {s('above_r')} | "
                 f"{s('arm_band_l')} / {s('arm_band_r')} | {s('gap_px')} | {s('excess_px')} | {mxv('fold'):.5f} | "
                 f"{mxv('residual_max_l')} / {mxv('residual_max_r')} | {mxv('runtime_s')} |")
lines += ["", "| garment | avatar | variant | top L / R | above L / R | arm L / R | gap | excess | fold | "
          "res L / R | neck_l / neck_r residual | collar_floor | runtime s | dropped |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
for r in results:
    nr = r["neck_residuals"]
    lines.append(f"| #{r['garment']} | {r['who']} | {r['variant']} | {r['shoulder_top_l']} / {r['shoulder_top_r']} | "
                 f"{r['above_l']} / {r['above_r']} | {r['arm_band_l']} / {r['arm_band_r']} | {r['gap_px']} | "
                 f"{r['excess_px']} | {r['fold']:.4f} | {r['residual_max_l']} / {r['residual_max_r']} | "
                 f"{nr.get('neck_l', {}).get('px')} / {nr.get('neck_r', {}).get('px')} | {r['collar_floor']} | "
                 f"{r['runtime_s']} | {', '.join(r['rejected']) or '-'} |")
worse = []
for vname, _, _ in LINE:
    part = []
    for gid in GARMENTS:
        for pk, who, *_ in avatars:
            c, ln = by[(gid, pk, "C")], by[(gid, pk, vname)]
            bad = [f"{lab} {c[k]} -> {ln[k]}" for k, lab in METRICS
                   if c[k] is not None and ln[k] is not None and ln[k] > c[k]]
            if bad:
                part.append(f"- #{gid} {who}: {'; '.join(bad)}")
    lines += ["", f"{vname} worse than C (any metric but runtime): {len(part)} / {len(GARMENTS) * len(avatars)} runs"]
    lines += part or ["- none"]
    worse += part
lines += ["", "Sampling notes:"] + ([f"- {n}" for n in notes] or ["- none"])
with open(f"{OUT}/table_shoulder9.md", "w") as fh:
    fh.write("\n".join(lines) + "\n")
print("\n".join(lines[2:2 + len(VARIANTS)]))
print(f"notes: {len(notes)}")
