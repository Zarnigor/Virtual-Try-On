"""MLS T-shirt warp (setting TRYON_WARP = "mls", docs/06 "MLS engine", docs/09 #98). Ported from the benchmark in
tools/warp-benchmark/ at commit c3f6883 (mls.py, mls_landmarks.py, mls_fitted.py); nothing here imports tools/.

The WHOLE T-shirt is warped by ONE rigid moving-least-squares field (Schaefer et al. 2006, inverse): control points
p = body targets, q = garment landmarks, paired by name; f(v) = R (v - p*) + q* with the weighted best rotation.
Rigid MLS has no scale, so the garment points are pre-scaled by s = body / garment shoulder width. The field is
computed on a 1/4 grid, upsampled and applied with one cv2.remap (premultiplied alpha).

Alignment: uniform scale s + translation (shoulder-line centres together). Each target = aligned point + k x (body
point - aligned point), k per group and axis (`k_map`). fit_mode (docs/09 #93, #96):
- keep_shape -> preset A (PRESET_A): own proportions, anchors fit; chest pair not used when chest is above the armpit.
- adapt -> the fitted-garment targets (round 7) at k 1.0: cuffs on the arm, hem from the silhouette + hem centre,
  shoulders out to the acromion, torso sides = silhouette edge + 1.5 % (x floor), armpit at the arm/torso junction,
  inner cuff clamped outside the armpit, mid-sleeve pairs. Known limit: gaps beside the torso on plus avatars.
Hem row: hip + hem_hip_fraction x (crotch - hip), at most crotch - hem_crotch_margin (benchmark assumption, docs/09
"Still open"). After the warp: edge fix once on the outer contour; adapt also drops partial alpha < 0.9; the inner
back collar is cleared (production neck handling); render_tryon puts the head/neck and hands on top.

`tshirt_layer` raises MlsUnavailable when a required landmark is missing or a core pair fails validation; the caller
falls back to the parts engine (quality warning "mls_fallback").
"""
import time

import cv2
import numpy as np

from . import warp as prod

NECK_WEIGHT = 5.0
GRID = 4
ROWS = ("shoulder", "armpit", "chest", "waist", "hem")
REQUIRED = ("collar", "collar_bottom", "shoulder", "armpit", "chest", "waist", "hem",
            "sleeve_cuff_outer", "sleeve_cuff_inner")
CORE_PAIRS = ("neck_l", "neck_r", "neck_c", "shoulder_l", "shoulder_r", "waist_l", "waist_r", "hem_l", "hem_r")
# keep_shape (docs/09 #96): group -> k or {"x", "y"}
PRESET_A = {"neck": 1.0, "shoulder": {"x": 0.5, "y": 1.0}, "armpit": 0.3, "chest": 0.3, "waist": 0.3,
            "hem": {"x": 0.3, "y": 0.5}, "cuff": 0.3}
CUFF_ARM_EASE = 1.1
SIDE_EASE = 0.015
UNDERARM_CLAMP = 2.0
HARD_EDGE = int(0.9 * 255)
ACROMION_ROWS = 4
ARM_FIT_ROWS = 20
_f = float


class MlsUnavailable(Exception):
    """The MLS warp cannot run for this garment/body: the caller uses the parts engine instead."""


def k_map_for(fit_mode: str) -> dict:
    """fit_mode -> per-group k: keep_shape = preset A; adapt = 1.0 everywhere (the fitted targets)."""
    if fit_mode == "keep_shape":
        return dict(PRESET_A)
    return {"neck": 1.0, "shoulder": 1.0, "armpit": 1.0, "chest": 1.0, "waist": 1.0, "hem": 1.0, "cuff": 1.0}


def k_of(k_map, group, default=1.0):
    v = (k_map or {}).get(group, default)
    if isinstance(v, dict):
        return float(v.get("x", default)), float(v.get("y", default))
    return float(v), float(v)


def missing_landmarks(glm: dict) -> list:
    span = ("y", "left_x", "right_x")
    need = {g: span for g in ("collar", "shoulder", "armpit", "chest", "waist", "hem")}
    need["collar_bottom"] = ("x", "y")
    out = []
    for g in REQUIRED:
        v = (glm or {}).get(g)
        if g.startswith("sleeve_cuff"):
            ok = isinstance(v, dict) and all(isinstance(v.get(s), dict) and all(c in v[s] for c in ("x", "y"))
                                              for s in ("left", "right"))
        else:
            ok = isinstance(v, dict) and all(c in v for c in need[g])
        if not ok:
            out.append(g)
    return out


# ---------- body geometry ----------

def body_hem_y(lm, hip_fraction=0.35, crotch_margin=10.0):
    hip, crotch = _f(lm["hip"]["y"]), _f(lm["crotch"]["y"])
    return min(hip + hip_fraction * (crotch - hip), crotch - crotch_margin)


def arm_direction(mask, lm, side, arms=None):
    """Unit vector body shoulder point -> arm centre at armpit + 10 % of the figure height, or None."""
    arm = (arms if arms is not None else prod.find_arms(mask, lm)).get(side)
    if not arm:
        return None
    y = _f(lm["armpit"]["y"]) + 0.1 * (_f(lm["foot_bottom"]["y"]) - _f(lm["head_top"]["y"]))
    rows = [r for r in arm["rows"] if abs(r[0] - y) <= 1]
    if not rows:
        return None
    d = np.array([(rows[0][1] + rows[0][2]) / 2, rows[0][0]], float) - \
        np.array([_f(lm["shoulder"][f"{side}_x"]), _f(lm["shoulder"]["y"])])
    return d / np.linalg.norm(d)


def _arm_at(arms, side, y):
    """(centre x, horizontal width) of the arm at row y: a straight fit through the first separated arm rows,
    extrapolated (short sleeves end above the row where the arm separates in the mask)."""
    rows = ((arms.get(side) or {}).get("rows") or [])[:ARM_FIT_ROWS]
    if len(rows) < 5:
        return None
    ys = np.array([r[0] for r in rows], float)
    a, b = np.polyfit(ys, np.array([(r[1] + r[2]) / 2 for r in rows], float), 1)
    return float(a * y + b), float(np.median([r[2] - r[1] for r in rows]))


def _torso_run(mask, y, axis):
    yi = min(max(int(round(y)), 0), mask.shape[0] - 1)
    return next((q for q in prod._runs(mask[yi]) if q[0] <= axis <= q[1]), None)


def _side_edges(mask, blm, row, y, axis):
    if row in blm and "left_x" in blm[row]:
        bl, br = _f(blm[row]["left_x"]), _f(blm[row]["right_x"])
    else:
        bl, br = prod.body_span(blm, y)
    run = _torso_run(mask, y, axis) if mask.any() else None
    if run and run[1] - run[0] <= 1.3 * (br - bl):
        return float(run[0]), float(run[1] + 1)
    return bl, br


def _underarm_edges(mask, arms, axis, fallback):
    out = list(fallback)
    for i, side in enumerate(("left", "right")):
        rows = (arms.get(side) or {}).get("rows") or []
        if rows:
            run = _torso_run(mask, rows[0][0], axis)
            if run:
                out[i] = float(run[0]) if side == "left" else float(run[1] + 1)
    return tuple(out)


def _floor_x(p, bx, side):
    return (min(p[0], bx) if side == "left" else max(p[0], bx), p[1])


def _order_flips(pairs, a, b):
    return (pairs[a][0][0] < pairs[b][0][0]) != (pairs[a][1][0] < pairs[b][1][0])


# ---------- control points ----------

def control_points(glm, blm, mask, k_map, fitted, hem_rule=(0.35, 10.0)):
    """(pairs {name: (q garment, p target, weight)}, rejected [names], s)."""
    arms = prod.find_arms(mask, blm) if mask.any() else {}
    g_sl, g_sr, g_sy = _f(glm["shoulder"]["left_x"]), _f(glm["shoulder"]["right_x"]), _f(glm["shoulder"]["y"])
    a_sl, a_sr, a_sy = _f(blm["shoulder"]["left_x"]), _f(blm["shoulder"]["right_x"]), _f(blm["shoulder"]["y"])
    if g_sr <= g_sl or a_sr <= a_sl:
        raise MlsUnavailable("shoulder span not positive")
    s = (a_sr - a_sl) / (g_sr - g_sl)
    g_cx, a_cx = (g_sl + g_sr) / 2, (a_sl + a_sr) / 2
    aligned = lambda q: np.array([a_cx + (q[0] - g_cx) * s, a_sy + (q[1] - g_sy) * s])  # noqa: E731

    def fit(q, b, group):
        kx, ky = k_of(k_map, group)
        a = aligned(q)
        return tuple(a + np.array([kx, ky]) * (np.asarray(b, float) - a))

    pairs, rejected = {}, []
    neck = ((_f(glm["collar"]["left_x"]), _f(glm["collar"]["y"])),
            (_f(glm["collar"]["right_x"]), _f(glm["collar"]["y"])),
            (_f(glm["collar_bottom"]["x"]), _f(glm["collar_bottom"]["y"])))
    for name, q in zip(("neck_l", "neck_r", "neck_c"), neck):
        pairs[name] = (q, tuple(aligned(q)), NECK_WEIGHT)

    hem_y = body_hem_y(blm, *hem_rule)
    g_waist_w = _f(glm["waist"]["right_x"]) - _f(glm["waist"]["left_x"])
    g_hem_w = _f(glm["hem"]["right_x"]) - _f(glm["hem"]["left_x"])
    b_waist_w = _f(blm["waist"]["right_x"]) - _f(blm["waist"]["left_x"])
    b_hip_w = _f(blm["hip"]["right_x"]) - _f(blm["hip"]["left_x"])
    hem_hw = max(g_hem_w / max(g_waist_w, 1e-6) * b_waist_w, b_hip_w) / 2
    b_hem_cx = (_f(blm["hip"]["left_x"]) + _f(blm["hip"]["right_x"])) / 2
    for side, sx in (("left", "_l"), ("right", "_r")):
        for r in ("shoulder", "armpit", "chest", "waist"):
            q = (_f(glm[r][f"{side}_x"]), _f(glm[r]["y"]))
            pairs[r + sx] = (q, fit(q, (_f(blm[r][f"{side}_x"]), _f(blm[r]["y"])), r), 1.0)
        q = (_f(glm["hem"][f"{side}_x"]), _f(glm["hem"]["y"]))
        pairs["hem" + sx] = (q, fit(q, (b_hem_cx + (-hem_hw if side == "left" else hem_hw), hem_y), "hem"), 1.0)

    g_len = _f(glm["hem"]["y"]) - g_sy
    b_len = hem_y - a_sy
    torso_ratio = (_f(blm["chest"]["right_x"]) - _f(blm["chest"]["left_x"])) / \
        max(_f(glm["chest"]["right_x"]) - _f(glm["chest"]["left_x"]), 1e-6)
    for side, sx in (("left", "_l"), ("right", "_r")):
        d = arm_direction(mask, blm, side, arms)
        if d is None:
            rejected.append(f"cuff{sx} (arm not found)")
            continue
        out = np.array([_f(glm["sleeve_cuff_outer"][side]["x"]), _f(glm["sleeve_cuff_outer"][side]["y"])])
        inn = np.array([_f(glm["sleeve_cuff_inner"][side]["x"]), _f(glm["sleeve_cuff_inner"][side]["y"])])
        S_g = np.array([_f(glm["shoulder"][f"{side}_x"]), g_sy])
        L_b = float(np.linalg.norm((out + inn) / 2 - S_g)) / max(g_len, 1e-6) * b_len
        c = np.array([_f(blm["shoulder"][f"{side}_x"]), a_sy]) + d * L_b
        w = float(np.linalg.norm(out - inn)) * torso_ratio
        perp = np.array([-d[1], d[0]])
        if (perp[0] > 0) != (side == "right"):
            perp = -perp
        pairs["cuff_out" + sx] = (tuple(out), fit(out, c + perp * w / 2, "cuff"), 1.0)
        pairs["cuff_in" + sx] = (tuple(inn), fit(inn, c - perp * w / 2, "cuff"), 1.0)
    if fitted:
        _retarget_fitted(pairs, glm, blm, mask, arms, fit, hem_y, rejected)
    rejected += drop_crossing_chest(pairs, glm)
    rejected += validate(pairs)
    return pairs, rejected, s


def _retarget_fitted(pairs, glm, blm, mask, arms, fit, hem_y, rejected):
    """adapt (round 7 of the benchmark): see the module docstring."""
    a_sy = _f(blm["shoulder"]["y"])
    for side, sx, out in (("left", "_l", -1), ("right", "_r", 1)):  # shoulders out to the acromion
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
    axis = prod._crotch_x(blm)
    bl, br = prod.body_span(blm, hem_y)
    run = _torso_run(mask, hem_y, axis) if mask.any() else None
    if run and run[1] - run[0] <= 1.3 * (br - bl):
        bl, br = float(run[0]), float(run[1] + 1)
    e = SIDE_EASE * (br - bl)
    g_hy = _f(glm["hem"]["y"])
    for side, sx, bx in (("left", "_l", bl - e), ("right", "_r", br + e)):
        q = (_f(glm["hem"][f"{side}_x"]), g_hy)
        pairs["hem" + sx] = (q, _floor_x(fit(q, (bx, hem_y), "hem"), bx, side), 1.0)
    for row in ("armpit", "chest", "waist"):  # torso sides: silhouette edge + ease, x floored
        y = _f(blm[row]["y"])
        l, r = _side_edges(mask, blm, row, y, axis)
        if row == "armpit":
            l, r = _underarm_edges(mask, arms, axis, (l, r))
        e = SIDE_EASE * (r - l)
        for side, sx, bx in (("left", "_l", l - e), ("right", "_r", r + e)):
            q = pairs[row + sx][0]
            pairs[row + sx] = (q, _floor_x(fit(q, (bx, y), row), bx, side), 1.0)
    q = ((_f(glm["hem"]["left_x"]) + _f(glm["hem"]["right_x"])) / 2, g_hy)
    pairs["hem_c"] = (q, fit(q, ((bl + br) / 2, hem_y), "hem"), 1.0)
    torso_ratio = (_f(blm["chest"]["right_x"]) - _f(blm["chest"]["left_x"])) / \
        max(_f(glm["chest"]["right_x"]) - _f(glm["chest"]["left_x"]), 1e-6)
    for side, sx in (("left", "_l"), ("right", "_r")):  # cuffs on the arm, mid-sleeve pairs
        if "cuff_out" + sx not in pairs:
            continue
        d = arm_direction(mask, blm, side, arms)
        out_q, in_q = pairs["cuff_out" + sx][0], pairs["cuff_in" + sx][0]
        g_sy = _f(glm["shoulder"]["y"])
        S_g = np.array([_f(glm["shoulder"][f"{side}_x"]), g_sy])
        g_len = _f(glm["hem"]["y"]) - g_sy
        L_b = float(np.linalg.norm((np.array(out_q) + np.array(in_q)) / 2 - S_g)) / max(g_len, 1e-6) * (hem_y - a_sy)
        c = np.array([_f(blm["shoulder"][f"{side}_x"]), a_sy]) + d * L_b
        at = _arm_at(arms, side, c[1])
        if at is None:
            rejected.append(f"cuff{sx} (arm not found: plain cuff targets kept)")
            continue
        c = np.array([at[0], c[1]])
        w = min(float(np.linalg.norm(np.array(out_q) - np.array(in_q))) * torso_ratio,
                at[1] * abs(d[1]) * CUFF_ARM_EASE)
        perp = np.array([-d[1], d[0]])
        if (perp[0] > 0) != (side == "right"):
            perp = -perp
        pairs["cuff_out" + sx] = (out_q, fit(out_q, c + perp * w / 2, "cuff"), 1.0)
        pairs["cuff_in" + sx] = (in_q, fit(in_q, c - perp * w / 2, "cuff"), 1.0)
        m = (np.array(pairs["shoulder" + sx][1]) + c) / 2
        at_m = _arm_at(arms, side, m[1])
        if at_m is not None and "armpit" + sx in pairs:
            m = np.array([at_m[0], m[1]])
            wm = at_m[1] * abs(d[1]) * CUFF_ARM_EASE
            q_out = tuple((np.array(pairs["shoulder" + sx][0]) + np.array(out_q)) / 2)
            q_in = tuple((np.array([_f(glm["armpit"][f"{side}_x"]), _f(glm["armpit"]["y"])]) + np.array(in_q)) / 2)
            pairs["smid_out" + sx] = (q_out, fit(q_out, m + perp * wm / 2, "cuff"), 1.0)
            pairs["smid_in" + sx] = (q_in, tuple((np.array(pairs["armpit" + sx][1]) +
                                                  np.array(pairs["cuff_in" + sx][1])) / 2), 1.0)
    _validate_fitted(pairs, rejected)
    hl, hr, hc = pairs["hem_l"], pairs["hem_r"], pairs["hem_c"]
    if not all(hl[i][0] < hc[i][0] < hr[i][0] for i in (0, 1)):
        del pairs["hem_c"]
        rejected.append("hem_c")


def _validate_fitted(pairs, rejected):
    for sx in ("_l", "_r"):
        if "smid_out" + sx in pairs:
            ok = True
            for i in (0, 1):
                S, C = np.array(pairs["shoulder" + sx][i]), np.array(pairs["cuff_out" + sx][i])
                u = (C - S) / max(np.linalg.norm(C - S), 1e-6)
                t = (np.array(pairs["smid_out" + sx][i]) - S) @ u
                ok &= 0 < t < (C - S) @ u
            if not ok or _order_flips(pairs, "smid_out" + sx, "smid_in" + sx):
                del pairs["smid_out" + sx], pairs["smid_in" + sx]
                rejected.append("smid" + sx)
        a, c = "armpit" + sx, "cuff_in" + sx
        if a in pairs and c in pairs and _order_flips(pairs, a, c):  # inner cuff crossing the armpit: clamp
            out = -1.0 if sx == "_l" else 1.0
            q, p, w = pairs[c]
            pairs[c] = (q, (pairs[a][1][0] + out * UNDERARM_CLAMP, p[1]), w)
            if "smid_in" + sx in pairs:
                qm, _, wm = pairs["smid_in" + sx]
                pairs["smid_in" + sx] = (qm, tuple((np.array(pairs[a][1]) + np.array(pairs[c][1])) / 2), wm)
        if a in pairs and any(n in pairs and _order_flips(pairs, a, n) for n in (c, "smid_in" + sx)):
            del pairs[a]
            rejected.append(f"armpit{sx} (crossing)")


def drop_crossing_chest(pairs, glm):
    """Chest pairs at/above the armpit (oversized) or with a garment/body vertical order that differs: dropped."""
    marked = glm.get("armpit", {}).get("y") if isinstance(glm.get("armpit"), dict) else None
    bad = []
    for sx in ("_l", "_r"):
        k = "chest" + sx
        if k not in pairs:
            continue
        q, p, _ = pairs[k]
        pits = [_f(marked)] if marked is not None else []
        if "armpit" + sx in pairs:
            pits.append(pairs["armpit" + sx][0][1])
        crossed = any(q[1] <= y for y in pits)
        for r in ROWS:
            o = pairs.get(r + sx)
            if r != "chest" and o is not None and (q[1] > o[0][1]) != (p[1] > o[1][1]):
                crossed = True
        if crossed:
            bad.append(k)
            del pairs[k]
    return bad


def validate(pairs):
    """Removes (in place) and returns pairs that break the row order (shoulder < armpit < chest < waist < hem, both
    sides, garment and body), left < right per row, or cuffs not below their shoulder."""
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
                if not (pairs[k][0][1] > pairs["shoulder" + sx][0][1] and
                        pairs[k][1][1] > pairs["shoulder" + sx][1][1]):
                    bad.append(k)
                    del pairs[k]
    for r in ROWS + ("neck",):
        kl, kr = r + "_l", r + "_r"
        if kl in pairs and kr in pairs:
            ql, pl, _ = pairs[kl]
            qr, pr, _ = pairs[kr]
            if not (ql[0] < qr[0] and pl[0] < pr[0]):
                bad += [kl, kr]
                del pairs[kl], pairs[kr]
    return bad


# ---------- warp ----------

def mls_rigid_inverse(p, q, k, V, alpha=1.0):
    d = V[:, None, :] - p[None, :, :]
    w = k[None, :] / np.maximum((d ** 2).sum(-1), 1e-6) ** alpha
    W = w.sum(1, keepdims=True)
    ps = (w[..., None] * p[None]).sum(1) / W
    qs = (w[..., None] * q[None]).sum(1) / W
    ph, qh = p[None] - ps[:, None], q[None] - qs[:, None]
    dot = (w * (ph * qh).sum(-1)).sum(1)
    crs = (w * (ph[..., 0] * qh[..., 1] - ph[..., 1] * qh[..., 0])).sum(1)
    th = np.arctan2(crs, dot)
    c, s_ = np.cos(th), np.sin(th)
    vx, vy = V[:, 0] - ps[:, 0], V[:, 1] - ps[:, 1]
    return np.stack([c * vx - s_ * vy + qs[:, 0], s_ * vx + c * vy + qs[:, 1]], 1)


def tshirt_layer(garment_img, glm, body_lm, mask, fit_mode="adapt", H=1200, W=600, hem_rule=(0.35, 10.0)):
    """(BGRA layer HxW, info {engine, pairs, rejected, s, neck_opening?, sleeve_hems, runtime}).
    Raises MlsUnavailable (missing landmarks, failed core pairs, bad geometry): the caller uses the parts engine."""
    t0 = time.perf_counter()
    miss = missing_landmarks(glm)
    if miss:
        raise MlsUnavailable(f"missing landmarks: {', '.join(miss)}")
    img = prod._bgra(garment_img)
    fitted = fit_mode != "keep_shape"
    try:
        pairs, rejected, s = control_points(glm, body_lm, mask, k_map_for(fit_mode), fitted, hem_rule)
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
        raise MlsUnavailable(f"control points: {e!r}") from e
    lost = [n for n in CORE_PAIRS if n not in pairs]
    if lost:
        raise MlsUnavailable(f"pair validation failed: {', '.join(lost)}")
    names = list(pairs)
    q = np.array([pairs[n][0] for n in names], float) * s
    p = np.array([pairs[n][1] for n in names], float)
    w = np.array([pairs[n][2] for n in names], float)
    gy, gx = np.mgrid[0:H + GRID:GRID, 0:W + GRID:GRID].astype(np.float64)
    F = mls_rigid_inverse(p, q, w, np.stack([gx.ravel(), gy.ravel()], 1)) / s
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
    if fitted:
        alpha = layer[:, :, 3]
        alpha[alpha < HARD_EDGE] = 0
    info = {"engine": "mls", "fit_mode": fit_mode, "pairs": pairs, "rejected": rejected, "s": s}
    geo = prod.back_collar_geometry(img[:, :, 3] > 128, glm, img)
    if geo:
        g_cx = (_f(glm["shoulder"]["left_x"]) + _f(glm["shoulder"]["right_x"])) / 2
        a_cx = (_f(body_lm["shoulder"]["left_x"]) + _f(body_lm["shoulder"]["right_x"])) / 2
        g_sy, a_sy = _f(glm["shoulder"]["y"]), _f(body_lm["shoulder"]["y"])
        info["neck_opening"] = {"cx": a_cx + (geo["cx"] - g_cx) * s, "hw": geo["hw"] * s,
                                "y0": a_sy + (geo["y0"] - g_sy) * s, "depth": geo["depth"] * s}
        layer = prod.clear_back_collar(layer, info["neck_opening"], body_lm)
    hems = {}
    for side, sx in (("left", "_l"), ("right", "_r")):  # the hands/forearms overlay starts at the cuff line
        if "cuff_out" + sx in pairs and "cuff_in" + sx in pairs:
            sh = np.array([_f(body_lm["shoulder"][f"{side}_x"]), _f(body_lm["shoulder"]["y"])])
            hems[side] = (np.float32(pairs["cuff_out" + sx][1]), np.float32(pairs["cuff_in" + sx][1]), sh)
    info["sleeve_hems"] = hems
    info["runtime"] = time.perf_counter() - t0
    return layer, info
