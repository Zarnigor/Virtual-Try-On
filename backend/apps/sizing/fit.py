"""Fit check: does a garment of known real size fit a body of known size? (docs/11, docs/09 #125).

Pure logic: plain dicts in, frozen dataclasses out. Imports no model and nothing from tryon_engine, garments or
bodies; the render never sees these numbers. Thresholds come from settings.FIT_RULES (or a `rules` argument).

Garment sizes are flat-lay cm (apps/garments/size_checks.py keys). Body sizes (cm):
  chest, waist, hip = circumferences; shoulder_width = a WIDTH (not the circumference `shoulder` stored in
  Body/Avatar.measurements, which is never converted); inseam optional, else height_cm x BODY_INSEAM_HEIGHT_RATIO.
"""
import math
from dataclasses import dataclass

EPS = 1e-9  # "exactly on a limit passes" must survive float noise (e.g. 2 x 45.1)

# type -> [(zone, garment key, body key, garment value is a flat width -> x2)], in report order
ZONES = {
    "tshirt": [("chest", "chest_width", "chest", True), ("shoulder", "shoulder_width", "shoulder_width", False)],
    "pants": [("waist", "waist_width", "waist", True), ("hip", "hip_width", "hip", True),
              ("inseam", "inseam", "inseam", False)],
}
FIT_MODES = ("adapt", "keep_shape")


class SizesMissing(Exception):
    def __init__(self, side: str, keys: list):
        super().__init__(f"{side} sizes missing: {', '.join(keys)}")
        self.side = side
        self.keys = list(keys)


@dataclass(frozen=True)
class ZoneCheck:
    zone: str
    garment_cm: float
    body_cm: float
    ease_cm: float
    verdict: str  # ok | too_small | too_large
    limit_cm: float | None  # the broken limit, in garment_cm units (body + allowed ease); None when ok


@dataclass(frozen=True)
class FitResult:
    fits: bool
    checks: list


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _body_value(body, key, ratio):
    if key == "inseam" and not _num(body.get("inseam")) and _num(body.get("height_cm")):
        return body["height_cm"] * ratio
    return body.get(key)


def check_fit(garment_type, garment_sizes, stretch, fit_mode, body_sizes, rules=None) -> FitResult:
    if garment_type not in ZONES:
        raise ValueError(f"unknown garment_type: {garment_type!r}")
    if fit_mode not in FIT_MODES:
        raise ValueError(f"unknown fit_mode: {fit_mode!r}")
    if rules is None:
        from django.conf import settings
        rules = settings.FIT_RULES
    zones = ZONES[garment_type]
    ratio = rules["BODY_INSEAM_HEIGHT_RATIO"]

    garment = garment_sizes if isinstance(garment_sizes, dict) else {}
    missing = [g for _, g, _, _ in zones if not _num(garment.get(g))]
    if missing:
        raise SizesMissing("garment", missing)
    body = body_sizes if isinstance(body_sizes, dict) else {}
    missing = [b for _, _, b, _ in zones if not _num(_body_value(body, b, ratio))]
    if missing:
        raise SizesMissing("body", missing)

    checks = []
    for zone, gkey, bkey, flat in zones:
        rule = rules[garment_type][zone]
        g = garment[gkey] * (2 if flat else 1)
        b = _body_value(body, bkey, ratio)
        ease = g - b
        min_ease = rule.get("min_ease_stretch", rule["min_ease"]) if stretch else rule["min_ease"]
        verdict, limit = "ok", None
        if ease < min_ease - EPS:
            verdict, limit = "too_small", b + min_ease
        elif fit_mode == "adapt" and ease > rule["max_ease"] + EPS:
            verdict, limit = "too_large", b + rule["max_ease"]
        checks.append(ZoneCheck(zone, round(g, 1), round(b, 1), round(ease, 1), verdict,
                                None if limit is None else round(limit, 1)))
    return FitResult(all(c.verdict == "ok" for c in checks), checks)
