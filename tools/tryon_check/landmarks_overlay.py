"""Landmark overlays + docs/03 sanity checks for the 6 avatars and every garment with landmarks (read-only).

    docker compose exec -T backend python manage.py shell < tools/tryon_check/landmarks_overlay.py
    docker compose cp backend:/tmp/landmarks_overlay/. tools/tryon_check/out/landmarks_overlay/

Writes avatar_<id>_<sex>_<build>.png (600x1200 canvas, 1x) and garment_<id>_<type>.png (2x) with every landmark line,
its left/right ticks and its name, and prints the check results. Nothing is written to the DB.
Checks (docs/03):
  avatars: vertical order, % of figure height ranges, ankle < knee, shoulder < 1.6 x chest, one knee < 0.5 x hip,
           left/right knee and ankle widths within 15 %, every tick within 2 px of a silhouette edge on its row.
  garments: apps/garments/landmark_checks.py (required keys, left < right, order), every tick within 2 px of an
           alpha edge on its row.
"""
import os

import cv2
import numpy as np

from apps.avatars.models import Avatar
from apps.garments.landmark_checks import LandmarksInvalid, validate_garment_landmarks
from apps.garments.models import Garment

OUT = "/tmp/landmarks_overlay"
os.makedirs(OUT, exist_ok=True)
EDGE_PX = 2
COLORS = [(13, 115, 217), (224, 79, 139), (90, 58, 214), (100, 165, 31), (232, 120, 59), (192, 167, 26),
          (160, 179, 47), (0, 140, 255), (180, 0, 180), (0, 160, 0), (60, 60, 220)]
ORDER = ["head_top", "neck", "shoulder", "armpit", "chest", "waist", "hip", "crotch", "knee"]
RANGES = {"neck": (12, 19), "shoulder": (16, 23), "armpit": (25, 35), "chest": (27, 38), "waist": (34, 47),
          "hip": (46, 59), "crotch": (49, 61), "knee": (68, 76), "ankle": (84, 95)}


def read(path):
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    return cv2.cvtColor(img, cv2.COLOR_BGR2BGRA) if img.shape[2] == 3 else img


def segments(lm):
    """(name, y, [x ...]) per drawn line; legs give one line each."""
    out = []
    for name, v in lm.items():
        if not isinstance(v, dict):
            continue
        if "left_leg" in v or "left" in v:
            for side in ("left_leg", "right_leg", "left", "right"):
                s = v.get(side)
                if not isinstance(s, dict):
                    continue
                y = s.get("y", v.get("y"))
                xs = [s[k] for k in ("left_x", "right_x", "x") if k in s]
                if y is not None and xs:
                    out.append((f"{name}.{side}", y, xs))
        elif "y" in v:
            xs = [v[k] for k in ("left_x", "center_x", "right_x") if k in v]
            out.append((name, v["y"], xs))
    return out


def edge_ticks(lm):
    """(label, x, y) of every point that should sit on a silhouette edge (center points are not edges)."""
    pts = []
    for name, y, _ in segments(lm):
        base, _, side = name.partition(".")
        v = lm[base] if not side else lm[base][side]
        for k in ("left_x", "right_x", "x"):
            if k in v:
                pts.append((f"{name}.{k}", v[k], y))
    return pts


def edge_dist(mask, x, y):
    yi = int(round(y))
    if not 0 <= yi < mask.shape[0]:
        return 1e9
    row = mask[yi].astype(np.int8)
    trans = np.nonzero(np.diff(row))[0] + 0.5  # boundary between pixel i and i+1
    trans = np.concatenate([trans, [-0.5] if row[0] else [], [len(row) - 0.5] if row[-1] else []])
    return float(np.min(np.abs(trans - x))) if len(trans) else 1e9


def edge_failures(mask, lm):
    bad = []
    for label, x, y in edge_ticks(lm):
        d = edge_dist(mask, x, y)
        if d > EDGE_PX:
            bad.append(f"{label} {d:.1f} px off the edge" if d < 1e8 else f"{label} row outside the image")
    return bad


def draw(img, lm, scale):
    rgb = img[:, :, :3].astype(np.float32)
    a = img[:, :, 3:4].astype(np.float32) / 255
    canvas = (rgb * a + 235 * (1 - a)).astype(np.uint8)  # light grey background shows the silhouette edge
    canvas = cv2.resize(canvas, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    for i, (name, y, xs) in enumerate(segments(lm)):
        c = COLORS[i % len(COLORS)]
        yy = int(round(y * scale))
        if not xs:  # y-only line (head_top, armpit, crotch, foot_bottom without edge points): dashed, full width
            for x in range(0, canvas.shape[1], 12):
                cv2.line(canvas, (x, yy), (x + 6, yy), c, 1)
            xs = []
            x0 = x1 = None
        else:
            x0, x1 = (min(xs), max(xs)) if len(xs) > 1 else (xs[0] - 15, xs[0] + 15)
        if x0 is not None:
            cv2.line(canvas, (int(x0 * scale), yy), (int(x1 * scale), yy), c, 1, cv2.LINE_AA)
        for x in xs:
            cv2.line(canvas, (int(x * scale), yy - 6), (int(x * scale), yy + 6), c, 2)
        tx = 4 if ".right" not in name else canvas.shape[1] - 130
        cv2.putText(canvas, name, (tx, yy - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 3, cv2.LINE_AA)
        cv2.putText(canvas, name, (tx, yy - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.38, c, 1, cv2.LINE_AA)
    return canvas


def avatar_checks(lm):
    bad = []
    try:
        ys = [lm[k]["y"] for k in ORDER] + [min(lm["ankle"]["left_leg"]["y"], lm["ankle"]["right_leg"]["y"]),
                                             lm["foot_bottom"]["y"]]
    except KeyError as e:
        return [f"missing {e}"]
    names = ORDER + ["ankle", "foot_bottom"]
    for (na, a), (nb, b) in zip(zip(names, ys), zip(names[1:], ys[1:])):
        if (b < a) if (na, nb) == ("armpit", "chest") else (b <= a):
            bad.append(f"order: {nb} ({b:.0f}) not below {na} ({a:.0f})")
    top, fh = lm["head_top"]["y"], lm["foot_bottom"]["y"] - lm["head_top"]["y"]
    for k, (lo, hi) in RANGES.items():
        y = max(lm["ankle"]["left_leg"]["y"], lm["ankle"]["right_leg"]["y"]) if k == "ankle" else lm[k]["y"]
        pct = 100 * (y - top) / fh
        if not lo <= pct <= hi:
            bad.append(f"range: {k} at {pct:.1f}% (expected {lo}-{hi})")
    w = lambda v: v["right_x"] - v["left_x"]  # noqa: E731
    for leg in ("left_leg", "right_leg"):
        if w(lm["ankle"][leg]) >= w(lm["knee"][leg]):
            bad.append(f"ankle {leg} not narrower than the knee")
        if w(lm["knee"][leg]) >= 0.5 * w(lm["hip"]):
            bad.append(f"knee {leg} width >= 0.5 x hip")
    if w(lm["shoulder"]) >= 1.6 * w(lm["chest"]):
        bad.append("shoulder >= 1.6 x chest")
    for part in ("knee", "ankle"):
        l, r = w(lm[part]["left_leg"]), w(lm[part]["right_leg"])
        if abs(l - r) > 0.15 * max(l, r):
            bad.append(f"{part} left/right widths differ > 15 % ({l:.0f} vs {r:.0f})")
    return bad


print("== avatars ==")
for av in Avatar.objects.order_by("pk"):
    img = read(av.image.path)
    lm = av.landmarks
    cv2.imwrite(f"{OUT}/avatar_{av.pk}_{av.sex}_{av.build}.png", draw(img, lm, 1))
    bad = avatar_checks(lm) + edge_failures(img[:, :, 3] > 128, lm)
    print(f"avatar {av.pk} {av.sex} {av.build}: {len(bad)} failure(s)" + "".join(f"\n    - {b}" for b in bad))

print("== garments ==")
for g in Garment.objects.exclude(landmarks={}).order_by("pk"):
    img = read(g.image.path)
    cv2.imwrite(f"{OUT}/garment_{g.pk}_{g.type}.png", draw(img, g.landmarks, 2))
    bad = []
    try:
        validate_garment_landmarks(g.type, g.landmarks, img.shape[1], img.shape[0])
    except LandmarksInvalid as e:
        bad.append(f"rules: {e}")
    bad += edge_failures(img[:, :, 3] > 128, g.landmarks)
    print(f"garment {g.pk} {g.type}: {len(bad)} failure(s)" + "".join(f"\n    - {b}" for b in bad))
