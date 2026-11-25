# 04. Data model and API contract

Stack (confirmed): React + TypeScript; Django + DRF; PostgreSQL; Celery + Redis (AI jobs); Docker Compose;
OpenCV + rembg; Google Gemini API (Nano Banana 2). Auth: email + password. MVP storage: local media volume
behind signed URLs (assumption; S3-compatible later).

## Models
- **User**: email, password, is_adult_confirmed
- **Body**: user (OneToOne, unique), normalized image, sex (male|female; required at upload, null only on bodies created
  before 2026-11-11: the UI asks once via `PATCH body/sex/`, never guessed), landmarks (JSON), height_cm (nullable),
  measurements (JSON, optional), measurements_changed_at, confirmed_at (null until confirmed), created_at. Photo/landmarks immutable after confirmed_at.
  The original upload is deleted after normalization.
- **Avatar**: sex, build (slim|average|plus), image, landmarks (JSON), measurements (JSON, circumference cm), height_cm
  (nominal, nullable), landmarks_confirmed_at (null = auto-detected; set by the staff editor). Seeded by command or uploaded by staff.
- **Garment**: owner (FK, null for admin catalog), type (`tshirt` | `pants`), image (cleaned transparent PNG),
  landmarks (JSON), visibility (private|public), status (pending|approved|review|hidden),
  fit_mode (adapt|keep_shape, default adapt), gender (female|male|unisex, default unisex), created_at,
  sizes (JSON, nullable: real flat-lay cm, docs/11 + docs/09 #125; required keys tshirt `chest_width, length, shoulder_width`,
  pants `waist_width, hip_width, inseam`; optional tshirt `waist_width, sleeve_length`, pants `thigh_width, leg_opening`;
  null only for rows made before the fit check), stretch (bool, default false).
  Engine mapping (docs/09 #96): `adapt` = full fit (k 1.0); `keep_shape` = MLS per-point fit strength preset A
  (docs/06 "keep_shape decision"). Wired behind `TRYON_WARP` (docs/09 #98): `mls` applies preset A to T-shirts,
  the default `parts` warps keep_shape like adapt. Pants: keep_shape = adapt on both engines.
  No image update. The original upload is deleted after cleaning. No garment real-size field.
- **Outfit**: owner, body (FK) or avatar (FK), garments (M2M), result_image, realistic_image (nullable), created_at
- **Report**: garment, reporter, reason; unique (garment, reporter)
- **Job**: user, kind (body_validation | garment_clean | moderation | realistic), status (queued|running|done|failed), result/error code, ai_called, ai_called_at, ai_outcome (""|responded|invalid|unavailable;
  daily limit, docs/09 #29), created_at. `garment_clean` result: `{cleaned, ai_skipped, ai_cached}`

## API contract (implemented, 2026-11-09)
This section is the contract. The frontend mirror is `frontend/src/api/types.ts`; the Django views and
serializers implement it. **Change all three in the same commit.**

General rules
- Base path `/api/`. Every path ends with a slash. Auth: `Authorization: Bearer <access>` (JWT) on everything except register/login/refresh.
- JSON bodies, except uploads (multipart). Image fields are short-lived signed URLs (`/api/media/signed/...`).
- Errors we produce: `{code, detail}` (`detail` is the Uzbek message). DRF validation errors: `{field: [messages]}`.
- Another user's private object always returns **404**, never 403.

| Method | Path | Request | Response |
|---|---|---|---|
| POST | auth/register/ | `{email, password, is_adult_confirmed}` | 201 `AuthResponse {user, access, refresh}` |
| POST | auth/login/ | `{email, password}` | 200 `AuthResponse`; 400 `BAD_CREDENTIALS` |
| POST | auth/refresh/ | `{refresh}` | `{access}` |
| GET | auth/me/ | | `User` |
| DELETE | auth/me/ | | 204 (deletes the account) |
| GET | body/ | | `Body`; 404 `BODY_NOT_FOUND` |
| POST | body/ | multipart `photo`, `is_adult_confirmed`, `sex` (male\|female, required) | 201 `{body, job_id}`; 400 if sex missing/invalid; 409 `BODY_EXISTS` |
| PATCH | body/sex/ | `{sex}` | `Body`; only while `sex` is null (older bodies); 400 `BAD_SEX`; 409 `SEX_ALREADY_SET`; 404 `BODY_NOT_FOUND` |
| DELETE | body/ | | 204 (should cascade to its outfits: **not yet**, outfits are kept today, fix in step 3) |
| POST | body/confirm/ | `{landmarks, height_cm?, measurements?}` | `Body` (photo + landmarks locked); 409 `BODY_CONFIRMED`; 400 `MEASUREMENTS_INVALID` `{code, detail, field}` (docs/11 ranges, nothing locked) |
| PATCH | body/measurements/ | `{height_cm?, measurements?}` | `Body`; 403 `MEASUREMENTS_LOCKED` + `unlock_at`; 400 `MEASUREMENTS_INVALID` `{code, detail, field}` (the lock does not start) |
| GET | avatars/ | | `Avatar[]` |
| GET | avatars/nearest/ | `?sex&shoulder&chest&waist&hip` (all required, circumference cm 20..300; `height` optional, unused); 400 `SEX_REQUIRED` / `MEASUREMENTS_REQUIRED` `{fields}` | `Avatar` |
| GET | staff/avatars/ | (staff only, others 404) | `StaffAvatar[]` (`Avatar` + `height_cm, landmarks_confirmed_at, status: confirmed\|auto`) |
| GET | staff/avatars/{id}/ | (staff only) | `StaffAvatar`; landmarks not yet confirmed get edge points from the mask (GET never writes) |
| POST | staff/avatars/ | multipart `sex, build, photo, height_cm, shoulder, chest, waist, hip` (staff only) | 201 `StaffAvatar + warnings[]` (200 when it replaced that sex+build; landmarks reset to auto); 400 `{code, detail}` (`NO_PERSON`, `HEAD_OR_FEET_CUT`, `FIGURE_CLIPPED`, upload codes) |
| PATCH | staff/avatars/{id}/landmarks/ | `{landmarks, height_cm?, measurements?}` (staff only) | `StaffAvatar`, sets `landmarks_confirmed_at`; 400 `LANDMARKS_INVALID` (rules in docs/03) |
| GET | garments/ | `?scope=mine\|catalog\|all&type=tshirt\|pants&gender=female\|male\|unisex` (female/male also return unisex; unknown values ignored) `&for_sex=male\|female\|all&avatar_id=` (try-on rule, docs/09 #97: male -> male + unisex, female -> female + unisex, all = no filter; without `for_sex`, `scope=catalog` defaults to the sex of `avatar_id` or of the user's body when known) | `Garment[]`; 400 `BAD_SEX` for another `for_sex` |
| POST | garments/ | multipart `photo`, `type`, `sizes` (JSON string, required), `stretch?` (bool, default false), `name?` | 201 `{garment, job_id}`; 400 `SIZES_INVALID` `{code, detail}` (missing, malformed JSON, unknown key, out of range, not a finite number; nothing is created) |
| GET | garments/{id}/ | | `Garment` (owner, or public+approved) |
| PATCH | garments/{id}/ | `{fit_mode?, gender?}` (owner only; same style as visibility) | `Garment`; 400 `BAD_FIT_MODE` / `BAD_GENDER` / `FIELD_NOT_EDITABLE` (any other key, e.g. image, name, landmarks, sizes, stretch: nothing saved; the image is never updatable); 404 for others |
| DELETE | garments/{id}/ | | 204 (owner only) |
| PATCH | garments/{id}/landmarks/ | `{landmarks}` (the FULL object; T-shirt step 1 sends the stored collar / neck_hole back untouched) | `Garment + landmark_warnings[{code, group, detail}]` (range warnings, saved anyway; 409 `GARMENT_NOT_READY` until cleaned; 400 `LANDMARKS_INVALID` `{code, detail}` with a short Uzbek message naming the group, rules in docs/03 incl. `neck_hole.polygon`; legacy `sleeve_end` and `neck_hole: null` are never stored; 404 for other users) |
| PATCH | garments/{id}/sizes/ | `{sizes, stretch?}` (owner only; `sizes` FULL replace, no merge; same validation as upload; `stretch` omitted keeps the stored value) | `Garment`; 400 `SIZES_INVALID`; 404 for others |
| PATCH | garments/{id}/visibility/ | `{visibility: private\|public}` | `Garment` |
| GET | jobs/{id}/ | | `Job {id, kind, status, result, error_code, error_message, ...}` |
| POST | tryon/ | `{base: body\|avatar, avatar_id?, garment_ids[], measurements?}` (`measurements` = `{height_cm?, chest?, waist?, hip?, shoulder_width?, inseam?}`, base=avatar only: the user's sizes, not the avatar's; ignored for base=body) | 202 `{job_id, outfit_id, engine}` (`engine`: debug, the T-shirt engine asked for = setting `TRYON_WARP`, `mls` (default, docs/09 #105)\|`parts`, docs/09 #98; the job `result` adds `engine` actually used, `quality_warnings`, e.g. `["mls_fallback"]`, `tshirt_config`, `finish` and `render_ms`); 400 `GENDER_MISMATCH` `{garment_id, garment_gender, base_sex}` when a garment's gender is not the base's sex (unisex always passes); 400 `BODY_SEX_REQUIRED` for a body without sex; 400 `MEASUREMENTS_INVALID` `{code, detail, field}` (docs/11 ranges, always checked for base=avatar). **Fit gate** (only with `FIT_CHECK_ENABLED=1`, default 0; docs/11): after the checks above, before the demo short-circuit; the first failing garment in `garment_ids` order: 400 `GARMENT_SIZE_MISSING` `{garment_id, keys, detail}` / `BODY_SIZE_MISSING` `{keys, detail}` / `SIZE_MISMATCH` `{garment_id, checks: [{zone, garment_cm, body_cm, ease_cm, verdict, limit_cm}], detail}` (one Uzbek line per failing zone); no job and no outfit |
| GET | tryon/fit-check/ | `?base=avatar\|body&avatar_id=&garment_ids=1,2` (+ `height_cm, chest, waist, hip, shoulder_width, inseam` for base=avatar) | 200 `{results: [{garment_id, fits, checks, code?, keys?}]}` (same gate as `POST tryon/`, regardless of the flag; not fitting = `fits: false`; missing sizes = `checks: []` + `code` `GARMENT_SIZE_MISSING`\|`BODY_SIZE_MISSING` + `keys`); 400 `BAD_BASE` / `BAD_GARMENT_IDS` / `BAD_AVATAR_ID` / `MEASUREMENTS_INVALID`; 404 for an unknown avatar, no own body, or a garment the user cannot see |
| GET | config/ | (public, no auth) | `AppConfig {demo_mode}` |
| GET | outfits/ | | `Outfit[]` |
| GET | outfits/{id}/ | | `Outfit` |
| DELETE | outfits/{id}/ | | 204 |

Notes
- There is **no** endpoint to edit body photo/landmarks or a garment image. Body landmarks are sent once, in `body/confirm/`.
- `measurements` = cm: `{shoulder?, chest?, waist?, hip?, shoulder_width?, inseam?}`; shoulder, chest, waist, hip are circumferences (decision 13), `shoulder_width` is a WIDTH and `inseam` a length, both for the fit check (docs/11, docs/09 #126). Ranges (all optional): height_cm 140-210, chest 70-150, waist 55-150, hip 75-160, shoulder_width 30-60, inseam 55-100; `shoulder` keeps > 0 (`apps/sizing/measurements.py`). Values given at confirm do not start the yearly lock; each `PATCH body/measurements/` does.
- Body fields: `id, image_url, landmarks, height_cm, measurements, confirmed_at, measurements_unlock_at, can_change_measurements, created_at`.
- Garment fields: `id, name, type, image_url, thumb_url, original_preview_url, width, height, landmarks, landmarks_complete, neck_complete, visibility, fit_mode, gender, status, owned_by_me, ai_skipped, sizes, stretch, sizes_complete, created_at`. `sizes_complete` = every required size key is present (false when `sizes` is null). `landmarks_complete` = every point of the MAIN set exists (T-shirt step 1: shoulder, armpit, chest, waist, hem, cuff corners; docs/09 #92, #102). `neck_complete` = T-shirt step 2 done: collar + collar_bottom + `landmarks.neck_hole.polygon` (null for pants; the wardrobe shows "Boʻyin belgilanmagan" when false).
- Try-on job `result` (`GET jobs/{id}`): `{outfit_id, engine, quality_warnings[], neck_hole: {"<garment id>": bool}, tshirt_config: {"<garment id>": {...}}, finish, render_ms}`.
  `finish` (debug, docs/09 #107, #108): `r17` when a garment got the finish (smooth edge, form shading, contact shadow; settings `TRYON_FINISH`, and `TRYON_FINISH_PANTS` for pants), else `off`. Absent in demo-mode results.
  `tshirt_config` (debug, docs/09 #105; one entry per T-shirt): what the render actually used, (keep_shape on MLS also `keep_scale: fit`, docs/09 #112, and `keep_neck_dy` (px moved down), docs/09 #121; tube sleeves also `tube_clip: arm`, docs/09 #113) `{fit_mode: adapt|keep_shape, engine: mls|parts, sleeve: r7|A|B|C|null, tube: bool, side_floor: mask|off, armpit: r14|off, hem: garment|mls, cuff: hem|chord, fringe: drop|keep}` (`engine: parts`: only `fit_mode` and `engine`; keep_shape: `sleeve: null`, the rest off; `armpit` is `off` whenever the tube or the side floor is off; `cuff` / `fringe` (docs/09 #106) are `chord` / `keep` whenever the tube is off). `render_ms` (debug) = the render call in ms, without file I/O. Both are absent in demo-mode results. Quality warning `tube_fallback` = the tube sleeve could not be built on a side, the T-shirt was rendered with MLS sleeves (`tube: false`, `armpit: off`, `cuff: chord`, `fringe: keep`).
  `neck_hole` (debug, docs/09 #102) = the owner polygon was used; only with `TRYON_WARP=mls`, `TRYON_NECK_HOLE=1` and a valid polygon (adapt or keep_shape, docs/09 #103). Quality warning `neck_hole_invalid` = a stored polygon failed the render-time check and was skipped (no fallback to parts).
  `ai_skipped` (read-only) = the AI check was skipped by `AI_DEV_BYPASS` (local dev only): the frontend shows a dev warning.
- `User` fields: `id, email, is_adult_confirmed, is_staff, created_at` (`is_staff` read-only).
- Outfit fields: `id, body, avatar, garments[], result_url, realistic_url, created_at`.
- **Demo mode** (`DEMO_MODE=1`, `apps/tryon_engine/demo.py`): `POST tryon/` for an (avatar, garments) pair built by
  `manage.py build_demo` returns the same 202 shape, but the job is already `done` with `result.demo = true` (no Celery).
  Other pairs take the normal path. Demo garments are approved public catalog garments (owner empty).

Not built yet (add here and in types.ts when built): `POST tryon/{id}/realistic/`, `POST outfits/` (explicit save; today every
try-on creates an outfit), `POST garments/{id}/report/`, admin moderation endpoints, `GET assets/sample-pose/`,
try-on `quality_warnings[]`, outfit `name` and per-garment `deleted` flag.

## Permissions (tests required)
- Body endpoints: only the owner; another user gets 404.
- Garment read: owner always; others only if `visibility=public` AND `status=approved`.
- Image URLs: signed, short-lived.
- Rate limits: daily AI-reaching upload attempts per user; throttling on auth.
