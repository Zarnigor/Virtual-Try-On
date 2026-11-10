"""Realism flags for render_tryon from settings (env TRYON_SHADING, TRYON_CONTACT_SHADOW, TRYON_EDGE_FEATHER)."""
from django.conf import settings


def render_flags() -> dict:
    return {"shading": settings.TRYON_SHADING, "contact_shadows": settings.TRYON_CONTACT_SHADOW,
            "edge_feather": settings.TRYON_EDGE_FEATHER}
