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
hem_mode (keyword only, benchmark round 12, default "off"; adapt only): "smooth" = `smooth_hem` on the finished layer;
"garment" (round 12b) = `garment_hem`: the bottom edge follows the garment's own hem curve between the hem targets.
hem_c_pair (keyword only, round 12b, default False; adapt only): one extra pair, the garment's hem centre (bottom edge
at the middle column between the hem corners) -> the midpoint of the hem targets, weight 1.0.

side_floor_mode (keyword only, benchmark round 12, default "landmarks" = round 10; only with side_floor=True, adapt):
"mask" places floor pairs every SIDE_FLOOR_STEP px from armpit to hem from the mask's torso edge (arm-touch rows
interpolated, `torso_side_edges`), garment edge at the HARD_EDGE alpha, docs/06 "Side coverage, round 12". Round 12b:
"mask" blends its map back to the landmark floor map (`_blend_new_holes`) around every figure px it uncovers that the
landmark floor solve covered, until no such px is left (ANCHOR_ITERS rounds at most); last guard: the finished
landmark floor layer (same keywords, side_floor_mode "landmarks", tube_arm "r11") is built too and any figure px it
covers that the "mask" layer does not (outside the px cleared beyond a fit tube's cuff) takes its px
(info["side_floor_mask"]["patched_px"]).

sleeve_mode (keyword only, benchmark round 11, default "mls"; render_tryon never passes it): "tube" / "tube_perp"
re-map each sleeve as a strip widened to the arm (`tube_sleeves`, adapt only, a no-op in keep_shape), docs/06 "Tube sleeve, round 11".
tube_arm (keyword only, round 12b / 13, default "r11"; only with a tube sleeve_mode): "finished" (round 13) = the
"fit" widths; leftover MLS sleeve px cleared only (a) over the background beyond the arm + ease or (b) over the arm
below the tube's cuff line, never in the underarm zone (`_underarm_zone`) or the torso; "finished_a" = rule (a) only
(the gate fallback). Round 13b ("finished"): the rule (b) cut is kept out of remove_halo (clean fabric, no photo
fringe: the cuff edge stays on the cuff line) and enclosed holes of the final contour in `sleeve_zone` are filled
(rule #63, info["tube"]["filled_px"]). armpit_mode="r14" (round 14,
benchmark, with side_floor, docs/06 "Armpit wedge, round 14"): the garment's torso side seam is pinned to the
arm/torso boundary (`arm_torso_boundary`) from the cuff row down to the crease, in a second solve used only in a
window around the armpits (`_add_armpit_pairs`); tube rule (b) and the seam ease are cut on that boundary; a local
guard puts back figure px the map without those pairs covers. "fit" = the arm floor also from the
straight arm fit (`_arm_at`, the real arm width, not cut at the armhole line), output half-widths clamped to
[arm x CUFF_ARM_EASE, arm x TUBE_ARM_MAX], and the MLS sleeve px beyond the tube's cuff line cleared.

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
SLEEVE_MODES = ("mls", "tube", "tube_perp")
SIDE_FLOOR_MODES = ("landmarks", "mask")
SIDE_FLOOR_STEP = 12  # px between the body rows of side_floor_mode="mask"
SIDE_FLOOR_EASE_PX = 2  # px: the "mask" floor target sits this far outward of the torso edge
SIDE_FLOOR_HEM_BAND = 0.08  # x torso length (shoulder -> hem target): no "mask" floor rows in this band above the hem
HEM_MODES = ("off", "smooth", "garment")
HEM_GARMENT_WARN_STRETCH = 1.25  # hem_mode="garment": a vertical stretch above this in the hem band is reported
TUBE_ARMS = ("r11", "fit", "finished", "finished_a")
ARMPIT_MODES = ("off", "r14")  # keyword armpit_mode (round 14; round 13c "r13c" was deleted 2026-11-15)
ARMPIT_STEP = 4  # px between the body rows of the round 14 torso-seam pairs (cuff row -> crease)
ARMPIT_INSIDE = 20  # px inside the arm/torso boundary where the first solve gives the garment row of a body row
ARMPIT_LEAD = 4  # px: the pinned seam starts this far above the point where the cuff line meets the boundary
ARMPIT_RUN = 24  # px: and runs at least this far down (the last row keeps the first solve's garment row)
ARMPIT_EASE = 4  # px: the seam target sits this far on the arm side of the boundary (clipped back with a tube)
ARMPIT_CRUMB = 8  # px: detached garment pieces up to this size inside the window are removed
ARMPIT_KEEP = 14  # px around those pairs where the round 14 solve is used in full
ARMPIT_SIGMA = 6.0  # px: Gaussian ramp of that window; outside it the map is the one without the armpit pairs
TUBE_FRINGES = ("keep", "drop")  # keyword tube_fringe (round 16): the tube's photo-fringe px over solid MLS fabric
TUBE_FRINGE_VISIBLE = 6  # grey levels: a fringe px that changes the fabric below by more than this is reported
CUFF_MODES = ("chord", "hem")  # keyword cuff_mode (round 15): the tube's t = 1 garment line
CUFF_HEM_FROM = 0.5  # cuff_mode="hem": the garment rows are pulled back to the real hem over t >= this (smoothstep)
CUFF_HEM_SHORT = 0.85  # cuff_mode="hem": a marched cuff half-width below this x the landmark half-chord is re-measured
CUFF_HEM_MAX = 0.25  # x the garment sleeve axis length: a hem farther above the chord than this is not followed
TUBE_ARM_MAX = 1.25  # tube_arm="fit": output half-width <= arm extent x this (ghost-mannequin sleeves follow the arm)
ANCHOR_ITERS = 4  # side_floor_mode="mask": rounds of the local blend back to the landmark floor map
BLEND_GROW = 4  # px: the uncovered area grows by this x the round number before it is blended
BLEND_SIGMA = 4.0  # px: Gaussian ramp of the blend weight around that area
HEM_SMOOTH_WAVE = 0.15  # x the hem width: waves shorter than this are smoothed out (hem_mode="smooth")
HEM_SMOOTH_BAND = 0.08  # x torso length: the vertical remap of hem_mode="smooth" stays inside this band
HEM_SMOOTH_NEAR = 60  # px: only columns whose bottom edge is this close to the hem target row are smoothed
SIDE_TOUCH = 1.3  # a side's mask edge farther from the axis than this x the landmark half-span = an arm touching
TUBE_SECTIONS = 6  # cross-sections along the sleeve (a parameter: long sleeves would reuse the tube with more)
TUBE_CLIPS = ("armhole", "arm")
TUBE_CLIP_EASE = 2  # px the tube may reach past the arm/torso boundary (clip="arm")
TUBE_BLEND_PX = 10  # px from the body armhole segment over which the tube map is blended into the torso MLS map
TUBE_U_MARGIN = 0.15  # the strip extends this x the half-width beyond each edge (antialiased edges, no clipping)
TUBE_SUB = 6  # mesh steps per section interval (t) for the piecewise-affine inverse map
TUBE_RAMP_T = 0.33  # garment widths ramp (smoothstep) from the t = 0 width to garment x s over t <= this
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

KEEP_SCALES = ("shoulder", "fit")
KEEP_SCALE_EASE = 1.04  # "fit": the garment's chest / waist / hem rows are at least this much wider than the body's
KEEP_SCALE_MAX = 1.45  # "fit": at most this many times the shoulder scale (a cropped T-shirt is not blown up)
KEEP_NECK_T = 0.25  # keep_shape (docs/09 #121): the collar line sits at least at neck.y + this x (shoulder.y - neck.y),
# where regular (adapt) T-shirts put it (#28 0.11-0.19, #43 0.23-0.34, #40 0.10-0.28, #45 0.16-0.33 on 6 avatars)


def keep_neck_dy(pairs, blm):
    """keep_shape (docs/09 #121): whole px the aligned garment moves down so its collar line (the neck_l / neck_r
    targets) reaches neck.y + KEEP_NECK_T x (shoulder.y - neck.y); only down (0 when it is already lower)."""
    collar = (pairs["neck_l"][1][1] + pairs["neck_r"][1][1]) / 2
    ny = _f(blm["neck"]["y"])
    target = ny + KEEP_NECK_T * (_f(blm["shoulder"]["y"]) - ny)
    return max(int(round(target - collar)), 0)


def keep_neck_pairs(pairs, blm, dy):
    """keep_shape (docs/09 #121), in place: every target moves down by dy, then the shoulder targets' y is bound to
    the body's shoulder row (x as aligned), so the lowered garment's shoulder line is pulled back up onto the body's
    shoulders by the MLS warp instead of leaving them bare."""
    for k, (q, p, w) in list(pairs.items()):
        pairs[k] = (q, (p[0], p[1] + dy), w)
    a_sy = _f(blm["shoulder"]["y"])
    for k in ("shoulder_l", "shoulder_r"):
        if k in pairs:
            q, p, w = pairs[k]
            pairs[k] = (q, (p[0], a_sy), w)


def keep_shape_scale(glm, blm, hem_y):
    """keep_shape scale "fit" (docs/09 #112): the largest of (a) the shoulder scale (seam on the acromion),
    (b) the length scale (garment shoulder..hem = body shoulder..hem row: T-shirt lengths differ little between
    regular and oversized cuts, widths differ a lot) and (c) the width scales (garment chest / waist / hem row at
    least KEEP_SCALE_EASE x the body's chest / waist / hip row), capped at KEEP_SCALE_MAX x the shoulder scale."""
    w = lambda lm, r: _f(lm[r]["right_x"]) - _f(lm[r]["left_x"])  # noqa: E731
    s_sh = w(blm, "shoulder") / w(glm, "shoulder")
    cands = [s_sh, (hem_y - _f(blm["shoulder"]["y"])) / max(_f(glm["hem"]["y"]) - _f(glm["shoulder"]["y"]), 1e-6)]
    for g_row, b_row in (("chest", "chest"), ("waist", "waist"), ("hem", "hip")):
        cands.append(KEEP_SCALE_EASE * w(blm, b_row) / max(w(glm, g_row), 1e-6))
    return min(max(cands), KEEP_SCALE_MAX * s_sh)


def keep_shape_drop(glm, blm, s):
    """Rows the aligned shoulder line sits below the body's with scale "fit": the collar stays where the shoulder
    scale puts it, so a larger scale lets the shoulder seam hang lower (a dropped shoulder), not the collar ride up."""
    s_sh = (_f(blm["shoulder"]["right_x"]) - _f(blm["shoulder"]["left_x"])) / \
        (_f(glm["shoulder"]["right_x"]) - _f(glm["shoulder"]["left_x"]))
    return max(_f(glm["shoulder"]["y"]) - _f(glm["collar"]["y"]), 0.0) * max(s - s_sh, 0.0)


def control_points(glm, blm, mask, k_map, fitted, hem_rule=(0.35, 10.0), *, sleeve_variant="r7",
                   side_floor=False, keep_scale="shoulder"):
    """(pairs {name: (q garment, p target, weight)}, rejected [names], s). sleeve_variant: module docstring."""
    if sleeve_variant not in SLEEVE_VARIANTS:
        raise ValueError(f"unknown sleeve variant: {sleeve_variant!r}")
    arms = prod.find_arms(mask, blm) if mask.any() else {}
    g_sl, g_sr, g_sy = _f(glm["shoulder"]["left_x"]), _f(glm["shoulder"]["right_x"]), _f(glm["shoulder"]["y"])
    a_sl, a_sr, a_sy = _f(blm["shoulder"]["left_x"]), _f(blm["shoulder"]["right_x"]), _f(blm["shoulder"]["y"])
    if g_sr <= g_sl or a_sr <= a_sl:
        raise MlsUnavailable("shoulder span not positive")
    s = (a_sr - a_sl) / (g_sr - g_sl)
    drop = 0.0
    if keep_scale == "fit" and not fitted:
        s = keep_shape_scale(glm, blm, body_hem_y(blm, *hem_rule))
        drop = keep_shape_drop(glm, blm, s)
        k_map = {**k_map, "shoulder": {"x": k_of(k_map, "shoulder")[0], "y": 0.0}}  # the seam hangs, not pinned up
    g_cx, a_cx = (g_sl + g_sr) / 2, (a_sl + a_sr) / 2
    aligned = lambda q: np.array([a_cx + (q[0] - g_cx) * s, a_sy + drop + (q[1] - g_sy) * s])  # noqa: E731

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



def torso_side_edges(mask, blm, ys, axis):
    """Round 12 (docs/06 "Side coverage, round 12"): per body row in `ys` and side, the torso edge x and its source:
    "mask" (the torso run through the axis; per side clean when its distance from the axis is <= SIDE_TOUCH x the
    landmark half-span), else "interp" (an arm touches: linear between the nearest clean rows of that side above and
    below; the body armpit landmark is the anchor above when no clean row is above), or None (no anchor below).
    Returns {side: [(y, x or None, src)]}."""
    out = {}
    raw = {}
    for y in ys:
        bl, br = prod.body_span(blm, y)
        run = _torso_run(mask, y, axis)
        raw[y] = (run, bl, br)
    for i, side in enumerate(("left", "right")):
        clean = {}
        for y in ys:
            run, bl, br = raw[y]
            if run is None:
                continue
            e = float(run[0]) if side == "left" else float(run[1] + 1)
            half = (axis - bl) if side == "left" else (br - axis)
            if abs(e - axis) <= SIDE_TOUCH * max(half, 1.0):
                clean[y] = e
        anchor = (float(blm["armpit"]["y"]), _f(blm["armpit"][f"{side}_x"]))
        rows = []
        for y in ys:
            if y in clean:
                rows.append((y, clean[y], "mask"))
                continue
            above = [(yy, clean[yy]) for yy in clean if yy < y]
            below = [(yy, clean[yy]) for yy in clean if yy > y]
            a = max(above) if above else anchor
            if not below:
                rows.append((y, None, None))
                continue
            b = min(below)
            t = (y - a[0]) / max(b[0] - a[0], 1e-6)
            rows.append((y, a[1] + t * (b[1] - a[1]), "interp"))
        out[side] = rows
    return out


def _add_side_floor_mask_pairs(pairs, blm, mask, img, mx, my, rejected, report):
    """side_floor_mode="mask" (round 12, adapt only): IN ADDITION to the 3 landmark-row floor pairs (side_a, side_b,
    side_hip: replacing them opened the hem corners, 2242 new hole px on #28 f-plus), every SIDE_FLOOR_STEP px from
    armpit + 2 to the hem target, skipping rows within SIDE_FLOOR_STEP / 2 of a landmark floor pair, per side: torso edge from `torso_side_edges`; garment edge = the outermost
    px of the first solve's covered run through the axis, alpha at the HARD_EDGE threshold; when that edge is inside
    the torso edge a pair is added: q = that px's garment point (first-solve map), p = torso edge moved
    SIDE_FLOOR_EASE_PX outward, weight 1.0. Pairs keep the vertical order of their side (garment and body)."""
    H, W = mask.shape
    axis = prod._crotch_x(blm)
    a_y, hem_y = _f(blm["armpit"]["y"]), pairs["hem_l"][1][1]
    band = SIDE_FLOOR_HEM_BAND * (hem_y - _f(blm["shoulder"]["y"]))
    ys_all = list(range(int(a_y) + 2, int(hem_y), SIDE_FLOOR_STEP))
    ys = [y for y in ys_all if y < hem_y - band]  # owner 2026-11-13: rows in the hem band pulled a tongue down
    report["hem_band_removed_rows"] = [y for y in ys_all if y not in ys]
    edges = torso_side_edges(mask, blm, ys, axis)
    f = img[:, :, 3].astype(np.float32)
    wa = cv2.remap(f, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    solid = wa >= HARD_EDGE
    rows_rep = []
    for side, sx in (("left", "_l"), ("right", "_r")):
        last_q = last_p = None
        taken = [pairs[n + sx][1][1] for n in SIDE_FLOOR_NAMES if n + sx in pairs]
        for y, e, src in edges[side]:
            rec = {"y": y, "side": side, "edge": None if e is None else round(e, 1), "src": src}
            rows_rep.append(rec)
            if e is None or any(abs(y - t) < SIDE_FLOOR_STEP / 2 for t in taken):
                continue
            run = next((q for q in prod._runs(solid[y]) if q[0] <= axis <= q[1]), None)
            if run is None:
                continue
            ge = run[0] if side == "left" else run[1]
            rec["garment_edge"] = int(ge)
            inside = ge > e if side == "left" else ge + 1 < e
            if not inside:
                continue
            q = (float(mx[y, ge]), float(my[y, ge]))
            if q[0] < 0 or q[1] < 0:
                continue
            p = (e - SIDE_FLOOR_EASE_PX if side == "left" else e + SIDE_FLOOR_EASE_PX, float(y))
            if last_q is not None and not (q[1] > last_q[1] + 1 and p[1] > last_p[1] + 1):
                rejected.append(f"sfm{y}{sx} (order)")
                continue
            clash = False
            for r in SIDE_ROWS:  # same vertical order as every existing side pair of this side (garment and body)
                o = pairs.get(r + sx)
                if o is not None and ((q[1] > o[0][1]) != (p[1] > o[1][1]) or abs(q[1] - o[0][1]) <= 1 or
                                      abs(p[1] - o[1][1]) <= 1):
                    clash = True
                    break
            if clash:
                rejected.append(f"sfm{y}{sx} (order vs {r}{sx})")
                continue
            pairs[f"sfm{y}{sx}"] = (q, p, 1.0)
            rec["pair"] = True
            last_q, last_p = q, p
    report["rows"] = rows_rep


def arm_torso_boundary(mask, blm, side):
    """Round 14: ({row: x}, crease (x, y) or None). The arm/torso boundary on the rows where the arm touches the
    torso, from the body armpit landmark row down to the crease = the first row where the mask separates arm and
    torso (`torso_side_edges`: "interp" rows, linear from the armpit landmark to the torso edge on the crease row;
    measured 2026-11-15: within -1.5 .. +3 px of the top of the background gap on all 6 avatars). Empty when the arm
    is separated at the armpit row already or never separates."""
    axis = prod._crotch_x(blm)
    y0 = int(_f(blm["armpit"]["y"]))
    rows, crease = {}, None
    for y, e, src in torso_side_edges(mask, blm, list(range(y0, min(y0 + 250, mask.shape[0]))), axis)[side]:
        if src == "mask":
            crease = (float(e), float(y))
            break
        if e is None:
            return {}, None
        rows[y] = float(e)
    if crease is None:
        return {}, None
    return rows, crease


def garment_notch(alpha, glm, side):
    """Round 14: the garment's own underarm corner (x, y) = the top of the transparent gap between the sleeve
    underside and the torso side, on the alpha at HARD_EDGE; None when the garment has no such gap."""
    solid = alpha >= HARD_EDGE
    gH, gW = solid.shape
    cx = (_f(glm["armpit"]["left_x"]) + _f(glm["armpit"]["right_x"])) / 2
    y = int(min(max(_f(glm["sleeve_cuff_inner"][side]["y"]), _f(glm["armpit"]["y"])) + 12, gH - 1))
    torso = next((q for q in prod._runs(solid[y]) if q[0] <= cx <= q[1]), None)
    if torso is None:
        return None
    x = torso[0] - 1 if side == "left" else torso[1] + 1
    g = next((q for q in prod._runs(~solid[y]) if q[0] <= x <= q[1]), None) if 0 <= x < gW else None
    if g is None:
        return None
    while y > 0:
        bg = [q for q in prod._runs(~solid[y - 1]) if q[0] <= g[1] and q[1] >= g[0]]
        if not bg:
            break
        g, y = (max(bg, key=lambda q: q[0]) if side == "left" else min(bg, key=lambda q: q[0])), y - 1
    return ((g[0] + g[1]) / 2, float(y))


def _cuff_line(pairs, blm, side, tube):
    """(point c, unit d towards the hand) of the sleeve's cuff line on the body: the tube's cuff (through the
    midpoint of the cuff targets, perpendicular to the tube axis) or the line through the MLS cuff targets."""
    sx = "_l" if side == "left" else "_r"
    co, ci = np.array(pairs["cuff_out" + sx][1], float), np.array(pairs["cuff_in" + sx][1], float)
    c = (co + ci) / 2
    B0 = np.array(pairs["shoulder" + sx][1], float)
    if tube:
        B1 = np.array(pairs["armpit" + sx][1], float) if "armpit" + sx in pairs else \
            np.array([_f(blm["armpit"][f"{side}_x"]), _f(blm["armpit"]["y"])])
        return c, _unit(c - (B0 + B1) / 2)
    d = _unit(np.array([-(ci - co)[1], (ci - co)[0]]))
    return c, (d if (c - B0) @ d > 0 else -d)


def _add_armpit_pairs(pairs, glm, blm, mask, img, mx, my, rejected, report, tube=True):
    """armpit_mode="r14" (round 14, adapt only, with side_floor). The garment splits into sleeve underside and torso
    side at its notch; the body splits into arm and torso at the crease, which is lower: the first solve puts the
    notch 1-74 px above the crease, and on the rows between, where the body is one silhouette, the transparent px
    between the two garment edges lie over the figure (the open wedge). Here, per side:
    - J = the point where the sleeve's cuff line meets the arm/torso boundary (the crease when the cuff is lower);
    - the garment's torso side seam is pinned to the boundary from ARMPIT_LEAD px above J downward: body rows every
      ARMPIT_STEP px, garment rows linear from the notch row + 2 (at the first body row) to the first solve's garment
      row ARMPIT_INSIDE px inside the boundary at the last body row (>= ARMPIT_RUN px below J and never above the
      crease: the fabric's vertical placement is kept there), q = the torso edge of the garment alpha on that row,
      p = the boundary moved ARMPIT_EASE px outward, weight 1.0;
    - "mask" floor pairs on those rows and side pairs out of order with the new ones (a chest pair that holds the
      seam inside the boundary) are left out of this solve;
    - the inner cuff target is moved onto the boundary when it lies inside the torso (the straight arm fit is
      extrapolated above the crease).
    `pairs` is a copy: the solve from it is used inside report["window"] only (1 around the new pairs, Gaussian
    ramp to 0), so nothing moves elsewhere."""
    H, W = mask.shape
    solid = img[:, :, 3] >= HARD_EDGE
    gH, gW = solid.shape
    cx = (_f(glm["armpit"]["left_x"]) + _f(glm["armpit"]["right_x"])) / 2
    axis = prod._crotch_x(blm)
    a_y = int(_f(blm["armpit"]["y"]))
    zone = np.zeros((H, W), np.float32)
    report["window"] = None
    for side, sx, sgn in (("left", "_l", 1), ("right", "_r", -1)):
        rep = {}
        report[side] = rep
        rows, crease = arm_torso_boundary(mask, blm, side)
        notch = garment_notch(img[:, :, 3], glm, side)
        if not rows or notch is None or "cuff_in" + sx not in pairs or "cuff_out" + sx not in pairs:
            rep["skipped"] = "no arm-touch rows" if not rows else "garment has no underarm notch" \
                if notch is None else "cuff pair dropped"
            continue
        edge = {y: e for y, e, src in torso_side_edges(mask, blm, list(range(a_y, min(a_y + 250, H))), axis)[side]
                if e is not None}
        c, d = _cuff_line(pairs, blm, side, tube)  # before any pair of this copy is changed
        j_y = next((y for y in sorted(rows) if (np.array([rows[y], y]) - c) @ d >= 0), int(crease[1]))
        rep["crease"], rep["notch"], rep["junction_y"] = crease, notch, j_y
        q_in, t_in, w_in = pairs["cuff_in" + sx]
        e = rows.get(int(round(t_in[1])))
        lim = None if e is None else e - sgn * (ARMPIT_EASE + 1)  # 1 px on the arm side of the pinned torso seam
        if tube:  # the tube draws the sleeve: its inner MLS pairs would only fight the pinned seam in the window
            rep["sleeve_pairs_left_out"] = [k for k in ("cuff_in" + sx, "smid_in" + sx) if pairs.pop(k, None)]
        elif lim is not None and (t_in[0] - lim) * sgn > 0:
            pairs["cuff_in" + sx] = (q_in, (float(lim), t_in[1]), w_in)
            rep["cuff_in_moved_px"] = round(abs(t_in[0] - lim), 1)
            if "smid_in" + sx in pairs and "armpit" + sx in pairs:
                pairs["smid_in" + sx] = (pairs["smid_in" + sx][0], tuple(
                    (np.array(pairs["armpit" + sx][1]) + np.array(pairs["cuff_in" + sx][1])) / 2), 1.0)
        # the seam starts above J, and above the inner cuff target by the length of the garment's sleeve underside
        under = max(_f(glm["sleeve_cuff_inner"][side]["y"]) - notch[1], 0.0) * report.get("s", 1.0)
        y0 = max(int(min(j_y - ARMPIT_LEAD, t_in[1] - under)), a_y + 2)
        g0 = notch[1] + 2
        y1 = gy1 = None
        for yb in range(max(int(crease[1]), y0 + ARMPIT_RUN), min(y0 + ARMPIT_RUN + 61, H), 12):
            if yb not in edge:
                break
            xi = int(round(edge[yb] + sgn * ARMPIT_INSIDE))
            if not (0 <= xi < W and mx[yb, xi] >= 0 and my[yb, xi] >= 0):
                continue
            slope = (float(my[yb, xi]) - g0) / (yb - y0)  # garment px per body px along the seam
            if 0.4 / max(report.get("s", 1.0), 1e-6) <= slope <= 2.5 / max(report.get("s", 1.0), 1e-6):
                y1, gy1 = yb, float(my[yb, xi])
                break
        if y1 is None:
            rep["skipped"] = "no row below the crease with a usable garment row"
            continue
        added = []
        for y in list(range(y0, y1, ARMPIT_STEP)) + [y1]:
            gy = g0 + (y - y0) / (y1 - y0) * (gy1 - g0)
            if y not in edge or not 0 <= int(round(gy)) < gH:
                continue
            run = next((q for q in prod._runs(solid[int(round(gy))]) if q[0] <= cx <= q[1]), None)
            if run is None:
                continue
            ease = ARMPIT_EASE if y in rows else SIDE_FLOOR_EASE_PX  # below the crease: the "mask" floor ease
            ex = edge[y] - 1 if side == "left" else edge[y]  # left: the first torso px; right: one past the last
            added.append((y, (float(run[0] if side == "left" else run[1]), gy), (ex - sgn * ease, float(y))))
        if len(added) < 2:
            rep["skipped"] = "no garment seam rows"
            continue
        gone = [k for k in pairs if k.endswith(sx) and k[:-2] not in ("armpit", "hem") and (
            k.startswith("sfm") or k[:-2] in SIDE_ROWS) and (
                y0 - ARMPIT_STEP <= pairs[k][1][1] <= y1 + ARMPIT_STEP or
                (pairs[k][0][1] > g0) != (pairs[k][1][1] > y0) or (pairs[k][0][1] > gy1) != (pairs[k][1][1] > y1))]
        for k in gone:
            del pairs[k]
        for y, q, p in added:
            pairs[f"apit{y}{sx}"] = (q, p, 1.0)
            x_ = int(round(edge[y]))
            zone[max(y - ARMPIT_KEEP, 0):y + ARMPIT_KEEP + 1, max(x_ - ARMPIT_KEEP, 0):x_ + ARMPIT_KEEP + 1] = 1
        rep.update({"rows": [a_[0] for a_ in added], "left_out": gone})
    if zone.any():
        report["window"] = np.maximum(np.clip(cv2.GaussianBlur(zone, (0, 0), ARMPIT_SIGMA), 0, 1), zone)


WEDGE_TORSO = 25  # px: the wedge metric looks this far into the torso from the arm/torso boundary
WEDGE_ARM = 12  # px: and this far onto the arm, above the cuff line only
WEDGE_CUFF_MARGIN = 2  # px: arm px closer than this to the cuff line count as below it (never counted)
RAGGED_BOX = 45  # px: half-width of the armpit box of the ragged-edge metric
RAGGED_OPEN = 5  # px: garment parts thinner than this (opening with an ellipse of this size) are spikes


def armpit_wedge(layer, mask, blm, hems):
    """Round 14 metric (benchmark / tests): per side the open wedge = figure px with alpha < 128 (a) on the torso
    side of the arm/torso boundary, at most WEDGE_TORSO px from it, rows armpit landmark -> crease + 2, or (b) on
    the arm side, at most WEDGE_ARM px from it, rows armpit landmark -> crease, ABOVE the layer's own cuff line
    (`info["sleeve_hems"]`; arm skin at or below the cuff line is correct and never counted). Independent of the
    tube's zones. Returns {side: {"px", "torso_px", "arm_px", "map"}}."""
    H, W = mask.shape
    Y, X = np.mgrid[0:H, 0:W]
    open_ = mask & (layer[:, :, 3] < 128)
    out = {}
    for side in ("left", "right"):
        rows, crease = arm_torso_boundary(mask, blm, side)
        torso, arm, arm_h = np.zeros((H, W), bool), np.zeros((H, W), bool), 0.0
        if rows:
            ex = np.full((H, 1), np.nan, np.float32)
            for y, e in rows.items():
                ex[y, 0] = e
            arm_rows = ~np.isnan(ex)
            for y in range(int(crease[1]), min(int(crease[1]) + 3, H)):
                ex[y, 0] = crease[0]
            d = (X - ex) * (1 if side == "left" else -1)  # > 0 = torso side
            ok = ~np.isnan(ex)
            torso = ok & (d >= 0) & (d < WEDGE_TORSO)
            arm = arm_rows & (d < 0) & (d >= -WEDGE_ARM)
            if side in hems:
                a, b, sh = (np.asarray(v, float) for v in hems[side])
                n = np.array([-(b - a)[1], (b - a)[0]])
                n = n / max(float(np.linalg.norm(n)), 1e-9)
                if (sh - a) @ n > 0:
                    n = -n  # n points from the shoulder to the hand
                above = -((X - a[0]) * n[0] + (Y - a[1]) * n[1])
                arm &= above > WEDGE_CUFF_MARGIN
                if (open_ & arm).any():
                    arm_h = float(above[open_ & arm].max())
            else:
                arm[:] = False
        m = open_ & (torso | arm)
        out[side] = {"px": int(m.sum()), "torso_px": int((open_ & torso).sum()), "arm_px": int((open_ & arm).sum()),
                     "arm_max_above_cuff": round(arm_h, 1), "map": m}
    return out


def armpit_ragged(layer, mask, blm):
    """Round 14 metric (benchmark / tests): ragged garment edges in the armpit box (rows armpit landmark - 10 ->
    crease + 15, RAGGED_BOX px each side of the boundary), per side: fragment_px = garment px (alpha >= 128) of
    the box that are not connected to the garment's largest piece; spike_px = garment px of the box removed by a
    morphological opening with a RAGGED_OPEN px ellipse (teeth, spikes, 1-4 px wide slivers).
    Returns {side: {"fragment_px", "spike_px", "box"}}."""
    H, W = mask.shape
    cov = (layer[:, :, 3] >= 128).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(cov, connectivity=8)
    main = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) if n > 1 else 0
    frag = (cov > 0) & (lab != main)
    spike = (cov > 0) & (cv2.morphologyEx(cov, cv2.MORPH_OPEN, cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (RAGGED_OPEN, RAGGED_OPEN))) == 0)
    out = {}
    for side in ("left", "right"):
        rows, crease = arm_torso_boundary(mask, blm, side)
        box = np.zeros((H, W), bool)
        if rows:
            xs = list(rows.values()) + [crease[0]]
            y0, y1 = max(min(rows) - 10, 0), min(int(crease[1]) + 15, H - 1)
            box[y0:y1 + 1, max(int(min(xs)) - RAGGED_BOX, 0):int(max(xs)) + RAGGED_BOX + 1] = True
        out[side] = {"fragment_px": int((frag & box).sum()), "spike_px": int((spike & box).sum()), "box": box}
    return out


def _add_hem_c_pair(pairs, glm, alpha):
    """Round 12b (hem_c_pair=True, adapt only): q = the garment's hem centre (middle column between the hem corners,
    its lowest px at alpha >= HARD_EDGE), p = the midpoint of the hem_l / hem_r targets, weight 1.0. adapt already has
    a hem_c pair (round 7: garment hem LANDMARK row at the centre -> the torso centre on the hem target row; dropped
    when out of order): this one replaces it (the old pair is reported). Returns a report."""
    gx = int(round((_f(glm["hem"]["left_x"]) + _f(glm["hem"]["right_x"])) / 2))
    b = int(hem_bottom(alpha, gx, gx)[0]) if 0 <= gx < alpha.shape[1] else -1
    if b < 0:
        return {"skipped": "no garment px in the centre column"}
    hl, hr = pairs["hem_l"][1], pairs["hem_r"][1]
    p = ((hl[0] + hr[0]) / 2, (hl[1] + hr[1]) / 2)
    prev = pairs.get("hem_c")
    pairs["hem_c"] = ((float(gx), float(b)), p, 1.0)
    return {"q": [gx, b], "p": [round(p[0], 1), round(p[1], 1)], "garment_drop_px": round(b - _f(glm["hem"]["y"]), 1),
            "replaced": None if prev is None else [[round(v, 1) for v in prev[0]], [round(v, 1) for v in prev[1]]]}


def _blend_new_holes(H, W, alpha, mask, ref_map, mx, my, report, iters=ANCHOR_ITERS, hole=None):
    """Round 12b (owner 2026-11-15, side_floor_mode="mask"): figure px the landmark floor solve (`ref_map`) covers at
    alpha >= HARD_EDGE after the remove_halo erosion and the owner's neck hole (`hole`, garment px; what the
    finished adapt layer keeps) and the "mask" solve does not get the landmark floor map back, locally: the uncovered px (grown by
    BLEND_GROW px per round) get weight 1, a Gaussian ramp (sigma BLEND_SIGMA) around them, map = (1 - w) x mask map
    + w x landmark map; repeated (the region grows) until no such px is left, at most `iters` rounds. Tried first and
    dropped (2026-11-15): anchor pairs at the holes (did not converge, opened holes at the shoulders). Returns
    (mx, my); report: blend_px (w > 0), rounds, residual px."""
    f = alpha.astype(np.float32)
    rx, ry = ref_map
    ke = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * prod.HALO_ERODE + 1,) * 2)

    def covered(x_, y_):  # as the finished layer: warped alpha, eroded like remove_halo, >= HARD_EDGE, neck hole
        a_ = cv2.remap(f, x_, y_, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        a_ = cv2.erode(a_, ke, borderType=cv2.BORDER_CONSTANT, borderValue=0)
        a_[a_ < HARD_EDGE] = 0
        if hole is not None:
            a_ = a_ * (1 - np.clip(cv2.remap(hole, x_, y_, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                                             borderValue=0), 0, 1))
        return a_ >= 128

    ref_cov = covered(rx, ry)
    m0x, m0y = mx, my
    region = np.zeros((H, W), np.uint8)
    w = np.zeros((H, W), np.float32)
    rounds, left = 0, 0
    for it in range(iters + 1):
        lost = mask & ref_cov & ~covered(mx, my)
        left = int(lost.sum())
        if not left or it == iters:
            break
        k = 2 * BLEND_GROW * (it + 1) + 1
        region = cv2.dilate(region | lost.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        w = np.maximum(cv2.GaussianBlur(region.astype(np.float32), (0, 0), BLEND_SIGMA), region.astype(np.float32))
        mx = ((1 - w) * m0x + w * rx).astype(np.float32)
        my = ((1 - w) * m0y + w * ry).astype(np.float32)
        rounds += 1
    report["blend_px"] = int((w > 0.01).sum())
    report["blend_rounds"] = rounds
    report["blend_residual_px"] = left
    return mx, my


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



def _smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def _unit(v):
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else v


def _march(inside, p, d, limit):
    """Distance from p along unit d while inside(point) holds (0.5 px steps), at most `limit`."""
    dist, step = 0.0, 0.5
    while dist + step <= limit:
        q = p + d * (dist + step)
        if not inside(q):
            break
        dist += step
    return dist


def _arm_fit_extent(arms, side, c, d):
    """Round 12b (tube_arm="fit"): arm extents (outer, inner) along the unit cross-section direction d from the tube
    centre c (u < 0 = outer, u > 0 = inner, like the tube), from the straight arm fit `_arm_at` (centre line x(y) and
    the horizontal width): the arm is a strip along its centre line; its horizontal width is converted to the width
    along d. (None, None) when the arm has no fit or d is parallel to the arm."""
    f0, f1 = _arm_at(arms, side, float(c[1])), _arm_at(arms, side, float(c[1]) + 10.0)
    if f0 is None or f1 is None:
        return None, None
    a0 = np.array([f0[0], float(c[1])])
    e = _unit(np.array([f1[0] - f0[0], 10.0]))
    cr = float(e[0] * d[1] - e[1] * d[0])
    if abs(cr) < 0.2:
        return None, None
    m = np.array([[d[0], -e[0]], [d[1], -e[1]]])
    u_c = float(np.linalg.solve(m, a0 - np.asarray(c, float))[0])  # c + u_c d = the arm centre line
    half = 0.5 * f0[1] * abs(e[1]) / abs(cr)
    return max(half - u_c, 0.0), max(half + u_c, 0.0)


def sleeve_zone(pairs, blm, H, W, around=15):
    """Shoulder / armpit / sleeve zone (both sides, = tests_mls.tube_zone): outward of the body armhole line above the
    lower cuff target + 10 px, plus `around` px around the armhole segment."""
    Y, X = np.mgrid[0:H, 0:W]
    P = np.stack([X, Y], -1).astype(np.float32)
    zone = np.zeros((H, W), bool)
    for side, sx in (("left", "_l"), ("right", "_r")):
        if "cuff_out" + sx not in pairs or "cuff_in" + sx not in pairs:
            continue
        B0 = np.array(pairs["shoulder" + sx][1], float)
        B1 = np.array(pairs["armpit" + sx][1], float) if "armpit" + sx in pairs else \
            np.array([_f(blm["armpit"][f"{side}_x"]), _f(blm["armpit"]["y"])])
        cm = (np.array(pairs["cuff_out" + sx][1]) + np.array(pairs["cuff_in" + sx][1])) / 2
        ba = np.array([-(B1 - B0)[1], (B1 - B0)[0]])
        if (cm - B0) @ ba < 0:
            ba = -ba
        ylow = max(pairs["cuff_out" + sx][1][1], pairs["cuff_in" + sx][1][1]) + 10
        seg = B1 - B0
        t = np.clip(((P - B0) @ seg) / float(seg @ seg), 0, 1)
        near = np.linalg.norm(P - (B0 + t[..., None] * seg), axis=-1) <= around
        zone |= ((((P - B0) @ ba) > 0) & (Y <= ylow)) | near
    return zone


def _fill_sleeve_holes(layer, pairs, blm):
    """Round 13b (owner 2026-11-15, rule #63 on the FINAL T-shirt contour, torso + tube): px with alpha < 128 that
    cannot reach the canvas border through alpha < 128 px (enclosed by the garment) are filled (alpha 255, colour
    from the nearest opaque px), only inside `sleeve_zone` (the neck opening is never touched). Returns
    (layer, filled px)."""
    H, W = layer.shape[:2]
    free = np.ones((H + 2, W + 2), np.uint8)
    free[1:-1, 1:-1] = layer[:, :, 3] < 128
    cv2.floodFill(free, None, (0, 0), 2)
    holes = (free[1:-1, 1:-1] == 1) & sleeve_zone(pairs, blm, H, W)
    if not holes.any():
        return layer, 0
    out = layer.copy()
    prod._colour_from_nearest_opaque(out, holes)
    out[:, :, 3][holes] = 255
    return out, int(holes.sum())


def _hem_half_width(g_in, c, d, back, length, max_r):
    """Round 15 (cuff="hem"): the garment cuff's half-width from c along unit d, at most `length` (the cuff landmark):
    the farthest point up to which the fabric is found on the chord or within max_r behind it (along -back). The
    plain march along the chord stops where the hem rises above the chord (#43 left: 3 px of a 50 px half chord)."""
    best, v = 0.0, 0.5
    while v <= length:
        p = c + d * v
        if not any(g_in(p - back * r) for r in np.arange(0.0, max_r + 0.5, 0.5)):
            break
        best, v = v, v + 0.5
    return best


def _below_cuff(P, ca, cb, d):
    """Px beyond the cuff segment ca-cb in the axis direction d, inside the strip of the cuff width x TUBE_ARM_MAX
    (never the torso beside the arm)."""
    c = (ca + cb) / 2
    cw = _unit(cb - ca)
    hw = float(np.linalg.norm(cb - ca)) / 2
    return (((P - c) @ d) > 0) & (np.abs((P - c) @ cw) <= hw * TUBE_ARM_MAX)


def _underarm_zone(H, W, inner, ca, cb, B0, B1):
    """Round 13 (owner 2026-11-15): the protected underarm zone, bounded by the body armhole line (B0-B1, extended),
    the tube's inner edge (`inner`, t = 0 -> 1) and the cuff line (ca-cb, extended): polygon armpit -> inner edge ->
    inner cuff end -> the cuff line's crossing with the armhole line. Empty when the lines do not cross."""
    zone = np.zeros((H, W), np.uint8)
    d1, d2 = B1 - B0, cb - ca
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-6:
        return zone > 0
    t = ((ca[0] - B0[0]) * d2[1] - (ca[1] - B0[1]) * d2[0]) / den
    X = B0 + t * d1
    poly = np.array([B1] + [np.asarray(p, float) for p in inner] + [cb, X], np.float64)
    cv2.fillPoly(zone, [np.round(poly * 8).astype(np.int32)], 1, shift=3)
    return zone > 0


def tube_sleeves(img, glm, blm, mask, pairs, s, mx, my, arms=None, sections=TUBE_SECTIONS, blend=TUBE_BLEND_PX,
                 mode="tube", tube_maps=None, arm="r11", armpit_mode="off", cuff="chord", clip="armhole"):
    """Round 11 benchmark (keyword tshirt_layer(sleeve_mode="tube" | "tube_perp"), adapt only, docs/06 "Tube sleeve,
    round 11"). Per side the sleeve is a strip in (t, u): t along the axis, u across (-1 = outer edge, +1 = inner
    edge, outer and inner widths measured separately at `sections` cross-sections).
    Body cuff (fix 1, owner 2026-11-13): the segment through the midpoint of the MLS cuff targets (cuff_out / cuff_in
    pairs, already on the arm), perpendicular to the axis; body axis = armhole midpoint (shoulder target -> armpit
    target) -> that point. Garment axis = armhole midpoint -> cuff midpoint.
    "tube": t = 0 on the armhole segment (garment: shoulder seam -> armpit; body: shoulder target -> armpit target),
    cross-sections turn from the armhole direction to the axis normal (ruled strip), t = 1 on the cuff.
    "tube_perp": every cross-section perpendicular to the axis; t = 0 is the perpendicular through the shoulder seam
    (body: the shoulder target); the underarm triangle between that line and the armhole stays MLS (never cleared).
    Output widths (fix 2): max(arm extent in the mask outward of the armhole line x CUFF_ARM_EASE, ramp), ramp =
    smoothstep (t <= TUBE_RAMP_T) from the t = 0 width to garment width x s; the arm floor holds at every
    cross-section after t = 0 (t = 0 itself is pinned: the armhole segment for "tube", the shoulder target outward
    for "tube_perp"). The strip is meshed and each triangle mapped affinely back to the garment; the tube map is
    smoothstep-blended into the MLS map within `blend` px of the t = 0 segment. The domain is clipped to the outward
    side of the body armhole line. A tube px must come from a garment sleeve px.
    Layering (owner 2026-11-13, the #40 underarm holes): the tube is a SEPARATE map written into `tube_maps` (tx, ty)
    and drawn OVER the MLS layer by tshirt_layer (tube wins where both exist); the MLS map is kept, and an MLS px is
    cleared only when its source is a sleeve px, the tube does not draw it, it is outward of the armhole line and it
    lies over the background beyond the figure dilated by the arm ease (median arm half-width x (CUFF_ARM_EASE - 1),
    at least 1 px). arm="fit" (round 12b): the arm extents per cross-section are also taken from the straight arm fit
    (`_arm_at`: centre line and width of the separated arm rows, the width converted to the cross-section direction),
    the larger of fit and march wins; half-widths = clamp(ramp, arm x CUFF_ARM_EASE, arm x TUBE_ARM_MAX); MLS sleeve
    px the tube does not draw beyond its cuff line (outward of the armhole line, inside the strip of the cuff width
    x TUBE_ARM_MAX) are cleared too (report "cleared_beyond_cuff_px", zone "beyond_cuff_zone" = those px grown by
    the remove_halo reach). The clamp alone can uncover a few figure px (inner armpit): with side_floor_mode="mask"
    the last guard in tshirt_layer puts them back. Tried and dropped (2026-11-15): a round 11 tube map fallback.
    cuff="hem" (round 15, owner 2026-11-15 option A): the garment's t = 1 line is the real sleeve hem where it lies
    ABOVE the chord between the cuff landmarks (per strip column: the first solid px back from the chord, at most
    CUFF_HEM_MAX x the sleeve axis), so the hem lands on the body cuff line and no arm skin shows above it; the
    garment rows are pulled back over t >= CUFF_HEM_FROM (smoothstep). Where the hem is at / below the chord nothing
    changes. The t = 1 line sits HALO_ERODE body px inside the fabric and the tube's end on the cuff line is
    kept out of remove_halo (as the rule (b) cut, "cut_b"): the cuff edge is not eroded above the line. The garment
    cuff width reaches the cuff landmarks when the hem is found behind the chord (`_hem_half_width`).
    Report "cuff_hem" (rise per column in garment px, max in body px), "cuff_cut_px".
    Returns {side: report}."""
    H, W = mask.shape
    gH, gW = img.shape[:2]
    alpha = img[:, :, 3]
    arms = arms if arms is not None else prod.find_arms(mask, blm)
    report, tube_any = {}, np.zeros((H, W), bool)
    mls_x, mls_y = mx.copy(), my.copy()
    Y, X = np.mgrid[0:H, 0:W]
    P = np.stack([X, Y], -1).astype(np.float32)
    for side, sx in (("left", "_l"), ("right", "_r")):
        rep = {"mode": mode}
        report[side] = rep
        try:
            A0 = np.array([_f(glm["shoulder"][f"{side}_x"]), _f(glm["shoulder"]["y"])])
            A1 = np.array([_f(glm["armpit"][f"{side}_x"]), _f(glm["armpit"]["y"])])
            C0 = np.array([_f(glm["sleeve_cuff_outer"][side]["x"]), _f(glm["sleeve_cuff_outer"][side]["y"])])
            C1 = np.array([_f(glm["sleeve_cuff_inner"][side]["x"]), _f(glm["sleeve_cuff_inner"][side]["y"])])
        except (KeyError, TypeError):
            rep["skipped"] = "garment armpit / shoulder / cuff missing"
            continue
        if not all(k + sx in pairs for k in ("shoulder", "cuff_out", "cuff_in")):
            rep["skipped"] = "shoulder or cuff pair dropped"
            continue
        B0 = np.array(pairs["shoulder" + sx][1], float)
        B1 = np.array(pairs["armpit" + sx][1], float) if "armpit" + sx in pairs else \
            np.array([_f(blm["armpit"][f"{side}_x"]), _f(blm["armpit"]["y"])])
        Mb0 = (B0 + B1) / 2
        Mb1 = (np.array(pairs["cuff_out" + sx][1], float) + np.array(pairs["cuff_in" + sx][1], float)) / 2  # fix 1
        Mg0, Mg1 = (A0 + A1) / 2, (C0 + C1) / 2
        d_b, d_g = _unit(Mb1 - Mb0), _unit(Mg1 - Mg0)
        gA, gC, bA = _unit(A1 - A0), _unit(C1 - C0), _unit(B1 - B0)
        nrm = np.array([-d_b[1], d_b[0]])  # body axis normal, oriented outer -> inner like the armhole
        if nrm @ bA < 0:
            nrm = -nrm
        ng = np.array([-d_g[1], d_g[0]])
        if ng @ gA < 0:
            ng = -ng
        if mode == "tube_perp":  # t = 0 = the perpendicular through the shoulder seam / shoulder target
            G0 = Mg1 + d_g * ((A0 - Mg1) @ d_g)
            O0 = Mb1 + d_b * ((B0 - Mb1) @ d_b)
        else:
            G0, O0 = Mg0, Mb0
        ga = np.array([-gA[1], gA[0]])
        if (Mg1 - A0) @ ga < 0:
            ga = -ga
        yy, xx = np.mgrid[0:gH, 0:gW]
        g_sleeve = (((xx - A0[0]) * ga[0] + (yy - A0[1]) * ga[1]) > -1.0) & (yy <= max(C0[1], C1[1]) + 10) & \
            (alpha > 0)
        g_solid = g_sleeve & (alpha > 128)
        ba = np.array([-bA[1], bA[0]])
        if (Mb1 - B0) @ ba < 0:
            ba = -ba

        def g_in(q):
            x, y = int(round(q[0])), int(round(q[1]))
            return 0 <= x < gW and 0 <= y < gH and g_solid[y, x]

        def b_in(q):
            x, y = int(round(q[0])), int(round(q[1]))
            return 0 <= x < W and 0 <= y < H and mask[y, x] and (q - B0) @ ba > 0

        lim = 3 * max(float(np.linalg.norm(A1 - A0)), float(np.linalg.norm(C1 - C0)))
        ts = np.linspace(0.0, 1.0, sections + 1)
        G, O = [], []
        for k, t in enumerate(ts):
            gc, bc = G0 + t * (Mg1 - G0), O0 + t * (Mb1 - O0)
            if mode == "tube_perp":
                gd, bd = ng, nrm
            else:
                gd, bd = _unit((1 - t) * gA + t * gC), _unit((1 - t) * bA + t * nrm)
            if k == 0 and mode != "tube_perp":  # the armhole segment, pinned
                g_o, g_i = float(np.linalg.norm(A0 - Mg0)), float(np.linalg.norm(A1 - Mg0))
                a_o = a_i = None
                w0 = (float(np.linalg.norm(B0 - Mb0)), float(np.linalg.norm(B1 - Mb0)))
            else:
                g_o = _march(g_in, gc, -gd, lim) or 0.5 * float(np.linalg.norm(C1 - C0))
                g_i = _march(g_in, gc, gd, lim) or 0.5 * float(np.linalg.norm(C1 - C0))
                a_o, a_i = _march(b_in, bc, -bd, lim * s), _march(b_in, bc, bd, lim * s)
                if arm != "r11":
                    fo, fi = _arm_fit_extent(arms, side, bc, _unit(bd))
                    if fo is not None:
                        a_o, a_i = max(a_o, fo), max(a_i, fi)
                if cuff == "hem" and k == len(ts) - 1:  # round 15: the cuff width up to the landmarks, hem included
                    max_r_ = CUFF_HEM_MAX * float(np.linalg.norm(Mg1 - G0))
                    lo_, li_ = abs(float((C0 - gc) @ gd)), abs(float((C1 - gc) @ gd))
                    if g_o < CUFF_HEM_SHORT * lo_:  # only when the march stopped well before the landmark (the
                        g_o = max(g_o, _hem_half_width(g_in, gc, -gd, d_g, lo_, max_r_))  # chord left the fabric
                    if g_i < CUFF_HEM_SHORT * li_:  # through the hem, not through the sleeve's side edge)
                        g_i = max(g_i, _hem_half_width(g_in, gc, gd, d_g, li_, max_r_))
                if k == 0:  # tube_perp t = 0: outer pinned at the shoulder target, inner from the garment
                    w0 = (float(abs((B0 - O0) @ nrm)), g_i * s)
            G.append([gc, gd, g_o, g_i])
            O.append([bc, bd, None, None, a_o, a_i])
        for k, t in enumerate(ts):  # fix 2: ramp only the garment part, the arm floor at every section after t = 0
            r = _smoothstep(t / TUBE_RAMP_T) if TUBE_RAMP_T > 0 else 1.0
            ramp_o = w0[0] + (G[k][2] * s - w0[0]) * r
            ramp_i = w0[1] + (G[k][3] * s - w0[1]) * r
            if k == 0:
                O[k][2], O[k][3] = w0
            elif arm != "r11":  # round 12b: clamp(garment x s ramp, arm x ease, arm x TUBE_ARM_MAX)
                O[k][2] = float(np.clip(ramp_o, O[k][4] * CUFF_ARM_EASE, O[k][4] * TUBE_ARM_MAX)) if O[k][4] else ramp_o
                O[k][3] = float(np.clip(ramp_i, O[k][5] * CUFF_ARM_EASE, O[k][5] * TUBE_ARM_MAX)) if O[k][5] else ramp_i
            else:
                O[k][2] = max(O[k][4] * CUFF_ARM_EASE, ramp_o)
                O[k][3] = max(O[k][5] * CUFF_ARM_EASE, ramp_i)
        tt = np.linspace(0.0, 1.0, sections * TUBE_SUB + 1)
        uu = np.linspace(-1 - TUBE_U_MARGIN, 1 + TUBE_U_MARGIN, 23)

        def at(seq, t):
            f = t * sections
            k = min(int(f), sections - 1)
            r = f - k
            return [None if x is None or y is None else (1 - r) * np.asarray(x, float) + r * np.asarray(y, float)
                    for x, y in zip(seq[k], seq[k + 1])]

        def point(sec, u):
            c, d, w_o, w_i = sec[0], _unit(sec[1]), float(sec[2]), float(sec[3])
            return c + d * (u * (w_i if u > 0 else w_o))

        inner_base = [point(at(O, t), 1.0) for t in tt]  # the tube's inner edge

        P_out = np.zeros((len(tt), len(uu), 2), np.float32)
        P_g = np.zeros((len(tt), len(uu), 2), np.float32)
        for i, t in enumerate(tt):
            go, oo = at(G, t), at(O, t)
            for j, u in enumerate(uu):
                P_out[i, j] = point(oo, u)
                P_g[i, j] = point(go, u)
        P_g0 = None
        if cuff == "hem":  # round 15: t = 1 follows the garment's real hem where it rises above the chord
            P_g0 = P_g.copy()  # the chord mapping, for the edge guard below
            n_sub = min(TUBE_SUB, len(tt) - 1)
            max_r = CUFF_HEM_MAX * float(np.linalg.norm(Mg1 - G0))
            inset = prod.HALO_ERODE / max(s, 1e-6)  # garment px: t = 1 samples fabric inside the photo fringe
            rise = np.full(len(uu), np.nan)
            dirs = np.zeros((len(uu), 2))
            for j, u in enumerate(uu):
                dirs[j] = _unit(P_g[-1, j].astype(float) - P_g[-1 - n_sub, j].astype(float))
                if abs(u) > 1.0:
                    continue  # the margin columns take the nearest fabric column's value
                p0 = P_g[-1, j].astype(float)
                if g_in(p0):  # the hem is at / below the chord: pulled back only when closer than the inset
                    rise[j] = max(inset - _march(g_in, p0, dirs[j], inset + 1.0), 0.0)
                    continue
                r_ = 0.5
                while r_ <= max_r:
                    if g_in(p0 - dirs[j] * r_):
                        rise[j] = r_ + inset
                        break
                    r_ += 0.5
            okr = ~np.isnan(rise)
            if okr.any():
                idx = np.arange(len(uu))
                rise = np.interp(idx, idx[okr], rise[okr])
                for i, t in enumerate(tt):
                    wt_ = float(_smoothstep((t - CUFF_HEM_FROM) / max(1.0 - CUFF_HEM_FROM, 1e-6)))
                    if wt_ > 0:
                        P_g[i] -= (dirs * (rise * wt_)[:, None]).astype(np.float32)
                rep["cuff_hem"] = {"u": [round(float(u), 3) for u in uu],
                                   "rise_garment_px": [round(float(r_), 1) for r_ in rise],
                                   "not_found_cols": int((~okr & (np.abs(uu) <= 1.0)).sum()),
                                   "rise_max_body_px": round(float(rise.max()) * s, 1),
                                   "rise_max_u": round(float(uu[int(rise.argmax())]), 3)}
            else:
                rep["cuff_hem"] = {"skipped": "no hem found above the chord"}
        tmx = np.full((H, W), -1.0, np.float32)
        tmy = np.full((H, W), -1.0, np.float32)
        if P_g0 is not None:
            tmx0, tmy0 = tmx.copy(), tmy.copy()
        dom = np.zeros((H, W), bool)
        for i in range(len(tt) - 1):
            for j in range(len(uu) - 1):
                quad = ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))
                for tri in ((quad[0], quad[1], quad[2]), (quad[0], quad[2], quad[3])):
                    src = np.float32([P_out[a_] for a_ in tri])
                    dst = np.float32([P_g[a_] for a_ in tri])
                    x0, y0 = np.floor(src.min(0)).astype(int)
                    x1, y1 = np.ceil(src.max(0)).astype(int)
                    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, W - 1), min(y1, H - 1)
                    if x1 < x0 or y1 < y0:
                        continue
                    m = np.zeros((y1 - y0 + 1, x1 - x0 + 1), np.uint8)
                    cv2.fillConvexPoly(m, np.round((src - [x0, y0]) * 16).astype(np.int32), 1, cv2.LINE_8, 4)
                    if not m.any():
                        continue
                    try:
                        M = cv2.getAffineTransform(src, dst)
                    except cv2.error:
                        continue
                    ys, xs = np.nonzero(m)
                    Xs, Ys = xs + x0, ys + y0
                    tmx[Ys, Xs] = M[0, 0] * Xs + M[0, 1] * Ys + M[0, 2]
                    tmy[Ys, Xs] = M[1, 0] * Xs + M[1, 1] * Ys + M[1, 2]
                    dom[Ys, Xs] = True
                    if P_g0 is not None:
                        M0 = cv2.getAffineTransform(src, np.float32([P_g0[a_] for a_ in tri]))
                        tmx0[Ys, Xs] = M0[0, 0] * Xs + M0[0, 1] * Ys + M0[0, 2]
                        tmy0[Ys, Xs] = M0[1, 0] * Xs + M0[1, 1] * Ys + M0[1, 2]
        if P_g0 is not None:  # edge guard: a px the chord mapping covers better keeps the chord source (the pull
            a_h = cv2.remap(alpha, tmx, tmy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            a_c = cv2.remap(alpha, tmx0, tmy0, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            swap = dom & (a_c > a_h)  # moves the sleeve's wavy side edges by up to 1 px; background px too: the
            # halo erosion works from the outer contour)
            tmx[swap], tmy[swap] = tmx0[swap], tmy0[swap]
            rep["cuff_guard_px"] = int(swap.sum())
        gx, gy = np.rint(tmx).astype(int), np.rint(tmy).astype(int)
        okg = (gx >= 0) & (gx < gW) & (gy >= 0) & (gy < gH)
        src_sleeve = np.zeros((H, W), bool)
        src_sleeve[okg] = g_sleeve[gy[okg], gx[okg]]
        tmx[dom & ~src_sleeve] = -1
        tmy[dom & ~src_sleeve] = -1
        sx_, sy_ = np.rint(mls_x).astype(int), np.rint(mls_y).astype(int)
        okm = (sx_ >= 0) & (sx_ < gW) & (sy_ >= 0) & (sy_ < gH)
        mls_sleeve = np.zeros((H, W), bool)
        mls_sleeve[okm] = g_sleeve[sy_[okm], sx_[okm]] & (alpha[sy_[okm], sx_[okm]] > 0)
        out_side = ((P - B0) @ ba) > 0
        dom &= out_side  # the tube works only outward of the body armhole line (torso px never touched)
        if clip == "arm":  # round 20 (docs/09 #113): below the armpit row the extended armhole line runs into the
            # chest; there the tube ends on the arm/torso boundary (touch rows) and on the crease column below it
            b_rows, crease = arm_torso_boundary(mask, blm, side)
            if crease is not None:
                lim = np.full(H, np.nan, np.float32)
                for y_, x_ in b_rows.items():
                    lim[int(y_)] = x_
                lim[int(crease[1]):] = crease[0]
                edge = lim[:, None] + (TUBE_CLIP_EASE if side == "left" else -TUBE_CLIP_EASE)
                with np.errstate(invalid="ignore"):
                    torso_px = (X > edge) if side == "left" else (X < edge)
                under = np.zeros((H, W), bool)  # only where the MLS layer below has solid fabric: nothing uncovered
                under[okm] = alpha[sy_[okm], sx_[okm]] >= 250
                under = cv2.erode(under.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
                torso_px &= under
                rep["clip_arm_px"] = int((dom & torso_px & (tmx >= 0)).sum())
                dom &= ~torso_px
        # t = 0 segment (output) and the side beyond it (towards the cuff)
        T0a, T0b = point(O[0], -1.0), point(O[0], 1.0)
        seg = T0b - T0a
        tpar = np.clip(((P - T0a) @ seg) / max(float(seg @ seg), 1e-9), 0, 1)
        dist = np.linalg.norm(P - (T0a + tpar[..., None] * seg), axis=-1)
        wgt = _smoothstep(dist / max(blend, 1e-6))
        use = dom & (tmx >= 0)
        bx = np.where(mls_x >= 0, (1 - wgt) * mls_x + wgt * tmx, tmx)
        by = np.where(mls_y >= 0, (1 - wgt) * mls_y + wgt * tmy, tmy)
        tx, ty = tube_maps
        tx[use], ty[use] = bx[use], by[use]
        # MLS stays; clear only sleeve px over the background beyond the arm + ease that the tube does not draw
        halves = [v for o in O[1:] for v in (o[4], o[5]) if v]
        ease_px = max(1, int(round(float(np.median(halves)) * (CUFF_ARM_EASE - 1)))) if halves else 1
        near = cv2.dilate(mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                                                           (2 * ease_px + 1, 2 * ease_px + 1))) > 0
        # (tried 2026-11-13 and reverted: clearing them over the arm beyond TUBE_DISTAL_T opened 117-144 px of holes
        # inside the sleeve on #28 / #40, the tube is narrower than the arm there; docs/06 round 12)
        clear = out_side & mls_sleeve & ~use & ~near & ~tube_any
        if arm in ("finished", "finished_a"):  # round 13: rule (a) never in the underarm zone; rule (b) over the arm
            ca, cb = point(O[-1], -1.0), point(O[-1], 1.0)
            prot = _underarm_zone(H, W, inner_base, ca, cb, B0, B1)
            clear &= ~prot
            rep["protected_px"] = int(prot.sum())
            rep["protected_zone"] = prot
            below = _below_cuff(P, ca, cb, d_b) & out_side
            if armpit_mode == "r14":  # round 14: the cuff-width strip x 1.25 reached torso px beside the arm; rule
                bnd, crease = arm_torso_boundary(mask, blm, side)  # (b) works on the arm side of the boundary only
                ex = np.full((H, 1), np.nan, np.float32)
                for y_, e_ in bnd.items():
                    ex[y_, 0] = e_
                torso_side = ~np.isnan(ex) & ((X >= ex) if side == "left" else (X < ex))
                if crease is not None:  # below the crease the torso is the mask run through the axis
                    ax_ = prod._crotch_x(blm)
                    for y_ in range(int(crease[1]), min(int(crease[1]) + 120, H)):
                        run_ = _torso_run(mask, y_, ax_)
                        if run_:
                            torso_side[y_, run_[0]:run_[1] + 1] = True
                below &= ~torso_side
            rep["below_cuff_zone"] = below
            if arm == "finished":
                arm_b = below & mask & mls_sleeve & ~use & ~tube_any & ~prot
                rep["cleared_below_cuff_px"] = int((arm_b & ~clear).sum())
                rep["cut_b"] = arm_b & ~clear  # round 13b: an interior cut of clean fabric, kept out of remove_halo
                clear |= arm_b
                if armpit_mode == "r14":  # torso fabric the seam ease put on the arm below the cuff line: clipped
                    arm_touch = ~np.isnan(ex) & ~torso_side  # on the arm/torso boundary (a cut, as rule b)
                    # (sleeve px too: on the touch rows rule (b) is not limited to the cuff strip / the armhole line)
                    spill = arm_touch & (((P - (ca + cb) / 2) @ d_b) > 0) & mask & (mx >= 0) & ~use & ~tube_any
                    arm_sep = np.zeros((H, W), bool)  # below the crease: torso fabric never on the separated arm
                    for y_, l_, r_ in (arms.get(side) or {}).get("rows", []):
                        arm_sep[y_, l_:r_ + 1] = True
                    spill |= arm_sep & (((P - (ca + cb) / 2) @ d_b) > 0) & (mx >= 0) & ~mls_sleeve & ~use & ~tube_any
                    rep["clipped_on_arm_px"] = int((spill & ~clear).sum())
                    rep["cut_b"] = rep["cut_b"] | (spill & ~clear)
                    clear |= spill
        elif arm == "fit":  # round 12b: the MLS sleeve px beyond the tube's cuff line go (the jagged cuffs)
            ca, cb = point(O[-1], -1.0), point(O[-1], 1.0)
            cw = _unit(cb - ca)  # across the cuff: only the strip of the cuff's own width (+ TUBE_ARM_MAX - 1 each
            hw = float(np.linalg.norm(cb - ca)) / 2  # side), never the torso px under the armpit
            lat = np.abs((P - (ca + cb) / 2) @ cw) <= hw * TUBE_ARM_MAX
            beyond = (((P - (ca + cb) / 2) @ d_b) > 0) & lat & out_side & mls_sleeve & ~use & ~tube_any
            rep["cleared_beyond_cuff_px"] = int((beyond & ~clear).sum())
            rep["cleared_beyond_cuff_figure_px"] = int((beyond & ~clear & mask).sum())
            k = 2 * (prod.HALO_ERODE + 1) + 1  # + the reach of remove_halo's erosion from that new edge (benchmark)
            rep["beyond_cuff_zone"] = cv2.dilate((beyond & ~clear).astype(np.uint8),
                                                 cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
            clear |= beyond
        mx[clear] = -1
        my[clear] = -1
        if cuff == "hem":  # round 15: the tube's end on the cuff line is a cut of clean fabric (t = 1 lies inside
            ca_, cb_ = point(O[-1], -1.0), point(O[-1], 1.0)  # the fringe), not a photo fringe: out of remove_halo
            k_ = 2 * (prod.HALO_ERODE + 1) + 1
            band = (((P - (ca_ + cb_) / 2) @ d_b) > 0) & ~use & (cv2.dilate(
                use.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_, k_))) > 0)
            rep["cuff_cut_px"] = int(band.sum())
            rep["cut_b"] = (rep["cut_b"] | band) if rep.get("cut_b") is not None else band
        tube_any |= use
        rep["ease_px"] = ease_px
        # fix 3: axis vs the arm centreline = the straight fit through the separated arm rows (_arm_at), lower half
        devs = []
        for k, t in enumerate(ts):
            if t < 0.5:
                continue
            fit = _arm_at(arms, side, float(O[k][0][1]))
            if fit is not None:
                devs.append(abs(float(O[k][0][0]) - fit[0]))
        c1 = O[-1]
        rep.update({
            "cleared_px": int(clear.sum()), "domain_px": int(dom.sum()),
            "axis_garment": [G0.round(1).tolist(), Mg1.round(1).tolist()],
            "axis_body": [O0.round(1).tolist(), Mb1.round(1).tolist()],
            "armhole_body": [B0.round(1).tolist(), B1.round(1).tolist()],
            "t0_body": [T0a.round(1).tolist(), T0b.round(1).tolist()],
            "cuff": [point(c1, -1.0).round(1).tolist(), point(c1, 1.0).round(1).tolist()],
            "sections": [[point(o, -1.0).round(1).tolist(), point(o, 1.0).round(1).tolist()] for o in O],
            "widths": [{"t": round(float(t), 3), "garment_out_in": [round(g[2], 1), round(g[3], 1)],
                        "garment_x_s": [round(g[2] * s, 1), round(g[3] * s, 1)],
                        "arm_out_in": [None if o[4] is None else round(o[4], 1), None if o[5] is None else round(o[5], 1)],
                        "out_in": [round(o[2], 1), round(o[3], 1)]} for t, g, o in zip(ts, G, O)],
            "axis_dev_max": round(max(devs), 1) if devs else None,
        })
    return report



def _gauss1d(v, sigma):
    if sigma <= 0.5:
        return v.astype(np.float64)
    r = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    pad = np.pad(v.astype(np.float64), r, mode="edge")
    return np.convolve(pad, k, mode="valid")


def hem_bottom(alpha, x0, x1):
    """Per column x0..x1: the lowest row with alpha >= HARD_EDGE (-1 when the column has none)."""
    sub = alpha[:, x0:x1 + 1] >= HARD_EDGE
    has = sub.any(0)
    last = sub.shape[0] - 1 - np.argmax(sub[::-1], 0)
    return np.where(has, last, -1)


def smooth_hem(layer, pairs, blm, mask, report):
    """hem_mode="smooth" (round 12, owner 2026-11-13; adapt only): the warped bottom edge between the hem targets is
    replaced by a smooth curve: Gaussian low-pass with sigma = HEM_SMOOTH_WAVE x hem width / 3 (waves shorter than
    ~15 % of the width go, the hem's own long shape stays). The edge only moves DOWN, or up only where every row it
    would uncover is background (e.g. a tongue between the legs): no figure px is ever uncovered. The move is a
    vertical remap of the layer inside the hem band (HEM_SMOOTH_BAND x torso length above the edge), per column."""
    H, W = mask.shape
    hl, hr = pairs["hem_l"][1], pairs["hem_r"][1]
    x0, x1 = max(int(np.floor(hl[0])), 0), min(int(np.ceil(hr[0])), W - 1)
    if x1 - x0 < 10:
        report["skipped"] = "hem too narrow"
        return layer
    a = layer[:, :, 3]
    old = hem_bottom(a, x0, x1).astype(np.float64)
    ok = (old >= 0) & (np.abs(old - hl[1]) <= HEM_SMOOTH_NEAR)  # torso-hem columns only (not sleeve-level bottoms)
    if ok.sum() < 10:
        report["skipped"] = "no hem edge"
        return layer
    xs = np.arange(x0, x1 + 1)
    i0, i1 = np.nonzero(ok)[0][[0, -1]]
    filled = np.interp(xs, xs[ok], old[ok])
    sm = filled.copy()
    sm[i0:i1 + 1] = _gauss1d(filled[i0:i1 + 1], HEM_SMOOTH_WAVE * (xs[i1] - xs[i0]) / 3.0)
    band = HEM_SMOOTH_BAND * (hr[1] - _f(blm["shoulder"]["y"]))
    new = old.copy()
    raised = lowered = 0
    for i, x in enumerate(xs):
        if not ok[i]:
            continue
        target = int(round(sm[i]))
        if target > old[i]:
            new[i] = min(target, old[i] + band)
            lowered += 1
        elif target < old[i]:
            col = mask[target + 1:int(old[i]) + 1, x]
            fig = np.nonzero(col)[0]
            new[i] = old[i] if len(fig) == len(col) else (target + 1 + fig.max() if len(fig) else target)
            new[i] = max(new[i], target)
            raised += int(new[i] < old[i])
    out = _hem_column_remap(layer, xs, ok, old, new, band, mask, report)
    report.update({"columns": int(ok.sum()), "lowered": lowered, "raised": raised,
                   "max_move_px": round(float(np.max(np.abs(new[ok] - old[ok]))), 1)})
    return out


def _hem_column_remap(layer, xs, ok, old, new, band, mask=None, report=None):
    """Vertical remap per column x in xs (where ok and new != old): rows old - band .. new take rows
    old - band .. old (linear), rows below new become transparent. Alpha < HARD_EDGE -> 0 afterwards.
    mask (round 12b): a figure px covered (alpha >= 128) before and not after keeps its old px (the slanted side
    edges near the hem corners and the interpolated bottom row); report["restored_px"]."""
    H, W = layer.shape[:2]
    mxm = np.tile(np.arange(W, dtype=np.float32), (H, 1))
    mym = np.tile(np.arange(H, dtype=np.float32)[:, None], (1, W))
    for i, x in enumerate(xs):
        if not ok[i] or new[i] == old[i]:
            continue
        b0 = old[i] - band
        ys = np.arange(int(np.floor(b0)), H)
        ys = ys[ys >= 0]
        src = np.where(ys <= new[i], b0 + (ys - b0) * (old[i] - b0) / max(new[i] - b0, 1e-6), -1.0)
        mym[ys, x] = src.astype(np.float32)
    out = cv2.remap(layer, mxm, mym, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    out[:, :, 3][out[:, :, 3] < HARD_EDGE] = 0
    if mask is not None:
        back = mask & (layer[:, :, 3] >= 128) & (out[:, :, 3] < 128)
        out[back] = layer[back]
        if report is not None:
            report["restored_px"] = int(back.sum())
    return out


def _raise_limit(mask, x, target, old):
    """The highest bottom edge in column x between target and old (target < old) that uncovers no figure px."""
    col = mask[target + 1:int(old) + 1, x]
    fig = np.nonzero(col)[0]
    new = old if len(fig) == len(col) else (target + 1 + fig.max() if len(fig) else target)
    return max(new, target)


def garment_hem_offsets(alpha, glm, near=HEM_SMOOTH_NEAR):
    """The garment's own hem curve: (gxs, off) for the garment columns between the hem corners whose bottom edge
    (alpha >= HARD_EDGE) is within `near` px of the hem landmark row; off = bottom - the straight line between the
    first and last such bottoms (garment px). None when fewer than 10 columns."""
    g0, g1 = int(np.ceil(_f(glm["hem"]["left_x"]))), int(np.floor(_f(glm["hem"]["right_x"])))
    gy = _f(glm["hem"]["y"])
    if g1 - g0 < 10:
        return None
    b = hem_bottom(alpha, g0, g1).astype(np.float64)
    gxs = np.arange(g0, g1 + 1)
    ok = (b >= 0) & (np.abs(b - gy) <= near)
    if ok.sum() < 10:
        return None
    gxs, b = gxs[ok], b[ok]
    line = b[0] + (b[-1] - b[0]) * (gxs - gxs[0]) / max(gxs[-1] - gxs[0], 1)
    return gxs.astype(np.float64), b - line


def garment_hem(layer, pairs, glm, g_alpha, s, blm, mask, report):
    """hem_mode="garment" (round 12b, owner 2026-11-15; adapt only): target bottom edge per output column between the
    hem targets = the straight line between the hem_l / hem_r targets + s x the garment's own hem offset
    (`garment_hem_offsets`, garment column mapped linearly from the target span to the garment's curve span). The edge
    moves down to the target, or up only through background px (clamped where a figure px would be uncovered: never
    above the reference edge over the figure). Vertical remap inside a band of max(HEM_SMOOTH_BAND x torso length,
    2 x the largest applied correction) above the old edge. Report: max stretch (band rows new / old), clamped
    columns, warn when the stretch is above HEM_GARMENT_WARN_STRETCH."""
    H, W = mask.shape
    hl, hr = pairs["hem_l"][1], pairs["hem_r"][1]
    x0, x1 = max(int(np.floor(hl[0])), 0), min(int(np.ceil(hr[0])), W - 1)
    curve = garment_hem_offsets(g_alpha, glm)
    if x1 - x0 < 10 or curve is None:
        report["skipped"] = "hem too narrow or no garment hem edge"
        return layer
    gxs, goff = curve
    a = layer[:, :, 3]
    old = hem_bottom(a, x0, x1).astype(np.float64)
    ok = (old >= 0) & (np.abs(old - hl[1]) <= HEM_SMOOTH_NEAR)
    if ok.sum() < 10:
        report["skipped"] = "no hem edge"
        return layer
    xs = np.arange(x0, x1 + 1)
    u = (xs - hl[0]) / max(hr[0] - hl[0], 1e-6)
    tgt = hl[1] + u * (hr[1] - hl[1]) + s * np.interp(gxs[0] + u * (gxs[-1] - gxs[0]), gxs, goff)
    new = old.copy()
    clamped = 0
    for i, x in enumerate(xs):
        if not ok[i]:
            continue
        t = int(round(tgt[i]))
        if t > old[i]:
            new[i] = t
        elif t < old[i]:
            new[i] = _raise_limit(mask, x, t, old[i])
            clamped += int(new[i] > t)
    corr = np.abs(new[ok] - old[ok])
    band = max(HEM_SMOOTH_BAND * (hr[1] - _f(blm["shoulder"]["y"])), 2.0 * float(corr.max()))
    stretch = float(np.max((new[ok] - (old[ok] - band)) / band))
    out = _hem_column_remap(layer, xs, ok, old, new, band, mask, report)
    report.update({"columns": int(ok.sum()), "lowered": int((new[ok] > old[ok]).sum()),
                   "raised": int((new[ok] < old[ok]).sum()), "clamped": clamped,
                   "max_move_px": round(float(corr.max()), 1), "band_px": round(band, 1),
                   "max_stretch": round(stretch, 3), "stretch_warn": stretch > HEM_GARMENT_WARN_STRETCH,
                   "garment_offset_px": [round(float(goff.min()), 1), round(float(goff.max()), 1)]})
    return out


def tshirt_layer(garment_img, glm, body_lm, mask, fit_mode="adapt", H=1200, W=600, hem_rule=(0.35, 10.0), *,
                 sleeve_variant="r7", debug_map=False, side_floor=False, neckline_variant="r7", source="body",
                 base=None, neck_clip=False, neck_hole_polygon=None, collar_floor_on=True, shoulder_variant="off",
                 shoulder_fractions=SHOULDER_LINE_FRACTIONS, shoulder_ease=SHOULDER_LINE_EASE,
                 shoulder_edge_alpha=128, sleeve_mode="mls", side_floor_mode="landmarks", hem_mode="off",
                 tube_arm="r11", hem_c_pair=False, armpit_mode="off", cuff_mode="chord", tube_fringe="keep",
                 keep_scale="shoulder", tube_clip="armhole", keep_neck=False):
    """(BGRA layer HxW, info {engine, pairs, rejected, s, neck_opening?, sleeve_hems, runtime, map?}).
    keep_scale (keep_shape only, docs/09 #112): "shoulder" = the scale before #112 | "fit" = keep_shape_scale.
    keep_neck (keep_shape only, docs/09 #121; render_tryon always passes True, the default here is the old output
    the regression fixtures pin): every target moves down by keep_neck_dy (the collar line on the row regular
    T-shirts use) and the shoulder targets are bound to the body's shoulder row (keep_neck_pairs), before the warp;
    the back-collar opening moves with them; info["keep_neck_dy"]. A no-op for adapt.
    Raises MlsUnavailable (missing landmarks, failed core pairs, bad geometry): the caller uses the parts engine.
    sleeve_variant: benchmark only (module docstring); debug_map: info["map"] = (mx, my) for the fold metric."""
    if sleeve_variant not in SLEEVE_VARIANTS:  # a programming error, never a silent fallback to parts
        raise ValueError(f"unknown sleeve variant: {sleeve_variant!r}")
    if tube_clip not in TUBE_CLIPS:
        raise ValueError(f"unknown tube clip: {tube_clip!r}")
    if keep_scale not in KEEP_SCALES:
        raise ValueError(f"unknown keep_shape scale: {keep_scale!r}")
    if neckline_variant not in NECKLINE_VARIANTS:
        raise ValueError(f"unknown neckline variant: {neckline_variant!r}")
    if shoulder_variant not in SHOULDER_VARIANTS:
        raise ValueError(f"unknown shoulder variant: {shoulder_variant!r}")
    if sleeve_mode not in SLEEVE_MODES:
        raise ValueError(f"unknown sleeve mode: {sleeve_mode!r}")
    if side_floor_mode not in SIDE_FLOOR_MODES:
        raise ValueError(f"unknown side floor mode: {side_floor_mode!r}")
    if hem_mode not in HEM_MODES:
        raise ValueError(f"unknown hem mode: {hem_mode!r}")
    if tube_arm not in TUBE_ARMS:
        raise ValueError(f"unknown tube arm: {tube_arm!r}")
    if armpit_mode not in ARMPIT_MODES:
        raise ValueError(f"unknown armpit mode: {armpit_mode!r}")
    if cuff_mode not in CUFF_MODES:
        raise ValueError(f"unknown cuff mode: {cuff_mode!r}")
    if tube_fringe not in TUBE_FRINGES:
        raise ValueError(f"unknown tube fringe: {tube_fringe!r}")
    if fit_mode == "keep_shape":  # armpit modes: adapt only (rounds 13c / 14 benchmark), a no-op in keep_shape
        armpit_mode = "off"
    if fit_mode == "keep_shape":  # hem smoothing / garment hem / hem_c pair: adapt only (rounds 12, 12b)
        hem_mode = "off"
        hem_c_pair = False
    if fit_mode == "keep_shape":  # tube sleeves: adapt only (round 11 benchmark), a no-op in keep_shape
        sleeve_mode = "mls"
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
                                            sleeve_variant=sleeve_variant, side_floor=side_floor,
                                            keep_scale=keep_scale)
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
        raise MlsUnavailable(f"control points: {e!r}") from e
    lost = [n for n in CORE_PAIRS if n not in pairs]
    if lost:
        raise MlsUnavailable(f"pair validation failed: {', '.join(lost)}")
    hem_c_rep = _add_hem_c_pair(pairs, glm, img[:, :, 3]) if hem_c_pair else None
    sline = shoulder_line(pairs, glm, body_lm, mask, img[:, :, 3], shoulder_fractions, shoulder_ease,
                          shoulder_edge_alpha) if shoulder_variant == "line" else None
    raised = collar_floor(pairs, body_lm, mask) if collar_floor_on else None
    neck_dy = keep_neck_dy(pairs, body_lm) if keep_neck and not fitted else None
    if neck_dy:  # docs/09 #121
        keep_neck_pairs(pairs, body_lm, neck_dy)
    mx, my = _inverse_maps(pairs, s, H, W)
    sfm_report = ap_report = ap_base = None
    if side_floor:  # second stage: pairs where the first solve left the garment edge, x floored; solve again
        before = set(pairs)
        _add_side_floor_pairs(pairs, glm, body_lm, mask, img[:, :, 3] > 128, mx, my, rejected)
        ref_pairs = dict(pairs)
        if side_floor_mode == "mask":
            sfm_report = {}
            _add_side_floor_mask_pairs(pairs, body_lm, mask, img, mx, my, rejected, sfm_report)
        mx0, my0 = mx, my
        if set(pairs) != before:  # only when the floor added a pair: otherwise the first solve stands as it is
            mx, my = _inverse_maps(pairs, s, H, W)
        if side_floor_mode == "mask" and set(pairs) != set(ref_pairs):  # round 12b: no new holes vs the landmark floor
            ref_map = _inverse_maps(ref_pairs, s, H, W) if set(ref_pairs) != before else (mx0, my0)
            nh = None
            if neckline_variant.startswith("hole") and neck_hole_polygon is not None and len(neck_hole_polygon) >= 3:
                nh = np.zeros(img.shape[:2], np.uint8)
                cv2.fillPoly(nh, [np.round(np.asarray(neck_hole_polygon, float) * 8).astype(np.int32)], 1, shift=3)
                nh = nh.astype(np.float32)
            mx, my = _blend_new_holes(H, W, img[:, :, 3], mask, ref_map, mx, my, sfm_report, hole=nh)
        if armpit_mode == "r14":  # round 14: a second solve with the armpit pairs, used only around the armpits
            ap_report = {"s": s}
            ap_pairs = dict(pairs)
            _add_armpit_pairs(ap_pairs, glm, body_lm, mask, img, mx0, my0, rejected, ap_report,
                              tube=sleeve_mode != "mls")
            ap_report.pop("s")
            win = ap_report.pop("window")
            if win is not None:
                ap_base = (mx, my, win)  # for the local guard at the end
                ax, ay = _inverse_maps(ap_pairs, s, H, W)
                mx = ((1 - win) * mx + win * ax).astype(np.float32)
                my = ((1 - win) * my + win * ay).astype(np.float32)
    tube_maps = (np.full((H, W), -1.0, np.float32), np.full((H, W), -1.0, np.float32)) if sleeve_mode != "mls" else None
    tube = tube_sleeves(img, glm, body_lm, mask, pairs, s, mx, my, mode=sleeve_mode, tube_maps=tube_maps,
                        arm=tube_arm, armpit_mode=armpit_mode, cuff=cuff_mode, clip=tube_clip) \
        if sleeve_mode != "mls" else None
    f = img.astype(np.float32)
    f[:, :, :3] *= f[:, :, 3:4] / 255.0
    out = cv2.remap(f, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    if tube_maps is not None:  # the tube layer OVER the MLS layer (premultiplied "over")
        tl = cv2.remap(f, *tube_maps, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        # round 16: the tube's fringe px (source within HALO_ERODE body px of the garment's alpha edge: the photo's
        # light edge) that lie over solid MLS fabric draw a faint line along the sleeve's inner edge (#28). They are
        # counted always and, with tube_fringe="drop", not drawn: the MLS fabric below stays. Never a new hole.
        rg = max(1, int(np.ceil(prod.HALO_ERODE / max(s, 1e-6))))
        core = cv2.erode((img[:, :, 3] >= 250).astype(np.uint8),
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * rg + 1, 2 * rg + 1)),
                         borderType=cv2.BORDER_CONSTANT, borderValue=0)
        core_t = cv2.remap(core, *tube_maps, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0) > 0
        fringe = (tl[:, :, 3] > 0) & ~core_t & (out[:, :, 3] >= 250)
        if fringe.any():
            over = tl[fringe] + out[fringe] * (1 - tl[fringe][:, 3:4] / 255.0)
            dg = np.abs(over[:, :3].mean(1) / np.maximum(over[:, 3], 1e-6)
                        - out[fringe][:, :3].mean(1) / np.maximum(out[fringe][:, 3], 1e-6)) * 255.0
            tube["fringe_visible_px"] = int((dg > TUBE_FRINGE_VISIBLE).sum())
            tube["fringe_max_grey"] = round(float(dg.max()), 1)
        else:
            tube["fringe_visible_px"], tube["fringe_max_grey"] = 0, 0.0
        tube["fringe_px"] = int(fringe.sum())
        tube["fringe_zone"] = fringe
        tube["fringe_mode"] = tube_fringe
        if tube_fringe == "drop":
            tl[fringe] = 0
            tube_maps[0][fringe] = -1
            tube_maps[1][fringe] = -1
        out = tl + out * (1 - tl[:, :, 3:4] / 255.0)
        drawn = tube_maps[0] >= 0
        mx = np.where(drawn, tube_maps[0], mx)  # the map the tube px come from (fold metric, info["map"])
        my = np.where(drawn, tube_maps[1], my)
    a = out[:, :, 3:4] / 255.0
    out[:, :, :3] = np.where(a > 0, out[:, :, :3] / np.maximum(a, 1e-6), 0)
    layer = np.clip(np.rint(out), 0, 255).astype(np.uint8)
    cut = np.zeros((H, W), bool)  # round 13b: the rule (b) cut edge is not a photo fringe, remove_halo skips it
    for side in ("left", "right"):
        z = (tube or {}).get(side, {}).get("cut_b")
        if z is not None:
            cut |= z & (layer[:, :, 3] == 0)
    if cut.any():
        tmp = layer.copy()
        tmp[:, :, 3][cut] = 255  # the cut px count as fabric during the erosion, then go back to transparent
        prod._colour_from_nearest_opaque(tmp, cut, ok=layer[:, :, 3] >= 250)
        layer = prod.remove_halo(tmp, outer_only=True)
        layer[cut] = 0
    else:
        layer = prod.remove_halo(layer, outer_only=True)  # edge fix, once, outer contour
    if fitted:
        alpha = layer[:, :, 3]
        alpha[alpha < HARD_EDGE] = 0
    if hem_mode == "smooth":
        hem_rep = {}
        layer = smooth_hem(layer, pairs, body_lm, mask, hem_rep)
    elif hem_mode == "garment":
        hem_rep = {}
        layer = garment_hem(layer, pairs, glm, img[:, :, 3], s, body_lm, mask, hem_rep)
    info = {"engine": "mls", "fit_mode": fit_mode, "pairs": pairs, "rejected": rejected, "s": s}
    if hem_mode == "smooth":
        info["hem_smooth"] = hem_rep
    elif hem_mode == "garment":
        info["hem_garment"] = hem_rep
    if hem_c_rep is not None:
        info["hem_c"] = hem_c_rep
    if raised is not None:
        info["collar_floor"] = raised
    if tube is not None:
        info["tube"] = tube
    if sfm_report is not None:
        info["side_floor_mask"] = sfm_report
    if ap_report is not None:
        info["armpit"] = ap_report
    if sline is not None:
        info["shoulder_line"] = sline
    if debug_map:
        info["map"] = (mx, my)
    geo = prod.back_collar_geometry(img[:, :, 3] > 128, glm, img)
    if geo:
        g_cx = (_f(glm["shoulder"]["left_x"]) + _f(glm["shoulder"]["right_x"])) / 2
        a_cx = (_f(body_lm["shoulder"]["left_x"]) + _f(body_lm["shoulder"]["right_x"])) / 2
        g_sy, a_sy = _f(glm["shoulder"]["y"]), _f(body_lm["shoulder"]["y"])
        if keep_scale == "fit" and not fitted:
            a_sy += keep_shape_drop(glm, body_lm, s)
        a_sy += neck_dy or 0  # docs/09 #121: the opening moves down with the garment
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
        sh = np.array([_f(body_lm["shoulder"][f"{side}_x"]), _f(body_lm["shoulder"]["y"])])
        if tube is not None and "cuff" in tube.get(side, {}):  # the tube's own cuff segment
            a_, b_ = tube[side]["cuff"]
            hems[side] = (np.float32(a_), np.float32(b_), sh)
        elif "cuff_out" + sx in pairs and "cuff_in" + sx in pairs:
            hems[side] = (np.float32(pairs["cuff_out" + sx][1]), np.float32(pairs["cuff_in" + sx][1]), sh)
    info["sleeve_hems"] = hems
    if tube is not None and tube_arm == "finished":  # round 13b: rule #63 on the final contour, sleeve zone only
        layer, tube["filled_px"] = _fill_sleeve_holes(layer, pairs, body_lm)
    if ap_base is not None:  # round 14: inside the window no figure px the map without the armpit pairs covers is lost
        bx_, by_, win = ap_base  # (arm skin below the cuff line is never put back)
        bl = cv2.remap(f, bx_, by_, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        ke = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * prod.HALO_ERODE + 1,) * 2)  # as remove_halo; tried
        # without the erosion (2026-11-15): 0 new holes, but it pastes the 1-2 px photo fringe (fragments, spikes)
        solid_b = cv2.erode(bl[:, :, 3], ke, borderType=cv2.BORDER_CONSTANT, borderValue=0) >= HARD_EDGE
        Yq, Xq = np.mgrid[0:H, 0:W]
        skin, sleeve_arm = np.zeros((H, W), bool), np.zeros((H, W), bool)
        for side in ("left", "right"):
            rows_, crease_ = arm_torso_boundary(mask, body_lm, side)
            if not rows_ or side not in hems:
                continue
            ex_ = np.full((H, 1), np.nan, np.float32)
            for y_, e_ in rows_.items():
                ex_[y_, 0] = e_
            a_, b_, sh_ = (np.asarray(v, float) for v in hems[side])
            n_ = _unit(np.array([-(b_ - a_)[1], (b_ - a_)[0]]))
            n_ = -n_ if (sh_ - a_) @ n_ > 0 else n_
            arm_ = ~np.isnan(ex_) & ((Xq < ex_) if side == "left" else (Xq >= ex_))
            below_ = ((Xq - a_[0]) * n_[0] + (Yq - a_[1]) * n_[1]) > 0
            skin |= arm_ & below_
            sleeve_arm |= arm_ & ~below_
        # on the arm above the cuff line the sleeve's thin hem px count too (not eroded there)
        lost = mask & (win > 0.01) & (layer[:, :, 3] < 128) & ((solid_b & ~skin) |
                                                             ((bl[:, :, 3] >= HARD_EDGE) & sleeve_arm))
        if lost.any():
            layer[:, :, :3][lost] = np.clip(np.rint(bl[:, :, :3][lost] / np.maximum(bl[:, :, 3:4][lost], 1e-6) * 255.0),
                                            0, 255).astype(np.uint8)
            layer[:, :, 3][lost] = 255
        ap_report["guard_px"] = int(lost.sum())
        n_c, lab, st, _ = cv2.connectedComponentsWithStats((layer[:, :, 3] >= 128).astype(np.uint8), connectivity=8)
        crumbs = np.isin(lab, [i for i in range(1, n_c) if st[i, cv2.CC_STAT_AREA] <= ARMPIT_CRUMB]) & (win > 0.01)
        layer[crumbs] = 0  # detached garment crumbs inside the window (no ragged fragments)
        ap_report["crumb_px"] = int(crumbs.sum())
    if sfm_report is not None:  # round 12b: the last guard, no figure px the landmark floor layer covers is lost
        ref, _ = tshirt_layer(garment_img, glm, body_lm, mask, fit_mode, H, W, hem_rule, sleeve_variant=sleeve_variant,
                              side_floor=side_floor, neckline_variant=neckline_variant, source=source, base=base,
                              neck_clip=neck_clip, neck_hole_polygon=neck_hole_polygon,
                              collar_floor_on=collar_floor_on, shoulder_variant=shoulder_variant,
                              shoulder_fractions=shoulder_fractions, shoulder_ease=shoulder_ease,
                              shoulder_edge_alpha=shoulder_edge_alpha, sleeve_mode=sleeve_mode,
                              hem_c_pair=hem_c_pair, tube_arm=tube_arm,  # same tube (round 13 fix 4)
                              armpit_mode=armpit_mode, cuff_mode=cuff_mode, tube_fringe=tube_fringe)
        lost = mask & (ref[:, :, 3] >= 128) & (layer[:, :, 3] < 128)
        for side in ("left", "right"):  # the arm px cleared beyond the tube cuff on purpose (tube_arm="fit")
            z = (tube or {}).get(side, {}).get("beyond_cuff_zone")
            if z is not None:
                lost &= ~z
        layer[lost] = ref[lost]
        sfm_report["patched_px"] = int(lost.sum())
    if neck_dy is not None:
        info["keep_neck_dy"] = neck_dy
    info["runtime"] = time.perf_counter() - t0
    return layer, info
