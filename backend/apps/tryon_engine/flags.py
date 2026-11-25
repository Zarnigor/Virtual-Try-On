"""Flags for render_tryon from settings. Realism effects (default 0): TRYON_SHADING, TRYON_CONTACT_SHADOW,
TRYON_EDGE_FEATHER. Structural steps (default 1): TRYON_SHOULDER_CAP, TRYON_HEM_SNAP, TRYON_HALO_REMOVAL,
TRYON_NECK_FIX, TRYON_NECK_GAP_FILL. TRYON_DROPPED_SHOULDER_SINGLE (default 0, docs/09 #90).
T-shirt hem rule: TRYON_HEM_RULE (default 1), TRYON_HEM_HIP_FRACTION, TRYON_HEM_CROTCH_MARGIN (docs/09 #91).
TRYON_WARP: "mls" (default, docs/09 #105) | "parts" for the T-shirt (docs/09 #98). TRYON_NECK_HOLE (default 1, MLS
only, docs/09 #102). TRYON_MLS_SLEEVE: MLS sleeve variant, default "C" (docs/09 #104). Adapt T-shirts on MLS (docs/09
#105): TRYON_MLS_TUBE (default 1), TRYON_MLS_SIDE_FLOOR (mask | off), TRYON_MLS_ARMPIT (r14 | off), TRYON_MLS_HEM
(garment | mls); each off value = the behaviour before #105. Tube sleeves (docs/09 #106): TRYON_MLS_CUFF (hem | chord),
TRYON_MLS_FRINGE (drop | keep); each second value = the behaviour before #106.
TRYON_FINISH (docs/09 #107): "r17" (default) = the round 17 finish on the T-shirt layer (smooth edge + form shading +
contact shadow; the three realism flags are then not read) | "off" = the three realism flags as before.
TRYON_FINISH_PANTS (docs/09 #108, default 1): with TRYON_FINISH=r17 the pants layer gets the finish too | 0 = T-shirts
only, the behaviour before #108. Without TRYON_FINISH=r17 it does nothing.
TRYON_PANTS_TUCK (docs/09 #109, default 1): an adapt MLS T-shirt worn with pants hangs over them | 0 = before #109.
TRYON_MLS_KEEP_SCALE (docs/09 #112, default fit): keep_shape MLS T-shirts are scaled to fit the body | shoulder = before.
TRYON_MLS_TUBE_CLIP (docs/09 #113, default arm): tube sleeves end on the arm/torso boundary | armhole = before.
TRYON_PANTS_ENGINE (docs/09 #114, #116, default rows): rows = warp_pants (round 26 fit model, docs/09 #120) |
fit = warp_pants_fit (rounds 21-22).
TRYON_DRAPE_BODY_MARGIN (docs/09 #119, default 6 px | off = before): the drape over pants stops at the figure edge.
TRYON_PANTS_LEG (docs/09 #122, default smooth | r26 = before): rows pants legs without the knee bend."""
from django.conf import settings


def render_flags(source: str = "body") -> dict:
    """source: "avatar" or "body" (own photo). Passed through to render_tryon, which never runs the neck-gap fill
    for an own body."""
    if source not in ("avatar", "body"):
        raise ValueError(f"unknown body source: {source!r}")
    r17 = settings.TRYON_FINISH == "r17"
    return {"source": source, "finish": "r17" if r17 else "r60",
            "finish_pants": r17 and settings.TRYON_FINISH_PANTS, "pants_tuck": settings.TRYON_PANTS_TUCK, "mls_keep_scale": settings.TRYON_MLS_KEEP_SCALE, "mls_tube_clip": settings.TRYON_MLS_TUBE_CLIP, "pants_engine": settings.TRYON_PANTS_ENGINE,
            "drape_body_margin": settings.TRYON_DRAPE_BODY_MARGIN, "pants_leg": settings.TRYON_PANTS_LEG,
            "shading": r17 or settings.TRYON_SHADING, "contact_shadows": r17 or settings.TRYON_CONTACT_SHADOW,
            "edge_feather": r17 or settings.TRYON_EDGE_FEATHER, "shoulder_cap": settings.TRYON_SHOULDER_CAP,
            "hem_snap": settings.TRYON_HEM_SNAP, "halo_removal": settings.TRYON_HALO_REMOVAL,
            "neck_fix": settings.TRYON_NECK_FIX, "neck_gap_fill": settings.TRYON_NECK_GAP_FILL,
            "dropped_shoulder_single": settings.TRYON_DROPPED_SHOULDER_SINGLE,
            "hem_rule": settings.TRYON_HEM_RULE, "hem_hip_fraction": settings.TRYON_HEM_HIP_FRACTION,
            "hem_crotch_margin": settings.TRYON_HEM_CROTCH_MARGIN, "warp_engine": settings.TRYON_WARP,
            "neck_hole": settings.TRYON_NECK_HOLE, "mls_sleeve": settings.TRYON_MLS_SLEEVE,
            "mls_tube": settings.TRYON_MLS_TUBE, "mls_side_floor": settings.TRYON_MLS_SIDE_FLOOR,
            "mls_armpit": settings.TRYON_MLS_ARMPIT, "mls_hem": settings.TRYON_MLS_HEM,
            "mls_cuff": settings.TRYON_MLS_CUFF, "mls_fringe": settings.TRYON_MLS_FRINGE}
