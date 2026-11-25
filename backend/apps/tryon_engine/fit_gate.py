"""Fit gate: the one place where try-on meets the fit check (docs/11, docs/09 #125, #126).

View layer only: used by POST tryon/ and GET tryon/fit-check/ (views.py). warp, mls and tasks never import
apps.sizing; apps.sizing imports no models. Garment and body objects are turned into plain dicts here.
"""
from dataclasses import asdict, dataclass, field

from apps.sizing import messages
from apps.sizing.fit import SizesMissing, check_fit

GARMENT_SIZE_MISSING = "GARMENT_SIZE_MISSING"
BODY_SIZE_MISSING = "BODY_SIZE_MISSING"
SIZE_MISMATCH = "SIZE_MISMATCH"


@dataclass(frozen=True)
class GateResult:
    garment_id: int
    fits: bool
    checks: list = field(default_factory=list)  # ZoneCheck list (empty when a size is missing)
    code: str | None = None  # None | GARMENT_SIZE_MISSING | BODY_SIZE_MISSING (missing sizes only)
    keys: list | None = None  # the missing keys for those two codes
    detail: str = ""  # Uzbek message ("" when it fits)
    warnings: list = field(default_factory=list)  # too_large zones: rendered anyway, the user is told (docs/09 #128)
    warning_detail: str = ""  # Uzbek "Bu kiyim sizga katta: ..." lines

    def as_result(self) -> dict:
        """GET tryon/fit-check/ item: {garment_id, fits, checks, warnings, warning_detail, code?, keys?}."""
        out = {"garment_id": self.garment_id, "fits": self.fits, "checks": [asdict(c) for c in self.checks],
               "warnings": [asdict(c) for c in self.warnings], "warning_detail": self.warning_detail}
        if self.code is not None:
            out["code"] = self.code
            out["keys"] = list(self.keys or [])
        return out

    def as_error(self) -> dict:
        """POST tryon/ 400 body for a failing garment."""
        if self.code == BODY_SIZE_MISSING:
            return {"code": BODY_SIZE_MISSING, "keys": list(self.keys), "detail": self.detail}
        if self.code == GARMENT_SIZE_MISSING:
            return {"code": GARMENT_SIZE_MISSING, "garment_id": self.garment_id, "keys": list(self.keys),
                    "detail": self.detail}
        return {"code": SIZE_MISMATCH, "garment_id": self.garment_id,
                "checks": [asdict(c) for c in self.checks], "detail": self.detail}

    def as_warning(self) -> dict:
        """Job result `fit_warnings` item for a rendered garment that is too large somewhere."""
        return {"garment_id": self.garment_id, "checks": [asdict(c) for c in self.warnings],
                "detail": self.warning_detail}


def sizes_from(base) -> dict:
    """The rendered body's sizes (docs/09 #129): Body or Avatar `height_cm` + `measurements` (chest, waist, hip,
    shoulder_width, inseam; the circumference `shoulder` is never used, docs/11). Inseam missing: check_fit estimates."""
    m = base.measurements or {}
    sizes = {k: m[k] for k in ("chest", "waist", "hip", "shoulder_width", "inseam") if m.get(k) is not None}
    if base.height_cm is not None:
        sizes["height_cm"] = base.height_cm
    return sizes


def check_garment(garment, body_sizes: dict) -> GateResult:
    try:
        r = check_fit(garment.type, garment.sizes, garment.stretch, garment.fit_mode, body_sizes)
    except SizesMissing as e:
        if e.side == "garment":
            return GateResult(garment.pk, False, code=GARMENT_SIZE_MISSING, keys=e.keys,
                              detail=messages.GARMENT_SIZE_MISSING)
        return GateResult(garment.pk, False, code=BODY_SIZE_MISSING, keys=e.keys, detail=messages.BODY_SIZE_MISSING)
    return GateResult(garment.pk, r.fits, list(r.checks),
                      detail="" if r.fits else messages.size_mismatch_detail(r),
                      warnings=list(r.warnings), warning_detail=messages.warning_detail(r))


def run_gate(garments, body_sizes: dict) -> list:
    """Every garment, in the given order (garment_ids order)."""
    return [check_garment(g, body_sizes) for g in garments]


def first_failure(results):
    return next((r for r in results if not r.fits), None)


# Calibration (docs/11 "Calibration"): zones that depend on the height alone (a model photo gives only the height).
HEIGHT_ZONES = ("inseam",)


def height_only_checks(garment, height_cm: float) -> list:
    """The height-dependent zone checks of `garment` for a body known only by its height (inseam estimated), with the
    same check_fit rules as the gate. The other required body keys are filled with the garment's own size (ease 0)
    and their zones are dropped. Empty for a garment type without a height zone (T-shirt) or without sizes."""
    gs = garment.sizes or {}
    filler = {"chest": 2 * gs.get("chest_width", 0), "waist": 2 * gs.get("waist_width", 0),
              "hip": 2 * gs.get("hip_width", 0), "shoulder_width": gs.get("shoulder_width", 0)}
    try:
        r = check_fit(garment.type, garment.sizes, garment.stretch, garment.fit_mode,
                      {**filler, "height_cm": height_cm})
    except SizesMissing:
        return []
    return [c for c in r.checks if c.zone in HEIGHT_ZONES]
