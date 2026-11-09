"""Pydantic schemas for the AI validation replies (prompts/01 and prompts/02) and fail-closed parsers.

Rule (docs/02 #17): empty, invalid or incomplete AI JSON means REJECTED. Never let it through.
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

BODY_ISSUES = {
    "NO_PERSON", "MULTIPLE_PEOPLE", "NOT_FULL_BODY", "NOT_FRONT_FACING", "NOT_UPRIGHT", "ARMS_NOT_AWAY",
    "LEGS_NOT_APART", "LOOSE_OR_THICK_CLOTHING", "LONG_GARMENT", "LONG_SLEEVES", "OBJECT_OR_ACCESSORY",
    "POOR_LIGHTING", "BLURRY", "NOT_A_REAL_PHOTO", "APPARENT_MINOR", "ESTIMATE_UNCLEAR",
}
AI_RESPONSE_INVALID = "AI_RESPONSE_INVALID"  # a reply came back but is not valid JSON / does not match the schema


class _Strict(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class BodyValidation(_Strict):
    """prompts/02-body-validation.txt"""
    ok: bool
    person_count: int
    full_body_visible: bool
    front_facing: bool
    upright: bool
    arms_away: bool
    legs_apart: bool
    clothing: Literal["tight", "loose", "thick", "long_garment", "unclear"]
    sleeves: Literal["none", "short", "long", "unclear"]
    held_objects_or_accessories: bool
    lighting: Literal["good", "poor"]
    sharpness: Literal["good", "blurry"]
    is_real_photo: bool
    apparent_age: Literal["adult", "minor_suspected", "unclear"]
    issues: list[str]
    confidence: float = Field(ge=0, le=1)

    def passes(self) -> bool:
        """Re-check the decision rules in code: the model's own `ok` is not trusted alone."""
        return (
            self.ok and not self.issues and self.person_count == 1 and self.full_body_visible
            and self.front_facing and self.upright and self.arms_away and self.legs_apart
            and self.clothing == "tight" and self.sleeves in ("none", "short")
            and not self.held_objects_or_accessories and self.lighting == "good"
            and self.sharpness == "good" and self.is_real_photo and self.apparent_age == "adult"
        )


@dataclass
class Verdict:
    accepted: bool
    codes: list[str] = field(default_factory=list)


def parse_validation(raw, schema: type[_Strict], known_issues: set[str]) -> Verdict:
    """raw: the model's text reply. Returns a fail-closed verdict with issue codes for the user message."""
    if not raw or not isinstance(raw, (str, bytes)):
        return Verdict(False, [AI_RESPONSE_INVALID])
    try:
        data = schema.model_validate(json.loads(raw))
    except (ValueError, ValidationError):
        return Verdict(False, [AI_RESPONSE_INVALID])
    if data.passes():
        return Verdict(True)
    codes = [c for c in data.issues if c in known_issues]
    return Verdict(False, codes or [AI_RESPONSE_INVALID])


# ---------- garment (prompts/01-garment-validation.txt) ----------

# Our garment type -> the DECLARED TYPE word prompt 01 uses.
PROMPT_GARMENT_TYPE = {"tshirt": "top", "pants": "pants"}
WRONG_GARMENT_TYPE = "WRONG_GARMENT_TYPE"
MIN_VISIBLE_FRACTION = 0.6  # prompt 01 RULES
TSHIRT_SLEEVES = {"none", "short"}  # MVP T-shirt = short-sleeved or sleeveless (docs/09 #3)

# Codes the backend can report for a garment, in the order the first one becomes the job's error_code.
GARMENT_CODES = (
    "NOT_A_CLOTHING_PHOTO", "NO_GARMENT", "MULTIPLE_GARMENTS", WRONG_GARMENT_TYPE, "NOT_FRONT_VIEW",
    "GARMENT_CUT_OFF", "LOW_QUALITY",
)
# The AI's own issue codes (prompt 01) -> backend codes. The AI's WRONG_TYPE becomes WRONG_GARMENT_TYPE.
_AI_GARMENT_ISSUES = {c: c for c in GARMENT_CODES} | {"WRONG_TYPE": WRONG_GARMENT_TYPE}


class GarmentValidation(_Strict):
    """The JSON block of prompts/01-garment-validation.txt, field for field."""
    ok: bool
    garment_count: int = Field(ge=0)
    detected_type: Literal["top", "pants", "other", "none"]
    sleeve_length: Literal["none", "short", "three_quarter", "long", "not_applicable"]
    view: Literal["front", "back", "side", "unclear"]
    presentation: Literal["hanger", "flat", "mannequin", "worn_by_person", "other"]
    visible_fraction: float = Field(ge=0, le=1)
    quality: Literal["good", "blurry", "too_dark", "too_small"]
    is_clothing_photo: bool
    issues: list[str]
    confidence: float = Field(ge=0, le=1)

    def derived_codes(self, declared: str) -> list[str]:
        """Codes from the reply's own fields, checked in code: the model's `ok` and `issues` are not trusted alone."""
        codes = []
        if not self.is_clothing_photo:
            codes.append("NOT_A_CLOTHING_PHOTO")
        if self.garment_count == 0 or self.detected_type == "none":
            codes.append("NO_GARMENT")
        elif self.garment_count > 1:
            codes.append("MULTIPLE_GARMENTS")
        if self.detected_type not in ("none", PROMPT_GARMENT_TYPE[declared]):
            codes.append(WRONG_GARMENT_TYPE)
        elif declared == "tshirt" and self.detected_type == "top" and self.sleeve_length not in TSHIRT_SLEEVES:
            codes.append(WRONG_GARMENT_TYPE)  # a long-sleeve top is not a T-shirt
        if self.view != "front":
            codes.append("NOT_FRONT_VIEW")
        if self.visible_fraction < MIN_VISIBLE_FRACTION:
            codes.append("GARMENT_CUT_OFF")
        if self.quality != "good":
            codes.append("LOW_QUALITY")
        return codes


@dataclass
class GarmentVerdict:
    accepted: bool
    codes: list[str] = field(default_factory=list)
    data: GarmentValidation | None = None  # None = the reply was not valid JSON for the schema

    @property
    def cacheable(self) -> bool:
        """Only a well-formed, self-consistent answer is cached (never AI_RESPONSE_INVALID)."""
        return self.data is not None and AI_RESPONSE_INVALID not in self.codes


def judge_garment(data: GarmentValidation, declared: str) -> GarmentVerdict:
    """Fail closed both ways: merge the derived codes with the AI's issues; accept only if ok and none remain."""
    if declared not in PROMPT_GARMENT_TYPE:
        raise ValueError(f"unsupported garment type {declared!r}")
    found = set(data.derived_codes(declared))
    found |= {_AI_GARMENT_ISSUES[c] for c in data.issues if c in _AI_GARMENT_ISSUES}
    codes = [c for c in GARMENT_CODES if c in found]
    if data.ok and not codes:
        return GarmentVerdict(True, [], data)
    # ok: false but no failing field and no known issue: the reply contradicts itself.
    return GarmentVerdict(False, codes or [AI_RESPONSE_INVALID], data)


def parse_garment_validation(raw, declared: str) -> GarmentVerdict:
    """raw: the model's reply text. Empty, non-JSON or schema-mismatched -> AI_RESPONSE_INVALID."""
    if not raw or not isinstance(raw, (str, bytes)):
        return GarmentVerdict(False, [AI_RESPONSE_INVALID])
    try:
        data = GarmentValidation.model_validate_json(raw)
    except ValidationError as e:
        logger.warning("garment validation reply invalid at %s", [list(err["loc"]) for err in e.errors()][:10])
        return GarmentVerdict(False, [AI_RESPONSE_INVALID])
    return judge_garment(data, declared)


def garment_response_schema() -> dict:
    """JSON schema sent as responseJsonSchema, generated from the same model that parses the reply."""
    schema = GarmentValidation.model_json_schema()
    schema.pop("description", None)  # the class docstring is for developers, not the model
    return schema
