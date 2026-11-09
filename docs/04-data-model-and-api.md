# 04. Data model and API contract

Stack (confirmed): React + TypeScript; Django + DRF; PostgreSQL; Celery + Redis (AI jobs); Docker Compose;
OpenCV + rembg; Google Gemini API (Nano Banana 2). Auth: email + password. MVP storage: local media volume
behind signed URLs (assumption; S3-compatible later).

## Models
- **User**: email, password, is_adult_confirmed
- **Body**: user (OneToOne, unique), normalized image, landmarks (JSON), height_cm (nullable), measurements (JSON, optional),
  measurements_changed_at, confirmed_at (null until confirmed), created_at. Photo/landmarks immutable after confirmed_at.
  The original upload is deleted after normalization.
- **Avatar**: sex, build (slim|average|plus), image, landmarks (JSON), seeded by command
- **Garment**: owner (FK, null for admin catalog), type (`tshirt` | `pants`), image (cleaned transparent PNG),
  landmarks (JSON), visibility (private|public), status (pending|approved|review|hidden), created_at.
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
| POST | body/ | multipart `photo`, `is_adult_confirmed` | 201 `{body, job_id}`; 409 `BODY_EXISTS` |
| DELETE | body/ | | 204 (should cascade to its outfits: **not yet**, outfits are kept today, fix in step 3) |
| POST | body/confirm/ | `{landmarks, height_cm?, measurements?}` | `Body` (photo + landmarks locked); 409 `BODY_CONFIRMED` |
| PATCH | body/measurements/ | `{height_cm?, measurements?}` | `Body`; 403 `MEASUREMENTS_LOCKED` + `unlock_at` |
| GET | avatars/ | | `Avatar[]` |
| GET | avatars/nearest/ | `?sex&height&shoulder&chest&waist&hip` | `Avatar` |
| GET | garments/ | `?scope=mine\|catalog\|all&type=tshirt\|pants` | `Garment[]` |
| POST | garments/ | multipart `photo`, `type`, `name?` | 201 `{garment, job_id}` |
| GET | garments/{id}/ | | `Garment` (owner, or public+approved) |
| DELETE | garments/{id}/ | | 204 (owner only) |
| PATCH | garments/{id}/landmarks/ | `{landmarks}` | `Garment` (409 `GARMENT_NOT_READY` until cleaned) |
| PATCH | garments/{id}/visibility/ | `{visibility: private\|public}` | `Garment` |
| GET | jobs/{id}/ | | `Job {id, kind, status, result, error_code, error_message, ...}` |
| POST | tryon/ | `{base: body\|avatar, avatar_id?, garment_ids[]}` | 202 `{job_id, outfit_id}` |
| GET | outfits/ | | `Outfit[]` |
| GET | outfits/{id}/ | | `Outfit` |
| DELETE | outfits/{id}/ | | 204 |

Notes
- There is **no** endpoint to edit body photo/landmarks or a garment image. Body landmarks are sent once, in `body/confirm/`.
- `measurements` = circumferences in cm: `{shoulder?, chest?, waist?, hip?}` (decision 13). Values given at confirm do not start the yearly lock; each `PATCH body/measurements/` does.
- Body fields: `id, image_url, landmarks, height_cm, measurements, confirmed_at, measurements_unlock_at, can_change_measurements, created_at`.
- Garment fields: `id, name, type, image_url, thumb_url, original_preview_url, width, height, landmarks, visibility, status, owned_by_me, ai_skipped, created_at`.
  `ai_skipped` (read-only) = the AI check was skipped by `AI_DEV_BYPASS` (local dev only): the frontend shows a dev warning.
- Outfit fields: `id, body, avatar, garments[], result_url, realistic_url, created_at`.

Not built yet (add here and in types.ts when built): `POST tryon/{id}/realistic/`, `POST outfits/` (explicit save; today every
try-on creates an outfit), `POST garments/{id}/report/`, admin moderation endpoints, `GET assets/sample-pose/`,
try-on `quality_warnings[]`, outfit `name` and per-garment `deleted` flag.

## Permissions (tests required)
- Body endpoints: only the owner; another user gets 404.
- Garment read: owner always; others only if `visibility=public` AND `status=approved`.
- Image URLs: signed, short-lived.
- Rate limits: daily AI-reaching upload attempts per user; throttling on auth.
