# 09. Decisions log and remaining open questions

## Decided by the owner (do not ask again)
1. **Garment real size: NOT entered.** The garment always adapts (is deformed) to the body. No size-mismatch display.
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
59. **Pants keep their own silhouette** (2026-11-10, docs/06 "Pants fit"): one uniform scale (waist..hem vs waist..ankle,
    rise for short pants); only the waistband fits the body (+4 % ease), blended to the garment's width by the hip; below
    the hip a row is max(garment, body + 4 %), capped at 1.8x body (knee width below the knee, so cuffs are not
    squeezed); legs centred on the body's leg centreline. Warnings only when a row's scale differs from the uniform
    scale by > 1.3x. T-shirt keeps the old "widths follow the body" model for now.
60. **Realism pass** (2026-11-10, docs/06 "Realism pass"): shading from the avatar's luminance (strength 0.7), 1 px
    rim removal + feather, 0.25 contact shadow on the figure, loose pants hang half way to a vertical drop, curved
    waistband top. Pure 2D post-processing of the warped garment; nothing of the avatar is redrawn.
61. **Loose pants do not bend at the knee** (2026-11-10, docs/06 "Loose-leg centreline"): loose legs (knee ratio
    >= 1.15x) use a smooth monotonic centreline with at most 25 % knee pull; tight legs keep the knee line. Loose/tight
    and the hang weight are decided per leg, not per row.
62. **Looseness per garment, smooth** (2026-11-10, replaces the per-leg cut of #61): mean knee ratio of both legs,
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
