"""Garment landmark schema and checks (pure, no Django): the single source of truth for both garment types.

Used by PATCH garments/{id}/landmarks/ (write), build_demo / export_demo_garments (read) and the try-on task
(`engine_landmarks`). The frontend mirrors the same rules in landmark-editor/garmentRules.ts.
Coordinates are pixels of the cleaned PNG; left/right = image left/right. Order checks use a strict "<";
the editor keeps an extra 4 px gap. The armpit may lie below the chest line (oversized garments, docs/09 #94).

T-shirt set (docs/03, docs/09 #92). Required (write): shoulder, chest, waist, hem {y, left_x, right_x} and the four
sleeve cuff corners `sleeve_cuff_outer|sleeve_cuff_inner .left|.right {x, y}`, which replace `sleeve_end`.
Optional for now: `armpit {y, left_x, right_x}`, `collar {y, left_x, right_x}` (collar edges at the shoulder line),
`collar_bottom {x, y}` (lowest centre point of the neckline). Legacy `sleeve_end.left|right {x, y}` is accepted on
read instead of the cuffs (records marked before 2026-11-11) and is never written: `for_storage` drops it.
Unknown extra keys are allowed and kept.
"""
import math

# Group names as the editor shows them (frontend/src/locale/uz.ts, same strings).
GROUP_NAMES = {
    "tshirt": {
        "collar": "Yoqa", "shoulder": "Yelka", "collar_bottom": "Yoqa pasti", "armpit": "Qoʻltiq",
        "sleeve_cuff_outer": "Yeng uchi (tashqi)", "sleeve_cuff_inner": "Yeng uchi (ichki)",
        "chest": "Koʻkrak", "waist": "Bel", "hem": "Pastki", "sleeve_end": "Yeng",
    },
    "pants": {"waist": "Bel", "hip": "Son", "crotch": "Qoʻshilish", "knee": "Tizza", "hem": "Pocha"},
}

_SPAN = ("y", "left_x", "right_x")
_SIDES = ("left.x", "left.y", "right.x", "right.y")
# group -> fields; a group is checked as a whole (all fields or, for an optional group, none)
TSHIRT_GROUPS = {
    "shoulder": _SPAN, "chest": _SPAN, "waist": _SPAN, "hem": _SPAN,
    "sleeve_cuff_outer": _SIDES, "sleeve_cuff_inner": _SIDES,
    "armpit": _SPAN, "collar": _SPAN, "collar_bottom": ("x", "y"),
}
TSHIRT_REQUIRED = ("shoulder", "chest", "waist", "hem", "sleeve_cuff_outer", "sleeve_cuff_inner")
TSHIRT_OPTIONAL = ("armpit", "collar", "collar_bottom")
TSHIRT_NEW = ("armpit", "collar", "collar_bottom", "sleeve_cuff_outer", "sleeve_cuff_inner")
LEGACY_SLEEVE = ("sleeve_end", _SIDES)

REQUIRED = {
    "tshirt": [f"{g}.{f}" for g in TSHIRT_REQUIRED for f in TSHIRT_GROUPS[g]],
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
COLLAR_NEAR_SHOULDER = 0.15  # x shoulder span: collar edges further from the shoulder line -> warning
BBOX_TOLERANCE = 2  # px outside the garment's alpha bounding box still accepted without a warning

MESSAGES = {
    "missing": "«{g}» belgisi toʻliq emas. Barcha nuqtalarni qoʻying.",
    "bounds": "«{g}» nuqtasi rasm chegarasidan chiqib ketgan.",
    "x_order": "«{g}»: chap nuqta oʻng nuqtadan chapda boʻlsin.",
    "legs": "«{g}»: chap va oʻng poycha bir-birini kesib oʻtmasin.",
    "center": "«{g}»: markaz nuqtasi chap va oʻng nuqtalar orasida boʻlsin.",
    "center_hip": "«{g}»: markaz nuqtasi «{other}» chizigʻining ichida boʻlsin.",
    "y_order": "«{g}» chizigʻi «{other}» chizigʻidan pastda boʻlsin.",
    "cuff_side": "«{g}»: chap yeng nuqtasi rasmning chap yarmida, oʻngi oʻng yarmida boʻlsin.",
    "cuff_order": "«{g}»: tashqi nuqta yengning tashqi (yelka) tomonida, ichki nuqta qoʻltiq tomonida boʻlsin.",
}
WARNINGS = {
    "collar_far": "«{g}» nuqtalari yelka chizigʻidan uzoq. Yoqa chetlarini yelka chizigʻida belgilang.",
    "outside_garment": "«{g}» nuqtasi kiyimdan tashqarida. Nuqtani kiyim ustiga qoʻying.",
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


def validate_garment_landmarks(gtype: str, landmarks, width: int, height: int, bbox=None,
                               mode: str = "write") -> list[dict]:
    """Raise LandmarksInvalid (reason, group, Uzbek detail) on the first broken rule. Returns the warnings
    [{code, group, detail}] (ranges: collar far from the shoulder line, points outside the garment's alpha
    bounding box `bbox` = (x0, y0, x1, y1) when given). mode "read": a stored T-shirt may carry the legacy
    `sleeve_end` instead of the cuff corners."""
    names = GROUP_NAMES[gtype]

    def fail(reason, group, other=None):
        raise LandmarksInvalid(reason, group, MESSAGES[reason].format(g=names[group], other=names.get(other, "")))

    if not isinstance(landmarks, dict):
        fail("missing", next(iter(names)))

    v = {}

    def take(path):
        value = _get(landmarks, path)
        if not _is_number(value):
            fail("missing", path.split(".")[0])
        v[path] = float(value)

    if gtype == "tshirt":
        legacy = mode == "read" and not any(g in landmarks for g in ("sleeve_cuff_outer", "sleeve_cuff_inner")) \
            and "sleeve_end" in landmarks
        groups = [g for g in TSHIRT_REQUIRED if not (legacy and g.startswith("sleeve_cuff"))]
        groups += [g for g in TSHIRT_OPTIONAL if g in landmarks]  # optional: all of its fields or none
        for g in groups:
            for f in TSHIRT_GROUPS[g]:
                take(f"{g}.{f}")
        if legacy:
            for f in LEGACY_SLEEVE[1]:
                take(f"sleeve_end.{f}")
    else:
        for path in REQUIRED[gtype]:
            take(path)

    for path, value in v.items():
        limit = width if path.endswith("x") else height
        if not 0 <= value <= limit:
            fail("bounds", path.split(".")[0])

    def lt(a, b, reason, group, other=None):
        if not v[a] < v[b]:
            fail(reason, group, other)

    if gtype == "tshirt":
        _tshirt_order(v, lt, fail)
        return _tshirt_warnings(v, bbox, names)

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
    return _bbox_warnings(v, bbox, names)


def _tshirt_order(v, lt, fail):
    has = lambda g: f"{g}.y" in v or f"{g}.left.x" in v or f"{g}.x" in v  # noqa: E731
    for g in ("shoulder", "chest", "waist", "hem", "armpit", "collar"):
        if has(g):
            lt(f"{g}.left_x", f"{g}.right_x", "x_order", g)
    for upper, lower in (("shoulder", "chest"), ("chest", "waist"), ("waist", "hem")):
        lt(f"{upper}.y", f"{lower}.y", "y_order", lower, upper)
    if has("armpit"):
        lt("shoulder.y", "armpit.y", "y_order", "armpit", "shoulder")  # no armpit <= chest rule (docs/09 #94)
    if has("collar_bottom"):
        if has("collar"):
            lt("collar.y", "collar_bottom.y", "y_order", "collar_bottom", "collar")
            lt("collar.left_x", "collar_bottom.x", "center", "collar_bottom")
            lt("collar_bottom.x", "collar.right_x", "center", "collar_bottom")
    if "sleeve_end.left.x" in v:  # legacy record (read only)
        lt("sleeve_end.left.x", "sleeve_end.right.x", "x_order", "sleeve_end")
        for side in ("left", "right"):
            lt("shoulder.y", f"sleeve_end.{side}.y", "y_order", "sleeve_end", "shoulder")
        return
    cx = (v["shoulder.left_x"] + v["shoulder.right_x"]) / 2
    for g in ("sleeve_cuff_outer", "sleeve_cuff_inner"):
        if not (v[f"{g}.left.x"] < cx < v[f"{g}.right.x"]):
            fail("cuff_side", g)
        for side in ("left", "right"):
            lt("shoulder.y", f"{g}.{side}.y", "y_order", g, "shoulder")
    # The axis shoulder point -> cuff midpoint always separates the two corners (it passes through their
    # midpoint): the outer corner must lie on the side away from the torso centre (centre x, chest y).
    for side in ("left", "right"):
        sx, sy = v[f"shoulder.{side}_x"], v["shoulder.y"]
        mx = (v[f"sleeve_cuff_outer.{side}.x"] + v[f"sleeve_cuff_inner.{side}.x"]) / 2
        my = (v[f"sleeve_cuff_outer.{side}.y"] + v[f"sleeve_cuff_inner.{side}.y"]) / 2
        cross = lambda px, py: (mx - sx) * (py - sy) - (my - sy) * (px - sx)  # noqa: E731
        torso = cross(cx, v["chest.y"])
        outer = cross(v[f"sleeve_cuff_outer.{side}.x"], v[f"sleeve_cuff_outer.{side}.y"])
        if not torso * outer < 0:
            fail("cuff_order", "sleeve_cuff_outer")


def _tshirt_warnings(v, bbox, names):
    out = []
    if "collar.y" in v:
        span = v["shoulder.right_x"] - v["shoulder.left_x"]
        if abs(v["collar.y"] - v["shoulder.y"]) > COLLAR_NEAR_SHOULDER * span:
            out.append({"code": "collar_far", "group": "collar",
                        "detail": WARNINGS["collar_far"].format(g=names["collar"])})
    return out + _bbox_warnings(v, bbox, names)


def _bbox_warnings(v, bbox, names):
    if not bbox:
        return []
    x0, y0, x1, y1 = bbox
    seen, out = set(), []
    for path, value in v.items():
        lo, hi = (x0, x1) if path.endswith("x") else (y0, y1)
        group = path.split(".")[0]
        if not lo - BBOX_TOLERANCE <= value <= hi + BBOX_TOLERANCE and group not in seen:
            seen.add(group)
            out.append({"code": "outside_garment", "group": group,
                        "detail": WARNINGS["outside_garment"].format(g=names.get(group, group))})
    return out


def for_storage(gtype: str, landmarks: dict) -> dict:
    """What PATCH stores: the payload as sent (extra keys kept), without the legacy `sleeve_end` (never written)."""
    if gtype != "tshirt":
        return landmarks
    return {k: val for k, val in landmarks.items() if k != "sleeve_end"}


def landmarks_complete(gtype: str, landmarks) -> bool:
    """True when every point of the current set exists (T-shirt: the new points too; pants: no new points)."""
    if not isinstance(landmarks, dict) or not landmarks:
        return False
    groups = TSHIRT_GROUPS if gtype == "tshirt" else None
    if groups is None:
        return all(_is_number(_get(landmarks, p)) for p in REQUIRED[gtype])
    return all(_is_number(_get(landmarks, f"{g}.{f}")) for g in groups for f in groups[g])


def engine_landmarks(gtype: str, landmarks: dict) -> dict:
    """Landmarks for the try-on engine, which still reads `sleeve_end` (the production warp is unchanged): a
    record with cuff corners and no `sleeve_end` gets one per side at the cuff midpoint. Nothing is stored."""
    if gtype != "tshirt" or "sleeve_end" in landmarks or not landmarks:
        return landmarks
    try:
        se = {side: {"x": (landmarks["sleeve_cuff_outer"][side]["x"] + landmarks["sleeve_cuff_inner"][side]["x"]) / 2,
                     "y": (landmarks["sleeve_cuff_outer"][side]["y"] + landmarks["sleeve_cuff_inner"][side]["y"]) / 2}
              for side in ("left", "right")}
    except (KeyError, TypeError):
        return landmarks
    return {**landmarks, "sleeve_end": se}
