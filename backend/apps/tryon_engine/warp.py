"""
Scanline warp engine — same algorithm as tools/warp_experiment/run.py,
adapted for real garment images (PIL/numpy) and body landmark dicts.
"""
import numpy as np
import cv2
from typing import Optional

STRETCH_WARN_HIGH = 1.4
STRETCH_WARN_LOW = 0.6


def _alpha_composite(base: np.ndarray, overlay: np.ndarray) -> np.ndarray:
    out = base.copy().astype(np.float32)
    ov = overlay.astype(np.float32)
    alpha = ov[:, :, 3:4] / 255.0
    out[:, :, :3] = out[:, :, :3] * (1 - alpha) + ov[:, :, :3] * alpha
    out[:, :, 3] = np.clip(out[:, :, 3] + ov[:, :, 3], 0, 255)
    return out.astype(np.uint8)


def _scanline_strip(src: np.ndarray, src_rows: list, dst_rows: list,
                     H: int, W: int, warnings: list, label: str) -> np.ndarray:
    result = np.zeros((H, W, 4), dtype=np.uint8)

    for seg in range(len(src_rows) - 1):
        sy0, slx0, srx0 = src_rows[seg]
        sy1, slx1, srx1 = src_rows[seg + 1]
        dy0, dlx0, drx0 = dst_rows[seg]
        dy1, dlx1, drx1 = dst_rows[seg + 1]

        # stretch check
        for src_w, dst_w, loc in [
            (srx0 - slx0, drx0 - dlx0, f"{label}-top"),
            (srx1 - slx1, drx1 - dlx1, f"{label}-bot"),
        ]:
            if src_w > 0:
                s = dst_w / src_w
                if s > STRETCH_WARN_HIGH or s < STRETCH_WARN_LOW:
                    warnings.append(f"{loc}:{s:.2f}x")

        y0 = int(round(dy0))
        y1 = int(round(dy1))
        dy_span = dy1 - dy0 if dy1 != dy0 else 1

        for dst_y in range(y0, y1 + 1):
            if dst_y < 0 or dst_y >= H:
                continue
            t = (dst_y - dy0) / dy_span

            src_y = int(round(sy0 + t * (sy1 - sy0)))
            src_lx = slx0 + t * (slx1 - slx0)
            src_rx = srx0 + t * (srx1 - srx0)
            src_y = max(0, min(src_y, src.shape[0] - 1))

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


def warp_tshirt(body_lm: dict, garment_lm: dict, garment_img: np.ndarray,
                H: int, W: int) -> tuple[np.ndarray, list]:
    warnings = []
    result = np.zeros((H, W, 4), dtype=np.uint8)
    g = garment_lm
    a = body_lm

    body_hem_y = float(a["hip"]["y"]) + (float(a["crotch"]["y"]) - float(a["hip"]["y"])) * 0.3

    # garment image dimensions
    gh, gw = garment_img.shape[:2]

    # determine garment landmark pixel coords (landmarks stored relative to garment's own canvas)
    def gx(lm_key, side):
        return garment_lm[lm_key].get(f"{side}_x", garment_lm[lm_key].get("center_x", gw // 2))

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

    if garment_img.shape[2] == 3:
        garment_img = cv2.cvtColor(garment_img, cv2.COLOR_BGR2BGRA)
    garment_rgba = garment_img

    torso = _scanline_strip(garment_rgba, torso_src, torso_dst, H, W, warnings, "torso")
    result = _alpha_composite(result, torso)

    # sleeves
    hand_y = float(a.get("armpit", {}).get("y", a["chest"]["y"])) + (float(a["crotch"]["y"]) - float(a["chest"]["y"])) * 0.5
    armpit_y = float(a["armpit"]["y"]) if "armpit" in a else float(a["chest"]["y"])

    for side in ("left", "right"):
        sign = -1 if side == "left" else 1
        sh_x = float(a["shoulder"][f"{side}_x"])
        arm_outer_x = sh_x + sign * 22
        se = g["sleeve_end"][side]

        src_tri = np.array([
            [g["shoulder"][f"{side}_x"], g["shoulder"]["y"]],
            [g["chest"][f"{side}_x"],    g["chest"]["y"]],
            [se["x"],                    se["y"]],
        ], dtype=np.float32)
        dst_tri = np.array([
            [sh_x,         a["shoulder"]["y"]],
            [sh_x,         armpit_y],
            [arm_outer_x,  hand_y],
        ], dtype=np.float32)

        M = cv2.getAffineTransform(src_tri, dst_tri)
        warped = cv2.warpAffine(garment_rgba, M, (W, H),
                                flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_TRANSPARENT)
        mask = np.zeros((H, W), dtype=np.uint8)
        cv2.fillPoly(mask, [dst_tri.astype(np.int32)], 255)
        warped[:, :, 3] = np.where(mask > 0, warped[:, :, 3], 0)
        result = _alpha_composite(result, warped)

    return result, warnings


def warp_pants(body_lm: dict, garment_lm: dict, garment_img: np.ndarray,
               H: int, W: int) -> tuple[np.ndarray, list]:
    warnings = []
    result = np.zeros((H, W, 4), dtype=np.uint8)
    g = garment_lm
    a = body_lm

    if garment_img.shape[2] == 3:
        garment_img = cv2.cvtColor(garment_img, cv2.COLOR_BGR2BGRA)
    garment_rgba = garment_img

    crotch_y_g = float(g["crotch"]["y"])
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
    block = _scanline_strip(garment_rgba, block_src, block_dst, H, W, warnings, "waist-crotch")
    result = _alpha_composite(result, block)

    ankle_l = a["ankle"]["left_leg"]
    ankle_r = a["ankle"]["right_leg"]
    half_w = int((a["hip"]["right_x"] - a["hip"]["left_x"]) // 2)

    for side in ("left", "right"):
        if side == "left":
            g_lx_c = g["hip"]["left_x"]
            g_rx_c = g["waist"]["center_x"] - 5
            g_lx_k = g["knee"]["left_leg"]["left_x"]
            g_rx_k = g["knee"]["left_leg"]["right_x"]
            g_hem  = g["hem"]["left_leg"]
            a_lx_c = a["hip"]["left_x"]
            a_rx_c = a["hip"]["left_x"] + half_w - 10
            a_lx_k = a["knee"]["left_leg"]["left_x"]
            a_rx_k = a["knee"]["left_leg"]["right_x"]
            a_ank_lx = int(ankle_l["left_x"])
            a_ank_rx = int(ankle_l["right_x"])
            a_ank_y  = float(ankle_l["y"])
        else:
            g_lx_c = g["waist"]["center_x"] + 5
            g_rx_c = g["hip"]["right_x"]
            g_lx_k = g["knee"]["right_leg"]["left_x"]
            g_rx_k = g["knee"]["right_leg"]["right_x"]
            g_hem  = g["hem"]["right_leg"]
            a_lx_c = a["hip"]["left_x"] + half_w + 10
            a_rx_c = a["hip"]["right_x"]
            a_lx_k = a["knee"]["right_leg"]["left_x"]
            a_rx_k = a["knee"]["right_leg"]["right_x"]
            a_ank_lx = int(ankle_r["left_x"])
            a_ank_rx = int(ankle_r["right_x"])
            a_ank_y  = float(ankle_r["y"])

        leg_src = [
            (crotch_y_g,     g_lx_c, g_rx_c),
            (g["knee"]["y"], g_lx_k, g_rx_k),
            (g_hem["y"],     g_hem["left_x"], g_hem["right_x"]),
        ]
        leg_dst = [
            (crotch_y_a,     a_lx_c, a_rx_c),
            (a["knee"]["y"], a_lx_k, a_rx_k),
            (a_ank_y,        a_ank_lx, a_ank_rx),
        ]
        leg = _scanline_strip(garment_rgba, leg_src, leg_dst, H, W, warnings, f"{side}-leg")
        result = _alpha_composite(result, leg)

    return result, warnings


def composite(body_img: np.ndarray, garment_warp: np.ndarray) -> np.ndarray:
    """Composite warped garment over body, return 600×1200 RGB."""
    H, W = body_img.shape[:2]
    if body_img.shape[2] == 3:
        body_rgba = cv2.cvtColor(body_img, cv2.COLOR_BGR2BGRA)
        body_rgba[:, :, 3] = 255
    else:
        body_rgba = body_img.copy()

    result = _alpha_composite(body_rgba, garment_warp)
    final = np.full((H, W, 3), 255, dtype=np.uint8)
    alpha = result[:, :, 3:4] / 255.0
    final = (result[:, :, :3] * alpha + final * (1 - alpha)).astype(np.uint8)
    return final
