"""Benchmark only (not the production path): the WHOLE T-shirt warped by ONE rigid MLS field.

    warp(garment_rgba, garment_lm, body_lm, out_size=(600, 1200), base=None, alpha=1.0) -> (RGBA, info)

Method (Schaefer et al. 2006, rigid MLS, inverse): control points p = body (canvas) points, q = garment points,
paired by name. For every output pixel v: weights w_i = k_i / |p_i - v|^(2 alpha), p*, q* weighted centroids, the
best rotation of the p-hat onto the q-hat, f(v) = R (v - p*) + q*. Rigid MLS has no scale, so the garment points are
pre-scaled by s = body shoulder width / garment shoulder width and f is divided by s afterwards. The field is
computed on a grid at 1/4 resolution, upsampled (bilinear) and applied with one cv2.remap (premultiplied).

Control points (garment -> body), see docs/06 "MLS single-field benchmark":
  neck_l / neck_r / neck_c  collar edges + collar bottom centre (auto-detected), weight NECK_WEIGHT, targets by
                            the uniform scale only (centred on the body's shoulder line, like production)
  shoulder_l/r              garment shoulder seam -> body shoulder point
  armpit_l/r                garment underarm corner (auto: deepest convexity defect) -> body armpit edge
  chest_l/r, waist_l/r      -> body chest / waist edges
  hem_l/r                   -> hem_y = hip + 0.35 (crotch - hip) <= crotch - 10; half-width = garment hem/waist
                            ratio x body waist half-width, at least the body's hip half-width
  cuff_out/cuff_in (l, r)   sleeve cuff corners (auto) -> along the arm direction (body shoulder -> arm centre at
                            armpit + 10 % of the figure height), length = garment sleeve length / garment
                            shoulder-to-hem x body shoulder-to-hem, cuff width x torso width ratio, perpendicular
Pairs that break the row order or left/right order on either side are rejected before warping (listed in info).
After the warp: edge fix once on the outer contour; the production neck handling (inner back collar cleared,
head/neck overlay on top with the collar band kept) and the hands/forearms overlay.
"""
import time

import cv2
import numpy as np

from apps.tryon_engine import warp as prod

NECK_WEIGHT = 5.0
GRID = 4
HIP_FRACTION, CROTCH_MARGIN = 0.35, 10.0
ROWS = ("shoulder", "armpit", "chest", "waist", "hem")


def _f(v):
    return float(v)


# ---------- garment landmark auto-detection (never invented: None when not found) ----------

def detect_neck(alpha, g, img):
    """(left edge, right edge, bottom centre) of the collar in garment px, or None.
    Crew neck with a darker inner back: production's back_collar_geometry. Otherwise the top profile: the highest
    pixel on each side of the centre (the collar tips) and the centre column's top (a V or scoop dip), accepted only
    if the dip is at least 4 % of the shoulder span below the tips."""
    geo = prod.back_collar_geometry(alpha, g, img)
    if geo:
        rim = geo["hw"] / (1 - prod.OPENING_INSET)
        return ((geo["cx"] - rim, geo["y0"]), (geo["cx"] + rim, geo["y0"]),
                (geo["cx"], geo["y0"] + geo["depth"])), "crew (inner back)"
    sl, sr = _f(g["shoulder"]["left_x"]), _f(g["shoulder"]["right_x"])
    cx = int(round((sl + sr) / 2))
    top = np.where(alpha.any(axis=0), alpha.argmax(axis=0), 10 ** 6).astype(np.float64)
    half = int(0.35 * (sr - sl))
    left, right = top[cx - half:cx], top[cx + 1:cx + half + 1]
    if not len(left) or not len(right):
        return None, "failed"
    xl = cx - half + int(np.argmin(left))
    xr = cx + 1 + int(np.argmin(right))
    tip = max(top[xl], top[xr])
    bottom = top[cx - 2:cx + 3].max()
    if bottom - tip < 0.04 * (sr - sl) or bottom >= 10 ** 6:
        return None, "failed (flat top, no darker inner back)"
    kind = "V" if (bottom - tip) > 0.6 * (xr - xl) / 2 else "scoop"
    return ((float(xl), float(top[xl])), (float(xr), float(top[xr])), (float(cx), float(bottom))), kind


def detect_armpits(alpha, g):
    """{side: (x, y)} underarm corners: deepest convexity defect of the outline per side between the shoulder and
    waist rows. Missing side = not found."""
    cs, _ = cv2.findContours(alpha.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cs:
        return {}
    c = max(cs, key=cv2.contourArea)
    hull = cv2.convexHull(c, returnPoints=False)
    try:
        defects = cv2.convexityDefects(c, hull)
    except cv2.error:
        return {}
    if defects is None:
        return {}
    cx = (_f(g["shoulder"]["left_x"]) + _f(g["shoulder"]["right_x"])) / 2
    y0, y1 = _f(g["shoulder"]["y"]), _f(g["waist"]["y"])
    best = {}
    for s_, e_, far, depth in defects[:, 0]:
        x, y = c[far][0]
        if not y0 < y < y1:
            continue
        side = "left" if x < cx else "right"
        if depth > best.get(side, (0, None))[0]:
            best[side] = (depth, (float(x), float(y)))
    return {k: v[1] for k, v in best.items() if v[0] > 256 * 3}  # at least 3 px deep


def detect_cuff(alpha, g, side, armpit):
    """(outer corner, inner corner) of one sleeve cuff, garment px, or None. Sleeve pixels = outward of the line
    shoulder -> armpit, not below the sleeve end by more than 30 % of the sleeve length; the cuff band = the 3 % of
    them farthest along shoulder -> sleeve_end; its two extremes across the axis are the corners (outer = the one on
    the shoulder-line side)."""
    S = np.array([_f(g["shoulder"][f"{side}_x"]), _f(g["shoulder"]["y"])])
    E = np.array([_f(g["sleeve_end"][side]["x"]), _f(g["sleeve_end"][side]["y"])])
    A = np.asarray(armpit if armpit is not None else (_f(g["chest"][f"{side}_x"]), _f(g["chest"]["y"])), float)
    u = E - S
    L = float(np.linalg.norm(u))
    if L < 5:
        return None
    u /= L
    t = A - S
    nrm = np.array([t[1], -t[0]]) / max(float(np.linalg.norm(t)), 1e-6)
    if (nrm[0] > 0) == (side == "left"):
        nrm = -nrm
    ys, xs = np.nonzero(alpha)
    P = np.stack([xs, ys], 1).astype(np.float64)
    keep = ((P - S) @ nrm > 0) & (ys <= E[1] + 0.3 * L)
    P = P[keep]
    if len(P) < 50:
        return None
    along = (P - S) @ u
    band = P[along >= np.percentile(along, 97)]
    if len(band) < 5:
        return None
    perp = np.array([-u[1], u[0]])
    across = (band - S) @ perp
    a, b = band[np.argmin(across)], band[np.argmax(across)]
    # outer = the corner farther from the garment's centre line across the axis (the sleeve's top edge side)
    cx = (_f(g["shoulder"]["left_x"]) + _f(g["shoulder"]["right_x"])) / 2
    out, inn = (a, b) if abs(a[0] - cx) > abs(b[0] - cx) else (b, a)
    if (out - S) @ nrm < (inn - S) @ nrm:  # outer must be further out of the armhole line
        out, inn = inn, out
    return (tuple(out), tuple(inn))


# ---------- body targets ----------

def body_hem_y(lm):
    hip, crotch = _f(lm["hip"]["y"]), _f(lm["crotch"]["y"])
    return min(hip + HIP_FRACTION * (crotch - hip), crotch - CROTCH_MARGIN)


def arm_direction(mask, lm, side):
    """Unit vector body shoulder point -> arm centre at armpit + 10 % of the figure height, or None."""
    arms = prod.find_arms(mask, lm)
    arm = arms.get(side)
    if not arm:
        return None
    fig_h = _f(lm["foot_bottom"]["y"]) - _f(lm["head_top"]["y"])
    y = _f(lm["armpit"]["y"]) + 0.1 * fig_h
    rows = [r for r in arm["rows"] if abs(r[0] - y) <= 1]
    if not rows:
        return None
    c = np.array([(rows[0][1] + rows[0][2]) / 2, rows[0][0]], float)
    S = np.array([_f(lm["shoulder"][f"{side}_x"]), _f(lm["shoulder"]["y"])])
    d = c - S
    return d / np.linalg.norm(d)


def control_points(gimg, glm, blm, mask):
    """(pairs {name: (q garment, p body, weight)}, auto {name: how}, rejected [names], s)."""
    alpha = gimg[:, :, 3] > 128
    auto, rejected, pairs = {}, [], {}
    g_sl, g_sr, g_sy = _f(glm["shoulder"]["left_x"]), _f(glm["shoulder"]["right_x"]), _f(glm["shoulder"]["y"])
    a_sl, a_sr, a_sy = _f(blm["shoulder"]["left_x"]), _f(blm["shoulder"]["right_x"]), _f(blm["shoulder"]["y"])
    s = (a_sr - a_sl) / (g_sr - g_sl)
    g_cx, a_cx = (g_sl + g_sr) / 2, (a_sl + a_sr) / 2
    uni = lambda q: (a_cx + (q[0] - g_cx) * s, a_sy + (q[1] - g_sy) * s)  # noqa: E731

    neck, kind = detect_neck(alpha, glm, gimg)
    auto["neck"] = kind
    if neck is None:
        return None, auto, ["neck"], s
    for name, q in zip(("neck_l", "neck_r", "neck_c"), neck):
        pairs[name] = (q, uni(q), NECK_WEIGHT)
    pits = detect_armpits(alpha, glm)
    auto["armpit"] = {k: tuple(round(c, 1) for c in v) for k, v in pits.items()} or "failed"
    hem_y = body_hem_y(blm)
    g_waist_w = _f(glm["waist"]["right_x"]) - _f(glm["waist"]["left_x"])
    g_hem_w = _f(glm["hem"]["right_x"]) - _f(glm["hem"]["left_x"])
    b_waist_w = _f(blm["waist"]["right_x"]) - _f(blm["waist"]["left_x"])
    b_hip_w = _f(blm["hip"]["right_x"]) - _f(blm["hip"]["left_x"])
    hem_hw = max(g_hem_w / g_waist_w * b_waist_w, b_hip_w) / 2
    b_hem_cx = (_f(blm["hip"]["left_x"]) + _f(blm["hip"]["right_x"])) / 2
    for i, side in enumerate(("left", "right")):
        sx = "_l" if side == "left" else "_r"
        pairs["shoulder" + sx] = ((_f(glm["shoulder"][f"{side}_x"]), g_sy),
                                  (_f(blm["shoulder"][f"{side}_x"]), a_sy), 1.0)
        if side in pits:
            pairs["armpit" + sx] = (pits[side], (_f(blm["armpit"][f"{side}_x"]), _f(blm["armpit"]["y"])), 1.0)
        for k in ("chest", "waist"):
            pairs[k + sx] = ((_f(glm[k][f"{side}_x"]), _f(glm[k]["y"])), (_f(blm[k][f"{side}_x"]), _f(blm[k]["y"])), 1.0)
        pairs["hem" + sx] = ((_f(glm["hem"][f"{side}_x"]), _f(glm["hem"]["y"])),
                             (b_hem_cx + (-hem_hw if side == "left" else hem_hw), hem_y), 1.0)
    # sleeves
    g_len = _f(glm["hem"]["y"]) - g_sy
    b_len = hem_y - a_sy
    torso_ratio = (_f(blm["chest"]["right_x"]) - _f(blm["chest"]["left_x"])) / \
        (_f(glm["chest"]["right_x"]) - _f(glm["chest"]["left_x"]))
    for side in ("left", "right"):
        sx = "_l" if side == "left" else "_r"
        cuff = detect_cuff(alpha, glm, side, pits.get(side))
        d = arm_direction(mask, blm, side)
        auto["cuff" + sx] = "auto" if cuff else "failed"
        if cuff is None or d is None:
            rejected.append(f"cuff{sx} ({'no cuff' if cuff is None else 'arm not found'})")
            continue
        out, inn = np.array(cuff[0]), np.array(cuff[1])
        S_g = np.array([_f(glm["shoulder"][f"{side}_x"]), g_sy])
        mid = (out + inn) / 2
        L_b = float(np.linalg.norm(mid - S_g)) / g_len * b_len
        S_b = np.array([_f(blm["shoulder"][f"{side}_x"]), a_sy])
        c = S_b + d * L_b
        w = float(np.linalg.norm(out - inn)) * torso_ratio
        perp = np.array([-d[1], d[0]])
        if (perp[0] > 0) != (side == "right"):  # outward = away from the body centre
            perp = -perp
        pairs["cuff_out" + sx] = (tuple(out), tuple(c + perp * w / 2), 1.0)
        pairs["cuff_in" + sx] = (tuple(inn), tuple(c - perp * w / 2), 1.0)
    rejected += validate(pairs)
    return pairs, auto, rejected, s


def validate(pairs):
    """Removes (in place) and returns the pairs that break the order on either side: per side the rows
    shoulder < armpit < chest < waist < hem (y), and per row left x < right x; cuffs below their shoulder.
    A later row that is not below the last accepted one is rejected (so it cannot cross)."""
    bad = []
    for sx in ("_l", "_r"):
        last = None
        for r in ROWS:
            k = r + sx
            if k not in pairs:
                continue
            q, p, _ = pairs[k]
            if last is not None and not (q[1] > last[0][1] + 1 and p[1] > last[1][1] + 1):
                bad.append(k)
                del pairs[k]
                continue
            last = (q, p)
        for k in ("cuff_out" + sx, "cuff_in" + sx):
            if k in pairs and "shoulder" + sx in pairs:
                if not (pairs[k][0][1] > pairs["shoulder" + sx][0][1] and pairs[k][1][1] > pairs["shoulder" + sx][1][1]):
                    bad.append(k)
                    del pairs[k]
    for r in ROWS + ("neck",):
        kl, kr = (r + "_l", r + "_r")
        if kl in pairs and kr in pairs:
            ql, pl, _ = pairs[kl]
            qr, pr, _ = pairs[kr]
            if not (ql[0] < qr[0] and pl[0] < pr[0]):
                bad += [kl, kr]
                del pairs[kl], pairs[kr]
    return bad


# ---------- MLS ----------

def mls_rigid_inverse(p, q, k, V, alpha):
    """Rigid MLS f: body -> (scaled) garment at the points V (M x 2). p, q: N x 2, k: N weights."""
    d = V[:, None, :] - p[None, :, :]
    d2 = np.maximum((d ** 2).sum(-1), 1e-6)
    w = k[None, :] / d2 ** alpha
    W = w.sum(1, keepdims=True)
    ps = (w[..., None] * p[None]).sum(1) / W
    qs = (w[..., None] * q[None]).sum(1) / W
    ph = p[None] - ps[:, None]
    qh = q[None] - qs[:, None]
    dot = (w * (ph * qh).sum(-1)).sum(1)
    crs = (w * (ph[..., 0] * qh[..., 1] - ph[..., 1] * qh[..., 0])).sum(1)
    th = np.arctan2(crs, dot)
    c, s_ = np.cos(th), np.sin(th)
    vx, vy = V[:, 0] - ps[:, 0], V[:, 1] - ps[:, 1]
    return np.stack([c * vx - s_ * vy + qs[:, 0], s_ * vx + c * vy + qs[:, 1]], 1)


def warp(garment_rgba, garment_lm, body_lm, out_size=(600, 1200), base=None, alpha=1.0):
    """RGBA garment layer on the canvas + info (pairs, auto, rejected, maps, runtime). base (BGRA avatar) is used
    for the arm direction; without it the sleeves get no control points."""
    t0 = time.perf_counter()
    W, H = out_size
    mask = prod.figure_mask(cv2.resize(prod._bgra(base), (W, H))) if base is not None else np.zeros((H, W), bool)
    img = prod._bgra(garment_rgba)
    pairs, auto, rejected, s = control_points(img, garment_lm, body_lm, mask)
    info = {"auto": auto, "rejected": rejected, "s": s}
    if pairs is None:
        info["skipped"] = True
        return None, info
    names = list(pairs)
    q = np.array([pairs[n][0] for n in names], float) * s
    p = np.array([pairs[n][1] for n in names], float)
    k = np.array([pairs[n][2] for n in names], float)
    gy, gx = np.mgrid[0:H + GRID:GRID, 0:W + GRID:GRID].astype(np.float64)
    V = np.stack([gx.ravel(), gy.ravel()], 1)
    F = mls_rigid_inverse(p, q, k, V, alpha) / s
    mx = cv2.resize(F[:, 0].reshape(gx.shape).astype(np.float32), None, fx=GRID, fy=GRID,
                    interpolation=cv2.INTER_LINEAR)[:H, :W]
    my = cv2.resize(F[:, 1].reshape(gx.shape).astype(np.float32), None, fx=GRID, fy=GRID,
                    interpolation=cv2.INTER_LINEAR)[:H, :W]
    f = img.astype(np.float32)
    f[:, :, :3] *= f[:, :, 3:4] / 255.0
    out = cv2.remap(f, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    a = out[:, :, 3:4] / 255.0
    out[:, :, :3] = np.where(a > 0, out[:, :, :3] / np.maximum(a, 1e-6), 0)
    layer = np.clip(np.rint(out), 0, 255).astype(np.uint8)
    layer = prod.remove_halo(layer, outer_only=True)  # edge fix, once, outer contour
    info.update({"pairs": pairs, "map": (mx, my), "runtime": time.perf_counter() - t0})
    # neck: the production handling (opening via the same uniform scale the neck anchors use)
    geo = prod.back_collar_geometry(img[:, :, 3] > 128, garment_lm, img)
    if geo:
        g_cx = (_f(garment_lm["shoulder"]["left_x"]) + _f(garment_lm["shoulder"]["right_x"])) / 2
        a_cx = (_f(body_lm["shoulder"]["left_x"]) + _f(body_lm["shoulder"]["right_x"])) / 2
        g_sy, a_sy = _f(garment_lm["shoulder"]["y"]), _f(body_lm["shoulder"]["y"])
        info["neck_opening"] = {"cx": a_cx + (geo["cx"] - g_cx) * s, "hw": geo["hw"] * s,
                                "y0": a_sy + (geo["y0"] - g_sy) * s, "depth": geo["depth"] * s}
        layer = prod.clear_back_collar(layer, info["neck_opening"], body_lm)
    return layer, info


def composite(base, layer, body_lm, info, H=1200, W=600):
    """Avatar -> MLS garment layer -> head/neck (production overlay, collar band kept) -> hands/forearms."""
    base = cv2.resize(prod._bgra(base), (W, H))
    mask = prod.figure_mask(base)
    canvas = prod._alpha_composite(base.copy(), layer)
    head = prod.head_neck_overlay(mask, body_lm, prod.NECK_FEATHER_FIX, info.get("neck_opening"))[:, :, None]
    canvas = np.clip(np.rint(canvas.astype(np.float32) * (1 - head) + base.astype(np.float32) * head),
                     0, 255).astype(np.uint8)
    arms = prod.find_arms(mask, body_lm)
    hems = {}
    for side, sx in (("left", "_l"), ("right", "_r")):
        if "cuff_out" + sx in info.get("pairs", {}):
            a_, b_ = np.array(info["pairs"]["cuff_out" + sx][1]), np.array(info["pairs"]["cuff_in" + sx][1])
            sh = np.array([_f(body_lm["shoulder"][f"{side}_x"]), _f(body_lm["shoulder"]["y"])])
            hems[side] = (np.float32(a_), np.float32(b_), sh)
    keep = prod.arm_overlay_mask(mask, arms, hems)
    canvas[keep] = base[keep]
    white = np.full((H, W, 3), 255, np.float32)
    a = canvas[:, :, 3:4].astype(np.float32) / 255.0
    return (canvas[:, :, :3].astype(np.float32) * a + white * (1 - a)).astype(np.uint8)


def metrics(layer, info, body_lm):
    """fold ratio, min/max local scale (+ where), sleeve px above the shoulder slope line, floating px."""
    mx, my = info["map"]
    on = layer[:, :, 3] > 128
    dxx, dxy = np.gradient(mx, axis=1), np.gradient(mx, axis=0)
    dyx, dyy = np.gradient(my, axis=1), np.gradient(my, axis=0)
    det = dxx * dyy - dxy * dyx  # inverse map (dst -> src) Jacobian
    fold = float((det[on] < 0).mean()) if on.any() else 0.0
    # forward local scale = 1 / singular values of the inverse Jacobian
    ok = on & (det > 1e-3)  # folded or degenerate pixels (stretch -> infinity) are counted by `fold`, not here
    a, b, c, d = dxx[ok], dxy[ok], dyx[ok], dyy[ok]
    ss = a * a + b * b + c * c + d * d
    disc = np.sqrt(np.maximum((a * a + b * b - c * c - d * d) ** 2 + 4 * (a * c + b * d) ** 2, 0))
    s1, s2 = np.sqrt((ss + disc) / 2), np.sqrt(np.maximum((ss - disc) / 2, 1e-12))
    fmax, fmin = 1 / s2, 1 / s1  # forward stretch max / min (dst px per garment px)
    ys, xs = np.nonzero(ok)
    imax, imin = int(np.argmax(fmax)), int(np.argmin(fmin))
    at_min, at_max = _region(xs[imin], ys[imin], body_lm), _region(xs[imax], ys[imax], body_lm)
    # sleeve pixels above the shoulder slope line (body: collar edge target -> shoulder point, extended outward)
    ys, xs = np.nonzero(on)
    above = 0
    for sx, side in (("_l", "left"), ("_r", "right")):
        if "neck" + sx not in info["pairs"]:
            continue
        (x0, y0), (x1, y1) = info["pairs"]["neck" + sx][1], (_f(body_lm["shoulder"][f"{side}_x"]),
                                                           _f(body_lm["shoulder"]["y"]))
        m = (y1 - y0) / (x1 - x0)
        out = (xs < x1 - 4) if side == "left" else (xs > x1 + 4)
        above += int((out & ((y0 + m * (xs + 0.5 - x0)) - (ys + 0.5) > 1)).sum())
    n, lab, st, _ = cv2.connectedComponentsWithStats(on.astype(np.uint8), connectivity=8)
    floating = int(st[1:, 4].sum() - st[1:, 4].max()) if n > 2 else 0
    deg = int((on & (np.abs(det) <= 1e-3)).sum())
    return {"fold": fold, "degenerate_px": deg, "scale_min": float(fmin.min()), "scale_min_at": at_min,
            "scale_max": float(fmax.max()), "scale_max_at": at_max,
            "scale_p1": float(np.percentile(fmin, 1)), "scale_p99": float(np.percentile(fmax, 99)),
            "above_line": above, "floating": floating}


def _region(x, y, lm):
    side = "left" if x < _f(lm["shoulder"]["left_x"]) * 0.5 + _f(lm["shoulder"]["right_x"]) * 0.5 else "right"
    for name in ("shoulder", "armpit", "chest", "waist", "hip"):
        if y < _f(lm[name]["y"]) + 15:
            break
    inside = _f(lm["armpit"]["left_x"]) <= x <= _f(lm["armpit"]["right_x"])
    return f"{'torso' if inside else 'sleeve'} {side} near {name} ({int(x)},{int(y)})"
