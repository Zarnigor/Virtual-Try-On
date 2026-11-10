"""Flags for render_tryon from settings. Realism effects (default 0): TRYON_SHADING, TRYON_CONTACT_SHADOW,
TRYON_EDGE_FEATHER. Structural steps (default 1): TRYON_SHOULDER_CAP, TRYON_HEM_SNAP, TRYON_HALO_REMOVAL,
TRYON_NECK_FIX."""
from django.conf import settings


def render_flags() -> dict:
    return {"shading": settings.TRYON_SHADING, "contact_shadows": settings.TRYON_CONTACT_SHADOW,
            "edge_feather": settings.TRYON_EDGE_FEATHER, "shoulder_cap": settings.TRYON_SHOULDER_CAP,
            "hem_snap": settings.TRYON_HEM_SNAP, "halo_removal": settings.TRYON_HALO_REMOVAL,
            "neck_fix": settings.TRYON_NECK_FIX}
