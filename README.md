# TryOn Studio

2D virtual try-on (MVP): a T-shirt or pants photo is cut out, marked with landmarks and **deformed onto a body**
(one of 6 model avatars, later the user's own photo) by landmarks, not pasted on. Django + React, all in Docker.
Instructions for Claude Code and all decisions: `CLAUDE.md` and `docs/` (source of truth: `docs/02`, `docs/09`).

## Run
Docker runs in **OrbStack** on the dev Mac (`~/.orbstack/bin` on PATH; OrbStack needs the Desktop folder permission in
System Settings -> Privacy & Security -> Files & Folders). The Mac has no host Python/Node: everything runs in containers.
```
cp .env.example .env                       # then set GEMINI_API_KEY and GEMINI_VALIDATION_MODEL (garment AI check)
docker compose up -d --build               # db, redis, backend :8000, worker, frontend :5173
                                           # backend start runs migrate + creates MISSING placeholder avatars only
docker compose exec -T backend python manage.py seed_avatars --from /avatars    # real avatar photos (./avatars, not in git; any subset of female_slim.jpg ...)
open http://localhost:5173                 # register, upload a garment, mark landmarks, try it on an avatar
```
Staff pages (staff users only, see `create_staff_user` below): `/staff/avatars` (list, landmark status),
`/staff/avatars/new` (upload a new avatar photo + nominal height and circumferences), `/staff/avatars/:id` (body landmark
editor with live cm widths and circumference estimates; Save confirms the landmarks the try-on engine uses).
`.env` flags (defaults in `.env.example`): `AI_DEV_BYPASS=0` (1 = skip AI checks locally, DEBUG only, garments get a
"DEV: tekshirilmagan" chip), `AI_CLEANING_ENABLED=0` (prompt 04 not built, docs/09 #55), `DEMO_MODE=0`,
`TRYON_SHADING` / `TRYON_CONTACT_SHADOW` / `TRYON_EDGE_FEATHER` (realism effects, all `0` = plain opaque garment),
`TRYON_SHOULDER_CAP` / `TRYON_HEM_SNAP` / `TRYON_HALO_REMOVAL` / `TRYON_NECK_FIX` / `TRYON_NECK_GAP_FILL` (structural try-on steps, all `1`; docs/06 "Layer order"), `TRYON_DROPPED_SHOULDER_SINGLE` (`0`, docs/09 #90), `TRYON_HEM_RULE` (`1`, docs/09 #91),
`BODY_AI_CHECK_ENABLED=1` (prompt 02 on own-body uploads; 0 honoured only with DEBUG),
`AI_DAILY_LIMIT` / `AI_GARMENT_DAILY_LIMIT` (staff are exempt from the garment limit, the AI check still runs), optional `GEMINI_TIMEOUT_S` (min 60). The first rembg run downloads its
model (~176 MB, `u2net` volume, kept across rebuilds).

## Demo mode (no Gemini, no Celery for the covered pairs)
```
mkdir -p demo_garments                                                         # not in git
docker compose exec -T backend python manage.py export_demo_garments /demo_garments 13 21   # garments marked in the app
docker compose exec -T backend python manage.py build_demo --garments /demo_garments        # renders into media/demo/
DEMO_MODE=1 docker compose up -d backend worker                                # or set DEMO_MODE=1 in .env
```
A demo folder holds `<name>.png` (cleaned transparent garment) + `<name>.json` (`{type, name, landmarks}`) per garment.
`build_demo` turns them into approved catalog garments and renders every avatar x garment and every T-shirt + pants
pair. With `DEMO_MODE=1` the header shows **DEMO**, the try-on page also lists the catalog, and a covered
(avatar, garments) pair returns its precomputed image at once (labelled "DEMO"); other pairs use the normal worker.
Rebuild after reseeding avatars. Currently built: 1 T-shirt + 1 pants x 6 avatars = 18 results.

## Architecture
1. `frontend/` React + TypeScript (Vite). API types mirror `docs/04` in `src/api/types.ts`. All images come from the API.
2. `backend/` Django + DRF, PostgreSQL; JWT auth (email + password); signed short-lived media URLs, no open `/media/`.
3. Celery + Redis run the slow jobs (`apps/jobs/tasks.py`, `apps/tryon_engine/tasks.py`); the client polls `GET jobs/{id}/`.
4. Garment upload: byte-level file checks -> Gemini prompt 01 (type check, over `httpx`, fail closed, daily limit,
   cache by image hash) -> rembg mask-only cutout -> tight-cropped RGBA PNG -> landmarks in the editor (checked server side).
5. Avatars: `seed_avatars --from` cuts real photos with rembg, scales uniformly onto a 600x1200 canvas
   (figure y 50..1150, axis x 300) and detects initial landmarks from the mask (`apps/avatars/prep.py`).
6. Try-on engine `apps/tryon_engine/warp.py` (`render_tryon`): scanline strips for torso and pants, rigid sleeves along
   the arm; lengths follow the garment, widths follow the body; hands/forearms are redrawn above the garment.
7. Demo mode: `apps/tryon_engine/demo.py` + `build_demo`; a manifest maps (avatar, garments) to a precomputed image.
8. Tests never make real HTTP calls (`tryon_studio/test_runner.py` blocks them; Gemini is faked with `httpx.MockTransport`).
9. `tools/tryon_check/run.py` renders every avatar x garment and measures sleeve reach, covered hands, hem, distortion.
10. AI prompts and the Uzbek error table live in `prompts/`; decisions in `docs/09`; diagrams in `docs/diagrams/`.

## Not done / known limits (honest list, 2026-11-10)
- **Own-body flow does not work end to end.** The body pipeline (code checks, normalization, landmarks) is not built;
  the body AI check (prompt 02) is not wired, so uploads fail closed with "try again later" unless `AI_DEV_BYPASS=1`;
  the body landmark editor is not built, so `BodyConfirm` cannot confirm. Plan: docs/09 #22-36 and the Part B plan.
- **Avatar measurements are nominal** (fixed per sex/build in `seed_avatars`, not measured from the photos); "nearest
  avatar" uses them. Avatar landmarks are auto-detected from the mask and look right on all 6, but there is no staff
  editor to correct them yet.
- **Realistic render (prompt 05) is absent.** AI garment cleaning (prompt 04) is off: hangers are not removed.
- Garment upload has no Save/Cancel preview and keeps the original photo after cleaning (breaks the "originals
  deleted" rule until step 6 is finished). Every try-on creates an outfit (no explicit save yet).
- Engine limits: arms that touch the body cannot be separated, so hands there may stay under the garment (warning);
  a T-shirt is as long as its own landmarks say (cut below crotch + 35 % of crotch->knee); puff sleeves stand out
  past the arm edge; distortion > 1.4x is reported as a warning, not fixed. The demo pants' landmarks were derived
  from the cutout automatically, not hand-marked.
- The frontend does not follow `design/` yet (screens 3, 5, 6, 8, 9, 12 missing). Only 2 demo garments (target ~10).

## Commands
```
docker compose exec -T backend python manage.py test apps     # 186 tests
docker compose exec -T frontend npx tsc --noEmit              # type check
docker compose exec -T frontend npm test                      # vitest: 44 tests (landmark editor, body cm)
docker compose exec -T backend python manage.py migrate
docker compose exec -T backend python manage.py seed_avatars [--from /avatars | --force]
docker compose exec backend python manage.py create_staff_user --email you@example.com   # asks the password
                                                              # (or -e STAFF_PASSWORD=...; never commit it)
docker compose exec -T backend python manage.py promote_garments --list                    # ids, type, status
docker compose exec -T backend python manage.py promote_garments --ids 28 33 --catalog     # public + approved
docker compose exec -T backend python manage.py reflatten_garments --all-solid --dry-run   # flatten lighting once
docker compose exec -T -e ENGINE=new backend python manage.py shell < tools/tryon_check/run.py   # try-on check
docker compose logs -f backend worker
docker compose down                                           # stop (add -v to wipe db + media)
```
There is no ESLint config yet (`npm run lint` fails).

## Contents
```
CLAUDE.md                       instructions, hard rules, status for Claude Code
docs/                           product, decisions, landmarks, API contract, AI pipeline, engine, security, roadmap, decisions log
design/                         UI design: 12 desktop screens (previews + sources), design tokens
prompts/                        5 AI prompts + config + Uzbek error messages
tools/                          landmark-editor prototype, avatar-prep script, try-on check script
seed/avatars.reference.json     landmark schema example (placeholder avatars)
```
