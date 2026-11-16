"""MLS benchmark round 16: the faint line along the tube's inner edge (docs/06 "Tube fringe, round 16", NOT production).

    docker compose exec -T backend rm -rf /tmp/warp-benchmark /tmp/warp_benchmark
    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T [-e SHEETS=0] backend python manage.py shell < tools/warp-benchmark/run_fringe16.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

#28, #43, #40 x 6 avatars, adapt; base = the production config (docs/09 #105) + cuff_mode "hem" (round 15).
Columns: current (tube_fringe "keep") | fixed (tube_fringe "drop").
Metrics: fringe px = tube px whose source lies within HALO_ERODE body px of the garment's alpha edge and that lie
over solid MLS fabric (`info["tube"]["fringe_zone"]`, the px tube_fringe "drop" does not draw); line px = fringe px
at least 4 px inside the final garment contour whose grey value differs between the columns by more than
TUBE_FRINGE_VISIBLE (the fixed column shows the MLS fabric there), L / R, and the largest difference; new holes =
figure px current covers and fixed does not; changed outside = px that differ between the columns farther than
3 px from a fringe px (fully transparent px in both columns are not compared).
GATE (fixed): new holes = 0, changed outside = 0.
Writes out/table_fringe16.md, out/results_fringe16.json, out/sheet_fringe16_<id>.png (per avatar: current L | R,
fixed L | R, 4x crops at the middle of the tube's inner edge, clean). Exit status 1 when the gate fails.
"""
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, "/tmp/warp-benchmark")
import mls as bm  # noqa: E402

from apps.tryon_engine import mls as pm  # noqa: E402
from apps.tryon_engine import warp  # noqa: E402

GARMENTS = [28, 43, 40]
BASE = {"sleeve_variant": "C", "side_floor": True, "side_floor_mode": "mask", "hem_mode": "garment",
        "sleeve_mode": "tube", "tube_arm": "finished", "armpit_mode": "r14", "cuff_mode": "hem"}
H, W = 1200, 600
OUT = "/tmp/warp_benchmark"
DATA = "/tmp/warp-benchmark/data/side12"
CROP, ZOOM = 30, 4
SHEETS = os.environ.get("SHEETS", "1") == "1"
os.makedirs(OUT, exist_ok=True)


def label(img, text, y=14, scale=0.4):
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(img, text, (4, y), cv2.FONT_HERSHEY_SIMPLEX, scale, col, th, cv2.LINE_AA)
    return img


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
    crop_rows = []
    for pk, who, blm, base, mask in avatars:
        cur, ci = pm.tshirt_layer(gimg, glm, blm, mask, "adapt", H, W, tube_fringe="keep", **BASE, **hole_kw)
        fix, fi = pm.tshirt_layer(gimg, glm, blm, mask, "adapt", H, W, tube_fringe="drop", **BASE, **hole_kw)
        F = ci["tube"]["fringe_zone"]
        inner = cv2.erode((cur[:, :, 3] >= 128).astype(np.uint8),
                          cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))) > 0
        dg = np.abs(cur[:, :, :3].astype(np.float32).mean(2) - fix[:, :, :3].astype(np.float32).mean(2))
        line = F & inner & (dg > pm.TUBE_FRINGE_VISIBLE)
        c0, c1 = cur[:, :, 3] >= 128, fix[:, :, 3] >= 128
        changed = (cur != fix).any(2) & ((cur[:, :, 3] > 0) | (fix[:, :, 3] > 0))  # hidden RGB under alpha 0: not a change
        fr_zone = cv2.dilate(F.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
        rec = {"garment": gid, "avatar": pk, "who": who, "fringe_px": ci["tube"]["fringe_px"],
               "line_px": [int(line[:, :300].sum()), int(line[:, 300:].sum())],
               "line_max_grey": round(float(dg[line].max()), 1) if line.any() else 0.0,
               "new_holes": int((mask & c0 & ~c1).sum()), "changed": int(changed.sum()),
               "changed_outside": int((changed & ~fr_zone).sum()),
               "runtime": [round(ci["runtime"], 3), round(fi["runtime"], 3)]}
        bad = []
        if rec["new_holes"]:
            bad.append(f"new holes {rec['new_holes']}")
        if rec["changed_outside"]:
            bad.append(f"changed outside {rec['changed_outside']}")
        if bad:
            fails.append(f"#{gid} {who}: " + ", ".join(bad))
        results.append(rec)
        print(json.dumps(rec))
        if not SHEETS:
            continue
        rgb = {"current": bm.composite(base, cur, blm, ci), "fixed": bm.composite(base, fix, blm, fi)}
        cells = []
        for name in ("current", "fixed"):
            for i, side in enumerate(("left", "right")):
                t = ci["tube"][side]
                c = (np.asarray(t["armhole_body"][1]) + np.asarray(t["cuff"][1])) / 2
                v = rec["line_px"][i] if name == "current" else 0
                cells.append(label(crop(rgb[name], c), f"{name} {side[0].upper()} #{gid} {who} line {v}"))
        crop_rows.append(np.hstack(cells))
    if SHEETS:
        cv2.imwrite(f"{OUT}/sheet_fringe16_{gid}.png", np.vstack(crop_rows))
with open(f"{OUT}/results_fringe16.json", "w") as fh:
    json.dump({"runs": results, "fails": fails}, fh, indent=1)

pr = lambda v: f"{v[0]} / {v[1]}"  # noqa: E731
lines = ["| garment | avatar | fringe px over fabric | line px L / R (current; fixed 0) | max grey difference | "
         "new holes | px changed | changed outside | runtime s current / fixed |", "|" + "---|" * 9]
for r in results:
    lines.append(f"| #{r['garment']} | {r['who']} | {r['fringe_px']} | {pr(r['line_px'])} | {r['line_max_grey']} | "
                 f"{r['new_holes']} | {r['changed']} | {r['changed_outside']} | {pr(r['runtime'])} |")
lines += ["", f"Totals: fringe px {sum(r['fringe_px'] for r in results)}; line px "
              f"{sum(r['line_px'][0] for r in results)} / {sum(r['line_px'][1] for r in results)} (fixed 0 / 0); new holes "
              f"{sum(r['new_holes'] for r in results)}; changed outside {sum(r['changed_outside'] for r in results)}; "
              f"runtime mean {sum(r['runtime'][0] for r in results) / len(results):.3f} / "
              f"{sum(r['runtime'][1] for r in results) / len(results):.3f} s",
          "", f"GATE (fixed: new holes 0, changed outside 0): {len(fails)} / {len(results)} runs fail"]
lines += [f"- {f}" for f in fails]
with open(f"{OUT}/table_fringe16.md", "w") as fh:
    fh.write("\n".join(lines) + "\n")
print("\n".join(lines))
if fails:
    sys.exit(1)
