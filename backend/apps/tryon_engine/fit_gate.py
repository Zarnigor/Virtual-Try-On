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

    def as_result(self) -> dict:
        """GET tryon/fit-check/ item: {garment_id, fits, checks, code?, keys?}."""
        out = {"garment_id": self.garment_id, "fits": self.fits, "checks": [asdict(c) for c in self.checks]}
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


def body_sizes_from_body(body) -> dict:
    """Own body: Body.height_cm + Body.measurements (the circumference `shoulder` is not used, docs/11)."""
    m = body.measurements or {}
    sizes = {k: m[k] for k in ("chest", "waist", "hip", "shoulder_width", "inseam") if m.get(k) is not None}
    if body.height_cm is not None:
        sizes["height_cm"] = body.height_cm
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
                      detail="" if r.fits else messages.size_mismatch_detail(r))


def run_gate(garments, body_sizes: dict) -> list:
    """Every garment, in the given order (garment_ids order)."""
    return [check_garment(g, body_sizes) for g in garments]


def first_failure(results):
    return next((r for r in results if not r.fits), None)
