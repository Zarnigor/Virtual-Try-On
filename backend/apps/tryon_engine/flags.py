"""Flags for render_tryon from settings. Realism effects (default 0): TRYON_SHADING, TRYON_CONTACT_SHADOW,
TRYON_EDGE_FEATHER. Structural steps (default 1): TRYON_SHOULDER_CAP, TRYON_HEM_SNAP, TRYON_HALO_REMOVAL,
TRYON_NECK_FIX, TRYON_NECK_GAP_FILL. TRYON_DROPPED_SHOULDER_SINGLE (default 0, docs/09 #90).
T-shirt hem rule: TRYON_HEM_RULE (default 1), TRYON_HEM_HIP_FRACTION, TRYON_HEM_CROTCH_MARGIN (docs/09 #91).
TRYON_WARP: "parts" (default) | "mls" for the T-shirt (docs/09 #98). TRYON_NECK_HOLE (default 1, MLS only, docs/09 #102)."""
from django.conf import settings


def render_flags(source: str = "body") -> dict:
    """source: "avatar" or "body" (own photo). Passed through to render_tryon, which never runs the neck-gap fill
    for an own body."""
    if source not in ("avatar", "body"):
        raise ValueError(f"unknown body source: {source!r}")
    return {"source": source, "shading": settings.TRYON_SHADING, "contact_shadows": settings.TRYON_CONTACT_SHADOW,
            "edge_feather": settings.TRYON_EDGE_FEATHER, "shoulder_cap": settings.TRYON_SHOULDER_CAP,
            "hem_snap": settings.TRYON_HEM_SNAP, "halo_removal": settings.TRYON_HALO_REMOVAL,
            "neck_fix": settings.TRYON_NECK_FIX, "neck_gap_fill": settings.TRYON_NECK_GAP_FILL,
            "dropped_shoulder_single": settings.TRYON_DROPPED_SHOULDER_SINGLE,
            "hem_rule": settings.TRYON_HEM_RULE, "hem_hip_fraction": settings.TRYON_HEM_HIP_FRACTION,
            "hem_crotch_margin": settings.TRYON_HEM_CROTCH_MARGIN, "warp_engine": settings.TRYON_WARP,
            "neck_hole": settings.TRYON_NECK_HOLE}
