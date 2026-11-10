"""Write garments marked in the app into a build_demo folder: manage.py export_demo_garments /demo_garments 13 21

For each id: <folder>/<type>_<id>.png (the cleaned PNG) and <type>_<id>.json ({type, name, landmarks}).
Only garments with saved landmarks; the landmarks are checked like the landmark editor's save.
"""
import json
from pathlib import Path

import cv2
from django.core.management.base import BaseCommand, CommandError

from apps.garments.landmark_checks import LandmarksInvalid, validate_garment_landmarks
from apps.garments.models import Garment


class Command(BaseCommand):
    help = "Export garments (cleaned PNG + landmarks) into a folder for build_demo"

    def add_arguments(self, parser):
        parser.add_argument("folder")
        parser.add_argument("ids", nargs="+", type=int)

    def handle(self, *args, **opts):
        out = Path(opts["folder"])
        out.mkdir(parents=True, exist_ok=True)
        for gid in opts["ids"]:
            g = Garment.objects.filter(pk=gid).first()
            if g is None or not g.image:
                raise CommandError(f"garment {gid}: not found or not cleaned")
            img = cv2.imread(g.image.path, cv2.IMREAD_UNCHANGED)
            try:
                validate_garment_landmarks(g.type, g.landmarks, img.shape[1], img.shape[0])
            except LandmarksInvalid as e:
                raise CommandError(f"garment {gid}: {e.detail}")
            stem = f"{g.type}_{g.pk}"
            (out / f"{stem}.png").write_bytes(Path(g.image.path).read_bytes())
            meta = {"type": g.type, "name": g.name or stem, "landmarks": g.landmarks}
            (out / f"{stem}.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
            self.stdout.write(f"garment {gid} -> {out / stem}.png/.json")
