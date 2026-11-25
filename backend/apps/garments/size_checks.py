"""Garment real-size schema and checks (pure, no Django): docs/11-fit-check.md, docs/09 #125.

Sizes are flat-lay centimetres (garment laid flat, measured on one side). Used by POST garments/ and
PATCH garments/{id}/sizes/. Ranges are inclusive; only finite real numbers count (no bool, NaN, inf, strings).
Unknown keys are rejected. The fit check itself (`apps/sizing`) is a later step.
"""
import math

# key -> (min, max) in cm, inclusive
RANGES = {
    "tshirt": {
        "chest_width": (30, 90), "length": (40, 100), "shoulder_width": (30, 70),
        "waist_width": (20, 90), "sleeve_length": (5, 40),
    },
    "pants": {
        "waist_width": (20, 90), "hip_width": (30, 90), "inseam": (40, 100),
        "thigh_width": (15, 50), "leg_opening": (8, 40),
    },
}
REQUIRED = {
    "tshirt": ("chest_width", "length", "shoulder_width"),
    "pants": ("waist_width", "hip_width", "inseam"),
}
# Uzbek field names for messages
NAMES = {
    "chest_width": "Koʻkrak eni", "length": "Uzunlik", "shoulder_width": "Yelka eni", "waist_width": "Bel eni",
    "sleeve_length": "Yeng uzunligi", "hip_width": "Son eni", "inseam": "Ichki chok uzunligi",
    "thigh_width": "Son (yuqori) eni", "leg_opening": "Pocha eni",
}


class SizesInvalid(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def validate_sizes(gtype: str, sizes) -> dict:
    """Return `sizes` unchanged when valid, else raise SizesInvalid with a short Uzbek message naming the field."""
    ranges = RANGES.get(gtype)
    if ranges is None:
        raise SizesInvalid("Kiyim turi notoʻgʻri.")
    if not isinstance(sizes, dict):
        raise SizesInvalid("Oʻlchamlar obyekt boʻlishi kerak.")
    for key in sizes:
        if key not in ranges:
            raise SizesInvalid(f"Nomaʼlum oʻlcham: {key}.")
    for key in REQUIRED[gtype]:
        if key not in sizes:
            raise SizesInvalid(f"{NAMES[key]} kiritilmagan.")
    for key, value in sizes.items():
        lo, hi = ranges[key]
        if not _is_number(value):
            raise SizesInvalid(f"{NAMES[key]}: son kiriting.")
        if not lo <= value <= hi:
            raise SizesInvalid(f"{NAMES[key]}: {lo} dan {hi} sm gacha boʻlishi kerak.")
    return sizes


def sizes_complete(gtype: str, sizes) -> bool:
    """True when every required key is present (False for null sizes)."""
    req = REQUIRED.get(gtype)
    return bool(req) and isinstance(sizes, dict) and all(k in sizes for k in req)
