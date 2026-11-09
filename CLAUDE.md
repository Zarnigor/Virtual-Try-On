# TryOn Studio: instructions for Claude Code

2D virtual try-on web app (MVP) for a job application: 3 days to build, day 4 for checking.
Core goal: the garment is deformed to fit the person's exact body (landmarks), not just pasted on.
Owner: Nursulton (backend developer: Python, Django, PostgreSQL, Docker). The backend is the main stack,
but the frontend must fully work too (React is required). The owner works and reviews in Uzbek.

## How to work with me (read first)
1. **Plan first, then wait.** Before writing code, creating files or changing anything, show a short plan
   (what, which files, in what order) and wait for my explicit confirmation. Applies to every milestone.
2. **Ask instead of assuming.** If a requirement is unclear, or it is still open in `docs/09-open-questions.md`, ask.
   Ask short, specific questions. Do not invent requirements. Decisions already logged in `docs/09` are final: do not ask again.
3. **One milestone at a time.** Small, reviewable steps. Run tests before saying "done".
4. **Share opinions.** If you see a better approach or a risk, say so briefly with a reason, then follow my decision.
5. **Language:** user-facing text in Uzbek (Latin script, use ʻ for oʻ/gʻ); code, comments, commit messages, API fields in English.
6. Keep this file and `docs/` updated when a decision changes. Update the matching diagram in `docs/diagrams/`.

## Decisions already made (details: docs/02 and docs/09)
- **MVP garments: T-shirt (`tshirt`) and pants (`pants`) only.** Other types are rejected.
- Stack: React + TypeScript, Django + DRF, PostgreSQL, Celery + Redis, Docker Compose, OpenCV + rembg.
  Auth: email + password only (no Google sign-in). Image model: **Nano Banana 2 (standard)** via the official Gemini API.
- **The garment always adapts to the body.** Garment real size is NOT entered. No tight/loose fit label.
- **Model (avatar) path: numeric measurements are required.** Own-body path: measurements optional.
- Garment AI cleaning (hanger/background removal, prompt 04) is **in P0**.
- Realistic render is saved with the outfit. Originals are deleted after processing.

## Hard rules (do not break)
- **One body per user, photo/landmarks immutable after confirmation.** Enforce in the backend (unique `user_id`, no PUT/PATCH for
  photo/landmarks, second upload fails). A hidden frontend button is not enough.
  Measurements may change **once per 365 days**. The user **may delete** their body (cascades to its outfits) and create a new one.
- **Garment images are immutable**, only deletable. Landmarks and visibility are data and may be edited.
- Body, photo and measurements are **private to the owner**: every query filtered by `user_id`; other users get 404.
- Garment visibility: `private` (default) or `public`. The owner sees a new garment immediately either way.
  Public garments reach others only after moderation (`approve`).
- Body photo: ONE photo, A-pose, whole body, front view, **tight thin clothing required** (strict reject, clear reason):
  **short-sleeved or sleeveless top** and **shorts or tight leggings**.
  **Never build features that remove or redraw the user's clothes/body.**
- Adults only for body photos (AI suspected-minor rejection + "I am 18+" confirmation).
- **Code checks first, AI checks second** (cost). Geometry (arms touch, legs gap, framing) is checked by code, not AI.
- **AI fails closed**: invalid/empty AI JSON means rejected. AI returns codes; the backend maps codes to Uzbek messages.
- Daily limit on AI-reaching upload attempts per user (default 5). Code-check rejections do not count.
- Canvas for body/avatars/results: **600 x 1200 px**, `axis_x = 300`, figure from y = 50 to about 1150.
  Garments: tight-cropped transparent PNG (not forced to 600x1200).
- Gemini image aspect ratios have no 1:2. Cleaning uses 3:4; realistic render pads to 9:16 and crops back (see prompts/README.md).
- Official Google Gemini API only. No third-party resellers. Secrets only in env vars.
- Signed short-lived URLs for images. Strip EXIF. No logging of image content.
- **All images of people and clothes come from the backend API** (bodies, avatars, garments, try-on results, realistic images,
  outfits). The `design/` files draw silhouettes and flat garments only as PLACEHOLDERS: never ship them. No hard-coded garments or
  sample catalog in the frontend. The backend returns the finished try-on image; the frontend does not compose it. See `docs/10`.

## Where things are
| Path | What |
|---|---|
| `docs/01-product-and-flows.md` | Pages, flows, who does what |
| `docs/02-decisions-and-rules.md` | All decisions and invariants (source of truth) |
| `docs/03-landmarks-and-coordinates.md` | Landmark names, definitions, canvas, sanity checks, past bugs |
| `docs/04-data-model-and-api.md` | Models, **API contract** (mirrored by `frontend/src/api/types.ts`), permissions |
| `docs/05-ai-pipeline.md` | Body, garment and realistic pipelines, cost |
| `docs/06-try-on-engine.md` | Mesh warp, risks, day-1 experiment, fallbacks (proposal) |
| `docs/07-security-privacy.md` | Privacy and safety |
| `docs/08-roadmap-and-testing.md` | P0/P1/P2, day plan, tests, definition of done |
| `docs/09-open-questions.md` | Decisions log, proposed defaults, what is still open |
| `docs/10-frontend-and-design.md` | Screen map, what comes from the backend, states the design does not show |
| `design/` | UI reference: 12 desktop screens (`previews/*.png`, `artboards/*.dc.html`), `tokens.md` |
| `docs/diagrams/` | UML activity diagrams (.puml source, .png/.svg rendered) |
| `prompts/` | The 5 AI prompts (raw .txt), config and Uzbek error-message table |
| `tools/landmark-editor-prototype/` | Working vanilla-JS landmark editor to PORT to React |
| `tools/avatar-prep/` | Script that removes backgrounds and normalizes photos to 600x1200 |
| `seed/avatars.reference.json` | Schema reference only (not final data) |

## Scope and priorities
- **Day-1 experiment first:** one T-shirt and one pair of pants warped onto 3 avatars (criteria in `docs/06`). Stop and ask me if it fails.
- **P0 (days 1-3):** auth, models, `LandmarkEditor` (React), seed 6 avatars by command, own-body flow (with delete and yearly
  measurement change), avatar flow, garment upload with AI cleaning (prompts 01, 04), landmark marking, mesh-warp try-on engine.
  Body AI validation (prompt 02) is recommended for P0 (open question 12).
- **P1:** realistic render (05), saved outfits.
- **P2:** public garments, AI moderation (03), report button, admin queue.
P0 is large: if behind schedule, cut in the order given in `docs/08`. Keep a **demo mode** with precomputed results
for about 10 garments in case the network/API is slow.

## Frontend and design
- Build the UI from `design/` (previews first, `design/tokens.md` for the theme): React + TypeScript, desktop web first, stacks on narrow widths.
- Do not copy `.dc.html` files into the app; rebuild components. Sample names and silhouettes in them are placeholders.
- Build the states the design does not show (loading, empty, error, polling, limits, confirmations): list in `docs/10`.

## Conventions
- AI jobs are asynchronous: the client polls `GET /jobs/{id}`; show a "preparing" state.
- Validate every AI response with Pydantic (schemas follow the JSON blocks in `prompts/`).
- Landmark names are fixed (`docs/03`); garments reuse the same names; deformation pairs them by name.
- Frontend and backend both run the landmark sanity checks (client is only a convenience).
- Tests must cover: immutability, yearly measurement limit, body deletion cascade, permissions (404 for other users),
  sanity checks, fail-closed AI parsing, 600x1200 canvas, daily limit rules, originals deleted after processing.
- Commands (fill in after scaffolding, keep README in sync): run, test, lint, seed avatars, migrate.

## Status and next step (READ THIS FIRST in a new session; keep it updated at the end of every step)
Last updated: 2026-11-09. The first task (summary + plan) is done. The owner approved the 10-step plan below.
Work it top to bottom, one step per turn, and tick the box when a step is done and tested.

- [ ] 1. Day-1 experiment, properly: 3 real male avatars (avatar-prep + landmark editor), fix sleeves
      (anchor shoulder->about 40% of the arm, not down to the hand), per-leg pants on real separated legs.
      Then log the scanline-vs-mesh decision (docs/09 item 19, docs/06). **Blocked on the owner: real avatar photos.**
- [x] 2. Frontend and backend agree: API contract in docs/04 + `frontend/src/api/types.ts`; paths/fields fixed.
      Not run or type-checked yet (no tooling on the Mac). **Git init + first commit still pending** (needs git:
      `xcode-select --install`). Do the commit first thing once git exists.
- [ ] 3. Hard-rule bugs + tests: body delete must delete its outfits + files (Outfit.body is SET_NULL today);
      account delete must delete the user's garments + files (Garment.owner is SET_NULL); drop the open `/media/`
      static route in `tryon_studio/urls.py`; AI fails closed (`run_body_validation` approves everything today).
      (Already fixed in step 2: try-on rejects others' unapproved public garments; first measurements don't start the lock.)
- [ ] 4. Own-body pipeline: code checks -> rembg -> normalize 600x1200 -> delete original -> strip EXIF -> prompt 02
      (`google-genai` SDK, Pydantic) -> daily AI limit -> auto landmark detection returned in `GET body/`.
- [ ] 5. One `LandmarkEditor` (port of `tools/landmark-editor-prototype`) for body + garments; sanity checks client + server.
      Body confirm page must send the edited landmarks to `POST body/confirm/` (BodyConfirm.tsx has a TODO).
- [ ] 6. Garment pipeline: prompts 01 + 04, quality check, Save/Cancel preview (screen 8), delete original, visibility (screen 9).
- [ ] 7. Avatar path: all measurements required in `avatars/nearest/`, adjust landmarks to measurements, screens 3 + 6.
- [ ] 8. Try-on: hands/forearms above the garment, `quality_warnings[]`, explicit `POST outfits/` save, screens 10-12 per design.
- [ ] 9. Test suite (list in Conventions), demo mode, README commands verified.
- [ ] 10. P1 if time: realistic render (prompt 05).

Open questions for the owner (ask once, then log the answers in docs/09):
which build day we are on; whether real avatar photos exist; scanline instead of mesh warp OK;
where the stack runs (this Mac has no Docker/Node/Python/git).

Known gaps that are not bugs in the contract: frontend pages do not follow the design yet (nav names, missing screens
3, 5, 6, 8, 9, 12, emojis, no locale file). Seeded avatars are drawn placeholders from `seed/avatars.reference.json`.
