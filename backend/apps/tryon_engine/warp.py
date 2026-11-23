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
LOOSE_FROM, LOOSE_FULL = 1.05, 1.15  # T-shirt garment/body width ratio: smoothstep tight -> loose
WAISTBAND_CURVE = 0.04  # waistband top edge dips by this fraction of the waist width at the centre
OPENING_COLOR_DIST = 40  # a hole whose colour is this close to the photo background is a real opening (kept)
ROW_STEP = 3  # dst px between control rows of the row warp
ROW_SMOOTH = 5  # control rows averaged per span edge (about 15 px): removes per-row jitter, keeps the silhouette
ROW_PAD = 3.0  # src px outside a (smoothed) span that still belong to the row: bumps of the real edge
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


def _warp_rows(src: np.ndarray, src_rows: list, dst_rows: list, H: int, W: int,
               pad: float = ROW_PAD) -> np.ndarray:
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


def _smooth_rows(rows: list, window: int = ROW_SMOOTH) -> list:
    """Rows (y, lx, rx) with lx/rx averaged over `window` neighbours (ends replicated). Silhouette spans read per
    row jitter by a pixel; unsmoothed, every oblique line inside the garment turns into stair steps."""
    if len(rows) < 3 or window < 2:
        return rows
    a = np.array(rows, np.float64)
    pad = window // 2
    k = np.ones(window) / window
    for c in (1, 2):
        a[:, c] = np.convolve(np.pad(a[:, c], pad, mode="edge"), k, mode="valid")
    return [tuple(r) for r in a]


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
NECK_FEATHER_FIX = 1.0  # px sigma in the neck zone with TRYON_NECK_FIX: an about 3 px (10-90 %) feathered edge
NECK_WALL = 3.0  # outside the neck the overlay's lower edge rises this many px per px (no vertical wall)
NECK_GAP_FEATHER = 0.8  # px sigma of the neck-gap fill edge (~2 px)
NECK_GAP_MIN_CHROMA = 0.45  # a pixel with less than this x the neck skin's Lab chroma is not skin (grey tank)
NECK_GAP_MAX_HUE = 30.0  # degrees of Lab hue from the neck skin beyond which a pixel is not skin
NECK_ZONE = 0.06  # neck zone = neck row .. shoulder row, +- this fraction of the figure height
OPENING_MAX_WIDTH = 0.58  # back-collar rim wider than this x the chest span is not a crew neck (V necks, lapels)
OPENING_MIN_WIDTH = 0.12
OPENING_DEPTH = 0.33  # inner opening depth below the rim top, x its width (crew neck, front lower than back)
OPENING_INSET = 0.1  # the opening is this share narrower than the rim on each side: the collar ring stays
OPENING_DARKER = 0.9  # the inner back must be darker than the collar ring under it by this factor (mean luminance)
OPENING_FEATHER = 0.7  # px sigma of the opening's edge (antialiased, ~1.5 px)
SHOULDER_SMOOTH = 1.5  # px sigma of the shoulder-edge alpha smoothing inside the neck zone
NECK_ARC = 0.25  # the overlay's lower edge dips by this x neck width at the centre (crew collar arc)
NECK_RISE = 0.3  # ... and rises by this x neck width above the neck row at the sides (U shape)
CAP_SAMPLE_ROWS = 12  # garment rows under the top edge whose median colours the shoulder cap
CAP_FEATHER = 0.7  # px sigma of the shoulder-cap fill edge (antialiased, ~1.5 px)
HEM_OVER_WAISTBAND = 6  # px the T-shirt hem reaches past the pants waistband top when it is snapped
HEM_GAP_MAX = 12  # only a hem at most this far above the pants waist is snapped (crop tops stay as they are)
SHOULDER_MAX_CHEST = 1.35  # garment shoulder span beyond this x chest span = marked on the sleeves, not the armholes
SHOULDER_OVER_CHEST = 0.12  # estimated armhole top: this x chest span outward of the armpit
SLEEVE_MERGED_TOL = 0.06  # x chest span: a run reaching further past the torso's side line is torso + sleeve
DROPPED_SHOULDER_RATIO = 0.60  # flat shoulder reach x s / avatar shoulder half-width above this: one-piece warp
#   (measured: #36 white oversized 0.67; #28 0.53, #17 0.50; threshold = midpoint; docs/09 #90)
DROPPED_FLAT_TOL = 0.03  # x shoulder span: top-edge rows within this of the highest centre pixel count as "flat"
SINGLE_BEND_BAND = 0.5  # x armhole length: outward of the armhole the torso map bends into the sleeve map over this
SINGLE_UNDERARM_ROWS = 10  # below the armpit row the bend edge moves from the armpit point to the torso edge
SLEEVE_CLIP_RADIUS = 1.0  # x armhole length: the shoulder-line clip acts within this distance of the shoulder point
SLEEVE_OVERLAP = 3  # src px the rigid sleeve reaches past its armhole line over the torso (no seam gap)
CAP_MAX_DEPTH = 0.03  # shoulder cap: at most this fraction of the figure height below the collar top
HALO_ERODE = 2  # px removed from the garment's alpha edge (photo background fringe)
PRESCALE_BELOW = 0.8  # garments that would be shrunk more than this are area-resampled to their final size first


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
                mask: np.ndarray | None = None, hem_over: float | None = None,
                under: np.ndarray | None = None, dropped_single: bool = False,
                hem_rule: tuple[float, float] | None = None) -> tuple[np.ndarray, list]:
    """T-shirt keeps its own silhouette (docs/06 "T-shirt fit"): one uniform scale s for both axes, set so the
    garment's shoulder line = body shoulder + ease; below the shoulders every row is max(garment, body + ease)
    (capped), blended in from the shoulder fit by the chest row; the hem is the garment's own (scaled) length.

    Three clipped pieces, each garment pixel in exactly one (docs/06 "Layer order"): the TORSO (row warp of the
    garment without its sleeve regions) and two rigid SLEEVES (uniform s + rotation onto the upper arm, drawn once,
    SLEEVE_OVERLAP px over the torso). hem_over: a row the hem must reach when it ends at most HEM_GAP_MAX px
    above it (the pants top): the rows below the chest are stretched by those few px, nothing is repeated.
    under: bool mask of what is worn under the T-shirt (the pants layer): rows that overlap it are at least as wide
    (a T-shirt hangs over the waistband, the waistband never shows beside it).
    dropped_single (TRYON_DROPPED_SHOULDER_SINGLE): a dropped-shoulder garment (`dropped_shoulder_ratio` above
    DROPPED_SHOULDER_RATIO) is warped as ONE piece (`_single_piece`) instead of torso + rigid sleeves.
    hem_rule (TRYON_HEM_RULE): (hip fraction, crotch margin px). The hem lands on `body_hem_y` whatever the
    garment's own length: uniform scale s down to the chest row (aligned with the sleeves), then the chest -> hem
    rows are stretched or squeezed (never cut, never repeated). Hem snap and the crotch cut are then not used."""
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
    if hem_rule is not None:  # the garment's real bottom edge (trims below the hem landmark) is what lands on the
        # body's hem row: the same rows _tail_rows would add, at most 8 % of the garment height
        x0, x1 = max(int(_f(g["hem"]["left_x"])), 0), max(int(np.ceil(_f(g["hem"]["right_x"]))), 1)
        below = np.nonzero(alpha[int(g_hem):, x0:x1].any(axis=1))[0]
        if len(below):
            # sampled at pixel centres: the last pixel's 50 % alpha edge is at its row + 0.5 (stays sharp when stretched)
            g_hem = min(g_hem + min(float(below[-1]) + 0.5 - (g_hem - int(g_hem)), 0.08 * gh), gh - 1.0)
    hem_y = to_dst(g_hem)  # the garment's own length: crop tops stay short
    hem_max = _f(a["crotch"]["y"]) + MAX_SHIRT_BELOW_CROTCH * (_f(a["knee"]["y"]) - _f(a["crotch"]["y"]))
    cut_hem = hem_y > hem_max and hem_rule is None
    if cut_hem:  # cut, never squeeze
        warnings.append(f"hem: garment is {hem_y - hem_max:.0f} px too long for this body, cut at the limit")
        hem_y = hem_max
        g_hem = g_sy + (hem_y - a_sy) / s
    chest_dst = to_dst(_f(g["chest"]["y"]))
    knot = min(chest_dst, hem_y - 1.0)  # the vertical scale is s down to here; below it the hem may be snapped
    hem_own = hem_y
    if hem_rule is not None:  # the body's hem row (TRYON_HEM_RULE): the garment's length is fitted to it
        hem_y = body_hem_y(a, *hem_rule) + HALO_ERODE  # the edge fix takes HALO_ERODE px off the bottom edge
        knot = min(chest_dst, hem_y - 1.0)
    elif hem_over is not None and 0 <= hem_over - HEM_OVER_WAISTBAND - hem_y <= HEM_GAP_MAX + 0.04 * (a_sr - a_sl) \
            and hem_over <= hem_max:
        hem_y = hem_over
    g_knot = g_sy + (knot - a_sy) / s
    v_stretch = (hem_y - knot) / max(hem_own - knot, 1.0)  # 1 unless snapped or fitted by the hem rule
    if hem_rule is not None and abs(v_stretch - 1) > 0.25:
        warnings.append(f"hem: garment length fitted to the body ({'stretched' if v_stretch > 1 else 'squeezed'}"
                        f" {max(v_stretch, 1 / v_stretch):.2f}x below the chest)")

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

    t_alpha = alpha & torso_keep  # the torso's own pixels: its row spans
    # the torso samples a few px past its armhole line: its clipped edge then lies inside the sleeve's territory
    # (replaced there), never on the visible join
    k = 2 * SLEEVE_OVERLAP + 1
    torso_img = img.copy()
    torso_img[:, :, 3] = np.where(cv2.dilate(torso_keep.astype(np.uint8), np.ones((k, k), np.uint8)) > 0,
                                  img[:, :, 3], 0)

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
                # + HALO_ERODE: the edge fix on the composited layer takes that much off the outer contour
                half = max(half, c - (run[0] - 2 - HALO_ERODE), run[1] + 3 + HALO_ERODE - c)
        if under is not None:
            run = next((q for q in _runs(under[min(int(y), H - 1)]) if q[0] <= axis <= q[1]), None)
            if run and run[1] - run[0] < PANTS_MAX_BODY * bw:
                half = max(half, c - (run[0] - 1 - HALO_ERODE), run[1] + 2 + HALO_ERODE - c)
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
    n_collar = len(src_rows) - len(torso)
    src_rows[n_collar:], dst_rows[n_collar:] = _smooth_rows(src_rows[n_collar:]), _smooth_rows(dst_rows[n_collar:])
    if not cut_hem and hem_rule is None:  # with the hem rule the bottom edge is already the last row
        _tail_rows(t_alpha, src_rows, dst_rows, s * v_stretch)
    torso_layer = _warp_rows(torso_img, src_rows, dst_rows, H, W)

    # ---- sleeves: hard per-pixel ownership. The sleeve's territory is its `draw` region mapped by its rigid
    # transform (threshold 0.5, no feather) and clipped below the torso's shoulder slope line. Inside it only the
    # sleeve is drawn, sampled from the WHOLE garment image (so its alpha is the garment's own: opaque across the
    # join, no clipped soft edge); outside it only the torso. Each pixel comes from exactly one piece: no doubled
    # contour, no lightness dip along the join.
    result = torso_layer.copy()
    parts = {}
    lines, owned = {}, np.zeros((H, W), bool)
    py, px = np.mgrid[0:H, 0:W].astype(np.float32) + 0.5
    k5 = np.ones((5, 5), np.uint8)
    for side, (M, draw, S_dst, A_dst) in sleeves.items():
        m, c = shoulder_slope_line(torso_layer[:, :, 3], side, S_dst, a_cx, a_sy, a_sr - a_sl)
        lines[side] = (m, c)
        above = np.clip((m * px + c) - py + 0.5, 0, 1)  # antialiased: 1 above the line, 0 below it
        # only around the shoulder (a rotated sleeve's top corner): far down the arm the line says nothing
        R = SLEEVE_CLIP_RADIUS * float(np.linalg.norm(np.asarray(A_dst) - np.asarray(S_dst)))
        r = np.hypot(px - S_dst[0], py - S_dst[1])
        near = np.clip((1.4 * R - r) / max(0.4 * R, 1e-6), 0, 1)
        cover = 1 - above * near
        # territory: the sleeve's own garment pixels (+2 px for its soft edge), mapped by its rigid transform
        own_px = draw & (cv2.dilate((img[:, :, 3] > 0).astype(np.uint8), k5) > 0)
        terr = (cv2.warpAffine(own_px.astype(np.float32), M, (W, H), flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=0) >= 0.5) & (cover > 0)
        piece = _warp_affine_premultiplied(img, M, W, H)
        piece[:, :, 3] = np.where(terr, np.rint(piece[:, :, 3] * cover), 0).astype(np.uint8)
        parts[f"sleeve_{side}"] = piece
        # outward of the armhole line only the sleeve exists (its contour is drawn once); inward of it (the
        # overlap band, the underarm) the sleeve is drawn over the torso: across the join both are opaque (same
        # source pixels, no alpha ramp, no gap) and the torso's side stays under the sleeve's underarm edge
        t = np.asarray(A_dst, np.float64) - np.asarray(S_dst, np.float64)
        nrm = np.array([t[1], -t[0]]) / max(float(np.linalg.norm(t)), 1e-6)
        if (nrm[0] > 0) == (side == "left"):
            nrm = -nrm
        outward = ((px - S_dst[0]) * nrm[0] + (py - S_dst[1]) * nrm[1] > 0) & (py <= A_dst[1])
        result[terr & outward] = piece[terr & outward]
        inner = terr & ~outward
        result[inner] = _alpha_composite(result[inner][None], piece[inner][None])[0]
        owned |= terr & (outward | (piece[:, :, 3] >= 250))
    torso_drawn = torso_layer.copy()
    torso_drawn[owned] = 0  # replaced by the sleeve or hidden under an opaque sleeve pixel: drawn once
    parts = {"torso": torso_drawn, **parts}
    ratio = dropped_shoulder_ratio(alpha, g)
    single = dropped_single and ratio > DROPPED_SHOULDER_RATIO and bool(sleeves)
    if single:  # one continuous warp: the shoulder slope runs into the sleeves, no second layer, no underarm tab
        result = _single_piece(img, src_rows, dst_rows, sleeves, a_cx, s, H, W)
        parts = {"single": result}
    if info is not None:
        info["sleeve_hems"] = hems
        info["tshirt_rows"] = torso
        info["tshirt_hem"] = torso[-1]
        info["tshirt_parts"] = parts
        info["shoulder_lines"] = lines
        info["dropped_shoulder"] = {"ratio": ratio, "single": single}
        info["sleeve_transforms"] = {side: v[0] for side, v in sleeves.items()}
        info["armhole_lines"] = {side: (v[2], v[3]) for side, v in sleeves.items()}
        info["tshirt_shoulders"] = (float(shoulders["left"][0]), float(shoulders["right"][0]))
        geo = back_collar_geometry(alpha, g, img)  # garment coordinates -> the collar mapping used for the rows above
        if geo:  # the shoulder line (same uniform scale, centred on the body)
            info["neck_opening"] = {"cx": a_cx + (geo["cx"] - g_cx) * s, "hw": geo["hw"] * s, "y0": to_dst(geo["y0"]),
                                    "depth": geo["depth"] * s}
    return result, warnings


def shoulder_slope_line(torso_alpha: np.ndarray, side: str, S_dst, cx: float, sy: float,
                        shoulder_w: float) -> tuple[float, float]:
    """(m, c) of the torso's shoulder slope line y = m * x + c on one side (dst px), fitted to the torso layer's
    top edge over the outer half of the shoulder (between 15 % and 60 % of the way from the shoulder point to the
    centre; the collar is not part of it). The rigid sleeve is clipped below this line, so its top edge continues
    the torso's slope and never rises above it (no shoulder 'pad'). Fallback: through the shoulder point, flat."""
    xs_ = S_dst[0] + np.array([0.15, 0.6]) * (cx - S_dst[0])
    x0, x1 = int(np.ceil(min(xs_))), int(np.floor(max(xs_)))
    lo, hi = max(int(sy - 0.3 * shoulder_w), 0), min(int(sy + 0.2 * shoulder_w), torso_alpha.shape[0])
    pts = []
    for x in range(max(x0, 0), min(x1 + 1, torso_alpha.shape[1])):
        col = np.nonzero(torso_alpha[lo:hi, x] >= 128)[0]
        if len(col):
            pts.append((x + 0.5, lo + col[0]))
    if len(pts) < 5:
        return 0.0, float(S_dst[1])
    xs, ys = np.array(pts, np.float64).T
    m, c = np.polyfit(xs, ys, 1)
    return float(m), float(c)


def body_hem_y(lm: dict, hip_fraction: float, crotch_margin: float) -> float:
    """The body's T-shirt hem row (TRYON_HEM_RULE; bodies have no hem landmark): hip + hip_fraction x (crotch - hip),
    never lower than crotch - crotch_margin."""
    hip, crotch = _f(lm["hip"]["y"]), _f(lm["crotch"]["y"])
    return min(hip + hip_fraction * (crotch - hip), crotch - crotch_margin)


def dropped_shoulder_ratio(alpha: np.ndarray, g: dict) -> float:
    """How far the garment's high, flat shoulder line reaches from the centre, relative to its shoulder half-width,
    times (1 + ease): at the T-shirt's uniform scale this is that reach over the avatar's shoulder half-width
    (scale-free, so the same for every avatar). Flat = top-edge pixel within DROPPED_FLAT_TOL x shoulder span of the
    highest one near the centre, contiguous from the centre. A dropped-shoulder garment (#36) keeps its top line far
    out to the seam; a set-in sleeve slopes down from the collar."""
    sl, sr = _f(g["shoulder"]["left_x"]), _f(g["shoulder"]["right_x"])
    if sr - sl < 4:
        return 0.0
    top = np.where(alpha.any(axis=0), alpha.argmax(axis=0), 10 ** 6)
    mid = int(round((sl + sr) / 2))
    near = top[max(mid - 10, 0):mid + 11]
    if not len(near) or near.min() >= 10 ** 6:
        return 0.0
    tol = DROPPED_FLAT_TOL * (sr - sl)
    flat = top <= near.min() + tol
    a = b = mid
    while a > 0 and flat[a - 1]:
        a -= 1
    while b < len(flat) - 1 and flat[b + 1]:
        b += 1
    return (b - a + 1) / 2.0 / ((sr - sl) / 2.0) * (1 + TSHIRT_EASE)


def _row_inverse(src_rows: list, dst_rows: list, H: int, W: int, s: float):
    """(map_x, map_y, valid) of the torso row warp, inverse, for every dst pixel (also outside the span: the row's
    linear map continued). Rows above the first control row continue at the uniform scale; below the last one
    nothing (valid False)."""
    order = np.argsort([r[0] for r in dst_rows], kind="stable")
    d = np.array([dst_rows[i] for i in order], np.float64)
    g = np.array([src_rows[i] for i in order], np.float64)
    keep = np.concatenate([[True], np.diff(d[:, 0]) > 1e-6])
    d, g = d[keep], g[keep]
    ys = np.arange(H, dtype=np.float64)
    l, r = np.interp(ys, d[:, 0], d[:, 1]), np.interp(ys, d[:, 0], d[:, 2])
    sy = np.interp(ys, d[:, 0], g[:, 0])
    sl, sr = np.interp(ys, d[:, 0], g[:, 1]), np.interp(ys, d[:, 0], g[:, 2])
    up = ys < d[0, 0]
    sy[up] = g[0, 0] + (ys[up] - d[0, 0]) / s
    scale = (sr - sl) / np.maximum(r - l, 1e-6)
    xs = np.arange(W, dtype=np.float64) + 0.5
    map_x = sl[:, None] + (xs[None, :] - l[:, None]) * scale[:, None] - 0.5
    map_y = np.repeat(sy[:, None], W, axis=1)
    valid = np.repeat((ys <= d[-1, 0])[:, None], W, axis=1)
    return map_x, map_y, valid, l, r


def _single_piece(img: np.ndarray, src_rows: list, dst_rows: list, sleeves: dict, cx: float, s: float,
                  H: int, W: int) -> np.ndarray:
    """The whole T-shirt as ONE continuous warp (dropped shoulders, docs/06 "Dropped shoulders"): every dst pixel
    samples the garment once, through an inverse map that is the torso row map inward of the armhole line and bends
    smoothly (smoothstep over SINGLE_BEND_BAND x armhole length, outward) into the sleeve's rigid map. Below the
    armpit row the bend edge is the torso's own edge (reached over SINGLE_UNDERARM_ROWS rows), so the sleeve's inner
    bottom corner never passes the torso edge: inward of it only the torso map exists."""
    tx, ty, tvalid, l_rows, r_rows = _row_inverse(src_rows, dst_rows, H, W, s)
    py, px = np.mgrid[0:H, 0:W].astype(np.float64)
    map_x, map_y = tx.copy(), ty.copy()
    wsum = np.zeros((H, W), np.float64)
    for side, (M, _, S_dst, A_dst) in sleeves.items():
        S, A = np.asarray(S_dst, np.float64), np.asarray(A_dst, np.float64)
        t = A - S
        length = max(float(np.linalg.norm(t)), 1e-6)
        nrm = np.array([t[1], -t[0]]) / length
        if (nrm[0] > 0) == (side == "left"):
            nrm = -nrm
        delta = (px + 0.5 - S[0]) * nrm[0] + (py + 0.5 - S[1]) * nrm[1]  # outward of the armhole line
        edge_rows = l_rows if side == "left" else r_rows
        k = np.clip((np.arange(H) - A[1]) / SINGLE_UNDERARM_ROWS, 0, 1)
        e = A[0] + k * (edge_rows - A[0])  # bend edge below the armpit row: armpit point -> torso edge
        below = (px + 0.5 - e[:, None]) * (-1.0 if side == "left" else 1.0)
        delta = np.where(py + 0.5 > A[1], below, delta)
        half = (px + 0.5 < cx) if side == "left" else (px + 0.5 >= cx)
        u = np.clip(delta / (SINGLE_BEND_BAND * length), 0, 1)
        w = np.where(half, u * u * (3 - 2 * u), 0.0)
        Minv = cv2.invertAffineTransform(M).astype(np.float64)
        sx = Minv[0, 0] * px + Minv[0, 1] * py + Minv[0, 2]
        sy = Minv[1, 0] * px + Minv[1, 1] * py + Minv[1, 2]
        map_x = map_x * (1 - w) + sx * w
        map_y = map_y * (1 - w) + sy * w
        wsum += w
    ok = tvalid | (wsum >= 1 - 1e-9)  # below the torso rows: only where the sleeve map alone applies
    map_x = np.where(ok, map_x, -10.0).astype(np.float32)
    map_y = np.where(ok, map_y, -10.0).astype(np.float32)
    f = img.astype(np.float32)
    f[:, :, :3] *= f[:, :, 3:4] / 255.0
    out = cv2.remap(f, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    a = out[:, :, 3:4] / 255.0
    out[:, :, :3] = np.where(a > 0, out[:, :, :3] / np.maximum(a, 1e-6), 0)
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def tshirt_scale(g: dict, a: dict) -> float:
    """The T-shirt's one uniform scale: garment shoulder line -> body shoulder line + ease."""
    return (_f(a["shoulder"]["right_x"]) - _f(a["shoulder"]["left_x"])) * (1 + TSHIRT_EASE) / \
        (_f(g["shoulder"]["right_x"]) - _f(g["shoulder"]["left_x"]))


def back_collar_geometry(alpha: np.ndarray, g: dict, img: np.ndarray | None = None) -> dict | None:
    """Garment coordinates of the inner back collar of a crew neck, or None. A ghost-mannequin photo shows the
    inside of the back of the collar through the neck hole: dark fabric between the back rim (the garment's flat
    top edge, found as the run of columns whose top pixel is within 3 px of the highest one, around the centre) and
    the front neckline below it (modelled as a half ellipse OPENING_DEPTH x the rim width deep). Returns
    {cx, hw, y0, depth}; None if the rim is not crew-neck sized (V necks, lapels: nothing is removed) or, when the
    image is given, if the inside is not clearly darker than the ring below it (nothing to tell them apart)."""
    chest_w = _f(g["chest"]["right_x"]) - _f(g["chest"]["left_x"])
    cx0 = (_f(g["shoulder"]["left_x"]) + _f(g["shoulder"]["right_x"])) / 2
    lo, hi = max(int(cx0 - 0.5 * chest_w), 0), min(int(cx0 + 0.5 * chest_w) + 1, alpha.shape[1])
    if hi - lo < 10:
        return None
    sub = alpha[:, lo:hi]
    has = sub.any(axis=0)
    top = np.where(has, sub.argmax(axis=0), 10 ** 6)
    mid = (hi - lo) // 2
    y_top = int(top[max(mid - int(0.1 * chest_w), 0):mid + int(0.1 * chest_w) + 1].min())
    if y_top >= 10 ** 6:
        return None
    flat = top <= y_top + 3
    a = b = mid
    while a > 0 and flat[a - 1]:
        a -= 1
    while b < len(flat) - 1 and flat[b + 1]:
        b += 1
    width = b - a + 1
    if not OPENING_MIN_WIDTH * chest_w <= width <= OPENING_MAX_WIDTH * chest_w:
        return None
    geo = {"cx": lo + (a + b) / 2.0 + 0.5, "hw": width / 2.0 * (1 - OPENING_INSET), "y0": float(y_top),
           "depth": OPENING_DEPTH * width}
    if img is not None:  # a solid block of one colour has no inner back to remove: it must be darker than the ring
        lum = cv2.cvtColor(np.ascontiguousarray(img[:, :, :3]), cv2.COLOR_BGR2GRAY).astype(np.float32)
        yy, xx = np.mgrid[0:alpha.shape[0], 0:alpha.shape[1]].astype(np.float32)
        ex, ey = (xx + 0.5 - geo["cx"]) / geo["hw"], (yy + 0.5 - geo["y0"]) / geo["depth"]
        inside = (ex * ex + ey * ey <= 0.64) & (yy >= geo["y0"]) & alpha
        ring = (ey > 1.1) & (ey < 1.1 + 0.35) & (np.abs(ex) <= 0.8) & alpha
        if inside.sum() < 20 or ring.sum() < 20 or lum[inside].mean() > OPENING_DARKER * lum[ring].mean():
            return None
    return geo


def neck_zone_rows(lm: dict, H: int) -> tuple[int, int]:
    """First and last row of the neck zone: neck row .. shoulder row, +- NECK_ZONE of the figure height."""
    fig_h = _f(lm.get("foot_bottom", {}).get("y", H - 50)) - _f(lm.get("head_top", {}).get("y", 50))
    return (max(int(_f(lm["neck"]["y"]) - NECK_ZONE * fig_h), 0),
            min(int(_f(lm["shoulder"]["y"]) + NECK_ZONE * fig_h), H - 1))


def clear_back_collar(layer: np.ndarray, opening: dict | None, lm: dict) -> np.ndarray:
    """T-shirt layer with its inner back collar made transparent (alpha only; RGB and the avatar are untouched):
    the avatar's own neck shows through. The region is the column + half ellipse of `opening` (dst px) inside the neck zone,
    antialiased by OPENING_FEATHER. Everything outside the neck zone rows is returned unchanged."""
    if not opening or "neck" not in lm:
        return layer
    H, W = layer.shape[:2]
    z0, z1 = neck_zone_rows(lm, H)
    yy, xx = np.mgrid[z0:z1 + 1, 0:W].astype(np.float32)
    ex = (xx + 0.5 - opening["cx"]) / max(opening["hw"], 1e-6)
    ey = (yy + 0.5 - opening["y0"]) / max(opening["depth"], 1e-6)
    # a column above the rim top line (the rim itself belongs to the opening) + the half ellipse below it
    rim = 1.0 / (1 - OPENING_INSET)  # the full rim width: its top lip (ey <= 0.1) belongs to the opening
    inside = ((np.abs(ex) <= rim) & (ey <= 0.1)) | ((np.abs(ex) <= 1.0) & ((ey <= 0) | ((ex * ex + ey * ey) <= 1.0)))
    soft = cv2.GaussianBlur(inside.astype(np.float32), (0, 0), OPENING_FEATHER)
    soft = np.where(inside, np.maximum(soft, 0.5 + 0.5 * soft), soft)  # the inside is cleared at least half
    out = layer.copy()
    out[z0:z1 + 1, :, 3] = np.clip(np.rint(layer[z0:z1 + 1, :, 3] * (1 - np.clip(soft, 0, 1))), 0, 255).astype(np.uint8)
    return out


def smooth_shoulder_alpha(layer: np.ndarray, lm: dict) -> np.ndarray:
    """T-shirt layer whose alpha edge inside the neck zone rows is smoothed: the binary mask is blurred
    (SHOULDER_SMOOTH) and thresholded with a ~1.5 px antialiased ramp, which removes the 1 px stair steps of the
    shoulder slope. Pixels that become visible take the colour of the nearest solid garment pixel; the solid
    interior (alpha 255 two px away from an edge) and everything outside the zone rows are untouched."""
    H, W = layer.shape[:2]
    z0, z1 = neck_zone_rows(lm, H)
    a = layer[z0:z1 + 1, :, 3]
    if not a.any():
        return layer
    soft = cv2.GaussianBlur((a > 127).astype(np.float32), (0, 0), SHOULDER_SMOOTH)
    smooth = np.clip((soft - 0.5) * 2.5 + 0.5, 0, 1) * 255
    interior = cv2.erode((a >= 250).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    new = np.where(interior, a, np.rint(smooth)).astype(np.uint8)
    out = layer.copy()
    out[z0:z1 + 1, :, 3] = new
    grown = np.zeros((H, W), bool)
    grown[z0:z1 + 1] = (new > 0) & (a < 250)
    grown &= layer[:, :, 3] < 250
    if grown.any():  # colour: local mean of the solid garment pixels around (a single stitch cannot dominate)
        ok = (layer[:, :, 3] >= 250).astype(np.float32)
        num = cv2.GaussianBlur(layer[:, :, :3].astype(np.float32) * ok[:, :, None], (0, 0), 2.0)
        den = cv2.GaussianBlur(ok, (0, 0), 2.0)
        mean = np.where(den[:, :, None] > 0.05, num / np.maximum(den, 1e-6)[:, :, None], 0)
        has = grown & (den > 0.05)
        out[:, :, :3][has] = np.clip(np.rint(mean[has]), 0, 255).astype(np.uint8)
        _colour_from_nearest_opaque(out, grown & ~has, ok=ok > 0)
    return out


def head_neck_overlay(base_mask: np.ndarray, lm: dict, feather: float = NECK_FEATHER,
                      opening: dict | None = None) -> np.ndarray:
    """HxW float weight (0..1) of the avatar's head and neck drawn ON TOP of the garment: figure pixels above one
    smooth lower edge, feathered. The edge is a U (half ellipse: NECK_ARC x neck width below the `neck` row at the
    centre, rising NECK_RISE x neck width above it at the neck + NECK_MARGIN sides, like a crew collar that wraps
    the neck) that continues upward outside the neck at NECK_WALL px per px: no vertical wall, so no step or
    rectangular corner where the collar meets it. With the T-shirt's `opening` (neck fix) the edge stays at
    least 1 px above the inner edge of the front collar band: the band stays visible. Ghost-mannequin back
    collars never cover the head."""
    n = lm.get("neck")
    out = np.zeros(base_mask.shape, np.float32)
    if not n:
        return out
    H, W = base_mask.shape
    lx, rx = _f(n["left_x"]) - NECK_MARGIN, _f(n["right_x"]) + NECK_MARGIN
    cx, half = (lx + rx) / 2, max((rx - lx) / 2, 1.0)
    nw = _f(n["right_x"]) - _f(n["left_x"])
    depth, rise = NECK_ARC * nw, NECK_RISE * nw
    xs = np.arange(W, dtype=np.float32) + 0.5
    u = np.abs(xs - cx) / half
    bottom = np.where(u <= 1, _f(n["y"]) - rise + (depth + rise) * np.sqrt(np.clip(1 - u * u, 0, 1)),
                      _f(n["y"]) - rise - (u - 1) * half * NECK_WALL)
    if opening:
        ex = (xs - opening["cx"]) / max(opening["hw"], 1e-6)
        front = opening["y0"] + opening["depth"] * np.sqrt(np.clip(1 - ex * ex, 0, 1)) - 1.0
        bottom = np.where(np.abs(ex) < 1, np.minimum(bottom, front), bottom)
    yy = np.arange(H, dtype=np.float32)[:, None] + 0.5
    out[:] = np.clip(bottom[None, :] - yy + 0.5, 0, 1)  # antialiased curve
    out = cv2.GaussianBlur(out, (0, 0), feather)
    return out * base_mask


def neck_gap_fill_fn(canvas: np.ndarray, base: np.ndarray, mask: np.ndarray, lm: dict, head: np.ndarray,
                  tshirt_alpha: np.ndarray, opening: dict | None) -> tuple[np.ndarray, np.ndarray]:
    """(canvas, weight): the avatar's own non-skin pixels (a tank collar) left visible between the head/neck
    overlay and the T-shirt's collar are painted in the skin colour of the avatar's neck centre, feathered
    NECK_GAP_FEATHER. Only inside the neck columns (the T-shirt's opening rim, else the neck + NECK_MARGIN),
    from the neck zone top to the shoulder row, on the figure, where neither the head overlay nor the garment is."""
    n = lm.get("neck")
    H, W = mask.shape
    weight = np.zeros((H, W), np.float32)
    if not n:
        return canvas, weight
    nw = _f(n["right_x"]) - _f(n["left_x"])
    ncx, ny = (_f(n["left_x"]) + _f(n["right_x"])) / 2, _f(n["y"])
    box = base[max(int(ny - 0.4 * nw), 0):max(int(ny - 0.1 * nw), 1),
               max(int(ncx - 0.15 * nw), 0):int(ncx + 0.15 * nw) + 1]
    box_m = mask[max(int(ny - 0.4 * nw), 0):max(int(ny - 0.1 * nw), 1),
                 max(int(ncx - 0.15 * nw), 0):int(ncx + 0.15 * nw) + 1]
    if not box_m.any():
        return canvas, weight
    skin = np.median(box[:, :, :3][box_m], axis=0).astype(np.uint8)
    if opening:
        rim = opening["hw"] / (1 - OPENING_INSET) + 2
        x0, x1 = opening["cx"] - rim, opening["cx"] + rim
    else:
        x0, x1 = _f(n["left_x"]) - NECK_MARGIN, _f(n["right_x"]) + NECK_MARGIN
    z0, _ = neck_zone_rows(lm, H)
    region = np.zeros((H, W), bool)
    region[z0:int(_f(lm["shoulder"]["y"])) + 1, max(int(np.floor(x0)), 0):min(int(np.ceil(x1)) + 1, W)] = True
    region &= mask & (head < 0.5) & (tshirt_alpha < 128)
    if not region.any():
        return canvas, weight
    gap = region & ~skin_like(base, skin)
    if not gap.any():
        return canvas, weight
    weight = np.maximum(cv2.GaussianBlur(gap.astype(np.float32), (0, 0), NECK_GAP_FEATHER), gap) * mask
    weight *= tshirt_alpha < 250  # never over the garment's solid pixels
    top = np.zeros_like(canvas)
    top[:, :, :3] = skin
    top[:, :, 3] = np.clip(np.rint(weight * 255), 0, 255).astype(np.uint8)
    return _alpha_composite(canvas, top), weight


def skin_like(img: np.ndarray, skin) -> np.ndarray:
    """Bool mask of pixels with the skin's colour (hue and chroma in Lab, brightness ignored: a shadow under the
    chin is still skin). A grey tank collar has almost no chroma; a coloured top has another hue."""
    lab = cv2.cvtColor(np.ascontiguousarray(img[:, :, :3]), cv2.COLOR_BGR2LAB).astype(np.float32)
    ref = cv2.cvtColor(np.asarray(skin, np.uint8).reshape(1, 1, 3), cv2.COLOR_BGR2LAB).astype(np.float32)[0, 0]
    a, b = lab[:, :, 1] - 128, lab[:, :, 2] - 128
    ra, rb = ref[1] - 128, ref[2] - 128
    chroma, rchroma = np.hypot(a, b), max(float(np.hypot(ra, rb)), 1e-6)
    cos = (a * ra + b * rb) / np.maximum(chroma * rchroma, 1e-6)
    return (chroma >= NECK_GAP_MIN_CHROMA * rchroma) & (cos >= np.cos(np.radians(NECK_GAP_MAX_HUE)))


def shoulder_cap_layer(tshirt: np.ndarray, figure: np.ndarray, lm: dict, head: np.ndarray,
                       shoulders: tuple | None, skip: tuple | None = None) -> np.ndarray:
    """BGRA layer of the two shoulder caps, drawn UNDER the T-shirt (it shows only where the garment does not):
    a small clipped polygon per side, between the collar (the garment's highest top-edge pixel on that side, or
    the neck + NECK_MARGIN if that is further in) and the shoulder point; from the garment's top edge up by at
    most CAP_MAX_DEPTH of the figure height, never above the collar top; figure pixels only, never the head.
    Colour: per column the median of the garment's solid pixels 3..3 + CAP_SAMPLE_ROWS rows under its top edge
    (the adjacent shoulder rows; the fringe is skipped), median-filtered along the shoulder; never the skin.
    skip: columns (x0, x1) the cap never covers (the opened neckline with TRYON_NECK_FIX: the skin shows there)."""
    H, W = figure.shape
    out = np.zeros_like(tshirt)
    opaque = tshirt[:, :, 3] >= 250
    cols = opaque.any(axis=0)
    if shoulders is None or not cols.any():
        return out
    top = np.where(cols, opaque.argmax(axis=0), H)
    fig_h = _f(lm.get("foot_bottom", {}).get("y", H - 50)) - _f(lm.get("head_top", {}).get("y", 50))
    depth = int(round(CAP_MAX_DEPTH * fig_h))
    # colour of the adjacent shoulder row, per column
    colour = np.full((W, 3), np.nan, np.float32)
    for x in np.nonzero(cols)[0]:
        y0 = int(top[x]) + 3
        seg = tshirt[y0:y0 + CAP_SAMPLE_ROWS, x]
        ok = seg[:, 3] >= 250
        if ok.any():
            colour[x] = np.median(seg[ok, :3], axis=0)
    valid = ~np.isnan(colour[:, 0])
    if not valid.any():
        return out
    xs_all = np.arange(W)
    for ch in range(3):
        colour[:, ch] = np.interp(xs_all, xs_all[valid], colour[valid, ch])
    # median along the shoulder (a thin stitch or print line is not the shoulder's colour), then a light blur
    colour = cv2.medianBlur(np.clip(np.rint(colour), 0, 255).astype(np.uint8).reshape(1, W, 3), 9)
    colour = cv2.GaussianBlur(colour.astype(np.float32), (0, 0), 2.0).reshape(W, 3)
    n = lm.get("neck")
    cx = (shoulders[0] + shoulders[1]) / 2
    region = np.zeros((H, W), bool)
    for side, x0, x1 in (("left", shoulders[0], cx), ("right", cx, shoulders[1])):
        xs = np.arange(max(int(np.floor(x0)), 0), min(int(np.ceil(x1)) + 1, W))
        xs = xs[cols[xs]]
        if not len(xs):
            continue
        peak = int(xs[np.argmin(top[xs])])
        y_top = int(top[peak])
        if n:  # the collar side: the peak, or the neck side + margin if that lies further in
            inner = _f(n["left_x"]) - NECK_MARGIN if side == "left" else _f(n["right_x"]) + NECK_MARGIN
            peak = min(peak, int(inner)) if side == "left" else max(peak, int(np.ceil(inner)))
        for x in (xs[xs <= peak] if side == "left" else xs[xs >= peak]):
            y1 = int(top[x])
            y0 = max(y_top, y1 - depth)
            if y1 > y0:
                region[y0:y1 + 3, x] = True  # 3 px under the garment's top edge: no gap at the join
    if skip:
        region[:, max(int(np.floor(skip[0])), 0):max(int(np.ceil(skip[1])) + 1, 0)] = False
    region &= figure & (head < 0.5)
    soft = np.maximum(cv2.GaussianBlur(region.astype(np.float32), (0, 0), CAP_FEATHER), region)
    soft[~(cv2.dilate(region.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0)] = 0
    out[:, :, :3] = np.clip(np.rint(colour), 0, 255).astype(np.uint8)[None, :, :]
    out[:, :, 3] = np.clip(np.rint(soft * 255 * figure), 0, 255).astype(np.uint8)
    return out


PANTS_EASE = 0.04  # pants cover the body with ~4% ease (no skin/underwear showing)
PANTS_MAX_BODY = 1.8  # a pants row is never wider than this times the body
PANTS_DISTORT_LIMIT = 1.3  # warn when a row's horizontal scale differs from the uniform scale by more


def _smooth(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def pants_width(garment_w: float, body_w: float, ease: float = PANTS_EASE, cap: float = PANTS_MAX_BODY,
                cap_ref: float | None = None) -> float:
    """The garment's own (uniformly scaled) width, but at least the body plus ease so nothing shows through, and at
    most `cap` times `cap_ref` (default: the body width of the row). Used by the parts T-shirt's torso rows
    (tshirt_row_width); pants have their own model since round 26 (warp_pants)."""
    if body_w <= 0:
        return garment_w
    ref = max(body_w, cap_ref or 0)
    return min(max(garment_w, body_w * (1 + ease)), ref * cap)


def waist_blend_width(garment_w: float, body_w: float, t: float, ease: float = PANTS_EASE) -> float:
    """From t=0 (the body + ease) to t=1 (pants_width) by smoothstep: the parts T-shirt's shoulder -> torso rows."""
    k = _smooth(t)
    return (1 - k) * body_w * (1 + ease) + k * pants_width(garment_w, body_w, ease)


def _ys(y0: float, y1: float, step: int = 6) -> list[float]:
    ys = list(np.arange(y0, y1, step, dtype=np.float64))
    return [float(y) for y in ys] + [float(y1)]


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


PANTS_BODY_EASE = 0.03  # rows pants (round 26): the waist -> crotch block and a leg's top are the body + 3 %
PANTS_LEG_OPEN = 0.2  # share of crotch..knee over which a leg opens from the body + ease to its own width x s
PANTS_EDGE_SIGMA_ROWS = 4.0  # px (rows): Gaussian blur of the leg edges after the monotonic pass
PANTS_BODY_CLAMP = 0.1  # the figure run used as the body is at most this x the landmark width past the landmarks
PANTS_LEG_CLAMP = 0.25  # same for a leg (the thigh's curve is not in the straight landmark lines)
PANTS_RING = 3  # px: the outer ring of the warped pants that takes its colour from the plain fabric
PANTS_PLAIN_SHARE = 0.15  # colour clusters holding at least this share of the fabric are plain fabric (not print)
PANTS_PLAIN_DIST = 40.0  # a px is plain fabric when its colour lies this close to a plain cluster centre
PANTS_PLAIN_SIGMA = 4.0  # px: blur of the plain-fabric colour field the ring is filled from
PANTS_SRC_SIGMA = 3.0  # rows (leg_mode smooth): blur of a leg's src span along y
PANTS_BODY_SIGMA = 8.0  # rows (leg_mode smooth): blur of the body leg width along y


def _blur_rows(v: np.ndarray, sigma: float) -> np.ndarray:
    """1-D Gaussian blur of a per-row sequence (ends replicated)."""
    v = np.asarray(v, np.float64)
    if len(v) < 3:
        return v.copy()
    return cv2.GaussianBlur(v.reshape(-1, 1), (1, 0), sigma, borderType=cv2.BORDER_REPLICATE)[:, 0]


def _clamped_run(run, lo: float, hi: float, width: float, k: float):
    """(left, right) pixel EDGES of a mask run (l, r inclusive), clamped to k x width past the landmarks lo..hi;
    the landmark span when there is no run."""
    if run is None:
        return lo, hi
    lim = k * max(width, 1.0)
    return max(float(run[0]), lo - lim), min(float(run[1]) + 1.0, hi + lim)


def _monotone_outward(v: np.ndarray, sign: int) -> np.ndarray:
    """The monotonic edge closest to v that lies on or outside it everywhere (sign -1: a left edge, never larger
    x; +1: a right edge, never smaller x). Of the two directions the one that adds the least is taken."""
    f = v * sign
    a = np.maximum.accumulate(f)  # non-decreasing in f
    b = np.maximum.accumulate(f[::-1])[::-1]  # non-increasing in f
    best = a if (a - f).sum() <= (b - f).sum() else b
    return best * sign


def _leg_edges(v: np.ndarray, sign: int) -> np.ndarray:
    """A leg edge from crotch to hem: monotonic and outward (_monotone_outward), blurred (a blur keeps a monotonic
    sequence monotonic), and pushed back outside the monotonic edge (the min / max of two sequences that run the
    same way runs that way too). No kinks, no bulges, the body under it stays covered."""
    m = _monotone_outward(np.asarray(v, np.float64), sign)
    if len(m) < 3:
        return m
    s = cv2.GaussianBlur(m.reshape(-1, 1), (1, 0), PANTS_EDGE_SIGMA_ROWS, borderType=cv2.BORDER_REPLICATE)[:, 0]
    return np.minimum(s, m) if sign < 0 else np.maximum(s, m)


def _warp_pieces(src: np.ndarray, y0: int, pieces: np.ndarray, H: int, W: int) -> np.ndarray:
    """One BGRA layer from per-row pieces: pieces[i, k] = (dst left, dst right, src left, src right, src y) of
    piece k (0 = left of the crotch axis, 1 = right) in dst row y0 + i; x are pixel EDGES as in _warp_rows. A px
    takes the piece on its side of the midpoint between them; inside a piece dst x maps linearly onto src x, so
    two pieces that share the axis and the src x there join without a step. Premultiplied bilinear sampling.
    The alpha of a px that a span edge cuts is its geometric coverage (about 1 px antialiased, the same in every
    row: the drawn outline is the model's outline, no source-edge jitter); where two pieces meet there is no edge.
    A piece with right <= left is not drawn."""
    out = np.zeros((H, W, 4), np.uint8)
    n = pieces.shape[0]
    ys = np.arange(y0, y0 + n)
    ok = (ys >= 0) & (ys < H)
    if not ok.any():
        return out
    p = pieces[ok]
    ys = ys[ok]
    xs = np.arange(W, dtype=np.float64)[None, :] + 0.5
    has_l, has_r = p[:, 0, 1] > p[:, 0, 0], p[:, 1, 1] > p[:, 1, 0]
    mid = np.where(has_l & has_r, (p[:, 0, 1] + p[:, 1, 0]) / 2, np.where(has_l, np.inf, -np.inf))
    right = xs >= mid[:, None]
    q = np.where(right[:, :, None], p[:, None, 1, :], p[:, None, 0, :])  # (rows, W, 5)
    dl, dr, sl, sr, sy = (q[:, :, k] for k in range(5))
    shared = (has_l & has_r & (np.abs(p[:, 0, 1] - p[:, 1, 0]) < 0.5))[:, None]
    scale = (sr - sl) / np.maximum(dr - dl, 1e-6)
    edge = np.clip(sl + (xs - dl) * scale, sl + 0.5, sr - 0.5)  # px centres on the span's own outer px at most
    x0 = xs - 0.5
    lo = np.where(shared & right, -np.inf, dl)  # a shared boundary is not an edge
    hi = np.where(shared & ~right, np.inf, dr)
    cov = np.clip(np.minimum(x0 + 1, hi) - np.maximum(x0, lo), 0.0, 1.0)
    inside = (dr > dl) & (cov > 0)
    map_x = np.where(inside, edge - 0.5, -10.0).astype(np.float32)
    map_y = np.where(inside, sy, -10.0).astype(np.float32)
    f = src.astype(np.float32)
    f[:, :, :3] *= f[:, :, 3:4] / 255.0
    w = cv2.remap(f, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    a = w[:, :, 3:4] / 255.0
    w[:, :, :3] = np.where(a > 0, w[:, :, :3] / np.maximum(a, 1e-6), 0)
    w[:, :, 3] = np.where(cov < 1, 255.0 * cov * (w[:, :, 3] > 0), w[:, :, 3])
    out[ys] = np.clip(np.rint(w), 0, 255).astype(np.uint8)
    return out


def _leg_bottom(alpha: np.ndarray, side: str, axis: float, below: float) -> float:
    """Source y of a leg's own last row (the last row with garment px on its side of the axis, below `below`):
    the last dst row samples it, never the transparent row under it (that would repeat its colour)."""
    cols = alpha[:, :int(axis)] if side == "left" else alpha[:, int(np.ceil(axis)):]
    rows = np.nonzero(cols.any(axis=1))[0]
    rows = rows[rows > below]
    return float(rows[-1]) if len(rows) else float(alpha.shape[0] - 1)


def warp_pants(body_lm: dict, garment_lm: dict, garment_img: np.ndarray, H: int, W: int,
               arms: dict | None = None, info: dict | None = None,
               mask: np.ndarray | None = None, engine: str = "rows",
               leg_mode: str = "r26") -> tuple[np.ndarray, list]:
    """leg_mode (round 28, docs/09 #122, setting TRYON_PANTS_LEG; the default here is the off value): "smooth" =
    each leg gets one horizontal factor (the garment's own outline, at most PANTS_MAX_BODY x the body leg: no
    bend where a per-row cap switches from the thigh to the knee width), one smooth centre line (a degree-2 curve
    through the body leg's centres, no knee kink), src spans and body widths blurred along y; "r26" = round 26.
    engine "fit" = warp_pants_fit (round 21, docs/09 #114, setting TRYON_PANTS_ENGINE); "rows" (the default) =
    the round 26 fit model (docs/06 "Pants fit, round 26", docs/09 #120):
    - length: the garment's waist..crotch lands on the body's waist..crotch; its crotch..own bottom edge on the
      body's crotch..ankle (full length, pants_scale) or, shorter pants, at the uniform scale s;
    - waist -> crotch (body crotch): ONE piece, every row the figure's run through the axis (an arm or hand that
      touches the hip is clamped off) + PANTS_BODY_EASE; the garment's own width is not used. The row is mapped in
      two halves that meet on the axis: the garment's crotch x lands on the body's crotch x in every row, so a fly,
      a drawstring or a print crosses the axis without a step;
    - legs, below the body crotch only: each starts as its half of the block (its edges leave the block's last row
      with the same smoothstep, no step at the crotch row), sized as the body leg + ease, and opens to the
      garment's own leg width x s with a smoothstep over the first PANTS_LEG_OPEN of crotch..knee, at most
      PANTS_MAX_BODY x the body leg (below the knee: x the knee); centred on the body leg; the inner edge never
      comes closer to the axis than the garment's own gap between its legs (x s), or than the body leg's inner
      edge where that is further out: the rest of the width goes outward, so a wide leg stays a leg (no skirt); every edge monotonic and smooth from crotch to hem
      (_leg_edges), the body leg always inside;
    - hem: the leg's own bottom edge on the ankle line (no repeated rows below a hem landmark);
    - nothing above the body's waist row; the waistband top dips (curve_waistband, for the T-shirt hem snap).
    The outline's alpha is the model's geometric coverage (_warp_pieces), so the photo's fringe is only left in the
    colour of the outer px: pants_edge (in garment_layer) repaints that ring from the plain fabric. info: pants_rows
    = {"block", "left", "right": [(y, left, right)]}, pants_gap = the px between the legs (kept open by the hole
    fill), pants_scale."""
    if engine == "fit":
        return warp_pants_fit(body_lm, garment_lm, garment_img, H, W, arms=arms, info=info, mask=mask)
    warnings: list[str] = []
    g, a = garment_lm, body_lm
    img = _bgra(garment_img)
    g_alpha = img[:, :, 3] > 128
    g_wy, a_wy = _f(g["waist"]["y"]), _f(a["waist"]["y"])
    g_cr, a_cr = _f(g["crotch"]["y"]), _f(a["crotch"]["y"])
    g_cx, a_cx = _f(g["crotch"]["center_x"]), _crotch_x(a)
    a_kn = _f(a["knee"]["y"])
    s, full = pants_scale(g, a, H)
    s_rise = (a_cr - a_wy) / max(g_cr - g_wy, 1e-6)  # dst px per src px, waist -> crotch
    g_rows = [(g_wy, _f(g["waist"]["left_x"]), _f(g["waist"]["right_x"])),
              (_f(g["hip"]["y"]), _f(g["hip"]["left_x"]), _f(g["hip"]["right_x"])),
              (g_cr, _f(g["hip"]["left_x"]), _f(g["hip"]["right_x"]))]
    worst: dict[str, float] = {}

    def track(label, src_w, dst_w):
        if src_w > 1:
            r = dst_w / (src_w * s)
            if abs(np.log(r)) > abs(np.log(worst.get(label, 1.0))):
                worst[label] = r

    legs = {}
    for side in ("left", "right"):
        leg = f"{side}_leg"
        gk, gh, ak, aa = g["knee"][leg], g["hem"][leg], a["knee"][leg], a["ankle"][leg]
        g_bot = _leg_bottom(g_alpha, side, g_cx, g_cr)
        hem_dst = _f(aa["y"]) if full else a_cr + (g_bot - g_cr) * s
        g_outer = _f(g["hip"][f"{side}_x"])
        a_outer = _f(a["hip"][f"{side}_x"])
        legs[side] = {
            "g_bot": g_bot, "hem": hem_dst, "v": (g_bot - g_cr) / max(hem_dst - a_cr, 1e-6),  # src px per dst px
            "src": [(g_cr, g_outer, g_cx) if side == "left" else (g_cr, g_cx, g_outer),
                    (_f(g["knee"]["y"]), _f(gk["left_x"]), _f(gk["right_x"])),
                    (_f(gh["y"]), _f(gh["left_x"]), _f(gh["right_x"]))],
            "body": [(a_cr, a_outer, a_cx) if side == "left" else (a_cr, a_cx, a_outer),
                     (a_kn, _f(ak["left_x"]), _f(ak["right_x"])),
                     (_f(aa["y"]), _f(aa["left_x"]), _f(aa["right_x"]))]}

    def leg_body(side, y):
        L = legs[side]
        bl, br = _interp_span(L["body"], y)
        run = _leg_run(mask, int(y), side, a_cx, (bl + br) / 2) if mask is not None else None
        return _clamped_run(run, bl, br, br - bl, PANTS_LEG_CLAMP)

    knee_w = {side: (lambda e: e[1] - e[0])(leg_body(side, a_kn)) for side in legs}

    y_top = int(np.floor(a_wy))
    y_cr = int(np.floor(a_cr))  # last block row
    y_end = int(np.ceil(max(L["hem"] for L in legs.values())))
    n = y_end - y_top + 1
    pieces = np.zeros((n, 2, 5))
    block, leg_rows = [], {"left": [], "right": []}
    # waist -> crotch: the figure + ease, in two halves on the axis
    for y in range(y_top, y_cr + 1):
        bl, br = body_span(a, y)
        run = next((q for q in _runs(mask[min(max(y, 0), H - 1)]) if q[0] <= a_cx <= q[1]), None) \
            if mask is not None else None
        fl, fr = _clamped_run(run, bl, br, br - bl, PANTS_BODY_CLAMP)
        e = PANTS_BODY_EASE * (fr - fl) / 2
        sy = g_wy + max(y - a_wy, 0.0) / s_rise
        sl, sr = _garment_span(g_alpha, sy, _interp_span(g_rows, sy))
        block.append([y, fl - e, fr + e, sl, sr, sy])
    blk = np.array(block, np.float64)
    for i, (y, l, r, sl, sr, sy) in enumerate(blk):
        sc = min(max(g_cx, sl + 1), sr - 1)
        pieces[i, 0] = (l, a_cx, sl, sc, sy)
        pieces[i, 1] = (a_cx, r, sc, sr, sy)
        if y >= _f(a["hip"]["y"]):
            track("waist-crotch", sr - sl, r - l)
    # legs: body leg + ease -> the garment's own width x s, centred on the body leg, never across the axis
    for side in ("left", "right"):
        L = legs[side]
        open_h = max(PANTS_LEG_OPEN * (a_kn - a_cr), 1.0)
        raw = []
        for y in range(y_cr + 1, int(np.floor(L["hem"])) + 1):
            sy = g_cr + (y - a_cr) * L["v"]
            sl, sr = _leg_span(g_alpha, sy, _interp_span(L["src"], sy), side, g_cx)
            raw.append([y, sy, sl, sr, *leg_body(side, y)])
        raw = np.array(raw, np.float64).reshape(-1, 6)
        ys_ = raw[:, 0]
        bw_ = raw[:, 5] - raw[:, 4]
        ref_ = np.where(ys_ > a_kn, np.maximum(bw_, knee_w[side]), bw_)
        cen_ = (raw[:, 4] + raw[:, 5]) / 2
        own_ = (raw[:, 3] - raw[:, 2]) * s
        if leg_mode == "smooth" and len(raw) >= 5:  # round 28 (docs/09 #122): no knee bend, no row jitter
            # src spans blurred along y, never past the garment's own run (no transparent src px sampled)
            raw[:, 2] = np.maximum(_blur_rows(raw[:, 2], PANTS_SRC_SIGMA), raw[:, 2])
            raw[:, 3] = np.minimum(_blur_rows(raw[:, 3], PANTS_SRC_SIGMA), raw[:, 3])
            own_ = (raw[:, 3] - raw[:, 2]) * s
            bw_ = _blur_rows(bw_, PANTS_BODY_SIGMA)
            # one horizontal factor for the whole leg instead of a per-row cap: the garment's own outline (no
            # bend where the cap switches from the thigh to the knee width)
            below = ys_ > a_cr + open_h
            cap = np.maximum(ref_ * PANTS_MAX_BODY, bw_ * (1 + PANTS_BODY_EASE))
            ratio = cap / np.maximum(own_, 1e-6)
            f = float(min(1.0, ratio[below].min())) if below.any() else 1.0
            if info is not None:
                j = int(np.argmin(np.where(below, ratio, np.inf))) if below.any() else 0
                info.setdefault("pants_leg_cap_at", {})[side] = (float((ys_[j] - a_cr) / max(L["hem"] - a_cr, 1)),
                                                                   float(ys_[j] > a_kn))
            own_ = own_ * f
            ref_ = np.full_like(ref_, np.inf)  # the factor is the cap
            # the leg's centre line: one smooth curve through the body leg's centres (degree 2, no knee kink)
            cen_ = np.polyval(np.polyfit(ys_, cen_, 2), ys_)
            if info is not None:
                info.setdefault("pants_leg_factor", {})[side] = f
        rows = []
        for i, (y, sy, sl, sr, rl, rr) in enumerate(raw):
            bw = bw_[i]
            base = bw * (1 + PANTS_BODY_EASE)
            target = min(max(own_[i], base), max(ref_[i] * PANTS_MAX_BODY, base))
            k_open = _smooth((y - a_cr) / open_h)
            w = base + k_open * (target - base)
            c = cen_[i]
            l, r = c - w / 2, c + w / 2
            if side == "left":  # the inner edge stays out of the garment's own gap between the legs
                lim = max(a_cx - max(g_cx - sr, 0.0) * s, rr)  # never inside the body leg
                if r > lim:
                    l, r = l - (r - lim), lim
            else:
                lim = min(a_cx + max(sl - g_cx, 0.0) * s, rl)
                if l < lim:
                    l, r = lim, r + (lim - l)
            # the leg leaves the block's last row (its outer edge and the axis) with the same smoothstep: no step
            # at the crotch row, the crotch is a smooth inverted V
            l0, r0 = (blk[-1, 1], a_cx) if side == "left" else (a_cx, blk[-1, 2])
            l, r = k_open * l + (1 - k_open) * l0, k_open * r + (1 - k_open) * r0
            rows.append([y, min(l, rl), max(r, rr), sl, sr, sy])
            if y - a_cr > open_h:
                track(f"{side}-leg", sr - sl, w)
        if not rows:
            continue
        lr = np.array(rows, np.float64)
        if info is not None:
            info.setdefault("pants_profile", {})[side] = {"y": lr[:, 0].copy(), "raw_l": lr[:, 1].copy(),
                                                          "raw_r": lr[:, 2].copy()}
        lr[:, 1] = _leg_edges(lr[:, 1], -1)
        lr[:, 2] = _leg_edges(lr[:, 2], 1)
        if info is not None:
            info["pants_profile"][side].update(l=lr[:, 1].copy(), r=lr[:, 2].copy())
        leg_rows[side] = [tuple(r_[:3]) for r_ in lr]
        k = 0 if side == "left" else 1
        for y, l, r, sl, sr, sy in lr:
            pieces[int(y) - y_top, k] = (l, r, sl, sr, sy)
    # rows below one leg's hem keep that piece empty (right <= left); a row with both empty draws nothing
    result = _warp_pieces(img, y_top, pieces, H, W)
    hip_dst = _f(a["hip"]["y"])
    top_l, top_r = blk[0, 1], blk[0, 2]
    result = curve_waistband(result, a_wy, hip_dst, top_l, top_r)
    result[:max(int(np.ceil(a_wy)), 0)] = 0  # pants exist only from the body's waist row down
    gap = np.zeros((H, W), bool)  # between the legs: an opening, not a hole to fill
    lft, rgt = dict((int(y), r) for y, _, r in leg_rows["left"]), dict((int(y), l) for y, l, _ in leg_rows["right"])
    for y in set(lft) & set(rgt):
        x0, x1 = int(np.ceil(lft[y])) + 1, int(np.floor(rgt[y])) - 1
        if 0 <= y < H and x1 > x0:
            gap[y, max(x0, 0):min(x1, W)] = True
    for label, r in worst.items():
        if r > PANTS_DISTORT_LIMIT or r < 1 / PANTS_DISTORT_LIMIT:
            warnings.append(f"{label}: distorted {max(r, 1 / r):.2f}x ({'wider' if r > 1 else 'narrower'})")
    if info is not None:
        info["pants_waist_y"] = a_wy
        info["pants_top_dip"] = WAISTBAND_CURVE * (top_r - top_l)
        info["pants_rows"] = {"block": [tuple(r_[:3]) for r_ in blk], **leg_rows}
        info["pants_gap"] = gap
        info["pants_scale"] = {"s": s, "rise": s_rise, "full": bool(full),
                               "legs": {sd: 1 / L["v"] for sd, L in legs.items()}}
    return result, warnings


def _plain_fabric(layer: np.ndarray, region: np.ndarray) -> np.ndarray:
    """HxW bool: the px of `region` that are plain fabric, not print: k-means colour clusters of the region, the
    clusters holding at least PANTS_PLAIN_SHARE of it (at least the largest) are plain; a px is plain when it lies
    within PANTS_PLAIN_DIST of a plain cluster's centre."""
    px = layer[:, :, :3][region].astype(np.float32)
    if len(px) < 20:
        return region.copy()
    rng = np.random.default_rng(0)
    sample = px[rng.choice(len(px), min(len(px), 20000), replace=False)]
    k = min(5, len(sample))
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    cv2.setRNGSeed(0)
    _, lab, centres = cv2.kmeans(sample, k, None, crit, 2, cv2.KMEANS_PP_CENTERS)
    share = np.bincount(lab[:, 0], minlength=k) / len(lab)
    plain = centres[(share >= PANTS_PLAIN_SHARE) | (share == share.max())]
    d = np.linalg.norm(px[:, None, :] - plain[None, :, :], axis=2).min(axis=1)
    out = np.zeros(region.shape, bool)
    out[region] = d < PANTS_PLAIN_DIST
    return out


def pants_edge(layer: np.ndarray, ring: int = PANTS_RING) -> np.ndarray:
    """Round 26 halo fix for warped pants (docs/06 "Pants fit, round 26"): nothing is eroded (the warp draws the
    model's outline with a geometric, antialiased alpha); the outer `ring` px of the outer contour (enclosed
    openings are not touched) take their colour from the plain fabric only: a colour field blurred from the plain
    px (_plain_fabric) or, where no plain px is near, the nearest plain px. The photo's light fringe goes; a print
    or a stitch that reaches the edge is cut there, never smeared along it; deeper px keep their colour exactly."""
    a = np.ascontiguousarray(layer[:, :, 3])
    if not a.any():
        return layer
    outside = np.ones((a.shape[0] + 2, a.shape[1] + 2), np.uint8)
    outside[1:-1, 1:-1] = a < 128
    cv2.floodFill(outside, None, (0, 0), 2)
    solid = np.where(outside[1:-1, 1:-1] == 1, 255, a) >= 128  # enclosed holes count as fabric
    depth = cv2.distanceTransform(solid.astype(np.uint8), cv2.DIST_L2, 3)
    ring_px = (a > 0) & (depth <= ring)
    deep = (a >= 250) & (depth > ring)
    out = layer.copy()
    if not ring_px.any() or not deep.any():
        return out
    plain = _plain_fabric(layer, deep)
    if not plain.any():
        plain = deep
    rgb = layer[:, :, :3].astype(np.float32)
    w = plain.astype(np.float32)
    num = cv2.GaussianBlur(rgb * w[:, :, None], (0, 0), PANTS_PLAIN_SIGMA)
    den = cv2.GaussianBlur(w, (0, 0), PANTS_PLAIN_SIGMA)
    field = num / np.maximum(den, 1e-6)[:, :, None]
    near = ring_px & (den > 0.02)
    out[:, :, :3][near] = np.clip(np.rint(field[near]), 0, 255).astype(np.uint8)
    far = ring_px & ~near
    if far.any():
        _colour_from_nearest_opaque(out, far, ok=plain)
    return out


PANTS_FIT_MAX = 1.7  # "fit": the one horizontal factor is at most this (beyond it single rows widen, warning)
PANTS_FIT_JOIN = 0.3  # "fit": share of crotch..knee over which a leg leaves the waist block's edges
PANTS_FIT_TOP = 0.4  # "fit": share of crotch..knee whose rows count for the hip factor (below: the leg factor)
PANTS_FIT_SIGMA = 7.0  # "fit": rows (x ROW_STEP px) of the blur behind a leg's factor profile
HEM_TILT_MIN = 0.02  # a leg leaning less than this (px sideways per px down, about 1 degree) keeps a level hem
HEM_TILT_MAX = 0.2  # at most this lean is followed
PANTS_EDGE_SIGMA = 3.0  # "fit": rows of the outward-only smoothing of a leg's edges
CROTCH_GAP_MIN_CONTRAST = 30.0  # colour distance fabric <-> photo background below which the gap is left alone
CROTCH_GAP_MAX_HALF = 12  # px: a cleared component is at most about twice this wide (a gap strip, not a print)
CROTCH_GAP_BG_SHARE = 0.5  # a gap px goes when its distance to the background is under this x that to the fabric
PANTS_FIT_SEAM = 2.0  # "fit": px the two legs overlap where they meet on the crotch axis
PANTS_FIT_TAPER = 20.0  # "fit": extra blur rows per unit of (fx - 1)
PANTS_FIT_COVER = 3.0  # px the pants reach past the body leg in the mask


def _leg_span(alpha: np.ndarray, sy: float, fallback: tuple, side: str, axis: float) -> tuple[float, float]:
    """One leg's whole span in garment row sy: every run on its side of the axis that overlaps the landmark span,
    from the first to the last (a slit at the hem splits the leg into two runs: both belong to it)."""
    y = min(max(int(round(sy)), 0), alpha.shape[0] - 1)
    runs = []
    for l, r in _runs(alpha[y]):
        if l <= axis <= r:
            l, r = (l, int(axis)) if side == "left" else (int(axis), r)
        elif (r < axis) != (side == "left"):
            continue
        if r >= fallback[0] and l <= fallback[1]:
            runs.append((l, r))
    if not runs or max(q[1] for q in runs) - min(q[0] for q in runs) < 0.3 * (fallback[1] - fallback[0]):
        return fallback
    return float(min(q[0] for q in runs)), float(max(q[1] for q in runs)) + 1.0


def _torso_cover(mask, y: float, axis: float, bl: float, br: float) -> tuple[float, float]:
    """(left, right) x the pants block must reach in row y: the figure's run through the axis + PANTS_FIT_COVER,
    at most 10 % of the landmark width beyond the landmark span (an arm that touches the hip is not the hip)."""
    if mask is None:
        return bl, br
    yi = min(max(int(round(y)), 0), mask.shape[0] - 1)
    run = next((q for q in _runs(mask[yi]) if q[0] <= axis <= q[1]), None)
    if run is None:
        return bl, br
    lim = 0.1 * (br - bl)
    return max(run[0] - PANTS_FIT_COVER, bl - lim), min(run[1] + 1 + PANTS_FIT_COVER, br + lim)


def _tilt_hem(strip: np.ndarray, dst_rows: list, knee_y: float, hem_y: float) -> tuple[np.ndarray, float]:
    """A leg that leans keeps its hem square to the leg: below the knee the strip's content is moved DOWN, more
    towards the side the leg leans away from (0 px on the side it leans to), growing from the knee to the hem.
    Nothing moves up, so nothing is uncovered. Returns (strip, the hem's drop in px on the far side)."""
    rows = [r_ for r_ in dst_rows if knee_y <= r_[0] <= hem_y]
    if len(rows) < 3 or hem_y - knee_y < 20:
        return strip, 0.0
    c0, c1 = (rows[0][1] + rows[0][2]) / 2, (rows[-1][1] + rows[-1][2]) / 2
    slope = (c1 - c0) / max(rows[-1][0] - rows[0][0], 1e-6)  # px sideways per px down
    l, r = rows[-1][1], rows[-1][2]
    drop = abs(slope) * (r - l)
    if abs(slope) < HEM_TILT_MIN or drop < 1.0:
        return strip, 0.0
    slope = float(np.clip(slope, -HEM_TILT_MAX, HEM_TILT_MAX))
    H, W = strip.shape[:2]
    xs = np.arange(W, dtype=np.float32)[None, :]
    ys = np.arange(H, dtype=np.float32)[:, None]
    far = np.clip(xs - l, 0, r - l) if slope < 0 else np.clip(r - xs, 0, r - l)  # distance from the high side
    ramp = np.clip((ys - knee_y) / max(hem_y - knee_y, 1e-6), 0, 1) ** 2
    map_y = (ys - abs(slope) * far * ramp).astype(np.float32)
    map_x = np.repeat(xs, H, axis=0).astype(np.float32)
    f = strip.astype(np.float32)
    f[:, :, :3] *= f[:, :, 3:4] / 255.0
    w = cv2.remap(f, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    a = w[:, :, 3:4] / 255.0
    w[:, :, :3] = np.where(a > 0, w[:, :, :3] / np.maximum(a, 1e-6), 0)
    return np.clip(np.rint(w), 0, 255).astype(np.uint8), float(abs(slope) * (r - l))


def _smooth_outward(xs: list, sign: int, sigma: float = PANTS_EDGE_SIGMA) -> list:
    """A smooth version of an edge that lies on or outside it everywhere (sign -1: a left edge, never larger x;
    +1: a right edge, never smaller x): blur, push back out to the edge, three times, then a light blur and a last
    push. Valleys narrower than about sigma rows are bridged, the outline's own curves stay."""
    v = np.asarray(xs, np.float64) * sign
    if len(v) < 3:
        return list(xs)
    f = v.copy()
    for s_ in (sigma, sigma, sigma, sigma / 3):
        f = np.maximum(cv2.GaussianBlur(f.reshape(-1, 1), (1, 0), s_, borderType=cv2.BORDER_REPLICATE)[:, 0], v)
    return [float(x) * sign for x in f]


def clean_crotch_gap(img: np.ndarray, glm: dict) -> tuple[np.ndarray, int]:
    """Pants cutout: opaque px between the legs that still carry the photo's background (the cutout model keeps
    the narrow gap below the crotch) are made transparent. Only inside the gap polygon (crotch -> the legs' inner
    knee and hem points, grown a little) and only when the fabric is clearly not background-coloured; a px goes
    when it is nearer the background colour than the fabric's. Returns (image, px cleared)."""
    bg = background_color(img)
    if bg is None:
        return img, 0
    try:
        cx, cy = _f(glm["crotch"]["center_x"]), _f(glm["crotch"]["y"])
        kl, kr = _f(glm["knee"]["left_leg"]["right_x"]), _f(glm["knee"]["right_leg"]["left_x"])
        hl, hr = _f(glm["hem"]["left_leg"]["right_x"]), _f(glm["hem"]["right_leg"]["left_x"])
        ky = _f(glm["knee"]["y"])
        hy = max(_f(glm["hem"]["left_leg"]["y"]), _f(glm["hem"]["right_leg"]["y"]))
    except (KeyError, TypeError):
        return img, 0
    h, w = img.shape[:2]
    grow = max(4.0, 0.012 * w)
    poly = np.array([(cx - grow, cy - grow), (min(kl, cx) - grow, ky), (min(hl, cx) - grow, hy),
                     (max(hr, cx) + grow, hy), (max(kr, cx) + grow, ky), (cx + grow, cy - grow)], np.int32)
    zone = np.zeros((h, w), np.uint8)
    cv2.fillPoly(zone, [poly], 1)
    opaque = img[:, :, 3] > 128
    rgb = img[:, :, :3].astype(np.float32)
    legs = opaque & (zone == 0)
    legs[:int(cy)] = False
    if legs.sum() < 50:
        return img, 0
    fabric = np.median(rgb[legs], axis=0)
    if float(np.linalg.norm(fabric - bg)) < CROTCH_GAP_MIN_CONTRAST:
        return img, 0
    d_bg = np.linalg.norm(rgb - np.asarray(bg, np.float32), axis=2)
    d_fab = np.linalg.norm(rgb - fabric, axis=2)
    cand = (zone > 0) & opaque & (d_bg < CROTCH_GAP_BG_SHARE * d_fab)
    if not cand.any():
        return img, 0
    # only background-coloured px that reach the transparent background (the fringe and the gap strip); a light
    # print, an embroidery or a white seam line inside the fabric stays, even near the edge
    n, lab = cv2.connectedComponents(cand.astype(np.uint8), connectivity=8)
    edge = cv2.dilate((~opaque).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    touching = np.unique(lab[edge & cand])
    gone = np.isin(lab, touching[touching > 0])
    small = np.zeros(n, bool)  # a component is a fringe or a gap only when it is thin: at most a few px wide
    for i in touching[touching > 0]:
        m = lab == i
        if int(cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, 3).max()) <= CROTCH_GAP_MAX_HALF:
            small[i] = True
    gone &= small[lab]
    if not gone.any():
        return img, 0
    out = img.copy()
    out[:, :, 3][gone] = 0
    return out, int(gone.sum())


def _pants_leg_profile(need: list, fx: float, sigma: float = PANTS_FIT_SIGMA) -> list:
    """A leg's horizontal factor per row: starts at the hip factor fx, then the smooth upper envelope of what the
    body needs (>= 1, <= PANTS_FIT_MAX): wide where the body is wider than the garment, the garment's own width
    (factor 1) where it is loose; smooth along the leg so the outline has no kinks."""
    n = np.clip(np.asarray(need, np.float64), 1.0, PANTS_FIT_MAX)
    if not len(n):
        return []
    n[0] = max(n[0], fx)
    f = n.copy()
    for _ in range(3):  # blur, then lift back over the need: converges to a smooth curve above it
        f = cv2.GaussianBlur(f.reshape(-1, 1), (1, 0), sigma, borderType=cv2.BORDER_REPLICATE)[:, 0]
        f = np.maximum(f, n)
    f = cv2.GaussianBlur(f.reshape(-1, 1), (1, 0), sigma / 3, borderType=cv2.BORDER_REPLICATE)[:, 0]
    return [float(v) for v in np.clip(np.maximum(f, n), 1.0, PANTS_FIT_MAX)]


def _pants_fit_factor(ratios: list) -> float:
    """The one horizontal factor of a pair of pants: the largest body / garment width ratio over the hip and leg
    rows (so the garment covers the body everywhere with its own outline), at least 1, at most PANTS_FIT_MAX."""
    return float(min(max([1.0] + list(ratios)), PANTS_FIT_MAX))


def warp_pants_fit(body_lm: dict, garment_lm: dict, garment_img: np.ndarray, H: int, W: int,
                   arms: dict | None = None, info: dict | None = None,
                   mask: np.ndarray | None = None) -> tuple[np.ndarray, list]:
    """Pants, round 21 (docs/09 #114, docs/06 "Pants fit, round 21"). The garment keeps its own outline:
    - vertical: the uniform scale s of pants_scale; the crotch never above the body's crotch;
    - horizontal: garment row width x s x a smooth factor, never a per-row "garment or body, whichever is
      wider": fx for the hip block (the largest body / garment ratio over the hip rows and the top PANTS_FIT_TOP
      of the thighs); down each leg `_pants_leg_profile` (starts at fx, the smooth upper envelope of the body's
      need, 1 where the garment is loose), so a flare stays a flare and a straight leg stays straight; only the
      waistband is fitted to the body's waist (smoothstep to the garment width by the hip row);
    - each leg hangs straight down from its half of the hip block and is moved sideways only as far as the body
      leg in the mask pushes it (a tight leg follows the body leg, a wide leg stays vertical); where the two legs
      would overlap they meet on the crotch axis;
    - the body leg in the mask + PANTS_FIT_COVER px is always covered (a row that needs more than fx widens)."""
    warnings: list[str] = []
    g, a = garment_lm, body_lm
    img = _bgra(garment_img)
    g_alpha = img[:, :, 3] > 128
    legs = ("left", "right")
    g_wy, a_wy = _f(g["waist"]["y"]), _f(a["waist"]["y"])
    g_cr, a_cr, g_hy = _f(g["crotch"]["y"]), _f(a["crotch"]["y"]), _f(g["hip"]["y"])
    g_cx, a_cx = _f(g["crotch"]["center_x"]), _crotch_x(a)
    s, full = pants_scale(g, a, H)
    cr_dst = max(a_wy + (g_cr - g_wy) * s, a_cr)
    v_block = (g_cr - g_wy) / max(cr_dst - a_wy, 1e-6)  # src px per dst px, waist..crotch
    hip_dst = a_wy + (g_hy - g_wy) / v_block
    g_rows = [(g_wy, _f(g["waist"]["left_x"]), _f(g["waist"]["right_x"])),
              (g_hy, _f(g["hip"]["left_x"]), _f(g["hip"]["right_x"])),
              (g_cr, _f(g["hip"]["left_x"]), _f(g["hip"]["right_x"]))]

    # ---- per leg: garment spans, body runs, the body leg's straight centre line
    leg = {}
    for side in legs:
        key = f"{side}_leg"
        gk, gh, ak, aa = g["knee"][key], g["hem"][key], a["knee"][key], a["ankle"][key]
        g_outer, a_outer = _f(g["hip"][f"{side}_x"]), _f(a["hip"][f"{side}_x"])
        leg_src = [(g_cr, g_outer, g_cx) if side == "left" else (g_cr, g_cx, g_outer),
                   (_f(g["knee"]["y"]), _f(gk["left_x"]), _f(gk["right_x"])),
                   (_f(gh["y"]), _f(gh["left_x"]), _f(gh["right_x"]))]
        body_rows = [(a_cr, a_outer, a_cx) if side == "left" else (a_cr, a_cx, a_outer),
                     (_f(a["knee"]["y"]), _f(ak["left_x"]), _f(ak["right_x"])),
                     (_f(aa["y"]), _f(aa["left_x"]), _f(aa["right_x"]))]
        hem_dst = _f(aa["y"]) if full else cr_dst + (_f(gh["y"]) - g_cr) * s
        v_leg = (_f(gh["y"]) - g_cr) / max(hem_dst - cr_dst, 1e-6)
        rows = []
        for y in _ys(cr_dst, hem_dst, ROW_STEP):
            sy = g_cr + (y - cr_dst) * v_leg
            sl, sr = _leg_span(g_alpha, sy, _interp_span(leg_src, sy), side, g_cx)
            bl, br = _interp_span(body_rows, y)
            run = _leg_run(mask, int(y), side, a_cx, (bl + br) / 2) if mask is not None and y <= _f(aa["y"]) else None
            if run is None and y <= _f(aa["y"]):
                run = (bl, br)
            rows.append((y, sy, sl, sr, run))
        pts = [(y, (run[0] + run[1]) / 2) for y, _, _, _, run in rows if run is not None and y >= a_cr + 12]
        if len(pts) >= 2:
            k1, k0 = np.polyfit([p_[0] for p_ in pts], [p_[1] for p_ in pts], 1)
        else:
            k1, k0 = 0.0, (body_rows[0][1] + body_rows[0][2]) / 2
        leg[side] = {"rows": rows, "line": (float(k1), float(k0)), "hem_dst": hem_dst, "v": v_leg,
                     "knee_dst": cr_dst + (_f(g["knee"]["y"]) - g_cr) / v_leg}

    # ---- the horizontal factors: fx for the hip block; per leg a smooth profile from fx down the leg
    top, need_all = [], []
    for y in _ys(hip_dst, cr_dst, ROW_STEP):
        sy = g_wy + (y - a_wy) * v_block
        sl, sr = _garment_span(g_alpha, sy, _interp_span(g_rows, sy))
        bl, br = body_span(a, y)
        top.append((br - bl) * (1 + PANTS_EASE) / max((sr - sl) * s, 1e-6))
    for side in legs:
        split = cr_dst + PANTS_FIT_TOP * (leg[side]["knee_dst"] - cr_dst)
        need = []
        for y, _, sl, sr, run in leg[side]["rows"]:
            r_ = ((run[1] - run[0]) + 2 * PANTS_FIT_COVER) / max((sr - sl) * s, 1e-6) \
                if run is not None and y >= a_cr + 12 else 1.0
            need.append(r_)
            if y < split:
                top.append(r_)
        leg[side]["need"] = need
        need_all += need
    fx = _pants_fit_factor(top)
    for side in legs:
        # a large hip factor leaves the leg slowly (no bulge that ends just under the hip)
        leg[side]["factor"] = _pants_leg_profile(leg[side]["need"], fx, PANTS_FIT_SIGMA + PANTS_FIT_TAPER * (fx - 1))
    need = max(top + need_all) if top or need_all else 1.0
    fx_low = float(min(min(leg[side]["factor"]) for side in legs))
    if need > PANTS_FIT_MAX:
        warnings.append(f"the body needs {need:.2f}x the garment's width (limit {PANTS_FIT_MAX})")

    # ---- waist -> crotch block
    src_rows, dst_rows, cover = [], [], []
    for y in _ys(a_wy, cr_dst, ROW_STEP):
        sy = g_wy + (y - a_wy) * v_block
        sl, sr = _garment_span(g_alpha, sy, _interp_span(g_rows, sy))
        bl, br = body_span(a, y)
        floor = (br - bl) * (1 + PANTS_EASE)
        k = _smooth((y - a_wy) / max(hip_dst - a_wy, 1e-6))
        w = (1 - k) * floor + k * max((sr - sl) * s * fx, floor)
        t = (y - a_wy) / max(cr_dst - a_wy, 1e-6)
        c = (1 - t * t) * (bl + br) / 2 + t * t * a_cx  # the block ends centred on the crotch axis
        src_rows.append((sy, sl, sr))
        dst_rows.append((y, c - w / 2, c + w / 2))
        cover.append(_torso_cover(mask, y, a_cx, bl, br))
    src_rows, dst_rows = _smooth_rows(src_rows), _smooth_rows(dst_rows)
    band_l, band_r = dst_rows[0][1], dst_rows[0][2]  # the waistband's dip is measured on the fitted width
    dst_rows = [(y, min(l, cl), max(r, cr_)) for (y, l, r), (cl, cr_) in zip(dst_rows, cover)]
    result = _warp_rows(img, src_rows, dst_rows, H, W, pad=1.0)
    result = curve_waistband(result, a_wy, a_wy + (g_hy - g_wy) * s, band_l, band_r)  # the dip as in "rows"
    top_dip = WAISTBAND_CURVE * (band_r - band_l)
    block_l, block_r = dst_rows[-1][1], dst_rows[-1][2]

    # ---- legs
    tilt = {}
    for side in legs:
        L = leg[side]
        k1, k0 = L["line"]
        top = (block_l, a_cx + PANTS_FIT_SEAM) if side == "left" else (a_cx - PANTS_FIT_SEAM, block_r)
        join = max(PANTS_FIT_JOIN * (L["knee_dst"] - cr_dst), 1.0)
        x_hang = (top[0] + top[1]) / 2
        src_rows, dst_rows = [], []
        for (y, sy, sl, sr, run), fy in zip(L["rows"], L["factor"]):
            w = (sr - sl) * s * fy
            # the leg hangs straight down from the hip (centre x_hang) and is moved only as far as the body leg
            # pushes it: a tight leg follows the body leg, a wide one stays vertical while the leg fits inside
            lo, hi = (run[1] + 1 + PANTS_FIT_COVER - w / 2, run[0] - PANTS_FIT_COVER + w / 2) if run is not None \
                else (x_hang, x_hang)
            c = min(max(x_hang, lo), hi) if lo <= hi else k1 * y + k0
            l, r = c - w / 2, c + w / 2
            if side == "left" and r > a_cx:  # the legs meet on the crotch axis instead of overlapping
                l, r = a_cx - w, a_cx + PANTS_FIT_SEAM  # (+ a seam overlap: no body px shows between them)
            elif side == "right" and l < a_cx:
                l, r = a_cx - PANTS_FIT_SEAM, a_cx + w
            if run is not None:  # the body leg is always covered
                l, r = min(l, run[0] - PANTS_FIT_COVER), max(r, run[1] + 1 + PANTS_FIT_COVER)
                if side == "left":
                    r = min(r, max(a_cx + PANTS_FIT_SEAM, run[1] + 1 + PANTS_FIT_COVER))
                else:
                    l = max(l, min(a_cx - PANTS_FIT_SEAM, run[0] - PANTS_FIT_COVER))
            f = 1 - _smooth((y - cr_dst) / join)
            l, r = f * top[0] + (1 - f) * l, f * top[1] + (1 - f) * r
            src_rows.append((sy, sl, sr))
            dst_rows.append((y, l, r))
        if info is not None:
            info.setdefault("pants_leg_rows", {})[side] = dst_rows
        src_rows[1:] = _smooth_rows(src_rows[1:])
        # the edges are smoothed outward only: a smooth curve that never comes inside the computed edge, so the
        # body leg stays covered without the kink a hard per-row limit leaves (the bump at a knee that pushes)
        # (the inner edge more: where the legs touch in the garment photo the leg is cut on the axis and its
        # width steps when they part, usually near the knee)
        ls = _smooth_outward([r_[1] for r_ in dst_rows[1:]], -1, PANTS_EDGE_SIGMA * (1 if side == "left" else 2))
        rs = _smooth_outward([r_[2] for r_ in dst_rows[1:]], 1, PANTS_EDGE_SIGMA * (2 if side == "left" else 1))
        dst_rows[1:] = [(r_[0], l, r) for r_, l, r in zip(dst_rows[1:], ls, rs)]
        _tail_rows(g_alpha, src_rows, dst_rows, 1 / L["v"])
        leg_img = img.copy()
        other = slice(int(np.ceil(g_cx)), None) if side == "left" else slice(0, int(g_cx))
        leg_img[int(g_cr):, other, 3] = 0
        strip = _warp_rows(leg_img, src_rows, dst_rows, H, W)
        strip, tilt[side] = _tilt_hem(strip, dst_rows, L["knee_dst"], L["hem_dst"])
        result = _alpha_composite(result, strip)
        L["dst"] = dst_rows

    # the open space between the legs stays open (the hole filling of garment_layer would paint it over when the
    # legs touch again lower down)
    gap = np.zeros((H, W), bool)
    dl, dr = np.array(leg["left"]["dst"], np.float64), np.array(leg["right"]["dst"], np.float64)
    y_lo, y_hi = int(np.ceil(cr_dst)), int(min(dl[-1, 0], dr[-1, 0]))
    if y_hi > y_lo:
        ys_ = np.arange(y_lo, min(y_hi, H - 1) + 1)
        inner_l = np.interp(ys_, dl[:, 0], dl[:, 2])
        inner_r = np.interp(ys_, dr[:, 0], dr[:, 1])
        xs_ = np.arange(W)[None, :]
        gap[ys_] = (xs_ >= np.ceil(inner_l)[:, None] + 1) & (xs_ <= np.floor(inner_r)[:, None] - 1)
        gap &= result[:, :, 3] < 128

    result[:max(int(np.ceil(a_wy)), 0)] = 0
    if info is not None:
        info["pants_waist_y"] = a_wy
        info["pants_top_dip"] = top_dip
        info["pants_hem_tilt"] = tilt
        info["pants_gap"] = gap
        info["pants_fit"] = {"engine": "fit", "fx": fx, "fx_low": fx_low, "need": float(need), "s": float(s), "full": bool(full)}
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


def remove_halo(img: np.ndarray, px: int = HALO_ERODE, outer_only: bool = False) -> np.ndarray:
    """Garment without its photo-background fringe: the alpha is eroded by px (the soft edge moves inward and
    stays soft), and the RGB of the new edge ring (the next 2 * px, where fringe colour is still blended in) is taken
    from the nearest interior pixel. Pixels deeper than 3 * px keep their colour exactly.
    outer_only: only the outer contour is treated (holes inside the silhouette, e.g. a real opening, are not
    eroded) and the recoloured ring is px wide: used on the composited T-shirt, whose pieces meet without any
    alpha edge between them."""
    a = np.ascontiguousarray(img[:, :, 3])
    src = a
    if outer_only:
        outside = np.ones((a.shape[0] + 2, a.shape[1] + 2), np.uint8)  # a 1 px frame of background
        outside[1:-1, 1:-1] = a < 128
        cv2.floodFill(outside, None, (0, 0), 2)  # background reached from the frame: 2, holes stay 1
        src = np.where(outside[1:-1, 1:-1] == 1, 255, a).astype(np.uint8)  # holes count as garment
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * px + 1, 2 * px + 1))
    er = cv2.erode(src, k, borderType=cv2.BORDER_CONSTANT, borderValue=0)
    ring = px if outer_only else 2 * px  # after the warp the fringe is already inside the eroded px: a px ring
    k2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * ring + 1, 2 * ring + 1))
    deep = cv2.erode(er, k2, borderType=cv2.BORDER_CONSTANT, borderValue=0)
    if outer_only:
        er = np.minimum(er, a)
        deep = np.where(a >= 250, deep, 0)
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
    remove the halo -> warp -> fill warp seams. Openings are warped along and stay open. T-shirt: the halo is
    removed after the warp, on the outer contour of the composited torso + sleeves (no edge treatment at the
    internal joins). Rows pants (docs/09 #120): the photo background between the legs is cleared first
    (clean_crotch_gap) and the halo is removed after the warp by pants_edge (ring from the plain fabric)."""
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
    else:  # docs/09 #115, #120: the photo background left between the legs
        src, info["crotch_gap_px"] = clean_crotch_gap(src, glm)
    k = tshirt_scale(glm, body_lm) if gtype == "tshirt" else pants_scale(glm, body_lm, H)[0]
    if k < PRESCALE_BELOW:
        src, glm = _prescale(src, k), _scale_landmarks(glm, k)
        aux = _prescale(aux, k) if aux is not None else None
    rows_pants = gtype == "pants" and kw.get("engine") != "fit"
    if halo_removal and gtype != "tshirt" and not rows_pants:  # the fit engine: before the warp, as before #120
        src = remove_halo(src)
    warped, warns = fn(body_lm, glm, src, H, W, arms=arms, info=info, mask=mask, **kw)
    keep = None
    if aux is not None:
        aux_w, _ = fn(body_lm, glm, aux, H, W, arms=arms, info={}, mask=mask, **kw)
        keep = aux_w[:, :, 3] > 128
    if info.get("pants_gap") is not None and info["pants_gap"].any():  # docs/09 #115
        keep = info["pants_gap"] if keep is None else keep | info["pants_gap"]
    out = fill_alpha_holes(warped, keep, inpaint=True)
    if halo_removal and gtype == "tshirt":  # T-shirt: once, on the outer contour of the composited pieces only
        out = remove_halo(out, outer_only=True)
    elif halo_removal and rows_pants:  # rows pants (#120): after the warp, the ring from the plain fabric only
        out = pants_edge(out)
    return out, warns


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


FINISH_EDGE_SIGMA = 1.2  # px: blur of the 0 / 1 coverage before the ramp (takes the 1 px stair steps out)
FINISH_EDGE_GAIN = 2.0  # ramp steepness around 50 % coverage: a straight edge becomes about 0.82 | 0.18


def soft_coverage(solid: np.ndarray, sigma: float = FINISH_EDGE_SIGMA, gain: float = FINISH_EDGE_GAIN) -> np.ndarray:
    """HxW float32 0..1: the bool coverage with an anti-aliased, de-stepped edge. The 50 % contour stays on the
    pixel edge of straight runs; every covered px keeps at least 128 / 255 (nothing is uncovered)."""
    s = cv2.GaussianBlur(solid.astype(np.float32), (0, 0), sigma)
    out = np.clip((s - 0.5) * gain + 0.5, 0.0, 1.0)
    return np.where(solid, np.maximum(out, 128 / 255.0), np.minimum(out, 127 / 255.0)).astype(np.float32)


def smooth_edges(layer: np.ndarray) -> np.ndarray:
    """Round 17 edge finish (docs/06): the alpha edge of soft_coverage(alpha >= 128), nothing eroded; the colour
    under the outer fringe is grown from the nearest covered px."""
    solid = layer[:, :, 3] >= 128
    if not solid.any():
        return layer
    k = np.ones((3, 3), np.uint8)
    fill = layer[:, :, :3] * solid[:, :, None]
    known = solid
    for _ in range(3):
        grown = cv2.dilate(fill, k)
        fill = np.where(known[:, :, None], fill, grown)
        known = cv2.dilate(known.astype(np.uint8), k) > 0
    out = np.empty_like(layer)
    out[:, :, :3] = fill
    out[:, :, 3] = np.rint(soft_coverage(solid) * 255)
    return out


FINISH_ARM_NEAR = 12  # px around a finished layer where the arm overlay border is soft (finish "r17")
FORM_SHADE = 0.10  # darkening at the garment's left / right outline (form shading, round 17)
FORM_SHADE_LENGTH = 14.0  # px: the darkening falls to 1 / e this far inside the outline


def form_shading_map(alpha: np.ndarray, strength: float = FORM_SHADE, length: float = FORM_SHADE_LENGTH) -> np.ndarray:
    """HxW float32 shade (1 - strength .. 1) from the garment's own outline: each covered px is darkened by its
    horizontal distance to the end of its row run (a rounded body / sleeve), smoothed. Nothing is read from the
    avatar, so the avatar's own clothes cannot print through. 1.0 outside the garment."""
    cov = alpha >= 128
    idx = np.arange(alpha.shape[1], dtype=np.float32)[None, :]
    left = idx - np.maximum.accumulate(np.where(cov, -1.0, idx), axis=1)
    rev = idx - np.maximum.accumulate(np.where(cov[:, ::-1], -1.0, idx), axis=1)  # the same, from the right
    d = np.minimum(left, rev[:, ::-1])
    shade = 1.0 - strength * np.exp(-np.maximum(d - 1, 0) / length)
    shade = cv2.GaussianBlur(np.where(cov, shade, 1.0 - strength).astype(np.float32), (0, 0), 2.0)
    return np.where(alpha > 0, shade, 1.0).astype(np.float32)


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
# The T-shirt is one layer: torso, rigid sleeves (hard per-pixel ownership) and shoulder cap, composited first.
LAYER_ORDER = ("avatar", "pants", "tshirt_torso", "tshirt_sleeves", "shoulder_cap", "neck_gap_fill", "head_neck",
               "hands_forearms")


def _neck_hole_kwargs(g_img, glm, enabled, info) -> dict:
    """tshirt_layer keywords for the owner-drawn neckline hole (docs/09 #102, adapt and keep_shape since
    2026-11-13), or {} (the call as before)."""
    from apps.garments.landmark_checks import alpha_stats, neck_hole_polygon, neck_hole_problem
    if not enabled or neck_hole_polygon(glm) is None:
        return {}
    alpha = _bgra(g_img)[:, :, 3]
    bbox, area = alpha_stats(alpha)
    if neck_hole_problem(glm["neck_hole"], alpha.shape[1], alpha.shape[0], area, bbox):
        info["quality_warnings"].append("neck_hole_invalid")
        return {}
    return {"neckline_variant": "hole", "neck_hole_polygon": [list(p) for p in glm["neck_hole"]["polygon"]]}


def _mls_adapt_kwargs(cfg: dict) -> dict:
    """mls.tshirt_layer keywords of an adapt T-shirt for a tshirt_config (docs/09 #105). Every option off = {}."""
    kw = {}
    if cfg["side_floor"] == "mask":
        kw.update(side_floor=True, side_floor_mode="mask")
    if cfg["tube"]:
        kw.update(sleeve_mode="tube", tube_arm="finished")
    if cfg["armpit"] == "r14":
        kw["armpit_mode"] = "r14"
    if cfg["hem"] == "garment":
        kw["hem_mode"] = "garment"
    if cfg["cuff"] == "hem":  # docs/09 #106
        kw["cuff_mode"] = "hem"
    if cfg["fringe"] == "drop":
        kw["tube_fringe"] = "drop"
    return kw


PANTS_TUCK_TAPER = 10  # rows above the T-shirt's hem corner over which the pants widen back to their own edge
PANTS_TUCK_RELEASE = 40  # px the pants edge is let out across the taper
PANTS_TUCK_BODY = 3  # px around the figure that the pants always keep (nothing of the body is uncovered)


DRAPE_MARGIN = 2  # px the T-shirt's side reaches past the pants it hangs over
DRAPE_MAX = 1.35  # largest row stretch of a side; what is left beside the shirt is tucked (tuck_pants)
DRAPE_SIGMA = 6.0  # rows: the stretch is smoothed along y, the side line stays one curve


def _torso_runs(solid: np.ndarray, ax: int) -> tuple[np.ndarray, np.ndarray]:
    """Per row the (left, right) x of the solid run that holds the axis column; -1 where there is none."""
    H = solid.shape[0]
    left, right = np.full(H, -1), np.full(H, -1)
    for y in np.where(solid.any(axis=1))[0]:
        run = next((q for q in _runs(solid[y]) if q[0] <= ax <= q[1]), None)
        if run is not None:
            left[y], right[y] = run
    return left, right


def _drape_body_cap(half: np.ndarray, b_edge: np.ndarray, rows: np.ndarray, ax: int, sign: int,
                    margin: float) -> np.ndarray:
    """docs/09 #119: per-row largest drape stretch of one shirt side. The limit half-width is
    max(the MLS half-width, the figure's half-width + margin); the figure edge is smoothed along y (DRAPE_SIGMA) so the
    stretched side has no steps. Rows without a figure run through the axis are interpolated from their neighbours;
    rows outside the figure's run range get no stretch (cap 1)."""
    cap = np.ones(len(half))
    b_half = np.where(b_edge >= 0, (b_edge - ax) * sign, -1).astype(np.float64)
    have = np.where(b_half > 0)[0]
    if not len(rows) or not len(have):
        return cap
    y0, y1 = int(have[0]), int(have[-1]) + 1
    filled = np.interp(np.arange(y0, y1), have, b_half[have])
    smooth = cv2.GaussianBlur(filled.reshape(-1, 1), (1, 0), DRAPE_SIGMA, borderType=cv2.BORDER_REPLICATE)[:, 0]
    limit = np.zeros(len(half))
    limit[y0:y1] = smooth + margin
    limit = np.maximum(limit, half)  # never narrower than the MLS output: only extra stretch is blocked
    ok = half > 4
    cap[ok] = limit[ok] / half[ok]
    return cap


def drape_over_pants(shirt: np.ndarray, pants_alpha: np.ndarray, axis: float, mask: np.ndarray | None = None,
                     body_margin: float | None = None) -> tuple[np.ndarray, float]:
    """An untucked T-shirt hangs over the pants: on the rows where the pants are wider than the shirt, each half of
    the shirt row is stretched about the axis until its side covers the pants (+ DRAPE_MARGIN), at most DRAPE_MAX.
    The stretch is smoothed along y and held from the widest row down to the hem, so the hem is as wide as the row
    above it. Rows that need nothing keep their bytes. Coverage only grows. Returns (layer, largest stretch).
    mask + body_margin (setting TRYON_DRAPE_BODY_MARGIN, docs/09 #119; None = before #119): a side never reaches past
    max(its MLS edge, the smoothed figure edge + body_margin px) (`_drape_body_cap`); the pants left beside the shirt
    are tucked by tuck_pants."""
    H, W = pants_alpha.shape
    ax = int(np.clip(round(axis), 1, W - 2))
    sl, sr = _torso_runs(shirt[:, :, 3] >= 128, ax)
    pl, pr = _torso_runs(pants_alpha >= 128, ax)
    capped = mask is not None and body_margin is not None
    bl, br = _torso_runs(mask, ax) if capped else (None, None)
    scales = []
    for s_edge, p_edge, b_edge, sign in ((sl, pl, bl, -1), (sr, pr, br, 1)):
        half = np.where(s_edge >= 0, (s_edge - ax) * sign, 0).astype(np.float64)
        want = np.where((s_edge >= 0) & (p_edge >= 0), (p_edge - ax) * sign + DRAPE_MARGIN, 0)
        k = np.where((half > 4) & (want > half), want / np.maximum(half, 1), 1.0)
        rows = np.where(s_edge >= 0)[0]
        if len(rows) > 75:  # the hem's own rows (a curved hem narrows there) do not ask for a stretch of their own
            ref = np.median(half[rows[-60]:rows[-15]])
            side_rows = rows[half[rows] >= 0.97 * ref]
            k[(side_rows[-1] if len(side_rows) else rows[-15]) + 1:] = 1.0
        if len(rows) and (k > 1).any():
            k[np.argmax(k):rows[-1] + 1] = k.max()  # the hem keeps the widest row's stretch
            k = np.maximum(cv2.GaussianBlur(k.reshape(-1, 1), (1, 0), DRAPE_SIGMA, borderType=cv2.BORDER_REPLICATE)[:, 0], 1.0)
            k[rows[-1] + 1:] = 1.0
        k = np.clip(k, 1.0, DRAPE_MAX)
        if capped:
            k = np.maximum(np.minimum(k, _drape_body_cap(half, b_edge, rows, ax, sign, body_margin)), 1.0)
        scales.append(k)
    kl, kr = scales
    todo = np.where((kl > 1.001) | (kr > 1.001))[0]
    if not len(todo):
        return shirt, 1.0
    y0, y1 = int(todo[0]), int(todo[-1]) + 1
    xs = np.arange(W, dtype=np.float32)[None, :]
    c = ax + 0.5
    k = np.where(xs + 0.5 < c, kl[y0:y1, None], kr[y0:y1, None]).astype(np.float32)
    map_x = (c + (xs + 0.5 - c) / k - 0.5).astype(np.float32)
    map_y = np.repeat(np.arange(y0, y1, dtype=np.float32)[:, None], W, axis=1)
    f = shirt.astype(np.float32)
    f[:, :, :3] *= f[:, :, 3:4] / 255.0
    w = cv2.remap(f, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    a = w[:, :, 3:4] / 255.0
    w[:, :, :3] = np.where(a > 0, w[:, :, :3] / np.maximum(a, 1e-6), 0)
    out = shirt.copy()
    changed = (kl[y0:y1] > 1.001) | (kr[y0:y1] > 1.001)
    out[y0:y1][changed] = np.clip(np.rint(w), 0, 255).astype(np.uint8)[changed]
    return out, float(max(kl.max(), kr.max()))


def tuck_pants(pants: np.ndarray, shirt_alpha: np.ndarray, mask: np.ndarray, axis: float) -> tuple[np.ndarray, int]:
    """Pants worn under an untucked T-shirt: above the shirt's hem the pants do not show beside the shirt.
    Per side, a pants px left / right of the shirt's torso run is dropped down to the shirt's hem corner (the
    last PANTS_TUCK_TAPER rows widen back smoothly), unless it lies within PANTS_TUCK_BODY px of the figure: the
    body is never uncovered. Returns (pants layer, px dropped)."""
    H, W = shirt_alpha.shape
    solid = shirt_alpha >= 128
    ax = int(np.clip(round(axis), 0, W - 1))
    left, right = _torso_runs(solid, ax)
    ys = np.where(left >= 0)[0]
    if len(ys) < 2 * PANTS_TUCK_TAPER:
        return pants, 0
    y_bot = int(ys[-1])
    ref = ys[(ys >= y_bot - 60) & (ys <= y_bot - 15)]
    if not len(ref):
        return pants, 0
    k = 2 * PANTS_TUCK_BODY + 1
    body = cv2.dilate(mask.astype(np.uint8), np.ones((k, k), np.uint8)) > 0
    drop = np.zeros((H, W), bool)
    xs = np.arange(W)
    for side, edge in (("left", left), ("right", right)):
        x_ref = int(np.median(edge[ref]))
        col = int(np.clip(x_ref + (4 if side == "left" else -4), 0, W - 1))
        col_rows = np.where(solid[:, col])[0]
        corner = int(col_rows[-1]) if len(col_rows) else y_bot  # the hem's bottom row at this side
        for y in ys[ys <= corner]:
            t = _smooth((y - (corner - PANTS_TUCK_TAPER)) / PANTS_TUCK_TAPER)  # 0 above the taper, 1 at the corner
            if side == "left":
                drop[y] |= xs < edge[y] - t * PANTS_TUCK_RELEASE
            else:
                drop[y] |= xs > edge[y] + t * PANTS_TUCK_RELEASE
    drop &= (pants[:, :, 3] > 0) & ~body
    if not drop.any():
        return pants, 0
    out = pants.copy()
    out[drop] = 0
    return out, int(drop.sum())


def render_tryon(base: np.ndarray, body_lm: dict, garments: list, H: int = 1200, W: int = 600,
                 shading: bool = False, contact_shadows: bool = False, edge_feather: bool = False,
                 shading_strength: float = SHADING_STRENGTH, shoulder_cap: bool = True, hem_snap: bool = True,
                 halo_removal: bool = True, neck_fix: bool = True, neck_gap_fill: bool = True,
                 source: str = "body", dropped_shoulder_single: bool = False, hem_rule: bool = False,
                 hem_hip_fraction: float = 0.35, hem_crotch_margin: float = 10.0,
                 fit_modes: dict | None = None, warp_engine: str = "parts", neck_hole: bool = True,
                 mls_sleeve: str = "C", mls_tube: bool = False, mls_side_floor: str = "off",
                 mls_armpit: str = "off", mls_hem: str = "mls", mls_cuff: str = "chord", mls_fringe: str = "keep",
                 finish: str = "r60", finish_pants: bool = False, pants_tuck: bool = False,
                 mls_keep_scale: str = "shoulder", mls_tube_clip: str = "armhole", pants_engine: str = "rows",
                 drape_body_margin: float | None = None, mls_keep_neck: bool = True, pants_leg: str = "r26"):
    """base: BGR/BGRA image; garments: [(type, BGRA image, landmarks)]. Layers, bottom to top (LAYER_ORDER):
    avatar -> pants (from their own waist row down) -> the T-shirt: torso + rigid sleeves (each pixel from exactly
    one piece, sleeves clipped below the torso's shoulder slope line), halo removed once on the outer contour of
    that union, then the shoulder cap under it (shows only above the garment's top edge) -> neck-gap fill (skin
    over a tank collar left between the neck and the collar) -> the avatar's head/neck -> its hands/forearms.
    The realism effects are off by default (TRYON_SHADING / TRYON_CONTACT_SHADOW / TRYON_EDGE_FEATHER); the
    structural steps are on by default (TRYON_SHOULDER_CAP / TRYON_HEM_SNAP / TRYON_HALO_REMOVAL /
    TRYON_NECK_FIX / TRYON_NECK_GAP_FILL, see flags.render_flags). neck_fix: in the neck zone the T-shirt's inner
    back collar is made transparent (the avatar's neck shows), the head/neck edge is one smooth curve feathered
    about 3 px that keeps the front collar band visible, and the shoulder-edge alpha is smoothed.
    source: "avatar" (admin avatar photo) or "body" (the user's own photo, the default: fail closed). The neck-gap
    fill paints over the avatar's own clothes, so it runs for avatars only, never for an own body whatever the flag
    (docs/02 rule 12, docs/09 #89).
    dropped_shoulder_single: TRYON_DROPPED_SHOULDER_SINGLE (default 0, docs/09 #90): dropped-shoulder T-shirts as
    one piece. Off by default: below the armpit row the sleeves shear into stepped blocks (docs/06 "Known limits").
    hem_rule (TRYON_HEM_RULE, default 1 in settings, False here so direct calls keep the garment's own length): the
    T-shirt hem lands on hip + hem_hip_fraction x (crotch - hip), at most crotch - hem_crotch_margin (docs/09 #91).

    fit_modes: {garment type: "adapt" | "keep_shape"} (Garment.fit_mode, docs/09 #93). Used only by the MLS engine.
    warp_engine (setting TRYON_WARP, docs/09 #98): "parts" (default: torso row warp + rigid sleeves, fit_modes
    ignored) or "mls" for the T-shirt (apps/tryon_engine/mls.py: keep_shape -> preset A, adapt -> fitted at k 1.0).
    When MLS cannot run (missing landmarks, failed core pairs) the T-shirt falls back to "parts" and
    debug["quality_warnings"] gets "mls_fallback". Pants always use their own warp. debug["engine"] = the engine
    the T-shirt actually used ("parts" when there is no T-shirt).
    mls_sleeve (setting TRYON_MLS_SLEEVE, default "C", docs/09 #104): the MLS sleeve variant (adapt only).
    Adapt T-shirts on MLS (docs/09 #105; the settings default to the first value, the defaults here are the off values
    so direct calls keep the behaviour before #105; keep_shape ignores all four and is called as before):
    mls_tube (TRYON_MLS_TUBE): tube sleeves "finished" (docs/06 rounds 11-13b). When the tube skips a side the
    T-shirt is rendered again with MLS sleeves (and without the armpit mode) and gets quality warning "tube_fallback".
    mls_side_floor (TRYON_MLS_SIDE_FLOOR) "mask" | "off": the side coverage floor from the figure mask (round 12 / 12b).
    mls_armpit (TRYON_MLS_ARMPIT) "r14" | "off": the torso seam on the arm/torso boundary (round 14); needs the tube
    and the side floor, otherwise it is off. mls_hem (TRYON_MLS_HEM) "garment" | "mls": the garment's own hem shape
    (round 12b) or no hem post-processing. Tube sleeves only (docs/09 #106, off without the tube): mls_cuff
    (TRYON_MLS_CUFF) "hem" | "chord": the garment's real sleeve hem lands on the cuff line (round 15); mls_fringe
    (TRYON_MLS_FRINGE) "drop" | "keep": the tube's photo-fringe px over solid fabric are not drawn (round 16).
    debug["tshirt_config"] = what was actually used: {fit_mode, engine, sleeve, tube, side_floor, armpit, hem, cuff,
    fringe} (engine "parts": {fit_mode, engine} only).
    neck_hole (setting TRYON_NECK_HOLE, docs/09 #102): MLS only, adapt and keep_shape. When the T-shirt landmarks carry
    `neck_hole.polygon` and it passes landmark_checks.neck_hole_problem (same rules as PATCH), the MLS layer is made
    with neckline_variant="hole" + that polygon (never neck_clip); a failing polygon is skipped with quality warning
    "neck_hole_invalid". parts and neck_hole=False ignore the polygon. debug["neck_hole"] = used or not.

    finish (setting TRYON_FINISH, docs/09 #107, docs/06 "Finish pass, round 17"; the default here is the off value):
    "r60" = the realism effects as before, on every garment layer; "r17" = the effects that are on apply to the
    T-shirt layer (and to the pants layer with finish_pants; without it pants are composited plain, exactly as with
    every effect off) and work differently:
    edge_feather = smooth_edges (nothing eroded) and a soft border of the arm overlay within FINISH_ARM_NEAR px of
    a finished layer; shading = form_shading_map (from the garment's outline, the avatar's luminance is not read);
    contact_shadows also falls on the arm below the cuff. debug["finish"] = "r17" when a layer got it, else
    "off"; debug["tshirt_final"] = the T-shirt layer as composited, debug["arm_weight"] = the arm overlay weight.
    finish_pants (setting TRYON_FINISH_PANTS, docs/09 #108, docs/06 "Finish pass on pants, round 17b"; the default
    here is the off value): finish "r17" also on the pants layer. debug["final_layers"] = {garment type: the layer as composited}.
    pants_engine (setting TRYON_PANTS_ENGINE, docs/09 #114; the default here is the off value): "fit" =
    warp_pants_fit (one horizontal factor, legs on the body leg's line) | "rows" = warp_pants (round 26 fit model,
    docs/09 #120: the waist -> crotch block on the body + ease, legs opening to their own width, halo by pants_edge).
    mls_tube_clip (setting TRYON_MLS_TUBE_CLIP, docs/09 #113; the default here is the off value): "arm" = a tube
    sleeve is not drawn on the torso side of the arm/torso boundary below the armpit row where the MLS layer has
    solid fabric; `tshirt_config.tube_clip` is then "arm".
    mls_keep_scale (setting TRYON_MLS_KEEP_SCALE, docs/09 #112; the default here is the off value): "fit" = a
    keep_shape MLS T-shirt is scaled by mls.keep_shape_scale; `tshirt_config.keep_scale` is then "fit".
    pants_tuck (setting TRYON_PANTS_TUCK, docs/09 #109; the default here is the off value): MLS T-shirt + pants: the
    adapt T-shirt hangs over the pants: its sides are stretched to cover them (drape_over_pants) and what is still
    beside it above the hem is dropped unless it lies on the figure (tuck_pants). keep_shape is not touched.
    debug["pants_drape"] = largest row stretch, debug["pants_tuck_px"] = pants px dropped.
    pants_leg (setting TRYON_PANTS_LEG, docs/09 #122; the default here is the off value "r26"): "smooth" = rows
    pants legs without the knee bend (warp_pants leg_mode).
    drape_body_margin (setting TRYON_DRAPE_BODY_MARGIN, docs/09 #119; the default here is the off value None): the
    drape stops at max(the MLS edge, the smoothed figure edge + this many px).
    mls_keep_neck (docs/09 #121, no setting: the default True is production): keep_shape MLS T-shirts move down so the
    collar line sits on the regular T-shirts' row, shoulders bound to the body (mls.keep_neck_pairs);
    `tshirt_config.keep_neck_dy`. False = before #121 (only the frozen regression fixtures use it).

    Returns (BGR uint8 HxWx3 on white, warnings: [str], debug: dict).
    """
    if warp_engine not in ("parts", "mls"):
        raise ValueError(f"unknown warp engine: {warp_engine!r}")
    if finish not in ("r60", "r17"):
        raise ValueError(f"unknown finish: {finish!r}")
    if mls_side_floor not in ("mask", "off") or mls_armpit not in ("r14", "off") or mls_hem not in ("garment", "mls") \
            or mls_cuff not in ("hem", "chord") or mls_fringe not in ("drop", "keep"):
        raise ValueError(f"unknown MLS T-shirt option: {mls_side_floor!r}, {mls_armpit!r}, {mls_hem!r}, "
                         f"{mls_cuff!r}, {mls_fringe!r}")
    fit_modes = fit_modes or {}
    base = cv2.resize(_bgra(base), (W, H))
    mask = figure_mask(base)
    canvas = base.copy()  # base alpha kept as is: forcing 255 inside the mask showed a grey halo at soft edges
    arms = find_arms(mask, body_lm)
    warnings, info = [], {"engine": "parts", "quality_warnings": []}
    by_type = {t: (img, lm) for t, img, lm in garments if t in ("tshirt", "pants")}
    layers = []
    if "pants" in by_type:
        warped, warns = garment_layer("pants", *by_type["pants"], body_lm, H, W, arms, info, mask,
                                      halo_removal=halo_removal,
                                      **({"engine": "fit"} if pants_engine == "fit" else {"leg_mode": pants_leg}))
        warnings += [f"pants: {w}" for w in warns]
        layers.append(("pants", warped))
    opening = None
    mls_layer = None
    info["neck_hole"] = False
    if "tshirt" in by_type and warp_engine == "mls":
        from . import mls as mls_engine
        hole_kw = _neck_hole_kwargs(*by_type["tshirt"], neck_hole, info)
        fit = fit_modes.get("tshirt", "adapt")
        cfg = {"fit_mode": fit, "engine": "mls", "sleeve": None, "tube": False, "side_floor": "off", "armpit": "off",
               "hem": "mls", "cuff": "chord", "fringe": "keep"}
        adapt_kw = {}
        if fit == "keep_shape" and mls_keep_scale != "shoulder":  # docs/09 #112
            adapt_kw = {"keep_scale": mls_keep_scale}
            cfg["keep_scale"] = mls_keep_scale
        if fit == "keep_shape" and mls_keep_neck:  # docs/09 #121: the collar on the regular T-shirts' row
            adapt_kw = {**adapt_kw, "keep_neck": True}
        if fit != "keep_shape":  # docs/09 #105; keep_shape is called exactly as before
            cfg.update(sleeve=mls_sleeve, tube=bool(mls_tube), side_floor=mls_side_floor, hem=mls_hem,
                       armpit=mls_armpit if mls_tube and mls_side_floor == "mask" else "off",
                       cuff=mls_cuff if mls_tube else "chord", fringe=mls_fringe if mls_tube else "keep")
            adapt_kw = _mls_adapt_kwargs(cfg)
            if cfg["tube"] and mls_tube_clip != "armhole":  # docs/09 #113
                adapt_kw["tube_clip"] = mls_tube_clip
                cfg["tube_clip"] = mls_tube_clip
        try:
            mls_layer, mls_info = mls_engine.tshirt_layer(
                *by_type["tshirt"], body_lm, mask, fit, H, W,
                (hem_hip_fraction, hem_crotch_margin), sleeve_variant=mls_sleeve, **adapt_kw, **hole_kw)
            skipped = [s for s, r in (mls_info.get("tube") or {}).items() if isinstance(r, dict) and "skipped" in r]
            if skipped:  # the tube could not be built on a side: the whole T-shirt with MLS sleeves
                cfg.update(tube=False, armpit="off", cuff="chord", fringe="keep")
                info["quality_warnings"].append("tube_fallback")
                warnings.append(f"tshirt: tube fallback to MLS sleeves ({', '.join(skipped)}: "
                                f"{mls_info['tube'][skipped[0]]['skipped']})")
                mls_layer, mls_info = mls_engine.tshirt_layer(
                    *by_type["tshirt"], body_lm, mask, fit, H, W,
                    (hem_hip_fraction, hem_crotch_margin), sleeve_variant=mls_sleeve, **_mls_adapt_kwargs(cfg),
                    **hole_kw)
            if "keep_neck_dy" in mls_info:
                cfg["keep_neck_dy"] = mls_info["keep_neck_dy"]
            info["tshirt_config"] = cfg
            info["neck_hole"] = bool(hole_kw)
            info.update(engine="mls", mls=mls_info, sleeve_hems=mls_info["sleeve_hems"])
            warnings += [f"tshirt: mls dropped {r}" for r in mls_info["rejected"]]
        except mls_engine.MlsUnavailable as e:
            info["quality_warnings"].append("mls_fallback")
            warnings.append(f"tshirt: mls fallback to parts: {e}")
    info["pants_tuck_px"], info["pants_drape"] = 0, 1.0
    if pants_tuck and mls_layer is not None and "pants" in by_type \
            and fit_modes.get("tshirt", "adapt") != "keep_shape":  # docs/09 #109 (parts widens the shirt itself)
        mls_layer, info["pants_drape"] = drape_over_pants(mls_layer, layers[0][1][:, :, 3], _crotch_x(body_lm),
                                                          mask, drape_body_margin)
        tucked, info["pants_tuck_px"] = tuck_pants(layers[0][1], mls_layer[:, :, 3], mask, _crotch_x(body_lm))
        layers[0] = ("pants", tucked)
    if mls_layer is not None:
        opening = info["mls"].get("neck_opening") if neck_fix else None
        head = head_neck_overlay(mask, body_lm, NECK_FEATHER_FIX if neck_fix else NECK_FEATHER, opening)
        info["tshirt_layer"] = mls_layer
        layers.append(("tshirt", mls_layer))
    elif "tshirt" in by_type:
        info["tshirt_config"] = {"fit_mode": fit_modes.get("tshirt", "adapt"), "engine": "parts"}
        hem_over, under = None, None
        if "pants" in by_type:
            under = layers[0][1][:, :, 3] > 128
            if hem_snap:  # the hem overlaps the waistband: no gap line between them
                hem_over = info["pants_waist_y"] + info["pants_top_dip"] + HEM_OVER_WAISTBAND
        warped, warns = garment_layer("tshirt", *by_type["tshirt"], body_lm, H, W, arms, info, mask,
                                      halo_removal=halo_removal, hem_over=hem_over, under=under,
                                      dropped_single=dropped_shoulder_single,
                                      hem_rule=(hem_hip_fraction, hem_crotch_margin) if hem_rule else None)
        warnings += [f"tshirt: {w}" for w in warns]
        opening = info.get("neck_opening") if neck_fix else None
        head = head_neck_overlay(mask, body_lm, NECK_FEATHER_FIX if neck_fix else NECK_FEATHER, opening)
        if neck_fix:
            warped = smooth_shoulder_alpha(clear_back_collar(warped, opening, body_lm), body_lm)
        if shoulder_cap:
            skip = (opening["cx"] - opening["hw"] / (1 - OPENING_INSET) - 2,
                    opening["cx"] + opening["hw"] / (1 - OPENING_INSET) + 2) if opening else None
            cap = shoulder_cap_layer(warped, mask, body_lm, head, info.get("tshirt_shoulders"), skip)
            info["shoulder_cap"] = cap
            warped = _alpha_composite(cap, warped)  # the cap only shows where the garment does not
        info["tshirt_layer"] = warped
        layers.append(("tshirt", warped))
    else:
        head = head_neck_overlay(mask, body_lm, NECK_FEATHER_FIX if neck_fix else NECK_FEATHER)
    r17 = finish == "r17"
    arm_dark = np.zeros((H, W), np.float32)
    info["finish"] = "off"
    info["final_layers"] = {}
    finished = np.zeros((H, W), bool)  # px of the layers that got finish "r17"
    for gtype, warped in layers:
        if r17 and gtype != "tshirt" and not finish_pants:  # docs/09 #107: pants as with every effect off
            info["final_layers"][gtype] = warped
            canvas = _alpha_composite(canvas, warped)
            continue
        if r17 and (edge_feather or shading or contact_shadows):
            info["finish"] = "r17"
            finished |= warped[:, :, 3] > 0
        if edge_feather:
            warped = smooth_edges(warped) if r17 else soften_edges(warped)
        if shading and r17:
            warped = apply_shading(warped, form_shading_map(warped[:, :, 3]), 1.0)
        elif shading:
            warped = apply_shading(warped, shading_map(base, mask & (warped[:, :, 3] > 0)), shading_strength)
        if contact_shadows:
            dark = contact_shadow(warped[:, :, 3], mask, _crotch_x(body_lm))
            canvas[:, :, :3] = (canvas[:, :, :3].astype(np.float32) * (1 - dark[:, :, None])).astype(np.uint8)
            arm_dark = np.maximum(arm_dark, dark)
        if gtype == "tshirt":
            info["tshirt_final"] = warped
        info["final_layers"][gtype] = warped
        canvas = _alpha_composite(canvas, warped)
    if neck_gap_fill and source == "avatar" and "tshirt_layer" in info and info["engine"] == "parts":
        canvas, info["neck_gap"] = neck_gap_fill_fn(canvas, base, mask, body_lm, head,
                                                    info["tshirt_layer"][:, :, 3], opening)
    info["head_overlay"] = head

    head = head[:, :, None]  # head and neck always above the garment
    canvas = np.clip(np.rint(canvas.astype(np.float32) * (1 - head) + base.astype(np.float32) * head),
                     0, 255).astype(np.uint8)
    keep = arm_overlay_mask(mask, arms, info.get("sleeve_hems"))
    info["arm_weight"] = keep.astype(np.float32)
    if r17 and (edge_feather or contact_shadows) and finished.any():
        arm_px = base.astype(np.float32)
        if contact_shadows:  # the cuff's shadow on the arm (the plain overlay would paste the unshaded arm back)
            arm_px[:, :, :3] *= (1 - arm_dark)[:, :, None]
        if edge_feather:  # soft only beside a finished layer: the hands over plain pants stay a plain paste
            k = 2 * FINISH_ARM_NEAR + 1
            near = cv2.dilate(finished.astype(np.uint8), np.ones((k, k), np.uint8)) > 0
            info["arm_weight"] = np.where(near, soft_coverage(keep) * mask, keep).astype(np.float32)
        wgt = info["arm_weight"][:, :, None]
        canvas = np.clip(np.rint(canvas.astype(np.float32) * (1 - wgt) + arm_px * wgt), 0, 255).astype(np.uint8)
    else:
        canvas[keep] = base[keep]
    for side in ("left", "right"):
        if not arms.get(side):
            warnings.append(f"arm {side}: not separated from the body in the mask, hands may be covered")

    white = np.full((H, W, 3), 255, np.float32)
    a = canvas[:, :, 3:4].astype(np.float32) / 255.0
    rgb = (canvas[:, :, :3].astype(np.float32) * a + white * (1 - a)).astype(np.uint8)
    return rgb, warnings, {"arms": arms, "arm_mask": keep, **info}
