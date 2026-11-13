"""MLS benchmark: neckline opening variants r7 | clear | clear_skin (docs/06 "V-neck opening", NOT production).

    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/run_neck.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

Reads the round 8b export (data/sleeve8b/, export_sleeve8b.py), or NECK_DATA (the 2026-11-12 re-run with #40's
re-marked collar: EXPORT_ROOT=/tmp/warp-benchmark/data/neck export_sleeve8b.py, then NECK_DATA=same). Production mls.tshirt_layer(..., "adapt",
neckline_variant=v, source="avatar", base=avatar) for #40 (V neck), #28 and #43 (crew) x all avatars.
Composite = avatar -> T-shirt layer -> neck_fill (clear_skin) -> head/neck overlay -> hands (benchmark composite order).
Metrics (opening = mls.neckline_opening weight, the same for every variant of a run):
  fabric_open_px: layer alpha >= 128 where the opening weight >= 0.5; fabric_open_visible_px: of those, not under the
  head/neck overlay (what the viewer sees); changed_vs_r7_px: composite RGB px different from r7; changed_outside_px:
  of those, outside the opening dilated by 3 px (should be 0); fill_px: neck_fill alpha > 0; strip_*: the band between
  the un-inset opening edge and the inset edge (NECKLINE_INSET): fabric px there and its thickness on the centre
  column (crew: the collar_bottom landmark sits on the band's inner edge, so this is inner fabric at the centre).
Writes out/results_neck.json, out/table_neck.md, out/sheet_neck_<id>.png (rows = avatars; r7 | clear | clear_skin;
neck-chest crop 3x, thin grey = the un-inset opening outline) and out/crop_neck_worst_<v>.png (the run with the most
visible fabric in the opening, 3x).
"""
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, "/tmp/warp-benchmark")
from apps.tryon_engine import mls as pm  # noqa: E402
from apps.tryon_engine import warp  # noqa: E402

GARMENTS = [int(x) for x in os.environ.get("NECK_GARMENTS", "40,28,43").split(",")]
VARIANTS = ["r7", "clear", "clear_skin"]
NECK_CLIP = os.environ.get("NECK_CLIP") == "1"  # neck_clip=True on the clear variants: columns clear | clear+clip | clear_skin+clip
H, W = 1200, 600
DATA = os.environ.get("NECK_DATA", "/tmp/warp-benchmark/data/sleeve8b")  # 2026-11-12 re-run: data/neck
OUT = "/tmp/warp_benchmark"
ZOOM = 3
os.makedirs(OUT, exist_ok=True)


def composite(base, layer, blm, info, mask):
    canvas = warp._alpha_composite(base.copy(), layer)
    if info.get("neck_fill") is not None:
        canvas = warp._alpha_composite(canvas, info["neck_fill"])
    head = warp.head_neck_overlay(mask, blm, warp.NECK_FEATHER_FIX, info.get("neck_opening"))
    h = head[:, :, None]
    canvas = np.clip(np.rint(canvas.astype(np.float32) * (1 - h) + base.astype(np.float32) * h), 0, 255).astype(np.uint8)
    arms = warp.find_arms(mask, blm)
    keep = warp.arm_overlay_mask(mask, arms, info.get("sleeve_hems"))
    canvas[keep] = base[keep]
    a = canvas[:, :, 3:4].astype(np.float32) / 255.0
    rgb = (canvas[:, :, :3].astype(np.float32) * a + 255 * (1 - a)).astype(np.uint8)
    return rgb, head


def label(img, text, scale=0.45, y=16):
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(img, text, (6, y), cv2.FONT_HERSHEY_SIMPLEX, scale, col, th, cv2.LINE_AA)
    return img


avatars = []
for pk in sorted(int(f[:-5]) for f in os.listdir(f"{DATA}/avatars") if f.endswith(".json")):
    with open(f"{DATA}/avatars/{pk}.json") as fh:
        d = json.load(fh)
    if os.environ.get("NECK_SEX") and d["sex"] != os.environ["NECK_SEX"]:  # e.g. NECK_SEX=female for a female garment
        continue
    base = cv2.imread(f"{DATA}/avatars/{pk}.png", cv2.IMREAD_UNCHANGED)
    avatars.append((pk, f"{d['sex'][0]}-{d['build']}", d["landmarks"], base, warp.figure_mask(base)))

results, worst = [], {}
for gid in GARMENTS:
    gimg = cv2.imread(f"{DATA}/garments/{gid}.png", cv2.IMREAD_UNCHANGED)
    with open(f"{DATA}/garments/{gid}.json") as fh:
        glm = json.load(fh)["landmarks"]
    rows = []
    for pk, who, blm, base, mask in avatars:
        outs = {}
        runs = [(v, v, False) for v in VARIANTS] if not NECK_CLIP else \
            [("r7", "r7", False), ("clear", "clear", False), ("clear+clip", "clear", True),
             ("clear_skin+clip", "clear_skin", True)]
        for name, v, clip in runs:
            layer, info = pm.tshirt_layer(gimg, glm, blm, mask, "adapt", H, W, neckline_variant=v, source="avatar",
                                          base=base, neck_clip=clip)
            rgb, head = composite(base, layer, blm, info, mask)
            outs[name] = (layer, info, rgb, head)
        cols = [n for n, _, _ in runs] if not NECK_CLIP else ["clear", "clear+clip", "clear_skin+clip"]
        box = pm.neck_clip_box(outs["r7"][1]["pairs"], blm, H, W)
        w, meta = pm.neckline_opening(outs["r7"][1]["pairs"], glm, H, W)
        if w is None:
            print(gid, pk, "no opening:", meta)
            continue
        side = meta["side"]
        region = np.zeros((H, W), np.uint8)
        cv2.fillPoly(region, [np.round(side * 8).astype(np.int32)], 1, shift=3)
        region = region > 0
        zone = cv2.dilate((w > 0).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
        strip = region & (w < 0.5)
        cx = int(round(outs["r7"][1]["pairs"]["neck_c"][1][0]))
        cells = []
        y0 = max(int(blm["neck"]["y"]) - 30, 0)
        y1 = min(int(max(side[:, 1].max(), blm["shoulder"]["y"])) + 40, H)
        x0 = max(int(blm["neck"]["left_x"]) - 70, 0)
        x1 = min(int(blm["neck"]["right_x"]) + 70, W)
        for v in cols:
            layer, info, rgb, head = outs[v]
            fab = (layer[:, :, 3] >= 128) & (w >= 0.5)
            diff = (rgb != outs["r7"][2]).any(2)
            fill = info.get("neck_fill")
            rec = {"garment": gid, "avatar": pk, "who": who, "variant": v, "shape": meta["shape"],
                   "ratio": meta["ratio"], "inset_px": meta["inset_px"],
                   "opening_px": int((w >= 0.5).sum()), "fabric_open_px": int(fab.sum()),
                   "fabric_open_visible_px": int((fab & (head < 0.5)).sum()),
                   "changed_vs_r7_px": int(diff.sum()), "changed_outside_px": int((diff & ~zone).sum()),
                   "fill_px": int((fill[:, :, 3] > 0).sum()) if fill is not None else 0,
                   "strip_fabric_px": int(((layer[:, :, 3] >= 128) & strip).sum()),
                   "strip_fabric_visible_px": int(((layer[:, :, 3] >= 128) & strip & (head < 0.5)).sum()),
                   "strip_centre_thickness_px": int(((layer[:, cx, 3] >= 128) & strip[:, cx]).sum()),
                   "back_collar_r7": "neck_opening" in info, "runtime_s": round(info["runtime"], 3),
                   "over_bg_box_px": int(((layer[:, :, 3] >= 128) & ~mask & box).sum()) if box is not None else None,
                   "changed_vs_clear_outside_box_px": int(((rgb != outs["clear"][2]).any(2) & ~box).sum())
                   if box is not None and "clear" in outs else None}
            results.append(rec)
            print(json.dumps(rec))
            crop = rgb[y0:y1, x0:x1].copy()
            cv2.polylines(crop, [np.round((side - [x0, y0]) * 8).astype(np.int32)], False, (150, 150, 150), 1,
                          cv2.LINE_AA, shift=3)
            big = cv2.resize(crop, None, fx=ZOOM, fy=ZOOM, interpolation=cv2.INTER_NEAREST)
            cells.append(label(big, f"{v} #{gid} {who} over bg {rec['over_bg_box_px']} fill {rec['fill_px']}"))
            if v not in worst or rec["fabric_open_visible_px"] > worst[v][0]:
                worst[v] = (rec["fabric_open_visible_px"], gid, who, big.copy())
        rows.append(np.hstack(cells))
    wmax, out = max(r.shape[1] for r in rows), []
    for r in rows:
        out.append(cv2.copyMakeBorder(r, 0, 4, 0, wmax - r.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255)))
    cv2.imwrite(f"{OUT}/sheet_neck_{gid}.png", np.vstack(out))
for v, (n, gid, who, img) in worst.items():
    label(img, f"worst {v}: {n} visible fabric px in the opening, #{gid} {who}", 0.6, img.shape[0] - 10)
    cv2.imwrite(f"{OUT}/crop_neck_worst_{v}.png", img)
with open(f"{OUT}/results_neck.json", "w") as fh:
    json.dump(results, fh, indent=1)

lines = ["| garment | shape (depth/width) | variant | opening px (sum) | fabric in opening px (sum / visible) | "
         "changed vs r7 px (sum) | changed outside neck zone px (sum) | skin fill px (sum) | runtime s (max) |",
         "|---|---|---|---|---|---|---|---|---|"]
for gid in GARMENTS:
    for v in VARIANTS:
        rs = [r for r in results if r["garment"] == gid and r["variant"] == v]
        lines.append(f"| #{gid} | {rs[0]['shape']} ({rs[0]['ratio']}) | {v} | {sum(r['opening_px'] for r in rs)} | "
                     f"{sum(r['fabric_open_px'] for r in rs)} / {sum(r['fabric_open_visible_px'] for r in rs)} | "
                     f"{sum(r['changed_vs_r7_px'] for r in rs)} | {sum(r['changed_outside_px'] for r in rs)} | "
                     f"{sum(r['fill_px'] for r in rs)} | {max(r['runtime_s'] for r in rs):.2f} |")
lines += ["", "| garment | avatar | variant | inset px | opening px | fabric in opening (all / visible) | changed vs r7 | "
          "changed outside zone | fill px | strip fabric (all / visible, centre thickness) | r7 back collar | runtime s |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
for r in results:
    lines.append(f"| #{r['garment']} | {r['who']} | {r['variant']} | {r['inset_px']} | {r['opening_px']} | "
                 f"{r['fabric_open_px']} / {r['fabric_open_visible_px']} | {r['changed_vs_r7_px']} | "
                 f"{r['changed_outside_px']} | {r['fill_px']} | {r['strip_fabric_px']} / {r['strip_fabric_visible_px']}, "
                 f"{r['strip_centre_thickness_px']} | {'yes' if r['back_collar_r7'] else 'no'} | {r['runtime_s']} |")
with open(f"{OUT}/table_neck.md", "w") as fh:
    fh.write("\n".join(lines) + "\n")
print("\n".join(lines[:11]))
print("done", len(results))
