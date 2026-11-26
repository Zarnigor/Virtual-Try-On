"""Uzbek user messages for the fit check (docs/11 "User messages"; pure, no Django). Backend-produced
(docs/02 rule 18): the frontend shows `detail` as is."""
from .fit import FitResult

GARMENT_SIZE_MISSING = "Bu kiyimning oʻlchamlari kiritilmagan."
BODY_SIZE_MISSING = "Kiyimni tekshirish uchun oʻlchamlaringizni kiriting."

ZONE_NAMES = {"chest": "koʻkrak", "shoulder": "yelka", "waist": "bel", "hip": "son", "inseam": "uzunlik"}
# zone -> (too_small word, too_large word); default tor | keng
_WORDS = {"inseam": ("qisqa", "uzun")}

# Measurement field names (MEASUREMENTS_INVALID)
FIELD_NAMES = {
    "height_cm": "Boʻy", "chest": "Koʻkrak", "waist": "Bel", "hip": "Son", "shoulder_width": "Yelka eni",
    "inseam": "Ichki chok uzunligi",
}


def format_cm(value: float) -> str:
    """1 decimal, trailing .0 dropped: 6.0 -> "6", 2.25 -> "2.3" (half away from zero is not needed: round())."""
    text = f"{round(value, 1):.1f}"
    return text[:-2] if text.endswith(".0") else text


def zone_line(c) -> str:
    """too_small: "Bu kiyim sizga mos emas: {zone} {n} sm tor|qisqa."; too_large (a warning, docs/09 #128):
    "Bu kiyim sizga katta: {zone} {n} sm keng|uzun."; "" for an ok zone."""
    if c.verdict == "ok":
        return ""
    small, large = _WORDS.get(c.zone, ("tor", "keng"))
    n = format_cm(abs(c.garment_cm - c.limit_cm))
    if c.verdict == "too_small":
        return f"Bu kiyim sizga mos emas: {ZONE_NAMES[c.zone]} {n} sm {small}."
    return f"Bu kiyim sizga katta: {ZONE_NAMES[c.zone]} {n} sm {large}."


def size_mismatch_detail(result: FitResult) -> str:
    """400 SIZE_MISMATCH detail: one line per failing zone (too_small and too_large), in zone order."""
    return "\n".join(line for line in map(zone_line, result.checks) if line)


def warning_detail(result: FitResult) -> str:
    """The too_large lines only ("" when there is no warning)."""
    return "\n".join(zone_line(c) for c in result.warnings)


def measurement_invalid_detail(key: str, lo=None, hi=None) -> str:
    name = FIELD_NAMES.get(key)
    if name is None:
        return f"Nomaʼlum oʻlcham: {key}."
    if lo is None:
        return f"{name}: son kiriting."
    return f"{name}: {format_cm(lo)} dan {format_cm(hi)} sm gacha boʻlishi kerak."


def measurement_missing_detail(key: str) -> str:
    """A required body size that was not sent (POST body/confirm/, docs/09 #130)."""
    return f"{FIELD_NAMES.get(key, key)}: kiriting."
