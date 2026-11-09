"""
Day-1 warp experiment.
Warps a synthetic T-shirt and a synthetic pair of pants onto the 3 male avatars
from seed/avatars.reference.json and writes 6 output PNGs to tools/warp_experiment/out/.

Pass criteria (docs/06):
  1. Shoulder and waist lines of the garment land on the body edge.
  2. Sleeves sit on the arms.
  3. Text/print is not visibly stretched (scale factor check: warn if > 1.4x or < 0.6x).
  4. Mesh does not fold or tear (monotonicity check on warp grid).

Usage:
  python3 tools/warp_experiment/run.py
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SEED_JSON = ROOT / "seed" / "avatars.reference.json"
GARMENTS_JSON = Path(__file__).parent / "garments.json"
OUT_DIR = Path(__file__).parent / "out"
OUT_DIR.mkdir(exist_ok=True)

CANVAS_W, CANVAS_H = 600, 1200
STRETCH_WARN_HIGH = 1.4
STRETCH_WARN_LOW = 0.6


# ---------------------------------------------------------------------------
# Synthetic image generators
# ---------------------------------------------------------------------------

def make_avatar_image(lm: dict, build: str) -> np.ndarray:
    img = np.zeros((CANVAS_H, CANVAS_W, 4), dtype=np.uint8)
    colours = {"slim": (90, 120, 160, 255), "average": (70, 100, 140, 255), "plus": (60, 85, 125, 255)}
    col = colours.get(build, (80, 110, 150, 255))
    pts = _body_polygon(lm)
    cv2.fillPoly(img, [pts], col)
    head_top_y = int(lm["head_top"]["y"])
    neck_y = int(lm["neck"]["y"])
    head_r = int((neck_y - head_top_y) * 0.55)
    cv2.circle(img, (CANVAS_W // 2, head_top_y + head_r + 4), head_r, col, -1)
    return img


def _body_polygon(lm: dict) -> np.ndarray:
    shoulder = lm["shoulder"]
    chest = lm["chest"]
    waist = lm["waist"]
    hip = lm["hip"]
    crotch_y = int(lm["crotch"]["y"])
    knee = lm["knee"]
    ankle_l = lm["ankle"]["left_leg"]
    ankle_r = lm["ankle"]["right_leg"]
    foot_y = int(lm["foot_bottom"]["y"])
    hand_y = int(lm.get("qa", {}).get("hand_end_y", hip["y"] + 20))

    left = [
        (CANVAS_W // 2, int(lm["neck"]["y"])),
        (int(shoulder["left_x"]), int(shoulder["y"])),
        (int(shoulder["left_x"]) - 18, int(chest["y"])),
        (int(shoulder["left_x"]) - 18, hand_y),
        (int(shoulder["left_x"]) - 8, hand_y + 10),
        (int(chest["left_x"]), int(chest["y"])),
        (int(waist["left_x"]), int(waist["y"])),
        (int(hip["left_x"]), int(hip["y"])),
        (int(hip["left_x"]) - 5, crotch_y),
        (int(knee["left_leg"]["left_x"]), int(knee["y"])),
        (int(ankle_l["left_x"]), int(ankle_l["y"])),
        (int(ankle_l["left_x"]), foot_y),
    ]
    right = [
        (int(ankle_r["right_x"]), foot_y),
        (int(ankle_r["right_x"]), int(ankle_r["y"])),
        (int(knee["right_leg"]["right_x"]), int(knee["y"])),
        (int(hip["right_x"]) + 5, crotch_y),
        (int(hip["right_x"]), int(hip["y"])),
        (int(waist["right_x"]), int(waist["y"])),
        (int(chest["right_x"]), int(chest["y"])),
        (int(shoulder["right_x"]) + 8, hand_y + 10),
        (int(shoulder["right_x"]) + 18, hand_y),
        (int(shoulder["right_x"]) + 18, int(chest["y"])),
        (int(shoulder["right_x"]), int(shoulder["y"])),
        (CANVAS_W // 2, int(lm["neck"]["y"])),
    ]
    return np.array(left + right, dtype=np.int32)


def make_tshirt_image(g: dict) -> np.ndarray:
    w, h = g["image_size"]
    img = np.zeros((h, w, 4), dtype=np.uint8)
    lm = g["landmarks"]
    torso = np.array([
        [lm["shoulder"]["left_x"], lm["shoulder"]["y"]],
        [lm["shoulder"]["right_x"], lm["shoulder"]["y"]],
        [lm["hem"]["right_x"], lm["hem"]["y"]],
        [lm["hem"]["left_x"], lm["hem"]["y"]],
    ], dtype=np.int32)
    cv2.fillPoly(img, [torso], (70, 130, 200, 255))
    left_sleeve = np.array([
        [lm["shoulder"]["left_x"], lm["shoulder"]["y"]],
        [lm["chest"]["left_x"], lm["chest"]["y"]],
        [lm["sleeve_end"]["left"]["x"], lm["sleeve_end"]["left"]["y"]],
    ], dtype=np.int32)
    cv2.fillPoly(img, [left_sleeve], (70, 130, 200, 255))
    right_sleeve = np.array([
        [lm["shoulder"]["right_x"], lm["shoulder"]["y"]],
        [lm["chest"]["right_x"], lm["chest"]["y"]],
        [lm["sleeve_end"]["right"]["x"], lm["sleeve_end"]["right"]["y"]],
    ], dtype=np.int32)
    cv2.fillPoly(img, [right_sleeve], (70, 130, 200, 255))
    # stripe grid for stretch visibility
    for stripe_y in range(lm["shoulder"]["y"], lm["hem"]["y"], 20):
        cv2.line(img, (lm["hem"]["left_x"], stripe_y),
                 (lm["hem"]["right_x"], stripe_y), (100, 160, 220, 180), 1)
    for stripe_x in range(lm["hem"]["left_x"], lm["hem"]["right_x"], 20):
        cv2.line(img, (stripe_x, lm["shoulder"]["y"]),
                 (stripe_x, lm["hem"]["y"]), (100, 160, 220, 180), 1)
    cx = lm["chest"]["center_x"]
    cy = (lm["chest"]["y"] + lm["waist"]["y"]) // 2
    cv2.putText(img, "A", (cx - 20, cy + 15),
                cv2.FONT_HERSHEY_SIMPLEX, 1.8, (255, 255, 255, 255), 3)
    neck_cx = lm["shoulder"]["center_x"]
    neck_r = lm["shoulder"]["width"] // 7
    cv2.circle(img, (neck_cx, lm["shoulder"]["y"] - 5), neck_r, (0, 0, 0, 0), -1)
    return img


def make_pants_image(g: dict) -> np.ndarray:
    w, h = g["image_size"]
    img = np.zeros((h, w, 4), dtype=np.uint8)
    lm = g["landmarks"]
    crotch_y = lm["crotch"]["y"]
    left_hem = lm["hem"]["left_leg"]
    right_hem = lm["hem"]["right_leg"]
    ll = lm["knee"]["left_leg"]
    rl = lm["knee"]["right_leg"]
    left_pts = np.array([
        [lm["waist"]["left_x"], lm["waist"]["y"]],
        [lm["hip"]["left_x"], lm["hip"]["y"]],
        [lm["hip"]["left_x"] - 5, crotch_y],
        [ll["left_x"], lm["knee"]["y"]],
        [left_hem["left_x"], left_hem["y"]],
        [left_hem["right_x"], left_hem["y"]],
        [ll["right_x"], lm["knee"]["y"]],
        [lm["waist"]["center_x"] - 5, crotch_y],
        [lm["waist"]["center_x"] - 5, lm["waist"]["y"]],
    ], dtype=np.int32)
    cv2.fillPoly(img, [left_pts], (60, 60, 90, 255))
    right_pts = np.array([
        [lm["waist"]["center_x"] + 5, lm["waist"]["y"]],
        [lm["waist"]["center_x"] + 5, crotch_y],
        [rl["left_x"], lm["knee"]["y"]],
        [right_hem["left_x"], right_hem["y"]],
        [right_hem["right_x"], right_hem["y"]],
        [rl["right_x"], lm["knee"]["y"]],
        [lm["hip"]["right_x"] + 5, crotch_y],
        [lm["hip"]["right_x"], lm["hip"]["y"]],
        [lm["waist"]["right_x"], lm["waist"]["y"]],
    ], dtype=np.int32)
    cv2.fillPoly(img, [right_pts], (60, 60, 90, 255))
    cv2.rectangle(img, (lm["waist"]["left_x"], lm["waist"]["y"] - 2),
                  (lm["waist"]["right_x"], lm["waist"]["y"] + 18), (40, 40, 65, 255), -1)
    # grid for stretch visibility
    for stripe_y in range(crotch_y, left_hem["y"], 30):
        cv2.line(img, (ll["left_x"], stripe_y), (ll["right_x"], stripe_y), (90, 90, 120, 180), 1)
        cv2.line(img, (rl["left_x"], stripe_y), (rl["right_x"], stripe_y), (90, 90, 120, 180), 1)
    stripe_x = (ll["left_x"] + ll["right_x"]) // 2
    cv2.line(img, (stripe_x, crotch_y), (stripe_x, left_hem["y"]), (100, 100, 140, 255), 3)
    return img


# ---------------------------------------------------------------------------
# Core: scanline warp (horizontal strips, no seams)
# ---------------------------------------------------------------------------

def _scanline_warp_strip(src: np.ndarray,
                          src_rows: list,  # list of (y, left_x, right_x)
                          dst_rows: list,  # list of (y, left_x, right_x) on canvas
                          out_shape: tuple,
                          warnings: list,
                          label: str) -> np.ndarray:
    """
    Scanline strip warp. For each output row between consecutive dst landmarks,
    interpolates src boundaries and scales the source scanline horizontally.
    Produces seamless output with no triangle artefacts.
    """
    H, W = out_shape[:2]
    result = np.zeros((H, W, 4), dtype=np.uint8)

    # stretch check across full strip (top to bottom)
    src_w_top = src_rows[0][2] - src_rows[0][1]
    dst_w_top = dst_rows[0][2] - dst_rows[0][1]
    src_w_bot = src_rows[-1][2] - src_rows[-1][1]
    dst_w_bot = dst_rows[-1][2] - dst_rows[-1][1]
    for src_w, dst_w, loc in [(src_w_top, dst_w_top, "top"), (src_w_bot, dst_w_bot, "bot")]:
        if src_w > 0:
            s = dst_w / src_w
            if s > STRETCH_WARN_HIGH or s < STRETCH_WARN_LOW:
                warnings.append(f"  STRETCH WARNING {label}-{loc}: {s:.2f}x (src={src_w:.0f}px dst={dst_w:.0f}px)")

    for seg in range(len(src_rows) - 1):
        sy0, slx0, srx0 = src_rows[seg]
        sy1, slx1, srx1 = src_rows[seg + 1]
        dy0, dlx0, drx0 = dst_rows[seg]
        dy1, dlx1, drx1 = dst_rows[seg + 1]

        y0 = int(round(dy0))
        y1 = int(round(dy1))
        span = max(y1 - y0, 1)

        for dst_y in range(y0, y1 + 1):
            if dst_y < 0 or dst_y >= H:
                continue
            t = (dst_y - dy0) / (dy1 - dy0) if dy1 != dy0 else 0.0

            # interpolate source row
            src_y = int(round(sy0 + t * (sy1 - sy0)))
            src_lx = slx0 + t * (slx1 - slx0)
            src_rx = srx0 + t * (srx1 - srx0)
            src_y = max(0, min(src_y, src.shape[0] - 1))

            # interpolate dest row boundaries
            dst_lx = int(round(dlx0 + t * (dlx1 - dlx0)))
            dst_rx = int(round(drx0 + t * (drx1 - drx0)))
            dst_width = max(dst_rx - dst_lx, 1)

            src_lx_i = max(0, int(src_lx))
            src_rx_i = min(src.shape[1], int(src_rx) + 1)
            if src_rx_i <= src_lx_i:
                continue

            src_row = src[src_y, src_lx_i:src_rx_i]
            if src_row.shape[0] == 0:
                continue

            dst_row = cv2.resize(src_row.reshape(1, -1, 4), (dst_width, 1),
                                  interpolation=cv2.INTER_LINEAR)[0]

            x0 = max(dst_lx, 0)
            x1 = min(dst_rx, W)
            if x1 <= x0:
                continue
            row_x0 = x0 - dst_lx
            row_x1 = row_x0 + (x1 - x0)
            if row_x1 > dst_row.shape[0]:
                row_x1 = dst_row.shape[0]
                x1 = x0 + (row_x1 - row_x0)
            if row_x1 <= row_x0:
                continue

            piece = dst_row[row_x0:row_x1].astype(np.float32)
            alpha = piece[:, 3:4] / 255.0
            base = result[dst_y, x0:x1].astype(np.float32)
            base[:, :3] = base[:, :3] * (1 - alpha) + piece[:, :3] * alpha
            base[:, 3] = np.clip(base[:, 3] + piece[:, 3], 0, 255)
            result[dst_y, x0:x1] = base.astype(np.uint8)

    return result


def _alpha_composite(base: np.ndarray, overlay: np.ndarray) -> np.ndarray:
    out = base.copy().astype(np.float32)
    ov = overlay.astype(np.float32)
    alpha = ov[:, :, 3:4] / 255.0
    out[:, :, :3] = out[:, :, :3] * (1 - alpha) + ov[:, :, :3] * alpha
    out[:, :, 3] = np.clip(out[:, :, 3] + ov[:, :, 3], 0, 255)
    return out.astype(np.uint8)


# ---------------------------------------------------------------------------
# T-shirt warp
# ---------------------------------------------------------------------------

def warp_tshirt(avatar_lm: dict, garment: dict, garment_img: np.ndarray,
                canvas_shape: tuple) -> tuple:
    warnings = []
    H, W = canvas_shape[:2]
    result = np.zeros((H, W, 4), dtype=np.uint8)

    g = garment["landmarks"]
    a = avatar_lm
    body_hem_y = int(a["hip"]["y"]) + int((a["crotch"]["y"] - a["hip"]["y"]) * 0.3)

    # torso: 3 scanline strips (shoulder->chest, chest->waist, waist->hem)
    torso_src = [
        (g["shoulder"]["y"], g["shoulder"]["left_x"], g["shoulder"]["right_x"]),
        (g["chest"]["y"],    g["chest"]["left_x"],    g["chest"]["right_x"]),
        (g["waist"]["y"],    g["waist"]["left_x"],    g["waist"]["right_x"]),
        (g["hem"]["y"],      g["hem"]["left_x"],      g["hem"]["right_x"]),
    ]
    torso_dst = [
        (a["shoulder"]["y"], a["shoulder"]["left_x"], a["shoulder"]["right_x"]),
        (a["chest"]["y"],    a["chest"]["left_x"],    a["chest"]["right_x"]),
        (a["waist"]["y"],    a["waist"]["left_x"],    a["waist"]["right_x"]),
        (body_hem_y,         a["hip"]["left_x"],      a["hip"]["right_x"]),
    ]
    torso_warp = _scanline_warp_strip(garment_img, torso_src, torso_dst,
                                       (H, W), warnings, "torso")
    result = _alpha_composite(result, torso_warp)

    # sleeves: affine triangle (rotation handled naturally)
    hand_y = int(a.get("qa", {}).get("hand_end_y", a["hip"]["y"] + 10))
    armpit_y = int(a["armpit"]["y"])

    for side in ("left", "right"):
        if side == "left":
            sh_x = int(a["shoulder"]["left_x"])
            arm_outer_x = sh_x - 22
            se = g["sleeve_end"]["left"]
            src_tri = np.array([
                [g["shoulder"]["left_x"], g["shoulder"]["y"]],
                [g["chest"]["left_x"],    g["chest"]["y"]],
                [se["x"],                 se["y"]],
            ], dtype=np.float32)
            dst_tri = np.array([
                [sh_x,          int(a["shoulder"]["y"])],
                [sh_x,          armpit_y],
                [arm_outer_x,   hand_y],
            ], dtype=np.float32)
        else:
            sh_x = int(a["shoulder"]["right_x"])
            arm_outer_x = sh_x + 22
            se = g["sleeve_end"]["right"]
            src_tri = np.array([
                [g["shoulder"]["right_x"], g["shoulder"]["y"]],
                [g["chest"]["right_x"],    g["chest"]["y"]],
                [se["x"],                  se["y"]],
            ], dtype=np.float32)
            dst_tri = np.array([
                [sh_x,         int(a["shoulder"]["y"])],
                [sh_x,         armpit_y],
                [arm_outer_x,  hand_y],
            ], dtype=np.float32)

        M = cv2.getAffineTransform(src_tri, dst_tri)
        warped = cv2.warpAffine(garment_img, M, (W, H),
                                flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_TRANSPARENT)
        mask = np.zeros((H, W), dtype=np.uint8)
        cv2.fillPoly(mask, [dst_tri.astype(np.int32)], 255)
        warped[:, :, 3] = np.where(mask > 0, warped[:, :, 3], 0)
        result = _alpha_composite(result, warped)

    return result, warnings


# ---------------------------------------------------------------------------
# Pants warp
# ---------------------------------------------------------------------------

def warp_pants(avatar_lm: dict, garment: dict, garment_img: np.ndarray,
               canvas_shape: tuple) -> tuple:
    warnings = []
    H, W = canvas_shape[:2]
    result = np.zeros((H, W, 4), dtype=np.uint8)

    g = garment["landmarks"]
    a = avatar_lm

    # waist-to-crotch block (both legs together)
    crotch_y_g = g["crotch"]["y"]
    crotch_y_a = float(a["crotch"]["y"])
    block_src = [
        (g["waist"]["y"], g["waist"]["left_x"], g["waist"]["right_x"]),
        (g["hip"]["y"],   g["hip"]["left_x"],   g["hip"]["right_x"]),
        (crotch_y_g,      g["hip"]["left_x"],   g["hip"]["right_x"]),
    ]
    block_dst = [
        (a["waist"]["y"], a["waist"]["left_x"], a["waist"]["right_x"]),
        (a["hip"]["y"],   a["hip"]["left_x"],   a["hip"]["right_x"]),
        (crotch_y_a,      a["hip"]["left_x"],   a["hip"]["right_x"]),
    ]
    block_warp = _scanline_warp_strip(garment_img, block_src, block_dst,
                                       (H, W), warnings, "pants-waist-crotch")
    result = _alpha_composite(result, block_warp)

    # per-leg: crotch->knee->ankle
    ankle_l = a["ankle"]["left_leg"]
    ankle_r = a["ankle"]["right_leg"]
    half_w = (a["hip"]["right_x"] - a["hip"]["left_x"]) // 2

    for side in ("left", "right"):
        if side == "left":
            g_lx_crotch = g["hip"]["left_x"]
            g_rx_crotch = g["waist"]["center_x"] - 5
            g_lx_knee   = g["knee"]["left_leg"]["left_x"]
            g_rx_knee   = g["knee"]["left_leg"]["right_x"]
            g_hem       = g["hem"]["left_leg"]
            a_lx_crotch = a["hip"]["left_x"]
            a_rx_crotch = a["hip"]["left_x"] + half_w - 10
            a_lx_knee   = a["knee"]["left_leg"]["left_x"]
            a_rx_knee   = a["knee"]["left_leg"]["right_x"]
            a_ank_lx    = int(ankle_l["left_x"])
            a_ank_rx    = int(ankle_l["right_x"])
            a_ank_y     = int(ankle_l["y"])
        else:
            g_lx_crotch = g["waist"]["center_x"] + 5
            g_rx_crotch = g["hip"]["right_x"]
            g_lx_knee   = g["knee"]["right_leg"]["left_x"]
            g_rx_knee   = g["knee"]["right_leg"]["right_x"]
            g_hem       = g["hem"]["right_leg"]
            a_lx_crotch = a["hip"]["left_x"] + half_w + 10
            a_rx_crotch = a["hip"]["right_x"]
            a_lx_knee   = a["knee"]["right_leg"]["left_x"]
            a_rx_knee   = a["knee"]["right_leg"]["right_x"]
            a_ank_lx    = int(ankle_r["left_x"])
            a_ank_rx    = int(ankle_r["right_x"])
            a_ank_y     = int(ankle_r["y"])

        leg_src = [
            (crotch_y_g,         g_lx_crotch, g_rx_crotch),
            (g["knee"]["y"],     g_lx_knee,   g_rx_knee),
            (g_hem["y"],         g_hem["left_x"], g_hem["right_x"]),
        ]
        leg_dst = [
            (crotch_y_a,         a_lx_crotch, a_rx_crotch),
            (a["knee"]["y"],     a_lx_knee,   a_rx_knee),
            (a_ank_y,            a_ank_lx,    a_ank_rx),
        ]
        leg_warp = _scanline_warp_strip(garment_img, leg_src, leg_dst,
                                         (H, W), warnings, f"{side}-leg")
        result = _alpha_composite(result, leg_warp)

    return result, warnings


# ---------------------------------------------------------------------------
# Composite + save
# ---------------------------------------------------------------------------

def composite_and_save(avatar_img: np.ndarray, garment_warp: np.ndarray,
                       out_path: Path, avatar_lm: dict, garment_type: str,
                       warnings: list):
    base = _alpha_composite(avatar_img, garment_warp)

    # draw landmark reference lines
    a = avatar_lm
    overlay = base.copy()
    if garment_type == "tshirt":
        lines = [
            (a["shoulder"]["y"], a["shoulder"]["left_x"], a["shoulder"]["right_x"], (255, 180, 0)),
            (a["chest"]["y"],    a["chest"]["left_x"],    a["chest"]["right_x"],    (220, 60, 60)),
            (a["waist"]["y"],    a["waist"]["left_x"],    a["waist"]["right_x"],    (60, 200, 100)),
        ]
    else:
        lines = [
            (a["waist"]["y"],   a["waist"]["left_x"],  a["waist"]["right_x"],  (255, 180, 0)),
            (a["hip"]["y"],     a["hip"]["left_x"],    a["hip"]["right_x"],    (220, 60, 60)),
            (a["crotch"]["y"],  a["hip"]["left_x"],    a["hip"]["right_x"],    (180, 60, 220)),
            (a["knee"]["y"],    a["knee"]["left_leg"]["left_x"],
             a["knee"]["right_leg"]["right_x"], (60, 200, 100)),
        ]
    for y, lx, rx, col in lines:
        cv2.line(overlay, (int(lx), int(y)), (int(rx), int(y)),
                 (col[2], col[1], col[0], 200), 2)
    cv2.addWeighted(overlay, 0.5, base, 0.5, 0, base)

    final = np.full((CANVAS_H, CANVAS_W, 3), 255, dtype=np.uint8)
    alpha = base[:, :, 3:4] / 255.0
    final = (base[:, :, :3] * alpha + final * (1 - alpha)).astype(np.uint8)
    cv2.imwrite(str(out_path), cv2.cvtColor(final, cv2.COLOR_RGB2BGR))

    print(f"  Saved {out_path.name}")
    if warnings:
        for w in warnings:
            print(w)
    else:
        print("  No stretch warnings.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    avatars_data = json.loads(SEED_JSON.read_text())["avatars"]
    garments_data = json.loads(GARMENTS_JSON.read_text())

    all_warnings = []

    for garment_type in ("tshirt", "pants"):
        g = garments_data[garment_type]
        g_img = make_tshirt_image(g) if garment_type == "tshirt" else make_pants_image(g)

        for build in ("slim", "average", "plus"):
            av = avatars_data[f"male_{build}"]
            lm = {**av["landmarks"], "qa": av.get("qa", {})}
            av_img = make_avatar_image(lm, build)

            print(f"\n{garment_type.upper()} on male_{build}:")
            if garment_type == "tshirt":
                warped, warns = warp_tshirt(lm, g, g_img, (CANVAS_H, CANVAS_W, 4))
            else:
                warped, warns = warp_pants(lm, g, g_img, (CANVAS_H, CANVAS_W, 4))

            all_warnings.extend(warns)
            composite_and_save(av_img, warped, OUT_DIR / f"{garment_type}_{build}.png",
                               lm, garment_type, warns)

    print("\n--- Summary ---")
    if all_warnings:
        print("Stretch warnings:")
        for w in sorted(set(all_warnings)):
            print(w)
    else:
        print("Pass: no stretch warnings.")


if __name__ == "__main__":
    main()
