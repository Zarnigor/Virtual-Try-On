"""Pydantic schemas for the AI validation replies (prompts/01 and prompts/02) and a fail-closed parser.

Rule (docs/02 #17): empty, invalid or incomplete AI JSON means REJECTED. Never let it through.
"""
import json
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

BODY_ISSUES = {
    "NO_PERSON", "MULTIPLE_PEOPLE", "NOT_FULL_BODY", "NOT_FRONT_FACING", "NOT_UPRIGHT", "ARMS_NOT_AWAY",
    "LEGS_NOT_APART", "LOOSE_OR_THICK_CLOTHING", "LONG_GARMENT", "LONG_SLEEVES", "OBJECT_OR_ACCESSORY",
    "POOR_LIGHTING", "BLURRY", "NOT_A_REAL_PHOTO", "APPARENT_MINOR", "ESTIMATE_UNCLEAR",
}
GARMENT_ISSUES = {
    "NOT_A_CLOTHING_PHOTO", "NO_GARMENT", "MULTIPLE_GARMENTS", "WRONG_TYPE", "NOT_FRONT_VIEW",
    "GARMENT_CUT_OFF", "LOW_QUALITY",
}
INVALID_AI_RESPONSE = "INVALID_AI_RESPONSE"


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


class GarmentValidation(_Strict):
    """prompts/01-garment-validation.txt"""
    ok: bool
    garment_count: int
    detected_type: Literal["tshirt", "pants", "other", "none"]
    matches_declared_type: bool
    view: Literal["front", "back", "side", "unclear"]
    presentation: Literal["hanger", "flat", "mannequin", "worn_by_person", "other"]
    visible_fraction: float = Field(ge=0, le=1)
    quality: Literal["good", "blurry", "too_dark", "too_small"]
    is_clothing_photo: bool
    issues: list[str]
    confidence: float = Field(ge=0, le=1)

    def passes(self) -> bool:
        return (
            self.ok and not self.issues and self.garment_count == 1 and self.matches_declared_type
            and self.view == "front" and self.visible_fraction >= 0.7 and self.quality == "good"
            and self.is_clothing_photo
        )


@dataclass
class Verdict:
    accepted: bool
    codes: list[str] = field(default_factory=list)


def parse_validation(raw, schema: type[_Strict], known_issues: set[str]) -> Verdict:
    """raw: the model's text reply. Returns a fail-closed verdict with issue codes for the user message."""
    if not raw or not isinstance(raw, (str, bytes)):
        return Verdict(False, [INVALID_AI_RESPONSE])
    try:
        data = schema.model_validate(json.loads(raw))
    except (ValueError, ValidationError):
        return Verdict(False, [INVALID_AI_RESPONSE])
    if data.passes():
        return Verdict(True)
    codes = [c for c in data.issues if c in known_issues]
    return Verdict(False, codes or [INVALID_AI_RESPONSE])
