"""Round 27: oversized keep_shape T-shirts lowered so the collar line sits where regular T-shirts put it
(docs/06 "keep_shape decision", docs/09 #121). Run MODE=before on the old code, then MODE=after.

    docker compose exec -T -e MODE=before backend python manage.py shell < tools/warp-benchmark/run_neck27.py
    docker compose exec -T -e MODE=after backend python manage.py shell < tools/warp-benchmark/run_neck27.py
    docker compose cp backend:/tmp/warp_benchmark/neck27/. tools/warp-benchmark/out/neck27/

GARMENTS (default 44,45) rendered as keep_shape (production flags) on every avatar. Per case:
  collar   aligned collar line row (mean of the neck_l / neck_r targets) before -> after
  target   neck.y + KEEP_NECK_T x (shoulder.y - neck.y)
  dy       the shift (info["keep_neck_dy"])
  neck     figure px between the neck row and the shoulder row inside the neck span covered by the garment
  bare     bare-shoulder px: figure px (arms excluded) between the neck row and the armpit row outside the neck span
           that the T-shirt layer does not cover and the final image shows as the avatar
  holes    px inside the T-shirt layer's outer outline transparent after and solid before, shifted by dy (gate 0)
Sheets out/neck27/sheet_<id>.png (rows = avatars, before | after, half size; docs/09 #121: dy + shoulders bound), 3x crops of neck + shoulders
out/neck27/crop_<id>_<avatar>.png (before | after), table out/neck27/table27.md.
"""
import os

import cv2
import numpy as np

from apps.avatars.models import Avatar
from apps.garments.landmark_checks import engine_landmarks
from apps.garments.models import Garment
from apps.tryon_engine import warp
from apps.tryon_engine.flags import render_flags

MODE = os.environ.get("MODE", "after")
GARMENTS = [int(v) for v in os.environ.get("GARMENTS", "44,45").split(",") if v]
H, W = 1200, 600
ROOT = "/tmp/warp_benchmark/neck27"
BEFORE = f"{ROOT}/before"
os.makedirs(BEFORE, exist_ok=True)
flags = render_flags("avatar")


def collar_row(dbg):
    p = dbg["mls"]["pairs"]
    return (p["neck_l"][1][1] + p["neck_r"][1][1]) / 2


rows = ["| garment | avatar | collar before -> after | target | dy | neck px before -> after | "
        "bare px before -> after | holes |", "|" + "---|" * 8]
for gid in GARMENTS:
    g = Garment.objects.get(id=gid)
    gi = cv2.imread(g.image.path, cv2.IMREAD_UNCHANGED)
    glm = engine_landmarks("tshirt", g.landmarks)
    cells = []
    for av in Avatar.objects.order_by("id"):
        lm = av.landmarks
        base = cv2.imread(av.image.path, cv2.IMREAD_UNCHANGED)
        img, _, dbg = warp.render_tryon(base, lm, [("tshirt", gi, glm)], H, W, fit_modes={"tshirt": "keep_shape"},
                                        **flags)
        layer = dbg["tshirt_layer"]
        mask = warp.figure_mask(cv2.resize(warp._bgra(base), (W, H)))
        body = mask & ~dbg["arm_mask"]
        ny, sy, ay = int(lm["neck"]["y"]), int(lm["shoulder"]["y"]), int(lm["armpit"]["y"])
        nl, nr = int(lm["neck"]["left_x"]), int(lm["neck"]["right_x"]) + 1
        bare_av = np.abs(img.astype(int) - warp.render_tryon(base, lm, [], H, W, **flags)[0].astype(int)).max(axis=2) <= 8
        zone_neck = np.zeros((H, W), bool)
        zone_neck[ny:sy, nl:nr] = True
        zone_sh = np.zeros((H, W), bool)
        zone_sh[ny:ay] = True
        zone_sh[:, nl:nr] = False
        cov = layer[:, :, 3] >= 128
        neck_px = int((cov & mask & zone_neck).sum())
        bare_px = int((body & zone_sh & ~cov & bare_av).sum())
        key = f"{BEFORE}/{gid}_{av.id}.npz"
        if MODE == "before":
            np.savez_compressed(key, img=img, layer=layer, collar=collar_row(dbg), neck=neck_px, bare=bare_px)
            print(f"before {gid} av{av.id}: collar {collar_row(dbg):.1f} neck {neck_px} bare {bare_px}", flush=True)
            continue
        old = np.load(key)
        dy = int(dbg["mls"].get("keep_neck_dy", 0))
        shifted = np.zeros_like(old["layer"])
        shifted[dy:] = old["layer"][:H - dy]
        sol = layer[:, :, 3] >= 128
        cs, _ = cv2.findContours(sol.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        fill = np.zeros((H, W), np.uint8)
        cv2.drawContours(fill, cs, -1, 1, -1)
        diff = int((fill.astype(bool) & ~sol & (shifted[:, :, 3] >= 128)).sum())
        target = lm["neck"]["y"] + warp_t * (lm["shoulder"]["y"] - lm["neck"]["y"]) if (warp_t := getattr(
            __import__("apps.tryon_engine.mls", fromlist=["KEEP_NECK_T"]), "KEEP_NECK_T", None)) else float("nan")
        rows.append(f"| #{gid} | {av.id} {av.sex} | {float(old['collar']):.1f} -> {collar_row(dbg):.1f} | {target:.1f} | "
                    f"{dy} | {int(old['neck'])} -> {neck_px} | {int(old['bare'])} -> {bare_px} | {diff} |")
        print(rows[-1], flush=True)
        cells.append(np.hstack([old["img"], np.full((H, 8, 3), 255, np.uint8), img]))
        y0, y1 = max(ny - 50, 0), ay + 20
        x0, x1 = max(int(lm["shoulder"]["left_x"]) - 40, 0), min(int(lm["shoulder"]["right_x"]) + 40, W)
        z = lambda im: cv2.resize(im[y0:y1, x0:x1], None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)  # noqa: E731
        a_, b_ = z(old["img"]), z(img)
        cv2.imwrite(f"{ROOT}/crop_{gid}_{av.id}.png", np.hstack([a_, np.full((a_.shape[0], 9, 3), 255, np.uint8), b_]))
    if MODE == "after":
        sheet = np.vstack([np.vstack([c, np.full((8, c.shape[1], 3), 255, np.uint8)]) for c in cells])
        cv2.imwrite(f"{ROOT}/sheet_{gid}.png", cv2.resize(sheet, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA))
if MODE == "after":
    open(f"{ROOT}/table27.md", "w").write("\n".join(rows) + "\n")
