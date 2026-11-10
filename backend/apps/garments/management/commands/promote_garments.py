"""List garments, or promote some to the public catalog.

    manage.py promote_garments --list
    manage.py promote_garments --ids 28 33 --catalog

--catalog: visibility=public, status=approved (staff action, counts as moderation) so every user sees them in
`GET garments/?scope=catalog`. The owner stays the same (the garment is still theirs to delete). Only garments
with a cleaned image and saved landmarks can be promoted (the try-on engine needs both).
"""
from django.core.management.base import BaseCommand, CommandError

from apps.garments.models import Garment


class Command(BaseCommand):
    help = "List garments or promote them to the approved public catalog"

    def add_arguments(self, parser):
        parser.add_argument("--list", action="store_true", help="print every garment")
        parser.add_argument("--ids", type=int, nargs="+", help="garment ids")
        parser.add_argument("--catalog", action="store_true", help="make the --ids public + approved")

    def handle(self, *args, **o):
        if o["list"]:
            return self._list()
        if not o["ids"] or not o["catalog"]:
            raise CommandError("use --list, or --ids ... --catalog")
        garments = {g.pk: g for g in Garment.objects.filter(pk__in=o["ids"])}
        missing = [i for i in o["ids"] if i not in garments]
        not_ready = [i for i, g in garments.items() if not g.image or not g.landmarks]
        if missing or not_ready:
            raise CommandError(
                "; ".join(([f"not found: {missing}"] if missing else [])
                          + ([f"no cleaned image or landmarks: {sorted(not_ready)}"] if not_ready else []))
            )
        for g in garments.values():
            g.visibility, g.status = "public", "approved"
            g.save(update_fields=["visibility", "status"])
            self.stdout.write(f"garment {g.pk} ({g.type}) -> catalog")
        self.stdout.write(self.style.SUCCESS(f"{len(garments)} garment(s) promoted"))

    def _list(self):
        for g in Garment.objects.select_related("owner").order_by("pk"):
            owner = g.owner.email if g.owner else "catalog"
            marked = "landmarks" if g.landmarks else "no landmarks"
            self.stdout.write(f"{g.pk:>5}  {g.type:<6}  {g.visibility:<7}  {g.status:<8}  {marked:<12}  {owner}  {g.name}")
