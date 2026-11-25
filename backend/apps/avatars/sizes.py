"""Avatar sizes for the fit check (docs/11, docs/09 #129): shoulder WIDTH from the shoulder landmarks.

width_cm = px width x height_cm / (foot_bottom.y - head_top.y)  (docs/09 #76, the staff editor's cm rule).
Pure: plain dicts in, a number (1 decimal) or None out.
"""


def _span_px(line):
    if not isinstance(line, dict):
        return None
    if isinstance(line.get("left_x"), (int, float)) and isinstance(line.get("right_x"), (int, float)):
        return float(line["right_x"] - line["left_x"])
    w = line.get("width")
    return float(w) if isinstance(w, (int, float)) else None


def shoulder_width_cm(landmarks, height_cm):
    """None when the landmarks or the height do not allow it."""
    if not isinstance(landmarks, dict) or not isinstance(height_cm, (int, float)) or height_cm <= 0:
        return None
    width_px = _span_px(landmarks.get("shoulder"))
    try:
        figure_px = float(landmarks["foot_bottom"]["y"]) - float(landmarks["head_top"]["y"])
    except (KeyError, TypeError, ValueError):
        return None
    if width_px is None or width_px <= 0 or figure_px <= 0:
        return None
    return round(width_px * height_cm / figure_px, 1)
