"""Read-only diagnosis of the pants layer (rows engine, production flags): belly bulge, edge pixels, centre seam.

    docker compose exec -T backend python manage.py shell < tools/tryon_check/pants_diag.py
    docker compose cp backend:/tmp/pants_diag/. tools/tryon_check/out/pants_diag/

Per pants x avatar:
  colour  garment mean colour (to find the pink pants)
  fitx    sx / s of fit_x
  over    block rows waist -> crotch: px of the pants run past the figure's torso run (sum, largest row, row of it)
  top10   largest over in the first 10 % of the block (the "top corners")
  ring    print share (px far from the plain-fabric colour) in the outer 3 px ring vs at depth 6-12 px:
          src = cleaned source, halo = after remove_halo, warp = warped layer (no finish), fin = final layer
  semi    px with alpha 1..199 at least 2 px inside the outer outline (final layer)
  tail    rows in the last 12 rows of a leg identical to the row above (warped layer, max diff <= 1)
  seam    block rows above the crotch: colour jump between the two columns at the crotch axis / median jump of the
          neighbouring column pairs (1 = no seam); src = the same in the source at the garment's crotch x
Crops (3x): out/pants_diag/crop_<pants>_<avatar>_{waist,leg}.png, final vs warped-without-finish side by side.
"""
import os

import cv2
import numpy as np

from apps.avatars.models import Avatar
from apps.garments.landmark_checks import engine_landmarks
from apps.garments.models import Garment
from apps.tryon_engine import warp
from apps.tryon_engine.flags import render_flags

H, W = 1200, 600
OUT = "/tmp/pants_diag"
os.makedirs(OUT, exist_ok=True)
flags = render_flags("avatar")
PANTS = [int(v) for v in os.environ.get("PANTS", "18,48,49,51").split(",") if v]


def plain_colour(img):
    a = img[:, :, 3] > 250
    px = img[:, :, :3][a].reshape(-1, 3).astype(np.float32)
    q = (px // 16).astype(np.int32)
    key = q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2]
    top = np.bincount(key).argmax()
    return px[key == top].mean(axis=0)


def depth(alpha):
    solid = (alpha >= 128).astype(np.uint8)
    cs, _ = cv2.findContours(solid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    fill = np.zeros_like(solid)
    cv2.drawContours(fill, cs, -1, 1, -1)
    return cv2.distanceTransform(fill, cv2.DIST_L2, 3), fill.astype(bool)


def ring_share(img, plain):
    d, _ = depth(img[:, :, 3])
    far = np.linalg.norm(img[:, :, :3].astype(np.float32) - plain, axis=2) > 45
    vis = img[:, :, 3] > 0
    ring, deep = (d > 0) & (d <= 3) & vis, (d >= 6) & (d <= 12) & vis
    return far[ring].mean() if ring.any() else 0.0, far[deep].mean() if deep.any() else 0.0


def seam(img, ax, y0, y1):
    rgb = img[:, :, :3].astype(np.float32)
    a = img[:, :, 3] > 250
    ax = int(round(ax))
    jumps = {}
    for dx in range(-14, 15):
        x = ax + dx
        ys = [y for y in range(int(y0), int(y1)) if a[y, x - 1] and a[y, x]]
        if ys:
            jumps[dx] = float(np.mean([np.abs(rgb[y, x] - rgb[y, x - 1]).sum() for y in ys]))
    if 0 not in jumps:
        return None
    ref = np.median([v for k, v in jumps.items() if abs(k) >= 3])
    return jumps[0] / max(ref, 1e-6), max(jumps[k] for k in (-1, 0, 1) if k in jumps) / max(ref, 1e-6)


def tail(layer, rows_by_side):
    out = {}
    for side, rows in ((k, v) for k, v in rows_by_side.items() if k in ("left", "right")):
        l = int(min(r[1] for r in rows[-6:])) - 2
        r_ = int(max(r[2] for r in rows[-6:])) + 3
        col = layer[:, max(l, 0):min(r_, W)].astype(np.int16)
        ys = np.nonzero((layer[:, max(l, 0):min(r_, W), 3] > 0).any(axis=1))[0]
        ys = ys[ys > rows[0][0]]
        last = ys[-12:]
        out[side] = int(sum(1 for y in last if (layer[y - 1, max(l, 0):min(r_, W), 3] > 0).any()
                            and np.abs(col[y] - col[y - 1]).max() <= 1))
    return out


def crop3(img, x0, y0, x1, y1):
    c = img[max(y0, 0):y1, max(x0, 0):x1]
    return cv2.resize(c, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)


lines = ["| pants | avatar | sex | fitx | over sum / max (row) | top10 | ring src / halo / warp / fin (deep) | semi | "
         "tail L/R | seam warp (src) |", "|" + "---|" * 10]
for gid in PANTS:
    g = Garment.objects.get(id=gid)
    gimg = cv2.imread(g.image.path, cv2.IMREAD_UNCHANGED)
    glm = engine_landmarks("pants", g.landmarks)
    src = warp._bgra(gimg)
    plain = plain_colour(src)
    print(f"pants #{gid}: plain BGR {np.round(plain).astype(int).tolist()} size {src.shape[1]}x{src.shape[0]}")
    s_src = seam(src, warp._f(glm["crotch"]["center_x"]), warp._f(glm["waist"]["y"]) + 4,
                 warp._f(glm["crotch"]["y"]) - 4)
    halo = warp.remove_halo(warp.fill_alpha_holes(src, warp.opening_mask(src, warp.background_color(src))))
    for av in Avatar.objects.order_by("id"):
        base = cv2.imread(av.image.path, cv2.IMREAD_UNCHANGED)
        lm = av.landmarks
        mask = warp.figure_mask(cv2.resize(warp._bgra(base), (W, H)))
        gp = ("pants", gimg, glm)
        img, warns, dbg = warp.render_tryon(base, lm, [gp], H, W, fit_modes={"pants": g.fit_mode}, **flags)
        raw = dict(flags, finish_pants=False)
        _, _, dbg0 = warp.render_tryon(base, lm, [gp], H, W, fit_modes={"pants": g.fit_mode}, **raw)
        fin, wl = dbg["final_layers"]["pants"], dbg0["final_layers"]["pants"]
        ax = warp._crotch_x(lm)
        a_wy, a_cr = warp._f(lm["waist"]["y"]), warp._f(lm["crotch"]["y"])
        torso = mask & ~dbg["arm_mask"]
        overs = []
        for y in range(int(np.ceil(a_wy)), int(a_cr)):
            p = next((r for r in warp._runs(wl[y, :, 3] >= 128) if r[0] <= ax <= r[1]), None)
            b = next((r for r in warp._runs(torso[y]) if r[0] <= ax <= r[1]), None)
            if p and b:
                overs.append((y, max(b[0] - p[0], 0) + max(p[1] - b[1], 0)))
        n10 = max(len(overs) // 10, 1)
        top10 = max(o for _, o in overs[:n10]) if overs else 0
        ymax, omax = max(overs, key=lambda t: t[1]) if overs else (0, 0)
        rs = [ring_share(x, plain) for x in (src, halo, wl, fin)]
        d, fill = depth(fin[:, :, 3])
        semi = int(((fin[:, :, 3] > 0) & (fin[:, :, 3] < 200) & (d >= 2)).sum())
        info = {}
        warp.garment_layer("pants", gimg, glm, lm, H, W, dbg.get("arms") or warp.find_arms(mask, lm), info, mask)
        tl = tail(wl, info.get("pants_rows", info.get("pants_leg_rows", {})))
        sw = seam(wl, ax, a_wy + 4, a_cr - 4)
        fx = (dbg.get("pants_fit_x") or info.get("pants_fit_x") or {}).get("ratio", 1.0)  # 1.00 after round 26
        lines.append(f"| {gid} | {av.id} | {av.sex} | {fx:.2f} | {sum(o for _, o in overs)} / {omax} ({ymax}) | "
                     f"{top10} | {' / '.join(f'{r:.2f}' for r, _ in rs)} ({rs[3][1]:.2f}) | {semi} | "
                     f"{tl.get('left')}/{tl.get('right')} | "
                     f"{'-' if sw is None else f'{sw[0]:.1f}'} ({'-' if s_src is None else f'{s_src[0]:.1f}'}) |")
        xs = np.nonzero((wl[:, :, 3] > 0).any(axis=0))[0]
        x0, x1 = int(xs[0]) - 6, int(xs[-1]) + 7
        side = lambda a_, b_: np.hstack([a_, np.full((a_.shape[0], 9, 3), 255, np.uint8), b_])  # noqa: E731
        bare = img[:, :, :3]
        _, _, dbgn = warp.render_tryon(base, lm, [gp], H, W, fit_modes={"pants": g.fit_mode}, **raw)
        noft = warp.render_tryon(base, lm, [gp], H, W, fit_modes={"pants": g.fit_mode}, **raw)[0][:, :, :3]
        y0 = int(a_wy) - 25
        cv2.imwrite(f"{OUT}/crop_{gid}_{av.id}_waist.png",
                    side(crop3(bare, x0, y0, x1, int(a_cr) + 25), crop3(noft, x0, y0, x1, int(a_cr) + 25)))
        kn = int(warp._f(lm["knee"]["y"]))
        lx = int(xs[0]) - 6
        cv2.imwrite(f"{OUT}/crop_{gid}_{av.id}_leg.png",
                    side(crop3(bare, lx, kn - 60, lx + 90, kn + 60), crop3(noft, lx, kn - 60, lx + 90, kn + 60)))
        ys = np.nonzero((wl[:, :, 3] > 0).any(axis=1))[0]
        cv2.imwrite(f"{OUT}/crop_{gid}_{av.id}_hem.png",
                    side(crop3(bare, x0, int(ys[-1]) - 40, x1, int(ys[-1]) + 8),
                         crop3(noft, x0, int(ys[-1]) - 40, x1, int(ys[-1]) + 8)))
        print(lines[-1], flush=True)
open(f"{OUT}/table.md", "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
