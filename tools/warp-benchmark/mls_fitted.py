"""Benchmark only (not the production path): fitted T-shirts on the single-field MLS warp, round 6 (docs/06).

    warp(garment_rgba, garment_lm, body_lm, out_size=(600, 1200), k=1.0, base=None, info=None) -> RGBA

Reuses mls_landmarks.warp (alignment, rigid MLS, validation, edge fix, neck handling) with a `retarget` hook:
1. Cuffs: width = min(garment cuff width x torso ratio, arm width (perpendicular, from the mask at the cuff position)
   x CUFF_ARM_EASE); cuff centre on the arm centre line at that row, cuff line perpendicular to the arm direction.
2. With that width the inner corner lands on (or ARM_EASE past) the arm's inner edge and the outer corner on its outer
   edge, so the sleeve underside runs from the armpit along the arm.
3. Hem: hem_l/r x = the torso silhouette edges at hem_y (mask run through the crotch axis) widened by HEM_EASE of its
   width; falls back to the landmark body span at hem_y (+ HEM_EASE) when the run is merged with the arms. Plus a hem
   centre pair `hem_c` (garment hem centre -> body hem centre at hem_y).
4. Shoulders: target = body shoulder point, moved outward to the acromion (outer silhouette edge a few rows below the
   shoulder line) when that edge is further out.
5. Edge fix: after the 2 px erosion (mls_landmarks), partial-alpha pixels below HARD_EDGE are removed (no soft specks).
Per-point k: neck and shoulder 1.0 (anchors); armpit, chest, waist, hem, cuff = the run's k.
"""
import numpy as np

import mls
import mls_landmarks as ml
from apps.tryon_engine import warp as prod

CUFF_ARM_EASE = 1.1
HEM_EASE = 0.02
HARD_EDGE = int(0.9 * 255)
ACROMION_ROWS = 4  # px below the shoulder line where the outer silhouette edge is read
_f = float


def k_map_for(k):
    return {"neck": 1.0, "shoulder": 1.0, "armpit": k, "chest": k, "waist": k, "hem": k, "cuff": k}


ARM_FIT_ROWS = 20  # first separated arm rows below the armpit used for the arm centre line and width


def _arm_at(arms, side, y):
    """(centre x, horizontal width) of the arm at row y, or None. Short sleeves end above the row where the arm
    separates from the torso in the mask, so the centre line is a straight fit through the first ARM_FIT_ROWS arm rows
    (extrapolated up to y) and the width is their median."""
    rows = ((arms.get(side) or {}).get("rows") or [])[:ARM_FIT_ROWS]
    if len(rows) < 5:
        return None
    ys = np.array([r[0] for r in rows], float)
    cs = np.array([(r[1] + r[2]) / 2 for r in rows], float)
    a, b = np.polyfit(ys, cs, 1)
    return float(a * y + b), float(np.median([r[2] - r[1] for r in rows]))


def _torso_run(mask, y, axis):
    yi = min(max(int(round(y)), 0), mask.shape[0] - 1)
    return next((q for q in prod._runs(mask[yi]) if q[0] <= axis <= q[1]), None)


def retarget(pairs, ctx):
    glm, blm, mask, fit, hem_y = ctx["glm"], ctx["blm"], ctx["mask"], ctx["fit"], ctx["hem_y"]
    arms = prod.find_arms(mask, blm) if mask.any() else {}
    a_sy = _f(blm["shoulder"]["y"])
    # 4. shoulders -> body shoulder point, out to the acromion
    for side, sx, out in (("left", "_l", -1), ("right", "_r", 1)):
        bx = _f(blm["shoulder"][f"{side}_x"])
        yi = int(round(a_sy)) + ACROMION_ROWS
        if mask.any() and 0 <= yi < mask.shape[0]:
            runs = prod._runs(mask[yi])
            if runs:
                edge = runs[0][0] if side == "left" else runs[-1][1]
                if (edge - bx) * out > 0:
                    bx = float(edge)
        q = pairs["shoulder" + sx][0]
        pairs["shoulder" + sx] = (q, fit(q, (bx, a_sy), "shoulder"), 1.0)
    # 3. hem from the silhouette at hem_y, plus the hem centre
    axis = prod._crotch_x(blm)
    bl, br = prod.body_span(blm, hem_y)
    run = _torso_run(mask, hem_y, axis) if mask.any() else None
    if run and run[1] - run[0] <= 1.3 * (br - bl):
        bl, br = float(run[0]), float(run[1] + 1)
    e = HEM_EASE * (br - bl)
    g_hy = _f(glm["hem"]["y"])
    for side, sx, bx in (("left", "_l", bl - e), ("right", "_r", br + e)):
        q = (_f(glm["hem"][f"{side}_x"]), g_hy)
        pairs["hem" + sx] = (q, fit(q, (bx, hem_y), "hem"), 1.0)
    q = ((_f(glm["hem"]["left_x"]) + _f(glm["hem"]["right_x"])) / 2, g_hy)
    pairs["hem_c"] = (q, fit(q, ((bl + br) / 2, hem_y), "hem"), 1.0)
    # 1 + 2. cuffs on the arm
    torso_ratio = (_f(blm["chest"]["right_x"]) - _f(blm["chest"]["left_x"])) / \
        (_f(glm["chest"]["right_x"]) - _f(glm["chest"]["left_x"]))
    for side, sx in (("left", "_l"), ("right", "_r")):
        if "cuff_out" + sx not in pairs:
            continue
        d = mls.arm_direction(mask, blm, side)
        out_q, in_q = pairs["cuff_out" + sx][0], pairs["cuff_in" + sx][0]
        # cuff distance along the arm: the round-2 rule (garment sleeve length / shoulder-to-hem x body's)
        g_sy = _f(glm["shoulder"]["y"])
        S_g = np.array([_f(glm["shoulder"][f"{side}_x"]), g_sy])
        g_len = _f(glm["hem"]["y"]) - g_sy
        L_b = float(np.linalg.norm((np.array(out_q) + np.array(in_q)) / 2 - S_g)) / g_len * (hem_y - a_sy)
        c = np.array([_f(blm["shoulder"][f"{side}_x"]), a_sy]) + d * L_b
        at = _arm_at(arms, side, c[1])
        if at is None:
            ctx["rejected"].append(f"cuff{sx} (arm not found: round-2 cuff targets kept)")
            continue
        c = np.array([at[0], c[1]])  # on the arm centre line
        arm_w = at[1] * abs(d[1])  # perpendicular arm width
        w = min(float(np.linalg.norm(np.array(out_q) - np.array(in_q))) * torso_ratio, arm_w * CUFF_ARM_EASE)
        perp = np.array([-d[1], d[0]])
        if (perp[0] > 0) != (side == "right"):
            perp = -perp
        pairs["cuff_out" + sx] = (out_q, fit(out_q, c + perp * w / 2, "cuff"), 1.0)
        pairs["cuff_in" + sx] = (in_q, fit(in_q, c - perp * w / 2, "cuff"), 1.0)
    # hem centre must stay between the hem corners on both sides (never a crossing pair)
    hl, hr, hc = pairs["hem_l"], pairs["hem_r"], pairs["hem_c"]
    if not all(hl[i][0] < hc[i][0] < hr[i][0] for i in (0, 1)):
        del pairs["hem_c"]
        ctx["rejected"].append("hem_c")


def warp(garment_rgba, garment_lm, body_lm, out_size=(600, 1200), k=1.0, base=None, info=None):
    layer = ml.warp(garment_rgba, garment_lm, body_lm, out_size, k=k, k_map=k_map_for(k), base=base, info=info,
                    retarget=retarget)
    if layer is not None:
        layer = layer.copy()
        a = layer[:, :, 3]
        a[a < HARD_EDGE] = 0  # 5. no soft specks after the erosion
    return layer


# ---------- metrics (round 6) ----------

def _arm_beyond_cuff(mask, blm, info):
    """Arm pixels (runs found by find_arms below the armpit) further along the arm than the cuff target midpoint."""
    out = np.zeros(mask.shape, bool)
    arms = prod.find_arms(mask, blm)
    for side, sx in (("left", "_l"), ("right", "_r")):
        arm, pr = arms.get(side), info["pairs"]
        if not arm or "cuff_out" + sx not in pr:
            continue
        S = np.array([_f(blm["shoulder"][f"{side}_x"]), _f(blm["shoulder"]["y"])])
        m = (np.array(pr["cuff_out" + sx][1]) + np.array(pr["cuff_in" + sx][1])) / 2
        d = (m - S) / max(np.linalg.norm(m - S), 1e-6)
        lim = float((m - S) @ d)
        for y, l, r in arm["rows"]:
            xs = np.arange(int(l), int(r) + 1)
            far = (xs - S[0]) * d[0] + (y - S[1]) * d[1] > lim
            out[int(y), xs[far]] = True
    return out


def coverage_metrics(layer, base_mask, info, blm):
    """uncovered: body px between the shoulder line and the hem row not covered by the garment, arms below the cuff
    excluded; excess: garment px outside the body silhouette dilated by 2 % of the shoulder width (ease band);
    gap: non-garment px between the sleeve and the torso below the armpit (two garment runs on one side of a row);
    hem_curve: max |y deviation| of the garment's bottom edge from the straight line between its ends (central 90 %)."""
    import cv2
    cover = layer[:, :, 3] >= 128
    H, W = cover.shape
    span = _f(blm["shoulder"]["right_x"]) - _f(blm["shoulder"]["left_x"])
    hem_y = info["pairs"]["hem_l"][1][1] if "hem_l" in info["pairs"] else mls.body_hem_y(blm)
    band = np.zeros_like(cover)
    band[int(_f(blm["shoulder"]["y"])):int(hem_y) + 1] = True
    uncovered = int((band & base_mask & ~cover & ~_arm_beyond_cuff(base_mask, blm, info)).sum())
    kpx = max(int(0.02 * span), 1) * 2 + 1
    near = cv2.dilate(base_mask.astype(np.uint8), np.ones((kpx, kpx), np.uint8)) > 0
    excess = int((cover & ~near).sum())
    axis = prod._crotch_x(blm)
    gap = 0
    y0 = int(_f(blm["armpit"]["y"])) + 1
    for sx, side in (("_l", "left"), ("_r", "right")):
        if "cuff_in" + sx not in info["pairs"]:
            continue
        y1 = int(info["pairs"]["cuff_in" + sx][1][1])
        for y in range(y0, min(y1, H - 1) + 1):
            runs = [q for q in prod._runs(cover[y]) if (q[1] < axis if side == "left" else q[0] > axis)
                    or q[0] <= axis <= q[1]]
            if len(runs) >= 2:
                a, b = (runs[0], runs[1]) if side == "left" else (runs[-2], runs[-1])
                gap += max(b[0] - a[1] - 1, 0)
    curve = None
    if "hem_l" in info["pairs"]:
        xl, xr = info["pairs"]["hem_l"][1][0], info["pairs"]["hem_r"][1][0]
        m = 0.05 * (xr - xl)
        xs = np.arange(int(xl + m), int(xr - m) + 1)
        xs = xs[(xs >= 0) & (xs < W)]
        bottoms = []
        for x in xs:
            col = np.nonzero(cover[:, x])[0]
            bottoms.append(col[-1] if len(col) else np.nan)
        b = np.array(bottoms, float)
        if len(b) > 2 and not np.isnan(b[[0, -1]]).any():
            line = b[0] + (b[-1] - b[0]) * (xs - xs[0]) / max(xs[-1] - xs[0], 1)
            curve = round(float(np.nanmax(np.abs(b - line))), 1)
    return {"uncovered_px": uncovered, "excess_px": excess, "gap_px": gap, "hem_curve_px": curve}
