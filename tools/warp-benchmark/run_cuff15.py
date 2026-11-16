"""MLS benchmark round 15: the sleeve cuff follows the garment's real hem (docs/06 "Cuff hem, round 15", NOT production).

    docker compose exec -T backend rm -rf /tmp/warp-benchmark /tmp/warp_benchmark
    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T [-e SHEETS=0] backend python manage.py shell < tools/warp-benchmark/run_cuff15.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

#28, #43, #40 x 6 avatars, adapt; base = the production config (docs/09 #105): sleeve C + side_floor "mask" + hem
"garment" + collar_floor + the neck_hole polygon + tube "finished" + armpit "r14". Columns: current (cuff_mode
"chord") | fixed (cuff_mode "hem", owner 2026-11-15 option A).
Metrics as round 14 (`mls.armpit_wedge`, `mls.armpit_ragged`, new holes vs current, arm covered below the cuff, neck)
plus: hem rise = how far the garment's hem lies above the cuff chord (max per side, body px, from the tube report),
outside = px that differ from current outside `mls.sleeve_zone` grown by 12 px.
GATE (fixed): wedge <= 5 per side, fragment px = 0, new holes = 0. Spike px reported.
Writes out/table_cuff15.md, out/results_cuff15.json, out/sheet_cuff15_<id>.png (per avatar: current L | R, fixed
L | R, 3x crops at the inner cuff end, clean; OVERLAY=1: wedge px red, px lost vs current yellow),
out/sheet_cuff15_full_<id>.png (per avatar: current | fixed, the whole T-shirt, 3x).
Exit status 1 when the gate fails.
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
        "sleeve_mode": "tube", "tube_arm": "finished", "armpit_mode": "r14"}
VARIANTS = [("current", "chord"), ("fixed", "hem")]
H, W = 1200, 600
OUT = "/tmp/warp_benchmark"
DATA = "/tmp/warp-benchmark/data/side12"
CROP, ZOOM, GATE_PX = 40, 3, 5
SHEETS = os.environ.get("SHEETS", "1") == "1"
OVERLAY = os.environ.get("OVERLAY", "0") == "1"
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
        runs = {n: pm.tshirt_layer(gimg, glm, blm, mask, "adapt", H, W, cuff_mode=m, **BASE, **hole_kw)
                for n, m in VARIANTS}
        c0 = runs["current"][0][:, :, 3] >= 128
        below0 = arm_below_cuff(mask, blm, arms, runs["current"][1]["sleeve_hems"], pm.WEDGE_CUFF_MARGIN)
        sl, sr = float(blm["shoulder"]["left_x"]), float(blm["shoulder"]["right_x"])
        neck = (Yg < float(blm["armpit"]["y"])) & (Xg > sl + 0.3 * (sr - sl)) & (Xg < sr - 0.3 * (sr - sl))
        zone = pm.sleeve_zone(runs["current"][1]["pairs"], blm, H, W)
        zone = cv2.dilate(zone.astype(np.uint8), np.ones((25, 25), np.uint8)) > 0
        rec = {"garment": gid, "avatar": pk, "who": who}
        for name, _ in VARIANTS:
            layer, info = runs[name]
            c = layer[:, :, 3] >= 128
            wd = pm.armpit_wedge(layer, mask, blm, info["sleeve_hems"])
            rg = pm.armpit_ragged(layer, mask, blm)
            lost = mask & c0 & ~c
            ch = {s: (info["tube"][s].get("cuff_hem") or {}) for s in ("left", "right")}
            rec[name] = {
                "wedge": [wd["left"]["px"], wd["right"]["px"]],
                "wedge_torso": [wd["left"]["torso_px"], wd["right"]["torso_px"]],
                "wedge_arm": [wd["left"]["arm_px"], wd["right"]["arm_px"]],
                "wedge_arm_h": [wd["left"]["arm_max_above_cuff"], wd["right"]["arm_max_above_cuff"]],
                "fragment": [rg["left"]["fragment_px"], rg["right"]["fragment_px"]],
                "spike": [rg["left"]["spike_px"], rg["right"]["spike_px"]],
                "new_holes": int(lost.sum()), "new_holes_arm_below_cuff": int((lost & below0).sum()),
                "arm_covered_below_cuff": int((c & ~c0 & arm_below_cuff(mask, blm, arms, info["sleeve_hems"], -1.0)).sum()),
                "neck_diff": int(((layer != runs["current"][0]).any(2) & neck).sum()),
                "outside_diff": int(((layer != runs["current"][0]).any(2) & ~zone).sum()),
                "rise": [ch["left"].get("rise_max_body_px"), ch["right"].get("rise_max_body_px")],
                "rise_u": [ch["left"].get("rise_max_u"), ch["right"].get("rise_max_u")],
                "rise_cols": [ch["left"].get("rise_garment_px"), ch["right"].get("rise_garment_px")],
                "skipped": [info["tube"][s].get("skipped") for s in ("left", "right")],
                "runtime": round(info["runtime"], 3),
                "patched": (info.get("side_floor_mask") or {}).get("patched_px"),
            }
        f, cur = rec["fixed"], rec["current"]
        bad = [f"wedge {s} {f['wedge'][i]}" for i, s in enumerate("LR") if f["wedge"][i] > GATE_PX]
        bad += [f"fragments {s} {f['fragment'][i]}" for i, s in enumerate("LR") if f["fragment"][i] > 0]
        rec["spikes_above_current"] = [f["spike"][i] - cur["spike"][i] for i in range(2)]
        if f["new_holes"] - f["new_holes_arm_below_cuff"]:
            bad.append(f"new holes {f['new_holes'] - f['new_holes_arm_below_cuff']}")
        if bad:
            fails.append(f"#{gid} {who}: " + ", ".join(bad))
        results.append(rec)
        print(json.dumps({k: v for k, v in rec.items()}, default=str)[:900])
        if not SHEETS:
            continue
        rgb = {n: bm.composite(base, runs[n][0], blm, runs[n][1]) for n, _ in VARIANTS}
        if OVERLAY:
            for n, _ in VARIANTS:
                wd = pm.armpit_wedge(runs[n][0], mask, blm, runs[n][1]["sleeve_hems"])
                rgb[n][wd["left"]["map"] | wd["right"]["map"]] = (0, 0, 255)
                rgb[n][mask & c0 & ~(runs[n][0][:, :, 3] >= 128)] = (0, 255, 255)
        cells = []
        for name, _ in VARIANTS:
            for i, side in enumerate(("left", "right")):
                a, b, _sh = runs["current"][1]["sleeve_hems"][side]
                cells.append(label(crop(rgb[name], (np.asarray(a) + 3 * np.asarray(b)) / 4),
                                   f"{name} {side[0].upper()} #{gid} {who} w{rec[name]['wedge'][i]}"))
        crop_rows.append(np.hstack(cells))
        fy0 = max(int(blm["neck"]["y"]) - 30, 0)
        fy1 = min(int(runs["current"][1]["pairs"]["hem_l"][1][1]) + 40, H)
        fx0, fx1 = 90, 510
        full_rows.append(np.hstack([label(cv2.resize(rgb[n][fy0:fy1, fx0:fx1], None, fx=3, fy=3,
                                                     interpolation=cv2.INTER_NEAREST),
                                          f"{n} #{gid} {who}", y=24, scale=0.7) for n, _ in VARIANTS]))
    if SHEETS:
        cv2.imwrite(f"{OUT}/sheet_cuff15_{gid}.png", np.vstack(crop_rows))
        w = max(r.shape[1] for r in full_rows)
        cv2.imwrite(f"{OUT}/sheet_cuff15_full_{gid}.png", np.vstack(
            [np.pad(r, ((0, 0), (0, w - r.shape[1]), (0, 0)), constant_values=255) for r in full_rows]))
with open(f"{OUT}/results_cuff15.json", "w") as fh:
    json.dump({"runs": results, "fails": fails}, fh, indent=1, default=str)

pr = lambda v: f"{v[0]} / {v[1]}"  # noqa: E731
lines = ["| garment | avatar | hem rise L / R (body px) | wedge L / R current | fixed | arm above cuff current | fixed | "
         "fragments fixed | spikes L / R current | fixed | new holes fixed (+ arm skin below the cuff) | "
         "arm covered below cuff | neck | outside | runtime s current / fixed |", "|" + "---|" * 15]
for r in results:
    c, f = r["current"], r["fixed"]
    lines.append(f"| #{r['garment']} | {r['who']} | {pr(f['rise'])} | {pr(c['wedge'])} | {pr(f['wedge'])} | "
                 f"{pr(c['wedge_arm'])} | {pr(f['wedge_arm'])} | {pr(f['fragment'])} | {pr(c['spike'])} | "
                 f"{pr(f['spike'])} | {f['new_holes'] - f['new_holes_arm_below_cuff']} "
                 f"(+ {f['new_holes_arm_below_cuff']} arm) | {f['arm_covered_below_cuff']} | {f['neck_diff']} | "
                 f"{f['outside_diff']} | {c['runtime']} / {f['runtime']} |")
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
up = [f"#{r['garment']} {r['who']} {'LR'[i]} {r['spikes_above_current'][i]:+d}" for r in results for i in range(2)
      if r["spikes_above_current"][i] != 0]
lines += ["", f"Spike px fixed vs current, {len(up)} / {2 * len(results)} sides changed: " + ", ".join(up)]
with open(f"{OUT}/table_cuff15.md", "w") as fh:
    fh.write("\n".join(lines) + "\n")
print("\n".join(lines))
if fails:
    sys.exit(1)
