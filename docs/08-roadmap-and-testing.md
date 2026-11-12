# 08. Roadmap and testing

3 days to build + day 4 for checking. Prefer a working MVP over everything half-done.
MVP garments: T-shirt + pants. Body photo: short-sleeved/sleeveless top + shorts or tight leggings.

## Day-1 experiment (first, before pages)
One T-shirt and one pair of pants warped onto the 3 avatars of one sex. Criteria in `06-try-on-engine.md`.
If the result is poor, stop and decide (fallbacks in the same file) before building the rest.

## P0 (days 1-3)
- Auth (email + password), Django project, models, Docker Compose (Postgres, Redis, Celery).
- LandmarkEditor component (React port of the prototype, landmark sets by type).
- Seed command for 6 avatars (data from the prepared images, no admin UI).
- Own-body flow: upload, code checks, rembg, landmarks, confirm/lock, delete body, measurements change once per year.
- Avatar flow: sex + required measurements -> nearest avatar.
- Garment upload with **AI cleaning** (prompts 01 and 04, Nano Banana 2; prompt 04 off for now via `AI_CLEANING_ENABLED`, docs/09 #55): hanger photos allowed, preview Save/Cancel, landmark marking, private visibility.
- Starter catalog prepared offline.
- Try-on engine (mesh warp: T-shirt torso + 2 sleeves, pants waist-hip + 2 legs), composite.
- Body AI validation (prompt 02): P0 recommended, see open question 12.

## P1 (end of day 3 if time allows)
- Realistic render button (05) and saved outfits (realistic version saved too).

## P2 (after day 4 or only if time remains)
- Public garments, AI moderation (03), report button, admin queue.

P0 is large for 3 days. If behind schedule, cut in this order: outfits, realistic render, body AI validation (keep code checks), starter catalog size.

## Day 4: checking
- Run through the 3 activity diagrams end to end.
- Demo safety: precomputed results for about 10 garments.
- Show one rejected upload on purpose (e.g. thick jacket or long sleeves) to demonstrate quality control.

## Tests to write
- Landmark sanity checks (order, ranges, body chest >= armpit, per-leg widths; garments: chest above armpit is a warning only).
- Garment gender in try-on (`GENDER_MISMATCH`, `BODY_SEX_REQUIRED`, `for_sex` filter) and `TRYON_WARP` fallback (`mls_fallback`).
- Immutability: second body upload fails; no update endpoints for body photo/landmarks and garment image.
- Measurements change allowed once per 365 days only.
- Body deletion removes body, photos and its outfits.
- Permissions: another user cannot read a body or a private garment (404).
- Public visibility only when approved.
- AI JSON parsing fails closed; code-side rejections do not count to the daily limit.
- Canvas: every stored result is 600x1200; realistic render crop keeps the person aligned.
- Upload limits, file type validation, originals deleted after processing.

## Definition of done (per feature)
Works end to end in the UI, has the tests above where relevant, errors have clear Uzbek messages,
no secrets in the repo, README commands updated.
