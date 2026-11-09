"""Garment landmark checks (pure, no Django). Used by PATCH garments/{id}/landmarks/.

The required keys are exactly what apps/tryon_engine/warp.py reads. Coordinates are pixels of the cleaned PNG.
Order checks use a strict "<"; the editor keeps an extra 4 px gap (frontend garmentGroups.ts, same rules).
Unknown extra keys are allowed and never touched: this module only reads.
"""
import math

# Group names as the editor shows them (frontend/src/components/landmark-editor/garmentGroups.ts).
GROUP_NAMES = {
    "tshirt": {"shoulder": "Yelka", "sleeve_end": "Yeng", "chest": "Koʻkrak", "waist": "Bel", "hem": "Pastki"},
    "pants": {"waist": "Bel", "hip": "Son", "crotch": "Qoʻshilish", "knee": "Tizza", "hem": "Pocha"},
}

REQUIRED = {
    "tshirt": [
        "shoulder.y", "shoulder.left_x", "shoulder.right_x",
        "sleeve_end.left.x", "sleeve_end.left.y", "sleeve_end.right.x", "sleeve_end.right.y",
        "chest.y", "chest.left_x", "chest.right_x",
        "waist.y", "waist.left_x", "waist.right_x",
        "hem.y", "hem.left_x", "hem.right_x",
    ],
    "pants": [
        "waist.y", "waist.left_x", "waist.right_x", "waist.center_x",
        "hip.y", "hip.left_x", "hip.right_x",
        "crotch.y", "crotch.center_x",
        "knee.y", "knee.left_leg.left_x", "knee.left_leg.right_x", "knee.right_leg.left_x", "knee.right_leg.right_x",
        "hem.left_leg.y", "hem.left_leg.left_x", "hem.left_leg.right_x",
        "hem.right_leg.y", "hem.right_leg.left_x", "hem.right_leg.right_x",
    ],
}

# warp.py uses waist.center_x - 5 / + 5 as the inner crotch edges of the two legs.
CENTER_HIP_MARGIN = 5

MESSAGES = {
    "missing": "«{g}» belgisi toʻliq emas. Barcha nuqtalarni qoʻying.",
    "bounds": "«{g}» nuqtasi rasm chegarasidan chiqib ketgan.",
    "x_order": "«{g}»: chap nuqta oʻng nuqtadan chapda boʻlsin.",
    "legs": "«{g}»: chap va oʻng poycha bir-birini kesib oʻtmasin.",
    "center": "«{g}»: markaz nuqtasi chap va oʻng nuqtalar orasida boʻlsin.",
    "center_hip": "«{g}»: markaz nuqtasi «{other}» chizigʻining ichida boʻlsin.",
    "y_order": "«{g}» chizigʻi «{other}» chizigʻidan pastda boʻlsin.",
}


class LandmarksInvalid(Exception):
    def __init__(self, reason: str, group: str, detail: str):
        super().__init__(reason)
        self.reason = reason
        self.group = group
        self.detail = detail


def _get(obj, path: str):
    for key in path.split("."):
        if not isinstance(obj, dict) or key not in obj:
            return None
        obj = obj[key]
    return obj


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def validate_garment_landmarks(gtype: str, landmarks, width: int, height: int) -> None:
    """Raise LandmarksInvalid (reason, group, Uzbek detail) on the first broken rule; return None if valid."""
    names = GROUP_NAMES[gtype]

    def fail(reason, group, other=None):
        raise LandmarksInvalid(reason, group, MESSAGES[reason].format(g=names[group], other=names.get(other, "")))

    if not isinstance(landmarks, dict):
        fail("missing", next(iter(names)))

    v = {}
    for path in REQUIRED[gtype]:
        value = _get(landmarks, path)
        if not _is_number(value):
            fail("missing", path.split(".")[0])
        v[path] = float(value)

    for path, value in v.items():
        limit = width if path.endswith("x") else height
        if not 0 <= value <= limit:
            fail("bounds", path.split(".")[0])

    def lt(a, b, reason, group, other=None):
        if not v[a] < v[b]:
            fail(reason, group, other)

    if gtype == "tshirt":
        for g in ("shoulder", "chest", "waist", "hem"):
            lt(f"{g}.left_x", f"{g}.right_x", "x_order", g)
        lt("sleeve_end.left.x", "sleeve_end.right.x", "x_order", "sleeve_end")
        for upper, lower in (("shoulder", "chest"), ("chest", "waist"), ("waist", "hem")):
            lt(f"{upper}.y", f"{lower}.y", "y_order", lower, upper)
        for side in ("left", "right"):
            lt("shoulder.y", f"sleeve_end.{side}.y", "y_order", "sleeve_end", "shoulder")
        return

    # pants
    for g in ("waist", "hip"):
        lt(f"{g}.left_x", f"{g}.right_x", "x_order", g)
    for g in ("knee", "hem"):
        for leg in ("left_leg", "right_leg"):
            lt(f"{g}.{leg}.left_x", f"{g}.{leg}.right_x", "x_order", g)
        lt(f"{g}.left_leg.right_x", f"{g}.right_leg.left_x", "legs", g)
    lt("waist.left_x", "waist.center_x", "center", "waist")
    lt("waist.center_x", "waist.right_x", "center", "waist")
    if not v["hip.left_x"] + CENTER_HIP_MARGIN < v["waist.center_x"] < v["hip.right_x"] - CENTER_HIP_MARGIN:
        fail("center_hip", "waist", "hip")
    hem_y = max(v["hem.left_leg.y"], v["hem.right_leg.y"])
    order = [("waist", v["waist.y"]), ("hip", v["hip.y"]), ("crotch", v["crotch.y"]), ("knee", v["knee.y"]),
             ("hem", hem_y)]
    for (upper, uy), (lower, ly) in zip(order, order[1:]):
        if not uy < ly:
            fail("y_order", lower, upper)
