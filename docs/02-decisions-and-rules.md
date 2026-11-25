# 02. Decisions and hard rules (invariants)

These come from the product owner. Do not change them without asking. Log: `09-open-questions.md`.

## Immutability and deletion
1. **Body**: exactly ONE per user. Uploaded once in A-pose. After the user confirms, the photo and landmarks are immutable:
   no edit, no replace. Enforce in the backend: unique constraint on `user_id`, no PUT/PATCH for the photo/landmarks,
   upload returns an error if a confirmed body exists. Hiding a button in the frontend is NOT enough.
2. **Body measurements** (height and optional measurements) may be changed **once per 365 days**
   (`measurements_changed_at`). Nothing else on the body changes. Exception: `Body.sex` is chosen at upload; for bodies
   created before it existed it can be set once afterwards (`PATCH body/sex/`), then it is locked (docs/09 #97).
3. **Body deletion is allowed**: deletes the body, all its photos and the outfits made with it. After that the user can create a new body.
4. **Garment images**: cannot be edited, only deleted. No PUT/PATCH for the image. (Landmarks and visibility are data and may be adjusted.)
5. Deleting a garment: hard delete of files. Outfits keep their saved result images.
6. **Original uploads are deleted** after normalization (body) or cleaning (garment). Only processed images are stored.

## Visibility and privacy
7. Body, body photo, measurements: private to the owner, always. Every query filtered by `user_id`.
8. Garment visibility: `private` (default) or `public` chosen by the owner. The owner always sees the garment immediately.
   Public garments reach the catalog only after AI moderation (`approve`), or admin approval (`review`).
9. Public garments never expose the uploader's body, measurements or photos.
10. Images are served via short-lived signed URLs, not open public URLs.

## Upload requirements (strict, by decision)
11. Body photo: ONE photo, A-pose, whole body, front view, **tight thin clothing required**
    (strict rejection with a clear reason): **short-sleeved or sleeveless top** (sleeves end above the elbow) and
    **shorts or tight leggings**. Arms must not touch the torso, legs apart. Show the sample (tight short-sleeve top + shorts).
12. Do NOT build anything that removes the user's clothes or redraws their body. Require tight clothing at upload instead.
13. Garment photo: one garment, front view; user declares type. **MVP types: `tshirt` (short sleeve or sleeveless) and `pants` only.**
    Hanger/mannequin photos are allowed: AI cleaning removes them (P0) **when `AI_CLEANING_ENABLED=1`; off for now, docs/09 #55**. Other types are rejected (WRONG_TYPE).
14. Only adults: reject suspected minors for body photos (prompt 02) and require an "I am 18+" confirmation.

## Checks order (cost control)
15. Code checks first (cheap, deterministic), then AI checks. Geometry (arms touch, legs gap, framing) is checked by code, not AI.
16. Per-user daily limit on AI-reaching upload attempts (suggested 5). Code-check rejections do not count.
17. AI failures fail closed: invalid/empty AI JSON = rejected.
18. AI returns codes, the backend produces Uzbek user messages.

## Measurements and fit
19. Own body: marked landmarks on the photo are the required input; numeric measurements and height are optional.
    **Changed 2026-11-25 (docs/11, docs/09 #125):** measurements are required for try-on because of the fit check.
20. **Model path (avatar): gender only (changed 2026-11-23, docs/09 #124; before: numeric measurements required).** The backend `avatars/nearest/` and the measurement fields stay, unused by the frontend. **Fit check (docs/11, docs/09 #125) needs the user's measurements for try-on; how the avatar path supplies them is still to be settled.**
21. **SUPERSEDED 2026-11-25 by `docs/11-fit-check.md` (docs/09 #125): garment real size (cm) IS entered and a fit
    check runs before try-on.** The render rules below are unchanged. Fit is set per garment (`fit_mode`, docs/09 #93, decided 2026-11-11):
    `adapt` (default) = the garment is fully deformed to the body's landmarks; `keep_shape` = the garment keeps its own
    proportions (oversized, wide-leg) and only its anchors fit the body. There is no tight/fits/loose label in the render.
    `keep_shape` = MLS per-point k preset A (docs/09 #96); wired in the MLS engine (`TRYON_WARP=mls`, docs/09 #98).
    `mls` is the default T-shirt engine since docs/09 #105 (owner 2026-11-15); the `parts` engine (pants, MLS
    fallback, `TRYON_WARP=parts`) warps keep_shape like adapt.
21a. **Garment gender is enforced in try-on** (docs/09 #97): a male body/avatar sees `male` and `unisex` garments, a
    female one `female` and `unisex`; the backend refuses a mismatch (`GENDER_MISMATCH`). Garment size classes are
    NOT decided.

## Try-on result rules
22. The result shows the garment fitted to the body landmarks according to its `fit_mode`: fully deformed (`adapt`),
    or anchored at the landmarks with its own proportions kept (`keep_shape`).
23. Realistic render is optional, paid AI, only on user request. It must not change the person's face/body or how the garment sits.
24. The user can save an outfit with the plain result and/or the realistic result; the realistic one is saved with the outfit.

## Canvas
25. Body/avatars/try-on results: 600 x 1200 px (width x height), axis_x = 300, figure from y=50 to y=1150.
26. Garments: tight-cropped transparent PNG (not forced to 600x1200).

## Stack and services
27. React + TypeScript; Django + DRF; PostgreSQL; Celery + Redis; Docker. Email + password auth only.
28. Image model: Nano Banana 2 (standard). Official Google Gemini API only.

## Language
29. User-facing text: Uzbek (Latin script, with ʻ for oʻ/gʻ). Code, comments, API: English.
