"""Round 26: the pants fit model rewritten (docs/06 "Pants fit, round 26", docs/09 #120). Before / after on the
same data: run once with MODE=before on the old code, then MODE=after on the new code.

    docker compose exec -T -e MODE=before backend python manage.py shell < tools/warp-benchmark/run_pants26.py
    (change the code, docker compose restart worker)
    docker compose exec -T -e MODE=after backend python manage.py shell < tools/warp-benchmark/run_pants26.py
    docker compose cp backend:/tmp/warp_benchmark/pants26/. tools/warp-benchmark/out/pants26/

Production flags (render_flags("avatar")). Cases: every pants in the DB alone x every avatar, and the outfits
OUTFITS x every avatar. MODE=before stores each case (result + layer alphas) in /tmp/warp_benchmark/pants26/before.
MODE=after measures, per case:
  over   pants px past the figure's torso run (arms excluded) on the rows waist -> body crotch: sum / largest row
  top    largest over in the first 10 % of those rows (the waistband corners)
  above  pants px above the body waist row (gate 0)
  seam   colour jump between the two columns at the crotch axis / the median jump of the neighbouring column pairs,
         rows waist + 4 .. crotch - 2 (1 = no seam)
  unc    figure px (arms and hands excluded) covered in "before" and bare in "after", down to the new hem (gate 0)
  unc below hem  the same below the new hem line (the hem is on the ankle line now: the length rule, not a hole)
  holes  px inside the layer's outer outline transparent in "after" and solid in "before" (gate 0)
  wing   (outfits) pants px visible beside the T-shirt's torso run above its bottom row
Sheets: out/pants26/sheet_<case>.png (rows = avatars, columns before | after, half size, clean) and for AVATAR
3x crops of the waist and the leg edges: crop_<pants>_{waist,leg,hem}.png (before | after). Table: table26.md.
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
OUTFITS = [tuple(int(v) for v in o.split("+")) for o in
           os.environ.get("OUTFITS", "28+51,43+48,40+49,47+51,45+51").split(",") if o]
AVATAR = int(os.environ.get("AVATAR", "5"))
H, W = 1200, 600
ROOT = "/tmp/warp_benchmark/pants26"
BEFORE = f"{ROOT}/before"
os.makedirs(BEFORE, exist_ok=True)
flags = render_flags("avatar")


def load(path):
    return cv2.imread(path, cv2.IMREAD_UNCHANGED)


def garment(gid):
    g = Garment.objects.get(id=gid)
    return g, (g.type, load(g.image.path), engine_landmarks(g.type, g.landmarks))


def run_at(solid, y, ax):
    return next((r for r in warp._runs(solid[y]) if r[0] <= ax <= r[1]), None)


def outline_fill(solid):
    cs, _ = cv2.findContours(solid.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    out = np.zeros(solid.shape, np.uint8)
    cv2.drawContours(out, cs, -1, 1, -1)
    return out.astype(bool)


def seam(img, ax, y0, y1):
    rgb, a, ax = img[:, :, :3].astype(np.float32), img[:, :, 3] > 250, int(round(ax))
    jumps = {}
    for dx in range(-14, 15):
        x = ax + dx
        ys = [y for y in range(int(y0), int(y1)) if a[y, x - 1] and a[y, x]]
        if ys:
            jumps[dx] = float(np.mean([np.abs(rgb[y, x] - rgb[y, x - 1]).sum() for y in ys]))
    if 0 not in jumps:
        return float("nan")
    return jumps[0] / max(np.median([v for k, v in jumps.items() if abs(k) >= 3]), 1e-6)


def cases():
    pants = list(Garment.objects.filter(type="pants").exclude(landmarks={}).order_by("id").values_list("id", flat=True))
    for pid in pants:
        yield f"p{pid}", [pid]
    for t, p in OUTFITS:
        yield f"t{t}+p{p}", [t, p]


avatars = list(Avatar.objects.order_by("id"))
rows = ["| case | avatar | over sum / max | top | above | seam | unc | unc below hem | holes | wing | warn |",
        "|" + "---|" * 11]
gate = {"above": 0, "unc": 0, "holes": 0}
for name, gids in cases():
    gs = [garment(i) for i in gids]
    fit = {g.type: g.fit_mode for g, _ in gs}
    cells = []
    for av in avatars:
        base = load(av.image.path)
        lm = av.landmarks
        img, warns, dbg = warp.render_tryon(base, lm, [x for _, x in gs], H, W, fit_modes=fit, **flags)
        layers = dbg["final_layers"]
        pants = layers["pants"]
        union = np.zeros((H, W), bool)
        for L in layers.values():
            union |= L[:, :, 3] >= 128
        key = f"{BEFORE}/{name}_{av.id}.npz"
        if MODE == "before":
            np.savez_compressed(key, img=img, pants=pants, union=union, shirt=layers.get("tshirt", pants)[:, :, 3])
            cells.append(img)
            continue
        old = np.load(key)
        mask = warp.figure_mask(cv2.resize(warp._bgra(base), (W, H)))
        body = mask & ~dbg["arm_mask"]
        ax = warp._crotch_x(lm)
        a_wy, a_cr = warp._f(lm["waist"]["y"]), warp._f(lm["crotch"]["y"])
        p_sol = pants[:, :, 3] >= 128
        overs = []
        for y in range(int(np.ceil(a_wy)), int(a_cr)):
            p, b = run_at(p_sol, y, ax), run_at(body, y, ax)
            if p and b:
                overs.append(max(b[0] - p[0], 0) + max(p[1] - b[1], 0))
        top = max(overs[:max(len(overs) // 10, 1)]) if overs else 0
        above = int(p_sol[:int(np.floor(a_wy))].sum())
        sm = seam(pants, ax, a_wy + 4, a_cr - 2)
        # bare avatar px under the "before" final image are not garment (hands drawn on top): not counted
        unc_px = old["union"] & ~union & body
        hem_y = int(np.nonzero(p_sol.any(axis=1))[0][-1])  # the new hem line: below it is the length rule
        unc_len = int(unc_px[hem_y + 1:].sum())
        unc_px[hem_y + 1:] = False
        unc = int(unc_px.sum())
        if unc and av.id == AVATAR:  # where: red over the result
            dbg_img = img.copy()
            dbg_img[unc_px] = (0, 0, 255)
            ys_, xs_ = np.nonzero(unc_px)
            print(f"  unc rows {ys_.min()}..{ys_.max()} cols {xs_.min()}..{xs_.max()}", flush=True)
            cv2.imwrite(f"{ROOT}/unc_{name}_{av.id}.png", dbg_img)
        holes = int((outline_fill(union) & ~union & old["union"]).sum())
        wing = "-"
        if "tshirt" in layers:
            sh = layers["tshirt"][:, :, 3] >= 128
            ys = np.nonzero(sh.any(axis=1))[0]
            vis = p_sol & ~sh
            n = 0
            for y in range(int(a_wy), int(ys[-1]) + 1):
                r = run_at(sh, y, ax)
                if r:
                    n += int(vis[y, :r[0]].sum() + vis[y, r[1] + 1:].sum())
            wing = str(n)
        gate["above"] += above
        gate["unc"] += unc
        gate["holes"] += holes
        rows.append(f"| {name} | {av.id} | {sum(overs)} / {max(overs) if overs else 0} | {top} | {above} | "
                    f"{sm:.1f} | {unc} | {unc_len} | {holes} | {wing} | {len(warns)} |")
        print(rows[-1], flush=True)
        cells.append(np.hstack([old["img"], np.full((H, 8, 3), 255, np.uint8), img]))
        if av.id == AVATAR and name.startswith("p"):
            xs = np.nonzero(p_sol.any(axis=0))[0]
            x0, x1 = int(xs[0]) - 8, int(xs[-1]) + 9
            z = lambda im, y0, y1, l, r: cv2.resize(im[max(y0, 0):y1, max(l, 0):r], None, fx=3, fy=3,  # noqa: E731
                                                    interpolation=cv2.INTER_NEAREST)
            pair = lambda a_, b_: np.hstack([a_, np.full((a_.shape[0], 9, 3), 255, np.uint8), b_])  # noqa: E731
            y0, y1 = int(a_wy) - 25, int(a_cr) + 25
            cv2.imwrite(f"{ROOT}/crop_{name}_waist.png", pair(z(old["img"], y0, y1, x0, x1), z(img, y0, y1, x0, x1)))
            kn = int(warp._f(lm["knee"]["y"]))
            cv2.imwrite(f"{ROOT}/crop_{name}_leg.png", pair(z(old["img"], kn - 60, kn + 60, x0, x0 + 90),
                                                           z(img, kn - 60, kn + 60, x0, x0 + 90)))
            yb = int(np.nonzero(p_sol.any(axis=1))[0][-1])
            cv2.imwrite(f"{ROOT}/crop_{name}_hem.png", pair(z(old["img"], yb - 40, yb + 8, x0, x1),
                                                           z(img, yb - 40, yb + 8, x0, x1)))
    if MODE == "after":
        sheet = np.vstack([np.vstack([c, np.full((8, c.shape[1], 3), 255, np.uint8)]) for c in cells])
        cv2.imwrite(f"{ROOT}/sheet_{name}.png", cv2.resize(sheet, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA))
    else:
        print(f"before stored: {name}", flush=True)
if MODE == "after":
    rows.append(f"\nGATE above {gate['above']} px, uncovered {gate['unc']} px, new holes {gate['holes']} px")
    open(f"{ROOT}/table26.md", "w").write("\n".join(rows) + "\n")
    print(rows[-1])
