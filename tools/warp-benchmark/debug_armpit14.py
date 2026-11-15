"""MLS benchmark round 14, step 1: root cause of the open armpit wedge, from the pixels (docs/06 "Armpit wedge,
round 14", NOT production; read-only: no engine change).

    docker compose exec -T backend rm -rf /tmp/warp-benchmark /tmp/warp_benchmark
    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/debug_armpit14.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

#28, #43, #40 x 6 avatars x both sides, adapt; base sleeve C + side_floor "mask" + hem "garment" + collar_floor + the
neck_hole polygon. Three runs: no tube | current (tube "finished", armpit_mode "off" = round 13b) | r14 (armpit_mode "r14"; this column was round 13c, "r13c", until it was
deleted, docs/09 #105: the step-1 overlays in docs/06 were made with 13c).
Per side one row of 6 panels (100 x 100 px box around the body crease, 4x):
 1 current, clean.
 2 geometry on the avatar: green tint = arm rows (find_arms); torso edge per row as the engine sees it (white dot =
   mask, red dot = interpolated); blue = body armhole line (extended, thin); grey = tube cross-sections; red = tube
   inner edge + cuff line; green squares = side floor pair targets (round = landmark floor); yellow + = body crease
   (top of the background gap between arm and torso); cyan x = armpit pair target; magenta x = where the MLS map puts
   the garment's own notch apex; white x = where it puts the garment's cuff_inner.
 3 who should own each open px (figure px, not covered, not the arm overlay below the cuff): red = MLS source is a
   transparent garment px (the garment's notch), inward of the armhole line (torso territory); orange = the same,
   outward (tube territory, tube draws nothing); blue = source outside the garment image; magenta = source opaque
   but cleared by a tube rule; yellow = source opaque, lost at the edge (halo erosion / hard edge).
 4 r14, clean.
 5 r14 vs current: cyan = px added by the tube, magenta = px added by the MLS layer (dark outline = over the
   background, not the figure), yellow = px current covers and r14 does not.
 6 the garment around its notch: cyan x = armpit landmark, magenta x = notch apex of the alpha, white x = cuff_inner,
   blue = armhole line (shoulder -> armpit landmark).
Writes out/debug_armpit14_<id>_<avatar>.png, out/debug_armpit14.json, out/table_debug_armpit14.md.
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
BASE = {"sleeve_variant": "C", "side_floor": True, "side_floor_mode": "mask", "hem_mode": "garment", "debug_map": True}
TUBE = {"sleeve_mode": "tube", "tube_arm": "finished"}
VARIANTS = [("nt", {}), ("cur", {**TUBE, "armpit_mode": "off"}), ("c13", {**TUBE, "armpit_mode": "r14"})]
H, W = 1200, 600
OUT = "/tmp/warp_benchmark"
DATA = "/tmp/warp-benchmark/data/side12"
R, Z = 50, 4
os.makedirs(OUT, exist_ok=True)
f_ = pm._f


def runs_of(row):
    return warp._runs(row)


def body_crease(mask, arms, side, axis):
    """Top of the background gap between the arm and the torso: (x, y), or None."""
    arm = arms.get(side)
    if not arm:
        return None
    y, l, r = arm["rows"][0]
    torso = next((q for q in runs_of(mask[y]) if q[0] <= axis <= q[1]), None)
    if torso is None:
        return None
    g = (r + 1, torso[0] - 1) if side == "left" else (torso[1] + 1, l - 1)
    while y > 0:
        bg = [q for q in runs_of(~mask[y - 1]) if q[0] <= g[1] and q[1] >= g[0] and q[0] > 0 and q[1] < W - 1]
        if not bg:
            break
        q = max(bg, key=lambda q: q[0]) if side == "left" else min(bg, key=lambda q: q[0])
        g, y = (q[0], q[1]), y - 1
    return ((g[0] + g[1]) / 2, float(y))


def garment_notch(alpha, glm, side):
    """Top of the transparent gap between the sleeve underside and the torso side, on the garment alpha."""
    solid = alpha > 128
    gH, gW = solid.shape
    cx = (f_(glm["armpit"]["left_x"]) + f_(glm["armpit"]["right_x"])) / 2
    y = int(min(max(f_(glm["sleeve_cuff_inner"][side]["y"]), f_(glm["armpit"]["y"])) + 12, gH - 1))
    torso = next((q for q in runs_of(solid[y]) if q[0] <= cx <= q[1]), None)
    if torso is None:
        return None
    x = torso[0] - 1 if side == "left" else torso[1] + 1
    if not 0 <= x < gW:
        return None
    g = next((q for q in runs_of(~solid[y]) if q[0] <= x <= q[1]), None)
    if g is None:
        return None
    while y > 0:
        bg = [q for q in runs_of(~solid[y - 1]) if q[0] <= g[1] and q[1] >= g[0]]
        if not bg:
            break
        q = max(bg, key=lambda q: q[0]) if side == "left" else min(bg, key=lambda q: q[0])
        g, y = q, y - 1
    return ((g[0] + g[1]) / 2, float(y))


def forward(mx, my, q):
    d2 = (mx - q[0]) ** 2 + (my - q[1]) ** 2
    d2[mx < 0] = 1e12
    i = int(np.argmin(d2))
    y, x = divmod(i, mx.shape[1])
    return (float(x), float(y)), float(np.sqrt(d2.flat[i]))


def label(img, text, y=14):
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(img, text, (4, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, col, th, cv2.LINE_AA)
    return img


class Box:
    def __init__(self, c, r=R, z=Z, w=W, h=H):
        self.x0 = int(min(max(round(c[0]) - r, 0), w - 2 * r))
        self.y0 = int(min(max(round(c[1]) - r, 0), h - 2 * r))
        self.r, self.z = r, z

    def crop(self, img):
        c = img[self.y0:self.y0 + 2 * self.r, self.x0:self.x0 + 2 * self.r]
        return cv2.resize(c, (2 * R * Z, 2 * R * Z), interpolation=cv2.INTER_NEAREST)

    def pt(self, p):
        z = 2 * R * Z / (2 * self.r)
        return int(round((p[0] - self.x0 + 0.5) * z)), int(round((p[1] - self.y0 + 0.5) * z))

    def sl(self):
        return slice(self.y0, self.y0 + 2 * self.r), slice(self.x0, self.x0 + 2 * self.r)


def cross(img, p, col, plus=False, n=7):
    x, y = p
    for c, th in (((0, 0, 0), 4), (col, 2)):
        if plus:
            cv2.line(img, (x - n, y), (x + n, y), c, th)
            cv2.line(img, (x, y - n), (x, y + n), c, th)
        else:
            cv2.line(img, (x - n, y - n), (x + n, y + n), c, th)
            cv2.line(img, (x - n, y + n), (x + n, y - n), c, th)


def tint(img, m, col, a=0.65):
    out = img.copy()
    out[m] = (np.asarray(col, np.float32) * a + out[m].astype(np.float32) * (1 - a)).astype(np.uint8)
    return out


avatars = []
for pk in sorted(int(f[:-5]) for f in os.listdir(f"{DATA}/avatars") if f.endswith(".json")):
    d = json.load(open(f"{DATA}/avatars/{pk}.json"))
    base = cv2.imread(f"{DATA}/avatars/{pk}.png", cv2.IMREAD_UNCHANGED)
    avatars.append((pk, f"{d['sex'][0]}-{d['build']}", d["landmarks"], base, warp.figure_mask(base)))

Yg, Xg = np.mgrid[0:H, 0:W]
P = np.stack([Xg, Yg], -1).astype(np.float32)
results = []
for gid in GARMENTS:
    gimg = cv2.imread(f"{DATA}/garments/{gid}.png", cv2.IMREAD_UNCHANGED)
    glm = json.load(open(f"{DATA}/garments/{gid}.json"))["landmarks"]
    galpha = gimg[:, :, 3]
    gH, gW = galpha.shape
    poly = (glm.get("neck_hole") or {}).get("polygon")
    hole_kw = {"neckline_variant": "hole", "neck_hole_polygon": poly} if poly else {}
    for pk, who, blm, base, mask in avatars:
        run = {n: pm.tshirt_layer(gimg, glm, blm, mask, "adapt", H, W, **BASE, **kw, **hole_kw) for n, kw in VARIANTS}
        rgb = {n: bm.composite(base, run[n][0], blm, run[n][1]) for n in run}
        _keep = pm._blend_new_holes  # the same "current" run without the round 12b blend back to the landmark floor
        pm._blend_new_holes = lambda H_, W_, a_, m_, ref_map, mx_, my_, report, iters=0, hole=None: (
            report.update(blend_px=0, blend_rounds=0, blend_residual_px=0) or (mx_, my_))
        try:
            cov_nb = pm.tshirt_layer(gimg, glm, blm, mask, "adapt", H, W, **BASE, **VARIANTS[1][1], **hole_kw)[0]
        finally:
            pm._blend_new_holes = _keep
        cov_nb = cov_nb[:, :, 3] >= 128
        cov = {n: run[n][0][:, :, 3] >= 128 for n in run}
        m0x, m0y = run["nt"][1]["map"]
        a0 = cv2.remap(galpha.astype(np.float32), m0x, m0y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                       borderValue=0)
        inside = (m0x >= 0) & (m0x <= gW - 1) & (m0y >= 0) & (m0y <= gH - 1)
        arms = warp.find_arms(mask, blm)
        axis = warp._crotch_x(blm)
        info = run["cur"][1]
        keep = warp.arm_overlay_mask(mask, arms, info["sleeve_hems"])
        cmx, cmy = info["map"]
        k13x, k13y = run["c13"][1]["map"]
        a_y = int(f_(blm["armpit"]["y"]))
        edges = pm.torso_side_edges(mask, blm, list(range(a_y, min(a_y + 200, H))), axis)
        rows_img = []
        for side, sx in (("left", "_l"), ("right", "_r")):
            rec = {"garment": gid, "avatar": pk, "who": who, "side": side}
            tb = info["tube"][side]
            pairs = info["pairs"]
            cr = body_crease(mask, arms, side, axis)
            lm_arm = (f_(blm["armpit"][f"{side}_x"]), f_(blm["armpit"]["y"]))
            box = Box(cr if cr else (lm_arm[0], lm_arm[1] + 15))
            sl = box.sl()
            B0, B1 = (np.array(v, float) for v in tb["armhole_body"])
            cuff_mid = (np.array(tb["cuff"][0]) + np.array(tb["cuff"][1])) / 2
            ba = np.array([-(B1 - B0)[1], (B1 - B0)[0]])
            if (cuff_mid - B0) @ ba < 0:
                ba = -ba
            out_side = ((P - B0) @ ba) > 0
            inbox = np.zeros((H, W), bool)
            inbox[sl] = True
            erows = edges[side]
            # ---- open px and their owner
            # the arm: figure px on the arm side of the torso edge (engine edge: mask rows / interpolated touch rows)
            # from the armpit landmark row down; arm px below the tube's cuff line are correct skin, never counted
            edge_x = np.full(H, np.nan)
            for y, e, src in erows:
                if e is not None:
                    edge_x[y] = e
            ex = edge_x[:, None]
            arm_px = mask & ~np.isnan(ex) & ((Xg < ex) if side == "left" else (Xg >= ex))
            d_b = np.array(tb["axis_body"][1]) - np.array(tb["axis_body"][0])
            below_cuff = ((P - cuff_mid) @ d_b) > 0
            legit = arm_px & below_cuff
            U = mask & ~cov["cur"] & ~legit & inbox
            # what the MLS map (no tube) brings to each px: garment sleeve px / torso px / transparent
            A0g = np.array([f_(glm["shoulder"][f"{side}_x"]), f_(glm["shoulder"]["y"])])
            A1g = np.array([f_(glm["armpit"][f"{side}_x"]), f_(glm["armpit"]["y"])])
            C0g = np.array([f_(glm["sleeve_cuff_outer"][side]["x"]), f_(glm["sleeve_cuff_outer"][side]["y"])])
            C1g = np.array([f_(glm["sleeve_cuff_inner"][side]["x"]), f_(glm["sleeve_cuff_inner"][side]["y"])])
            ga = np.array([-(A1g - A0g)[1], (A1g - A0g)[0]]) / np.linalg.norm(A1g - A0g)
            if ((C0g + C1g) / 2 - A0g) @ ga < 0:
                ga = -ga
            src_sleeve = (((m0x - A0g[0]) * ga[0] + (m0y - A0g[1]) * ga[1]) > -1.0) & (m0y <= max(C0g[1], C1g[1]) + 10)
            tube_drawn = (cmx >= 0) & ((cmx != m0x) | (cmy != m0y))
            cleared = (cmx < 0) & (m0x >= 0)
            cat = np.zeros((H, W), np.uint8)
            cat[U & ~inside] = 3
            cat[U & inside & (a0 < 128) & ~out_side] = 1
            cat[U & inside & (a0 < 128) & out_side] = 2
            cat[U & inside & (a0 >= 128) & cleared] = 4
            cat[U & inside & (a0 >= 128) & ~cleared] = 5
            names = {1: "notch_torso_side", 2: "notch_tube_side", 3: "src_outside", 4: "cleared", 5: "edge_lost"}
            rec["open_px"] = int(U.sum())
            rec["open_by_owner"] = {v: int((cat == k).sum()) for k, v in names.items()}
            rec["open_in_protected_zone"] = int((U & tb["protected_zone"]).sum())
            rec["open_above_cuff"] = int((U & ~below_cuff).sum())
            rec["open_torso_side_below_cuff"] = int((U & below_cuff).sum())
            rec["open_no_tube"] = int((mask & ~cov["nt"] & ~legit & inbox).sum())
            rec["open_13c"] = int((mask & ~cov["c13"] & ~legit & inbox).sum())
            rec["open_cur_that_no_tube_covers"] = int((U & cov["nt"]).sum())
            rec["arm_overlay_px_in_box"] = int((keep & inbox).sum())
            # ---- geometry numbers
            g_arm = (f_(glm["armpit"][f"{side}_x"]), f_(glm["armpit"]["y"]))
            g_cin = (f_(glm["sleeve_cuff_inner"][side]["x"]), f_(glm["sleeve_cuff_inner"][side]["y"]))
            notch = garment_notch(galpha, glm, side)
            f_notch = forward(m0x, m0y, notch)[0] if notch else None
            f_cin = forward(m0x, m0y, g_cin)[0]
            f_arm = forward(m0x, m0y, g_arm)[0]
            rec.update({
                "body_crease": cr, "body_armpit_lm": lm_arm, "s": round(run["cur"][1]["s"], 3),
                "armpit_pair_target": [round(v, 1) for v in pairs["armpit" + sx][1]] if "armpit" + sx in pairs else None,
                "garment_armpit_lm": g_arm, "garment_notch": notch, "garment_cuff_inner": g_cin,
                "garment_lm_minus_notch": None if notch is None else [g_arm[0] - notch[0], g_arm[1] - notch[1]],
                "garment_cuff_inner_below_notch_px": None if notch is None else g_cin[1] - notch[1],
                "notch_lands_at": f_notch, "armpit_lm_lands_at": f_arm, "cuff_inner_lands_at": f_cin,
                "notch_minus_crease": None if not (cr and f_notch) else [f_notch[0] - cr[0], f_notch[1] - cr[1]],
                "crease_minus_armpit_lm": None if not cr else [cr[0] - lm_arm[0], cr[1] - lm_arm[1]],
                "tube_cuff_inner_end": tb["cuff"][1], "tube_t0_inner_end": tb["t0_body"][1],
                "rejected": [r for r in run["cur"][1]["rejected"] if sx in r],
            })
            interp = [(y, e) for y, e, src in erows if src == "interp"]
            rec["torso_edge_interp_rows"] = [interp[0][0], interp[-1][0]] if interp else None
            if cr:
                e_at = next((e for y, e, src in erows if y == int(cr[1]) and e is not None), None)
                rec["torso_edge_minus_crease_x_at_crease_row"] = None if e_at is None else round(e_at - cr[0], 1)
            # interpolated edge vs the figure: px of arm (find_arms rows are separated rows only) cannot be checked in
            # touch rows; what can: the interp edge must stay inside the figure and end on the first clean row's edge
            sfm = [r for r in info["side_floor_mask"]["rows"] if r["side"] == side]
            rec["side_floor_rows"] = [[r["y"], r.get("src"), r.get("edge"), r.get("garment_edge"),
                                       bool(r.get("pair"))] for r in sfm if r["y"] <= a_y + 110]
            fp = [r["y"] for r in sfm if r.get("pair")]
            rec["first_side_floor_pair_below_armpit_px"] = (min(fp) - a_y) if fp else None
            # ---- per row, armpit landmark row -> crease + 6: the open run inward from the torso edge
            y_end = int(cr[1]) + 6 if cr else a_y + 60
            cuff_in_y = float(tb["cuff"][1][1])
            rowrec, sgn = [], (1 if side == "left" else -1)
            for y in range(a_y, min(y_end, H)):
                e = edge_x[y]
                if np.isnan(e):
                    continue
                x = int(np.ceil(e)) if side == "left" else int(np.floor(e)) - 1
                gaps = {}
                for nm, cv_ in (("cur", cov["cur"]), ("nt", cov["nt"]), ("nb", cov_nb)):
                    n, xx = 0, x
                    while 0 <= xx < W and mask[y, xx] and not cv_[y, xx] and n < 60:
                        n, xx = n + 1, xx + sgn
                    gaps[nm] = n
                rowrec.append([y, round(float(e), 1), gaps["nt"], gaps["cur"], gaps["nb"]])
            rec["rows_y_edge_gap_nt_cur_noblend"] = rowrec
            body = [r for r in rowrec if r[0] > cuff_in_y]
            rec["torso_gap_max_below_cuff"] = {"nt": max([r[2] for r in body], default=0),
                                               "cur": max([r[3] for r in body], default=0),
                                               "noblend": max([r[4] for r in body], default=0)}
            rec["torso_gap_px_below_cuff"] = {"nt": sum(r[2] for r in body), "cur": sum(r[3] for r in body),
                                              "noblend": sum(r[4] for r in body)}
            # side floor pairs of this side near the armpit: target p, where the final MLS map puts q
            sp = []
            for n, (q, p_, w_) in pairs.items():
                if n.endswith(sx) and (n.startswith("sfm") or n.startswith("side_") or n.startswith("armpit")
                                       or n.startswith("smid_in") or n.startswith("cuff_in")) and p_[1] <= y_end + 40:
                    land, err = forward(m0x, m0y, q)
                    sp.append([n, [round(v, 1) for v in p_], land, round(float(np.hypot(land[0] - p_[0],
                                                                                    land[1] - p_[1])), 1)])
            rec["pairs_target_landed_miss"] = sorted(sp, key=lambda v: v[1][1])
            # ---- 13c vs current
            added = cov["c13"] & ~cov["cur"] & inbox
            by_tube = added & (k13x >= 0) & ((k13x != cmx) | (k13y != cmy))
            by_paint = added & ~by_tube
            lost = cov["cur"] & ~cov["c13"] & inbox
            n_frag = 0
            if (added & ~mask).any():
                n_frag = cv2.connectedComponents((added & ~mask).astype(np.uint8))[0] - 1
            rec["c13"] = {"added_by_tube": int(by_tube.sum()), "added_by_inpaint": int(by_paint.sum()),
                          "added_over_background": int((added & ~mask).sum()), "bg_fragments": int(n_frag),
                          "added_over_arm_overlay": int((added & keep).sum()), "lost": int(lost.sum()),
                          "inner_widen_px": run["c13"][1]["tube"][side].get("inner_widen_px")}
            results.append(rec)
            # ---- panels
            p0 = label(box.crop(rgb["nt"]), f"0 no tube #{gid} {who} {side[0].upper()} (open {rec['open_no_tube']})")
            o0 = rgb["cur"].copy()
            fig = mask & inside
            o0 = tint(o0, fig & (a0 >= 128) & src_sleeve, (255, 120, 0), 0.5)
            o0 = tint(o0, fig & (a0 >= 128) & ~src_sleeve, (0, 170, 0), 0.5)
            o0 = tint(o0, fig & (a0 < 128), (0, 0, 255), 0.5)
            pm0 = box.crop(o0)
            cnt, _ = cv2.findContours(box.crop(tube_drawn.astype(np.uint8) * 255), cv2.RETR_EXTERNAL,
                                      cv2.CHAIN_APPROX_NONE)
            cv2.drawContours(pm0, cnt, -1, (255, 255, 255), 1)
            label(pm0, "1b MLS source: blue sleeve, green torso, red none; white = tube")
            p1 = label(box.crop(rgb["cur"]), f"1 current (open {rec['open_px']})")
            g2 = cv2.cvtColor(base, cv2.COLOR_BGRA2BGR) if base.shape[2] == 4 else base.copy()
            g2[~mask] = 255
            armm = np.zeros((H, W), bool)
            for y, l, r in (arms.get(side) or {}).get("rows", []):
                armm[y, l:r + 1] = True
            p2 = box.crop(tint(g2, armm, (0, 200, 0), 0.35))
            ext = (B1 - B0) / np.linalg.norm(B1 - B0)
            cv2.line(p2, box.pt(B0 - ext * 200), box.pt(B1 + ext * 200), (255, 120, 0), 1, cv2.LINE_AA)
            cv2.line(p2, box.pt(B0), box.pt(B1), (255, 120, 0), 3, cv2.LINE_AA)
            for a_, b_ in tb["sections"]:
                cv2.line(p2, box.pt(a_), box.pt(b_), (150, 150, 150), 1, cv2.LINE_AA)
            inner = [s_[1] for s_ in tb["sections"]]
            for a_, b_ in zip(inner, inner[1:]):
                cv2.line(p2, box.pt(a_), box.pt(b_), (0, 0, 255), 2, cv2.LINE_AA)
            cv2.line(p2, box.pt(tb["cuff"][0]), box.pt(tb["cuff"][1]), (0, 0, 255), 2, cv2.LINE_AA)
            for y, e, src in erows:
                if e is not None and y % 2 == 0:
                    cv2.circle(p2, box.pt((e, y)), 2, (255, 255, 255) if src == "mask" else (0, 0, 255), -1)
                    cv2.circle(p2, box.pt((e, y)), 3, (0, 0, 0), 1)
            for n, (q, p, w_) in pairs.items():
                if n.endswith(sx) and (n.startswith("sfm") or n.startswith("side_")):
                    x, y = box.pt(p)
                    if n.startswith("sfm"):
                        cv2.rectangle(p2, (x - 5, y - 5), (x + 5, y + 5), (0, 220, 0), 2)
                    else:
                        cv2.circle(p2, (x, y), 6, (0, 220, 0), 2)
            if cr:
                cross(p2, box.pt(cr), (0, 255, 255), plus=True)
            if "armpit" + sx in pairs:
                cross(p2, box.pt(pairs["armpit" + sx][1]), (255, 255, 0))
            if f_notch:
                cross(p2, box.pt(f_notch), (255, 0, 255))
            cross(p2, box.pt(f_cin), (255, 255, 255))
            label(p2, "2 geometry")
            cols = {1: (0, 0, 255), 2: (0, 140, 255), 3: (255, 0, 0), 4: (255, 0, 255), 5: (0, 255, 255)}
            o3 = rgb["cur"].copy()
            for k, c in cols.items():
                o3[cat == k] = c
            ob = rec["open_by_owner"]
            p3 = label(box.crop(o3), f"3 open {rec['open_px']}: notch T {ob['notch_torso_side']} / tube "
                                     f"{ob['notch_tube_side']}, clr {ob['cleared']}, edge {ob['edge_lost']}")
            p4 = label(box.crop(rgb["c13"]), f"4 r14 (open {rec['open_13c']})")
            o5 = rgb["c13"].copy()
            o5[by_tube] = (255, 255, 0)
            o5[by_paint] = (255, 0, 255)
            o5[added & ~mask] = (o5[added & ~mask] * 0.45).astype(np.uint8)
            o5[lost] = (0, 255, 255)
            c13 = rec["c13"]
            p5 = label(box.crop(o5), f"5 r14: tube +{c13['added_by_tube']}, mls +{c13['added_by_inpaint']}, over bg "
                                     f"{c13['added_over_background']}, lost {c13['lost']}")
            s = run["cur"][1]["s"]
            gr = int(round(R / s))
            gb = Box(notch if notch else g_arm, r=gr, w=gW, h=gH)
            gv = gimg[:, :, :3].astype(np.float32) * (gimg[:, :, 3:4] / 255.0) + \
                np.array([255, 200, 255], np.float32) * (1 - gimg[:, :, 3:4] / 255.0)
            gv = np.pad(gv.astype(np.uint8), ((0, max(0, 2 * gr - gH)), (0, max(0, 2 * gr - gW)), (0, 0)),
                        constant_values=255)
            p6 = gb.crop(gv)
            A0 = (f_(glm["shoulder"][f"{side}_x"]), f_(glm["shoulder"]["y"]))
            cv2.line(p6, gb.pt(A0), gb.pt(g_arm), (255, 120, 0), 2, cv2.LINE_AA)
            cross(p6, gb.pt(g_arm), (255, 255, 0))
            if notch:
                cross(p6, gb.pt(notch), (255, 0, 255))
            cross(p6, gb.pt(g_cin), (255, 255, 255))
            label(p6, f"6 garment #{gid} (lm - notch {rec['garment_lm_minus_notch']})")
            rows_img.append(np.hstack([p0, p1, pm0, p2, p3, p4, p5, p6]))
            print("GAP", gid, who, side[0], "cuff_in_y", round(cuff_in_y), "crease", cr, "max", rec["torso_gap_max_below_cuff"],
                  "px", rec["torso_gap_px_below_cuff"], "blend", info["side_floor_mask"].get("blend_px"),
                  "patched", info["side_floor_mask"].get("patched_px"))
        cv2.imwrite(f"{OUT}/debug_armpit14_{gid}_{who}.png", np.vstack(rows_img))

with open(f"{OUT}/debug_armpit14.json", "w") as fh:
    json.dump(results, fh, indent=1, default=str)
lines = ["| garment | avatar | side | open no tube / current (above cuff + torso side below; of it covered without tube) / r14 | notch torso side | notch tube side | cleared | "
         "edge lost | notch lands - crease (dx, dy) | cuff_inner below notch (garment px) | torso edge - crease x | "
         "first sfm pair below armpit | r14 tube / mls / over bg / lost |", "|" + "---|" * 13]
for r in results:
    ob, c = r["open_by_owner"], r["c13"]
    nm = r["notch_minus_crease"]
    lines.append(
        f"| #{r['garment']} | {r['who']} | {r['side'][0].upper()} | {r['open_no_tube']} / {r['open_px']} "
        f"({r['open_above_cuff']} + {r['open_torso_side_below_cuff']}; nt covers {r['open_cur_that_no_tube_covers']}) / "
        f"{r['open_13c']} | {ob['notch_torso_side']} | {ob['notch_tube_side']} | {ob['cleared']} | {ob['edge_lost']} | "
        f"{'-' if nm is None else f'{nm[0]:+.0f}, {nm[1]:+.0f}'} | {r['garment_cuff_inner_below_notch_px']} | "
        f"{r.get('torso_edge_minus_crease_x_at_crease_row')} | {r['first_side_floor_pair_below_armpit_px']} | "
        f"{c['added_by_tube']} / {c['added_by_inpaint']} / {c['added_over_background']} / {c['lost']} |")
with open(f"{OUT}/table_debug_armpit14.md", "w") as fh:
    fh.write("\n".join(lines) + "\n")
print("\n".join(lines))
