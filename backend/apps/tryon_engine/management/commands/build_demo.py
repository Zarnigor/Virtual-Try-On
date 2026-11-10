"""Build demo mode results: manage.py build_demo --garments <folder>

The folder holds one pair of files per garment:
    <name>.png   cleaned garment, tight-cropped transparent PNG (what the garment pipeline stores)
    <name>.json  {"type": "tshirt" | "pants", "name": "Shown name", "landmarks": {...}}
`manage.py export_demo_garments <folder> <garment ids>` writes such a folder from garments marked in the app.

Each garment becomes an approved public catalog garment (owner empty), updated in place on a rebuild.
Every avatar is rendered with every garment and with every T-shirt + pants pair into media/demo/,
and media/demo/manifest.json maps (avatar, garments) -> result. Renders use the same engine as the worker.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import cv2
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from apps.avatars.models import Avatar
from apps.garments.landmark_checks import LandmarksInvalid, validate_garment_landmarks
from apps.garments.models import Garment
from apps.tryon_engine.demo import DEMO_DIR, load_manifest, manifest_path, pair_key
from apps.tryon_engine.warp import render_tryon


class Command(BaseCommand):
    help = "Render demo try-on results for every avatar x demo garment into media/demo/"

    def add_arguments(self, parser):
        parser.add_argument("--garments", required=True, help="folder with <name>.png + <name>.json per garment")

    def handle(self, *args, **opts):
        folder = Path(opts["garments"])
        if not folder.is_dir():
            raise CommandError(f"folder not found: {folder}")
        specs = []
        for meta_path in sorted(folder.glob("*.json")):
            png = meta_path.with_suffix(".png")
            if not png.is_file():
                raise CommandError(f"{meta_path.name}: {png.name} is missing")
            meta = json.loads(meta_path.read_text())
            if meta.get("type") not in ("tshirt", "pants"):
                raise CommandError(f"{meta_path.name}: type must be tshirt or pants")
            img = cv2.imread(str(png), cv2.IMREAD_UNCHANGED)
            if img is None or img.ndim != 3 or img.shape[2] != 4:
                raise CommandError(f"{png.name}: must be a transparent (RGBA) PNG")
            try:
                validate_garment_landmarks(meta["type"], meta.get("landmarks"), img.shape[1], img.shape[0])
            except LandmarksInvalid as e:
                raise CommandError(f"{meta_path.name}: {e.detail}")
            specs.append((meta_path.stem, meta, png, img))
        if not specs:
            raise CommandError("no <name>.json garments in the folder")
        avatars = list(Avatar.objects.exclude(image="").order_by("pk"))
        if not avatars:
            raise CommandError("no avatars: run seed_avatars first")

        old = load_manifest()
        out_dir = Path(settings.MEDIA_ROOT) / DEMO_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        for f in out_dir.glob("*.png"):
            f.unlink()  # results of a previous build

        garments = {}
        for stem, meta, png, img in specs:
            g = Garment.objects.filter(pk=old.get("garments", {}).get(stem), owner__isnull=True).first()
            if g is None:
                g = Garment(owner=None, type=meta["type"])
            elif g.image:
                g.image.storage.delete(g.image.name)
            g.type, g.name = meta["type"], meta.get("name", stem)[:100]
            g.landmarks, g.visibility, g.status = meta["landmarks"], "public", "approved"
            g.image.save(f"demo_{stem}.png", ContentFile(png.read_bytes()), save=False)
            g.save()
            garments[stem] = (g, img)
            self.stdout.write(f"garment {stem} -> catalog garment {g.pk} ({g.type})")

        combos = [[s] for s in garments]
        tshirts = [s for s in garments if garments[s][0].type == "tshirt"]
        pants = [s for s in garments if garments[s][0].type == "pants"]
        combos += [[t, p] for t in tshirts for p in pants]

        results = {}
        for av in avatars:
            base = cv2.imread(av.image.path, cv2.IMREAD_UNCHANGED)
            for combo in combos:
                ids = [garments[s][0].pk for s in combo]
                items = [(garments[s][0].type, garments[s][1], garments[s][0].landmarks) for s in combo]
                rgb, warns, _ = render_tryon(base, av.landmarks, items, settings.CANVAS_H, settings.CANVAS_W)
                rel = f"{DEMO_DIR}/avatar{av.pk}_{'_'.join(str(i) for i in sorted(ids))}.png"
                cv2.imwrite(str(Path(settings.MEDIA_ROOT) / rel), rgb)
                results[pair_key(av.pk, ids)] = rel
                if warns:
                    self.stdout.write(f"  {av.sex} {av.build} + {'+'.join(combo)}: {'; '.join(warns)}")

        manifest = {"built_at": datetime.now(timezone.utc).isoformat(),
                    "garments": {s: g.pk for s, (g, _) in garments.items()}, "results": results}
        manifest_path().write_text(json.dumps(manifest, indent=1))
        self.stdout.write(self.style.SUCCESS(
            f"{len(results)} demo results for {len(avatars)} avatars x {len(combos)} garment sets in media/{DEMO_DIR}/"))
