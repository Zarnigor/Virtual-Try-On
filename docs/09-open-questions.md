# 09. Decisions log and remaining open questions

## Decided by the owner (do not ask again)
1. **Garment real size: NOT entered.** The garment always adapts (is deformed) to the body. No size-mismatch display.
   (Changed 2026-11-11, #93: fit is per garment, `adapt` | `keep_shape`.)
2. **Realistic result is saved** with the outfit (plain result is kept too; UI shows the realistic one first).
3. **MVP garments = T-shirt + pants.** Body photo: short-sleeved/sleeveless top and shorts or tight leggings.
4. **Model path (avatar): measurements are REQUIRED** if the user wants to use an avatar.
5. **Body deletion: allowed** (user can delete their body and upload a new one).
6. **Own-body measurements: editable once per year** (365 days). Photo and landmarks stay immutable.
7. **Original photos: deleted** after normalization / cleaning (body: right after the validation job, see 25 and 31).
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
- **Hem rule as a benchmark assumption (2026-11-11, not a decision):** the MLS single-field benchmark
  (`tools/warp-benchmark/`, docs/06 "MLS single-field benchmark") targets the T-shirt hem at
  hip_y + 0.35 x (crotch_y - hip_y), at most crotch_y - 10 px, with the hem half-width = garment hem/waist ratio x the
  body's waist half-width (at least the hip half-width). Used only to compare methods; the warp method (production
  row warp + rigid sleeves vs MLS) stays the owner's choice. The production hem rule itself is #91 (proposed).
  Round 2 (marked landmarks + fit strength k, docs/06) uses the same hem assumption; still not a decision.

## Rejected
- **shoulder_slope pair (V1), alignment tweak (V2), both (V3)** for `keep_shape` (rejected by the owner 2026-11-11,
  #96): they raise the garment top edge towards the jaw on male plus and add nothing over preset A once the shoulder
  points are marked at the sleeve seam. Kept in `tools/warp-benchmark/` for reference only. Former proposal:
  - **shoulder_slope pair + alignment tweak is a benchmark proposal (2026-11-11, not a decision):** docs/06 round 4.
    V3 (both) closes most of the bare-shoulder triangle on #44 at the cost of 73-187 px of garment above the shoulder;
    male plus is not closed. Whether to use it, the 50 % point, the 1.05 scale and the raise rule are NOT decided.
    Round 5 (2026-11-11, re-marked shoulder_* at the sleeve seam): plain preset A already closes the gap (0-3 px);
    the slope pair (V1) halves the garment-above-shoulder excess. Still a proposal; the method choice stays with the owner.

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
20. (Step 3) A rejected or failed body/garment upload is deleted (row + files), so the user can upload again;
    the job keeps the error code for the message. Uploads rejected by AI still count toward the daily limit (step 4).
21. (Step 3, changed in step 4: see 24) `AI_DEV_BYPASS`: local-only flag (works only with DEBUG) that skips AI calls.
    Default in docker-compose = 1 for local testing; production must leave it unset. Invalid AI replies are rejected even with it.

## Decided 2026-11-09: step 4 (own-body pipeline), confirmed by owner
22. **Body validation model: Gemini Flash text model**, set by env `GEMINI_VALIDATION_MODEL`. Default `gemini-3.6-flash`
    (stable, image in / text out, structured output; checked in Google's model docs on 2026-11-09). Nano Banana 2 stays the
    image model for prompts 04 and 05. Note: `temperature` is ignored on 3.6 Flash and newer, so reliability comes from
    `responseJsonSchema` + the code re-check (27).
23. **Gemini is called over plain `httpx`** (`generateContent` REST, `x-goog-api-key` header). No `google-genai` /
    `google-generativeai` SDK. The httpx transport is injectable; tests use `httpx.MockTransport` and a test-wide guard
    fails any real HTTP call. One manual check against the real API confirms the Pydantic-generated `responseJsonSchema` is accepted
    (synthetic image with no person in it, so no personal data is sent).
24. **`AI_DEV_BYPASS=1` always skips the AI call**, whether `GEMINI_API_KEY` is set or not (DEBUG only). Use `AI_DEV_BYPASS=0` to test
    real calls. A skipped job sets `ai_skipped`, does not set `ai_called` and does not count toward the limit.
25. **Image sent to the AI:** the EXIF-stripped original, resized to about 1024 px long side (JPEG). Not the 600x1200 cutout.
    The original is stored separately (`Body.original_image`, under `bodies/originals/`) and deleted in a `finally` block right
    after the job finishes, in any outcome. `Body.image` is only the normalized 600x1200 image.
26. **Pipeline order (code checks first):** EXIF strip -> rembg (`u2net_human_seg`) -> code checks (`HEAD_OR_FEET_CUT`,
    `ARMS_TOUCH_BODY`, `LEGS_TOUCH`, no/several people) -> normalize 600x1200 -> auto landmarks (returned in `GET body/`) ->
    reserve AI slot -> prompt 02 -> parse. Code-check rejections never reach the AI and never count.
27. **Fail closed both ways.** The backend derives issue codes from the reply's own fields (e.g. `sleeves == "long"` ->
    `LONG_SLEEVES`) and merges them with the AI's `issues`. Accepted only if `ok` is true, the merged list is empty and every field
    passes. `ok: true` with contradicting fields is rejected with the derived codes.
28. **Error codes: "AI could not answer" is separate from "photo rejected".**
    - `AI_UNAVAILABLE`: timeout, network error, 429/5xx after one retry, missing key. Does **not** count toward the daily limit.
    - `AI_RESPONSE_INVALID`: Gemini returned a response but it is not valid JSON or does not match the schema. **Counts** toward
      the limit (it was billed, and text in a photo could provoke it). Logged under this distinct code (Pydantic error
      locations only, never the image or the raw reply) and shown in an AI metric so prompt/schema bugs are visible.
    - Both show the user the same Uzbek "try again later" message, never "photo rejected". The upload is still rejected (fail
      closed) and the body deleted so the user can retry.
    - Photo rejections use the AI issue codes and their existing Uzbek messages. `INVALID_AI_RESPONSE` is no longer shown to users.
29. **Daily AI limit is race-safe.** Inside `transaction.atomic`, lock the user row (`select_for_update`), count today's
    (Asia/Tashkent) counted jobs, and if under the limit set `ai_called=True` **before** sending the request.
    `ai_called` is an audit flag, never cleared. `ai_outcome` = `""` (in flight) / `responded` / `invalid` / `unavailable`.
    Counted = `responded` + `invalid` + in flight (a not-yet-finalized job; the stuck-job cleanup in 32 finalizes it within 15 min).
    The upload view does a quick unlocked pre-check for a fast 429 `AI_LIMIT`; the worker check is the real one.
    Tested with a `TransactionTestCase` on PostgreSQL: two threads race for the last slot, exactly one gets it.
30. **Idempotent, crash-safe worker.** Celery `acks_late=True` and `task_reject_on_worker_lost=True`, so a crashed job is redelivered.
    On (re)delivery: if the job is already `done`/`failed`, exit. If `ai_called` is True and a saved verdict exists in `job.result`,
    finish from it. If `ai_called` is True and no verdict exists (poison-pill guard), finalize as `AI_UNAVAILABLE` with **no** new
    Gemini request. The parsed verdict is saved right after the response.
    (Assumption) Task `time_limit` 300 s (soft 240 s); Redis `visibility_timeout` 3600 s, well above the max task duration.
31. **Orphaned originals cleanup:** a Celery beat task (`CELERY_BEAT_SCHEDULE` in settings, new `beat` service in
    docker-compose) deletes body originals older than 1 hour and clears the field (covers crashes where `finally` never ran).
    Garment originals are added in step 6 (they must stay until Save/Cancel).
32. **Stuck-job cleanup:** jobs in `queued`/`running` not updated for **15 minutes** are finalized as `AI_UNAVAILABLE` with an atomic
    conditional `UPDATE ... WHERE status IN (queued, running) AND updated_at < now - 15 min`, so a live job is never touched
    (15 min is above the 5 min hard task limit). Only if that update hit a row is the unconfirmed body deleted.
    (Assumption) Runs every 5 minutes on the same beat service.
33. **Re-upload replaces an unconfirmed body.** `POST body/` while an **unconfirmed** body exists deletes it (and finalizes its
    open job, so a late worker finds no body) and starts a new upload, instead of returning `BODY_EXISTS`. A **confirmed** body
    still returns 409 `BODY_EXISTS` (delete it first). The stuck-job cleanup stays as a safety net.
34. (Assumption) **AI metric:** staff-only `GET /api/admin/metrics/ai/` returning job counts by kind and `error_code`
    (incl. `AI_RESPONSE_INVALID`) for the last 24 h and 7 days, read from the `jobs` table. No extra metrics stack in the MVP.
    Assumptions in 30, 32, 34 and the `AI_RESPONSE_INVALID` spelling were approved by the owner on 2026-11-09.
35. **A finalized job is a no-op on start.** The first thing the task does is check the job status. If it is already `done` or
    `failed` (e.g. finalized by the stuck-job cleanup in 32 before a late redelivery), the task exits without touching the body,
    the images or Gemini. This is checked before the poison-pill rule in 30.
36. **Replace-on-upload race (with 33).** `Body.current_job` points to the job that is processing that body. A re-upload
    (in one transaction, user row locked) marks the old open job `failed` with code `SUPERSEDED` and replaces the body.
    The worker finalizes only through a conditional update in one transaction: the body still exists, `body.current_job` is
    this job and the job is still `running`. If that check fails, the job was superseded: the worker discards the result
    and deletes every image it wrote (normalized image and original), so nothing is orphaned and the new upload is untouched.
    `SUPERSEDED` is internal (the user is already on the new upload); a superseded job that already called Gemini still counts.
    Test: two quick uploads in a row; only the second body survives, the first job ends `SUPERSEDED`, its files are gone.

## Decided 2026-11-09: landmark editor (design artboard VariantC), confirmed by owner
37. **Every group shares one Y** (Sol/Oʻng and all four leg points of Tizza/Pocha, and the sleeves). The payload shape is unchanged:
    every y path of a group (e.g. `knee.y`, `knee.left_leg.y`, `knee.right_leg.y`) is written with the same value. Old records
    whose sides differ load with the average. The "Sol va Oʻng bir Y da" switch from the design is removed (always on).
38. **Symmetry:** axis = image width / 2 (also the fallback for old records); a paired point moves its mirror to `w - x`;
    single points (`waist.center_x`, `crotch.center_x`) snap to the axis when symmetry is on (immediately when it is switched on).
39. **Nudge:** arrow keys 1 px, Shift 5 px (was 10 px in docs/03); arrow buttons use the 1 px / 5 px switch. Units are image
    pixels. Points are clamped to the image bounds and stored as whole pixels.
40. **Pants `crotch.center_x` is saved** (it was dropped before; separate commit 7c7125a). Optional in the contract: old records
    without it still load (x = w / 2).
41. **Frontend unit tests: `vitest`** (devDependency), for `components/landmark-editor/geometry.ts` only for now, including a
    round-trip test that the payload stays unchanged. Run: `docker compose exec -T frontend npm test`.
42. (Assumption, garment upload fix) **Server-side upload validation** in `backend/apps/images.py`, decided from the file bytes:
    JPEG/PNG only, at most `MAX_UPLOAD_MB` (20), at most `MAX_IMAGE_PIXELS` (50 MP, checked before decoding), full decode
    (truncated/corrupt -> `CORRUPT_FILE`), shorter side at least `GARMENT_MIN_SIDE_PX` (300). Errors are `{code, detail}` with an
    Uzbek message. The client repeats the checks only for UX. The original is stored byte-for-byte.
43. (Garment quality fix) The cleaning step takes **only the mask** from rembg and adds it as alpha to the untouched source pixels
    (rembg's own cutout stored colour * alpha in a straight-alpha PNG: dark fringes). EXIF orientation is applied in memory, the
    stored original is never rewritten, the result is saved once as lossless PNG. The editor draws the image in SVG at device
    resolution (the old 500 px canvas ignored devicePixelRatio) with no blend mode.
44. (Garment cleaning fix) `Garment.image` is **only** the cleaned PNG. At upload only `original_image` is stored, so `image_url`,
    `thumb_url`, `width`, `height` are `null` until the cleaning job has run (types.ts already allows null). The job reads
    `original_image`. `PATCH garments/{id}/landmarks/` returns 409 `GARMENT_NOT_READY` before that, so landmarks are always pixels
    of the cleaned crop. The wardrobe shows "Tayyorlanmoqda" / "Belgilangan" / "Belgilanmagan", shows the moderation status only
    for public garments (private ones always say "pending"), and polls until every garment has its image.

## Decided 2026-11-09: garment AI check (prompt 01, part of step 6), approved by owner
45. **Garment AI check is wired** in `run_garment_cleaning`, before cleaning: cache -> poison-pill guard -> daily slot -> Gemini
    (httpx, model from `GEMINI_VALIDATION_MODEL` in .env, never hardcoded) -> strict Pydantic parse. Timeout at least 60 s
    (`GEMINI_TIMEOUT_S`), one retry on 429/5xx and network errors, no retry on timeout. `google-generativeai` removed.
46. **The schema follows prompt 01** (`top|pants`, `sleeve_length`, `visible_fraction >= 0.6`). The backend sends `top` for
    `tshirt`. Type mismatch, a non-short-sleeved top declared as `tshirt`, or the AI's `WRONG_TYPE` -> **`WRONG_GARMENT_TYPE`**
    ("Rasmdagi kiyim tanlangan turga mos emas. Futbolka yoki shim turini toʻgʻri tanlang.", confirmed by owner).
    `ok: false` with no failing field and no known issue -> `AI_RESPONSE_INVALID`.
47. (Default, confirmed by owner 2026-11-09: `AI_UNAVAILABLE` stays free) **AI photo rejections still count** toward the daily limit (unchanged #20, #28: the reply was
    billed). Only `AI_UNAVAILABLE`, code-check rejections, bypassed jobs and cache hits are free. The race-safe slot from #29
    is built now (`apps/jobs/limits.py`, PostgreSQL race test). Over the limit the job fails with `AI_LIMIT` (worker only; the
    upload endpoint contract is unchanged, so there is no 429 pre-check yet).
48. (Default, owner to review) **`Garment.ai_skipped`** (read-only API field) marks garments whose AI check was bypassed. The
    frontend shows a yellow "DEV: tekshirilmagan" chip (wardrobe, try-on) and a banner (landmark editor).
49. (Default, owner to review) **Cache by image hash:** Django cache on Redis, 30 days, key = sha256(image hash, declared type,
    prompt hash, model). Stores the parsed fields only; rules are re-run in code on every hit. Only valid, self-consistent
    replies are cached. A cache error is a miss.
50. **Code renamed** `INVALID_AI_RESPONSE` -> `AI_RESPONSE_INVALID` (approved spelling, #34). It shows "try again later".
51. **Tests:** `apps/jobs/tests_garment_ai.py` (MockTransport, hand-written fixtures from the prompt schema). The test runner
    (`tryon_studio/test_runner.py`) blocks every real httpx call and uses an in-memory cache.
52. **Separate daily limits per job kind** (owner, 2026-11-09): `AI_DAILY_LIMIT` (body checks, default 5) and
    `AI_GARMENT_DAILY_LIMIT` (garment checks, default 5), counted by `Job.kind`, so garment uploads never use up the body check.
    Both are passed to the containers by docker-compose. `.env.example` sets `AI_GARMENT_DAILY_LIMIT=30` as the dev value.
    `AI_UNAVAILABLE` stays free for the user.

## Decided 2026-11-09: garment landmark validation, approved by owner
53. **Server-side garment landmark checks** (`apps/garments/landmark_checks.py`, pure function, rules in docs/03): required
    keys per type (what warp.py reads), finite numbers inside the cleaned PNG, left < right, legs do not overlap, pants waist
    center inside the waist and 5 px inside the hip, vertical order. Strict `<`, so old records with a 1-3 px gap still save.
    Failure: 400 `{code: "LANDMARKS_INVALID", detail}` with a fixed Uzbek message naming the group (never an exception text).
    `GARMENT_NOT_READY` (409) is checked first. Extra keys are stored unchanged.
54. **Editor clamps moves** with the same rules plus a 4 px gap (`MIN_GAP`): a drag or nudge stops at the neighbour. With
    symmetry, a pair is clamped together (it stays symmetric); a center point snaps to the axis only if the axis is in its
    range, otherwise it stays. If no valid place exists the point stays. **Loading never clamps** (an old record is unchanged
    until the user moves a point). Save is disabled until every point is placed, with the hint "Saqlash uchun barcha
    nuqtalarni qoʻying (n / total)."; a failed save shows the backend's `LANDMARKS_INVALID` message.

## Decided 2026-11-10: AI garment cleaning off for now, decided by owner
55. **AI cleaning (prompt 04) is optional and off** (`AI_CLEANING_ENABLED`, default `0`). Reason: the image model needs
    prepaid credits we do not have. Off: `run_garment_cleaning` runs prompt 01 (unchanged) then rembg only (mask only,
    original pixels kept, alpha added, cropped). Hanger/mannequin photos are not cleaned. On: prompt 04 is not built, so
    the job fails at once with `CLEAN_FAILED` (clear detail) before prompt 01, so no AI call or daily slot is spent.
    Also: `AI_DEV_BYPASS` now defaults to `0` in `.env.example` and in the docker-compose fallback (never bypass unless
    `.env` says so). The model name for prompt 01 comes only from `GEMINI_VALIDATION_MODEL`.

## Decided 2026-11-10: real avatars, try-on engine, demo mode (owner asked for these steps)
56. **Real avatars** from `./avatars` (6 JPG, 2400x1792, landscape): `seed_avatars --from /avatars`. Never stretched: one
    uniform scale = min(1100 / figure height, (300 - 10) / widest half from the body axis), padded to 600x1200 RGBA,
    figure top y=50, axis x=300; clipping fails loudly. File names map by tokens (`man_slim`, `woman_plus_size` ...).
    Initial landmarks per avatar from its own mask (no shared defaults); crotch = leg gap, or a seam > 30 grey levels
    darker just above it when the thighs touch (male plus). Staff editor = source of truth (not built yet).
    The backend start no longer overwrites seeded avatars (placeholder mode only creates missing ones; `--force`).
57. **Scanline engine kept** (no mesh warp, item 19): rules in docs/06 "Engine as built". Lengths follow the garment,
    widths follow the body; rigid sleeves along the outer silhouette, at most half the arm; hands redrawn above.
58. **Demo mode** (`DEMO_MODE=1`): `build_demo --garments <folder>` precomputes every avatar x garment and T-shirt+pants
    pair; covered pairs are served as finished jobs (no Celery/Gemini), others take the normal path. Demo garments are
    approved catalog garments. Public `GET /api/config/` exposes the flag; the UI shows "DEMO".
59. (**Replaced by #120 for rows pants.**) **Pants keep their own silhouette** (2026-11-10, docs/06 "Pants fit"): one uniform scale (waist..hem vs waist..ankle,
    rise for short pants); only the waistband fits the body (+4 % ease), blended to the garment's width by the hip; below
    the hip a row is max(garment, body + 4 %), capped at 1.8x body (knee width below the knee, so cuffs are not
    squeezed); legs centred on the body's leg centreline. Warnings only when a row's scale differs from the uniform
    scale by > 1.3x. T-shirt keeps the old "widths follow the body" model for now.
60. (**Pants hang replaced by #120.**) **Realism pass** (2026-11-10, docs/06 "Realism pass"): shading from the avatar's luminance (strength 0.7), 1 px
    rim removal + feather, 0.25 contact shadow on the figure, loose pants hang half way to a vertical drop, curved
    waistband top. Pure 2D post-processing of the warped garment; nothing of the avatar is redrawn.
61. (**Replaced by #120 for rows pants.**) **Loose pants do not bend at the knee** (2026-11-10, docs/06 "Loose-leg centreline"): loose legs (knee ratio
    >= 1.15x) use a smooth monotonic centreline with at most 25 % knee pull; tight legs keep the knee line. Loose/tight
    and the hang weight are decided per leg, not per row.
62. (**Replaced by #120 for rows pants.**) **Looseness per garment, smooth** (2026-11-10, replaces the per-leg cut of #61): mean knee ratio of both legs,
    smoothstep 1.05x .. 1.15x drives the knee pull (1 -> 0.25) and the hang weight (1 -> 0.5); both legs share them.
63. **Garments are opaque, realism is optional** (2026-11-10): holes inside the garment silhouette are filled after
    rembg and after warping (background-coloured openings kept); compositing fixed to straight-alpha "over".
    Shading, contact shadow and edge feather are behind `TRYON_SHADING`, `TRYON_CONTACT_SHADOW`, `TRYON_EDGE_FEATHER`
    (default 0). The T-shirt still uses "widths follow the body" (no ease model, no neck/sleeve layering yet).
64. **T-shirt keeps its own silhouette** (2026-11-10, docs/06 "T-shirt fit"): uniform scale from the shoulder line
    (+4 % ease), rows max(garment, body + 4 %) capped 1.8x, per-garment looseness, rigid overlapping sleeves, head/neck
    drawn above the garment. Scale from shoulder width, not torso length: length would force every hem to one row.
65. **T-shirt round 3** (2026-11-10): curved, feathered head/neck overlay edge; shoulder band filled under the
    garment with the shoulder-row colour; the pants reach 6 px under the T-shirt hem (crop tops with pants included).
66. **Hem over waistband, revised** (2026-11-10, replaces the pants extension of #65, which left maroon lines beside
    the T-shirt): pants are cropped above their waist row; a T-shirt hem within 12 px above the pants waist is extended
    down to 6 px past the pants top; crop tops further up are unchanged.
67. **Solid-colour garments** (2026-11-10): near-solid garments get 80 % of their low-frequency photo lighting removed
    once at cleaning (`GARMENT_FLATTEN_LIGHTING`, default 1); prints untouched. Sleeves warped premultiplied (dark
    edges in the sleeve/torso overlap). Both current demo garments are textured (detail std ~33), so not flattened.
68. **Texture thresholds from real garments** (2026-11-10): high-frequency luminance (L minus blur at 8 % width),
    std <= 16 and outlier share (|hf| > 25) <= 1.5 %. Measured: black T-shirts #19/#27/#28 8.1 / 0.9 %, #26 9.3 /
    0.6 % (flatten); pink T-shirt with text #4/#17 32.2 / 46 %, maroon joggers with white print #23 33.6 / 17 %,
    demo pants #18 33.5 / 24 % (keep). Synthetic: solid+gradient 3.7 / 0 %, small text 28 / 8.3 %, large print 50 / 40 %.
69. **Re-flattening existing garments** (2026-11-10): `manage.py reflatten_garments --ids ... | --all-solid
    [--dry-run]` rewrites the cleaned PNG of near-solid garments once (`Garment.lighting_flattened`, also set at
    cleaning and by build_demo); prints are never touched. Owner-approved exception to "garment images are
    immutable": an admin maintenance step on the processed image, not a user edit. Run on #28 (the black T-shirts
    #19/#26/#27 had been deleted in the app).
70. (**Replaced by #120 for rows pants.**) **Pants silhouette bug** (2026-11-10): the straight lower panel came from landmark-interpolated row spans
    (crotch -> knee -> hem), not from the centreline rule. Rows now use the garment's own silhouette span.
71. **Double sleeves fixed** (2026-11-10): with shoulder landmarks at the sleeve tips (garment #28), upper-sleeve
    fabric was warped by the torso rows AND sampled again by the rigid sleeve's inward reach (added in 98da3c7).
    Each garment pixel now belongs to the torso or a sleeve, never both; the torso widens to meet the sleeve.

## Decided 2026-11-10: staff avatar editor and staff tools (owner asked for these, built autonomously)
72. **Staff avatar editor** (`/staff/avatars`, `/staff/avatars/:id`, API `staff/avatars/...`, docs/04): the Variant C
    editor with body groups (`bodyGroups.ts`). Every line has left/right points on the body edge; `head_top`, `armpit`,
    `crotch`, `foot_bottom` gained `left_x`/`right_x` (crotch keeps `center_x`). (Interpretation) y-only lines get edges
    too, so each line can be checked on the silhouette. Saving validates (`apps/bodies/landmark_checks.py`, rules in
    docs/03), recomputes widths and sets `Avatar.landmarks_confirmed_at`; the engine reads `Avatar.landmarks` (test).
    Non-staff get **404**, anonymous 401. Not-yet-confirmed avatars get edge points from the mask on GET (never written).
73. **Shared body pipeline** `apps/bodies/pipeline.py` (EXIF strip -> rembg -> code checks `NO_PERSON`,
    `HEAD_OR_FEET_CUT`, `FIGURE_CLIPPED` -> 600x1200 -> auto landmarks). Used by `POST staff/avatars/` (synchronous,
    no AI: staff choose the photos) and `seed_avatars --from` (now any subset of the 6; a reseeded or re-uploaded avatar
    loses its confirmation). The own-body job is **not** switched to it yet: that is step 4 (waits for the 3b findings).
74. **`BODY_AI_CHECK_ENABLED`** (default 1): 0 skips prompt 02 on own-body uploads and marks `ai_skipped`; honoured only
    with DEBUG (adults-only is a hard rule, production always checks).
75. **Chest = fullest torso row** just below the armpit (armpit + 1..8 % of height), replacing "armpit + 2.5 %". Editor
    hints use one definition per line for body and garment (`lineHints.ts`): hip widest, waist narrowest, chest
    fullest, crotch where the legs split.
76. **cm beside the editor:** width_cm = px width x height_cm / (foot_bottom.y - head_top.y); circumference estimate =
    ellipse with depth 0.6 x width (Ramanujan), labelled "taxmin", editable, saved with `height_cm` to
    `Avatar.measurements` (merged). Unconfirmed avatars start from the estimate, confirmed ones from the saved values.
77. **Staff tools:** `create_staff_user --email` (password from `STAFF_PASSWORD` or a prompt; `is_staff`, not superuser).
    Staff are exempt from `AI_GARMENT_DAILY_LIMIT` only: the slot is still reserved and the AI check still runs
    (`AI_DEV_BYPASS` untouched, stays 0); the body limit applies to staff too. `promote_garments --list` and
    `--ids ... --catalog` (public + approved; refuses garments without a cleaned image or landmarks).
78. **Demo garments checked against their type** (2026-11-10): #17 `tshirt` (short-sleeved gingham top) and #18 `pants`
    (patched wide-leg trousers) both match (a short-sleeved top is a valid `tshirt`, #46). Nothing deleted.

## Decided 2026-11-10: try-on compositing restructured (owner asked: autonomous, 4 rounds, contact sheets)
79. **One layer order** (docs/06 "Layer order", `warp.LAYER_ORDER`): avatar -> pants (from their waist row) -> shoulder
    cap -> T-shirt torso -> rigid sleeves (once each) -> head/neck -> hands/forearms. Replaces the stacked patches of
    #65, #66 and #71 (shoulder band fill, hem row repetition, sleeve reach-in / torso widening by quad).
80. **Row warp by `cv2.remap`** (`_warp_rows`): sub-pixel, antialiased, span edges smoothed over 5 control rows; the
    integer `_scanline_strip` is gone. Garments shrunk below 0.8x are area-resampled first.
81. **Sleeve region** = outward of the armhole line; rows joined to the torso below the armpit are split along the
    armpit -> torso-edge line (#17, #28 had the sleeve inside the torso rows: "wings", streaks beside the arms).
    Sleeves are centred on the arm. The old quad (shoulder, sleeve_end x 1.15, armpit) took a strip of the torso side
    with it on cap sleeves (#34): the pale panels beside the arms.
82. **Shoulder landmarks on the sleeves** (span > 1.35 x chest span, #28) are replaced by estimated armhole tops
    (12 % of the chest span outward of the armpits) with a warning. Proposed default: confirm or re-mark #28.
83. **Hem snap** stretches the rows below the chest (0..12 px + 4 % of the shoulder width above the pants top ->
    6 px over it); a T-shirt row over the pants is at least as wide as the pants. Halo: erode 2 px + 4 px ring
    recolour, once, at the warped size.
84. **Flags** (structural, default 1, `flags.render_flags`): `TRYON_SHOULDER_CAP`, `TRYON_HEM_SNAP`,
    `TRYON_HALO_REMOVAL`. None had to be turned off after the 3 rounds. Remaining defects are data/rule limits, listed
    in docs/06 "Known limits": avatar's own top under crop tops and beside wide necklines, #25 hip bulge on slim
    avatars, rigid puff sleeves, stale demo results (run `build_demo` again).
    Check tool: `tools/tryon_check/matrix.py` (contact sheet per garment set, `MATRIX_CROP` for zoomed sheets).

## Decided 2026-11-10: neckline compositing (owner asked, built autonomously)
85. **Neck fix** (`TRYON_NECK_FIX`, default 1, docs/06 "Neck zone"): the T-shirt's inner back collar is made transparent
    (crew-neck-sized rim, clearly darker than the ring), head/neck edge feather 1.5 -> 0.6 px, shoulder-edge alpha
    smoothed, all inside the neck zone only. Garment #34 (pink crop top) no longer exists in the DB, and there is no white
    T-shirt: the check uses #28, the blouse #17 and `white28` (#28 recoloured to white in memory, never saved). Re-run
    `neck.py` with real ones when uploaded (`NECK_IDS`). Demo results need `build_demo` again.

## Decided 2026-11-10: T-shirt compositing round 4 (owner asked, built autonomously)
86. **Sleeve/torso ownership** (docs/06 "Layer order" step 4): the sleeve is sampled from the whole garment image
    inside its territory (own garment pixels + 3 px past the armhole, rigid transform, threshold 0.5); outward of the
    armhole line only the sleeve exists, inward the sleeve is drawn over the torso. Removes the seam lines along the
    join (two clipped soft edges over each other let the avatar through) and the doubled outer sleeve edge.
    The sleeve is clipped below the torso's shoulder slope line within one armhole length of the shoulder point:
    no shoulder "pad". The T-shirt halo fix runs once, after compositing, on the outer contour only (2 px erode +
    2 px ring), no longer on the source; holes and joins are untouched.
87. **Shoulder cap** is drawn under the finished T-shirt layer; colour = median of the garment's solid pixels 3..15
    rows under its top edge, median-filtered along the shoulder (was: one pixel per column plus a black/skin feather:
    the tan/brown streaks).
88. **Neck**: one smooth head/neck edge without vertical walls, feather ~3 px, kept above the front collar band. New
    flag `TRYON_NECK_GAP_FILL` (default 1): the avatar's grey tank collar left between the neck and the collar is
    painted in the neck's skin colour (chroma/hue test, ~2 px feather; 0-90 px per render). It touches the avatar's
    own clothes in a thin strip at the neckline; the owner may turn it off. A first version (Lab distance) took the
    shadow under the chin for "not skin" and painted a flat brown bib on the black T-shirt; replaced before commit.
    Remaining (docs/06 "Known limits"): dropped-shoulder corner on #36, prints split at the shoulder join, the
    avatar's top beside the torso where the arm touches (pre-existing). No flag had to be set to 0.
89. (decided 2026-11-10) Neck-gap fill (TRYON_NECK_GAP_FILL) is allowed for admin avatars only; it must be 0 for the own-body path (docs/02 rule 12).
90. **Dropped-shoulder T-shirts as one piece** (flag `TRYON_DROPPED_SHOULDER_SINGLE`, **default 0**; 2026-11-10).
    Detection: `dropped_shoulder_ratio` = the garment's flat top-line half-width (top within 3 % of the shoulder span of
    the highest centre pixel) / its shoulder half-width x 1.04, i.e. that reach at the T-shirt's scale over the avatar's
    shoulder half-width. Measured: #36 0.67, #28 0.53, #17 0.50 -> threshold 0.60 (midpoint). Above it, `_single_piece`
    remaps the whole garment once: the torso row map inward of the armhole, bending (smoothstep over half an armhole
    length) into the rigid sleeve map outward; below the armpit the bend edge is the torso edge. Result on #36: the
    boxy shoulder pad is gone (crop, male average), but below the armpit row each sleeve shears into stepped blocks
    sticking out sideways on all 6 avatars (the torso map continued past the torso edge samples the hanging sleeve at
    the wrong source rows). So the flag is 0; #28/#17 and all set-in sleeves are pixel-identical either way.
    Next step if wanted: below the armpit use the sleeve map alone (no blend) and verify on a sheet.
91. **T-shirt hem length rule (proposed, confirm with owner)**, flag `TRYON_HEM_RULE` (default 1), constants in
    settings (`TRYON_HEM_HIP_FRACTION` 0.35, `TRYON_HEM_CROTCH_MARGIN` 10). Bodies have no hem landmark:
    hem_y = hip_y + 0.35 x (crotch_y - hip_y), at most crotch_y - 10 px. The garment's real bottom edge (hem landmark
    + trims below it) lands on hem_y: uniform scale down to the chest row (sleeves stay aligned), then the chest ->
    hem rows are stretched or squeezed (warning beyond 1.25x); widths unchanged; the crotch cut and the hem snap over
    the pants are not used with the rule (the hem is below the waistband anyway). Measured on #17, #28, #36 x 6
    avatars: rendered hem 0-2 px above hem_y, never below the crotch. `TRYON_HEM_RULE=0` restores the garment's own
    length (crop tops stay short).

## Decided 2026-11-11: extended T-shirt landmark set (owner asked, built autonomously)
92. **T-shirt garment landmarks** (docs/03): `shoulder` (seam where the sleeve starts), `armpit` (new), `chest`, `waist`,
    `hem`, `collar` left/right (new, collar edges at the shoulder line), `collar_bottom` (new, lowest centre point of
    the neckline), `sleeve_cuff_outer` / `sleeve_cuff_inner` left/right (new, replace `sleeve_end`). Single source:
    `apps/garments/landmark_checks.py` (frontend mirror: `garmentGroups.ts` + `garmentChecks.ts`, names in
    `src/locale/uz.ts`). Optional in the API for now: armpit, collar, collar_bottom. The cuff corners are required on
    write because they replace the required `sleeve_end`; legacy `sleeve_end` is accepted on read and never written.
    The production warp is unchanged: it gets `sleeve_end` = cuff midpoint from `engine_landmarks` (not stored).
    Sanity checks: errors for order (collar_bottom below the collar, shoulder < armpit <= chest < waist < hem, cuffs on
    their own side, outer/inner not swapped); warnings for ranges (collar near the shoulder line, points inside the
    garment's alpha bounding box). `landmarks_complete` on the garment response; the editor shows a banner when false.
    Pants and body sets unchanged. Garments marked before this change must be re-marked to save again (cuffs).
    Still open (not decided by this change): the hem rule (#91 proposed, "Still open" benchmark note) and the
    measurement-to-width conversion.

## Decided 2026-11-11: per-garment fit mode and gender (owner decision)
93. **Garment fit is now per garment**: `Garment.fit_mode` = `adapt` (default, fully deformed to the body landmarks,
    the current engine) | `keep_shape` (keeps its own proportions, e.g. oversized or wide-leg; only anchors fit the
    body). Plus `Garment.gender` = `female` | `male` | `unisex` (default); the list filter `gender=` returns unisex
    garments for female and male too. Both editable with PATCH garments/{id}/ (owner only, nothing else editable,
    never the image), shown on screen 9 and as list badges. This changes docs/02 rules 21-22 (updated) and replaces
    decision 1's "the garment always adapts". The try-on task passes `fit_modes` to `render_tryon`, which ignores it
    for now (TODO): **engine behaviour for keep_shape is pending the MLS benchmark** (docs/06 "MLS single-field
    benchmark"). Existing garments got the defaults (adapt, unisex) by migration 0005.
    **Update 2026-11-11:** keep_shape = preset A (#96), wired for T-shirts in the MLS engine behind `TRYON_WARP=mls`
    (#98); the default `parts` engine still ignores fit_mode.

## Decided 2026-11-11: garment armpit <= chest rule removed
94. **2026-11-11: Garment armpit<=chest rule removed (oversized garments); body rule unchanged.** Client
    (`garmentChecks.ts`, editor clamp in `garmentGroups.ts`) and server (`apps/garments/landmark_checks.py`). Other
    garment checks stay. MLS benchmark pairing: a chest pair with garment chest <= armpit, or with a garment/body
    vertical order that differs from any other row pair, is dropped from the control points (never fed crossing).
    Production scanline engine does not pair the garment armpit, so it is unchanged (pixel-identical test).

## Decided 2026-11-11: chest above armpit is a warning, and the benchmark runs it
95. **2026-11-11:** T-shirt order rule is `shoulder < armpit` and `shoulder < chest < waist < hem`; chest above the
    armpit gives the warning `chest_above_armpit` (client + server), never an error. The keep_shape benchmark
    (`run_keep_shape.py`) no longer refuses such garments: the chest pair is not used, reported as "chest not used".

## Decided 2026-11-11: oversized garments, keep_shape = preset A (owner decision)
96. **2026-11-11: `fit_mode = keep_shape` = per-point fit strength preset A** (docs/06 "keep_shape decision"; benchmark
    commit 4b6ffbe, round 5 variant 0): neck 1.0; shoulder x 0.5, y 1.0; armpit, chest, waist 0.3; hem x 0.3, y 0.5;
    sleeve cuffs 0.3, on the single-field rigid MLS warp, computed with the re-marked landmarks: `shoulder_*` at the
    sleeve seam, collar points present, chest pair not used when the chest is above the armpit (#94, #95).
    `adapt` = k 1.0 (unchanged). Rejected: shoulder_slope pair, alignment tweak and both (see "Rejected"). Engine
    wiring is a separate task (docs/04). The hem rule stays open (benchmark assumption, "Still open").

## Decided 2026-11-11: garment gender enforced in try-on
97. **2026-11-11: garment gender is enforced in try-on.** Base sex = the avatar's `sex`, or the own body's `sex` (new
    required field, chosen at upload; bodies created earlier have null and the UI asks once via `PATCH body/sex/`,
    never guessed; try-on refuses them with `BODY_SEX_REQUIRED`). Male base -> male + unisex garments, female base ->
    female + unisex; unisex always passes. `POST tryon/` returns 400 `GENDER_MISMATCH` otherwise. `GET garments/`
    takes `for_sex=male|female|all`; the catalog defaults to the avatar's / body's sex. Screen 10 lists only matching
    garments, with a "Barcha kiyimlarni koʻrsatish" toggle (mismatched ones then show "Boshqa jins uchun" and the
    try-on button explains why). **Garment size classes are NOT decided**: the stretch quality guard stays as is.

## Decided 2026-11-11: MLS engine behind a flag (method not yet decided)
98. **2026-11-11: flag `TRYON_WARP` added** (`parts` | `mls`, **default unchanged: `parts`**). `mls` runs the
    single-field MLS T-shirt warp (`apps/tryon_engine/mls.py`): keep_shape -> preset A (#96), adapt -> fitted MLS at
    k 1.0; it falls back to `parts` with quality warning `mls_fallback` when landmarks are incomplete or pair
    validation fails. **The warp method is NOT decided** (parts vs MLS stays the owner's choice); the hem rule is still
    the benchmark assumption ("Still open"). `POST tryon/` and the job result report the engine for debugging.

## Decided 2026-11-12: avatar photos in one low round-neck tank (owner decision)
99. **2026-11-12: all 6 avatars are re-shot as real photos in the same tank top with a low round (scoop) neckline**
    (neutral colour, e.g. grey; tight and thin, sleeveless or short-sleeved; shorts or tight leggings, as before). Under
    a V-neck the little tank that shows reads as an undershirt, so the avatar's own clothes are never painted over:
    the skin fill variants (`clear_skin`, `hole_skin`, docs/06 "V-neck opening") are NOT used. The V-neck direction is
    the neckline hole (`hole`) + `neck_clip` (benchmark, NOT production yet; the hole is an owner-drawn polygon per
    garment, `data/neck_hole/<id>.json`; how a hole gets marked in the product is still open). Same rule as the own-body
    path (docs/02 rule 12): the user's own top shows in the V. Real photos, not edited: no photo-editor lowering of the
    old tanks. Next: new photos -> `tools/avatar-prep` -> `seed_avatars --from /avatars` -> staff editor landmarks ->
    re-run the benchmarks (round 8b, neck); the regression fixtures in `testdata/` stay as frozen snapshots.

## Decided 2026-11-13: neckline = hole + polygon for every shape; collar floor default (owner decision)
100. **2026-11-13: collar floor is the MLS default** (`mls.collar_floor`, `tshirt_layer(collar_floor_on=True)`):
    the `neck_l` / `neck_r` targets (placed by the shoulder alignment only) are raised to 2 px
    (`COLLAR_FLOOR_MARGIN`) above the body's shoulder contour when they land below it (first background -> figure
    step under the neck row, in that column); never lowered, at most 40 px (`COLLAR_FLOOR_MAX`). Why: on #47 (square
    neck, collar only 32 garment px above its shoulder points) the collar landed 5-9 px below the contour and the
    avatar's tank strap and skin showed above the garment. Raised: #47 1.5-10.7 px, #28 0.3-9.8 px, #40 0 px. Only
    the MLS engine (`TRYON_WARP=mls`); the default `parts` engine is unchanged. The frozen fixtures (`testdata/mls_r7`,
    `mls_r10`) are compared with `collar_floor_on=False`.
101. **2026-11-13: the neckline opening is the owner-drawn polygon (`hole`) for every neck shape** (V #40, crew #28,
    square #47; docs/06 "Neckline hole for every shape"). Fabric left in the hole 0-6 px, band untouched. When a
    polygon exists the landmark triangle/curve (`clear`) is not used (it guesses a V on the square neck and leaves
    7.6-12.4 k px of fabric). **`neck_clip` is NOT used as built:** its box reaches the shoulder targets and clips the
    crew T-shirt's shoulder overhang (#28: 301-2043 px changed outside the neck zone, wavy shoulder line). Still open:
    who marks the polygon in the product (every uploader or staff only), its editor (proposal: start from the collar
    landmarks, user drags points) and server checks; the hole is still benchmark only (`neck_hole_polygon` keyword,
    `render_tryon` passes none).

## Decided 2026-11-13: neckline hole in the product (owner decision)
102. **2026-11-13: every garment owner marks the neckline hole** (not staff only), stored in the existing landmarks
    JSON as `landmarks.neck_hole.polygon` (no new model field, no new endpoint: PATCH garments/{id}/landmarks/).
    - **Editor = two steps for T-shirts** (docs/10 screen 9): step 1 `/garments/{id}/landmarks` = every point except
      the collar ("Keyingi", sends the full object, the stored collar / neck_hole are kept); step 2
      `/garments/{id}/neck` = the 3 collar points + the polygon, auto-zoomed to the top centre,
      "Oʻtkazib yuborish" keeps the r7 neckline. Pants: one step.
      **Suggestion (owner 2026-11-13, replaces the first V-triangle / curve version):** shape buttons **V | Dumaloq |
      Toʻrtburchak**, default guessed from collar depth / width (< 0.35 round, < 0.65 square, else V; #47 0.56 ->
      square, #40 0.82 -> V, crews 0.19 -> round). The hole follows the band's INNER edge (sides and bottom inset by
      6 % of the collar width, at least 3 px) and closes along the garment's top edge (alpha box top), so the inner
      back is inside it; square = straight sides with corners plus side / bottom handles. The hole is created ONCE
      (after the last collar point is released) and never moves by itself: moving the collar points does not touch it,
      a shape button or "Qayta tiklash" rebuilds it from the current points. Two edit modes, "Yoqa nuqtalari" /
      "Yoqa teshigi", so collar handles and polygon handles never steal each other's clicks (the first version put the
      polygon corners exactly on the collar points, which took the drag).
    - **Rules** (`landmark_checks.neck_hole_problem`, single source, also at render time): 3..64 finite points inside
      the image, no self-intersection, area > 0, area <= 25 % of the solid alpha (#47 square neck is 18.6 %), every
      vertex in the top 40 % of the alpha box height, up to 3 px above the box accepted. 400 `LANDMARKS_INVALID`.
    - `landmarks_complete` = the main set only; new `neck_complete` (collar + collar_bottom + polygon; null for pants).
      MLS still needs the collar points (`mls_ready`); without them it falls back to parts as before.
    - **Try-on:** `render_tryon` passes `neckline_variant="hole"` + the polygon to `mls.tshirt_layer` (never
      `neck_clip`, #101) only when `TRYON_WARP=mls`, `TRYON_NECK_HOLE=1` (new flag, default 1), the T-shirt is
      **adapt** and the polygon passes the rules; a failing polygon is skipped with quality warning
      `neck_hole_invalid` (no fallback to parts). **keep_shape garments and the `parts` engine ignore the polygon**
      (0 px, tested on #28, #40, #43, #44, #45, #47 x 6 avatars). Job result: `neck_hole: {garment id: bool}`.
    - Measured (production path, `run_tryon_neck.py`): #40 with `40-2.json` fabric left in the hole 1-4 px, band
      0 px, outside the neck zone 0 px; #47 3-6 px; #28 0 px (only 6-91 px change: r7 already cleared most of it).
    (keep_shape: see #103.)

## Decided 2026-11-13: neckline hole for keep_shape too (owner decision)
103. **2026-11-13: a keep_shape T-shirt with a valid polygon gets the hole as well** (supersedes the keep_shape
    exclusion in #102). Diagnosis: `warp._neck_hole_kwargs` returned {} for every fit_mode but adapt, so #45
    (keep_shape, valid 16-point polygon) rendered the r7 neckline (job 241 `neck_hole: false`, job 242 after a switch to
    adapt `true`). The engine needs no change: `mls.tshirt_layer(keep_shape, hole)` on #45 / avatar 2 left 1 px of
    fabric in the hole (3000 before), 0 px outside the neck zone. Without a polygon keep_shape stays pixel-identical
    (#44, #45 x 6 avatars against the pre-wiring export); `parts` and `TRYON_NECK_HOLE=0` still ignore the polygon.
    Tests (#28, #40, #47 x 6 avatars x adapt + keep_shape): fabric left <= 5 px (#40) / 6 px (#28, #47); band 0 px off
    the hole; on the hole's antialiased edge 0 px for #40 adapt and <= 4 px elsewhere (pixels already partly
    transparent, alpha 129-199, at w 0.28-0.49, which alpha x (1 - w) takes under 128; measured 1-4 px).

## Decided 2026-11-13: MLS sleeve variant C in production (owner decision)
104. **2026-11-13: the MLS engine uses sleeve variant C** (round 8 / 8b: B's mid-sleeve pairs at the deltoid edge +
    `cuff_mid`, docs/06), new setting `TRYON_MLS_SLEEVE` (`r7 | A | B | C`, default `C`, invalid value stops startup),
    passed by `render_tryon` as `sleeve_variant`. Adapt garments only: keep_shape output is unchanged (C and r7 give the
    same layer there, tested). The shoulder line of round 9 / 9b is **not** used (stays a benchmark keyword, default
    off). `mls.tshirt_layer`'s own default stays `r7` so the frozen fixtures keep their meaning; the neck-hole fixture
    tests pin `mls_sleeve="r7"`. Only with `TRYON_WARP=mls`; the default engine is still `parts` (#98, not decided).

## Decided 2026-11-15: MLS is the default T-shirt engine; adapt config in production (owner decision)
105. **2026-11-15: `TRYON_WARP` defaults to `mls`** (settings, docker-compose, `.env.example`; `parts` stays
    selectable and is still the engine for pants and the fallback behind `mls_fallback`). This closes "parts vs MLS"
    (#98). **Adapt T-shirts on MLS are rendered with the config of benchmark rounds 11-14** (docs/06): sleeve C (#104)
    + tube sleeves "finished" (round 13b) + armpit mode r14 (round 14) + side floor "mask" (round 12 / 12b) + garment
    hem (round 12b). keep_shape garments are called exactly as before (0 px on #44, #45). Flags, each off value =
    the behaviour before this change, an invalid value stops startup: `TRYON_MLS_TUBE` (1 | 0), `TRYON_MLS_SIDE_FLOOR`
    (mask | off), `TRYON_MLS_ARMPIT` (r14 | off), `TRYON_MLS_HEM` (garment | mls = no hem post-processing);
    `TRYON_MLS_SLEEVE` unchanged. r14 needs the tube and the side floor: with either off the armpit mode is off (owner
    OK), reported in the job result. A tube that cannot be built on a side: the whole T-shirt is rendered with MLS
    sleeves, quality warning `tube_fallback` (Uzbek message in the locale file). Job result: `tshirt_config` per
    T-shirt (what was actually used), `render_ms` (docs/04, `types.ts`). `render_tryon`'s own defaults stay the off
    values (direct calls and the frozen fixtures keep their meaning); the settings switch the config on.
    **Round 13c is deleted** (`armpit_mode="r13c"`, `armpit_zone`, `_widen_inner`, `_inpaint_armpit`, its tests and
    runner). Gates passed: production layer = the benchmark call, 0 px, #28 / #43 / #40 x 6 avatars (DB data:
    `tools/tryon_check/prod_vs_bench.py`; fixture: `ProductionTshirtConfigTests`); keep_shape #44 / #45 x 6 = 0 px; all
    flags off = the previous production call, each single flag off = the benchmark call without that keyword; 369
    backend tests, 78 vitest, tsc. Check through the real `POST tryon/` path: `tools/tryon_check/post_path.py`
    (21 renders; #28 on female avatars and #43 / #40 on male avatars are refused by the gender rule #97).
    **Known issues, recorded, not blockers (owner 2026-11-15):** (1) the round 14 gate fails on 8 of 18 benchmark
    runs: arm skin 2.5-5.8 px above the nominal cuff line under the garment's curved cuff on #43 (6 runs) and #40
    m-plus, 1 px on #40 m-slim (docs/06 "Armpit wedge, round 14"); (2) render time of an adapt T-shirt about 1.0-1.5 s
    (before: about 0.15 s), to optimize later, likely the "mask" last guard's comparison layer; (3) a stepped torso
    edge (2-5 px) beside the gap below the armpit on #28; (4) demo-mode results were built with `parts` and are
    stale (owner: do not rebuild now). Still open: the hem rule (#91, proposed).
106. **2026-11-15: the cuff hem (round 15) and the tube fringe drop (round 16) are in production** (owner: "deploy
     everything to prod", after the round 15 sheets). Adapt T-shirts with tube sleeves get `cuff_mode="hem"` +
     `tube_fringe="drop"` through `render_tryon` (`warp._mls_adapt_kwargs`). Settings (first value = default, second =
     the behaviour before #106; an invalid value stops startup): `TRYON_MLS_CUFF` (hem | chord), `TRYON_MLS_FRINGE`
     (drop | keep). Both need the tube: with `TRYON_MLS_TUBE=0` or after a `tube_fallback` they are `chord` / `keep`
     and `tshirt_config` says so (new fields `cuff`, `fringe`; docs/04, `types.ts`). keep_shape ignores both.
     `render_tryon`'s own defaults stay the off values. Gates: benchmark round 15 0 / 18 (before 8 / 18), round 16
     0 / 18; production layer = the benchmark call 0 px on #28 / #43 / #40 x 6 avatars and keep_shape #44 / #45 x 6
     = 0 px (`tools/tryon_check/prod_vs_bench.py`, `ProductionTshirtConfigTests`); each flag off = the benchmark call
     without that keyword; 379 backend tests, 78 vitest, tsc. This closes known issue (1) of #105 (cuff slivers).
     **Recorded, not blockers:** the cuff edge is a straight cut 2 body px inside the garment's hem (a curved hem is
     drawn straight); the lower half of the sleeve is stretched by the hem rise (up to 8.8 px on #40); render time of
     an adapt T-shirt 1.08-1.46 s (mean 1.24); the stepped torso edge on #28, the r14 skip on older landmarks, the
     stale demo results and the hem rule (#91) are unchanged.
107. **2026-11-16: the round 17 finish is in production, T-shirts only** (owner: "r17, wire it into production",
     then "wire t-shirts only now"; docs/06 "Finish pass, round 17" + "Production wiring of the round 17 finish").
     Setting `TRYON_FINISH` (r17 | off, default r17; an invalid value stops startup). r17 = smooth anti-aliased
     edge with nothing eroded (`warp.smooth_edges`) + form shading from the garment's outline
     (`warp.form_shading_map`, the avatar is not read) + contact shadow, also on the arm under the cuff; T-shirt
     layer only, every engine and fit mode. With r17 the flags `TRYON_SHADING` / `TRYON_CONTACT_SHADOW` /
     `TRYON_EDGE_FEATHER` are not read; off = the behaviour before #107 (those three flags decide, default 0). Job
     result field `finish` (r17 | off; docs/04, `types.ts`). Gates: production image = the benchmark r17 call 0 px
     and `TRYON_FINISH=off` = the off call 0 px on 30 renders (#28, #43, #40, #44, #45 x 6 avatars), new holes
     0 / 30; 389 backend tests, 78 vitest, tsc. **Pants are not touched** (only one pair, #18, in the DB): their
     own round after the owner uploads 2-4 pants (tight / loose, dark / light, optionally shorts). The old realism
     effects (#60, r60) stay available with `TRYON_FINISH=off`; they fail the no-new-holes gate (516-1319 px per
     render). Demo results not rebuilt.
108. **2026-11-16: the round 17 finish is in production for pants too** (owner: "yes, wire r17 for pants too",
     plan approved; docs/06 "Finish pass on pants, round 17b", "Finish pass on outfits, round 17c", "Production
     wiring of the finish on pants"). Setting `TRYON_FINISH_PANTS` (1 | 0, default 1; needs `TRYON_FINISH=r17`;
     0 = T-shirts only, the behaviour of #107). Job result `finish` = r17 when any garment got it. Benchmarks:
     pants #18, #48, #49, #51 x 6 avatars and 5 T-shirt + pants outfits x 6 avatars: new holes 0, gates 0 fails.
     Production gates: production image = the benchmark call 0 px (30 outfits, 24 pants alone, 30 T-shirts alone);
     `TRYON_FINISH_PANTS=0` = the #107 output 0 px; `TRYON_FINISH=off` = the output before #107 0 px. 390 backend
     tests, 78 vitest, tsc. This replaces "pants are not touched" of #107. Recorded: the owner's pants #48, #49,
     #51 are stored as `unisex` (the owner described #48 / #49 as for girls, #51 as for men); shorts and
     white / black pants are not measured; demo results not rebuilt.
109. **2026-11-16: an adapt MLS T-shirt hangs over the pants** (round 18; owner approved the two-session finish
     plan, item "pants show beside the T-shirt"; docs/06 "Pants under the T-shirt, round 18"). Setting
     `TRYON_PANTS_TUCK` (1 | 0, default 1; 0 = the behaviour before #109). `warp.drape_over_pants`: on rows where
     the pants are wider than the T-shirt, each half of the T-shirt row is stretched about the axis until it covers
     the pants (+ 2 px, at most 1.35 x, smoothed along y, held down to the hem); `warp.tuck_pants`: pants px still
     beside the T-shirt above its hem are dropped unless they lie within 3 px of the figure. keep_shape T-shirts and
     the `parts` engine are not touched. Measured (5 outfits x 6 avatars, `run_tuck18.py`): pants px beside the
     T-shirt #28 + #51 25573 -> 1273, #43 + #48 19121 -> 2618, #40 + #49 12349 -> 2468; keep_shape #44 + #18 and
     #45 + #51 unchanged; figure px uncovered 0 / 30. Tests `PantsTuckTests` (4). Not in the job result.
110. **2026-11-16: own-body path and avatar path work end to end; submission runs without prompt 02** (owner
     approved the two-session finish plan: "roziman"). Deadline: the project is handed in on 2026-11-17.
     - **Body upload job** (`run_body_validation`): the shared pipeline `process_body_photo` now runs on the upload
       (EXIF strip, rembg, code checks, 600x1200, auto landmarks) before any AI step; a code-check rejection
       (`NO_PERSON`, `HEAD_OR_FEET_CUT`, `FIGURE_CLIPPED`, `CORRUPT_FILE`) fails the job with its Uzbek message and
       deletes the body; on success the normalized PNG + landmarks replace the original and the original file is
       deleted. Job result adds `warnings`.
     - **Confirm** (`POST body/confirm/`): `validate_body_landmarks` (400 `LANDMARKS_INVALID`) and
       `complete_body_landmarks`, as the staff avatar editor. `BodyConfirm.tsx` is the `LandmarkEditor` with the body
       groups and sends the edited landmarks.
     - **Upload over an unconfirmed body replaces it** (#33 was not implemented: it returned 409); a confirmed body
       still gives 409 `BODY_EXISTS`.
     - **Avatar path:** `GET avatars/nearest/` requires `sex` + shoulder, chest, waist, hip (400 `SEX_REQUIRED`,
       `MEASUREMENTS_REQUIRED` with `fields`); the try-on page asks for them and shows the avatar list only after a
       match. Landmarks are not adjusted to the measurements (not done).
     - **Prompt 02 (body AI check) is NOT wired** (`_ask_body_validation` returns None). Owner decision for the
       submission: run with `AI_DEV_BYPASS=1` + `BODY_AI_CHECK_ENABLED=0` (set in the local `.env`), say so in the
       README. Adults-only therefore rests on the "I am 18+" confirmation only. The daily AI limit for bodies is
       not exercised.
     - Hem rule (#91): the owner accepted the current default (`TRYON_HEM_RULE=1`) for the submission.
     - Check: `tools/tryon_check/own_body_path.py` (real API + worker, temporary user): 17 checks ok. 401 backend
       tests, 78 vitest, tsc.
     - Cut for the submission (known limits): engine rounds (side line, armpit fold, #48 hem, keep_shape shoulder,
       render time), prompts 02 / 04 / 05, public garments + moderation, explicit `POST outfits/` (an outfit is
       stored by every try-on).
111. **2026-11-16, session 2: the project is shown as a live demo on the owner's machine** (owner: "jonli demo").
     - A garment's original photo is deleted as soon as the cleaned image is stored (`run_garment_cleaning`;
       there is no Save / Cancel preview, so nothing needs it afterwards). `original_preview_url` is then null.
     - Frontend: nav = Bosh sahifa, Tana, Kiyimlar, Kiyib koʻrish, Obrazlar, Profil (design); new pages `/body`
       (`BodyHome`) and `/profile` (`Profile`, screen 12: privacy, delete body, delete account); home page per
       screen 2 (body card, newest garments, newest outfits, all from the API); emojis removed; new texts in
       `locale/uz.ts` (`NAV`, `BODY_TEXT`, `PROFILE_TEXT`, `HOME`).
     - Demo results rebuilt with the current engine (18; the demo T-shirt has the old landmark set and falls back
       to `parts`). `DEMO_MODE` stays 0 for the live demo.
     - README: "Live demo" walk-through and the known-limits list. `own_body_path.py`: 21 checks ok (also a garment
       upload). 401 backend tests, 78 vitest, tsc. The new pages were not opened in a browser by Claude.
112. **2026-11-16: keep_shape T-shirts are scaled to fit the body** (round 19; owner: "start with direction 1, fix
     the scale", after the keep_shape report). Setting `TRYON_MLS_KEEP_SCALE` (fit | shoulder, default fit;
     shoulder = before #112); `tshirt_config.keep_scale` = "fit" when used. Before: scale = body / garment shoulder
     width, so a dropped-shoulder T-shirt was shrunk until its seams sat on the shoulder points. Now
     `mls.keep_shape_scale` = the largest of the shoulder scale, the length scale (garment shoulder..hem = body
     shoulder..hem row) and the width scales (garment chest / waist / hem >= 1.04 x body chest / waist / hip), at
     most 1.45 x the shoulder scale; the collar stays where the shoulder scale puts it (`keep_shape_drop`) and the
     shoulder pair keeps its aligned y (the seam hangs lower instead of being pinned to the shoulder row).
     Numbers and what got worse: docs/06 "keep_shape scale, round 19". adapt is not touched; the regression
     fixtures are pinned to "shoulder". 402 backend tests.
113. **2026-11-16: tube sleeves end on the arm/torso boundary** (round 20; owner: "the task now is the sleeves,
     they are in a very bad state"). Setting `TRYON_MLS_TUBE_CLIP` (arm | armhole, default arm; armhole = before
     #113); `tshirt_config.tube_clip` = "arm" when used. Cause found: the tube's domain was clipped by the body
     armhole line (shoulder target -> armpit target) EXTENDED below the armpit; on short cap sleeves whose cuff
     row lies where the arm still touches the torso, the tube's inner half was drawn over the chest as a
     sharp-edged triangle (#43, #47, #40, #28, #45 as adapt). Now, below the armpit row, a tube px on the torso
     side of `arm_torso_boundary` (+ 2 px; the crease column below the crease) is not drawn where the MLS layer
     underneath has solid fabric. Measured (5 garments x 6 avatars, `run_clip20.py`): 18588 tube px clipped, new
     holes 0 / 30, px changed outside the sleeve band 0. 402 backend tests.
     **Not fixed in the sleeves:** the pinched cuff of #40, a dark dot at the armpit crease, skin at the top of
     the shoulder on #47, ragged cuff px on #45, and keep_shape sleeves (no tube: they stand out sideways).
114. **2026-11-16: the pants engine is rebuilt** (round 21; owner: "redo the pants fitting from scratch: after
     the waist it gets far too wide, at the knees the pants lose their shape and stick to the body; fix every
     pants problem"). Setting `TRYON_PANTS_ENGINE` (fit | rows, default fit; rows = `warp_pants` before #114).
     Causes found in "rows": (1) every row was `max(garment, body)` on its own, so the outline followed the body
     wherever the body was wider and the garment elsewhere (kinks, a flare lost); (2) the loose-leg "hang" centre
     plus "the body leg is always covered" widened a leg to 1.3-2.4 x on a legs-apart stance; (3) the leg left
     the hip block only by the knee; (4) a hem slit split the leg into two runs and only one was drawn.
     `warp.warp_pants_fit`: the garment's own outline x a smooth width factor (`fx` for the hip block, per leg
     `_pants_leg_profile` = the smooth upper envelope of what the body needs, 1 where the garment is loose); each
     leg hangs straight from its half of the hip block and moves only as far as the body leg pushes it; the legs
     meet on the crotch axis (2 px overlap); the crotch is never above the body's; both runs of a slit hem belong
     to the leg (`_leg_span`); the body leg + 3 px and the torso run are always covered.
     Numbers: docs/06 "Pants fit, round 21". Pants worn with a T-shirt: `run_tuck18.py` gate 0 / 30.
     **Not fixed:** a grey fringe at the crotch notch of #49 (in the garment cutout), a small bump on the inner
     edge at the knee of wide legs where the body knee pushes (#18), the hip bump on plus bodies with slim jeans
     (#48 needs 1.73 x, limit 1.7, warning), shorts are not measured, the hem stays horizontal on a tilted leg.
115. **2026-11-16: the leftovers of the pants engine are fixed** (round 22; owner: "fix what is not fixed, reduce
     the folds further if possible"). All in `warp_pants_fit` (setting `TRYON_PANTS_ENGINE=fit`), no new setting:
     - **Crotch fringe** (#49 grey line): `clean_crotch_gap` on the cutout before the warp: in the polygon between
       the legs (crotch -> inner knee and hem points, grown 1.2 %), px nearer the photo background than the fabric
       are made transparent when they belong to a thin component (<= 2 x 12 px) that touches the transparent
       background; a print, an embroidery or a seam line inside the fabric stays. Skipped when fabric and
       background are alike (contrast < 30). Cleared: #18 57, #48 1178, #49 3900, #51 1240 px (garment px).
     - **Knee bump** (#18): the leg edges are smoothed outward only (`_smooth_outward`, the inner edge twice as
       much): never inside the computed edge, so the body leg stays covered without the kink of a hard limit.
     - **Hip bulge on plus bodies**: the leg's width factor leaves the hip factor more slowly when it is large
       (blur `PANTS_FIT_SIGMA + 20 x (fx - 1)` rows).
     - **Hem on a leaning leg** (`_tilt_hem`): below the knee the content is moved DOWN towards the side the leg
       leans away from, so the hem stays square to the leg; nothing moves up (nothing uncovered); 0 below a
       2 % lean. Drop 2.3-15.5 px on the legs that lean.
     - **Gap between the legs** stays open: `garment_layer`'s hole filling no longer paints over it where the
       legs touch again lower down (#18 smeared a patch into the gap).
     Gates (`run_pants21.py`, `run_tuck18.py`): new holes 0 on #18, #49, #51; #48 223 px (its own hem slit, as in
     #114); with a T-shirt 0 / 30. Tests: `test_smooth_outward_never_comes_inside_the_edge`,
     `test_clean_crotch_gap_clears_background_between_the_legs_only`, `test_tilt_hem_only_moves_content_down`.
     **Still open:** slim jeans on the plus woman need 1.75 x the garment width (limit 1.7, warning); shorts are
     not measured.
116. **2026-11-19: pants are rendered with `rows` again** (owner, after comparing rows / fit, alone and with a
     T-shirt, on avatar 4 with T-shirt #43 + pants #49: "rows + T eng yaxshi chiqqani ekan, o'shani prodga").
     Setting `TRYON_PANTS_ENGINE` default `rows` (= `warp.warp_pants`, the engine before #114); `fit`
     (`warp_pants_fit`, rounds 21-22, #114, #115) stays in the code behind the setting, unchanged. Every pants
     render is affected (alone and with a T-shirt). Trade-off the owner accepted: the #114 / #115 gains are off
     by default (round 21: render warnings 33 vs 1 on 24 renders; #48 hem slit, crotch fringe clean-up, knee bump
     smoothing, hem on a leaning leg). Found on the way: the Celery worker does not reload code; after an engine
     change run `docker compose restart worker` (results made before the restart keep the old look).
117. **2026-11-19: rows pants without the per-row bumps** (**superseded by #118 the same day: `smooth` and
     `TRYON_PANTS_SMOOTH` removed from the code**; round 23; owner chose option A: "keep rows, replace the
     per-row widening at the hips with one smooth factor"). Cause (pants #49, 6 avatars): the uniform scale s comes
     from the length, so only the slim woman (#4) has body hip / garment hip x s = 0.99; on the others it is
     1.06-1.43 and `pants_width` widens each row to "garment or body, whichever is wider": a bump and a bend at the
     hips (#3, #6 warnings 1.30-1.50x). `warp_pants(smooth=True)`: one factor fx for the hip block (largest
     body / garment ratio over the hip rows and the top PANTS_FIT_TOP of the thighs, max PANTS_FIT_MAX) and down
     each leg `_pants_leg_profile` (the same profile as `fit`); a row that needs more than 1.7x still covers the
     body. Centring, hang, hem, finish and tuck as in rows. Setting `TRYON_PANTS_SMOOTH` (0 | 1, **default 0**
     until the owner reviews), render keyword `pants_smooth`; ignored with `TRYON_PANTS_ENGINE=fit`.
     Gates (`tools/warp-benchmark/run_smooth23.py`, 4 pants x 6 avatars, alone and with T-shirt #43): off = HEAD
     0 px (48 renders); new holes 0 on #18, #49, #51; #48 5 px (1-2 px of its own hem slit moved sideways, as in
     #114). Outward step under the crotch (max px): #18 6 -> 5, #48 8 -> 4, #49 6 -> 4, #51 5 -> 5. fx mean:
     #18 1.44, #48 1.43, #49 1.26, #51 1.10. Pants "distorted" warnings rise a little (#18 11 -> 13, #48 14 -> 17,
     #49 4 -> 6): the whole hip block is wider than the uniform scale, not only the bump rows.
     **Not changed:** legs that bend towards the body's knees (#1, #6 with #49) come from the centre line, not
     the width. Test: `test_rows_pants_smooth_covers_the_legs_and_is_off_by_default`.
118. (**Replaced by #120: `fit_x`, the underlay and `TRYON_PANTS_HANG` removed.**) **2026-11-19: rows pants get one horizontal scale (`fit_x`), in production** (round 24; owner: "smooth hal
     bo'lmagan" -> options A-D -> "Adan foydalanamiz, prodga implement qil"). Cause of the bumps: s comes from the
     length only, so the scaled garment is narrower than the hips on 5 of 6 avatars (body / garment x s at the hip
     1.06-1.43 on #49; only #4 0.99) and the rows engine patched each row. Check D first: garment landmarks are
     within ~1-5 canvas px, but avatar hip ticks are 2.5-11.5 px off the silhouette (#1 11.5 / 7.5, #6 knees up to
     17.5), so the width is measured on the figure mask, not on the landmarks.
     - `warp_pants(fit_x=True)`: one horizontal scale sx for the whole garment (waist block and both legs) = the
       largest mask / garment width ratio over the hip rows and the top PANTS_FIT_TOP of the thighs, at least s,
       at most 1.7 x s. Vertical scale, centring, hem, waistband, finish, tuck unchanged. Rows that still need more
       cover the body as before. "distorted" warnings are measured against sx.
     - Under each leg the leg without fit_x (its width and centre line) is drawn on the figure only: a hem slit
       widened by sx (#48) never shows more body than before. The waistband curve keeps the top row of the widths
       without fit_x (same dip).
     - Setting `TRYON_PANTS_FIT_X` (1 | 0, **default 1**), render keyword `pants_fit_x`; ignored with
       `TRYON_PANTS_ENGINE=fit`. B = `TRYON_PANTS_HANG` / `pants_hang` (loose legs hang straight from the hip
       block) stays in the code, **default 0, not used**: legs straighter (#18 centre-line deviation 10.5 -> 4.1 px
       on #3, 5.1 -> 0.4 on #5) but a new step under the hip (#18 6 -> 13 px, #51 5 -> 12) and #48 slit holes.
     Gates (`tools/warp-benchmark/run_fitx24.py`, 4 pants x 6 avatars, alone and with T-shirt #43): off = HEAD 0 px
     (48 renders), new holes 0 / 48. A vs off: pants warnings #48 14 -> 5, #49 4 -> 0, #51 4 -> 1, #18 11 -> 11;
     hip step (max px) #48 8 -> 1, #49 6 -> 4; sx / s mean #18 1.44, #48 1.48, #49 1.26, #51 1.10.
     Sheets: `tools/warp-benchmark/out/sheet_fitx24_<id>.png` (per avatar: off | A).
     **Still open:** wide legs still follow the body's knees a little (B is the start); the plus bodies get
     visibly wider pants (that is the intent: a larger size).
119. **2026-11-19: the T-shirt drape over the pants stops near the figure, in production** (belly "bulge" of an
     adapt T-shirt over pants). `drape_over_pants(mask, body_margin)` + `_drape_body_cap`: a drape row reaches at
     most max(its MLS edge, the figure edge + margin), the limit smoothed along y. Setting
     `TRYON_DRAPE_BODY_MARGIN` (px, **default 6** | `off` = before #119), render keyword `drape_body_margin`. Belly
     overhang 35-85 px -> 13-21 px (5 outfits x 6 avatars, `tools/tryon_check/belly_overlay.py`). Tests
     `PantsTuckTests` (5 new).
120. **2026-11-20: rows pants rewritten (round 26), in production, no new setting** (owner task: belly bulge,
     edge pixels, centre seam on #49 + female avatars; "do not stack patches, delete what you replace"). Full rules
     and measurements: docs/06 "Pants fit, round 26".
     - **Replaced / removed:** #59 (waistband blend to the garment's hip width, `pants_width` below the hip for
       pants), #60 pants hang, #61 / #62 (loose-leg centreline, looseness: `leg_centerline`, `pants_looseness`,
       `LOOSE_KNEE_PULL`, `HANG_LOOSE`), #70 (each leg row = the garment's own span: legs are now monotonic), #118
       (`fit_x`, its hem-slit underlay, `hang_straight`; settings `TRYON_PANTS_FIT_X`, `TRYON_PANTS_HANG` and
       `render_tryon(pants_fit_x=, pants_hang=)` deleted), round 25 (`pants_top`, variants A-E, `run_top25.py`) and
       `run_fitx24.py`. Pants no longer use `_tail_rows` or the pre-warp `remove_halo`. `pants_width` /
       `waist_blend_width` / `LOOSE_FROM` stay for the parts T-shirt only.
     - **New model (`warp_pants`, engine `rows`):** rise -> rise and crotch -> ankle vertical maps; waist -> body
       crotch = one piece, figure run + 3 %, in two halves meeting on the axis at the garment's crotch x; legs only
       below the body crotch: body leg + 3 % opening to own width x s over the first 20 % of crotch -> knee, cap
       1.8 x (knee below the knee), inner edge out of the garment's own leg gap, edges monotonic and smooth,
       leaving the block without a step; hem = the leg's own last row on the ankle line; geometric outline alpha;
       `pants_edge` after the warp (no erosion, 3 px ring from the plain fabric); `clean_crotch_gap` for both engines.
     - **Numbers** (24 pants renders): block past the figure 30-52 k px per pants -> 7.6 k (largest row 49-93 ->
       10 px, waistband corners 9-25 -> 4-8 px); axis jump in the leg band 10-240x -> none (block 0.8-4.8, #48 = its
       fly seam); print share in the warped edge ring #18 0.16 -> 0.02; pants above the waist 0.
     - **Gates:** new holes 20 px / 54 renders (18 px #47 + #51 avatar 4: background pocket under #47's hem corner;
       1 px gap between the legs); uncovered above the new hem 0-383 px per render (#48 hem slit 240-348); below the
       hem 343-2 853 px (length rule: hem on the ankle line). Tests (a)-(f) `PantsFitModelTests` + `pants_edge` test.
     - **Still open (owner):** #48's hem slit now shows the leg (keep it open as the garment's own slit, or close
       it? **owner 2026-11-20: decide later**); long pants no longer cover the shoe top; joggers / balloon cuffs no longer taper (monotonic legs); a
       1-3 px step can remain where a leg's outer edge leaves the block on avatar 5; the 18 px pocket under #47.
       #119 (drape body margin) is still to be written up (HANDOFF).
121. **2026-11-20: keep_shape T-shirts: the collar off the neck, shoulders bound to the body, in production** (owner
     task: #44 / #45 collar far above the neck base; owner answers: the neck-base row = where regular T-shirts put
     it; anchor = the collar line, T = 0.25; then "variant 1, bind the shoulders to the body"). keep_shape only, no
     setting: `mls.keep_neck_dy` + `keep_neck_pairs` (all MLS targets down by dy, shoulder targets' y = body
     shoulder row), `tshirt_layer(keep_neck=True)` from render_tryon, `tshirt_config.keep_neck_dy` (API type
     updated). Lifts for keep_shape: #112's "the collar stays where the shoulder scale puts it" and its "the seam
     hangs" (shoulder k_y 0) - the shoulder y is bound again. adapt, pants, parts and the frozen fixtures unchanged.
     #44: dy 24-34 px, neck px covered 1377-2868 -> 13-293, bare-shoulder px 0-15 -> 174-335 (regular crews 20-1411),
     new holes 0. #45 (re-marked, adapt): dy 0-3. Details: docs/06 "keep_shape decision".
123. **2026-11-23: pants cutout kept the photo background between the legs (black wedge), fixed in the cutout step**
     (garment 76, white wide-leg pants on a black photo). Root cause: the rembg model mask itself, not our post-processing:
     `u2net` kept 51 277 and `isnet-general-use` 133 317 opaque black px (wedge below the crotch, open to the outside, so
     `fill_alpha_holes` / the external-contour fill never touched it). The stored RGB was already the original photo.
     Fix (`apps/jobs/tasks.py`, pants only): `clear_background_between_legs(rgb, mask)` lowers alpha for px nearer the
     background colour than the fabric, only in the gap columns, only when connected to the outside background and only when
     the fabric/background contrast is clear (a black print on the fabric is kept; near-black pants on black: untouched);
     soft edge of 3 px (kernel 7 x 7 dilate = within 3 px each side), nothing is filled. Result on the real image: opaque
     black px 133 317 -> 14 (`isnet-general-use`), 51 277 -> 6 251 (`u2net`, the rest is the thin outer edge outline, left
     to `remove_halo`); white fabric lost 0 px. Settings: `REMBG_MODEL` (default `isnet-general-use`, `birefnet-general` |
     `u2net`; one cached session per process), `GARMENT_MASK_DEBUG_DIR` (DEBUG only: raw + final mask PNGs, off by default).
     T-shirt cutout unchanged. 422 backend tests (new: `apps/jobs/tests_leg_gap.py`). Open: `birefnet-general` not measured
     (about 1 GB download); garments cut out before this change keep their black wedge until re-uploaded.
124. **2026-11-23: model (avatar) picker is gender-only in the frontend** (owner; may bring measurements back much later).
     The 4 measurement inputs, their validation and the "Mos modelni topish" button are removed from `pages/TryOn.tsx`;
     choosing Erkak/Ayol selects that sex's `average` avatar from the loaded `GET /api/avatars/` (any avatar of that sex if
     none, else the inline error "Bu jins uchun model topilmadi."). Nothing is selected until the click. Removed on the
     frontend only: `nearestAvatar`, `NearestAvatarQuery`. Backend `avatars/nearest/`, `Avatar.measurements` and the
     serializers are unchanged (supersedes the "required" part of rule 20 / #110). Added a minimal `frontend/.eslintrc.cjs`
     (`npm run lint` now runs and passes; `no-explicit-any` off in `*.test.ts`). Checks: tsc clean, 78 vitest, lint clean,
     `POST /api/tryon/` with avatar 2 (male) and 5 (female) -> job done, result image saved.
