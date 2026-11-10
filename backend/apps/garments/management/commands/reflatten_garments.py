"""Flatten the photo lighting of garments cleaned before the flattening existed (docs/09 #69).

    manage.py reflatten_garments --ids 19 26 [--dry-run]
    manage.py reflatten_garments --all-solid [--dry-run]

Only near-solid garments are changed (apps/garments/lighting.py: printed or multi-colour garments are never
touched, also when named in --ids). Idempotent: a flattened garment gets `lighting_flattened = True` and is
skipped afterwards. --dry-run prints id, the measured values and whether it would change, and writes nothing.
The new PNG replaces the stored cleaned image (an admin maintenance step, not a user edit).
"""
import cv2
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from apps.garments import lighting
from apps.garments.models import Garment


class Command(BaseCommand):
    help = "Flatten the photo lighting of existing near-solid garments (once per garment)"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--ids", nargs="+", type=int)
        group.add_argument("--all-solid", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        qs = Garment.objects.exclude(image="").order_by("pk")
        if opts["ids"]:
            qs = qs.filter(pk__in=opts["ids"])
            missing = set(opts["ids"]) - set(qs.values_list("pk", flat=True))
            if missing:
                raise CommandError(f"garments not found or without image: {sorted(missing)}")
        changed = 0
        for g in qs:
            if g.lighting_flattened:
                self.stdout.write(f"{g.pk}: already flattened, skip")
                continue
            bgra = cv2.imread(g.image.path, cv2.IMREAD_UNCHANGED)
            if bgra is None or bgra.ndim != 3 or bgra.shape[2] != 4:
                self.stdout.write(f"{g.pk}: not an RGBA PNG, skip")
                continue
            rgba = cv2.cvtColor(bgra, cv2.COLOR_BGRA2RGBA)
            m = lighting.texture_measures(rgba) or {"hf_std": float("nan"), "hf_frac": float("nan")}
            solid = lighting.is_near_solid(rgba)
            verdict = "would flatten" if opts["dry_run"] else "flattened"
            self.stdout.write(f"{g.pk} {g.type}: hf_std {m['hf_std']:.1f}, hf_frac {m['hf_frac']:.3f} -> "
                              f"{verdict if solid else 'print/texture, unchanged'}")
            if not solid or opts["dry_run"]:
                continue
            out = cv2.cvtColor(lighting.flatten_lighting(rgba), cv2.COLOR_RGBA2BGRA)
            old = g.image.name
            g.image.save(f"flat_{g.pk}.png", ContentFile(cv2.imencode(".png", out)[1].tobytes()), save=False)
            g.lighting_flattened = True
            g.save(update_fields=["image", "lighting_flattened"])
            g.image.storage.delete(old)
            changed += 1
        if not opts["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"{changed} garment(s) flattened"))
