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

sleeve_variant (keyword only, benchmark round 8, docs/06; render_tryon never passes it, so production is always
"r7"): adapt sleeve pairs. "r7" = as above. "A" = no smid_out|in pairs. "B" = smid_out target at the arm's outer
silhouette edge on its row (outermost mask run, the deltoid edge) + the CUFF_ARM_EASE share of the arm width
measured lower down; smid_in unchanged. "C" = B + a cuff_mid pair (garment cuff-corner midpoint -> body
cuff-target midpoint), computed after validation and dropped when it fails.

side_floor (keyword only, benchmark round 10, docs/06; render_tryon never passes it, default False): the garment is
never narrower than the torso at its sides. Floor at body row y = torso silhouette edge -/+ SIDE_EASE x torso width
(`_torso_floor`). keep_shape: the side x targets of armpit, chest, waist and hem are clamped to the floor at their
target row (k still sets y). Both modes: a first solve WITHOUT new pairs (same clamped setup) shows where the
garment's measured side edge lands at 1/3 and 2/3 of armpit -> hem and at the hip row; a pair `side_a|side_b|side_hip`
is added there with x = max(that landing x, floor) (left: min), then the field is solved again. A garment already
wider than the floor gets NO pair there (2026-11-12, owner): the second solve runs only when the floor added a pair.
**Disabled for keep_shape for now** (owner, 2026-11-12): `tshirt_layer` ignores side_floor when fit_mode is
keep_shape, so keep_shape output is always the pre-round-10 output. The keep_shape clamp in `control_points` stays
(reachable only by calling it directly).

neckline_variant (keyword only, benchmark, docs/06 "V-neck opening"; render_tryon never passes it, default "r7"):
"r7" = the back-collar clearing only (crew-sized rims, darker inside). "clear" = r7 + the neckline opening made
transparent: the triangle (V: depth / width >= NECKLINE_V_RATIO, garment landmarks) or the parabola (crew / scoop)
through the neck_l, neck_r, neck_c body targets (collar_left/right, collar_bottom), its sides inset by
NECKLINE_INSET x the collar width so the collar band stays, edge antialiased ~1.5 px. "clear_skin" = clear + the
avatar's own non-skin clothes showing in the opening painted in the neck-centre skin colour (info["neck_fill"], a BGRA
overlay the caller composites under the head/neck overlay), admin avatars only: source != "avatar" -> exactly "clear".

neckline_variant "hole" / "hole_skin" (benchmark, owner 2026-11-12): instead of the landmark polygon, the neckline
interior is segmented in GARMENT space (`neckline_hole`: GrabCut restricted to a belt of NECK_HOLE_BELT px around the
landmark polygon; deeper inside = hole, further outside or transparent = garment), warped with the same field as the
garment (cv2.remap with mx, my) and cleared (union with the r7 back-collar clearing). No inset. "hole_skin" adds the
skin fill like "clear_skin" (admin avatars only; source != "avatar" -> exactly "hole"). `neck_hole_polygon` (keyword,
[[x, y], ...] in garment px, owner-drawn; benchmark file data/neck_hole/<id>.json) replaces the GrabCut hole when given.

shoulder_variant (keyword only, benchmark round 9, default "off"; render_tryon never passes it): "line" adds 3 pairs
per side on the shoulder LINE (`shoulder_line`, adapt only, a no-op in keep_shape), docs/06 "Shoulder line fit, round 9".
shoulder_fractions (benchmark, default SHOULDER_LINE_FRACTIONS = 25 / 50 / 75 %): which fractions get a pair;
shoulder_ease (default SHOULDER_LINE_EASE = 2 px) and shoulder_edge_alpha (default 128; round 9b uses HARD_EDGE - 1):
the target lift and the garment-edge alpha threshold. All ignored when shoulder_variant is "off".

neck_clip (keyword only, benchmark, default False; render_tryon never passes it): the finished layer's alpha is clipped
to the avatar's figure mask dilated by NECK_CLIP_DILATE px (edge ~0.7 px soft) in the neck/shoulder box: rows from the
neck-zone top (warp.neck_zone_rows) to the body shoulder row, columns between the two shoulder (acromion) targets, so
collar band tips cannot stick out over the background. Nothing outside that box changes (sleeve caps, hem, excess).
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
SLEEVE_VARIANTS = ("r7", "A", "B", "C")
NECKLINE_VARIANTS = ("r7", "clear", "clear_skin", "hole", "hole_skin")
SHOULDER_VARIANTS = ("off", "line")
SHOULDER_LINE_FRACTIONS = (0.25, 0.5, 0.75)  # of collar edge -> shoulder seam (garment) / neck edge -> acromion (body)
SHOULDER_LINE_EASE = 2  # px: the body target sits this far ABOVE the figure's top edge (fabric on the shoulder)
SHOULDER_LINE_WEIGHT = 1.0  # same as the shoulder pair
SHOULDER_LINE_STEEP = 2.0  # |dy/dx| between the neighbour columns above this = a near-vertical edge (recorded only)
NECK_HOLE_BELT = 15  # garment px: GrabCut decides only inside this belt around the landmark polygon (owner: 10-15)
NECK_HOLE_ITERS = 5
NECKLINE_INSET = 0.06  # the opening's sides move inward by this x the collar width: the collar band stays (owner)
NECKLINE_V_RATIO = 0.45  # collar depth / width at or above this = V neck (triangle), else a curve (owner)
NECKLINE_AA = 1.5  # px: antialiased ramp of the opening edge
COLLAR_FLOOR_MARGIN = 2  # px: collar_floor puts neck_l / neck_r this far above the body contour
COLLAR_FLOOR_MAX = 40  # px: collar_floor never raises a collar point more than this (a wrong contour does no harm)
NECK_CLIP_DILATE = 2  # px: the figure mask is dilated by this before clipping the neck/shoulder box (neck_clip)
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

def control_points(glm, blm, mask, k_map, fitted, hem_rule=(0.35, 10.0), *, sleeve_variant="r7",
                   side_floor=False):
    """(pairs {name: (q garment, p target, weight)}, rejected [names], s). sleeve_variant: module docstring."""
    if sleeve_variant not in SLEEVE_VARIANTS:
        raise ValueError(f"unknown sleeve variant: {sleeve_variant!r}")
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
        _retarget_fitted(pairs, glm, blm, mask, arms, fit, hem_y, rejected, sleeve_variant)
    elif side_floor:  # keep_shape: k sets y, the x never inside the floor
        axis = prod._crotch_x(blm)
        for r in ("armpit", "chest", "waist", "hem"):
            for side, sx in (("left", "_l"), ("right", "_r")):
                q, t, w = pairs[r + sx]
                pairs[r + sx] = (q, _floor_x(t, _torso_floor(mask, blm, t[1], axis)[0 if side == "left" else 1],
                                             side), w)
    rejected += drop_crossing_chest(pairs, glm)
    rejected += validate(pairs)
    if fitted and sleeve_variant == "C":
        _add_cuff_mid(pairs, rejected)
    return pairs, rejected, s


def _retarget_fitted(pairs, glm, blm, mask, arms, fit, hem_y, rejected, sleeve_variant="r7"):
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
        if at_m is not None and "armpit" + sx in pairs and sleeve_variant != "A":
            m = np.array([at_m[0], m[1]])
            wm = at_m[1] * abs(d[1]) * CUFF_ARM_EASE
            q_out = tuple((np.array(pairs["shoulder" + sx][0]) + np.array(out_q)) / 2)
            q_in = tuple((np.array([_f(glm["armpit"][f"{side}_x"]), _f(glm["armpit"]["y"])]) + np.array(in_q)) / 2)
            t_out = m + perp * wm / 2
            if sleeve_variant in ("B", "C"):
                edge = _outer_edge_x(mask, m[1], side)
                if edge is not None and (edge - m[0]) * (1 if side == "right" else -1) > 0:
                    # same ease as r7 (CUFF_ARM_EASE x half the arm width measured lower down), from the deltoid edge
                    t_out = np.array([edge, m[1]]) + perp * (CUFF_ARM_EASE - 1.0) * at_m[1] * abs(d[1]) / 2
                else:
                    rejected.append(f"smid_out{sx} edge (no outer edge: r7 target kept)")
            pairs["smid_out" + sx] = (q_out, fit(q_out, t_out, "cuff"), 1.0)
            pairs["smid_in" + sx] = (q_in, tuple((np.array(pairs["armpit" + sx][1]) +
                                                  np.array(pairs["cuff_in" + sx][1])) / 2), 1.0)
    _validate_fitted(pairs, rejected)
    hl, hr, hc = pairs["hem_l"], pairs["hem_r"], pairs["hem_c"]
    if not all(hl[i][0] < hc[i][0] < hr[i][0] for i in (0, 1)):
        del pairs["hem_c"]
        rejected.append("hem_c")


def _torso_edges(mask, blm, y, axis):
    """Torso silhouette (left, right) at body row y: the mask run through the axis, or the landmark span
    (prod.body_span) when there is no run or it is > 1.3x the span (an arm touching the torso)."""
    bl, br = prod.body_span(blm, y)
    run = _torso_run(mask, y, axis) if mask.any() else None
    if run and run[1] - run[0] <= 1.3 * (br - bl):
        return float(run[0]), float(run[1] + 1)
    return bl, br


def _torso_floor(mask, blm, y, axis):
    """Side floor at body row y: torso edges -/+ SIDE_EASE x their width (round 7 ease)."""
    l, r = _torso_edges(mask, blm, y, axis)
    e = SIDE_EASE * (r - l)
    return l - e, r + e


def _garment_side_edges(alpha, glm, y):
    """Garment side edges (left, right) at garment row y, measured on its alpha: the run through the garment centre,
    or the landmark span (linear between armpit/chest/waist/hem) when the run is > 1.3x that span (a sleeve joined
    to the torso) or missing."""
    rows = sorted((_f(glm[k]["y"]), _f(glm[k]["left_x"]), _f(glm[k]["right_x"])) for k in ("armpit", "chest", "waist",
                                                                                            "hem"))
    ys = [r[0] for r in rows]
    sl = float(np.interp(y, ys, [r[1] for r in rows]))
    sr = float(np.interp(y, ys, [r[2] for r in rows]))
    cx = (sl + sr) / 2
    yi = int(round(y))
    if 0 <= yi < alpha.shape[0]:
        run = next((q for q in prod._runs(alpha[yi]) if q[0] <= cx <= q[1]), None)
        if run and run[1] - run[0] <= 1.3 * (sr - sl):
            return float(run[0]), float(run[1] + 1)
    return sl, sr


SIDE_FLOOR_NAMES = ("side_a", "side_b", "side_hip")
SIDE_ROWS = ("armpit", "chest", "waist", "hem") + SIDE_FLOOR_NAMES
LAND_TOL = 3.0  # garment px: the first solve must place the garment edge point at least this close


def _add_side_floor_pairs(pairs, glm, blm, mask, alpha, mx, my, rejected):
    """Round 10 second stage: new side pairs from the first solve (mx, my: body px -> garment px), x floored."""
    a_y, hem_y = _f(blm["armpit"]["y"]), pairs["hem_l"][1][1]
    g0 = max(_f(glm["armpit"]["y"]), _f(glm["chest"]["y"]))
    g1 = _f(glm["hem"]["y"])
    if hem_y <= a_y + 3 or g1 <= g0 + 3:
        rejected.append("side_floor (rows)")
        return
    fr = {"side_a": 1 / 3, "side_b": 2 / 3}
    f_hip = (_f(blm["hip"]["y"]) - a_y) / (hem_y - a_y)
    if 0.05 < f_hip < 0.95:
        fr["side_hip"] = f_hip
    axis = prod._crotch_x(blm)
    for name, f in fr.items():
        gy = g0 + f * (g1 - g0)
        gl, gr = _garment_side_edges(alpha, glm, gy)
        for side, sx, gx in (("left", "_l", gl), ("right", "_r", gr)):
            d2 = (mx - gx) ** 2 + (my - gy) ** 2
            i = int(np.argmin(d2))
            if d2.flat[i] > LAND_TOL ** 2:
                rejected.append(name + sx + " (not placed)")
                continue
            y1, x1 = divmod(i, mx.shape[1])
            fl = _torso_floor(mask, blm, y1, axis)[0 if side == "left" else 1]
            p = _floor_x((float(x1), float(y1)), fl, side)
            if p[0] == float(x1):  # the garment already reaches the floor here: no pair (2026-11-12, owner)
                continue
            pairs[name + sx] = ((gx, gy), p, 1.0)
    _validate_side_floor(pairs, rejected)


def _validate_side_floor(pairs, rejected):
    """New side pairs: same vertical order as every other side pair on their side (garment and body, > 1 px apart),
    left < right on their row (garment and body). A failing new pair is dropped; existing pairs are never touched."""
    for name in SIDE_FLOOR_NAMES:
        for sx in ("_l", "_r"):
            k = name + sx
            if k not in pairs:
                continue
            q, p, _ = pairs[k]
            for r in SIDE_ROWS:
                o = pairs.get(r + sx)
                if r == name or o is None:
                    continue
                if (q[1] > o[0][1]) != (p[1] > o[1][1]) or abs(q[1] - o[0][1]) <= 1 or abs(p[1] - o[1][1]) <= 1:
                    del pairs[k]
                    rejected.append(k + " (order)")
                    break
        kl, kr = name + "_l", name + "_r"
        if kl in pairs and kr in pairs and not (pairs[kl][0][0] < pairs[kr][0][0] and pairs[kl][1][0] < pairs[kr][1][0]):
            del pairs[kl], pairs[kr]
            rejected += [kl + " (left/right)", kr + " (left/right)"]


def _inverse_maps(pairs, s, H, W):
    """The MLS field for these pairs: (mx, my) float32 HxW, body px -> garment px."""
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
    return mx, my


def neckline_ratio(glm):
    """Garment collar depth (collar_bottom below the collar line) / collar width."""
    w = _f(glm["collar"]["right_x"]) - _f(glm["collar"]["left_x"])
    return (_f(glm["collar_bottom"]["y"]) - _f(glm["collar"]["y"])) / max(w, 1e-6)


def neckline_opening(pairs, glm, H, W):
    """(weight HxW float32 in [0, 1], meta) of the neckline opening in body px, or (None, reason). Region: between the
    collar line (neck_l -> neck_r targets) and the sides (V: neck_l -> neck_c -> neck_r; else the parabola through the
    three targets); weight = 1 deeper than NECKLINE_INSET x collar width from the sides, ramping to 0 over NECKLINE_AA."""
    if not all(k in pairs for k in ("neck_l", "neck_r", "neck_c")):
        return None, "neck pairs missing"
    L, R, C = (np.array(pairs[k][1], float) for k in ("neck_l", "neck_r", "neck_c"))
    if not (L[0] < C[0] < R[0] and C[1] > max(L[1], R[1]) + 1):
        return None, "neck targets out of order"
    ratio = neckline_ratio(glm)
    shape = "v" if ratio >= NECKLINE_V_RATIO else "curve"
    if shape == "v":
        side = np.array([L, C, R])
    else:
        a, b, c = np.polyfit([L[0], C[0], R[0]], [L[1], C[1], R[1]], 2)
        xs = np.linspace(L[0], R[0], max(int(R[0] - L[0]) * 2, 8))
        side = np.stack([xs, a * xs * xs + b * xs + c], 1)
    region = np.zeros((H, W), np.uint8)
    cv2.fillPoly(region, [np.round(side * 8).astype(np.int32)], 1, lineType=cv2.LINE_8, shift=3)
    line = np.ones((H, W), np.uint8)
    cv2.polylines(line, [np.round(side * 8).astype(np.int32)], False, 0, 1, lineType=cv2.LINE_8, shift=3)
    dist = cv2.distanceTransform(line, cv2.DIST_L2, 5)
    inset = NECKLINE_INSET * float(np.linalg.norm(R - L))
    w = np.clip((dist - inset) / NECKLINE_AA + 0.5, 0, 1) * (region > 0)
    return w.astype(np.float32), {"shape": shape, "ratio": round(ratio, 3), "inset_px": round(inset, 1),
                                  "side": side}


def neck_clip_box(pairs, blm, H, W):
    """Bool HxW: rows neck-zone top .. body shoulder row, columns between the shoulder (acromion) targets; or None."""
    if "shoulder_l" not in pairs or "shoulder_r" not in pairs:
        return None
    z0, _ = prod.neck_zone_rows(blm, H)
    y1 = int(round(_f(blm["shoulder"]["y"])))
    x0 = int(np.floor(pairs["shoulder_l"][1][0]))
    x1 = int(np.ceil(pairs["shoulder_r"][1][0]))
    box = np.zeros((H, W), bool)
    box[max(z0, 0):min(y1, H - 1) + 1, max(x0, 0):min(x1, W - 1) + 1] = True
    return box


def _landmark_neck_polygon(glm):
    """The landmark neckline polygon in garment px: V triangle or the parabola through collar_left, collar_bottom,
    collar_right (NECKLINE_V_RATIO), closed along the collar line."""
    L = np.array([_f(glm["collar"]["left_x"]), _f(glm["collar"]["y"])])
    R = np.array([_f(glm["collar"]["right_x"]), _f(glm["collar"]["y"])])
    C = np.array([_f(glm["collar_bottom"]["x"]), _f(glm["collar_bottom"]["y"])])
    if neckline_ratio(glm) >= NECKLINE_V_RATIO:
        return np.array([L, C, R])
    a, b, c = np.polyfit([L[0], C[0], R[0]], [L[1], C[1], R[1]], 2)
    xs = np.linspace(L[0], R[0], max(int(R[0] - L[0]) * 2, 8))
    return np.stack([xs, a * xs * xs + b * xs + c], 1)


def neckline_hole(img, glm, belt=NECK_HOLE_BELT):
    """(bool mask in garment px, meta) of the neckline interior, or (None, reason). GrabCut on the garment colour,
    initialised from the landmark polygon: deeper than `belt` inside = hole (GC_FGD), further than `belt` outside or
    transparent = garment (GC_BGD), the inner half of the belt GC_PR_FGD, the outer half GC_PR_BGD. Only the largest
    connected hole component touching the definite hole is kept."""
    try:
        poly = _landmark_neck_polygon(glm)
    except (KeyError, TypeError, ValueError):
        return None, "collar landmarks missing"
    Hg, Wg = img.shape[:2]
    inside = np.zeros((Hg, Wg), np.uint8)
    cv2.fillPoly(inside, [np.round(poly * 8).astype(np.int32)], 1, shift=3)
    edge = np.ones((Hg, Wg), np.uint8)
    cv2.polylines(edge, [np.round(poly * 8).astype(np.int32)], True, 0, 1, shift=3)
    dist = cv2.distanceTransform(edge, cv2.DIST_L2, 5)
    m = np.full((Hg, Wg), cv2.GC_BGD, np.uint8)
    m[(inside > 0) & (dist > belt)] = cv2.GC_FGD
    m[(inside > 0) & (dist <= belt)] = cv2.GC_PR_FGD
    m[(inside == 0) & (dist <= belt)] = cv2.GC_PR_BGD
    alpha = img[:, :, 3] > 128
    m[~alpha & (m != cv2.GC_FGD)] = cv2.GC_BGD
    if not (m == cv2.GC_FGD).any():
        return None, "polygon thinner than the belt"
    ys, xs = np.nonzero(m != cv2.GC_BGD)
    y0, y1 = max(ys.min() - 4, 0), min(ys.max() + 5, Hg)
    x0, x1 = max(xs.min() - 4, 0), min(xs.max() + 5, Wg)
    rgb = np.ascontiguousarray(img[y0:y1, x0:x1, :3])
    sub = np.ascontiguousarray(m[y0:y1, x0:x1])
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(rgb, sub, None, bgd, fgd, NECK_HOLE_ITERS, cv2.GC_INIT_WITH_MASK)
    hole = np.zeros((Hg, Wg), bool)
    hole[y0:y1, x0:x1] = (sub == cv2.GC_FGD) | (sub == cv2.GC_PR_FGD)
    n, lab = cv2.connectedComponents(hole.astype(np.uint8), connectivity=8)
    keep = set(np.unique(lab[(m == cv2.GC_FGD) & hole])) - {0}
    hole = np.isin(lab, list(keep)) if keep else hole
    return hole, {"polygon_px": int(inside.sum()), "hole_px": int(hole.sum()), "belt": belt}


def _neck_skin(base, mask, lm):
    """Median skin colour of the neck centre (as warp.neck_gap_fill_fn samples it), or None."""
    n = lm.get("neck")
    if not n:
        return None
    nw = _f(n["right_x"]) - _f(n["left_x"])
    ncx, ny = (_f(n["left_x"]) + _f(n["right_x"])) / 2, _f(n["y"])
    ys = slice(max(int(ny - 0.4 * nw), 0), max(int(ny - 0.1 * nw), 1))
    xs = slice(max(int(ncx - 0.15 * nw), 0), int(ncx + 0.15 * nw) + 1)
    box, box_m = base[ys, xs], mask[ys, xs]
    if not box_m.any():
        return None
    return np.median(box[:, :, :3][box_m], axis=0).astype(np.uint8)


def _outer_edge_x(mask, y, side):
    """x of the outer edge of the figure on row y (left: first mask px, right: one past the last), or None."""
    yi = int(round(y))
    if not mask.any() or not 0 <= yi < mask.shape[0]:
        return None
    runs = prod._runs(mask[yi])
    if not runs:
        return None
    return float(runs[0][0]) if side == "left" else float(runs[-1][1] + 1)


def _add_cuff_mid(pairs, rejected):
    """Variant C: one pair at the cuff midpoint (garment corners -> body cuff targets, after every clamp). Dropped
    when the corners are degenerate (< 2 px apart), it is not strictly between cuff_out and cuff_in in x on both
    sides of the pair, or it crosses the armpit in x order."""
    for sx in ("_l", "_r"):
        o, i = pairs.get("cuff_out" + sx), pairs.get("cuff_in" + sx)
        if o is None or i is None:
            continue
        q = tuple((np.array(o[0]) + np.array(i[0])) / 2)
        p = tuple((np.array(o[1]) + np.array(i[1])) / 2)
        name = "cuff_mid" + sx
        ok = all(np.linalg.norm(np.array(o[j]) - np.array(i[j])) >= 2 for j in (0, 1))
        ok &= all(min(o[j][0], i[j][0]) < (q, p)[j][0] < max(o[j][0], i[j][0]) for j in (0, 1))
        pairs[name] = (q, p, 1.0)
        if ok and "armpit" + sx in pairs:
            ok = not _order_flips(pairs, "armpit" + sx, name)
        if not ok:
            del pairs[name]
            rejected.append(name)


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



def collar_floor(pairs, blm, mask, margin=COLLAR_FLOOR_MARGIN, max_raise=COLLAR_FLOOR_MAX):
    """Default since 2026-11-13 (owner, docs/09 #100; tshirt_layer(collar_floor_on=False) = the old placement, used
    only by the frozen regression fixtures). The neck_l / neck_r targets are placed by the shoulder alignment only, so a garment whose collar sits low over its shoulder points (#47, square neck) lands
    below the body's shoulder contour and the avatar's own top shows above it. A target below the contour (the first
    background -> figure step under the neck row, in its column) is raised to `margin` px above it, never lowered,
    at most `max_raise` px. Returns {name: px raised}; pairs are changed in place."""
    H, W = mask.shape
    y_neck = int(round(_f(blm["neck"]["y"])))
    out = {}
    for name in ("neck_l", "neck_r"):
        if name not in pairs:
            continue
        q, (tx, ty), w = pairs[name]
        x = int(round(tx))
        if not 0 <= x < W:
            continue
        col = mask[max(y_neck, 0):, x].astype(bool)
        steps = np.nonzero(~col[:-1] & col[1:])[0]  # background -> figure, top down
        if not len(steps):
            continue
        top = max(y_neck, 0) + int(steps[0]) + 1
        new_y = top - margin
        if ty > new_y and ty - new_y <= max_raise:
            pairs[name] = (q, (tx, float(new_y)), w)
            out[name] = round(ty - new_y, 1)
    return out



def shoulder_line(pairs, glm, blm, mask, g_alpha, fractions=SHOULDER_LINE_FRACTIONS, ease=SHOULDER_LINE_EASE,
                  edge_alpha=128):
    """Round 9 benchmark (keyword tshirt_layer(shoulder_variant="line"), adapt only, docs/06 "Shoulder line fit,
    round 9"): per side, 3 pairs `sline<NN>_l|r` on the shoulder LINE. Garment: the top alpha edge (alpha > 128) in
    the column at fraction f of collar edge -> shoulder seam. Body: in the column at f of neck edge (neck.left_x /
    right_x) -> acromion (shoulder.left_x / right_x), the first background -> figure step under the neck row (the
    collar_floor rule, so the head and hair above the neck row are not taken), target moved UP by `ease` px.
    Weight = the shoulder pair's. A side is skipped (reason in the report) when a collar point is missing or a sample
    has no edge. Returns {side: {"pairs": [...], "skipped": reason?, "head_columns": [...], "steep": [...]}}; pairs
    are added in place. edge_alpha (round 9b): the garment edge is the first row with alpha > edge_alpha (default
    128; HARD_EDGE - 1 = the edge the fitted layer keeps after its hard-edge cut)."""
    H, W = mask.shape
    gH, gW = g_alpha.shape
    solid = g_alpha > edge_alpha
    y_neck = max(int(round(_f(blm["neck"]["y"]))), 0)
    report = {}

    def g_edge(x):
        x = int(round(x))
        if not 0 <= x < gW:
            return None
        ys = np.nonzero(solid[:, x])[0]
        return int(ys[0]) if len(ys) else None

    def b_edge(x):
        """(edge y or None, head/hair above: the column is figure at the neck row)."""
        x = int(round(x))
        if not 0 <= x < W:
            return None, False
        col = mask[y_neck:, x].astype(bool)
        steps = np.nonzero(~col[:-1] & col[1:])[0]
        return (y_neck + int(steps[0]) + 1 if len(steps) else None), bool(col[0])

    def steep(edge, x):
        a, b = edge(x - 1), edge(x + 1)
        a = a[0] if isinstance(a, tuple) else a
        b = b[0] if isinstance(b, tuple) else b
        return a is not None and b is not None and abs(b - a) / 2.0 > SHOULDER_LINE_STEEP

    for side, sx in (("left", "_l"), ("right", "_r")):
        rep = {"pairs": [], "head_columns": [], "steep": []}
        report[side] = rep
        try:
            gc, gs = _f(glm["collar"][f"{side}_x"]), _f(glm["shoulder"][f"{side}_x"])
            bc, bs = _f(blm["neck"][f"{side}_x"]), _f(blm["shoulder"][f"{side}_x"])
        except (KeyError, TypeError):
            rep["skipped"] = "collar or neck point missing"
            continue
        new = {}
        for f in fractions:
            name = f"sline{int(round(f * 100)):02d}{sx}"
            gx, bx = gc + f * (gs - gc), bc + f * (bs - bc)
            gy = g_edge(gx)
            by, head = b_edge(bx)
            if head:
                rep["head_columns"].append(int(round(bx)))
            if gy is None or by is None:
                rep["skipped"] = f"no {'garment' if gy is None else 'body'} edge at {int(round(f * 100))} %"
                new = {}
                break
            if steep(g_edge, gx):
                rep["steep"].append(f"garment {name}")
            if steep(b_edge, bx):
                rep["steep"].append(f"body {name}")
            new[name] = ((float(int(round(gx))), float(gy)), (float(int(round(bx))), float(by - ease)),
                         SHOULDER_LINE_WEIGHT)
        pairs.update(new)
        rep["pairs"] = sorted(new)
    return report


def tshirt_layer(garment_img, glm, body_lm, mask, fit_mode="adapt", H=1200, W=600, hem_rule=(0.35, 10.0), *,
                 sleeve_variant="r7", debug_map=False, side_floor=False, neckline_variant="r7", source="body",
                 base=None, neck_clip=False, neck_hole_polygon=None, collar_floor_on=True, shoulder_variant="off",
                 shoulder_fractions=SHOULDER_LINE_FRACTIONS, shoulder_ease=SHOULDER_LINE_EASE,
                 shoulder_edge_alpha=128):
    """(BGRA layer HxW, info {engine, pairs, rejected, s, neck_opening?, sleeve_hems, runtime, map?}).
    Raises MlsUnavailable (missing landmarks, failed core pairs, bad geometry): the caller uses the parts engine.
    sleeve_variant: benchmark only (module docstring); debug_map: info["map"] = (mx, my) for the fold metric."""
    if sleeve_variant not in SLEEVE_VARIANTS:  # a programming error, never a silent fallback to parts
        raise ValueError(f"unknown sleeve variant: {sleeve_variant!r}")
    if neckline_variant not in NECKLINE_VARIANTS:
        raise ValueError(f"unknown neckline variant: {neckline_variant!r}")
    if shoulder_variant not in SHOULDER_VARIANTS:
        raise ValueError(f"unknown shoulder variant: {shoulder_variant!r}")
    if fit_mode == "keep_shape":  # shoulder line: adapt only (round 9 benchmark), a no-op in keep_shape
        shoulder_variant = "off"
    if neckline_variant in ("clear_skin", "hole_skin") and source != "avatar":  # docs/02 rule 12, docs/09 #89
        neckline_variant = neckline_variant.replace("_skin", "")
    if fit_mode == "keep_shape":  # side_floor disabled for keep_shape for now (owner, 2026-11-12): a no-op there
        side_floor = False
    t0 = time.perf_counter()
    miss = missing_landmarks(glm)
    if miss:
        raise MlsUnavailable(f"missing landmarks: {', '.join(miss)}")
    img = prod._bgra(garment_img)
    fitted = fit_mode != "keep_shape"
    try:
        pairs, rejected, s = control_points(glm, body_lm, mask, k_map_for(fit_mode), fitted, hem_rule,
                                            sleeve_variant=sleeve_variant, side_floor=side_floor)
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
        raise MlsUnavailable(f"control points: {e!r}") from e
    lost = [n for n in CORE_PAIRS if n not in pairs]
    if lost:
        raise MlsUnavailable(f"pair validation failed: {', '.join(lost)}")
    sline = shoulder_line(pairs, glm, body_lm, mask, img[:, :, 3], shoulder_fractions, shoulder_ease,
                          shoulder_edge_alpha) if shoulder_variant == "line" else None
    raised = collar_floor(pairs, body_lm, mask) if collar_floor_on else None
    mx, my = _inverse_maps(pairs, s, H, W)
    if side_floor:  # second stage: pairs where the first solve left the garment edge, x floored; solve again
        before = set(pairs)
        _add_side_floor_pairs(pairs, glm, body_lm, mask, img[:, :, 3] > 128, mx, my, rejected)
        if set(pairs) != before:  # only when the floor added a pair: otherwise the first solve stands as it is
            mx, my = _inverse_maps(pairs, s, H, W)
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
    if raised is not None:
        info["collar_floor"] = raised
    if sline is not None:
        info["shoulder_line"] = sline
    if debug_map:
        info["map"] = (mx, my)
    geo = prod.back_collar_geometry(img[:, :, 3] > 128, glm, img)
    if geo:
        g_cx = (_f(glm["shoulder"]["left_x"]) + _f(glm["shoulder"]["right_x"])) / 2
        a_cx = (_f(body_lm["shoulder"]["left_x"]) + _f(body_lm["shoulder"]["right_x"])) / 2
        g_sy, a_sy = _f(glm["shoulder"]["y"]), _f(body_lm["shoulder"]["y"])
        info["neck_opening"] = {"cx": a_cx + (geo["cx"] - g_cx) * s, "hw": geo["hw"] * s,
                                "y0": a_sy + (geo["y0"] - g_sy) * s, "depth": geo["depth"] * s}
        layer = prod.clear_back_collar(layer, info["neck_opening"], body_lm)
    if neckline_variant != "r7":
        if neckline_variant.startswith("hole"):
            if neck_hole_polygon is not None:  # owner-drawn interior (fallback b), garment px
                hole = np.zeros(img.shape[:2], np.uint8)
                cv2.fillPoly(hole, [np.round(np.asarray(neck_hole_polygon, float) * 8).astype(np.int32)], 1, shift=3)
                hole = hole > 0
                meta = {"source": "polygon", "hole_px": int(hole.sum())}
                area = abs(cv2.contourArea(np.asarray(neck_hole_polygon, np.float32))) \
                    if len(neck_hole_polygon) >= 3 else 0.0
                if area < 1.0 or not hole.any():  # degenerate polygon: no hole, r7 output
                    hole, meta = None, "polygon has no area"
            else:
                hole, meta = neckline_hole(img, glm)
            w = None if hole is None else np.clip(
                cv2.remap(hole.astype(np.float32), mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                          borderValue=0), 0, 1)
            if hole is not None:
                info["neck_hole_garment"] = hole
        else:
            w, meta = neckline_opening(pairs, glm, H, W)
        info["neckline"] = {"variant": neckline_variant, **({"skipped": meta} if w is None else
                                                             {k: v for k, v in meta.items() if k != "side"})}
        if w is not None:
            a = layer[:, :, 3].astype(np.float32) * (1 - w)  # union with the r7 clearing: alpha only goes down
            layer[:, :, 3] = np.clip(np.rint(np.minimum(a, layer[:, :, 3])), 0, 255).astype(np.uint8)
            info["neck_weight"] = w
            if neckline_variant in ("clear_skin", "hole_skin") and base is not None:
                skin = _neck_skin(base, mask, body_lm)
                if skin is not None:
                    gap = (w > 0) & mask & ~prod.skin_like(base, skin)
                    wt = np.maximum(cv2.GaussianBlur(gap.astype(np.float32), (0, 0), prod.NECK_GAP_FEATHER), gap)
                    wt = wt * mask * (w > 0) * (layer[:, :, 3] < 250)
                    fill = np.zeros((H, W, 4), np.uint8)
                    fill[:, :, :3] = skin
                    fill[:, :, 3] = np.clip(np.rint(wt * 255), 0, 255).astype(np.uint8)
                    info["neck_fill"] = fill
    if neck_clip:
        box = neck_clip_box(pairs, body_lm, H, W)
        if box is not None:
            k = 2 * NECK_CLIP_DILATE + 1
            fig = cv2.dilate(mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
            soft = cv2.GaussianBlur(fig.astype(np.float32), (0, 0), 0.7)
            soft = np.where(fig > 0, np.maximum(soft, 0.5), soft)  # the dilated mask itself keeps >= half alpha
            soft[mask] = 1.0  # never lower the garment over the figure itself
            lim = np.where(box, np.clip(soft, 0, 1) * 255, 255)
            layer[:, :, 3] = np.minimum(layer[:, :, 3], np.rint(lim)).astype(np.uint8)
            info["neck_clip"] = {"dilate_px": NECK_CLIP_DILATE}
    hems = {}
    for side, sx in (("left", "_l"), ("right", "_r")):  # the hands/forearms overlay starts at the cuff line
        if "cuff_out" + sx in pairs and "cuff_in" + sx in pairs:
            sh = np.array([_f(body_lm["shoulder"][f"{side}_x"]), _f(body_lm["shoulder"]["y"])])
            hems[side] = (np.float32(pairs["cuff_out" + sx][1]), np.float32(pairs["cuff_in" + sx][1]), sh)
    info["sleeve_hems"] = hems
    info["runtime"] = time.perf_counter() - t0
    return layer, info
