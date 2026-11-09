# 09. Decisions log and remaining open questions

## Decided by the owner (do not ask again)
1. **Garment real size: NOT entered.** The garment always adapts (is deformed) to the body. No size-mismatch display.
2. **Realistic result is saved** with the outfit (plain result is kept too; UI shows the realistic one first).
3. **MVP garments = T-shirt + pants.** Body photo: short-sleeved/sleeveless top and shorts or tight leggings.
4. **Model path (avatar): measurements are REQUIRED** if the user wants to use an avatar.
5. **Body deletion: allowed** (user can delete their body and upload a new one).
6. **Own-body measurements: editable once per year** (365 days). Photo and landmarks stay immutable.
7. **Original photos: deleted** after normalization / cleaning.
8. **Stack confirmed:** React + TypeScript, Django + DRF, PostgreSQL, Celery + Redis, Docker.
9. **Image model: Nano Banana 2 (standard)**, not Lite and not Pro. Verify current model ID/price in Google docs.
10. **Auth: email + password only.** No Google sign-in.
11. **Garment AI cleaning is in P0 (Option A).** Users can upload hanger photos. (`rembg` alone does not remove hangers.)

## Proposed defaults (assistant's assumptions: confirm or change)
- Model-path required fields: height, shoulder, chest, waist, hip.
- Deleting the body also deletes the outfits made with it (their result images contain the person).
- Storage for MVP: local media volume in Docker behind signed URLs (S3-compatible later).
- Stretch quality guard in the warp: beyond about 1.4x (or below 0.6x) show a warning instead of distorting prints further. Not a "fit" label.
- Unit for measurements: centimeters.

## Still open
_(none blocking P0)_

## Decided 2026-11-07
12. **Body AI validation (prompt 02): P0.** Confirmed by owner.
13. **Measurements: circumference (cm).** Entered by user; backend converts to front-width (÷π) for landmark matching. Confirmed by owner.
14. (Assumption) The uploaded garment original is kept only until the user presses Save/Cancel (needed for the before/after screen),
    then deleted; a short TTL deletes it if the user leaves.
15. (Assumption) The backend returns the finished try-on image; the frontend does not compose garments itself.
16. Design gaps: admin moderation queue, realistic before/after compare screen, rejection reasons list. Design them when P2 starts.

## Decided 2026-11-09
17. **API contract fixed** (docs/04 "API contract" + `frontend/src/api/types.ts`). REST shape: one resource path with
    GET/POST/DELETE (`body/`, `garments/`, `garments/{id}/`, `outfits/{id}/`, `auth/me/`); no `/delete/` or `/upload/` suffixes.
18. (Assumption) Body landmarks are sent **once**, inside `POST body/confirm/`, together with optional height/measurements.
    There is no separate body-landmarks endpoint, so nothing can edit them. Measurements given at confirm do not start the yearly lock.
19. (Not yet confirmed) The day-1 experiment used **scanline warp** (fallback 1 in docs/06), on drawn placeholder avatars.
    Sleeves failed the criteria. Needs real avatars and an owner decision: see "Status" in CLAUDE.md.
