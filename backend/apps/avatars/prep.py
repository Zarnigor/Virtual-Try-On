"""Avatar photo -> normalized 600x1200 RGBA figure + initial landmarks from the mask.

normalize(): rembg mask (u2net_human_seg) -> largest component -> crop -> ONE uniform scale -> pad.
  The figure is never stretched. Scale = min(FIG_H / figure_h, (axis_x - MARGIN) / widest half), where the
  widest half is measured from the body axis (head/feet centre), so arms spread wide on one side still fit.
  The figure top lands at y = 50 and the body axis at x = 300. If any figure pixel would fall outside the
  canvas, NormalizeError is raised (never silently clipped).
detect_landmarks(): a port of tools/landmark-editor-prototype detect() (docs/03). These are only the
  INITIAL positions; the staff landmark editor is the source of truth.
"""
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageOps

W, H = 600, 1200
TOP = 50
FIG_H = 1100
AXIS_X = 300
MARGIN = 10  # px kept free at the left/right canvas edge
SEAM_DARKER = 30  # grey levels a seam must be darker than its surroundings to beat the leg gap


class NormalizeError(Exception):
    pass


@dataclass
class Normalized:
    image: Image.Image  # RGBA 600x1200, transparent background, original pixels
    mask: np.ndarray  # bool HxW, the figure
    gray: np.ndarray  # uint8 HxW, for the crotch seam search
    scale: float
    figure_px: tuple  # (width, height) after scaling


def _largest_component(alpha: np.ndarray) -> np.ndarray:
    hard = (alpha > 128).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(hard, connectivity=8)
    if n <= 1:
        raise NormalizeError("no figure found in the mask")
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return labels == biggest


def _axis_x(mask: np.ndarray) -> float:
    """Body axis = mean of the head centre and the feet centre (arms ignored), as in the prototype."""
    ys = np.where(mask.any(axis=1))[0]
    top, bot = ys[0], ys[-1]
    h = bot - top
    head = mask[top: top + max(1, int(0.05 * h))]
    feet = mask[bot - max(1, int(0.03 * h)): bot + 1]
    return (np.nonzero(head)[1].mean() + np.nonzero(feet)[1].mean()) / 2


def normalize(src: Image.Image, session=None) -> Normalized:
    from rembg import new_session, remove

    src = ImageOps.exif_transpose(src).convert("RGB")
    session = session or new_session("u2net_human_seg")
    alpha = np.array(remove(src, only_mask=True, session=session).convert("L"))
    keep = _largest_component(alpha)
    alpha = np.where(keep, alpha, 0).astype(np.uint8)  # soft edges kept, other blobs (shadows, noise) dropped

    ys, xs = np.nonzero(keep)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    fig_h, fig_w = y1 - y0, x1 - x0
    axis = _axis_x(keep)
    half = max(axis - x0, x1 - axis)
    scale = min(FIG_H / fig_h, (AXIS_X - MARGIN) / half)

    rgba = np.dstack([np.array(src), alpha])[y0:y1, x0:x1]
    new_w, new_h = max(1, round(fig_w * scale)), max(1, round(fig_h * scale))
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    small = cv2.resize(rgba, (new_w, new_h), interpolation=interp)

    off_x = round(AXIS_X - (axis - x0) * scale)
    if off_x < 0 or off_x + new_w > W or TOP + new_h > H:
        raise NormalizeError(f"figure would be clipped: x {off_x}..{off_x + new_w}, y {TOP}..{TOP + new_h}")
    canvas = np.zeros((H, W, 4), np.uint8)
    canvas[TOP: TOP + new_h, off_x: off_x + new_w] = small
    mask = canvas[:, :, 3] > 128
    # Never silently clipped: every figure pixel is on the canvas and away from the edges.
    cols = np.nonzero(mask.any(axis=0))[0]
    if cols[0] < 1 or cols[-1] > W - 2:
        raise NormalizeError("figure touches the canvas edge")
    rgb = canvas[:, :, :3]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gray = np.where(mask, gray, 255).astype(np.uint8)
    return Normalized(Image.fromarray(canvas, "RGBA"), mask, gray, scale, (new_w, new_h))


# ---------- initial landmarks (port of the prototype's detect()) ----------

def _runs(mask, y):
    row = mask[int(np.clip(round(y), 0, mask.shape[0] - 1))].astype(np.int8)
    d = np.diff(np.concatenate([[0], row, [0]]))
    starts, ends = np.where(d == 1)[0], np.where(d == -1)[0] - 1
    return [(int(s), int(e)) for s, e in zip(starts, ends) if e - s >= 2]


def detect_landmarks(mask: np.ndarray, gray: np.ndarray) -> dict:
    rows = np.where(mask.any(axis=1))[0]
    top, bot = int(rows[0]), int(rows[-1])
    fh = bot - top
    cx = _axis_x(mask)

    def crun(y):
        r = _runs(mask, y)
        if not r:
            return (cx - 1, cx + 1)
        for q in r:
            if q[0] <= cx <= q[1]:
                return q
        return min(r, key=lambda q: min(abs(q[0] - cx), abs(q[1] - cx)))

    def wid(y):
        q = crun(y)
        return q[1] - q[0]

    def arg(lo, hi, fn, largest):
        lo, hi = int(round(lo)), int(round(hi))
        if hi <= lo:
            return lo
        vals = [fn(y) for y in range(lo, hi)]
        return lo + int(np.argmax(vals) if largest else np.argmin(vals))

    def legs(y):
        lim = 0.16 * fh
        rr = [q for q in _runs(mask, y) if q[1] > cx - lim and q[0] < cx + lim]
        split = []
        for q in rr:
            split += [(q[0], int(cx)), (int(cx), q[1])] if q[0] < cx < q[1] else [q]
        left = [q for q in split if q[1] <= cx]
        right = [q for q in split if q[0] >= cx]
        return (max(left, key=lambda q: q[1]) if left else None, min(right, key=lambda q: q[0]) if right else None)

    armpit = next((y for y in range(int(top + 0.18 * fh), int(top + 0.40 * fh)) if len(_runs(mask, y)) >= 3),
                  int(top + 0.30 * fh))
    ny = arg(top + 0.10 * fh, top + 0.19 * fh, wid, False)
    wmin = wid(ny)
    onset = next((y for y in range(ny, armpit) if wid(y) > wmin + 0.0145 * fh), None)
    ny = round(onset - 0.009 * fh) if onset is not None else ny

    def acromion(side):
        edge = [crun(y)[side] for y in range(ny, armpit)]
        if len(edge) < 12:
            return None
        base, total = edge[0], abs(edge[-6] - edge[0])
        win = max(4, round(0.0127 * fh))
        for i in range(len(edge) - win):
            if abs(edge[i] - base) > 0.55 * total:
                if sum(abs(edge[k + 1] - edge[k]) for k in range(i, i + win)) / win <= 1:
                    return ny + i, edge[i]
        return None

    a_l, a_r = acromion(0), acromion(1)
    if a_l and a_r:
        shoulder = {"y": (a_l[0] + a_r[0]) / 2, "left_x": a_l[1], "right_x": a_r[1]}
    else:
        y = ny + 0.06 * fh
        q = crun(y)
        shoulder = {"y": y, "left_x": q[0], "right_x": q[1]}

    chest_y = armpit + 0.025 * fh
    # Crotch: the first row below the armpit where the legs separate on the axis. When the thighs touch, that gap
    # opens too low, so a clearly dark seam junction just above the gap wins (docs/03). The prototype's "darkest
    # point in 50-62% of height" alone picked the shorts' waistband on uniform grey shorts.
    c = int(round(cx))
    gap = next((y for y in range(armpit, bot) if not mask[y, c - 1: c + 2].any()), round(top + 0.56 * fh))
    sw = max(2, round(0.005 * fh))
    lo = max(armpit + 1, round(gap - 0.05 * fh))
    vals = [float(gray[y, c - sw: c + sw + 1].mean()) for y in range(lo, max(lo + 1, gap - 2))]
    i = int(np.argmin(vals))
    crotch = lo + i if np.median(vals) - vals[i] > SEAM_DARKER else gap
    waist_y = arg(armpit + 0.35 * (crotch - armpit), armpit + 0.70 * (crotch - armpit), wid, False)
    hip_y = arg(waist_y + 0.04 * fh, crotch - 0.01 * fh, wid, True)
    knee_y = bot - 0.285 * fh

    lim = 0.145 * fh
    shoe = next((y for y in range(round(knee_y + 0.018 * fh), bot)
                 if ((gray[y, int(cx - lim): int(cx + lim)] < 60) & mask[y, int(cx - lim): int(cx + lim)]).sum()
                 > max(6, 0.011 * fh)), bot - 0.06 * fh)

    def ankle(i):
        def w(y):
            q = legs(y)[i]
            return q[1] - q[0] if q else 1e9
        y = arg(shoe - 0.07 * fh, shoe - max(3, 0.005 * fh), w, False)
        q = legs(y)[i] or (cx, cx)
        return {"y": float(y), "left_x": float(q[0]), "right_x": float(q[1]), "width": float(q[1] - q[0])}

    def span(y, q=None):
        q = q or crun(y)
        return {"y": float(y), "left_x": float(q[0]), "right_x": float(q[1]), "width": float(q[1] - q[0]),
                "center_x": (q[0] + q[1]) / 2}

    kl, kr = legs(knee_y)
    kl = kl or (cx - 2, cx - 1)
    kr = kr or (cx + 1, cx + 2)
    leg = lambda q: {"left_x": float(q[0]), "right_x": float(q[1]), "width": float(q[1] - q[0])}  # noqa: E731
    return {
        "head_top": {"y": float(top)},
        "neck": span(ny),
        "shoulder": span(shoulder["y"], (shoulder["left_x"], shoulder["right_x"])),
        "armpit": {"y": float(armpit)},
        "chest": span(chest_y),
        "waist": span(waist_y),
        "hip": span(hip_y),
        "crotch": {"y": float(crotch), "center_x": float(cx)},
        "knee": {"y": float(knee_y), "left_leg": leg(kl), "right_leg": leg(kr)},
        "ankle": {"left_leg": ankle(0), "right_leg": ankle(1)},
        "foot_bottom": {"y": float(bot)},
    }


ORDER = ["head_top", "neck", "shoulder", "armpit", "chest", "waist", "hip", "crotch", "knee"]
RANGES = {"neck": (12, 19), "shoulder": (16, 23), "armpit": (25, 35), "chest": (27, 38), "waist": (34, 47),
          "hip": (46, 59), "crotch": (49, 61), "knee": (68, 76)}


def landmark_warnings(lm: dict) -> list[str]:
    """docs/03 sanity checks, as warnings (the staff editor fixes them)."""
    out = []
    ys = [lm[k]["y"] for k in ORDER] + [min(lm["ankle"]["left_leg"]["y"], lm["ankle"]["right_leg"]["y"]),
                                         lm["foot_bottom"]["y"]]
    if any(b < a for a, b in zip(ys, ys[1:])):
        out.append("vertical order broken")
    top, fh = lm["head_top"]["y"], lm["foot_bottom"]["y"] - lm["head_top"]["y"]
    for k, (lo, hi) in RANGES.items():
        pct = 100 * (lm[k]["y"] - top) / fh
        if not lo <= pct <= hi:
            out.append(f"{k} at {pct:.1f}% of height (expected {lo}-{hi})")
    for side in ("left_leg", "right_leg"):
        a = lm["ankle"][side]
        if a["width"] >= lm["knee"][side]["width"]:
            out.append(f"ankle {side} not narrower than the knee")
    if lm["shoulder"]["width"] > 1.6 * lm["chest"]["width"]:
        out.append("shoulder wider than 1.6 x chest")
    return out
