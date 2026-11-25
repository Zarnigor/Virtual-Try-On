"""Fit check calibration matrix (read-only, docs/11 "Calibration"). Logic: backend/apps/tryon_engine/fit_report.py.

Run with tools/fit_check/run.sh (copies files in and out of the backend container), or directly:
    docker compose exec -T backend python - [--cases /tmp/fit_cases.json] [--out /tmp/fit_check] \
        < tools/fit_check/matrix.py
Writes <out>/fit_matrix.md and <out>/fit_matrix.json; prints skipped garments / avatars and failing cases.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, "/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tryon_studio.settings.local")
import django  # noqa: E402

django.setup()

from apps.avatars.models import Avatar  # noqa: E402
from apps.garments.models import Garment  # noqa: E402
from apps.tryon_engine import fit_report  # noqa: E402

parser = argparse.ArgumentParser(prog="fit_check/matrix.py")
parser.add_argument("--cases", help="JSON [{garment, model_height_cm, worn_size, expected}]")
parser.add_argument("--out", default="/tmp/fit_check")
args = parser.parse_args(sys.argv[1:])

garments = list(Garment.objects.order_by("pk"))
report = fit_report.build_matrix(garments, Avatar.objects.order_by("pk"))
cases = None
if args.cases:
    with open(args.cases, encoding="utf-8") as f:
        cases = fit_report.check_cases(json.load(f), {g.pk: g for g in garments})
    report["cases"] = cases

os.makedirs(args.out, exist_ok=True)
with open(os.path.join(args.out, "fit_matrix.md"), "w", encoding="utf-8") as f:
    f.write(fit_report.render_md(report, cases))
with open(os.path.join(args.out, "fit_matrix.json"), "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print(f"{len(report['garments'])} garment(s) x {len(report['avatars'])} avatar(s), {len(report['cells'])} cell(s)")
for s in report["skipped_garments"]:
    print(f"skipped garment #{s['garment_id']}: {s['reason']}")
for s in report["skipped_avatars"]:
    print(f"skipped avatar #{s['avatar_id']}: {s['reason']}")
for c in cases or []:
    if c.get("error"):
        print(f"case {c['case']}: ERROR {c['error']}")
    elif c["failed"]:
        print(f"case {c['case']} (garment #{c['garment_id']}, {c['model_height_cm']} cm, {c['worn_size']}): "
              f"expected fits, fails on {', '.join(c['failed_zones'])}")
print(f"written: {args.out}/fit_matrix.md, {args.out}/fit_matrix.json")
