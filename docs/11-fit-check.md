# 11. Fit check (garment real size vs body size)

Owner decision 2026-11-25 (docs/09 #125). **Supersedes docs/02 rule 21 ("garment real size is NOT entered") and
docs/09 #1.** Everything about the fit check lives in this doc; other docs only point here.

## What it does
The garment's real measurements (cm) are entered with its photo; the person's measurements (cm) are entered with the
body/avatar. Before rendering, the backend checks whether the garment really fits:
- fits -> try-on runs as today;
- does not fit -> no render, the user sees "Bu kiyim sizga mos emas" + the reason (zone and cm).

## Hard boundary: the render engine is NOT touched
- New app `apps/sizing/`. Pure function, no I/O:
  `check_fit(garment_type, garment_sizes, stretch, fit_mode, body_sizes) -> FitResult`.
- **Import boundary (owner, docs/09 #126):** `apps.sizing` imports no models and nothing from `tryon_engine`. Only the
  tryon_engine **view layer** (`views.py`, `fit_gate.py`) imports `apps.sizing`; `warp`, `mls` and `tasks` never do.
- The only coupling point: `apps/tryon_engine/fit_gate.py`, used by `POST tryon/` (before the job) and
  `GET tryon/fit-check/`.
- MLS, parts, warp, hem rules, regression fixtures: unchanged (0 px difference).
- Phase 1 limit (say it in the demo): the render does not know the cm. An `adapt` garment that is 2 cm or 18 cm loose
  looks the same on the body; only the yes/no answer reflects size. `FitResult` carries `ease_cm` per zone so a later
  phase could pass it to the render; not used now.
- Flag `FIT_CHECK_ENABLED` (env, **default 0; switched to 1 in step 5**, docs/09 #126). 0 = today's behaviour for
  `POST tryon/` (no check; sizes stored, request `measurements` validated but not used). `GET tryon/fit-check/` works
  either way.

## Decisions (owner, 2026-11-25)
1. **Too small -> always "mos emas". Too large -> "mos emas" only for `adapt`.** `keep_shape` (oversized, wide-leg)
   has no upper limit: it is big on purpose.
2. **Garments without sizes are blocked from try-on** until sizes are entered: `GARMENT_SIZE_MISSING`. Sizes are
   required on new uploads; existing garments (#28, #40, #43, #44, #45, demo catalog) get them once via
   `PATCH garments/{id}/sizes/`.
3. **`Garment.stretch: bool`** (default false). Stretch garments allow a small negative ease (see thresholds).
4. **Both body sources are supported in code** (avatar now, own body when its flow resumes). Own-body measurements
   become required for try-on (changes docs/02 rule 19 for the fit check; the yearly lock, rule 2, is unchanged).

## Data model
- `Garment.sizes` JSON (cm, flat-lay: garment laid flat, measured on one side), nullable for old rows.
- `Garment.stretch` bool, default false.
- Garment image stays immutable (docs/02 rule 4); `sizes` and `stretch` are data and editable by the owner.
- Body / avatar measurements: existing `measurements` JSON (circumference cm) + `height_cm`. New optional key `inseam`.

### Garment sizes (flat-lay, cm)
| type | required | optional |
|---|---|---|
| `tshirt` | `chest_width` (armpit to armpit), `length` (shoulder top to hem), `shoulder_width` | `waist_width`, `sleeve_length` |
| `pants` | `waist_width`, `hip_width`, `inseam` | `thigh_width`, `leg_opening` |

Validation ranges (400 `SIZES_INVALID` outside, Uzbek message naming the field):
`chest_width` 30-90, `length` 40-100, `shoulder_width` 30-70, `waist_width` 20-90, `sleeve_length` 5-40,
`hip_width` 30-90, `inseam` 40-100, `thigh_width` 15-50, `leg_opening` 8-40.

### Body sizes (cm)
`height_cm` 140-210; circumferences `chest` 70-150, `waist` 55-150, `hip` 75-160; `shoulder_width` (width) 30-60;
`inseam` optional 55-100, else estimated as 0.45 x height (proposed, calibrate).
Required for the check: tshirt `chest` + `shoulder_width`; pants `waist` + `hip` + `inseam` (or `height_cm` for the
estimate). Missing -> 400 `BODY_SIZE_MISSING`.

**Interpretation (step 2, 2026-11-25):** the existing `measurements.shoulder` (Body, Avatar, docs/09 #13) is a
**circumference** (seeded avatars: 96-126 cm). The fit check never converts it: it reads a separate body key
`shoulder_width` (cm, a width). Missing `shoulder_width` -> `SizesMissing(side="body", keys=["shoulder_width"])`.
Stored (step 3, docs/09 #126) as `Body.measurements.shoulder_width` (and optional `inseam`), validated with the other
keys by `apps/sizing/measurements.py` (docs/11 ranges, all optional; `MEASUREMENTS_INVALID`) at `body/confirm/` and
`PATCH body/measurements/` (yearly lock unchanged). The PATCH **merges** (docs/09 #127): sent keys replace the stored
values, the rest stay; `null` is rejected (no key removal); an identical PATCH does not start the lock. Avatar: no change, the avatar path sends the user's sizes in
`POST tryon/` `measurements`.

## Rules (proposed thresholds, calibrate in step 5)
`garment_circ = 2 x flat_width`, `ease = garment_circ - body_circ`. Widths (shoulder) are compared directly.

| zone | too_small if | too_large if (adapt only) |
|---|---|---|
| tshirt chest | ease < 0 (stretch: < -4) | ease > +20 |
| tshirt shoulder | garment `shoulder_width` < body `shoulder_width` - 2 | garment > body + 6 |
| pants waist | garment_circ < body - 4 (stretch: < -8) | garment_circ > body + 6 |
| pants hip | ease < 0 (stretch: < -4) | ease > +20 |
| pants inseam | garment < body - 5 | garment > body + 8 |

- **keep_shape: no too_large check on any zone** (too_small still applies), per decision 1.
- Thresholds live in one settings dict (`FIT_RULES` in `tryon_studio/settings/base.py`: per type, per zone
  `min_ease`, `min_ease_stretch` (chest, waist, hip only; else `min_ease` is used), `max_ease`; plus
  `BODY_INSEAM_HEIGHT_RATIO`), not in code branches. Code: `apps/sizing/fit.py` `check_fit(..., rules=None)`.
- Output: `FitResult(fits, checks)`, `ZoneCheck(zone, garment_cm, body_cm, ease_cm, verdict, limit_cm)`. For
  chest / waist / hip `garment_cm` is the circumference (2 x flat width); `limit_cm` = body + the broken ease limit
  (same unit as `garment_cm`), else null. Values rounded to 1 decimal after comparing. Zone order: tshirt chest,
  shoulder; pants waist, hip, inseam.
- Missing or non-numeric required keys raise `SizesMissing(side, keys)` (garment checked first); unknown type or
  fit_mode raise `ValueError`.
- A value exactly on a threshold passes (boundary tests).
- Optional garment fields are checked only when present (none have rules yet).
- `fits = all zones ok`.

## API
- `POST garments/` multipart: adds `sizes` (JSON string) and `stretch`; `sizes` required. 400 `SIZES_INVALID`.
- `PATCH garments/{id}/sizes/` `{sizes, stretch?}` -> `Garment` (owner only, others 404).
- Garment fields: + `sizes`, `stretch`, `sizes_complete`.
- `POST tryon/` order (flag 1): existing checks (`BODY_SEX_REQUIRED`, `GENDER_MISMATCH`, duplicate types, ...) ->
  fit gate -> demo short-circuit -> job. Every garment is checked; the first failing one in `garment_ids` order is
  reported: 400 `GARMENT_SIZE_MISSING` `{garment_id, keys, detail}` / `BODY_SIZE_MISSING` `{keys, detail}` /
  `SIZE_MISMATCH` `{garment_id, checks: [{zone, garment_cm, body_cm, ease_cm, verdict, limit_cm}], detail}`.
  No job and no outfit is created on failure. Base=body uses `Body.height_cm` + `Body.measurements`; base=avatar
  uses the request `measurements` (400 `MEASUREMENTS_INVALID` outside the ranges).
- `GET tryon/fit-check/?base=avatar|body&avatar_id=&garment_ids=1,2` (+ the measurement keys as query params for
  avatar) -> 200 `{results: [{garment_id, fits, checks, code?, keys?}]}` (UI: disable the try-on button early). Same
  gate as `POST tryon/`. Not fitting = a result; missing sizes = `fits: false, checks: []` + code + keys. 400 only for
  bad params; a garment the user cannot see -> 404. base=body needs a confirmed body (same 400 as `POST tryon/`).
- Avatar path: the check uses the measurements the user entered (the ones the avatar was chosen by), not the avatar's
  nominal measurements. Proposed: pass them in `POST tryon/` as `measurements` (same shape as body).
- Contract rule (docs/04): views, serializers and `frontend/src/api/types.ts` change in the same commit.

## User messages (Uzbek, backend-produced, docs/02 rule 18)
- `SIZE_MISMATCH`: "Bu kiyim sizga mos emas: {zone} {n} sm {tor|keng}." (one line per failing zone; inseam uses
  `qisqa|uzun`; n = |garment_cm - limit_cm|, 1 decimal, trailing .0 dropped). Code: `apps/sizing/messages.py`.
- `MEASUREMENTS_INVALID`: "{field}: {min} dan {max} sm gacha boʻlishi kerak." (or "{field}: son kiriting.")
- `GARMENT_SIZE_MISSING`: "Bu kiyimning oʻlchamlari kiritilmagan."
- `BODY_SIZE_MISSING`: "Kiyimni tekshirish uchun oʻlchamlaringizni kiriting."
- Zone names: koʻkrak (chest), yelka (shoulder), bel (waist), son (hip), uzunlik (inseam).

## Plan (about 3-4 days)
0. Decisions + this doc (done 2026-11-25).
1. Data model: fields, migration, range validation, serializers, `PATCH sizes/`, types.ts (0.5 day).
2. `apps/sizing.check_fit` + unit tests: every zone, boundaries, stretch, keep_shape, missing sizes (0.5-1 day).
3. Wire into `POST tryon/` + `GET tryon/fit-check/` + messages + flag + permission tests (0.5 day).
4. Frontend: size form with a "where to measure" image, required body/avatar sizes, "mos emas" with reasons (1 day).
5. Real cm for existing garments, 6 avatars x garments table, tune `FIT_RULES`, `build_demo` again (0.5 day).
Risk: real measurements. Garments photographed from the internet have no real cm (take them from the seller's size
chart, never invent).