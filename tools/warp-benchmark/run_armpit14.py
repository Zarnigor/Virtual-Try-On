"""MLS benchmark round 14: the open armpit wedge, geometric fix (docs/06 "Armpit wedge, round 14", NOT production).

    docker compose exec -T backend rm -rf /tmp/warp-benchmark /tmp/warp_benchmark
    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T [-e SHEETS=0] backend python manage.py shell < tools/warp-benchmark/run_armpit14.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

#28, #43, #40 x 6 avatars, adapt; base: sleeve C + side_floor "mask" + hem "garment" + collar_floor + the neck_hole
polygon + tube "finished". Columns: current (armpit_mode "off" = round 13b) | fixed (armpit_mode "r14"). The 13c
column of the first run (armpit_mode "r13c") was deleted with round 13c (docs/09 #105); its numbers are in docs/06.
Metrics (engine helpers `mls.armpit_wedge`, `mls.armpit_ragged`, independent of the tube's zones):
- wedge L / R: open figure px on the torso side of the arm/torso boundary (<= 25 px from it, armpit row -> crease
  + 2) plus arm px above the layer's own cuff line (<= 12 px from the boundary); arm skin below the cuff: never.
- ragged L / R: fragment px (garment px not connected to the main piece) / spike px (removed by a 5 px opening) in
  the armpit box.
- new holes: figure px the current column covers and this column does not (whole canvas), except arm skin at or
  below the current cuff line (arm px from 2 px above the line down, = the wedge metric's margin), reported apart
  as "+ arm": the current column covers that skin with leftover fabric, the fixed column cuts it on the boundary.
- arm covered below cuff: arm px more than 1 px below this column's cuff line that it covers and current does not
  (the px row on the line itself is not counted).
- neck: px that differ from current above the armpit row between the shoulders' inner 40 %.
GATE (fixed): wedge <= 5 per side, fragment px = 0, new holes = 0. Spike px are reported (sides above current are
listed), not gated: the garment's own wavy sleeve hem gives spike px in every column.
Writes out/table_armpit14.md, out/results_armpit14.json, out/sheet_armpit14_<id>.png (per avatar: current L | R,
fixed L | R, 3x armpit crops, clean), out/sheet_armpit14_full_<id>.png (per avatar: current | fixed,
the whole T-shirt, 3x). Exit status 1 when the gate fails.
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
        "sleeve_mode": "tube", "tube_arm": "finished"}
VARIANTS = [("current", "off"), ("fixed", "r14")]
H, W = 1200, 600
OUT = "/tmp/warp_benchmark"
DATA = "/tmp/warp-benchmark/data/side12"
CROP, ZOOM, GATE_PX = 40, 3, 5
SHEETS = os.environ.get("SHEETS", "1") == "1"
OVERLAY = os.environ.get("OVERLAY", "0") == "1"  # debug sheets: wedge px red, px lost vs current yellow
os.makedirs(OUT, exist_ok=True)
Yg, Xg = np.mgrid[0:H, 0:W]


def label(img, text, y=14, scale=0.4):
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(img, text, (4, y), cv2.FONT_HERSHEY_SIMPLEX, scale, col, th, cv2.LINE_AA)
    return img


def crop(img, c):
    x, y = int(round(c[0])), int(round(c[1]))
    x0, y0 = min(max(x - CROP, 0), W - 2 * CROP), min(max(y - CROP, 0), H - 2 * CROP)
    return cv2.resize(img[y0:y0 + 2 * CROP, x0:x0 + 2 * CROP], None, fx=ZOOM, fy=ZOOM, interpolation=cv2.INTER_NEAREST)


def arm_below_cuff(mask, blm, arms, hems, margin=0.0):
    """Arm px (touch rows: arm side of the boundary; separated rows: find_arms) below the cuff line (margin > 0:
    and up to that many px above it)."""
    out = np.zeros((H, W), bool)
    for side in ("left", "right"):
        if side not in hems:
            continue
        arm = np.zeros((H, W), bool)
        rows, crease = pm.arm_torso_boundary(mask, blm, side)
        for y, e in rows.items():
            arm[y] = mask[y] & ((Xg[y] < e) if side == "left" else (Xg[y] >= e))
        for y, l, r in (arms.get(side) or {}).get("rows", []):
            arm[y, l:r + 1] = True
        a, b, sh = (np.asarray(v, float) for v in hems[side])
        n = np.array([-(b - a)[1], (b - a)[0]])
        if (sh - a) @ n > 0:
            n = -n
        n = n / max(float(np.linalg.norm(n)), 1e-9)
        out |= arm & (((Xg - a[0]) * n[0] + (Yg - a[1]) * n[1]) > -margin)
    return out


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
    crop_rows, full_rows = [], []
    for pk, who, blm, base, mask in avatars:
        arms = warp.find_arms(mask, blm)
        runs = {n: pm.tshirt_layer(gimg, glm, blm, mask, "adapt", H, W, armpit_mode=m, **BASE, **hole_kw)
                for n, m in VARIANTS}
        c0 = runs["current"][0][:, :, 3] >= 128
        below0 = arm_below_cuff(mask, blm, arms, runs["current"][1]["sleeve_hems"], pm.WEDGE_CUFF_MARGIN)
        sl, sr = float(blm["shoulder"]["left_x"]), float(blm["shoulder"]["right_x"])
        neck = (Yg < float(blm["armpit"]["y"])) & (Xg > sl + 0.3 * (sr - sl)) & (Xg < sr - 0.3 * (sr - sl))
        rec = {"garment": gid, "avatar": pk, "who": who}
        for name, _ in VARIANTS:
            layer, info = runs[name]
            c = layer[:, :, 3] >= 128
            wd = pm.armpit_wedge(layer, mask, blm, info["sleeve_hems"])
            rg = pm.armpit_ragged(layer, mask, blm)
            lost = mask & c0 & ~c
            rec[name] = {
                "wedge": [wd["left"]["px"], wd["right"]["px"]],
                "wedge_torso": [wd["left"]["torso_px"], wd["right"]["torso_px"]],
                "wedge_arm": [wd["left"]["arm_px"], wd["right"]["arm_px"]],
                "wedge_arm_h": [wd["left"]["arm_max_above_cuff"], wd["right"]["arm_max_above_cuff"]],
                "guard_px": (info.get("armpit") or {}).get("guard_px"),
                "fragment": [rg["left"]["fragment_px"], rg["right"]["fragment_px"]],
                "spike": [rg["left"]["spike_px"], rg["right"]["spike_px"]],
                "new_holes": int(lost.sum()), "new_holes_arm_below_cuff": int((lost & below0).sum()),
                "arm_covered_below_cuff": int((c & ~c0 & arm_below_cuff(mask, blm, arms, info["sleeve_hems"], -1.0)).sum()),
                "neck_diff": int(((layer != runs["current"][0]).any(2) & neck).sum()),
                "runtime": round(info["runtime"], 3),
                "notes": [r for r in info["rejected"] if "armpit r14" in r or r.startswith("apit")],
                "armpit_rows": {s: len(v.get("rows", [])) for s, v in (info.get("armpit") or {}).items()
                                if isinstance(v, dict)},
                "patched": (info.get("side_floor_mask") or {}).get("patched_px"),
            }
        f, cur = rec["fixed"], rec["current"]
        bad = [f"wedge {s} {f['wedge'][i]}" for i, s in enumerate("LR") if f["wedge"][i] > GATE_PX]
        bad += [f"fragments {s} {f['fragment'][i]}" for i, s in enumerate("LR") if f["fragment"][i] > 0]
        rec["spikes_above_current"] = [max(f["spike"][i] - cur["spike"][i], 0) for i in range(2)]
        if f["new_holes"] - f["new_holes_arm_below_cuff"]:
            bad.append(f"new holes {f['new_holes'] - f['new_holes_arm_below_cuff']}")
        if bad:
            fails.append(f"#{gid} {who}: " + ", ".join(bad))
        results.append(rec)
        print(json.dumps(rec, default=str))
        if not SHEETS:
            continue
        rgb = {n: bm.composite(base, runs[n][0], blm, runs[n][1]) for n, _ in VARIANTS}
        if OVERLAY:  # debug: wedge px red, px lost vs current yellow
            for n, _ in VARIANTS:
                wd = pm.armpit_wedge(runs[n][0], mask, blm, runs[n][1]["sleeve_hems"])
                rgb[n][wd["left"]["map"] | wd["right"]["map"]] = (0, 0, 255)
                rgb[n][mask & c0 & ~(runs[n][0][:, :, 3] >= 128)] = (0, 255, 255)
        cells = []
        for name, _ in VARIANTS:
            for side in ("left", "right"):
                rows, crease = pm.arm_torso_boundary(mask, blm, side)
                c = (crease[0], crease[1] - 12) if crease else (float(blm["armpit"][f"{side}_x"]),
                                                               float(blm["armpit"]["y"]) + 20)
                i = 0 if side == "left" else 1
                cells.append(label(crop(rgb[name], c), f"{name} {side[0].upper()} #{gid} {who} w{rec[name]['wedge'][i]}"))
        crop_rows.append(np.hstack(cells))
        fy0 = max(int(blm["neck"]["y"]) - 30, 0)
        fy1 = min(int(runs["current"][1]["pairs"]["hem_l"][1][1]) + 40, H)
        fx0, fx1 = 90, 510
        full_rows.append(np.hstack([label(cv2.resize(rgb[n][fy0:fy1, fx0:fx1], None, fx=3, fy=3,
                                                     interpolation=cv2.INTER_NEAREST),
                                          f"{n} #{gid} {who}", y=24, scale=0.7) for n, _ in VARIANTS]))
    if SHEETS:
        cv2.imwrite(f"{OUT}/sheet_armpit14_{gid}.png", np.vstack(crop_rows))
        w = max(r.shape[1] for r in full_rows)
        cv2.imwrite(f"{OUT}/sheet_armpit14_full_{gid}.png", np.vstack(
            [np.pad(r, ((0, 0), (0, w - r.shape[1]), (0, 0)), constant_values=255) for r in full_rows]))
with open(f"{OUT}/results_armpit14.json", "w") as fh:
    json.dump({"runs": results, "fails": fails}, fh, indent=1, default=str)

pr = lambda v: f"{v[0]} / {v[1]}"  # noqa: E731
lines = ["| garment | avatar | wedge L / R current | fixed | fragments L / R current | fixed | "
         "spikes L / R current | fixed | new holes fixed (+ arm skin below the cuff, uncovered) | "
         "arm covered below cuff fixed | neck diff fixed | runtime s current / fixed |", "|" + "---|" * 12]
for r in results:
    c, f = r["current"], r["fixed"]
    lines.append(f"| #{r['garment']} | {r['who']} | {pr(c['wedge'])} | {pr(f['wedge'])} | "
                 f"{pr(c['fragment'])} | {pr(f['fragment'])} | {pr(c['spike'])} | "
                 f"{pr(f['spike'])} | {f['new_holes'] - f['new_holes_arm_below_cuff']} "
                 f"(+ {f['new_holes_arm_below_cuff']} arm) | "
                 f"{f['arm_covered_below_cuff']} | {f['neck_diff']} | {c['runtime']} / {f['runtime']} |")
tot = lambda n, k, i: sum(r[n][k][i] for r in results)  # noqa: E731
for n, _ in VARIANTS:
    lines.append("")
    lines.append(f"Totals {n}: wedge {tot(n, 'wedge', 0)} / {tot(n, 'wedge', 1)} (torso side "
                 f"{tot(n, 'wedge_torso', 0)} / {tot(n, 'wedge_torso', 1)}, arm above cuff {tot(n, 'wedge_arm', 0)} / "
                 f"{tot(n, 'wedge_arm', 1)}), fragments {tot(n, 'fragment', 0)} / {tot(n, 'fragment', 1)}, spikes "
                 f"{tot(n, 'spike', 0)} / {tot(n, 'spike', 1)}, new holes {sum(r[n]['new_holes'] for r in results)}, "
                 f"runtime {min(r[n]['runtime'] for r in results)}-{max(r[n]['runtime'] for r in results)} s "
                 f"(mean {sum(r[n]['runtime'] for r in results) / len(results):.3f})")
lines += ["", f"GATE (fixed: wedge <= {GATE_PX} per side, fragments 0, new holes 0): "
              f"{len(fails)} / {len(results)} runs fail"]
lines += [f"- {f}" for f in fails]
up = [f"#{r['garment']} {r['who']} {'LR'[i]} +{r['spikes_above_current'][i]}" for r in results for i in range(2)
      if r["spikes_above_current"][i] > 0]
lines += ["", f"Spike px above current (fixed), {len(up)} / {2 * len(results)} sides: " + ", ".join(up)]
lines += ["", "Wedge split (fixed), torso side L / R, arm above the cuff line L / R (max px above the line):"]
lines += [f"- #{r['garment']} {r['who']}: {pr(r['fixed']['wedge_torso'])}, {pr(r['fixed']['wedge_arm'])} "
          f"({pr(r['fixed']['wedge_arm_h'])})" for r in results]
with open(f"{OUT}/table_armpit14.md", "w") as fh:
    fh.write("\n".join(lines) + "\n")
print("\n".join(lines))
if fails:
    sys.exit(1)
