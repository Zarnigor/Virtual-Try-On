"""Fill Avatar.measurements.shoulder_width (cm, a WIDTH) from the shoulder landmarks (docs/11, docs/09 #129).

Never overwrites a value already set. --dry-run prints what would be written.
"""
from django.core.management.base import BaseCommand

from apps.avatars.models import Avatar
from apps.sizing.body_sizes import shoulder_width_cm


class Command(BaseCommand):
    help = "Fill Avatar.measurements.shoulder_width from the shoulder landmarks (never overwrites)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="print only, write nothing")

    def handle(self, *args, dry_run=False, **options):
        for avatar in Avatar.objects.order_by("pk"):
            label = f"avatar {avatar.pk} ({avatar.sex} {avatar.build})"
            m = dict(avatar.measurements or {})
            if m.get("shoulder_width") is not None:
                self.stdout.write(f"{label}: kept {m['shoulder_width']} cm (already set)")
                continue
            value = shoulder_width_cm(avatar.landmarks, avatar.height_cm)
            if value is None:
                self.stdout.write(f"{label}: skipped (no shoulder / head_top / foot_bottom landmarks or height_cm)")
                continue
            if dry_run:
                self.stdout.write(f"{label}: would set {value} cm")
                continue
            m["shoulder_width"] = value
            avatar.measurements = m
            avatar.save(update_fields=["measurements"])
            self.stdout.write(f"{label}: set {value} cm")
