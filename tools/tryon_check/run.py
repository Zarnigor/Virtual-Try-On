"""Try-on check without a browser: warp existing garments onto every seeded avatar.

Runs inside the backend container (reads the DB and media, writes nothing to the DB):
    docker compose exec -T backend python manage.py shell < tools/tryon_check/run.py
    docker compose cp backend:/tmp/tryon_check/. tools/tryon_check/out/

Composition is the same as apps/tryon_engine/tasks.py `_do_warp` (base -> warp -> alpha composite -> white).

Pants: if /tmp/tryon_check_in/pants.* exists (copy test-garments/pants_ok.jpg.webp there first), it is cut out
in memory with rembg (mask only, same as jobs.tasks._rembg_clean) and used instead of a DB garment; its landmarks
are derived from the alpha mask (never saved) and checked with the server's validate_garment_landmarks.
    docker compose cp test-garments/pants_ok.jpg.webp backend:/tmp/tryon_check_in/pants.webp

Diagnostics per image:
  - sleeve_end_y: where the sleeve tip lands (hand_y in warp.py) vs armpit / crotch
  - hand_cover_px: avatar arm pixels (outside the torso and legs) in the forearm/hand zone, i.e. below the
    sleeve end, that the garment covers. Should be 0: hands and forearms must stay above the garment.
"""
import glob
import os
import traceback

import cv2
import numpy as np
from django.conf import settings

from apps.avatars.models import Avatar
from apps.garments.landmark_checks import validate_garment_landmarks
from apps.garments.models import Garment
from apps.tryon_engine.warp import _alpha_composite, warp_pants, warp_tshirt

OUT = "/tmp/tryon_check"
os.makedirs(OUT, exist_ok=True)
H, W = settings.CANVAS_H, settings.CANVAS_W


def read_rgba(path):
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"cannot read {path}")
    if img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    return img


def runs(row):
    """[(start, end_exclusive)] of opaque runs in a boolean row."""
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
        if len(r) < 2:
            raise ValueError(f"legs not separated at y={y}")
        (l0, l1), (r0, r1) = r[0], r[-1]
        return {"left_x": int(l0), "right_x": int(l1 - 1), "y": y}, {"left_x": int(r0), "right_x": int(r1 - 1), "y": y}

    knee_y = crotch_y + int(0.45 * (bot - crotch_y))
    hem_y = bot - int(0.02 * h)
    kl, kr = legs(knee_y)
    el, er = legs(hem_y)
    cx = (wl + wr) // 2
    return {
        "waist": {"y": waist_y, "left_x": wl, "right_x": wr, "center_x": cx},
        "hip": {"y": hip_y, "left_x": hl, "right_x": hr},
        "crotch": {"y": crotch_y, "center_x": cx},
        "knee": {"y": knee_y, "left_leg": kl, "right_leg": kr},
        "hem": {"left_leg": el, "right_leg": er},
    }


def torso_band(lm):
    """Boolean HxW mask of the torso between shoulder and crotch (linear between landmark rows)."""
    rows = [(lm["shoulder"]["y"], lm["shoulder"]["left_x"], lm["shoulder"]["right_x"])]
    for k in ("chest", "waist", "hip"):
        rows.append((lm[k]["y"], lm[k]["left_x"], lm[k]["right_x"]))
    rows.append((lm["crotch"]["y"], lm["hip"]["left_x"], lm["hip"]["right_x"]))
    m = np.zeros((H, W), bool)
    for (y0, l0, r0), (y1, l1, r1) in zip(rows, rows[1:]):
        for y in range(int(y0), int(y1) + 1):
            t = (y - y0) / max(y1 - y0, 1)
            m[y, int(l0 + t * (l1 - l0)):int(r0 + t * (r1 - r0)) + 1] = True
    return m


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
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGBA2BGRA), paths[0]


def garment_sets():
    tshirt = Garment.objects.filter(type="tshirt").exclude(landmarks={}).order_by("ai_skipped", "-pk").first()
    pants = Garment.objects.filter(type="pants").exclude(image="").order_by("-pk").first()
    out = []
    if tshirt:
        out.append(("tshirt", tshirt.image.path, tshirt.landmarks))
    from_file = pants_from_file()
    if from_file:
        img, path = from_file
        lm = derive_pants_landmarks(img)
        validate_garment_landmarks("pants", lm, img.shape[1], img.shape[0])
        cv2.imwrite("/tmp/tryon_check/_pants_cut.png", img)
        print(f"pants from {path}: landmarks derived from alpha (not saved): {lm}")
        out.append(("pants", "/tmp/tryon_check/_pants_cut.png", lm))
    elif pants:
        img = read_rgba(pants.image.path)
        lm = pants.landmarks or derive_pants_landmarks(img)
        validate_garment_landmarks("pants", lm, img.shape[1], img.shape[0])
        src = "saved" if pants.landmarks else "derived from alpha (not saved)"
        print(f"pants garment {pants.pk}: landmarks {src}: {lm}")
        out.append(("pants", pants.image.path, lm))
    print("garments:", [(t, p) for t, p, _ in out])
    return out


def run():
    sets = garment_sets()
    combos = [[s] for s in sets] + ([sets] if len(sets) == 2 else [])
    for av in Avatar.objects.order_by("pk"):
        base = cv2.resize(read_rgba(av.image.path), (W, H))
        lm = av.landmarks
        # arm pixels: opaque, outside the torso band; below the crotch also outside the hip span (legs excluded)
        figure = (base[:, :, 3] > 128) & (base[:, :, :3] < 240).any(axis=2)  # seeded avatars are opaque RGB on white
        arms = figure & ~torso_band(lm)
        legs = np.zeros((H, W), bool)
        cy = int(lm["crotch"]["y"])
        legs[cy:, int(lm["hip"]["left_x"]):int(lm["hip"]["right_x"]) + 1] = True
        arms &= ~legs
        arms[: int(lm["armpit"]["y"])] = False
        hand_y = lm["armpit"]["y"] + (lm["crotch"]["y"] - lm["chest"]["y"]) * 0.5  # sleeve end in warp.py
        forearm_hand = arms.copy()
        forearm_hand[: int(hand_y) + 1] = False
        for combo in combos:
            name = f"avatar{av.pk}_{av.sex}_{av.build}_" + "+".join(t for t, _, _ in combo)
            arm_total = int(forearm_hand.sum())
            try:
                canvas = base.copy()
                report = []
                for gtype, gpath, glm in combo:
                    gimg = read_rgba(gpath)
                    fn = warp_tshirt if gtype == "tshirt" else warp_pants
                    warped, warns = fn(lm, glm, gimg, H, W)
                    cover = int(((warped[:, :, 3] > 128) & forearm_hand).sum())
                    extra = ""
                    if gtype == "tshirt":
                        extra = f" sleeve_end_y={hand_y:.0f} (armpit {lm['armpit']['y']:.0f}, crotch {lm['crotch']['y']:.0f})"
                    report.append(f"{gtype}: warnings={warns or 'none'} hand_cover_px={cover}{extra}")
                    canvas = _alpha_composite(canvas, warped)
                white = np.full((H, W, 3), 255, np.float32)
                alpha = canvas[:, :, 3:4].astype(np.float32) / 255.0
                rgb = (canvas[:, :, :3] * alpha + white * (1 - alpha)).astype(np.uint8)
                cv2.imwrite(f"{OUT}/{name}.png", rgb)
                print(f"OK   {name} (forearm/hand px on avatar: {arm_total})\n     " + "\n     ".join(report))
            except Exception:
                print(f"FAIL {name}\n{traceback.format_exc()}")


run()
