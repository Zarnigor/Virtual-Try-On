"""Try-on check without a browser: every seeded avatar x {tshirt, pants, both}, with measured defects.

Runs inside the backend container (reads the DB and media, writes nothing to the DB):
    docker compose cp test-garments/pants_ok.jpg.webp backend:/tmp/tryon_check_in/pants.webp   # optional
    docker compose exec -T -e ENGINE=new backend python manage.py shell < tools/tryon_check/run.py
    docker compose cp backend:/tmp/tryon_check/. tools/tryon_check/out/

ENGINE=old renders with the committed day-1 engine, copied to /tmp/warp_old.py first
(git show <rev>:backend/apps/tryon_engine/warp.py), composed exactly like the old tasks._do_warp.

Garments: the newest T-shirt with saved landmarks (AI-checked first). Pants: /tmp/tryon_check_in/pants.* cut out
in memory with rembg (mask only) and landmarks derived from its alpha (never saved).

Measured per image (same measures for both engines):
  sleeve%   lowest arm row the garment reaches, as % of the arm (shoulder -> hand end). Short sleeve: <= 50.
  hand_px   forearm/hand pixels (lower half of each arm) covered by the garment. Must be 0.
  hem       T-shirt: hem row as % of waist -> crotch (0 = waist, 100 = crotch). Pants: hem row - ankle row (px).
  out_px    garment pixels on the background (outside the figure), torso band rows only.
Avatar landmark check: every span landmark vs the mask run at its row (deviation > 6 px is reported).
"""
import glob
import importlib.util
import json
import os
import traceback

import cv2
import numpy as np
from django.conf import settings

from apps.avatars.models import Avatar
from apps.garments.landmark_checks import validate_garment_landmarks
from apps.garments.models import Garment
from apps.tryon_engine import warp as new_warp

ENGINE = os.environ.get("ENGINE", "new")
OUT = f"/tmp/tryon_check/{ENGINE}"
os.makedirs(OUT, exist_ok=True)
H, W = settings.CANVAS_H, settings.CANVAS_W


def read_rgba(path):
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"cannot read {path}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2BGRA) if img.shape[2] == 3 else img


def runs(row):
    d = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def derive_pants_landmarks(img):
    a = img[:, :, 3] > 128
    ys = np.where(a.any(axis=1))[0]
    top, bot = int(ys[0]), int(ys[-1])
    h = bot - top

    def span(y):
        r = runs(a[y])
        return int(r[0][0]), int(r[-1][1] - 1)

    waist_y = top + int(0.03 * h)
    wl, wr = span(waist_y)
    crotch_y = next(y for y in range(top + int(0.1 * h), bot) if len(runs(a[y])) >= 2)
    hip_y = top + int(0.6 * (crotch_y - top))
    hl, hr = span(hip_y)

    def legs(y):
        r = runs(a[y])
        (l0, l1), (r0, r1) = r[0], r[-1]
        return {"left_x": int(l0), "right_x": int(l1 - 1), "y": y}, {"left_x": int(r0), "right_x": int(r1 - 1), "y": y}

    knee_y = crotch_y + int(0.45 * (bot - crotch_y))
    kl, kr = legs(knee_y)
    el, er = legs(bot - int(0.02 * h))
    cx = (wl + wr) // 2
    return {"waist": {"y": waist_y, "left_x": wl, "right_x": wr, "center_x": cx},
            "hip": {"y": hip_y, "left_x": hl, "right_x": hr}, "crotch": {"y": crotch_y, "center_x": cx},
            "knee": {"y": knee_y, "left_leg": kl, "right_leg": kr}, "hem": {"left_leg": el, "right_leg": er}}


def pants_from_file():
    from PIL import Image, ImageOps
    from rembg import remove
    paths = glob.glob("/tmp/tryon_check_in/pants.*")
    if not paths:
        return None
    src = ImageOps.exif_transpose(Image.open(paths[0])).convert("RGB")
    mask = remove(src, only_mask=True).convert("L")
    img = src.convert("RGBA")
    img.putalpha(mask)
    img = img.crop(mask.getbbox())
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGBA2BGRA)


def garment_sets():
    out = []
    t = Garment.objects.filter(type="tshirt").exclude(landmarks={}).order_by("ai_skipped", "-pk").first()
    if t:
        out.append(("tshirt", read_rgba(t.image.path), t.landmarks, f"garment {t.pk}"))
    img = pants_from_file()
    if img is not None:
        lm = derive_pants_landmarks(img)
        validate_garment_landmarks("pants", lm, img.shape[1], img.shape[0])
        cv2.imwrite("/tmp/tryon_check/pants_cut.png", img)
        json.dump(lm, open("/tmp/tryon_check/pants_landmarks.json", "w"))
        out.append(("pants", img, lm, "test-garments/pants_ok (derived landmarks)"))
    print("garments:", [(t, s) for t, _, _, s in out])
    return out


def old_render(base, lm, garments):
    spec = importlib.util.spec_from_file_location("warp_old", "/tmp/warp_old.py")
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    canvas = cv2.resize(base, (W, H)).copy()
    warns = []
    for gtype, gimg, glm in garments:  # old order: as given
        fn = old.warp_tshirt if gtype == "tshirt" else old.warp_pants
        warped, w = fn(lm, glm, gimg, H, W)
        warns += [f"{gtype}: {x}" for x in w]
        canvas = old._alpha_composite(canvas, warped)
    white = np.full((H, W, 3), 255, np.float32)
    a = canvas[:, :, 3:4].astype(np.float32) / 255.0
    return (canvas[:, :, :3] * a + white * (1 - a)).astype(np.uint8), warns


def flat(base):
    b = cv2.resize(base, (W, H))
    a = b[:, :, 3:4].astype(np.float32) / 255.0
    return (b[:, :, :3] * a + 255 * (1 - a)).astype(np.uint8)


def landmark_check(lm, mask):
    """Span landmarks vs the mask run at the same row (torso run containing the axis, legs per side)."""
    issues = []
    axis = new_warp._crotch_x(lm)
    for k in ("chest", "waist", "hip"):
        r = new_warp._runs(mask[int(round(lm[k]["y"]))])
        q = next((x for x in r if x[0] <= axis <= x[1]), None)
        if q:
            dl, dr = lm[k]["left_x"] - q[0], lm[k]["right_x"] - q[1]
            if max(abs(dl), abs(dr)) > 6:
                issues.append(f"{k} edges off by {dl:+.0f}/{dr:+.0f} px (row {lm[k]['y']:.0f})")
    for part in ("knee", "ankle"):
        for s in ("left_leg", "right_leg"):
            src = lm[part][s]
            y = lm["knee"]["y"] if part == "knee" else src["y"]
            r = new_warp._runs(mask[int(round(y))])
            if not r:
                continue
            c = (src["left_x"] + src["right_x"]) / 2
            q = min(r, key=lambda x: abs((x[0] + x[1]) / 2 - c))
            dl, dr = src["left_x"] - q[0], src["right_x"] - q[1]
            if max(abs(dl), abs(dr)) > 6:
                issues.append(f"{part} {s} edges off by {dl:+.0f}/{dr:+.0f} px")
    return issues


def measure(result, base_flat, mask, lm, arms, types):
    changed = np.abs(result.astype(int) - base_flat.astype(int)).max(axis=2) > 40
    m = {}
    sh_y = lm["shoulder"]["y"]
    sleeve, hand = [], 0
    for side in ("left", "right"):
        arm = arms.get(side)
        if not arm:
            continue
        rows = arm["rows"]
        mid = rows[0][0] + (arm["end_y"] - rows[0][0]) / 2
        if "tshirt" in types:
            reach = [y for y, l, r in rows if changed[y, l:r + 1].mean() > 0.3]
            sleeve.append(100 * ((max(reach) if reach else sh_y) - sh_y) / (arm["end_y"] - sh_y))
        hand += sum(int(changed[y, l:r + 1].sum()) for y, l, r in rows if y >= mid)
    if sleeve:
        m["sleeve%"] = "/".join(f"{v:.0f}" for v in sleeve)
    m["hand_px"] = hand
    cx = int(new_warp._crotch_x(lm))
    if types == ["tshirt"]:
        col = np.where(changed[:, cx - 20: cx + 20].any(axis=1))[0]
        if len(col):
            m["hem"] = f"{100 * (col.max() - lm['waist']['y']) / (lm['crotch']['y'] - lm['waist']['y']):.0f}% waist->crotch"
    if "pants" in types:
        hems = []
        for s in ("left_leg", "right_leg"):
            a = lm["ankle"][s]
            c = int((a["left_x"] + a["right_x"]) / 2)
            col = np.where(changed[:, c - 5: c + 5].any(axis=1))[0]
            hems.append(f"{col.max() - a['y']:+.0f}" if len(col) else "none")
        m["pants_hem_vs_ankle_px"] = "/".join(hems)
    band = np.zeros_like(mask)
    band[int(sh_y): int(lm["crotch"]["y"])] = True
    m["out_px"] = int((changed & ~mask & band).sum())
    return m


def run():
    sets = garment_sets()
    combos = [[s] for s in sets] + ([sets] if len(sets) == 2 else [])
    rows = []
    for av in Avatar.objects.order_by("pk"):
        base = read_rgba(av.image.path)
        lm = av.landmarks
        mask = new_warp.figure_mask(cv2.resize(base, (W, H)))
        arms = new_warp.find_arms(mask, lm)
        lm_issues = landmark_check(lm, mask)
        print(f"avatar {av.pk} {av.sex} {av.build}: arms found L={bool(arms['left'])} R={bool(arms['right'])}; "
              f"landmark check: {lm_issues or 'ok'}")
        for combo in combos:
            types = [t for t, _, _, _ in combo]
            name = f"avatar{av.pk}_{av.sex}_{av.build}_" + "+".join(types)
            try:
                garments = [(t, img, glm) for t, img, glm, _ in combo]
                if ENGINE == "old":
                    rgb, warns = old_render(base, lm, garments)
                else:
                    rgb, warns, _ = new_warp.render_tryon(base, lm, garments, H, W)
                cv2.imwrite(f"{OUT}/{name}.png", rgb)
                m = measure(rgb, flat(base), mask, lm, arms, types)
                rows.append({"combo": name, "warnings": warns, "landmarks": lm_issues, **m})
                print(f"OK   {name}: {m}\n     warnings: {warns or 'none'}")
            except Exception:
                print(f"FAIL {name}\n{traceback.format_exc()}")
                rows.append({"combo": name, "error": traceback.format_exc().splitlines()[-1]})
    json.dump(rows, open(f"{OUT}/report.json", "w"), indent=1)


run()
