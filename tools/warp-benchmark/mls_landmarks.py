"""Benchmark only (not the production path): the WHOLE T-shirt warped by ONE rigid MLS field, control points from
the MARKED garment landmarks (docs/09 #92 set), with a fit strength k. docs/06 "MLS single-field benchmark, round 2".

    warp(garment_rgba, garment_lm, body_lm, out_size=(600, 1200), alpha=1.0, k=1.0, base=None, info=None) -> RGBA

base: BGRA avatar (its mask gives the arm direction for the sleeve targets); info: optional dict filled with the
pairs, rejected pairs, the inverse map and the runtime (for `mls.metrics` / `mls.composite`).

Alignment first: one uniform scale s = body shoulder width / garment shoulder width, translated so the garment's
shoulder-line centre sits on the body's (the neck anchors ride on it). aligned(q) = A(q). Every target is
    aligned(q) + k * (body_point - aligned(q))        (k = 1 full fit, k = 0 the aligned garment unchanged)
The neck points never move off the alignment (anchors, weight NECK_WEIGHT).

Pairs (garment -> body), by name; a garment missing any of these landmarks is not warped (`missing_landmarks`):
  neck_l / neck_r / neck_c   collar.left_x|right_x @ collar.y, collar_bottom (V tip on a V neck) -> aligned only
  shoulder_l/r               shoulder seam -> body shoulder point
  armpit_l/r                 armpit edges -> body armpit edges
  chest_l/r, waist_l/r       -> body chest / waist edges
  hem_l/r                    -> hem_y = hip + 0.35 (crotch - hip) <= crotch - 10 (benchmark assumption, docs/09
                             "Still open"); half-width = garment hem/waist ratio x body waist half-width, at least
                             the body's hip half-width
  cuff_out/cuff_in (l, r)    sleeve_cuff_outer|inner -> along the arm direction (body shoulder point -> arm centre at
                             armpit + 10 % of the figure height), length = garment sleeve length (shoulder -> cuff
                             midpoint) / garment shoulder-to-hem x body shoulder-to-hem; cuff width x the chest width
                             ratio, perpendicular to the arm, outer corner away from the body
Validation before warping: `mls.drop_crossing_chest` (oversized: chest at/above the armpit) then `mls.validate`
(row order shoulder < armpit < chest < waist < hem on both sides, left < right per row, cuffs below the shoulder).
Armpit and inner cuff are never moved or merged, even when they almost touch (oversized).
"""
import time

import cv2
import numpy as np

import mls
from apps.tryon_engine import warp as prod

NECK_WEIGHT = mls.NECK_WEIGHT
GRID = mls.GRID
REQUIRED = ("collar", "collar_bottom", "shoulder", "armpit", "chest", "waist", "hem",
            "sleeve_cuff_outer", "sleeve_cuff_inner")
_f = float


def missing_landmarks(glm: dict) -> list[str]:
    """Names of the required landmark groups that are absent or incomplete (never filled in)."""
    span = ("y", "left_x", "right_x")
    need = {g: span for g in ("collar", "shoulder", "armpit", "chest", "waist", "hem")}
    need["collar_bottom"] = ("x", "y")
    out = []
    for g in REQUIRED:
        v = glm.get(g)
        if g.startswith("sleeve_cuff"):
            ok = isinstance(v, dict) and all(isinstance(v.get(s), dict) and all(c in v[s] for c in ("x", "y"))
                                              for s in ("left", "right"))
        else:
            ok = isinstance(v, dict) and all(c in v for c in need[g])
        if not ok:
            out.append(g)
    return out


def control_points(glm, blm, mask, k=1.0):
    """(pairs {name: (q garment, p target, weight)}, rejected [names], s)."""
    g_sl, g_sr, g_sy = _f(glm["shoulder"]["left_x"]), _f(glm["shoulder"]["right_x"]), _f(glm["shoulder"]["y"])
    a_sl, a_sr, a_sy = _f(blm["shoulder"]["left_x"]), _f(blm["shoulder"]["right_x"]), _f(blm["shoulder"]["y"])
    s = (a_sr - a_sl) / (g_sr - g_sl)
    g_cx, a_cx = (g_sl + g_sr) / 2, (a_sl + a_sr) / 2
    aligned = lambda q: np.array([a_cx + (q[0] - g_cx) * s, a_sy + (q[1] - g_sy) * s])  # noqa: E731
    fit = lambda q, b: tuple(aligned(q) + k * (np.asarray(b, float) - aligned(q)))  # noqa: E731
    pairs, rejected = {}, []

    neck = ((_f(glm["collar"]["left_x"]), _f(glm["collar"]["y"])),
            (_f(glm["collar"]["right_x"]), _f(glm["collar"]["y"])),
            (_f(glm["collar_bottom"]["x"]), _f(glm["collar_bottom"]["y"])))
    for name, q in zip(("neck_l", "neck_r", "neck_c"), neck):
        pairs[name] = (q, tuple(aligned(q)), NECK_WEIGHT)

    hem_y = mls.body_hem_y(blm)
    g_waist_w = _f(glm["waist"]["right_x"]) - _f(glm["waist"]["left_x"])
    g_hem_w = _f(glm["hem"]["right_x"]) - _f(glm["hem"]["left_x"])
    b_waist_w = _f(blm["waist"]["right_x"]) - _f(blm["waist"]["left_x"])
    b_hip_w = _f(blm["hip"]["right_x"]) - _f(blm["hip"]["left_x"])
    hem_hw = max(g_hem_w / g_waist_w * b_waist_w, b_hip_w) / 2
    b_hem_cx = (_f(blm["hip"]["left_x"]) + _f(blm["hip"]["right_x"])) / 2
    for side, sx in (("left", "_l"), ("right", "_r")):
        for r in ("shoulder", "armpit", "chest", "waist"):
            q = (_f(glm[r][f"{side}_x"]), _f(glm[r]["y"]))
            pairs[r + sx] = (q, fit(q, (_f(blm[r][f"{side}_x"]), _f(blm[r]["y"]))), 1.0)
        q = (_f(glm["hem"][f"{side}_x"]), _f(glm["hem"]["y"]))
        pairs["hem" + sx] = (q, fit(q, (b_hem_cx + (-hem_hw if side == "left" else hem_hw), hem_y)), 1.0)

    g_len = _f(glm["hem"]["y"]) - g_sy
    b_len = hem_y - a_sy
    torso_ratio = (_f(blm["chest"]["right_x"]) - _f(blm["chest"]["left_x"])) / \
        (_f(glm["chest"]["right_x"]) - _f(glm["chest"]["left_x"]))
    for side, sx in (("left", "_l"), ("right", "_r")):
        d = mls.arm_direction(mask, blm, side)
        if d is None:
            rejected.append(f"cuff{sx} (arm not found)")
            continue
        out = np.array([_f(glm["sleeve_cuff_outer"][side]["x"]), _f(glm["sleeve_cuff_outer"][side]["y"])])
        inn = np.array([_f(glm["sleeve_cuff_inner"][side]["x"]), _f(glm["sleeve_cuff_inner"][side]["y"])])
        S_g = np.array([_f(glm["shoulder"][f"{side}_x"]), g_sy])
        L_b = float(np.linalg.norm((out + inn) / 2 - S_g)) / g_len * b_len
        c = np.array([_f(blm["shoulder"][f"{side}_x"]), a_sy]) + d * L_b
        w = float(np.linalg.norm(out - inn)) * torso_ratio
        perp = np.array([-d[1], d[0]])
        if (perp[0] > 0) != (side == "right"):  # outward = away from the body centre
            perp = -perp
        pairs["cuff_out" + sx] = (tuple(out), fit(out, c + perp * w / 2), 1.0)
        pairs["cuff_in" + sx] = (tuple(inn), fit(inn, c - perp * w / 2), 1.0)
    rejected += mls.drop_crossing_chest(pairs, glm)
    rejected += mls.validate(pairs)
    return pairs, rejected, s


def warp(garment_rgba, garment_lm, body_lm, out_size=(600, 1200), alpha=1.0, k=1.0, base=None, info=None):
    t0 = time.perf_counter()
    info = {} if info is None else info
    W, H = out_size
    mask = prod.figure_mask(cv2.resize(prod._bgra(base), (W, H))) if base is not None else np.zeros((H, W), bool)
    img = prod._bgra(garment_rgba)
    miss = missing_landmarks(garment_lm)
    if miss:
        info.update({"skipped": True, "missing": miss})
        return None
    pairs, rejected, s = control_points(garment_lm, body_lm, mask, k)
    names = list(pairs)
    q = np.array([pairs[n][0] for n in names], float) * s
    p = np.array([pairs[n][1] for n in names], float)
    w = np.array([pairs[n][2] for n in names], float)
    gy, gx = np.mgrid[0:H + GRID:GRID, 0:W + GRID:GRID].astype(np.float64)
    F = mls.mls_rigid_inverse(p, q, w, np.stack([gx.ravel(), gy.ravel()], 1), alpha) / s
    mx = cv2.resize(F[:, 0].reshape(gx.shape).astype(np.float32), None, fx=GRID, fy=GRID,
                    interpolation=cv2.INTER_LINEAR)[:H, :W]
    my = cv2.resize(F[:, 1].reshape(gx.shape).astype(np.float32), None, fx=GRID, fy=GRID,
                    interpolation=cv2.INTER_LINEAR)[:H, :W]
    f = img.astype(np.float32)
    f[:, :, :3] *= f[:, :, 3:4] / 255.0  # premultiplied: no dark fringe from transparent neighbours
    out = cv2.remap(f, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    a = out[:, :, 3:4] / 255.0
    out[:, :, :3] = np.where(a > 0, out[:, :, :3] / np.maximum(a, 1e-6), 0)
    layer = np.clip(np.rint(out), 0, 255).astype(np.uint8)
    layer = prod.remove_halo(layer, outer_only=True)  # edge fix, once, outer contour (2 px)
    # neck: production handling (inner back collar cleared; the head/neck overlay comes in mls.composite)
    geo = prod.back_collar_geometry(img[:, :, 3] > 128, garment_lm, img)
    if geo:
        g_cx = (_f(garment_lm["shoulder"]["left_x"]) + _f(garment_lm["shoulder"]["right_x"])) / 2
        a_cx = (_f(body_lm["shoulder"]["left_x"]) + _f(body_lm["shoulder"]["right_x"])) / 2
        g_sy, a_sy = _f(garment_lm["shoulder"]["y"]), _f(body_lm["shoulder"]["y"])
        info["neck_opening"] = {"cx": a_cx + (geo["cx"] - g_cx) * s, "hw": geo["hw"] * s,
                                "y0": a_sy + (geo["y0"] - g_sy) * s, "depth": geo["depth"] * s}
        layer = prod.clear_back_collar(layer, info["neck_opening"], body_lm)
    info.update({"pairs": pairs, "rejected": rejected, "s": s, "map": (mx, my),
                 "runtime": time.perf_counter() - t0})
    return layer


def scale_at(info, names):
    """{name: (min, max) forward local scale} at the target pixel of each named pair (oversized armpit/cuff)."""
    mx, my = info["map"]
    dxx, dxy = np.gradient(mx, axis=1), np.gradient(mx, axis=0)
    dyx, dyy = np.gradient(my, axis=1), np.gradient(my, axis=0)
    out = {}
    for n in names:
        if n not in info["pairs"]:
            continue
        x, y = (int(round(c)) for c in info["pairs"][n][1])
        y, x = min(max(y, 0), mx.shape[0] - 1), min(max(x, 0), mx.shape[1] - 1)
        J = np.array([[dxx[y, x], dxy[y, x]], [dyx[y, x], dyy[y, x]]])
        sv = np.linalg.svd(J, compute_uv=False)
        out[n] = (round(float(1 / max(sv[0], 1e-9)), 2), round(float(1 / max(sv[1], 1e-9)), 2))
    return out
