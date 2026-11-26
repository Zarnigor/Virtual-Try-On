"""
Seed the 6 avatars (male/female x slim/average/plus).

    manage.py seed_avatars --from /avatars    real photos (docker-compose mounts ./avatars there); any subset of the 6
    manage.py seed_avatars                    drawn placeholders from seed/avatars.reference.json

--from: each photo goes through the shared body pipeline apps/bodies/pipeline.py (EXIF strip, rembg mask, uniform
scale, pad to 600x1200 RGBA, figure top y=50, axis x=300, fails loudly instead of clipping) and gets INITIAL
landmarks from its own mask (no shared defaults: poses differ). A reseeded avatar loses its confirmed landmarks
(landmarks_confirmed_at = null). The staff landmark editor (/staff/avatars/:id) is the source of truth.
File names map to sex/build by tokens, e.g. man_slim.jpg, woman_plus_size.jpg, female_average.png.
"""
import json
import re
import numpy as np
import cv2
from pathlib import Path
from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from apps.avatars.models import Avatar
from apps.sizing.body_sizes import with_shoulder_width

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


NOMINAL_HEIGHT = {"male": 178.0, "female": 165.0}  # cm, staff edit them in the editor

SEX_ALIASES = {"male": "male", "man": "male", "men": "male", "female": "female", "woman": "female", "women": "female"}
BUILD_ALIASES = {"slim": "slim", "average": "average", "plus": "plus"}  # "plus_size" -> tokens plus, size
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def map_name(stem: str):
    """('male', 'slim') from a file stem, or None if it is not exactly one sex and one build."""
    tokens = [t for t in re.split(r"[^a-z]+", stem.lower()) if t]
    sexes = {SEX_ALIASES[t] for t in tokens if t in SEX_ALIASES}
    builds = {BUILD_ALIASES[t] for t in tokens if t in BUILD_ALIASES}
    if len(sexes) != 1 or len(builds) != 1:
        return None
    return sexes.pop(), builds.pop()


def _replace_image(avatar, name, data):
    if avatar.image and avatar.image.name:
        avatar.image.storage.delete(avatar.image.name)  # no orphaned file
    avatar.image.save(name, ContentFile(data), save=False)


class Command(BaseCommand):
    help = "Seed the 6 avatars from real photos (--from DIR) or as drawn placeholders"

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="src", help="folder with the 6 avatar photos (always updates)")
        parser.add_argument("--force", action="store_true",
                            help="placeholder mode: overwrite existing avatars too (default: only create missing)")

    def handle(self, *args, **options):
        if options["src"]:
            return self._from_photos(Path(options["src"]))
        self._placeholders(force=options["force"])

    def _from_photos(self, folder: Path):
        from rembg import new_session
        from django.core.management.base import CommandError
        from apps.avatars.staff_upload import save_processed
        from apps.bodies.pipeline import BodyPhotoRejected, process_body_photo

        if not folder.is_dir():
            raise CommandError(f"folder not found: {folder}")
        files = sorted(f for f in folder.iterdir() if f.suffix.lower() in PHOTO_EXT)
        mapping, errors = {}, []
        for f in files:
            key = map_name(f.stem)
            if key is None:
                errors.append(f"{f.name}: cannot tell sex and build from the name")
            elif key in mapping:
                errors.append(f"{f.name}: duplicate of {mapping[key].name} ({key[0]} {key[1]})")
            else:
                mapping[key] = f
        if errors:
            raise CommandError("; ".join(errors))
        if not mapping:
            raise CommandError(f"no avatar photos in {folder} (names like female_slim.jpg)")
        missing = [f"{s} {b}" for s in ("male", "female") for b in ("slim", "average", "plus") if (s, b) not in mapping]

        session = new_session("u2net_human_seg")
        for (sex, build), f in sorted(mapping.items()):
            try:
                processed = process_body_photo(f.read_bytes(), session=session)
            except BodyPhotoRejected as e:
                raise CommandError(f"{f.name}: {e.code} ({e.internal})")
            avatar, created = Avatar.objects.get_or_create(sex=sex, build=build)
            save_processed(avatar, processed, f"avatar_{sex}_{build}.png")
            avatar.measurements = avatar.measurements or MEASUREMENTS[f"{sex}_{build}"]  # nominal, staff edits them
            avatar.height_cm = avatar.height_cm or NOMINAL_HEIGHT[sex]
            # new landmarks -> new shoulder_width for the fit check (docs/09 #129)
            avatar.measurements = with_shoulder_width(avatar.measurements, avatar.landmarks, avatar.height_cm)
            avatar.save()
            self.stdout.write(
                f"{f.name} -> {sex} {build} (avatar {avatar.pk}, {'created' if created else 'updated'}): "
                f"scale {processed.scale:.3f}"
                + (f"; landmark warnings: {'; '.join(processed.warnings)}" if processed.warnings else "")
            )
        self.stdout.write(self.style.SUCCESS(
            f"{len(mapping)} avatar(s) seeded from photos. Check the landmarks in the editor (/staff/avatars)."
            + (f" Not in the folder (unchanged): {', '.join(missing)}." if missing else "")
        ))

    def _placeholders(self, force=False):
        """Drawn placeholders. Runs on every backend start (entrypoint.sh), so by default it only CREATES
        missing avatars: it must never overwrite avatars seeded from real photos."""
        data = json.loads(SEED_JSON.read_text())["avatars"]
        for key, av_data in data.items():
            sex, build = key.split("_", 1)
            existing = Avatar.objects.filter(sex=sex, build=build).exclude(image="").exclude(image__isnull=True).first()
            if existing and not force:
                self.stdout.write(f"Kept: {key} (already seeded; --force overwrites)")
                continue
            lm = {**av_data["landmarks"], "qa": av_data.get("qa", {})}
            col = COLOURS.get(key, (100, 130, 160))
            img_bytes = render_avatar(lm, col)

            avatar, created = Avatar.objects.get_or_create(sex=sex, build=build)
            avatar.landmarks = av_data["landmarks"]
            avatar.measurements = with_shoulder_width(MEASUREMENTS.get(key, {}), avatar.landmarks, avatar.height_cm)
            _replace_image(avatar, f"avatar_{key}.png", img_bytes)
            avatar.save()
            self.stdout.write(f"{'Created' if created else 'Updated'}: {key}")

        self.stdout.write(self.style.SUCCESS("Placeholder avatars checked."))
