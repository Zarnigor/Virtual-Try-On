"""Flatten the photo lighting of near-solid garments once, when the garment is cleaned (stored in the cleaned PNG).

A solid-colour T-shirt photographed under a lamp has a dark side and a bright side; warped onto an avatar that
reads as a different colour per side. For near-solid garments (low hue/chroma spread and little high-frequency
luminance, i.e. no print) 80 % of the low-frequency deviation from the median colour is removed; the
high-frequency texture (stitches, seams, folds narrower than the blur) is kept. Alpha is never changed.
Printed or multi-colour garments are left untouched. Works on RGBA or BGRA arrays (channel order agnostic).
"""
import cv2
import numpy as np

FLATTEN_STRENGTH = 0.8  # share of the low-frequency deviation removed
SIGMA_FRACTION = 0.08  # illumination blur sigma as a share of the garment width
MAX_HUE_STD = 12.0  # degrees: circular hue spread (saturation weighted) above which the garment is multi-colour
MAX_SAT_STD = 20.0  # HSV saturation spread (0..255) above which the garment is multi-colour
GREY_SAT = 30  # mean saturation below this: hue is meaningless (grey/white/black garment), only saturation counts
MAX_DETAIL_STD = 10.0  # std of luminance minus its blur above which the garment counts as printed/patterned


def _blur_masked(x: np.ndarray, m: np.ndarray, sigma: float) -> np.ndarray:
    num = cv2.GaussianBlur(x * m, (0, 0), sigma)
    den = cv2.GaussianBlur(m, (0, 0), sigma)
    return num / np.maximum(den, 1e-6)


def is_near_solid(img: np.ndarray, opaque: np.ndarray | None = None) -> bool:
    """Low chroma spread and mostly low-frequency luminance over the opaque area."""
    if opaque is None:
        opaque = img[:, :, 3] >= 250
    if opaque.sum() < 100:
        return False
    # hue and saturation do not change with the lighting (a shaded side of one colour is still one colour)
    hsv = cv2.cvtColor(np.ascontiguousarray(img[:, :, :3]), cv2.COLOR_RGB2HSV).astype(np.float32)
    hue, sat = hsv[:, :, 0][opaque] * (np.pi / 90), hsv[:, :, 1][opaque]
    if float(sat.std()) > MAX_SAT_STD:
        return False
    if sat.mean() >= GREY_SAT:
        w = sat / sat.sum()
        r = abs(complex((w * np.cos(hue)).sum(), (w * np.sin(hue)).sum()))
        if np.degrees(np.sqrt(-2 * np.log(max(r, 1e-9)))) > MAX_HUE_STD:
            return False
    lab = cv2.cvtColor(np.ascontiguousarray(img[:, :, :3]), cv2.COLOR_RGB2LAB).astype(np.float32)
    xs = np.nonzero(opaque.any(axis=0))[0]
    sigma = max(SIGMA_FRACTION * (xs[-1] - xs[0] + 1), 1.0)
    L = lab[:, :, 0]
    detail = (L - _blur_masked(L, opaque.astype(np.float32), sigma))[cv2.erode(opaque.astype(np.uint8),
                                                                               np.ones((5, 5), np.uint8)) > 0]
    return detail.size > 0 and float(detail.std()) <= MAX_DETAIL_STD


def flatten_lighting(img: np.ndarray, strength: float = FLATTEN_STRENGTH) -> np.ndarray:
    """Near-solid garment: out = pixel - strength * (lowfreq - median), per channel, on every pixel with alpha > 0.
    Anything else is returned unchanged."""
    opaque = img[:, :, 3] >= 250
    if not is_near_solid(img, opaque):
        return img
    xs = np.nonzero(opaque.any(axis=0))[0]
    sigma = max(SIGMA_FRACTION * (xs[-1] - xs[0] + 1), 1.0)
    m = opaque.astype(np.float32)
    rgb = img[:, :, :3].astype(np.float32)
    median = np.median(rgb[opaque], axis=0)
    low = np.stack([_blur_masked(rgb[:, :, c], m, sigma) for c in range(3)], axis=2)
    out = img.copy()
    covered = img[:, :, 3] > 0
    flat = rgb - strength * (low - median)
    out[:, :, :3][covered] = np.clip(np.rint(flat[covered]), 0, 255).astype(np.uint8)
    return out
