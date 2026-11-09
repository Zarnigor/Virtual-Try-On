"""
Seed 6 avatars (3 male + 3 female, slim/average/plus) from the reference JSON.
Generates synthetic avatar images using the same approach as the warp experiment.
"""
import json
import numpy as np
import cv2
from pathlib import Path
from io import BytesIO
from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from apps.avatars.models import Avatar

SEED_JSON = Path(__file__).resolve().parents[4] / "seed" / "avatars.reference.json"
CANVAS_W, CANVAS_H = 600, 1200

COLOURS = {
    "male_slim":    (90, 120, 160),
    "male_average": (70, 100, 140),
    "male_plus":    (60,  85, 125),
    "female_slim":    (160, 100, 120),
    "female_average": (140,  85, 105),
    "female_plus":    (120,  70,  90),
}

MEASUREMENTS = {
    "male_slim":     {"shoulder": 108, "chest": 90,  "waist": 76,  "hip": 90},
    "male_average":  {"shoulder": 116, "chest": 98,  "waist": 86,  "hip": 98},
    "male_plus":     {"shoulder": 126, "chest": 112, "waist": 102, "hip": 112},
    "female_slim":   {"shoulder": 96,  "chest": 82,  "waist": 64,  "hip": 90},
    "female_average":{"shoulder": 104, "chest": 90,  "waist": 72,  "hip": 98},
    "female_plus":   {"shoulder": 114, "chest": 104, "waist": 90,  "hip": 112},
}


def render_avatar(lm: dict, col: tuple) -> bytes:
    img = np.full((CANVAS_H, CANVAS_W, 3), 255, dtype=np.uint8)
    pts = _body_polygon(lm)
    cv2.fillPoly(img, [pts], col)
    head_top_y = int(lm["head_top"]["y"])
    neck_y = int(lm["neck"]["y"])
    head_r = int((neck_y - head_top_y) * 0.55)
    cv2.circle(img, (CANVAS_W // 2, head_top_y + head_r + 4), head_r, col, -1)
    _, buf = cv2.imencode(".png", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    return buf.tobytes()


def _body_polygon(lm):
    shoulder = lm["shoulder"]
    chest = lm["chest"]
    waist = lm["waist"]
    hip = lm["hip"]
    crotch_y = int(lm["crotch"]["y"])
    knee = lm["knee"]
    ankle_l = lm["ankle"]["left_leg"]
    ankle_r = lm["ankle"]["right_leg"]
    foot_y = int(lm["foot_bottom"]["y"])
    hand_y = int(lm.get("qa", {}).get("hand_end_y", hip["y"] + 20))

    left = [
        (CANVAS_W // 2, int(lm["neck"]["y"])),
        (int(shoulder["left_x"]), int(shoulder["y"])),
        (int(shoulder["left_x"]) - 18, int(chest["y"])),
        (int(shoulder["left_x"]) - 18, hand_y),
        (int(shoulder["left_x"]) - 8, hand_y + 10),
        (int(chest["left_x"]), int(chest["y"])),
        (int(waist["left_x"]), int(waist["y"])),
        (int(hip["left_x"]), int(hip["y"])),
        (int(hip["left_x"]) - 5, crotch_y),
        (int(knee["left_leg"]["left_x"]), int(knee["y"])),
        (int(ankle_l["left_x"]), int(ankle_l["y"])),
        (int(ankle_l["left_x"]), foot_y),
    ]
    right = [
        (int(ankle_r["right_x"]), foot_y),
        (int(ankle_r["right_x"]), int(ankle_r["y"])),
        (int(knee["right_leg"]["right_x"]), int(knee["y"])),
        (int(hip["right_x"]) + 5, crotch_y),
        (int(hip["right_x"]), int(hip["y"])),
        (int(waist["right_x"]), int(waist["y"])),
        (int(chest["right_x"]), int(chest["y"])),
        (int(shoulder["right_x"]) + 8, hand_y + 10),
        (int(shoulder["right_x"]) + 18, hand_y),
        (int(shoulder["right_x"]) + 18, int(chest["y"])),
        (int(shoulder["right_x"]), int(shoulder["y"])),
        (CANVAS_W // 2, int(lm["neck"]["y"])),
    ]
    return np.array(left + right, dtype=np.int32)


class Command(BaseCommand):
    help = "Seed 6 avatars from reference JSON"

    def handle(self, *args, **options):
        data = json.loads(SEED_JSON.read_text())["avatars"]
        for key, av_data in data.items():
            sex, build = key.split("_", 1)
            lm = {**av_data["landmarks"], "qa": av_data.get("qa", {})}
            col = COLOURS.get(key, (100, 130, 160))
            img_bytes = render_avatar(lm, col)

            avatar, created = Avatar.objects.get_or_create(sex=sex, build=build)
            avatar.landmarks = av_data["landmarks"]
            avatar.measurements = MEASUREMENTS.get(key, {})
            avatar.image.save(f"avatar_{key}.png", ContentFile(img_bytes), save=False)
            avatar.save()
            self.stdout.write(f"{'Created' if created else 'Updated'}: {key}")

        self.stdout.write(self.style.SUCCESS("6 avatar muvaffaqiyatli yuklandi."))
