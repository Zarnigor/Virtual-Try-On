# TryOn Studio

2D virtual try-on (MVP): a T-shirt or pants photo is cut out, marked with landmarks and **deformed onto a body**
(one of 6 model avatars or the user's own photo) by landmarks, not pasted on. Django + React, all in Docker.
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
`TRYON_SHOULDER_CAP` / `TRYON_HEM_SNAP` / `TRYON_HALO_REMOVAL` / `TRYON_NECK_FIX` / `TRYON_NECK_GAP_FILL` (structural try-on steps, all `1`; docs/06 "Layer order"), `TRYON_DROPPED_SHOULDER_SINGLE` (`0`, docs/09 #90), `TRYON_HEM_RULE` (`1`, docs/09 #91), `TRYON_NECK_HOLE` (`1`, owner-drawn neckline hole, MLS only (adapt and keep_shape), docs/09 #102), `TRYON_MLS_SLEEVE` (`C`, MLS sleeve variant, adapt only, docs/09 #104), `TRYON_WARP` (`mls`, the T-shirt engine; `parts` = the old engine; pants always use parts), adapt T-shirts on MLS (docs/09 #105; the second value = the behaviour before): `TRYON_MLS_TUBE` (`1` | `0`), `TRYON_MLS_SIDE_FLOOR` (`mask` | `off`), `TRYON_MLS_ARMPIT` (`r14` | `off`, needs the tube and the side floor), `TRYON_MLS_HEM` (`garment` | `mls`), tube sleeves (docs/09 #106; off without the tube): `TRYON_MLS_CUFF` (`hem` | `chord`), `TRYON_MLS_FRINGE` (`drop` | `keep`), `TRYON_FINISH` (`r17` | `off`, docs/09 #107: smooth edge + form shading + contact shadow on the T-shirt layer; with `off` the three realism flags decide as before), `TRYON_FINISH_PANTS` (`1` | `0`, docs/09 #108: the same finish on pants; needs `TRYON_FINISH=r17`), `TRYON_PANTS_TUCK` (`1` | `0`, docs/09 #109: an adapt MLS T-shirt hangs over the pants), `TRYON_MLS_KEEP_SCALE` (`fit` | `shoulder`, docs/09 #112: the scale of keep_shape T-shirts), `TRYON_MLS_TUBE_CLIP` (`arm` | `armhole`, docs/09 #113: tube sleeves end on the arm/torso boundary), `TRYON_PANTS_ENGINE` (`rows` | `fit`, docs/09 #116: the pants engine; `fit` = `warp_pants_fit`, #114; `rows` = the round 26 fit model, #120), `TRYON_DRAPE_BODY_MARGIN` (`6` | `off`, docs/09 #119: the T-shirt drape over pants stops at the figure edge + 6 px),
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

## Live demo (2026-11-17)
Before the demo: `docker compose up -d`, wait until `http://localhost:5173` opens, then run the end-to-end check
(a temporary user, deleted at the end; prints `ALL OK`):
```
docker compose exec -T backend python manage.py shell < tools/tryon_check/own_body_path.py
```
The local `.env` runs with `AI_DEV_BYPASS=1` and `BODY_AI_CHECK_ENABLED=0`: no Gemini call is made, nothing depends on
the network. Leave `DEMO_MODE=0` (the stored demo results use two old garments).
Walk-through, logged in as the owner of the marked garments:
1. **Bosh sahifa**: the body card, the newest garments and outfits.
2. **Kiyimlar** -> a garment -> the landmark editor (T-shirts: step 2 is the neckline). **Kiyim yuklash**: upload a
   photo, the background is removed, the original file is deleted.
3. **Kiyib koʻrish** -> **Model**: enter sex + four measurements -> the nearest model is chosen -> pick a T-shirt
   and pants -> the result in about 1.5 s; it is stored under **Obrazlar**.
4. **Tana** (own body, a second account without a body): upload an A-pose photo -> code checks, 600x1200, auto
   landmarks -> correct them in the editor -> **Tasdiqlash** (locked) -> **Kiyib koʻrish** -> **Mening tanam**.
5. **Profil**: privacy rules, delete the body (its outfits go with it) or the account.
A garment whose gender does not match the body is refused (`GENDER_MISMATCH`): #28 is male, #40 / #43 / #47 female.

## Not done / known limits (honest list, 2026-11-16; details docs/09 #110)
- **Body AI check (prompt 02) is not wired.** With `BODY_AI_CHECK_ENABLED=1` and no bypass an own-body upload fails
  closed with "try again later". The demo runs with the bypass: adults-only rests on the "I am 18+" confirmation and
  the clothing rule (tight, short-sleeved) is not checked; the code checks (person found, whole figure, framing) run.
- **AI garment cleaning (prompt 04) and the realistic render (prompt 05) are absent**: garments are cut out by rembg
  only (hangers stay), no Save / Cancel preview. Public garments, moderation (prompt 03) and reports are not built.
- **Avatar measurements are nominal** per sex / build; the nearest model is matched on them; its landmarks are not
  adjusted to the entered measurements.
- Every try-on stores an outfit (no explicit save step). Measurements entered after confirmation start the yearly lock.
- **Engine:** keep_shape (oversized) T-shirts are scaled to fit the body (docs/09 #112) but stand off the shoulders
  and their sleeves stick out sideways; an armpit fold on #43, a pinched
  cuff on #40, the uneven hem of jeans #48; an adapt T-shirt renders in about 1.2-1.5 s; arms that touch the body
  cannot be separated (hands may stay under the garment, warning); shorts and white / black pants are not measured; pants (docs/09 #120): the waist -> crotch block is the body + 3 %, legs are monotonic (a jogger cuff no longer tapers), a garment's own hem slit shows the leg, full-length pants end on the ankle line.
  Own body: the auto landmarks are a starting point, unedited shoulders can leave a gap at the sleeve seam.
- The frontend follows `design/` for the navigation, home, body, profile and editor pages; screens 3, 6, 8, 9 are
  simpler than the artboards. No ESLint config.

## Commands
```
docker compose exec -T backend python manage.py test apps     # 401 tests
docker compose exec -T frontend npx tsc --noEmit              # type check
docker compose exec -T frontend npm test                      # vitest: 78 tests (landmark editor, body cm)
docker compose exec -T backend python manage.py migrate
docker compose exec -T backend python manage.py seed_avatars [--from /avatars | --force]
docker compose exec backend python manage.py create_staff_user --email you@example.com   # asks the password
                                                              # (or -e STAFF_PASSWORD=...; never commit it)
docker compose exec -T backend python manage.py promote_garments --list                    # ids, type, status
docker compose exec -T backend python manage.py promote_garments --ids 28 33 --catalog     # public + approved
docker compose exec -T backend python manage.py reflatten_garments --all-solid --dry-run   # flatten lighting once
docker compose exec -T -e ENGINE=new backend python manage.py shell < tools/tryon_check/run.py   # try-on check
docker compose exec -T backend python manage.py shell < tools/tryon_check/landmarks_overlay.py   # landmark overlays + checks (read-only)
docker compose exec -T backend python manage.py shell < tools/tryon_check/neck_regress.py       # TRYON_NECK_FIX off/on diff
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
