"""Set real garment sizes from a JSON file (fit check calibration, docs/11 "Calibration").

    docker compose cp sizes.json backend:/tmp/sizes.json
    docker compose exec -T backend python manage.py set_garment_sizes --file /tmp/sizes.json [--dry-run]

File: {"<garment id>": {"chest_width": 52, "length": 70, "shoulder_width": 46, "stretch": false}, ...}.
`sizes` are validated with apps/garments/size_checks.py (the API rules) and fully replace the stored ones (same as
PATCH garments/{id}/sizes/); `stretch` is optional (omitted = unchanged). Any garment, incl. catalog / demo ones
(owner null). Any invalid entry -> nothing is written and every error is listed.
"""
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.garments.models import Garment
from apps.garments.size_checks import SizesInvalid, validate_sizes


class Command(BaseCommand):
    help = "Set Garment.sizes / stretch from a JSON file (all or nothing)."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="JSON {garment_id: {sizes..., stretch?}}")
        parser.add_argument("--dry-run", action="store_true", help="validate and print, write nothing")

    def handle(self, *args, file, dry_run=False, **options):
        try:
            with open(file, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            raise CommandError(f"cannot read {file}: {e}")
        if not isinstance(data, dict) or not data:
            raise CommandError("the file must be a non-empty JSON object {garment_id: {...}}")

        errors, plan = [], []
        for raw_id, entry in data.items():
            if not str(raw_id).isdigit():
                errors.append(f"{raw_id}: garment id must be an integer")
                continue
            garment = Garment.objects.filter(pk=int(raw_id)).first()
            if garment is None:
                errors.append(f"{raw_id}: garment not found")
                continue
            if not isinstance(entry, dict):
                errors.append(f"{raw_id}: entry must be an object")
                continue
            sizes = {k: v for k, v in entry.items() if k != "stretch"}
            stretch = entry.get("stretch", garment.stretch)
            if not isinstance(stretch, bool):
                errors.append(f"{raw_id}: stretch must be true or false")
                continue
            try:
                validate_sizes(garment.type, sizes)
            except SizesInvalid as e:
                errors.append(f"{raw_id} ({garment.type}): {e.detail}")
                continue
            plan.append((garment, sizes, stretch))

        if errors:
            raise CommandError("nothing written; invalid entries:\n  " + "\n  ".join(errors))

        with transaction.atomic():
            for garment, sizes, stretch in plan:
                owner = garment.owner.email if garment.owner_id else "catalog"
                self.stdout.write(f"garment {garment.pk} ({garment.type}, {owner}):")
                self.stdout.write(f"  before: sizes={garment.sizes} stretch={garment.stretch}")
                self.stdout.write(f"  after:  sizes={sizes} stretch={stretch}")
                if not dry_run:
                    garment.sizes, garment.stretch = sizes, stretch
                    garment.save(update_fields=["sizes", "stretch"])
        self.stdout.write(f"{len(plan)} garment(s) {'checked (dry run, nothing written)' if dry_run else 'updated'}.")
