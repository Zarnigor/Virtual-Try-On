"""TRYON_NECK_FIX regression check: same garment + avatar rendered with neck_fix off and on, plus an alpha diff.

    docker compose exec -T backend python manage.py shell < tools/tryon_check/neck_regress.py
    docker compose cp backend:/tmp/neck_regress/. tools/tryon_check/out/neck_regress/

Garments: `t36` (the real white T-shirt, if present), `white28` (garment 28 recoloured white in memory, as in neck.py) and `t28`, on every avatar.
Per pair: <g>_av<id>_off.png, <g>_av<id>_on.png, <g>_av<id>_alphadiff.png (T-shirt layer alpha: red = the flag
added coverage, blue = it removed coverage, grey = unchanged garment; the neck band of the fix is outlined green),
and <g>_av<id>_zoom.png (3x crops of the left shoulder/sleeve: off | on | diff).
Prints how many alpha pixels changed inside the sleeves vs inside the neck band.
"""
import os

import cv2
import numpy as np

from apps.avatars.models import Avatar
from apps.garments.models import Garment
from apps.tryon_engine import warp

OUT = "/tmp/neck_regress"
os.makedirs(OUT, exist_ok=True)
ZOOM = 3


def read(path):
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    return cv2.cvtColor(img, cv2.COLOR_BGR2BGRA) if img.shape[2] == 3 else img


def white_variant(img):
    out = img.copy()
    lum = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY).astype(np.float32)
    out[:, :, :3] = np.clip(165 + 3 * lum, 150, 252).astype(np.uint8)[:, :, None]
    return out


g28 = Garment.objects.get(pk=28)
GARMENTS = [("white28", white_variant(read(g28.image.path)), g28.landmarks), ("t28", read(g28.image.path), g28.landmarks)]
g36 = Garment.objects.filter(pk=36, type="tshirt").exclude(landmarks={}).first()  # the real white T-shirt
if g36:
    GARMENTS.insert(0, ("t36", read(g36.image.path), g36.landmarks))

for name, gimg, glm in GARMENTS:
    for av in Avatar.objects.order_by("pk"):
        base = read(av.image.path)
        res = {}
        for fix in (False, True):
            rgb, _, dbg = warp.render_tryon(base, av.landmarks, [("tshirt", gimg, glm)], neck_fix=fix)
            res[fix] = (rgb, dbg)
            cv2.imwrite(f"{OUT}/{name}_av{av.pk}_{'on' if fix else 'off'}.png", rgb)
        a0 = res[False][1]["tshirt_layer"][:, :, 3].astype(int)
        a1 = res[True][1]["tshirt_layer"][:, :, 3].astype(int)
        d = a1 - a0
        vis = np.full(a0.shape + (3,), 255, np.uint8)
        vis[a0 > 0] = (200, 200, 200)
        vis[d > 0] = (0, 0, 255)
        vis[d < 0] = (255, 0, 0)
        parts = res[False][1].get("tshirt_parts", {})
        sleeve = np.zeros(a0.shape, bool)
        for side in ("left", "right"):
            if f"sleeve_{side}" in parts:
                sleeve |= parts[f"sleeve_{side}"][:, :, 3] > 0
        band = warp.neck_band_mask(av.landmarks, a0.shape) if hasattr(warp, "neck_band_mask") else None
        if band is not None:
            cnt, _ = cv2.findContours(band.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            cv2.drawContours(vis, cnt, -1, (0, 160, 0), 1)
        cv2.imwrite(f"{OUT}/{name}_av{av.pk}_alphadiff.png", vis)
        sh = av.landmarks["shoulder"]
        x0, y0 = max(int(sh["left_x"]) - 70, 0), max(int(sh["y"]) - 40, 0)
        crops = [c[y0:y0 + 110, x0:x0 + 120] for c in (res[False][0], res[True][0], vis)]
        cv2.imwrite(f"{OUT}/{name}_av{av.pk}_zoom.png",
                    cv2.resize(np.hstack(crops), None, fx=ZOOM, fy=ZOOM, interpolation=cv2.INTER_NEAREST))
        changed = d != 0
        print(f"{name} avatar {av.pk} {av.sex} {av.build}: alpha changed {changed.sum()} px, "
              f"in sleeves {(changed & sleeve).sum()}, outside sleeves {(changed & ~sleeve).sum()}"
              + (f", outside neck band {(changed & ~band).sum()}" if band is not None else ""))


# Shoulder cap check (TRYON_SHOULDER_CAP 0/1 x TRYON_NECK_FIX 0/1): <g>_av<id>_cap.png, 2x2 grid of the left shoulder,
# rows = shoulder_cap off / on, columns = neck_fix off / on.
for name, gimg, glm in GARMENTS:
    for av in Avatar.objects.order_by("pk"):
        base = read(av.image.path)
        sh = av.landmarks["shoulder"]
        x0, y0 = max(int(sh["left_x"]) - 70, 0), max(int(sh["y"]) - 40, 0)
        grid = []
        for cap in (False, True):
            row = []
            for fix in (False, True):
                rgb, _, _ = warp.render_tryon(base, av.landmarks, [("tshirt", gimg, glm)], neck_fix=fix, shoulder_cap=cap)
                c = np.ascontiguousarray(rgb[y0:y0 + 140, x0:x0 + 150])
                cv2.putText(c, f"cap{int(cap)} neck{int(fix)}", (4, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
                row.append(c)
            grid.append(np.hstack(row))
        cv2.imwrite(f"{OUT}/{name}_av{av.pk}_cap.png",
                    cv2.resize(np.vstack(grid), None, fx=ZOOM, fy=ZOOM, interpolation=cv2.INTER_NEAREST))
