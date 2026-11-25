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


def size_mismatch_detail(result: FitResult) -> str:
    """One line per failing zone: "Bu kiyim sizga mos emas: {zone} {n} sm {tor|keng}."."""
    lines = []
    for c in result.checks:
        if c.verdict == "ok":
            continue
        small, large = _WORDS.get(c.zone, ("tor", "keng"))
        word = small if c.verdict == "too_small" else large
        n = abs(c.garment_cm - c.limit_cm)
        lines.append(f"Bu kiyim sizga mos emas: {ZONE_NAMES[c.zone]} {format_cm(n)} sm {word}.")
    return "\n".join(lines)


def measurement_invalid_detail(key: str, lo=None, hi=None) -> str:
    name = FIELD_NAMES.get(key)
    if name is None:
        return f"Nomaʼlum oʻlcham: {key}."
    if lo is None:
        return f"{name}: son kiriting."
    return f"{name}: {format_cm(lo)} dan {format_cm(hi)} sm gacha boʻlishi kerak."
