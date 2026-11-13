"""MLS benchmark round 9b: shoulder line with the garment edge at the HARD_EDGE alpha (docs/06 "Shoulder line fit,
round 9", NOT production). Same data and setup as run_shoulder9.py (data/shoulder9/, sleeve C, collar_floor on,
side_floor off, production neckline: #40's polygon -> hole in every variant, no neck_clip; NECK_HOLE=0 -> r7 neckline
for every garment, no hole).

    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/run_shoulder9b.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

Variants (all full line, 25 / 50 / 75 %): C (reference, line off), C+line (alpha > 128, ease 2 px),
line_hard2 (garment edge = first row with alpha >= HARD_EDGE, ease 2 px), line_hard4 (the same, ease 4 px).
shoulder_top_skin_px is split: edge_skin = uncovered figure px within EDGE_BAND px below the body's top edge (first
background -> figure step under the neck row, per column: the thin line along the shoulder), inner_skin = the rest
of the band (neck-side skin near the opening). Bands are the C run's, minus the union of the warped holes. Residual:
each line variant on its OWN line pairs (C on C+line's). #40: the pairs that compete with the line pairs are listed
(neck, shoulder, smid, cuff_mid, cuff corners; collar_floor raise) with their garment / body positions and, per line
pair, the pair whose target-to-garment stretch differs most from the global scale s; drawn on #40's sheet (orange).
Writes out/table_shoulder9b.md, out/results_shoulder9b.json, out/sheet_shoulder9b_<id>.png.
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
LINE = {"shoulder_variant": "line"}
VARIANTS = [("C", {}), ("C+line", dict(LINE)),
            ("line_hard2", dict(LINE, shoulder_edge_alpha=pm.HARD_EDGE - 1, shoulder_ease=2)),
            ("line_hard4", dict(LINE, shoulder_edge_alpha=pm.HARD_EDGE - 1, shoulder_ease=4))]
H, W = 1200, 600
OUT = "/tmp/warp_benchmark"
DATA = "/tmp/warp-benchmark/data/shoulder9"
ZOOM = 3
EDGE_BAND = 4
COMPETE = ("neck", "shoulder", "smid", "cuff_mid", "cuff_out", "cuff_in")
NECK_HOLE = os.environ.get("NECK_HOLE", "1") == "1"  # 0 = r7 neckline for every garment (no polygon hole)
CLEAN = os.environ.get("CLEAN", "0") == "1"  # 1 = sheets as the user sees the result: no bands, dots or pair names
os.makedirs(OUT, exist_ok=True)


def label(img, text, y=16, scale=0.42):
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(img, text, (6, y), cv2.FONT_HERSHEY_SIMPLEX, scale, col, th, cv2.LINE_AA)
    return img


def landed(q, p, mx, my, r=40):
    x0, x1 = max(int(p[0]) - r, 0), min(int(p[0]) + r + 1, W)
    y0, y1 = max(int(p[1]) - r, 0), min(int(p[1]) + r + 1, H)
    d = (mx[y0:y1, x0:x1] - q[0]) ** 2 + (my[y0:y1, x0:x1] - q[1]) ** 2
    iy, ix = np.unravel_index(int(np.argmin(d)), d.shape)
    return (x0 + ix, y0 + iy)


def residuals(sample_pairs, mx, my):
    out = {}
    for name, (q, p, _) in sample_pairs.items():
        pt = landed(q, p, mx, my)
        out[name] = {"landed": pt, "target": (round(p[0], 1), round(p[1], 1)),
                     "px": round(float(np.hypot(pt[0] - p[0], pt[1] - p[1])), 1)}
    return out


def edge_band(mask, blm):
    """Figure px within EDGE_BAND px below the body's top edge (first bg -> fig step under the neck row)."""
    y_neck = max(int(round(float(blm["neck"]["y"]))), 0)
    out = np.zeros_like(mask, bool)
    sub = mask[y_neck:].astype(bool)
    steps = ~sub[:-1] & sub[1:]
    has = steps.any(0)
    first = np.argmax(steps, 0) + 1 + y_neck
    for x in np.nonzero(has)[0]:
        out[first[x]:first[x] + EDGE_BAND, x] = True
    return out & mask


def competitors(pairs, s):
    """Per line pair: the other pair (COMPETE groups) whose stretch |dp| / (s |dq|) is furthest from 1."""
    lines = {k: v for k, v in pairs.items() if k.startswith("sline")}
    others = {k: v for k, v in pairs.items() if k.startswith(COMPETE)}
    out = {}
    for k, (q, p, _) in lines.items():
        best = None
        for o, (qo, po, _) in others.items():
            dq = float(np.hypot(q[0] - qo[0], q[1] - qo[1])) * s
            if dq < 1:
                continue
            ratio = float(np.hypot(p[0] - po[0], p[1] - po[1])) / dq
            if best is None or abs(np.log(ratio)) > abs(np.log(best[1])):
                best = (o, ratio, round(dq, 1))
        out[k] = {"pair": best[0], "stretch": round(best[1], 2), "garment_dist_px": best[2]} if best else None
    return out


avatars = []
for pk in sorted(int(f[:-5]) for f in os.listdir(f"{DATA}/avatars") if f.endswith(".json")):
    with open(f"{DATA}/avatars/{pk}.json") as fh:
        d = json.load(fh)
    base = cv2.imread(f"{DATA}/avatars/{pk}.png", cv2.IMREAD_UNCHANGED)
    avatars.append((pk, f"{d['sex'][0]}-{d['build']}", d["landmarks"], base, warp.figure_mask(base)))

results, notes, compete40 = [], [], []
for gid in GARMENTS:
    gimg = cv2.imread(f"{DATA}/garments/{gid}.png", cv2.IMREAD_UNCHANGED)
    with open(f"{DATA}/garments/{gid}.json") as fh:
        glm = json.load(fh)["landmarks"]
    poly = (glm.get("neck_hole") or {}).get("polygon") if NECK_HOLE else None
    hole_kw = {"neckline_variant": "hole", "neck_hole_polygon": poly} if poly else {}
    rows = []
    for pk, who, blm, base, mask in avatars:
        runs = {name: pm.tshirt_layer(gimg, glm, blm, mask, "adapt", H, W, sleeve_variant="C", debug_map=True,
                                      **kw, **hole_kw) for name, kw in VARIANTS}
        c_info = runs["C"][1]
        quads = mf.arm_band_quads(c_info["pairs"], blm)
        boxes = mf.shoulder_top_boxes(c_info["pairs"], blm, quads)
        holes = [i.get("neck_weight") for _, i in runs.values() if i.get("neck_weight") is not None]
        if holes:
            hu = np.logical_or.reduce([w > 0 for w in holes])
            boxes = {sd: (None if b is None else b & ~hu) for sd, b in boxes.items()}
        eb = edge_band(mask, blm)
        ref_samples = {k: v for k, v in runs["C+line"][1]["pairs"].items() if k.startswith("sline")}
        for name, _ in VARIANTS[1:]:
            for side, rep in runs[name][1].get("shoulder_line", {}).items():
                for key, txt in (("skipped", "skipped"), ("head_columns", "head/hair columns"), ("steep", "steep")):
                    if rep.get(key):
                        notes.append(f"#{gid} {who} {name} {side}: {txt} {rep[key]}")
        cells = []
        for name, _ in VARIANTS:
            layer, info = runs[name]
            mx, my = info["map"]
            cover = layer[:, :, 3] >= 128
            unc = mask & ~cover
            edge = {sd: (None if b is None else int((b & eb & unc).sum())) for sd, b in boxes.items()}
            inner = {sd: (None if b is None else int((b & ~eb & unc).sum())) for sd, b in boxes.items()}
            above = {sd: (None if b is None else int((b & cover & ~mask).sum())) for sd, b in boxes.items()}
            band = mf.arm_band_skin_px(layer, mask, quads)
            cov = mf.coverage_metrics(layer, mask, info, blm)
            own = {k: v for k, v in info["pairs"].items() if k.startswith("sline")} or ref_samples
            res = residuals(own, mx, my)
            rmax = {sd: max([r["px"] for k, r in res.items() if k.endswith(sx)], default=None)
                    for sd, sx in (("left", "_l"), ("right", "_r"))}
            rec = {"garment": gid, "avatar": pk, "who": who, "variant": name,
                   "edge_l": edge["left"], "edge_r": edge["right"], "inner_l": inner["left"], "inner_r": inner["right"],
                   "above_l": above["left"], "above_r": above["right"],
                   "arm_band_l": band["left"], "arm_band_r": band["right"],
                   "gap_px": cov["gap_px"], "excess_px": cov["excess_px"],
                   "fold": round(bm.metrics(layer, info, blm)["fold"], 5), "runtime_s": round(info["runtime"], 3),
                   "residual_max_l": rmax["left"], "residual_max_r": rmax["right"], "residuals": res,
                   "collar_floor": info.get("collar_floor"), "rejected": info["rejected"]}
            if gid == 40 and name != "C":
                listed = {k: {"q": [round(c, 1) for c in v[0]], "p": [round(c, 1) for c in v[1]], "w": v[2]}
                          for k, v in sorted(info["pairs"].items()) if k.startswith(COMPETE + ("sline",))}
                rec["pairs_40"] = listed
                rec["competitors"] = competitors(info["pairs"], info["s"])
                compete40.append(rec)
            results.append(rec)
            rgb = bm.composite(base, layer, blm, info)
            y0 = max(int(blm["neck"]["y"]) - 40, 0)
            y1 = min(int(blm["shoulder"]["y"]) + 70, H)
            crop = rgb[y0:y1].copy()
            for box in ([] if CLEAN else boxes.values()):
                if box is not None:
                    cs, _ = cv2.findContours(box[y0:y1].astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    cv2.drawContours(crop, cs, -1, (200, 120, 40), 1)
            big = cv2.resize(crop, None, fx=ZOOM, fy=ZOOM, interpolation=cv2.INTER_NEAREST)
            if gid == 40 and not CLEAN:  # competing pairs: orange target dot + short name
                for k, (q, p, _) in info["pairs"].items():
                    if k.startswith(COMPETE) and y0 <= p[1] < y1:
                        t = (int(round(p[0] * ZOOM)), int(round((p[1] - y0) * ZOOM)))
                        cv2.circle(big, t, 5, (0, 140, 255), -1, cv2.LINE_AA)
                        cv2.putText(big, k, (t[0] + 6, t[1] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 90, 200), 1,
                                    cv2.LINE_AA)
            for r in ([] if CLEAN else res.values()):
                t = (int(round(r["target"][0] * ZOOM)), int(round((r["target"][1] - y0) * ZOOM)))
                g = (int(round(r["landed"][0] * ZOOM)), int(round((r["landed"][1] - y0) * ZOOM)))
                cv2.line(big, t, g, (255, 255, 255), 1, cv2.LINE_AA)
                cv2.circle(big, t, 4, (60, 200, 60), -1, cv2.LINE_AA)
                cv2.circle(big, g, 3, (220, 40, 220), -1, cv2.LINE_AA)
            cells.append(label(big, f"{name} #{gid} {who}") if CLEAN else label(big, f"{name} #{gid} {who} edge {edge['left']}/{edge['right']} inner "
                                    f"{inner['left']}/{inner['right']} above {above['left']}/{above['right']} "
                                    f"res {rmax['left']}/{rmax['right']}", scale=0.38))
        hmax = max(c.shape[0] for c in cells)
        rows.append(np.hstack([np.pad(c, ((0, hmax - c.shape[0]), (0, 0), (0, 0)), constant_values=255)
                               for c in cells]))
    wmax = max(r.shape[1] for r in rows)
    cv2.imwrite(f"{OUT}/sheet_shoulder9b_{gid}.png", np.vstack(
        [np.pad(r, ((0, 0), (0, wmax - r.shape[1]), (0, 0)), constant_values=255) for r in rows]))

with open(f"{OUT}/results_shoulder9b.json", "w") as fh:
    json.dump({"runs": results, "notes": notes}, fh, default=str, indent=1)

# ---------- table ----------
lines = ["| garment | variant | edge skin L / R | inner skin L / R | above shoulder L / R | arm-band skin L / R | gap | "
         "excess | fold (max) | line residual max L / R | runtime s (max) |", "|---|---|---|---|---|---|---|---|---|---|---|"]
for gid in GARMENTS + ["all"]:
    for name, _ in VARIANTS:
        rs = [r for r in results if r["variant"] == name and (gid == "all" or r["garment"] == gid)]
        s = lambda k: sum(r[k] or 0 for r in rs)  # noqa: E731
        m = lambda k: max((r[k] for r in rs if r[k] is not None), default=0)  # noqa: E731
        g = f"#{gid}" if gid != "all" else "all"
        lines.append(f"| {g} | {name} | {s('edge_l')} / {s('edge_r')} | {s('inner_l')} / {s('inner_r')} | "
                     f"{s('above_l')} / {s('above_r')} | {s('arm_band_l')} / {s('arm_band_r')} | {s('gap_px')} | "
                     f"{s('excess_px')} | {m('fold'):.5f} | {m('residual_max_l')} / {m('residual_max_r')} | "
                     f"{m('runtime_s')} |")
lines += ["", "| garment | avatar | variant | edge L / R | inner L / R | above L / R | arm L / R | gap | excess | fold | "
          "res L / R | runtime s |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
for r in results:
    lines.append(f"| #{r['garment']} | {r['who']} | {r['variant']} | {r['edge_l']} / {r['edge_r']} | {r['inner_l']} / "
                 f"{r['inner_r']} | {r['above_l']} / {r['above_r']} | {r['arm_band_l']} / {r['arm_band_r']} | "
                 f"{r['gap_px']} | {r['excess_px']} | {r['fold']:.4f} | {r['residual_max_l']} / {r['residual_max_r']} | "
                 f"{r['runtime_s']} |")
METRICS = [("edge_l", "edge L"), ("edge_r", "edge R"), ("inner_l", "inner L"), ("inner_r", "inner R"),
           ("above_l", "above L"), ("above_r", "above R"), ("arm_band_l", "arm L"), ("arm_band_r", "arm R"),
           ("gap_px", "gap"), ("excess_px", "excess"), ("fold", "fold")]
by = {(r["garment"], r["avatar"], r["variant"]): r for r in results}
for name, _ in VARIANTS[1:]:
    part = []
    for gid in GARMENTS:
        for pk, who, *_ in avatars:
            c, v = by[(gid, pk, "C")], by[(gid, pk, name)]
            bad = [f"{lab} {c[k]} -> {v[k]}" for k, lab in METRICS if c[k] is not None and v[k] is not None and v[k] > c[k]]
            if bad:
                part.append(f"- #{gid} {who}: {'; '.join(bad)}")
    lines += ["", f"{name} worse than C (any metric but runtime): {len(part)} / {len(GARMENTS) * len(avatars)} runs"]
    lines += part or ["- none"]
lines += ["", "#40: pairs competing with the line pairs (C+line, line_hard2, line_hard4). Per line pair: the listed "
          "pair whose stretch |dp| / (s |dq|) is furthest from 1 (garment distance in canvas px).", ""]
for r in compete40:
    comp = "; ".join(f"{k}: {v['pair']} x{v['stretch']} @ {v['garment_dist_px']} px" for k, v in sorted(r["competitors"].items())
                     if v)
    lines.append(f"- {r['variant']} {r['who']} (res {r['residual_max_l']} / {r['residual_max_r']}, collar_floor "
                 f"{r['collar_floor'] or '{}'}): {comp}")
lines += ["", "#40 pair positions (garment q -> body p), C+line, first avatar:", ""]
first = next(r for r in compete40 if r["variant"] == "C+line")
for k, v in first["pairs_40"].items():
    lines.append(f"- {k}: q {v['q']} -> p {v['p']} (w {v['w']})")
lines += ["", "Sampling notes:"] + ([f"- {n}" for n in notes] or ["- none"])
with open(f"{OUT}/table_shoulder9b.md", "w") as fh:
    fh.write("\n".join(lines) + "\n")
print("\n".join(lines[:2 + 4 * (len(GARMENTS) + 1)]))
