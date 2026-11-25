"""Body measurement validator for the fit check (docs/11 "Body sizes"; pure, dict in / dict out).

Used by POST tryon/ (`measurements`, base=avatar) and by Body (POST body/confirm/, PATCH body/measurements/).
Every key is optional here; which keys a garment needs is check_fit's job. Ranges are inclusive cm, finite numbers
only (no bool / strings). chest, waist, hip are circumferences; shoulder_width is a width. The Body circumference
`shoulder` (docs/09 #13) is not a fit-check key: Body passes it through without this validator.
"""
import math

from .messages import measurement_invalid_detail

RANGES = {
    "height_cm": (140, 210), "chest": (70, 150), "waist": (55, 150), "hip": (75, 160),
    "shoulder_width": (30, 60), "inseam": (55, 100),
}


class MeasurementsInvalid(Exception):
    def __init__(self, key: str, detail: str):
        super().__init__(detail)
        self.key = key
        self.detail = detail


def validate_measurements(data, keys=None) -> dict:
    """Return a new dict with the valid values (None values dropped). Raise MeasurementsInvalid naming the field.
    `keys` limits the accepted keys (default: all of RANGES); any other key is rejected."""
    allowed = RANGES if keys is None else {k: RANGES[k] for k in keys}
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise MeasurementsInvalid("", "Oʻlchamlar obyekt boʻlishi kerak.")
    out = {}
    for key, value in data.items():
        if key not in allowed:
            raise MeasurementsInvalid(key, measurement_invalid_detail(key))
        if value is None:
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise MeasurementsInvalid(key, measurement_invalid_detail(key))
        lo, hi = allowed[key]
        if not lo <= value <= hi:
            raise MeasurementsInvalid(key, measurement_invalid_detail(key, lo, hi))
        out[key] = value
    return out
