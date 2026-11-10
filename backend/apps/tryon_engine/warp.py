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


def _segment_warning(label, src0, src1, dst0, dst1, warnings):
    """src/dst rows (y, lx, rx). Warn when the horizontal and vertical scale of the segment differ too much."""
    sh_src = ((src0[2] - src0[1]) + (src1[2] - src1[1])) / 2
    sh_dst = ((dst0[2] - dst0[1]) + (dst1[2] - dst1[1])) / 2
    sv_src, sv_dst = src1[0] - src0[0], dst1[0] - dst0[0]
    if sh_src <= 0 or sv_src <= 0 or sv_dst <= 0:
        return
    ratio = (sh_dst / sh_src) / (sv_dst / sv_src)
    if ratio > DISTORT_LIMIT or ratio < 1 / DISTORT_LIMIT:
        warnings.append(f"{label}: distorted {ratio:.2f}x (wider)" if ratio > 1 else f"{label}: distorted {1 / ratio:.2f}x (taller)")


def _scanline_strip(src: np.ndarray, src_rows: list, dst_rows: list, H: int, W: int,
                    warnings: list, label: str) -> np.ndarray:
    """Map each src row span onto the dst row span, linearly between consecutive (y, lx, rx) rows."""
    result = np.zeros((H, W, 4), dtype=np.uint8)
    for seg in range(len(src_rows) - 1):
        sy0, slx0, srx0 = src_rows[seg]
        sy1, slx1, srx1 = src_rows[seg + 1]
        dy0, dlx0, drx0 = dst_rows[seg]
        dy1, dlx1, drx1 = dst_rows[seg + 1]
        _segment_warning(f"{label}[{seg}]", src_rows[seg], src_rows[seg + 1], dst_rows[seg], dst_rows[seg + 1], warnings)
        dy_span = dy1 - dy0 if dy1 != dy0 else 1
        for dst_y in range(int(round(dy0)), int(round(dy1)) + 1):
            if dst_y < 0 or dst_y >= H:
                continue
            t = (dst_y - dy0) / dy_span
            src_y = min(max(int(round(sy0 + t * (sy1 - sy0))), 0), src.shape[0] - 1)
            src_lx, src_rx = slx0 + t * (slx1 - slx0), srx0 + t * (srx1 - srx0)
            dst_lx, dst_rx = int(round(dlx0 + t * (dlx1 - dlx0))), int(round(drx0 + t * (drx1 - drx0)))
            dst_width = max(dst_rx - dst_lx, 1)
            sl, sr = max(0, int(src_lx)), min(src.shape[1], int(src_rx) + 1)
            if sr <= sl:
                continue
            # resize premultiplied: the colour under transparent neighbours must not darken edge pixels
            srow = src[src_y, sl:sr].astype(np.float32)
            srow[:, :3] *= srow[:, 3:4] / 255.0
            row = cv2.resize(srow.reshape(1, -1, 4), (dst_width, 1), interpolation=cv2.INTER_LINEAR)[0]
            ra = row[:, 3:4] / 255.0
            row[:, :3] = np.where(ra > 0, row[:, :3] / np.maximum(ra, 1e-6), 0)
            x0, x1 = max(dst_lx, 0), min(dst_rx, W)
            if x1 <= x0:
                continue
            r0 = x0 - dst_lx
            r1 = min(r0 + (x1 - x0), row.shape[0])
            x1 = x0 + (r1 - r0)
            if r1 <= r0:
                continue
            piece = row[r0:r1].astype(np.float32)
            out = _over(result[dst_y, x0:x1].astype(np.float32), piece)
            result[dst_y, x0:x1] = np.clip(np.rint(out), 0, 255).astype(np.uint8)
    return result


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
SLEEVE_OVERLAP = 4  # px the rigid sleeve reaches into the torso / above the shoulder cap (no skin wedge)
NECK_MARGIN = 6  # px each side of the neck landmark width that the head/neck overlay covers
NECK_FEATHER = 1.5  # px sigma of the head/neck overlay edge


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


def warp_tshirt(body_lm: dict, garment_lm: dict, garment_img: np.ndarray, H: int, W: int,
                arms: dict | None = None, info: dict | None = None,
                mask: np.ndarray | None = None) -> tuple[np.ndarray, list]:
    """T-shirt keeps its own silhouette (docs/06 "T-shirt fit"): one uniform scale s for both axes, set so the
    garment's shoulder line = body shoulder + ease; below the shoulders every row is max(garment, body + ease)
    (capped), blended in from the shoulder fit by the chest row; the hem is the garment's own (scaled) length.
    Sleeves are rigid pieces along the upper arm, reaching a few px into the torso so no skin wedge shows."""
    warnings: list[str] = []
    g, a = garment_lm, body_lm
    img = _bgra(garment_img)
    gh = img.shape[0]
    alpha = img[:, :, 3] > 128

    g_sl, g_sr = _f(g["shoulder"]["left_x"]), _f(g["shoulder"]["right_x"])
    a_sl, a_sr = _f(a["shoulder"]["left_x"]), _f(a["shoulder"]["right_x"])
    s = (a_sr - a_sl) * (1 + TSHIRT_EASE) / (g_sr - g_sl)  # uniform: widths AND lengths
    g_cx, a_cx = (g_sl + g_sr) / 2, (a_sl + a_sr) / 2
    g_sy, a_sy = _f(g["shoulder"]["y"]), _f(a["shoulder"]["y"])
    to_dst = lambda gy: a_sy + (gy - g_sy) * s  # noqa: E731
    to_src = lambda dy: g_sy + (dy - a_sy) / s  # noqa: E731
    g_rows = [(_f(g[k]["y"]), _f(g[k]["left_x"]), _f(g[k]["right_x"])) for k in ("shoulder", "chest", "waist", "hem")]

    hem_y = to_dst(min(_f(g["hem"]["y"]), gh - 1.0))  # the garment's own length: crop tops stay short
    hem_max = _f(a["crotch"]["y"]) + MAX_SHIRT_BELOW_CROTCH * (_f(a["knee"]["y"]) - _f(a["crotch"]["y"]))
    if hem_y > hem_max:  # cut, never squeeze
        warnings.append(f"hem: garment is {hem_y - hem_max:.0f} px too long for this body, cut at the limit")
        hem_y = hem_max
    chest_dst = to_dst(_f(g["chest"]["y"]))

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

    src_rows, dst_rows, worst = [], [], 1.0
    # collar / neckline above the shoulder line: uniform scale, centred on the body (no fitting)
    top = np.where(alpha[:, max(int(g_sl), 0):int(g_sr) + 1].any(axis=1))[0]
    if len(top) and g_sy - top[0] > 2:
        for sy in np.arange(float(top[0]), g_sy, 3.0):
            span = _alpha_span(alpha, sy, g_sl, g_sr)
            if span:
                src_rows.append((sy, float(span[0]), float(span[1])))
                dst_rows.append((to_dst(sy), a_cx + (span[0] - g_cx) * s, a_cx + (span[1] - g_cx) * s))
    sep_y = _f(a["armpit"]["y"])  # below this the arms are separate in the mask: the torso run is the body
    axis = _crotch_x(a)
    for y in _ys(a_sy, hem_y):
        sy = to_src(y)
        sl, sr = _interp_span(g_rows, sy)
        bl, br = body_span(a, y)
        bw = br - bl
        w = tshirt_row_width((sr - sl) * s, bw, (y - a_sy) / max(chest_dst - a_sy, 1e-6))
        c = (1 - t_loose) * (bl + br) / 2 + t_loose * a_cx  # tight follows the torso, loose hangs straight
        l, r = c - w / 2, c + w / 2
        if mask is not None and y > sep_y:  # the avatar's own top/shorts never show at the sides
            run = next((q for q in _runs(mask[min(int(y), H - 1)]) if q[0] <= axis <= q[1]), None)
            if run and run[1] - run[0] < PANTS_MAX_BODY * bw:
                l, r = min(l, run[0] - 2), max(r, run[1] + 2)
        src_rows.append((sy, sl, sr))
        dst_rows.append((y, l, r))
        if y >= chest_dst and sr - sl > 1:
            ratio = (r - l) / ((sr - sl) * s)
            worst = ratio if abs(np.log(ratio)) > abs(np.log(worst)) else worst
    if worst > PANTS_DISTORT_LIMIT or worst < 1 / PANTS_DISTORT_LIMIT:
        warnings.append(f"torso: distorted {max(worst, 1 / worst):.2f}x ({'wider' if worst > 1 else 'narrower'})")
    result = _scanline_strip(img, src_rows, dst_rows, H, W, [], "torso")
    torso = [r for r in dst_rows if r[0] >= a_sy]

    def torso_edge(side, y):
        l, r = _interp_span(torso, y)
        return l if side == "left" else r

    # Sleeves: rigid (uniform s + rotation onto the upper arm), attached at the shoulder. The body's armpit
    # landmark is NOT used (it marks where the arms separate in the mask, far below the anatomical armpit).
    hems = {}
    for side in ("left", "right"):
        S_g = np.array([_f(g["shoulder"][f"{side}_x"]), g_sy])
        A_g = np.array([_f(g["chest"][f"{side}_x"]), _f(g["chest"]["y"])])
        E_g = np.array([_f(g["sleeve_end"][side]["x"]), _f(g["sleeve_end"][side]["y"])])
        S_b = np.array([a_sl if side == "left" else a_sr, a_sy])
        S_b[0] += (-1 if side == "left" else 1) * (a_sr - a_sl) * TSHIRT_EASE / 2
        v_g = E_g - S_g
        arm = (arms or {}).get(side)
        edge = None
        if mask is not None:
            reach = float(np.linalg.norm(v_g)) * s * SLEEVE_HEM_EXTEND * 1.2
            edge = outer_edge_line(mask, side, a_sy + 3, a_sy + reach)
        if edge:  # outer sleeve edge along the figure's outer edge (deltoid, then the upper arm)
            d = np.array([edge[0], 1.0])
            S_b[0] = min(S_b[0], edge[0] * a_sy + edge[1]) if side == "left" else max(S_b[0], edge[0] * a_sy + edge[1])
        elif arm:
            d = np.array([arm["slope"], 1.0])
        else:
            d = v_g.copy()
            warnings.append(f"sleeve {side}: arm not found in the mask, garment angle used")
        d = d / np.linalg.norm(d)
        theta = np.arctan2(d[1], d[0]) - np.arctan2(v_g[1], v_g[0])
        R = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]]) * s

        along = v_g * SLEEVE_HEM_EXTEND
        q = [R @ (c - S_g) for c in (S_g, S_g + along, A_g + along, A_g)]
        k = 1.0
        if arm:  # longer than allowed on this arm: shorten along the axis (never stretch)
            limit_y = a_sy + SLEEVE_MAX_ARM * (arm["end_y"] - a_sy)
            for qi in q:
                ad = float(qi @ d)
                if a_sy + qi[1] > limit_y and ad * d[1] > 1e-6:
                    k = min(k, (limit_y - a_sy - (qi[1] - ad * d[1])) / (ad * d[1]))
            k = max(k, 0.2)
            if k < 0.98:
                warnings.append(f"sleeve {side}: shortened to {k:.0%} to end half way down the arm")
        Kd = np.eye(2) + (k - 1) * np.outer(d, d)
        Mlin = Kd @ R
        quad = [S_b + Kd @ qi for qi in q]  # S, hem top, hem bottom, armhole bottom (dst)
        # Overlap: the armhole edge reaches inward past the torso edge (+SLEEVE_OVERLAP) and the cap upward,
        # sampling the garment's own fabric rigidly, so no skin wedge shows between sleeve and torso.
        inward = 1.0 if side == "left" else -1.0
        gap = 0.0
        for u in np.linspace(0, 1, 9):
            p = quad[0] + u * (quad[3] - quad[0])
            if a_sy <= p[1] <= hem_y:
                gap = max(gap, inward * (torso_edge(side, p[1]) - p[0]))
        reach_in = np.array([inward * (gap + SLEEVE_OVERLAP), 0.0])
        cap = -d * SLEEVE_OVERLAP
        poly = [quad[0] + reach_in + cap, quad[1] + cap, quad[2], quad[3] + reach_in]
        M = np.hstack([Mlin, (S_b - Mlin @ S_g).reshape(2, 1)]).astype(np.float32)
        warped = cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        piece = np.zeros((H, W), np.uint8)
        cv2.fillPoly(piece, [np.round(np.array(poly)).astype(np.int32)], 255)
        warped[:, :, 3] = np.where(piece > 0, warped[:, :, 3], 0)
        result = _alpha_composite(result, warped)
        hems[side] = (np.float32(quad[1]), np.float32(quad[2]), S_b)

    if info is not None:
        info["sleeve_hems"] = hems
        info["tshirt_rows"] = torso
    return result, warnings


def head_neck_overlay(base_mask: np.ndarray, lm: dict) -> np.ndarray:
    """HxW float weight (0..1) of the avatar's head and neck drawn ON TOP of the garment: figure pixels above the
    neck landmark row, within the neck width + NECK_MARGIN, feathered. Ghost-mannequin collars never cover them."""
    n = lm.get("neck")
    out = np.zeros(base_mask.shape, np.float32)
    if not n:
        return out
    y = int(round(_f(n["y"])))
    lx, rx = _f(n["left_x"]) - NECK_MARGIN, _f(n["right_x"]) + NECK_MARGIN
    out[:max(y, 0), max(int(lx), 0):int(rx) + 1] = 1.0
    out = cv2.GaussianBlur(out, (0, 0), NECK_FEATHER)
    return out * base_mask


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


def warp_pants(body_lm: dict, garment_lm: dict, garment_img: np.ndarray, H: int, W: int,
               arms: dict | None = None, info: dict | None = None,
               mask: np.ndarray | None = None) -> tuple[np.ndarray, list]:
    """Pants keep their own silhouette: one uniform scale for both axes (waist..hem vs the body's waist..ankle,
    or the rise for shorter pants). Only the waistband is fitted to the body; below the hip each row is
    pants_width(garment, body). Each leg is centred on the body's leg centreline (crotch -> knee -> ankle)."""
    warnings: list[str] = []
    g, a = garment_lm, body_lm
    img = _bgra(garment_img)

    g_wy, a_wy = _f(g["waist"]["y"]), _f(a["waist"]["y"])
    g_cr, a_cr = _f(g["crotch"]["y"]), _f(a["crotch"]["y"])
    g_hy = _f(g["hip"]["y"])
    legs = ("left_leg", "right_leg")
    g_hem_y = sum(_f(g["hem"][leg]["y"]) for leg in legs) / 2
    a_ank_y = sum(_f(a["ankle"][leg]["y"]) for leg in legs) / 2
    fig_h = _f(a.get("foot_bottom", {}).get("y", H - 50)) - _f(a.get("head_top", {}).get("y", 50))
    s_rise = (a_cr - a_wy) / (g_cr - g_wy)
    full = a_wy + (g_hem_y - g_wy) * s_rise >= a_ank_y - FULL_LENGTH_TOLERANCE * fig_h
    s = (a_ank_y - a_wy) / (g_hem_y - g_wy) if full else s_rise
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
    for y in _ys(a_wy, cr_dst):
        sy = g_wy + (y - a_wy) / s
        sl, sr = _interp_span(g_rows, sy)
        bl, br = body_span(a, y)
        t = (y - a_wy) / max(hip_dst - a_wy, 1e-6)
        w = waist_blend_width((sr - sl) * s, br - bl, t) if t < 1 else pants_width((sr - sl) * s, br - bl)
        c = (bl + br) / 2
        src_rows.append((sy, sl, sr))
        dst_rows.append((y, c - w / 2, c + w / 2))
        if t >= 1:
            track("waist-crotch", sr - sl, w)
    result = _scanline_strip(img, src_rows, dst_rows, H, W, [], "waist-crotch")
    result = curve_waistband(result, a_wy, hip_dst, dst_rows[0][1], dst_rows[0][2])
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
        for y in _ys(cr_dst, hem_dst):
            sy = g_cr + (y - cr_dst) * s_leg
            sl, sr = _interp_span(leg_src, sy)
            bl, br = _interp_span(body_rows, y)
            # tight: through the knee; loose: smooth monotonic curve; blended by the garment's looseness
            c = (1 - fit["t"]) * leg_centerline(y, *centre_pts, 1.0) + \
                fit["t"] * leg_centerline(y, *centre_pts, LOOSE_KNEE_PULL)
            run = _leg_run(mask, int(y), side, a_cx, (bl + br) / 2) if mask is not None else None
            bw = (run[1] - run[0]) if run else br - bl
            c = wb * c + (1 - wb) * drop_x
            w = pants_width((sr - sl) * s, bw, cap_ref=knee_bw if y > a_kn_y else None)
            l, r = c - w / 2, c + w / 2
            if run:  # the body's leg in the mask is always covered
                l, r = min(l, run[0] - 2), max(r, run[1] + 2)
            k = 1 - _smooth((y - cr_dst) / max(knee_dst - cr_dst, 1e-6))  # join the waist block at the crotch
            l, r = k * top[0] + (1 - k) * l, k * top[1] + (1 - k) * r
            src_rows.append((sy, sl, sr))
            dst_rows.append((y, l, r))
            if k < 0.5:
                track(f"{side}-leg", sr - sl, r - l)
        strip = _scanline_strip(img, src_rows, dst_rows, H, W, [], f"{side}-leg")
        result = _alpha_composite(result, strip)

    for label, r in worst.items():
        if r > PANTS_DISTORT_LIMIT or r < 1 / PANTS_DISTORT_LIMIT:
            warnings.append(f"{label}: distorted {max(r, 1 / r):.2f}x ({'wider' if r > 1 else 'narrower'})")
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


def _colour_from_nearest_opaque(img: np.ndarray, where: np.ndarray) -> None:
    """In place: RGB of `where` pixels from the nearest fully opaque pixel. Warped layers keep black under alpha 0,
    so up-scaled soft edges and holes are darkened; this removes that dark ring/spot."""
    ok = img[:, :, 3] >= 250
    if not where.any() or not ok.any():
        return
    _, labels = cv2.distanceTransformWithLabels((~ok).astype(np.uint8), cv2.DIST_L2, 3,
                                                labelType=cv2.DIST_LABEL_PIXEL)
    oy, ox = np.nonzero(ok)  # DIST_LABEL_PIXEL numbers the zero (= ok) pixels 1.. in raster order
    idx = labels[where] - 1
    img[:, :, :3][where] = img[oy[idx], ox[idx], :3]


def garment_layer(gtype: str, gimg: np.ndarray, glm: dict, body_lm: dict, H: int, W: int,
                  arms: dict, info: dict, mask: np.ndarray) -> tuple[np.ndarray, list]:
    """Warped BGRA layer of one garment, opaque inside its silhouette: holes are filled before warping (cleaned
    image) and again after (warp seams); background-coloured openings are warped along and kept open."""
    fn = {"tshirt": warp_tshirt, "pants": warp_pants}[gtype]
    src = _bgra(gimg)
    openings = opening_mask(src, background_color(src))
    src = fill_alpha_holes(src, openings)
    warped, warns = fn(body_lm, glm, src, H, W, arms=arms, info=info, mask=mask)
    keep = None
    if openings.any():
        aux = np.zeros_like(src)
        aux[openings] = 255
        aux_w, _ = fn(body_lm, glm, aux, H, W, arms=arms, info={}, mask=mask)
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


def render_tryon(base: np.ndarray, body_lm: dict, garments: list, H: int = 1200, W: int = 600,
                 shading: bool = False, contact_shadows: bool = False, edge_feather: bool = False,
                 shading_strength: float = SHADING_STRENGTH):
    """base: BGR/BGRA image; garments: [(type, BGRA image, landmarks)]. Pants are drawn under the T-shirt.
    The realism effects are off by default (TRYON_SHADING / TRYON_CONTACT_SHADOW / TRYON_EDGE_FEATHER, see
    flags.render_flags): with all off the result is the warped, opaque garment over the avatar.

    Returns (BGR uint8 HxWx3 on white, warnings: [str], debug: dict).
    """
    base = cv2.resize(_bgra(base), (W, H))
    mask = figure_mask(base)
    canvas = base.copy()  # base alpha kept as is: forcing 255 inside the mask showed a grey halo at soft edges
    arms = find_arms(mask, body_lm)
    warnings, info = [], {}
    order = {"pants": 0, "tshirt": 1}
    for gtype, gimg, glm in sorted(garments, key=lambda t: order.get(t[0], 9)):
        if gtype not in ("tshirt", "pants"):
            continue
        warped, warns = garment_layer(gtype, gimg, glm, body_lm, H, W, arms, info, mask)
        warnings += [f"{gtype}: {w}" for w in warns]
        if edge_feather:
            warped = soften_edges(warped)
        if shading:
            warped = apply_shading(warped, shading_map(base, mask & (warped[:, :, 3] > 0)), shading_strength)
        if contact_shadows:
            dark = contact_shadow(warped[:, :, 3], mask, _crotch_x(body_lm))
            canvas[:, :, :3] = (canvas[:, :, :3].astype(np.float32) * (1 - dark[:, :, None])).astype(np.uint8)
        canvas = _alpha_composite(canvas, warped)

    head = head_neck_overlay(mask, body_lm)[:, :, None]  # head and neck always above the garment
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
