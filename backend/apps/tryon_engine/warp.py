"""Try-on warp engine: garments are deformed onto the body by landmarks (scanline strips + affine sleeves).

Entry point: render_tryon(base, body_lm, garments) -> (RGB 600x1200, warnings).
Garment landmarks are pixels of the garment's own tight-cropped PNG; body landmarks are canvas pixels.

Design rules (fixes of the day-1 version, see docs/06):
- Lengths follow the GARMENT, widths follow the BODY. The garment's own proportions decide how long the
  sleeves, the T-shirt and the pants are (scaled by the body/garment shoulder or hip ratio); the body decides
  the widths ("the garment always adapts to the body").
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
WHITE_THRESHOLD = 235  # base images without transparency: figure = pixels darker than this in any channel


# ---------- helpers ----------

def _alpha_composite(base: np.ndarray, overlay: np.ndarray) -> np.ndarray:
    out = base.copy().astype(np.float32)
    ov = overlay.astype(np.float32)
    alpha = ov[:, :, 3:4] / 255.0
    out[:, :, :3] = out[:, :, :3] * (1 - alpha) + ov[:, :, :3] * alpha
    out[:, :, 3] = np.clip(out[:, :, 3] + ov[:, :, 3], 0, 255)
    return out.astype(np.uint8)


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


def _mapped_rows(g_rows: list, dst_ys: list, to_src_y, body_lm: dict) -> tuple[list, list]:
    """One vertical map (dst y -> src y) for the whole piece; widths: garment span -> body span at every row."""
    ys = []
    for y in sorted(dst_ys):
        if not ys or y - ys[-1] > 1:
            ys.append(y)
    src = [(to_src_y(y), *_interp_span(g_rows, to_src_y(y))) for y in ys]
    dst = [(y, *body_span(body_lm, y)) for y in ys]
    return src, dst


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
            row = cv2.resize(src[src_y, sl:sr].reshape(1, -1, 4), (dst_width, 1), interpolation=cv2.INTER_LINEAR)[0]
            x0, x1 = max(dst_lx, 0), min(dst_rx, W)
            if x1 <= x0:
                continue
            r0 = x0 - dst_lx
            r1 = min(r0 + (x1 - x0), row.shape[0])
            x1 = x0 + (r1 - r0)
            if r1 <= r0:
                continue
            piece = row[r0:r1].astype(np.float32)
            a = piece[:, 3:4] / 255.0
            base = result[dst_y, x0:x1].astype(np.float32)
            base[:, :3] = base[:, :3] * (1 - a) + piece[:, :3] * a
            base[:, 3] = np.clip(base[:, 3] + piece[:, 3], 0, 255)
            result[dst_y, x0:x1] = base.astype(np.uint8)
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


def _densify_leg(src: list, dst: list, mask: np.ndarray | None, side: str, axis: float, step: int = 12):
    """Insert rows every `step` px; each dst row covers the body's leg in the mask (+2 px ease) and never gets
    narrower than the landmark-interpolated span (so flares stay). Fixes skin/shorts showing at the thighs."""
    if mask is None:
        return src, dst
    out_s, out_d = [src[0]], [dst[0]]
    for i in range(len(dst) - 1):
        (sy0, *_), (sy1, *_) = src[i], src[i + 1]
        (dy0, dl0, dr0), (dy1, dl1, dr1) = dst[i], dst[i + 1]
        for y in range(int(dy0) + step, int(dy1), step):
            t = (y - dy0) / max(dy1 - dy0, 1e-6)
            sy = sy0 + t * (sy1 - sy0)
            sl, sr = _interp_span([src[i], src[i + 1]], sy)
            l, r = dl0 + t * (dl1 - dl0), dr0 + t * (dr1 - dr0)
            run = _leg_run(mask, y, side, axis, (l + r) / 2)
            if run:
                l, r = min(l, run[0] - 2), max(r, run[1] + 2)
                if side == "left":
                    r = min(r, axis)  # inner edge never crosses to the other leg
                else:
                    l = max(l, axis)
            out_s.append((sy, sl, sr))
            out_d.append((float(y), l, r))
        out_s.append(src[i + 1])
        out_d.append(dst[i + 1])
    return out_s, out_d


# ---------- garments ----------

def warp_tshirt(body_lm: dict, garment_lm: dict, garment_img: np.ndarray, H: int, W: int,
                arms: dict | None = None, info: dict | None = None,
                mask: np.ndarray | None = None) -> tuple[np.ndarray, list]:
    warnings: list[str] = []
    g, a = garment_lm, body_lm
    img = _bgra(garment_img)
    gh = img.shape[0]

    g_sw = _f(g["shoulder"]["right_x"]) - _f(g["shoulder"]["left_x"])
    a_sw = _f(a["shoulder"]["right_x"]) - _f(a["shoulder"]["left_x"])
    s = a_sw / g_sw  # garment px -> body px (widths)
    g_cx = (_f(g["shoulder"]["left_x"]) + _f(g["shoulder"]["right_x"])) / 2
    a_cx = (_f(a["shoulder"]["left_x"]) + _f(a["shoulder"]["right_x"])) / 2

    # One vertical scale for the whole garment (its own proportions, sized by the shoulder ratio); widths follow
    # the body at every row. Pinning each garment row to the same-named body row distorted the garment wherever
    # the garment's chest/waist lines and the body's disagree (they are defined differently).
    g_sy, a_sy = _f(g["shoulder"]["y"]), _f(a["shoulder"]["y"])
    to_dst = lambda gy: a_sy + (gy - g_sy) * s  # noqa: E731
    to_src = lambda dy: g_sy + (dy - a_sy) / s  # noqa: E731
    g_rows = [(_f(g[k]["y"]), _f(g[k]["left_x"]), _f(g[k]["right_x"])) for k in ("shoulder", "chest", "waist", "hem")]
    hem_y = to_dst(min(_f(g["hem"]["y"]), gh - 1.0))
    hem_max = _f(a["crotch"]["y"]) + MAX_SHIRT_BELOW_CROTCH * (_f(a["knee"]["y"]) - _f(a["crotch"]["y"]))
    if hem_y > hem_max:  # cut, never squeeze: the garment is longer than allowed on this body
        warnings.append(f"hem: garment is {hem_y - hem_max:.0f} px too long for this body, cut at the limit")
        hem_y = hem_max
    dst_ys = [to_dst(r[0]) for r in g_rows[:-1]] + [hem_y]
    dst_ys += [_f(a[k]["y"]) for k in ("chest", "waist", "hip") if a_sy < _f(a[k]["y"]) < hem_y]
    src, dst = _mapped_rows(g_rows, [y for y in dst_ys if y <= hem_y], to_src, a)

    # Collar / neckline above the shoulder line: same uniform scale, centred on the body.
    alpha = img[:, :, 3] > 128
    sl, sr = int(_f(g["shoulder"]["left_x"])), int(_f(g["shoulder"]["right_x"]))
    top_rows = np.where(alpha[:, sl:sr + 1].any(axis=1))[0]
    if len(top_rows) and g_sy - top_rows[0] > 2:
        yt = int(top_rows[0])
        xs = np.where(alpha[yt, sl:sr + 1])[0] + sl
        src.insert(0, (float(yt), float(xs[0]), float(xs[-1])))
        dst.insert(0, (to_dst(yt), a_cx + (xs[0] - g_cx) * s, a_cx + (xs[-1] - g_cx) * s))

    result = _scanline_strip(img, src, dst, H, W, warnings, "torso")

    # Sleeves: a rigid piece (uniform scale s + rotation onto the arm axis), attached at the shoulder point.
    # No fixed offsets and no stretch; a sleeve longer than SLEEVE_MAX_ARM of the arm is shortened along its
    # axis (warning). The body's armpit landmark is NOT used: it marks where the arms separate in the mask,
    # far below the anatomical armpit, and pinning the sleeve there blew the armhole up.
    hems = {}
    for side in ("left", "right"):
        S_g = np.array([_f(g["shoulder"][f"{side}_x"]), _f(g["shoulder"]["y"])])
        A_g = np.array([_f(g["chest"][f"{side}_x"]), _f(g["chest"]["y"])])
        E_g = np.array([_f(g["sleeve_end"][side]["x"]), _f(g["sleeve_end"][side]["y"])])
        S_b = np.array([_f(a["shoulder"][f"{side}_x"]), _f(a["shoulder"]["y"])])
        v_g = E_g - S_g
        arm = (arms or {}).get(side)
        edge = None
        if mask is not None:
            reach = float(np.linalg.norm(v_g)) * s * SLEEVE_HEM_EXTEND * 1.2
            edge = outer_edge_line(mask, side, S_b[1] + 3, S_b[1] + reach)
        if edge:
            # The sleeve's outer edge runs along the figure's outer edge (deltoid, then arm): a bulging upper
            # arm stays covered. The arm's centre axis alone left the deltoid uncovered on broad avatars.
            d = np.array([edge[0], 1.0])
            S_b = np.array([edge[0] * S_b[1] + edge[1], S_b[1]])
        elif arm:
            d = np.array([arm["slope"], 1.0])
        else:  # arm not separated in the mask: keep the garment's own sleeve angle
            d = v_g.copy()
            warnings.append(f"sleeve {side}: arm not found in the mask, garment angle used")
        d = d / np.linalg.norm(d)
        theta = np.arctan2(d[1], d[0]) - np.arctan2(v_g[1], v_g[0])
        R = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]]) * s

        along = v_g * SLEEVE_HEM_EXTEND
        quad_src = [S_g, S_g + along, A_g + along, A_g]
        q = [R @ (c - S_g) for c in quad_src]
        k = 1.0
        if arm:
            limit_y = S_b[1] + SLEEVE_MAX_ARM * (arm["end_y"] - S_b[1])
            for qi in q:
                ad = float(qi @ d)
                perp_y = qi[1] - ad * d[1]
                if S_b[1] + qi[1] > limit_y and ad * d[1] > 1e-6:
                    k = min(k, (limit_y - S_b[1] - perp_y) / (ad * d[1]))
            k = max(k, 0.2)
            if k < 0.98:  # below 2 % it is rounding, not a sleeve that is too long
                warnings.append(f"sleeve {side}: shortened to {k:.0%} to end half way down the arm")
        Kd = np.eye(2) + (k - 1) * np.outer(d, d)  # shorten along the arm axis only
        Mlin = Kd @ R
        M = np.hstack([Mlin, (S_b - Mlin @ S_g).reshape(2, 1)]).astype(np.float32)
        warped = cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        quad_dst = np.array([S_b + Kd @ qi for qi in q], np.float32)
        piece = np.zeros((H, W), np.uint8)  # not `mask`: that is the figure mask, needed for the next sleeve
        cv2.fillPoly(piece, [np.round(quad_dst).astype(np.int32)], 255)
        warped[:, :, 3] = np.where(piece > 0, warped[:, :, 3], 0)
        result = _alpha_composite(result, warped)
        hems[side] = (quad_dst[1], quad_dst[2], S_b)

    if info is not None:
        info["sleeve_hems"] = hems
    return result, warnings


def warp_pants(body_lm: dict, garment_lm: dict, garment_img: np.ndarray, H: int, W: int,
               arms: dict | None = None, info: dict | None = None,
               mask: np.ndarray | None = None) -> tuple[np.ndarray, list]:
    warnings: list[str] = []
    g, a = garment_lm, body_lm
    img = _bgra(garment_img)

    g_cr, a_cr = _f(g["crotch"]["y"]), _f(a["crotch"]["y"])
    g_wy, a_wy = _f(g["waist"]["y"]), _f(a["waist"]["y"])
    s_v = (a_cr - a_wy) / (g_cr - g_wy)  # rise scale: waist and crotch are anchored, used for the leg length too
    # The garment's hip row lands where its own proportions say (not on the body's hip landmark, which is the
    # widest row and sits just above the crotch); widths follow the body at every row.
    g_rows = [(g_wy, _f(g["waist"]["left_x"]), _f(g["waist"]["right_x"])),
              (_f(g["hip"]["y"]), _f(g["hip"]["left_x"]), _f(g["hip"]["right_x"])),
              (g_cr, _f(g["hip"]["left_x"]), _f(g["hip"]["right_x"]))]
    to_src = lambda dy: g_wy + (dy - a_wy) / s_v  # noqa: E731
    dst_ys = [a_wy, a_wy + (_f(g["hip"]["y"]) - g_wy) * s_v, a_cr]
    dst_ys += [_f(a["hip"]["y"])] if a_wy < _f(a["hip"]["y"]) < a_cr else []
    block_src, block_dst = _mapped_rows(g_rows, dst_ys, to_src, a)
    result = _scanline_strip(img, block_src, block_dst, H, W, warnings, "waist-crotch")

    g_cx, a_cx = _f(g["crotch"]["center_x"]), _crotch_x(a)
    fig_h = _f(a.get("foot_bottom", {}).get("y", H - 50)) - _f(a.get("head_top", {}).get("y", 50))
    for side in ("left", "right"):
        leg = f"{side}_leg"
        g_knee, a_knee = g["knee"][leg], a["knee"][leg]
        g_hem, a_ank = g["hem"][leg], a["ankle"][leg]
        g_outer = _f(g["hip"][f"{side}_x"])
        a_outer = _f(a["hip"][f"{side}_x"])
        top_src = (g_cr, g_outer, g_cx) if side == "left" else (g_cr, g_cx, g_outer)
        top_dst = (a_cr, a_outer, a_cx) if side == "left" else (a_cr, a_cx, a_outer)

        hem_y = a_cr + (_f(g_hem["y"]) - g_cr) * s_v
        ank_y = _f(a_ank["y"])
        full = hem_y >= ank_y - FULL_LENGTH_TOLERANCE * fig_h
        a_kl, a_kr = _f(a_knee["left_x"]), _f(a_knee["right_x"])
        if full:
            hem_y = ank_y
            knee_dst_y = _f(a["knee"]["y"])
            knee_l, knee_r = a_kl, a_kr
        else:  # shorter pants: proportional along the leg, widths from the body's leg at that height
            knee_dst_y = a_cr + (_f(g["knee"]["y"]) - g_cr) * s_v

            def leg_at(y):
                t = (y - a_cr) / max(_f(a["knee"]["y"]) - a_cr, 1e-6)
                if t <= 1:
                    return top_dst[1] + t * (a_kl - top_dst[1]), top_dst[2] + t * (a_kr - top_dst[2])
                t2 = (y - _f(a["knee"]["y"])) / max(ank_y - _f(a["knee"]["y"]), 1e-6)
                return a_kl + t2 * (_f(a_ank["left_x"]) - a_kl), a_kr + t2 * (_f(a_ank["right_x"]) - a_kr)
            knee_l, knee_r = leg_at(knee_dst_y)

        # Hem width: the body's leg width, or the garment's own hem relative to its knee if wider (flares).
        g_kw = _f(g_knee["right_x"]) - _f(g_knee["left_x"])
        s_knee = (knee_r - knee_l) / g_kw if g_kw > 0 else 1.0
        g_hw = (_f(g_hem["right_x"]) - _f(g_hem["left_x"])) * s_knee
        if full:
            body_l, body_r = _f(a_ank["left_x"]), _f(a_ank["right_x"])
        else:
            body_l, body_r = leg_at(hem_y)
        c = (body_l + body_r) / 2
        hw = max(body_r - body_l, g_hw)
        hem_dst = (hem_y, c - hw / 2, c + hw / 2)

        leg_src = [top_src, (_f(g["knee"]["y"]), _f(g_knee["left_x"]), _f(g_knee["right_x"])),
                   (_f(g_hem["y"]), _f(g_hem["left_x"]), _f(g_hem["right_x"]))]
        leg_dst = [top_dst, (knee_dst_y, knee_l, knee_r), hem_dst]
        _segment_warning(f"{side}-leg thigh", leg_src[0], leg_src[1], leg_dst[0], leg_dst[1], warnings)
        _segment_warning(f"{side}-leg shin", leg_src[1], leg_src[2], leg_dst[1], leg_dst[2], warnings)
        leg_src, leg_dst = _densify_leg(leg_src, leg_dst, mask, side, a_cx)
        strip = _scanline_strip(img, leg_src, leg_dst, H, W, [], f"{side}-leg")
        result = _alpha_composite(result, strip)
    return result, warnings


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


def render_tryon(base: np.ndarray, body_lm: dict, garments: list, H: int = 1200, W: int = 600):
    """base: BGR/BGRA image; garments: [(type, BGRA image, landmarks)]. Pants are drawn under the T-shirt.

    Returns (BGR uint8 HxWx3 on white, warnings: [str], debug: dict).
    """
    base = cv2.resize(_bgra(base), (W, H))
    mask = figure_mask(base)
    canvas = base.copy()  # base alpha kept as is: forcing 255 inside the mask showed a grey halo at soft edges
    arms = find_arms(mask, body_lm)
    warnings, info = [], {}
    order = {"pants": 0, "tshirt": 1}
    for gtype, gimg, glm in sorted(garments, key=lambda t: order.get(t[0], 9)):
        fn = {"tshirt": warp_tshirt, "pants": warp_pants}.get(gtype)
        if fn is None:
            continue
        warped, warns = fn(body_lm, glm, gimg, H, W, arms=arms, info=info, mask=mask)
        warnings += [f"{gtype}: {w}" for w in warns]
        canvas = _alpha_composite(canvas, warped)

    keep = arm_overlay_mask(mask, arms, info.get("sleeve_hems"))
    canvas[keep] = base[keep]
    for side in ("left", "right"):
        if not arms.get(side):
            warnings.append(f"arm {side}: not separated from the body in the mask, hands may be covered")

    white = np.full((H, W, 3), 255, np.float32)
    a = canvas[:, :, 3:4].astype(np.float32) / 255.0
    rgb = (canvas[:, :, :3].astype(np.float32) * a + white * (1 - a)).astype(np.uint8)
    return rgb, warnings, {"arms": arms, "arm_mask": keep, **info}
