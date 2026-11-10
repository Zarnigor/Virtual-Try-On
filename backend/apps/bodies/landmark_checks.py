"""Server-side body landmark checks (docs/03 "Body landmark checks"). Pure functions, no DB.

Used by the staff avatar editor (PATCH /api/staff/avatars/{id}/landmarks/). The editor (frontend
`bodyGroups.ts`) runs the same rules with a 4 px gap; here they are strict "<" (armpit <= chest).
Every line has left/right points on the body edge; crotch also has center_x; knee and ankle have one span per leg.
Failure: BodyLandmarksInvalid with a fixed Uzbek message naming the line (never an exception text).
"""
import math

SPAN_LINES = ["head_top", "neck", "shoulder", "armpit", "chest", "waist", "hip", "crotch", "foot_bottom"]
LEG_LINES = ["knee", "ankle"]
LEGS = ("left_leg", "right_leg")

NAMES = {
    "head_top": "Bosh tepasi", "neck": "Boʻyin", "shoulder": "Yelka", "armpit": "Qoʻltiq", "chest": "Koʻkrak",
    "waist": "Bel", "hip": "Son", "crotch": "Qoʻshilish", "knee": "Tizza", "ankle": "Toʻpiq",
    "foot_bottom": "Oyoq tagi",
}


class BodyLandmarksInvalid(Exception):
    def __init__(self, line: str, problem: str):
        self.line = line
        self.detail = f"«{NAMES.get(line, line)}» chizigʻi notoʻgʻri: {problem}"
        super().__init__(self.detail)


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _get(lm, line, *path):
    cur = lm.get(line)
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _need(lm, line, *path, w=None, h=None):
    v = _get(lm, line, *path)
    if not _num(v):
        raise BodyLandmarksInvalid(line, "nuqta qoʻyilmagan.")
    lim = h if path[-1] == "y" else w
    if lim is not None and not 0 <= v <= lim:
        raise BodyLandmarksInvalid(line, "nuqta rasm chegarasidan tashqarida.")
    return float(v)


def line_y(lm: dict, line: str) -> float:
    if line == "ankle":
        return max(lm["ankle"]["left_leg"]["y"], lm["ankle"]["right_leg"]["y"])
    return lm[line]["y"]


def validate_body_landmarks(lm, w: float = 600, h: float = 1200) -> None:
    """Raise BodyLandmarksInvalid on the first broken rule; return None if the landmarks are usable."""
    if not isinstance(lm, dict):
        raise BodyLandmarksInvalid("head_top", "maʼlumot yoʻq.")
    for line in SPAN_LINES:
        _need(lm, line, "y", w=w, h=h)
        left, right = _need(lm, line, "left_x", w=w, h=h), _need(lm, line, "right_x", w=w, h=h)
        if not left < right:
            raise BodyLandmarksInvalid(line, "chap nuqta oʻng nuqtadan chapda boʻlishi kerak.")
    c = _need(lm, "crotch", "center_x", w=w, h=h)
    if not lm["crotch"]["left_x"] < c < lm["crotch"]["right_x"]:
        raise BodyLandmarksInvalid("crotch", "markaz ikki chet orasida boʻlishi kerak.")
    _need(lm, "knee", "y", w=w, h=h)
    for line in LEG_LINES:
        xs = []
        for leg in LEGS:
            if line == "ankle":
                _need(lm, line, leg, "y", w=w, h=h)
            xs += [_need(lm, line, leg, "left_x", w=w, h=h), _need(lm, line, leg, "right_x", w=w, h=h)]
        if not xs[0] < xs[1] < xs[2] < xs[3]:
            raise BodyLandmarksInvalid(line, "har bir oyoqning chap va oʻng nuqtalari tartib bilan, oyoqlar ustma-ust emas.")
    order = ["head_top", "neck", "shoulder", "armpit", "chest", "waist", "hip", "crotch", "knee"]
    for a, b in zip(order, order[1:]):
        ok = lm[a]["y"] <= lm[b]["y"] if (a, b) == ("armpit", "chest") else lm[a]["y"] < lm[b]["y"]
        if not ok:
            raise BodyLandmarksInvalid(b, f"«{NAMES[a]}» chizigʻidan pastda boʻlishi kerak.")
    for leg in LEGS:
        if not lm["knee"]["y"] < lm["ankle"][leg]["y"] < lm["foot_bottom"]["y"]:
            raise BodyLandmarksInvalid("ankle", "tizza va oyoq tagi orasida boʻlishi kerak.")


def complete_body_landmarks(lm: dict) -> dict:
    """Copy with the derived fields recomputed from the edited points: width / center_x per span,
    width per leg, and the shared knee y on both legs. Unknown keys are kept."""
    import copy
    out = copy.deepcopy(lm)
    for line in SPAN_LINES:
        s = out[line]
        s["width"] = s["right_x"] - s["left_x"]
        if line != "crotch":
            s["center_x"] = (s["left_x"] + s["right_x"]) / 2
    for line in LEG_LINES:
        for leg in LEGS:
            s = out[line][leg]
            s["width"] = s["right_x"] - s["left_x"]
            if line == "knee":
                s["y"] = out["knee"]["y"]
    return out
