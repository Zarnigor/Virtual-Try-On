"""Try-on warp engine: garments are deformed onto the body by landmarks (scanline strips + affine sleeves).

Entry point: render_tryon(base, body_lm, garments) -> (RGB 600x1200, warnings).
Garment landmarks are pixels of the garment's own tight-cropped PNG; body landmarks are canvas pixels.

Design rules (fixes of the day-1 version, see docs/06):
- Garments keep their own silhouette: one uniform scale for both axes (T-shirt: shoulder line = body + 4 %; pants:
  waist..hem = waist..ankle). Only the shoulder line / waistband is fitted; every other row is max(garment, body +
  ease), capped at 1.8x body (docs/06 "Pants fit", "T-shirt fit"). Lengths and hems are the garment's own.
- No fixed pixel offsets. Sleeves follow the avatar's arm axis, fitted from the figure mask.
- Sleeves are clamped to at most SLEEVE_MAX_ARM of the arm length (warning), never stretched to the hands.
- Hands and forearms are drawn ABOVE the garment: arm pixels from the figure mask beyond the sleeve hem are
  copied back from the base image after compositing.
- Warnings report DISTORTION (horizontal scale / vertical scale of one segment), not plain width change.
"""
import numpy as np
import cv2

DISTORT_LIMIT = 1.4  # h/v scale ratio of one segment beyond which prints look squashed or stretched
SLEEVE_MAX_ARM = 0.5  # short sleeves end at most half way down the arm (shoulder -> fingertips)
SLEEVE_HEM_EXTEND = 1.15  # src sleeve quad is extended a bit so hem trims/lace past sleeve_end are kept
MAX_SHIRT_BELOW_CROTCH = 0.35  # T-shirt hem at most this fraction of crotch->knee below the crotch
FULL_LENGTH_TOLERANCE = 0.05  # pants ending within 5% of figure height (~9 cm) of the ankle break over the shoe
SHADING_STRENGTH = 0.7  # garment RGB *= shade ** strength (0 = off)
SHADING_SIGMA = 25  # px: luminance below this scale is kept as folds/shadow, above it is the avatar's base tone
SHADING_RANGE = (0.75, 1.2)
SHADOW_OPACITY = 0.25  # contact shadow of the garment on the avatar
SHADOW_OFFSET = (2, 3)  # px inward (towards the axis) and down
SHADOW_SIGMA = 4
LOOSE_KNEE_PULL = 0.25  # loose legs: the knee moves the smooth centreline by at most this share of its offset
HANG_LOOSE = 0.5  # loose leg: centreline weight of the body leg (rest: straight drop from the hip)
LOOSE_FROM, LOOSE_FULL = 1.05, 1.15  # garment/body knee width (mean of both legs): smoothstep tight -> loose
WAISTBAND_CURVE = 0.04  # waistband top edge dips by this fraction of the waist width at the centre
OPENING_COLOR_DIST = 40  # a hole whose colour is this close to the photo background is a real opening (kept)
WHITE_THRESHOLD = 235  # base images without transparency: figure = pixels darker than this in any channel


# ---------- helpers ----------

def _over(base: np.ndarray, top: np.ndarray) -> np.ndarray:
    """Straight-alpha 'over' of BGRA float arrays (any leading shape). The colour under alpha 0 never leaks in
    (the old 'rgb*(1-a) + top*a, alpha added' mixed the black of empty pixels into soft edges and overlaps)."""
    ta, ba = top[..., 3:4] / 255.0, base[..., 3:4] / 255.0
    oa = ta + ba * (1 - ta)
    rgb = (top[..., :3] * ta + base[..., :3] * ba * (1 - ta)) / np.maximum(oa, 1e-6)
    return np.concatenate([np.where(oa > 0, rgb, 0), oa * 255], axis=-1)


def _alpha_composite(base: np.ndarray, overlay: np.ndarray) -> np.ndarray:
    out = _over(base.astype(np.float32), overlay.astype(np.float32))
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def _warp_affine_premultiplied(img: np.ndarray, M: np.ndarray, W: int, H: int) -> np.ndarray:
    """Bilinear affine warp of a straight-alpha BGRA image without darkening its edges (the colour under alpha 0
    is black; interpolating straight RGB pulled it into every edge pixel)."""
    f = img.astype(np.float32)
    f[:, :, :3] *= f[:, :, 3:4] / 255.0
    w = cv2.warpAffine(f, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    a = w[:, :, 3:4] / 255.0
    w[:, :, :3] = np.where(a > 0, w[:, :, :3] / np.maximum(a, 1e-6), 0)
    return np.clip(np.rint(w), 0, 255).astype(np.uint8)


def _bgra(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2BGRA) if img.shape[2] == 3 else img


def figure_mask(base: np.ndarray) -> np.ndarray:
    """Bool mask of the person: alpha if the image has transparency, else 'not white' (opaque white photos)."""
    if base.shape[2] == 4 and (base[:, :, 3] < 250).any():
        return base[:, :, 3] > 128
    return (base[:, :, :3] < WHITE_THRESHOLD).any(axis=2)


def _f(v) -> float:
    return float(v)


def body_span(lm: dict, y: float) -> tuple[float, float]:
    """Torso left/right x at row y, linear between the landmark rows (above shoulder: shoulder, below hip: hip)."""
    rows = [(_f(lm[k]["y"]), _f(lm[k]["left_x"]), _f(lm[k]["right_x"])) for k in ("shoulder", "chest", "waist", "hip")]
    if y <= rows[0][0]:
        return rows[0][1], rows[0][2]
    for (y0, l0, r0), (y1, l1, r1) in zip(rows, rows[1:]):
        if y <= y1:
            t = (y - y0) / max(y1 - y0, 1e-6)
            return l0 + t * (l1 - l0), r0 + t * (r1 - r0)
    return rows[-1][1], rows[-1][2]


def _crotch_x(lm: dict) -> float:
    c = lm.get("crotch", {})
    return _f(c["center_x"]) if "center_x" in c else (_f(lm["hip"]["left_x"]) + _f(lm["hip"]["right_x"])) / 2


def _interp_span(rows: list, y: float) -> tuple[float, float]:
    """Left/right x at y, linear between (y, lx, rx) rows sorted by y (clamped at the ends)."""
    if y <= rows[0][0]:
        return rows[0][1], rows[0][2]
    for (y0, l0, r0), (y1, l1, r1) in zip(rows, rows[1:]):
        if y <= y1:
            t = (y - y0) / max(y1 - y0, 1e-6)
            return l0 + t * (l1 - l0), r0 + t * (r1 - r0)
    return rows[-1][1], rows[-1][2]


def _warp_rows(src: np.ndarray, src_rows: list, dst_rows: list, H: int, W: int, pad: float = 1.0) -> np.ndarray:
    """One clipped layer: every dst row maps linearly onto a src row span. Rows are (y, lx, rx) with y a pixel row
    and lx/rx pixel EDGES (a run of pixels a..b is the span a..b+1); between consecutive rows everything is
    interpolated. Sampling is bilinear on premultiplied colour (cv2.remap), so widths and positions are sub-pixel
    and the silhouette edge is antialiased; nothing is drawn outside the dst rows or the dst span (+ `pad` src px,
    which only lets the garment's own soft edge through)."""
    out = np.zeros((H, W, 4), np.uint8)
    if len(src_rows) < 2:
        return out
    order = np.argsort([r[0] for r in dst_rows], kind="stable")
    d = np.array([dst_rows[i] for i in order], np.float64)
    g = np.array([src_rows[i] for i in order], np.float64)
    keep = np.concatenate([[True], np.diff(d[:, 0]) > 1e-6])
    d, g = d[keep], g[keep]
    y0, y1 = max(int(np.ceil(d[0, 0] - 1e-6)), 0), min(int(np.floor(d[-1, 0] + 1e-6)), H - 1)
    if y1 < y0 or len(d) < 2:
        return out
    ys = np.arange(y0, y1 + 1, dtype=np.float64)
    l, r = np.interp(ys, d[:, 0], d[:, 1]), np.interp(ys, d[:, 0], d[:, 2])
    sy = np.interp(ys, d[:, 0], g[:, 0])
    sl, sr = np.interp(ys, d[:, 0], g[:, 1]), np.interp(ys, d[:, 0], g[:, 2])
    scale = (sr - sl) / np.maximum(r - l, 1e-6)  # src px per dst px
    xs = np.arange(W, dtype=np.float64) + 0.5
    edge = sl[:, None] + (xs[None, :] - l[:, None]) * scale[:, None]  # src position in edge coordinates
    inside = (edge >= sl[:, None] - pad) & (edge <= sr[:, None] + pad) & (sr > sl)[:, None]
    map_x = np.where(inside, edge - 0.5, -10.0).astype(np.float32)
    map_y = np.repeat(sy[:, None], W, axis=1).astype(np.float32)
    f = src.astype(np.float32)
    f[:, :, :3] *= f[:, :, 3:4] / 255.0
    w = cv2.remap(f, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    a = w[:, :, 3:4] / 255.0
    w[:, :, :3] = np.where(a > 0, w[:, :, :3] / np.maximum(a, 1e-6), 0)
    out[y0:y1 + 1] = np.clip(np.rint(w), 0, 255).astype(np.uint8)
    return out


def _tail_rows(alpha: np.ndarray, src_rows: list, dst_rows: list, s: float) -> None:
    """In place: continue the last row down to the garment's own bottom edge (trims below the hem landmark and the
    soft edge itself), same span and scale; at most 8 % of the garment height."""
    sy, sl, sr = src_rows[-1]
    x0, x1 = max(int(sl), 0), max(int(np.ceil(sr)), int(sl) + 1)
    rows = np.nonzero(alpha[int(sy):, x0:x1].any(axis=1))[0]
    if not len(rows):
        return
    extra = min(float(rows[-1]) + 1.5 - (sy - int(sy)), 0.08 * alpha.shape[0])
    if extra > 0.5:
        y, l, r = dst_rows[-1]
        src_rows.append((sy + extra, sl, sr))
        dst_rows.append((y + extra * s, l, r))


# ---------- arms (from the figure mask) ----------

def _runs(row: np.ndarray) -> list[tuple[int, int]]:
    d = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
    return [(int(s), int(e) - 1) for s, e in zip(np.where(d == 1)[0], np.where(d == -1)[0]) if e - s >= 2]


def outer_edge_line(mask: np.ndarray, side: str, y0: float, y1: float):
    """Fit x = a*y + b to the figure's outer silhouette edge on one side between rows y0..y1.

    Above the armpit the outermost run is the whole body (its edge is the deltoid); below it, the arm.
    Returns (a, b) or None if there are too few rows.
    """
    pts = []
    for y in range(max(0, int(y0)), min(mask.shape[0] - 1, int(y1))):
        runs = _runs(mask[y])
        if runs:
            pts.append((y, runs[0][0] if side == "left" else runs[-1][1]))
    if len(pts) < 10:
        return None
    ys, xs = np.array(pts, np.float64).T
    a, b = np.polyfit(ys, xs, 1)
    return float(a), float(b)


def find_arms(mask: np.ndarray, lm: dict) -> dict:
    """Per side: {"rows": [(y, l, r)], "slope": dx/dy of the arm axis, "end_y"} or None if not separated.

    Below the armpit an arm is the outermost run on its side of the body axis that does not contain the axis,
    when that side has more than one run (torso or leg + arm). Tracking stops when the arm disappears.
    """
    H = mask.shape[0]
    axis = _crotch_x(lm)
    start = int(_f(lm["armpit"]["y"])) + 2
    stop = min(H - 1, int(_f(lm["knee"]["y"])))
    arms = {}
    for side in ("left", "right"):
        rows, last_c, gap = [], None, 0
        for y in range(start, stop):
            runs = [q for q in _runs(mask[y]) if not (q[0] <= axis <= q[1])]
            mine = [q for q in runs if (q[1] < axis if side == "left" else q[0] > axis)]
            torso_present = any(q[0] <= axis <= q[1] for q in _runs(mask[y]))
            if len(mine) + (1 if torso_present else 0) < 2:
                gap += 1
            else:
                q = min(mine, key=lambda q: q[0]) if side == "left" else max(mine, key=lambda q: q[1])
                c = (q[0] + q[1]) / 2
                if last_c is not None and abs(c - last_c) > 25:  # jumped to another part (a leg): stop
                    break
                rows.append((y, q[0], q[1]))
                last_c, gap = c, 0
            if rows and gap > 6:
                break
        if len(rows) < 15:
            arms[side] = None
            continue
        ys = np.array([r[0] for r in rows], np.float64)
        cs = np.array([(r[1] + r[2]) / 2 for r in rows], np.float64)
        slope = float(np.polyfit(ys, cs, 1)[0])
        arms[side] = {"rows": rows, "slope": slope, "end_y": rows[-1][0], "end_x": float(cs[-1])}
    return arms


def _garment_span(alpha: np.ndarray, sy: float, fallback: tuple, side: str | None = None, axis: float = 0.0):
    """The garment's OWN span in source row sy, from its silhouette (bulges, balloon panels and gathered cuffs
    are kept; landmark interpolation made every leg a straight panel). side: one leg (split at the crotch axis);
    None: the runs overlapping the landmark span, to their own ends. Falls back to the landmark span."""
    y = min(max(int(round(sy)), 0), alpha.shape[0] - 1)
    near = (fallback[0] + fallback[1]) / 2
    if side is None:  # whole piece: the runs that overlap the landmark span, to their own ends (bulges kept;
        # a leg gap stays inside; a separate run beside it, e.g. a hanging sleeve, is not the torso)
        runs = [q for q in _runs(alpha[y]) if q[1] >= fallback[0] and q[0] <= fallback[1]]
        run = (min(q[0] for q in runs), max(q[1] for q in runs)) if runs else None
    else:
        run = _leg_run(alpha, y, side, axis, near)
    if run is None or run[1] - run[0] < 0.3 * (fallback[1] - fallback[0]):
        return fallback
    return float(run[0]), float(run[1]) + 1.0


def _leg_run(mask: np.ndarray, y: int, side: str, axis: float, near: float):
    """The leg's run in row y on one side of the axis (a run across the axis is split there), or None."""
    best = None
    for l, r in _runs(mask[min(max(y, 0), mask.shape[0] - 1)]):
        if l <= axis <= r:
            l, r = (l, int(axis)) if side == "left" else (int(axis), r)
        elif (r < axis) != (side == "left"):
            continue
        if best is None or abs((l + r) / 2 - near) < abs((best[0] + best[1]) / 2 - near):
            best = (l, r)
    return best


# ---------- garments ----------

TSHIRT_EASE = 0.04  # shoulder line and every torso row: body + 4 %
NECK_MARGIN = 6  # px each side of the neck landmark width that the head/neck overlay covers
NECK_FEATHER = 1.5  # px sigma of the head/neck overlay edge (~3 px ramp)
NECK_ARC = 0.25  # the overlay's lower edge dips by this x neck width at the centre (crew collar arc)
NECK_RISE = 0.3  # ... and rises by this x neck width above the neck row at the sides (U shape)
CAP_FEATHER = 1.0  # px sigma of the shoulder-cap fill edge (~2 px)
HEM_OVER_WAISTBAND = 6  # px the T-shirt hem reaches past the pants waistband top when it is snapped
HEM_GAP_MAX = 12  # only a hem at most this far above the pants waist is snapped (crop tops stay as they are)
SHOULDER_MAX_CHEST = 1.35  # garment shoulder span beyond this x chest span = marked on the sleeves, not the armholes
SHOULDER_OVER_CHEST = 0.12  # estimated armhole top: this x chest span outward of the armpit
SLEEVE_MERGED_TOL = 0.06  # x chest span: a run reaching further past the torso's side line is torso + sleeve
SLEEVE_OVERLAP = 3  # src px the rigid sleeve reaches past its armhole line over the torso (no seam gap)
CAP_MAX_DEPTH = 0.03  # shoulder cap: at most this fraction of the figure height below the collar top
HALO_ERODE = 2  # px removed from the garment's alpha edge (photo background fringe)
PRESCALE_BELOW = 0.8  # garments that would be shrunk more than this are area-resampled to their final size first
ROW_STEP = 3  # dst px between control rows of the row warp


def tshirt_looseness(ratios) -> float:
    """Once per garment: smoothstep of the mean garment/body width ratio over LOOSE_FROM..LOOSE_FULL (0 tight,
    1 loose); both sides use it, so a symmetric garment gives a symmetric result."""
    return _smooth((sum(ratios) / len(ratios) - LOOSE_FROM) / (LOOSE_FULL - LOOSE_FROM))


def tshirt_row_width(garment_w: float, body_w: float, t_shoulder: float) -> float:
    """Torso row width: at the shoulder line (t=0) the body + ease; from there (smoothstep) the garment's own scaled
    width, never narrower than the body + ease, capped at PANTS_MAX_BODY x body (same rule as pants)."""
    return waist_blend_width(garment_w, body_w, t_shoulder, TSHIRT_EASE)


def _alpha_span(alpha: np.ndarray, y: float, lo: float, hi: float):
    row = alpha[min(max(int(round(y)), 0), alpha.shape[0] - 1), max(int(lo), 0):int(hi) + 1]
    xs = np.nonzero(row)[0]
    return (xs[0] + max(int(lo), 0), xs[-1] + max(int(lo), 0)) if len(xs) else None


def sleeve_regions(alpha: np.ndarray, g: dict, side: str, g_rows: list) -> tuple[np.ndarray, np.ndarray]:
    """(own, draw) bool masks of one sleeve in the garment image. `own`: everything outward of the armhole line
    (shoulder point -> armpit/chest point) down to the armpit row, plus, below it, what lies outside the torso's
    own run (a sleeve hanging lower than the armpit). The torso is everything else, so each garment pixel belongs
    to exactly one piece. `draw` = own + SLEEVE_OVERLAP px past the armhole line: what the rigid sleeve paints."""
    gh, gw = alpha.shape
    yy, xx = np.mgrid[0:gh, 0:gw]
    S = np.array([_f(g["shoulder"][f"{side}_x"]), _f(g["shoulder"]["y"])])
    A = np.array([_f(g["chest"][f"{side}_x"]), _f(g["chest"]["y"])])
    t = A - S
    n = np.array([t[1], -t[0]]) / max(float(np.linalg.norm(t)), 1e-6)
    if (n[0] > 0) == (side == "left"):
        n = -n  # outward: away from the garment's centre
    dist = (xx - S[0]) * n[0] + (yy - S[1]) * n[1]
    above = (dist > 0) & (yy <= A[1])
    beside = np.zeros((gh, gw), bool)  # below the armpit row: clear of the torso's own run (and its soft edge)
    # Below the armpit row the sleeve may still be joined to the torso (no background gap): those rows reach
    # further out than the torso's own side (median run edge from the waist row down) by more than the tolerance.
    # They are split along a straight line from the armpit point to the torso edge of the first free row.
    tol = SLEEVE_MERGED_TOL * (_f(g["chest"]["right_x"]) - _f(g["chest"]["left_x"]))
    y0 = int(A[1]) + 1
    edges = []
    for y in range(y0, gh):
        l, r = _garment_span(alpha, y, _interp_span(g_rows, y))
        edges.append(l if side == "left" else r)
    edges = np.array(edges, np.float64)
    out = -1.0 if side == "left" else 1.0
    lower = edges[max(int(_f(g["waist"]["y"])) - y0, 0):max(int(_f(g["hem"]["y"])) - y0, 1)]
    ref = float(np.median(lower)) if len(lower) else float(A[0])
    free = np.nonzero((edges - ref) * out <= tol)[0]
    n_merged = int(free[0]) if len(free) else len(edges)
    end_x = float(edges[n_merged]) if n_merged < len(edges) else ref
    for i, y in enumerate(range(y0, gh)):
        e = A[0] + (i + 1) / (n_merged + 1) * (end_x - A[0]) if i < n_merged else edges[i] + 2 * out
        if side == "left":
            beside[y, :max(int(e), 0)] = True
        else:
            beside[y, min(int(np.ceil(e)), gw):] = True
    # only what is connected to the sleeve above the armpit row (never the torso's faint edge further down)
    n_lab, lab = cv2.connectedComponents(((above | beside) & alpha).astype(np.uint8), connectivity=8)
    seeds = np.unique(lab[above & alpha])
    hanging = np.isin(lab, seeds[seeds > 0]) & beside
    hanging = (cv2.dilate(hanging.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0) & beside
    own = above | hanging
    draw = own | ((dist > -SLEEVE_OVERLAP) & (yy <= A[1] + SLEEVE_OVERLAP))
    return own, draw


def normalize_tshirt_landmarks(g: dict, alpha: np.ndarray) -> tuple[dict, bool]:
    """(landmarks, changed). The `shoulder` points must be the armhole tops (where the sleeve starts). When they
    were marked on the sleeves instead (shoulder span > SHOULDER_MAX_CHEST x chest span, e.g. at the sleeve tips),
    the uniform scale shrinks the whole garment and the armhole line cuts each sleeve in two. Then the shoulder
    points are estimated: SHOULDER_OVER_CHEST of the chest span outward of each armpit, on the garment's top
    outline. Correctly marked garments are returned unchanged."""
    sh, ch = g["shoulder"], g["chest"]
    chest_w = _f(ch["right_x"]) - _f(ch["left_x"])
    if chest_w <= 0 or (_f(sh["right_x"]) - _f(sh["left_x"])) <= SHOULDER_MAX_CHEST * chest_w:
        return g, False
    xl = _f(ch["left_x"]) - SHOULDER_OVER_CHEST * chest_w
    xr = _f(ch["right_x"]) + SHOULDER_OVER_CHEST * chest_w
    tops = []
    for x in (xl, xr):
        col = np.nonzero(alpha[:, min(max(int(round(x)), 0), alpha.shape[1] - 1)])[0]
        tops.append(float(col[0]) if len(col) else _f(sh["y"]))
    y = min(max(tops), _f(ch["y"]) - 2.0)
    return {**g, "shoulder": {**sh, "left_x": xl, "right_x": xr, "y": y}}, True


def warp_tshirt(body_lm: dict, garment_lm: dict, garment_img: np.ndarray, H: int, W: int,
                arms: dict | None = None, info: dict | None = None,
                mask: np.ndarray | None = None, hem_over: float | None = None) -> tuple[np.ndarray, list]:
    """T-shirt keeps its own silhouette (docs/06 "T-shirt fit"): one uniform scale s for both axes, set so the
    garment's shoulder line = body shoulder + ease; below the shoulders every row is max(garment, body + ease)
    (capped), blended in from the shoulder fit by the chest row; the hem is the garment's own (scaled) length.

    Three clipped pieces, each garment pixel in exactly one (docs/06 "Layer order"): the TORSO (row warp of the
    garment without its sleeve regions) and two rigid SLEEVES (uniform s + rotation onto the upper arm, drawn once,
    SLEEVE_OVERLAP px over the torso). hem_over: a row the hem must reach when it ends at most HEM_GAP_MAX px
    above it (the pants top): the rows below the chest are stretched by those few px, nothing is repeated."""
    warnings: list[str] = []
    g, a = garment_lm, body_lm
    img = _bgra(garment_img)
    gh, gw = img.shape[:2]
    alpha = img[:, :, 3] > 128
    g, estimated = normalize_tshirt_landmarks(g, alpha)
    if estimated:
        warnings.append("shoulder landmarks are on the sleeves: armhole tops estimated from the chest")

    g_sl, g_sr = _f(g["shoulder"]["left_x"]), _f(g["shoulder"]["right_x"])
    a_sl, a_sr = _f(a["shoulder"]["left_x"]), _f(a["shoulder"]["right_x"])
    s = tshirt_scale(g, a)  # uniform: widths AND lengths
    g_cx, a_cx = (g_sl + g_sr) / 2, (a_sl + a_sr) / 2
    g_sy, a_sy = _f(g["shoulder"]["y"]), _f(a["shoulder"]["y"])
    to_dst = lambda gy: a_sy + (gy - g_sy) * s  # noqa: E731
    g_rows = [(_f(g[k]["y"]), _f(g[k]["left_x"]), _f(g[k]["right_x"])) for k in ("shoulder", "chest", "waist", "hem")]

    g_hem = min(_f(g["hem"]["y"]), gh - 1.0)
    hem_y = to_dst(g_hem)  # the garment's own length: crop tops stay short
    hem_max = _f(a["crotch"]["y"]) + MAX_SHIRT_BELOW_CROTCH * (_f(a["knee"]["y"]) - _f(a["crotch"]["y"]))
    cut_hem = hem_y > hem_max
    if cut_hem:  # cut, never squeeze
        warnings.append(f"hem: garment is {hem_y - hem_max:.0f} px too long for this body, cut at the limit")
        hem_y = hem_max
        g_hem = g_sy + (hem_y - a_sy) / s
    chest_dst = to_dst(_f(g["chest"]["y"]))
    knot = min(chest_dst, hem_y - 1.0)  # the vertical scale is s down to here; below it the hem may be snapped
    hem_own = hem_y
    if hem_over is not None and 0 <= hem_over - HEM_OVER_WAISTBAND - hem_y <= HEM_GAP_MAX + 0.04 * (a_sr - a_sl) \
            and hem_over <= hem_max:
        hem_y = hem_over
    g_knot = g_sy + (knot - a_sy) / s
    v_stretch = (hem_y - knot) / max(hem_own - knot, 1e-6)  # 1 unless snapped

    def to_src(dy):
        return g_sy + (dy - a_sy) / s if dy <= knot else g_knot + (dy - knot) / (s * v_stretch)

    def body_w(y):
        bl, br = body_span(a, y)
        return br - bl

    # looseness once per garment, from the chest and waist rows (mean of both)
    ratios = []
    for k in ("chest", "waist"):
        gy = _f(g[k]["y"])
        if to_dst(gy) <= hem_y:
            ratios.append((_f(g[k]["right_x"]) - _f(g[k]["left_x"])) * s / max(body_w(to_dst(gy)), 1e-6))
    t_loose = tshirt_looseness(ratios or [1.0])
    if info is not None:
        info["tshirt_fit"] = {"ratio": sum(ratios) / len(ratios) if ratios else 1.0, "t": t_loose}

    # ---- sleeves: geometry. Rigid (uniform s + rotation), pivot = shoulder point, outer edge along the figure's
    # outer silhouette edge (deltoid, then the upper arm). The body's armpit landmark is NOT used.
    yy, xx = np.mgrid[0:gh, 0:gw]
    sleeves, hems, shoulders = {}, {}, {}
    torso_keep = np.ones((gh, gw), bool)
    for side in ("left", "right"):
        own, draw = sleeve_regions(alpha, g, side, g_rows)
        torso_keep &= ~own
        S_g = np.array([_f(g["shoulder"][f"{side}_x"]), g_sy])
        A_g = np.array([_f(g["chest"][f"{side}_x"]), _f(g["chest"]["y"])])
        E_g = np.array([_f(g["sleeve_end"][side]["x"]), _f(g["sleeve_end"][side]["y"])])
        S_b = np.array([a_sl if side == "left" else a_sr, a_sy])
        S_b[0] += (-1 if side == "left" else 1) * (a_sr - a_sl) * TSHIRT_EASE / 2
        shoulders[side] = S_b.copy()
        v_g = E_g - S_g
        if not (own & alpha).any() or np.linalg.norm(v_g) < 2:
            continue  # sleeveless
        u_g = v_g / np.linalg.norm(v_g)
        proj = ((xx - S_g[0]) * u_g[0] + (yy - S_g[1]) * u_g[1])[own & alpha]
        length = max(float(np.percentile(proj, 99.5)), float(np.linalg.norm(v_g)))  # shoulder -> sleeve hem (src px)
        arm = (arms or {}).get(side)
        edge = None
        if mask is not None:
            edge = outer_edge_line(mask, side, a_sy + 3, a_sy + length * s * 1.2)
        if edge:
            d = np.array([edge[0], 1.0])
            x_edge = edge[0] * a_sy + edge[1]
            S_b[0] = min(S_b[0], x_edge) if side == "left" else max(S_b[0], x_edge)
        elif arm:
            d = np.array([arm["slope"], 1.0])
        else:
            d = v_g.copy()
            warnings.append(f"sleeve {side}: arm not found in the mask, garment angle used")
        d = d / np.linalg.norm(d)
        theta = np.arctan2(d[1], d[0]) - np.arctan2(v_g[1], v_g[0])
        R = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]]) * s
        k = 1.0
        if arm and d[1] > 1e-6:  # longer than allowed on this arm: shorten along the axis (never stretch)
            allowed = SLEEVE_MAX_ARM * (arm["end_y"] - a_sy) / d[1]
            if length * s > allowed:
                k = max(allowed / (length * s), 0.2)
            if k < 0.98:
                warnings.append(f"sleeve {side}: shortened to {k:.0%} to end half way down the arm")
        Mlin = (np.eye(2) + (k - 1) * np.outer(d, d)) @ R
        if arm and edge:  # axis on the arm: a sleeve wider than the arm spreads evenly to both sides of it
            oy, ox = np.nonzero(own & alpha)
            q = (np.stack([ox, oy], axis=1) - S_g) @ Mlin.T
            along, perp = q @ d, q @ np.array([-d[1], d[0]])
            low = along > 0.5 * along.max()  # the half of the sleeve near its hem
            mid = (np.array([-d[1], d[0]]) * (perp[low].min() + perp[low].max()) / 2 + d * along[low].mean())
            y_mid = S_b[1] + mid[1]
            arm_w = float(np.median([r_ - l_ for _, l_, r_ in arm["rows"][:15]]))
            inward = 1.0 if side == "left" else -1.0
            target = edge[0] * y_mid + edge[1] + inward * arm_w / 2  # arm centre: half an arm inside its outer edge
            shift = target - (S_b[0] + mid[0])
            S_b = S_b + np.array([float(np.clip(shift, -arm_w, arm_w)), 0.0])
        M = np.hstack([Mlin, (S_b - Mlin @ S_g).reshape(2, 1)]).astype(np.float32)
        hem_pt = S_b + d * (length * s * k + 1.0)  # the hem line: across the arm, just past the last sleeve pixel
        hems[side] = (np.float32(hem_pt), np.float32(hem_pt + np.array([-d[1], d[0]])), S_b)
        sleeves[side] = (M, draw, S_b, S_b + Mlin @ (A_g - S_g))

    torso_img = img.copy()
    torso_img[:, :, 3] = np.where(torso_keep, img[:, :, 3], 0)
    t_alpha = torso_img[:, :, 3] > 128

    def armhole_x(side, y):
        """x of the rigid sleeve's armhole edge (shoulder point -> armpit point, dst) at row y, or None."""
        if side not in sleeves:
            return None
        p0, p1 = sleeves[side][2], sleeves[side][3]
        if not min(p0[1], p1[1]) <= y <= max(p0[1], p1[1]) or abs(p1[1] - p0[1]) < 1e-6:
            return None
        return p0[0] + (y - p0[1]) / (p1[1] - p0[1]) * (p1[0] - p0[0])

    # ---- torso: row warp
    src_rows, dst_rows, worst = [], [], 1.0
    # collar / neckline above the shoulder line: uniform scale, centred on the body (no fitting)
    top = np.where(t_alpha[:, max(int(g_sl), 0):int(g_sr) + 1].any(axis=1))[0]
    if len(top) and g_sy - top[0] > 2:
        for sy in np.arange(float(top[0]) - 1.0, g_sy, 2.0):
            span = _alpha_span(t_alpha, max(sy, float(top[0])), g_sl, g_sr)
            if span:
                src_rows.append((sy, float(span[0]), span[1] + 1.0))
                dst_rows.append((to_dst(sy), a_cx + (span[0] - g_cx) * s, a_cx + (span[1] + 1.0 - g_cx) * s))
    sep_y = _f(a["armpit"]["y"])  # below this the arms are separate in the mask: the torso run is the body
    axis = _crotch_x(a)
    torso = []
    for y in _ys(a_sy, hem_y, ROW_STEP):
        sy = to_src(y)
        sl, sr = _garment_span(t_alpha, sy, _interp_span(g_rows, sy))
        bl, br = body_span(a, y)
        bw = br - bl
        w = tshirt_row_width((sr - sl) * s, bw, (y - a_sy) / max(chest_dst - a_sy, 1e-6))
        c = (1 - t_loose) * (bl + br) / 2 + t_loose * a_cx  # tight follows the torso, loose hangs straight
        half = w / 2
        if mask is not None and y > sep_y:  # the avatar's own top/shorts never show at the sides (symmetric)
            run = next((q for q in _runs(mask[min(int(y), H - 1)]) if q[0] <= axis <= q[1]), None)
            if run and run[1] - run[0] < PANTS_MAX_BODY * bw:
                half = max(half, c - (run[0] - 2), run[1] + 3 - c)
        l, r = c - half, c + half
        xl, xr = armhole_x("left", y), armhole_x("right", y)  # meet the sleeve's armhole edge: no skin wedge
        l = min(l, xl) if xl is not None else l
        r = max(r, xr) if xr is not None else r
        src_rows.append((sy, sl, sr))
        dst_rows.append((y, l, r))
        torso.append((y, l, r))
        if y >= chest_dst and sr - sl > 1:
            ratio = (r - l) / ((sr - sl) * s)
            worst = ratio if abs(np.log(ratio)) > abs(np.log(worst)) else worst
    if worst > PANTS_DISTORT_LIMIT or worst < 1 / PANTS_DISTORT_LIMIT:
        warnings.append(f"torso: distorted {max(worst, 1 / worst):.2f}x ({'wider' if worst > 1 else 'narrower'})")
    if not cut_hem:
        _tail_rows(t_alpha, src_rows, dst_rows, s * v_stretch)
    parts = {"torso": _warp_rows(torso_img, src_rows, dst_rows, H, W)}

    # ---- sleeves: each drawn exactly once, by its rigid piece
    for side, (M, draw, _, _) in sleeves.items():
        piece = img.copy()
        piece[:, :, 3] = np.where(draw, img[:, :, 3], 0)
        parts[f"sleeve_{side}"] = _warp_affine_premultiplied(piece, M, W, H)

    result = parts["torso"]
    for side in ("left", "right"):
        if f"sleeve_{side}" in parts:
            result = _alpha_composite(result, parts[f"sleeve_{side}"])
    if info is not None:
        info["sleeve_hems"] = hems
        info["tshirt_rows"] = torso
        info["tshirt_hem"] = torso[-1]
        info["tshirt_parts"] = parts
        info["tshirt_shoulders"] = (float(shoulders["left"][0]), float(shoulders["right"][0]))
    return result, warnings


def tshirt_scale(g: dict, a: dict) -> float:
    """The T-shirt's one uniform scale: garment shoulder line -> body shoulder line + ease."""
    return (_f(a["shoulder"]["right_x"]) - _f(a["shoulder"]["left_x"])) * (1 + TSHIRT_EASE) / \
        (_f(g["shoulder"]["right_x"]) - _f(g["shoulder"]["left_x"]))


def head_neck_overlay(base_mask: np.ndarray, lm: dict) -> np.ndarray:
    """HxW float weight (0..1) of the avatar's head and neck drawn ON TOP of the garment: figure pixels within the
    neck width + NECK_MARGIN and above a U-shaped lower edge (half ellipse: NECK_ARC x neck width below the `neck`
    row at the centre, rising NECK_RISE x neck width above it at the sides, like a crew collar that wraps the neck),
    feathered. Ghost-mannequin back collars never cover them."""
    n = lm.get("neck")
    out = np.zeros(base_mask.shape, np.float32)
    if not n:
        return out
    H, W = base_mask.shape
    lx, rx = _f(n["left_x"]) - NECK_MARGIN, _f(n["right_x"]) + NECK_MARGIN
    cx, half = (lx + rx) / 2, max((rx - lx) / 2, 1.0)
    nw = _f(n["right_x"]) - _f(n["left_x"])
    depth, rise = NECK_ARC * nw, NECK_RISE * nw
    xs = np.arange(W, dtype=np.float32)
    u = np.clip((xs - cx) / half, -1, 1)
    bottom = _f(n["y"]) - rise + (depth + rise) * np.sqrt(1 - u * u)  # lowest under the chin centre
    yy = np.arange(H, dtype=np.float32)[:, None]
    out[:] = ((yy < bottom[None, :]) & (xs[None, :] >= lx) & (xs[None, :] <= rx)).astype(np.float32)
    out = cv2.GaussianBlur(out, (0, 0), NECK_FEATHER)
    return out * base_mask


def shoulder_cap_layer(tshirt: np.ndarray, figure: np.ndarray, lm: dict, head: np.ndarray,
                       shoulders: tuple | None) -> np.ndarray:
    """BGRA layer of the two shoulder caps: figure pixels ABOVE the T-shirt's own top edge, between each collar
    top point (the garment's highest pixel on that side) and the shoulder point, at most CAP_MAX_DEPTH of the
    figure height deep and never above the collar top. Colour: the garment pixel just below, in the same column.
    Nothing inside the neckline, below the garment's top edge or beyond the shoulder points is touched."""
    H, W = figure.shape
    out = np.zeros_like(tshirt)
    opaque = tshirt[:, :, 3] >= 250
    cols = opaque.any(axis=0)
    if shoulders is None or not cols.any():
        return out
    top = np.where(cols, opaque.argmax(axis=0), H)
    fig_h = _f(lm.get("foot_bottom", {}).get("y", H - 50)) - _f(lm.get("head_top", {}).get("y", 50))
    depth = int(round(CAP_MAX_DEPTH * fig_h))
    cx = (shoulders[0] + shoulders[1]) / 2
    region = np.zeros((H, W), bool)
    for side, x0, x1 in (("left", shoulders[0], cx), ("right", cx, shoulders[1])):
        xs = np.arange(max(int(np.floor(x0)), 0), min(int(np.ceil(x1)) + 1, W))
        xs = xs[cols[xs]]
        if not len(xs):
            continue
        peak = xs[np.argmin(top[xs])]
        y_top = int(top[peak])
        for x in (xs[xs <= peak] if side == "left" else xs[xs >= peak]):
            y1 = int(top[x])
            y0 = max(y_top, y1 - depth)
            if y1 > y0:
                region[y0:y1, x] = True
                out[y0:y1 + 2, x, :3] = tshirt[min(y1 + 2, H - 1), x, :3]
    region &= figure & (head < 0.5)
    soft = cv2.GaussianBlur(region.astype(np.float32), (0, 0), CAP_FEATHER)
    out[:, :, 3] = np.clip(np.maximum(soft, region) * 255 * figure, 0, 255).astype(np.uint8)
    out[:, :, 3][~cv2.dilate(region.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)] = 0
    return out


PANTS_EASE = 0.04  # pants cover the body with ~4% ease (no skin/underwear showing)
PANTS_MAX_BODY = 1.8  # a pants row is never wider than this times the body
PANTS_DISTORT_LIMIT = 1.3  # warn when a row's horizontal scale differs from the uniform scale by more


def _smooth(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def pants_width(garment_w: float, body_w: float, ease: float = PANTS_EASE, cap: float = PANTS_MAX_BODY,
                cap_ref: float | None = None) -> float:
    """Width of a pants row below the hip: the garment's own (uniformly scaled) width, but at least the body plus
    ease so nothing shows through, and at most `cap` times `cap_ref` (default: the body width of the row; below
    the knee the knee width, so cuffs and flares are not squeezed to the thin ankle)."""
    if body_w <= 0:
        return garment_w
    ref = max(body_w, cap_ref or 0)
    return min(max(garment_w, body_w * (1 + ease)), ref * cap)


def waist_blend_width(garment_w: float, body_w: float, t: float, ease: float = PANTS_EASE) -> float:
    """Between waist (t=0) and hip (t=1): from the body-fitted waistband to the garment's own width (smoothstep)."""
    k = _smooth(t)
    return (1 - k) * body_w * (1 + ease) + k * pants_width(garment_w, body_w, ease)


def _ys(y0: float, y1: float, step: int = 6) -> list[float]:
    ys = list(np.arange(y0, y1, step, dtype=np.float64))
    return [float(y) for y in ys] + [float(y1)]


def pants_looseness(knee_ratios) -> dict:
    """One set of weights per garment (both legs alike): looseness t = smoothstep over LOOSE_FROM..LOOSE_FULL of the
    mean knee ratio; knee_pull 1 (tight, through the knee) -> LOOSE_KNEE_PULL; hang 1 (body line) -> HANG_LOOSE."""
    ratio = sum(knee_ratios) / len(knee_ratios)
    t = _smooth((ratio - LOOSE_FROM) / (LOOSE_FULL - LOOSE_FROM))
    return {"ratio": ratio, "t": t, "knee_pull": 1 - t * (1 - LOOSE_KNEE_PULL), "hang": 1 - t * (1 - HANG_LOOSE)}


def leg_centerline(y: float, top: tuple, knee: tuple, ankle: tuple, knee_weight: float) -> float:
    """Leg centre x at row y; points are (y, x). knee_weight >= 1: the piecewise line through the knee (tight).
    Otherwise a quadratic Bezier from top to ankle (control at mid height) that is off the straight line at the
    knee row by knee_weight of the knee's offset; the control x is clamped between the end points so x(y) is
    monotonic (no kink, no bulge at the knee)."""
    (y0, x0), (yk, xk), (y2, x2) = top, knee, ankle
    if knee_weight >= 1:
        return _interp_span([(y0, x0, x0), (yk, xk, xk), (y2, x2, x2)], y)[0]
    span = max(y2 - y0, 1e-6)
    u = min(max((y - y0) / span, 0.0), 1.0)
    uk = min(max((yk - y0) / span, 0.05), 0.95)
    xs = x0 + uk * (x2 - x0)
    target = xs + knee_weight * (xk - xs)
    x1 = (target - (1 - uk) ** 2 * x0 - uk ** 2 * x2) / (2 * uk * (1 - uk))
    x1 = min(max(x1, min(x0, x2)), max(x0, x2))
    return (1 - u) ** 2 * x0 + 2 * u * (1 - u) * x1 + u ** 2 * x2


def curve_waistband(layer: np.ndarray, top_y: float, hip_y: float, lx: float, rx: float,
                    depth: float = WAISTBAND_CURVE) -> np.ndarray:
    """Bend the straight waistband top into a slight curve: the centre drops by depth * waist width, the sides stay;
    the bend fades out by the hip row (content is moved, not cut)."""
    H, W = layer.shape[:2]
    half = max((rx - lx) / 2, 1.0)
    xs = np.arange(W, dtype=np.float32)
    u = np.clip((xs - (lx + rx) / 2) / half, -1, 1)
    drop = depth * (rx - lx) * (1 - u * u)  # per column
    ys = np.arange(H, dtype=np.float32)[:, None]
    fade = np.clip(1 - (ys - top_y) / max(hip_y - top_y, 1.0), 0, 1)
    map_y = (ys - drop[None, :] * fade).astype(np.float32)
    map_x = np.repeat(xs[None, :], H, axis=0)
    return cv2.remap(layer, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def pants_scale(g: dict, a: dict, H: int) -> tuple[float, bool]:
    """(the pants' one uniform scale, full length?): waist..hem -> waist..ankle when the hem would land within
    FULL_LENGTH_TOLERANCE of the ankle at the rise scale, else the rise scale (waist..crotch)."""
    legs = ("left_leg", "right_leg")
    g_wy, a_wy = _f(g["waist"]["y"]), _f(a["waist"]["y"])
    g_hem_y = sum(_f(g["hem"][leg]["y"]) for leg in legs) / 2
    a_ank_y = sum(_f(a["ankle"][leg]["y"]) for leg in legs) / 2
    fig_h = _f(a.get("foot_bottom", {}).get("y", H - 50)) - _f(a.get("head_top", {}).get("y", 50))
    s_rise = (_f(a["crotch"]["y"]) - a_wy) / (_f(g["crotch"]["y"]) - g_wy)
    full = a_wy + (g_hem_y - g_wy) * s_rise >= a_ank_y - FULL_LENGTH_TOLERANCE * fig_h
    return ((a_ank_y - a_wy) / (g_hem_y - g_wy) if full else s_rise), full


def warp_pants(body_lm: dict, garment_lm: dict, garment_img: np.ndarray, H: int, W: int,
               arms: dict | None = None, info: dict | None = None,
               mask: np.ndarray | None = None) -> tuple[np.ndarray, list]:
    """Pants keep their own silhouette: one uniform scale for both axes (waist..hem vs the body's waist..ankle,
    or the rise for shorter pants). Only the waistband is fitted to the body; below the hip each row is
    pants_width(garment, body). Each leg is centred on the body's leg centreline (crotch -> knee -> ankle)."""
    warnings: list[str] = []
    g, a = garment_lm, body_lm
    img = _bgra(garment_img)
    g_alpha = img[:, :, 3] > 128

    g_wy, a_wy = _f(g["waist"]["y"]), _f(a["waist"]["y"])
    g_cr, a_cr = _f(g["crotch"]["y"]), _f(a["crotch"]["y"])
    g_hy = _f(g["hip"]["y"])
    s, full = pants_scale(g, a, H)
    to_dst = lambda gy: a_wy + (gy - g_wy) * s  # noqa: E731

    worst: dict[str, float] = {}

    def track(label, src_w, dst_w):
        if src_w > 1:
            r = dst_w / (src_w * s)
            if abs(np.log(r)) > abs(np.log(worst.get(label, 1.0))):
                worst[label] = r

    # waist -> crotch block, centred on the body
    g_rows = [(g_wy, _f(g["waist"]["left_x"]), _f(g["waist"]["right_x"])),
              (g_hy, _f(g["hip"]["left_x"]), _f(g["hip"]["right_x"])),
              (g_cr, _f(g["hip"]["left_x"]), _f(g["hip"]["right_x"]))]
    hip_dst, cr_dst = to_dst(g_hy), to_dst(g_cr)
    src_rows, dst_rows = [], []
    for y in _ys(a_wy, cr_dst, ROW_STEP):
        sy = g_wy + (y - a_wy) / s
        sl, sr = _garment_span(g_alpha, sy, _interp_span(g_rows, sy))
        bl, br = body_span(a, y)
        t = (y - a_wy) / max(hip_dst - a_wy, 1e-6)
        w = waist_blend_width((sr - sl) * s, br - bl, t) if t < 1 else pants_width((sr - sl) * s, br - bl)
        c = (bl + br) / 2
        src_rows.append((sy, sl, sr))
        dst_rows.append((y, c - w / 2, c + w / 2))
        if t >= 1:
            track("waist-crotch", sr - sl, w)
    result = _warp_rows(img, src_rows, dst_rows, H, W)
    result = curve_waistband(result, a_wy, hip_dst, dst_rows[0][1], dst_rows[0][2])
    top_dip = WAISTBAND_CURVE * (dst_rows[0][2] - dst_rows[0][1])
    block_l, block_r = dst_rows[-1][1], dst_rows[-1][2]

    g_cx, a_cx = _f(g["crotch"]["center_x"]), _crotch_x(a)
    g_kn_y, a_kn_y = _f(g["knee"]["y"]), _f(a["knee"]["y"])
    knee_ratios = []
    for side in ("left", "right"):
        leg = f"{side}_leg"
        ak, gk = a["knee"][leg], g["knee"][leg]
        run = _leg_run(mask, int(a_kn_y), side, a_cx, (_f(ak["left_x"]) + _f(ak["right_x"])) / 2) \
            if mask is not None else None
        knee_bw = (run[1] - run[0]) if run else _f(ak["right_x"]) - _f(ak["left_x"])
        knee_ratios.append(((_f(gk["right_x"]) - _f(gk["left_x"])) * s / max(knee_bw, 1e-6), knee_bw))
    fit = pants_looseness([r for r, _ in knee_ratios])  # same weights for both legs: symmetric garment, symmetric fit
    if info is not None:
        info["pants_fit"] = {**fit, "legs": {side: {"ratio": r, "knee_pull": fit["knee_pull"], "hang": fit["hang"]}
                                             for side, (r, _) in zip(("left", "right"), knee_ratios)}}
    for side, (_, knee_bw) in zip(("left", "right"), knee_ratios):
        leg = f"{side}_leg"
        gk, gh, ak, aa = g["knee"][leg], g["hem"][leg], a["knee"][leg], a["ankle"][leg]
        g_outer, a_outer = _f(g["hip"][f"{side}_x"]), _f(a["hip"][f"{side}_x"])
        leg_src = [(g_cr, g_outer, g_cx) if side == "left" else (g_cr, g_cx, g_outer),
                   (g_kn_y, _f(gk["left_x"]), _f(gk["right_x"])),
                   (_f(gh["y"]), _f(gh["left_x"]), _f(gh["right_x"]))]
        body_rows = [(a_cr, a_outer, a_cx) if side == "left" else (a_cr, a_cx, a_outer),
                     (a_kn_y, _f(ak["left_x"]), _f(ak["right_x"])),
                     (_f(aa["y"]), _f(aa["left_x"]), _f(aa["right_x"]))]
        hem_dst = _f(aa["y"]) if full else to_dst(_f(gh["y"]))
        s_leg = (_f(gh["y"]) - g_cr) / max(hem_dst - cr_dst, 1e-6)  # src px per dst px (= 1/s up to hem snapping)
        knee_dst = cr_dst + (g_kn_y - g_cr) / s_leg
        top = (block_l, a_cx) if side == "left" else (a_cx, block_r)
        drop_x = (body_rows[0][1] + body_rows[0][2]) / 2  # leg centre at the crotch row, dropped straight down
        centre_pts = [(y_, (l_ + r_) / 2) for y_, l_, r_ in body_rows]
        wb = fit["hang"]  # hang: loose legs fall towards a straight drop (no V on wide stances)
        src_rows, dst_rows = [], []
        for y in _ys(cr_dst, hem_dst, ROW_STEP):
            sy = g_cr + (y - cr_dst) * s_leg
            sl, sr = _garment_span(g_alpha, sy, _interp_span(leg_src, sy), side, g_cx)
            bl, br = _interp_span(body_rows, y)
            # tight: through the knee; loose: smooth monotonic curve; blended by the garment's looseness
            c = (1 - fit["t"]) * leg_centerline(y, *centre_pts, 1.0) + \
                fit["t"] * leg_centerline(y, *centre_pts, LOOSE_KNEE_PULL)
            run = _leg_run(mask, int(y), side, a_cx, (bl + br) / 2) if mask is not None else None
            bw = (run[1] - run[0]) if run else br - bl
            c = wb * c + (1 - wb) * drop_x
            w = pants_width((sr - sl) * s, bw, cap_ref=knee_bw if y > a_kn_y else None)
            half = w / 2
            if run:  # the body's leg in the mask is always covered; the width spreads evenly to both sides
                half = max(half, c - (run[0] - 2), run[1] + 3 - c)
            l, r = c - half, c + half
            k = 1 - _smooth((y - cr_dst) / max(knee_dst - cr_dst, 1e-6))  # join the waist block at the crotch
            l, r = k * top[0] + (1 - k) * l, k * top[1] + (1 - k) * r
            src_rows.append((sy, sl, sr))
            dst_rows.append((y, l, r))
            if k < 0.5:
                track(f"{side}-leg", sr - sl, r - l)
        if info is not None:
            info.setdefault("pants_leg_rows", {})[side] = dst_rows
        _tail_rows(g_alpha, src_rows, dst_rows, 1 / s_leg)
        strip = _warp_rows(img, src_rows, dst_rows, H, W)
        result = _alpha_composite(result, strip)

    for label, r in worst.items():
        if r > PANTS_DISTORT_LIMIT or r < 1 / PANTS_DISTORT_LIMIT:
            warnings.append(f"{label}: distorted {max(r, 1 / r):.2f}x ({'wider' if r > 1 else 'narrower'})")
    result[:max(int(np.ceil(a_wy)), 0)] = 0  # pants exist only from their own waist row down
    if info is not None:
        info["pants_waist_y"] = a_wy
        info["pants_top_dip"] = top_dip
    return result, warnings


# ---------- opaque silhouette ----------

def _largest_silhouette(alpha: np.ndarray) -> np.ndarray:
    """Bool mask of the largest outer contour of alpha >= 128, filled (holes included)."""
    cnts, _ = cv2.findContours((alpha >= 128).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    filled = np.zeros(alpha.shape, np.uint8)
    if cnts:
        cv2.drawContours(filled, [max(cnts, key=cv2.contourArea)], -1, 1, -1)
    return filled.astype(bool)


def background_color(img: np.ndarray):
    """Median colour of the transparent pixels outside the garment (rembg keeps the photo's own background colour
    there), or None if there are too few."""
    a = img[:, :, 3]
    out = (a == 0) & ~_largest_silhouette(a)
    if out.sum() < 20:
        return None
    return np.median(img[:, :, :3][out].astype(np.float32), axis=0)


def opening_mask(img: np.ndarray, bg) -> np.ndarray:
    """Holes inside the silhouette whose colour matches the background: real openings (e.g. a neck hole)."""
    a = img[:, :, 3]
    holes = _largest_silhouette(a) & (a < 128)
    keep = np.zeros(a.shape, bool)
    if bg is None or not holes.any():
        return keep
    n, lab = cv2.connectedComponents(holes.astype(np.uint8), connectivity=8)
    rgb = img[:, :, :3].astype(np.float32)
    for i in range(1, n):
        m = lab == i
        if np.linalg.norm(np.median(rgb[m], axis=0) - np.asarray(bg, np.float32)) <= OPENING_COLOR_DIST:
            keep |= m
    return keep


def fill_alpha_holes(img: np.ndarray, keep: np.ndarray | None = None, inpaint: bool = False) -> np.ndarray:
    """Alpha 255 for every pixel inside the largest outer contour, except its outer 1 px edge and `keep` (real
    openings, whose 1 px edge also stays soft). inpaint: colour the newly opaque and soft-edge pixels from the
    nearest opaque pixel (warped layers store black under alpha 0; a cleaned photo keeps its true colours)."""
    a = img[:, :, 3]
    k3 = np.ones((3, 3), np.uint8)
    interior = cv2.erode(_largest_silhouette(a).astype(np.uint8), k3) > 0
    if keep is not None and keep.any():
        interior &= ~(cv2.dilate(keep.astype(np.uint8), k3) > 0)
    todo = interior & (a < 255)
    if not todo.any():
        return img
    out = img.copy()
    if inpaint:
        _colour_from_nearest_opaque(out, (interior & (a < 250)) | ((a > 0) & (a < 250)))
    out[:, :, 3][todo] = 255
    return out


def _colour_from_nearest_opaque(img: np.ndarray, where: np.ndarray, ok: np.ndarray | None = None) -> None:
    """In place: RGB of `where` pixels from the nearest fully opaque pixel (or the nearest `ok` pixel). Warped
    layers keep black under alpha 0, so up-scaled soft edges and holes are darkened; this removes that ring/spot."""
    ok = img[:, :, 3] >= 250 if ok is None else ok
    if not where.any() or not ok.any():
        return
    _, labels = cv2.distanceTransformWithLabels((~ok).astype(np.uint8), cv2.DIST_L2, 3,
                                                labelType=cv2.DIST_LABEL_PIXEL)
    oy, ox = np.nonzero(ok)  # DIST_LABEL_PIXEL numbers the zero (= ok) pixels 1.. in raster order
    idx = labels[where] - 1
    img[:, :, :3][where] = img[oy[idx], ox[idx], :3]


def remove_halo(img: np.ndarray, px: int = HALO_ERODE) -> np.ndarray:
    """Garment without its photo-background fringe: the alpha is eroded by px (the soft edge moves inward and
    stays soft), and the RGB of the new edge ring (the next px, where fringe colour is still blended in) is taken
    from the nearest interior pixel. Pixels deeper than 2 * px keep their colour exactly."""
    a = np.ascontiguousarray(img[:, :, 3])
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * px + 1, 2 * px + 1))
    er = cv2.erode(a, k, borderType=cv2.BORDER_CONSTANT, borderValue=0)
    deep = cv2.erode(er, k, borderType=cv2.BORDER_CONSTANT, borderValue=0)
    out = img.copy()
    _colour_from_nearest_opaque(out, (er > 0) & (deep < 250), ok=deep >= 250)
    out[:, :, 3] = er
    return out


def _scale_landmarks(lm, k: float):
    if isinstance(lm, dict):
        return {key: _scale_landmarks(v, k) for key, v in lm.items()}
    return lm * k if isinstance(lm, (int, float)) and not isinstance(lm, bool) else lm


def _prescale(img: np.ndarray, k: float) -> np.ndarray:
    """Area-resampled (premultiplied) copy at scale k < 1: a 1500 px photo squeezed to 200 px by the bilinear
    warp alone would alias (jagged edges, moire in ribbing)."""
    h, w = img.shape[:2]
    f = img.astype(np.float32)
    f[:, :, :3] *= f[:, :, 3:4] / 255.0
    f = cv2.resize(f, (max(int(round(w * k)), 2), max(int(round(h * k)), 2)), interpolation=cv2.INTER_AREA)
    a = f[:, :, 3:4] / 255.0
    f[:, :, :3] = np.where(a > 0, f[:, :, :3] / np.maximum(a, 1e-6), 0)
    return np.clip(np.rint(f), 0, 255).astype(np.uint8)


def garment_layer(gtype: str, gimg: np.ndarray, glm: dict, body_lm: dict, H: int, W: int,
                  arms: dict, info: dict, mask: np.ndarray, halo_removal: bool = True,
                  **kw) -> tuple[np.ndarray, list]:
    """Warped BGRA layer of one garment, opaque inside its silhouette. Steps, each once: fill holes in the cleaned
    image (background-coloured openings kept) -> resample to about the final size when it shrinks a lot ->
    remove the halo -> warp -> fill warp seams. Openings are warped along and stay open."""
    fn = {"tshirt": warp_tshirt, "pants": warp_pants}[gtype]
    src = _bgra(gimg)
    openings = opening_mask(src, background_color(src))
    src = fill_alpha_holes(src, openings)
    aux = None
    if openings.any():
        aux = np.zeros_like(src)
        aux[openings] = 255
    if gtype == "tshirt":
        glm, _ = normalize_tshirt_landmarks(glm, src[:, :, 3] > 128)
    k = tshirt_scale(glm, body_lm) if gtype == "tshirt" else pants_scale(glm, body_lm, H)[0]
    if k < PRESCALE_BELOW:
        src, glm = _prescale(src, k), _scale_landmarks(glm, k)
        aux = _prescale(aux, k) if aux is not None else None
    if halo_removal:
        src = remove_halo(src)
    warped, warns = fn(body_lm, glm, src, H, W, arms=arms, info=info, mask=mask, **kw)
    keep = None
    if aux is not None:
        aux_w, _ = fn(body_lm, glm, aux, H, W, arms=arms, info={}, mask=mask, **kw)
        keep = aux_w[:, :, 3] > 128
    return fill_alpha_holes(warped, keep, inpaint=True), warns


# ---------- realism (optional: shading, edges, contact shadow) ----------

def shading_map(base: np.ndarray, region: np.ndarray, sigma: float = SHADING_SIGMA,
                lo: float = SHADING_RANGE[0], hi: float = SHADING_RANGE[1]) -> np.ndarray:
    """HxW float32 shade from the avatar's own luminance: gray / blur(gray) inside `region` (blur normalised by
    the region so the white background does not leak in), clipped to lo..hi and smoothed; 1.0 outside."""
    gray = cv2.cvtColor(np.ascontiguousarray(base[:, :, :3]), cv2.COLOR_BGR2GRAY).astype(np.float32)
    m = region.astype(np.float32)
    if not m.any():
        return np.ones(region.shape, np.float32)
    num = cv2.GaussianBlur(gray * m, (0, 0), sigma)
    den = cv2.GaussianBlur(m, (0, 0), sigma)
    shade = np.where(m > 0, gray / np.maximum(num / np.maximum(den, 1e-6), 1.0), 1.0)
    shade = cv2.GaussianBlur(np.clip(shade, lo, hi).astype(np.float32), (0, 0), 1.5)
    return np.where(m > 0, np.clip(shade, lo, hi), 1.0).astype(np.float32)


def apply_shading(layer: np.ndarray, shade: np.ndarray, strength: float = SHADING_STRENGTH) -> np.ndarray:
    """BGRA layer with RGB multiplied by shade ** strength. Alpha is never modified."""
    out = layer.copy()
    out[:, :, :3] = np.clip(layer[:, :, :3].astype(np.float32) * (shade ** strength)[:, :, None], 0, 255)
    return out


def soften_edges(layer: np.ndarray) -> np.ndarray:
    """Drop the 1 px rim (often the photo's background colour), then feather the alpha edge by about 1 px.
    The colour under the feathered fringe is taken from the nearest garment pixels (no dark halo)."""
    a = layer[:, :, 3]
    if not a.any():
        return layer
    k = np.ones((3, 3), np.uint8)
    inner = cv2.erode(a, k)
    rgb = layer[:, :, :3].copy()
    solid = inner > 0
    fill = rgb * solid[:, :, None]
    for _ in range(2):  # grow the inner colours outwards over the rim and the feather
        grown = cv2.dilate(fill, k)
        grown_m = cv2.dilate(solid.astype(np.uint8), k) > 0
        fill = np.where(solid[:, :, None], fill, grown)
        solid = grown_m
    out = np.empty_like(layer)
    out[:, :, :3] = fill
    out[:, :, 3] = cv2.GaussianBlur(inner, (0, 0), 0.8)
    return out


def contact_shadow(alpha: np.ndarray, figure: np.ndarray, axis_x: float,
                   opacity: float = SHADOW_OPACITY) -> np.ndarray:
    """HxW float32 darkening (0..opacity) cast by the garment on the avatar: blurred alpha shifted down and
    inward, only on the figure (never on the background)."""
    H, W = alpha.shape
    dx, dy = SHADOW_OFFSET
    a = alpha.astype(np.float32) / 255.0
    shifted = np.zeros_like(a)
    ax = int(round(axis_x))
    shifted[dy:, dx:ax] = a[:H - dy, :ax - dx]  # left half moves right
    shifted[dy:, ax:W - dx] = a[:H - dy, ax + dx:]  # right half moves left
    return cv2.GaussianBlur(shifted, (0, 0), SHADOW_SIGMA) * opacity * figure


# ---------- full render ----------

def arm_overlay_mask(mask: np.ndarray, arms: dict, sleeve_hems: dict | None) -> np.ndarray:
    """Arm pixels that must stay above the garment: separated arm runs, beyond the sleeve hem if any."""
    H, W = mask.shape
    out = np.zeros((H, W), bool)
    for side, arm in arms.items():
        if not arm:
            continue
        for y, l, r in arm["rows"]:
            out[y, l:r + 1] = True
        hem = (sleeve_hems or {}).get(side)
        if hem is not None:  # keep only the part on the far side of the sleeve hem line (away from the shoulder)
            p0, p1, shoulder = hem
            yy, xx = np.mgrid[0:H, 0:W]
            n = np.array([-(p1[1] - p0[1]), p1[0] - p0[0]])
            side_of = lambda x, y: (x - p0[0]) * n[0] + (y - p0[1]) * n[1]  # noqa: E731
            beyond = np.sign(side_of(xx, yy)) != np.sign(side_of(shoulder[0], shoulder[1]))
            half = np.zeros((H, W), bool)
            half[:, : W // 2] = side == "left"
            half[:, W // 2:] = side == "right"
            out &= ~half | beyond
    return out & mask


# One explicit layer order, bottom to top (docs/06 "Layer order"). Every layer is clipped to its own region.
LAYER_ORDER = ("avatar", "pants", "shoulder_cap", "tshirt_torso", "tshirt_sleeves", "head_neck", "hands_forearms")


def render_tryon(base: np.ndarray, body_lm: dict, garments: list, H: int = 1200, W: int = 600,
                 shading: bool = False, contact_shadows: bool = False, edge_feather: bool = False,
                 shading_strength: float = SHADING_STRENGTH, shoulder_cap: bool = True, hem_snap: bool = True,
                 halo_removal: bool = True):
    """base: BGR/BGRA image; garments: [(type, BGRA image, landmarks)]. Layers, bottom to top (LAYER_ORDER):
    avatar -> pants (from their own waist row down) -> shoulder cap (only figure pixels above the T-shirt's top
    edge) -> T-shirt torso -> rigid sleeves (each once) -> the avatar's head/neck -> its hands/forearms.
    The realism effects are off by default (TRYON_SHADING / TRYON_CONTACT_SHADOW / TRYON_EDGE_FEATHER); the
    structural steps shoulder_cap / hem_snap / halo_removal are on by default (TRYON_SHOULDER_CAP / TRYON_HEM_SNAP
    / TRYON_HALO_REMOVAL, see flags.render_flags).

    Returns (BGR uint8 HxWx3 on white, warnings: [str], debug: dict).
    """
    base = cv2.resize(_bgra(base), (W, H))
    mask = figure_mask(base)
    canvas = base.copy()  # base alpha kept as is: forcing 255 inside the mask showed a grey halo at soft edges
    arms = find_arms(mask, body_lm)
    warnings, info = [], {}
    head = head_neck_overlay(mask, body_lm)
    by_type = {t: (img, lm) for t, img, lm in garments if t in ("tshirt", "pants")}
    layers = []
    if "pants" in by_type:
        warped, warns = garment_layer("pants", *by_type["pants"], body_lm, H, W, arms, info, mask,
                                      halo_removal=halo_removal)
        warnings += [f"pants: {w}" for w in warns]
        layers.append(("pants", warped))
    if "tshirt" in by_type:
        hem_over = None
        if hem_snap and "pants" in by_type:  # the hem overlaps the waistband: no gap line between them
            hem_over = info["pants_waist_y"] + info["pants_top_dip"] + HEM_OVER_WAISTBAND
        warped, warns = garment_layer("tshirt", *by_type["tshirt"], body_lm, H, W, arms, info, mask,
                                      halo_removal=halo_removal, hem_over=hem_over)
        warnings += [f"tshirt: {w}" for w in warns]
        if shoulder_cap:
            cap = shoulder_cap_layer(warped, mask, body_lm, head, info.get("tshirt_shoulders"))
            info["shoulder_cap"] = cap
            layers.append(("shoulder_cap", cap))
        layers.append(("tshirt", warped))
    for gtype, warped in layers:
        if edge_feather and gtype != "shoulder_cap":
            warped = soften_edges(warped)
        if shading:
            warped = apply_shading(warped, shading_map(base, mask & (warped[:, :, 3] > 0)), shading_strength)
        if contact_shadows and gtype != "shoulder_cap":
            dark = contact_shadow(warped[:, :, 3], mask, _crotch_x(body_lm))
            canvas[:, :, :3] = (canvas[:, :, :3].astype(np.float32) * (1 - dark[:, :, None])).astype(np.uint8)
        canvas = _alpha_composite(canvas, warped)

    head = head[:, :, None]  # head and neck always above the garment
    canvas = np.clip(np.rint(canvas.astype(np.float32) * (1 - head) + base.astype(np.float32) * head),
                     0, 255).astype(np.uint8)
    keep = arm_overlay_mask(mask, arms, info.get("sleeve_hems"))
    canvas[keep] = base[keep]
    for side in ("left", "right"):
        if not arms.get(side):
            warnings.append(f"arm {side}: not separated from the body in the mask, hands may be covered")

    white = np.full((H, W, 3), 255, np.float32)
    a = canvas[:, :, 3:4].astype(np.float32) / 255.0
    rgb = (canvas[:, :, :3].astype(np.float32) * a + white * (1 - a)).astype(np.uint8)
    return rgb, warnings, {"arms": arms, "arm_mask": keep, **info}
