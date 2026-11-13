"""MLS benchmark: neckline hole mask (GrabCut in garment space, warped with the garment field), docs/06, NOT production.

    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T -e NECK_DATA=/tmp/warp-benchmark/data/neck backend python manage.py shell \
        < tools/warp-benchmark/run_neck_hole.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

#40 and #28 x all avatars, adapt k 1.0. Writes out/overlay_hole_<id>_garment.png (garment px: grey = the landmark
polygon, red = the GrabCut hole, yellow = the belt), out/overlay_hole_<id>.png (rows = avatars; r7 composite with the
warped hole outlined red and the warped landmark polygon grey | clear | hole | hole+clip; 3x neck crop) and
out/table_neck_hole.md (fabric left in the hole, band px removed vs r7, changes outside the neck zone, runtime).
"""
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, "/tmp/warp-benchmark")
from apps.tryon_engine import mls as pm  # noqa: E402
from apps.tryon_engine import warp  # noqa: E402

GARMENTS = [int(x) for x in os.environ.get("NECK_GARMENTS", "40,28").split(",")]
DATA = os.environ.get("NECK_DATA", "/tmp/warp-benchmark/data/neck")
OUT = "/tmp/warp_benchmark"
COLLAR_FLOOR = os.environ.get("NECK_COLLAR_FLOOR", "1") == "1"  # owner 2026-11-13: collar points onto the contour
H, W, ZOOM = 1200, 600, 3
os.makedirs(OUT, exist_ok=True)
RUNS = [("r7", "r7", False), ("clear", "clear", False), ("hole", "hole", False), ("hole+clip", "hole", True)]
if os.environ.get("NECK_HOLE_SKIN") == "1":  # r7 | hole | hole_skin | hole_skin+clip
    RUNS = [("r7", "r7", False), ("hole", "hole", False), ("hole_skin", "hole_skin", False),
            ("hole_skin+clip", "hole_skin", True)]


def composite(base, layer, blm, info, mask):
    canvas = warp._alpha_composite(base.copy(), layer)
    if info.get("neck_fill") is not None:
        canvas = warp._alpha_composite(canvas, info["neck_fill"])
    head = warp.head_neck_overlay(mask, blm, warp.NECK_FEATHER_FIX, info.get("neck_opening"))
    h = head[:, :, None]
    canvas = np.clip(np.rint(canvas.astype(np.float32) * (1 - h) + base.astype(np.float32) * h), 0, 255).astype(np.uint8)
    keep = warp.arm_overlay_mask(mask, warp.find_arms(mask, blm), info.get("sleeve_hems"))
    canvas[keep] = base[keep]
    a = canvas[:, :, 3:4].astype(np.float32) / 255.0
    return (canvas[:, :, :3].astype(np.float32) * a + 255 * (1 - a)).astype(np.uint8), head


def label(img, text, scale=0.45, y=16):
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(img, text, (6, y), cv2.FONT_HERSHEY_SIMPLEX, scale, col, th, cv2.LINE_AA)
    return img


def outline(img, m, color, off=(0, 0)):
    cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(img, [c - np.array(off) for c in cs], -1, color, 1)


avatars = []
for pk in sorted(int(f[:-5]) for f in os.listdir(f"{DATA}/avatars") if f.endswith(".json")):
    with open(f"{DATA}/avatars/{pk}.json") as fh:
        d = json.load(fh)
    if os.environ.get("NECK_SEX") and d["sex"] != os.environ["NECK_SEX"]:  # e.g. NECK_SEX=female
        continue
    base = cv2.imread(f"{DATA}/avatars/{pk}.png", cv2.IMREAD_UNCHANGED)
    avatars.append((pk, f"{d['sex'][0]}-{d['build']}", d["landmarks"], base, warp.figure_mask(base)))

lines = ["| garment | avatar | variant | hole px (garment / warped) | fabric left in hole px | band px removed vs r7 | "
         "changed outside neck zone px | runtime s | note |", "|---|---|---|---|---|---|---|---|---|"]
for gid in GARMENTS:
    gimg = cv2.imread(f"{DATA}/garments/{gid}.png", cv2.IMREAD_UNCHANGED)
    with open(f"{DATA}/garments/{gid}.json") as fh:
        glm = json.load(fh)["landmarks"]
    poly_file = "/tmp/warp-benchmark/data/neck_hole/" + os.environ.get("NECK_HOLE_NAME", "{gid}.json").format(gid=gid)
    hole_poly = None
    if os.path.exists(poly_file):
        with open(poly_file) as fh:
            hole_poly = json.load(fh)["polygon"]
    if hole_poly is not None:
        hole_g = np.zeros(gimg.shape[:2], np.uint8)
        cv2.fillPoly(hole_g, [np.round(np.asarray(hole_poly, float) * 8).astype(np.int32)], 1, shift=3)
        hole_g = hole_g > 0
        meta = {"source": "polygon", "hole_px": int(hole_g.sum())}
    else:
        hole_g, meta = pm.neckline_hole(gimg, glm)
    poly = pm._landmark_neck_polygon(glm)
    # garment-space overlay
    a = gimg[:, :, 3:4] / 255.0
    gv = (gimg[:, :, :3] * a + 255 * (1 - a)).astype(np.uint8)
    inside = np.zeros(gimg.shape[:2], np.uint8)
    cv2.fillPoly(inside, [np.round(poly * 8).astype(np.int32)], 1, shift=3)
    if hole_g is not None:
        gv[hole_g] = (0.55 * gv[hole_g] + 0.45 * np.array([60, 60, 255])).astype(np.uint8)
    edge = np.ones(gimg.shape[:2], np.uint8)
    cv2.polylines(edge, [np.round(poly * 8).astype(np.int32)], True, 0, 1, shift=3)
    belt = cv2.distanceTransform(edge, cv2.DIST_L2, 5) <= pm.NECK_HOLE_BELT
    outline(gv, belt, (0, 200, 230))
    cv2.polylines(gv, [np.round(poly * 8).astype(np.int32)], True, (120, 120, 120), 1, cv2.LINE_AA, shift=3)
    ys, xs = np.nonzero(inside | belt)
    gy0, gy1, gx0, gx1 = max(ys.min() - 30, 0), ys.max() + 30, max(xs.min() - 30, 0), xs.max() + 30
    gcrop = cv2.resize(gv[gy0:gy1, gx0:gx1], None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    cv2.imwrite(f"{OUT}/overlay_hole_{gid}_garment.png",
                label(gcrop, f"#{gid} garment: grey = landmark polygon, yellow = belt {pm.NECK_HOLE_BELT} px, red = hole "
                             f"({meta if hole_g is None else str(meta['hole_px']) + ' px'})", 0.5))
    # owner 2026-11-13: with an owner-drawn polygon the landmark triangle/curve (clear) is not needed
    runs = [r for r in RUNS if not (hole_poly is not None and r[0] == "clear")]
    rows = []
    for pk, who, blm, base, mask in avatars:
        outs = {}
        for name, v, clip in runs:
            layer, info = pm.tshirt_layer(gimg, glm, blm, mask, "adapt", H, W, neckline_variant=v, source="avatar",
                                          base=base, neck_clip=clip, neck_hole_polygon=hole_poly,
                                          collar_floor_on=COLLAR_FLOOR)
            outs[name] = (layer, info, *composite(base, layer, blm, info, mask))
        r7l, r7i, r7rgb, _ = outs["r7"]
        hw = outs["hole"][1].get("neck_weight")
        ow, _ = pm.neckline_opening(r7i["pairs"], glm, H, W)
        zone = np.zeros((H, W), bool)
        for m_ in (hw, ow):
            if m_ is not None:
                zone |= m_ > 0
        zone = cv2.dilate(zone.astype(np.uint8), np.ones((7, 7), np.uint8))
        y0, y1 = max(int(blm["neck"]["y"]) - 30, 0), min(int(blm["shoulder"]["y"]) + 130, H)
        x0, x1 = max(int(blm["neck"]["left_x"]) - 70, 0), min(int(blm["neck"]["right_x"]) + 70, W)
        cells = []
        for name, _, _ in runs:
            layer, info, rgb, head = outs[name]
            w = info.get("neck_weight")
            crop = rgb[y0:y1, x0:x1].copy()
            if name == "r7" and hw is not None:
                outline(crop, (hw >= 0.5)[y0:y1, x0:x1], (40, 40, 230))
            fab = int(((layer[:, :, 3] >= 128) & (hw >= 0.5)).sum()) if hw is not None else None
            # band px removed vs r7: garment px that r7 kept, this run removed, and that are NOT in the warped hole
            diff = (rgb != r7rgb).any(2)
            out_zone = int((diff & ~(zone > 0)).sum())
            removed = (r7l[:, :, 3] >= 128) & (layer[:, :, 3] < 128)
            band_removed = int((removed & (hw < 0.5)).sum()) if (hw is not None and name.startswith("hole")) else "-"
            fill = info.get("neck_fill")
            fill_px = int((fill[:, :, 3] > 0).sum()) if fill is not None else 0
            if name != "r7":
                lines.append(f"| #{gid} | {who} | {name} | {meta['hole_px'] if hole_g is not None else '-'} / "
                             f"{int((hw >= 0.5).sum()) if hw is not None else '-'} | {fab if fab is not None else '-'} | "
                             f"{band_removed} | {out_zone} | {info['runtime']:.2f} | fill {fill_px} "
                             f"{info.get('neckline', {}).get('skipped', '')} raised {info.get('collar_floor', '-')} |")
            big = cv2.resize(crop, None, fx=ZOOM, fy=ZOOM, interpolation=cv2.INTER_NEAREST)
            cells.append(label(big, f"{name} #{gid} {who}" + (" (red = warped hole)" if name == "r7" else "")))
        rows.append(np.hstack(cells))
    wmax = max(r.shape[1] for r in rows)
    cv2.imwrite(f"{OUT}/overlay_hole_{gid}.png", np.vstack(
        [cv2.copyMakeBorder(r, 0, 4, 0, wmax - r.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255)) for r in rows]))
with open(f"{OUT}/table_neck_hole.md", "w") as fh:
    fh.write("\n".join(lines) + "\n")
print("\n".join(lines))
