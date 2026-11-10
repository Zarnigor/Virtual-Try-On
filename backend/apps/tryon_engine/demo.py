"""Demo mode: precomputed try-on results for a fixed list of (avatar, garments) pairs.

`manage.py build_demo --garments <folder>` renders every pair into media/demo/ and writes media/demo/manifest.json.
With DEMO_MODE=1, POST /api/tryon/ for a pair in the manifest returns a finished job at once (no Celery, no
Gemini); other pairs take the normal path. Without DEMO_MODE nothing changes.
"""
import json
from pathlib import Path

from django.conf import settings

DEMO_DIR = "demo"  # under MEDIA_ROOT


def manifest_path() -> Path:
    return Path(settings.MEDIA_ROOT) / DEMO_DIR / "manifest.json"


def pair_key(avatar_id: int, garment_ids) -> str:
    return f"{avatar_id}:{','.join(str(i) for i in sorted(int(g) for g in garment_ids))}"


def load_manifest() -> dict:
    try:
        return json.loads(manifest_path().read_text())
    except (OSError, ValueError):
        return {"garments": {}, "results": {}}


def lookup(avatar_id: int, garment_ids) -> str | None:
    """Media-relative path of the precomputed result, or None (also when the file is missing)."""
    rel = load_manifest().get("results", {}).get(pair_key(avatar_id, garment_ids))
    if rel and (Path(settings.MEDIA_ROOT) / rel).is_file():
        return rel
    return None
