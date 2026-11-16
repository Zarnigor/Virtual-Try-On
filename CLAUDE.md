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
- **Garment fit is per garment** (`fit_mode`: `adapt` default | `keep_shape`, docs/09 #93); `gender` female|male|unisex.
  Garment real size is NOT entered. No tight/loose fit label. **keep_shape = MLS per-point k preset A** (docs/09 #96,
  shoulder_* marked at the sleeve seam); wired only in the MLS engine (docs/09 #98). **MLS is the default T-shirt
  engine (`TRYON_WARP=mls`, docs/09 #105);** adapt T-shirts = sleeve C + tube + armpit r14 + side floor "mask" +
  garment hem + cuff hem + fringe drop (flags `TRYON_MLS_*`, docs/09 #105, #106); every T-shirt gets the r17
  finish (`TRYON_FINISH`, docs/09 #107) and so do pants (`TRYON_FINISH_PANTS`, docs/09 #108); an adapt T-shirt hangs
  over the pants (`TRYON_PANTS_TUCK`, docs/09 #109); `parts` = pants, the MLS fallback, and warps keep_shape like adapt.
  **The hem rule is NOT decided.**
  Garment gender is enforced in try-on (#97): body `sex` is required at upload; mismatch -> 400 `GENDER_MISMATCH`.
- **Model (avatar) path: numeric measurements are required.** Own-body path: measurements optional.
- Garment AI cleaning (hanger/background removal, prompt 04) is in P0 but **off for now** (`AI_CLEANING_ENABLED=0`, no prepaid
  image credits, docs/09 #55): garments are cleaned by rembg only.
- Realistic render is saved with the outfit. Originals are deleted after processing.

## Hard rules (do not break)
- **One body per user, photo/landmarks immutable after confirmation.** Enforce in the backend (unique `user_id`, no PUT/PATCH for
  photo/landmarks, upload while a **confirmed** body exists fails with 409). A hidden frontend button is not enough.
  An upload while an **unconfirmed** body exists replaces it (docs/09 #33).
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
- **AI fails closed, both ways**: invalid/empty AI JSON means rejected, and `ok: true` with contradicting fields is rejected
  with codes derived from those fields. AI returns codes; the backend maps codes to Uzbek messages.
  "AI could not answer" (`AI_UNAVAILABLE`, `AI_RESPONSE_INVALID`) shows "try again later", never "photo rejected".
- Daily limit on AI-reaching upload attempts per user (default 5), race-safe (`select_for_update`, slot reserved before the
  request). Counts responses incl. `AI_RESPONSE_INVALID`; does not count `AI_UNAVAILABLE`, code-check rejections or bypassed jobs.
- Gemini is called over plain `httpx` (no Google SDK). Tests never make real HTTP calls (`httpx.MockTransport` + guard).
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
| `docs/11-session-handoff.md` | End-of-session handoff: git state, done / not done, next steps, commands |
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
**Latest handoff: `docs/11-session-handoff.md` section 0 (2026-11-16): both finish sessions are done, the project is
shown as a live demo on 2026-11-17 (README "Live demo", docs/09 #109-#111). Read it first.**
Last updated: 2026-11-16. The first task (summary + plan) is done. The owner approved the 10-step plan below.
Work it top to bottom, one step per turn, and tick the box when a step is done and tested.

- [ ] 1. Day-1 experiment, properly: 3 real male avatars (avatar-prep + landmark editor), fix sleeves
      (anchor shoulder->about 40% of the arm, not down to the hand), per-leg pants on real separated legs.
      Then log the scanline-vs-mesh decision (docs/09 item 19, docs/06).
      **2026-11-10:** real photos seeded (`seed_avatars --from /avatars`, docs/09 #56); engine reworked and scanline kept
      (docs/09 #57, docs/06 "Engine as built"); before/after check `tools/tryon_check/run.py`. Left: staff landmark editor.
- [x] 2. Frontend and backend agree: API contract in docs/04 + `frontend/src/api/types.ts`; paths/fields fixed.
      Committed (e54f802). Environment runs (2026-11-09): Docker via OrbStack, all 5 services up, `manage.py check`,
      migrations and `tsc --noEmit` clean; a 30-check API smoke test passed (register -> body -> garment clean ->
      landmarks -> try-on 600x1200 -> deletes, plus 404/409 permission cases). How to run: README "Environment and commands".
- [x] 3. Hard-rule bugs + tests (done 2026-11-09, 34 tests pass: `docker compose exec -T backend python manage.py test apps`).
      Body delete cascades to outfits; account delete cascades to garments; files removed by post_delete signals
      (`apps/files.py`); open `/media/` route removed; AI fails closed (`apps/jobs/ai_schemas.py` Pydantic parser,
      `apps/jobs/tasks.py`), a rejected upload is deleted so the user can retry. `AI_DEV_BYPASS=1` (DEBUG only, set in
      docker-compose) skips the not-yet-wired AI calls for local testing and marks `result.ai_skipped`.
- [ ] 3b. NOW: owner tests with real clothes (garment upload -> rembg -> landmark dots -> try-on on a placeholder avatar).
      The owner sends the findings separately: log them in docs/09 before starting step 4.
- [ ] 4. Own-body pipeline. **Plan approved 2026-11-09, full spec in docs/09 items 22-34. Do NOT start coding until the 3b
      findings have arrived.** (Items 35-36 add: finalized job = no-op on start; `Body.current_job` + `SUPERSEDED`
      check before finalizing, with a two-quick-uploads test.) Summary: EXIF strip -> rembg -> code checks -> normalize 600x1200 -> auto landmarks in
      `GET body/` -> race-safe AI slot -> prompt 02 on the ~1024 px original via `gemini-3.6-flash` over httpx -> fail-closed
      parse (both ways) -> delete original in `finally`. Plus: `AI_UNAVAILABLE` vs `AI_RESPONSE_INVALID` (metric endpoint),
      `acks_late` + poison-pill guard, Celery beat (orphaned originals > 1 h, stuck jobs > 15 min via conditional UPDATE),
      re-upload replaces an unconfirmed body, `AI_DEV_BYPASS=1` always skips. Remove `google-generativeai` from requirements.
      Tests: MockTransport + real-HTTP guard, PostgreSQL `TransactionTestCase` race for the last slot; one manual real-API check
      of the generated `responseJsonSchema` (ask the owner before sending it).
      **2026-11-16 (docs/09 #110):** the upload job runs the shared pipeline (code checks, 600x1200, auto landmarks,
      original deleted); upload over an unconfirmed body replaces it; confirm runs the landmark checks. **Prompt 02
      is still not wired:** the submission runs with `AI_DEV_BYPASS=1` + `BODY_AI_CHECK_ENABLED=0` (owner decision).
      Check: `tools/tryon_check/own_body_path.py` (17 checks ok). 401 backend tests.
- [ ] 5. One `LandmarkEditor` (port of `tools/landmark-editor-prototype`) for body + garments; sanity checks client + server.
      **Partly done (2026-11-09, branch `landmark-editor-variant-c`):** garment editor rebuilt from design artboard VariantC in
      `frontend/src/components/landmark-editor/` (pure `geometry.ts` + `garmentGroups.ts` + component), used by
      `pages/LandmarkEditor.tsx`; rules in docs/09 #37-41; 13 vitest tests (`npm test`). Not yet checked by hand in the browser.
      **Garment sanity checks done (2026-11-09, docs/09 #53-54):** server `apps/garments/landmark_checks.py` (400
      `LANDMARKS_INVALID`), editor clamps moves to the order rules (4 px gap), Save needs every point placed. 35 vitest tests.
      Body groups + body checks done for the staff editor (docs/09 #72). Still to do: BodyConfirm wiring + checks at confirm. No ESLint config exists yet (`npm run lint` fails).
      **Done 2026-11-16 (docs/09 #110):** BodyConfirm is the editor with the body groups and sends the landmarks.
      **2026-11-11 (docs/09 #92):** extended T-shirt set (armpit, collar, collar_bottom, cuff corners replace
      sleeve_end), `landmarks_complete`, client + server checks; locale file `frontend/src/locale/uz.ts`.
- [ ] 6. Garment pipeline: prompts 01 + 04, quality check, Save/Cancel preview (screen 8), delete original, visibility (screen 9).
      **Prompt 01 done (2026-11-09, docs/09 #45-51, uncommitted):** garment AI check in `run_garment_cleaning` (httpx client
      `apps/jobs/gemini.py`, cache `ai_cache.py`, race-safe daily slot `limits.py`, `WRONG_GARMENT_TYPE`, `Garment.ai_skipped`
      + frontend dev warning). Committed (17644c8..5727582); separate daily limits per kind (#52). **Real-API check done 2026-11-09 on `gemini-3.5-flash-lite`:**
      8/8 verdicts as expected (6 photos + 2 wrong-type runs), responseJsonSchema accepted, 1.5-18 s per call. The earlier
      model (`gemini-3.8-flash`, still in .env) timed out / 503'd. Owner to choose the .env model. Owner to review the defaults in #47-49.
      **2026-11-10 (docs/09 #55):** prompt 04 behind `AI_CLEANING_ENABLED` (default 0, rembg only; 1 = stub that fails
      clearly). `AI_DEV_BYPASS` defaults to 0 in `.env.example` and docker-compose: set `AI_DEV_BYPASS=1` in `.env` for
      local testing without a key (body uploads fail closed with `AI_UNAVAILABLE` otherwise, prompt 02 is not wired).
      100 backend tests, tsc, 35 vitest pass. Still to do: prompt 04 (needs credits), quality check, Save/Cancel, delete original.
- [ ] 7. Avatar path: all measurements required in `avatars/nearest/`, adjust landmarks to measurements, screens 3 + 6.
      **2026-11-16 (docs/09 #110):** `avatars/nearest/` requires sex + 4 measurements; the try-on page has the form.
      Not done: landmarks adjusted to measurements, screens 3 + 6 as designed.
- [ ] 8. Try-on: hands/forearms above the garment, `quality_warnings[]`, explicit `POST outfits/` save, screens 10-12 per design.
      **2026-11-10 (docs/09 #79-84, docs/06 "Layer order" + "Known limits"):** compositing restructured into one layer
      order (pants -> shoulder cap -> torso -> rigid sleeves -> head/neck -> hands), row warp by `cv2.remap`, flags
      `TRYON_SHOULDER_CAP` / `TRYON_HEM_SNAP` / `TRYON_HALO_REMOVAL` (default 1). Contact sheets:
      `tools/tryon_check/matrix.py`. Demo results are stale until `build_demo` is run again. Owner to confirm #82.
      **2026-11-10 round 4 (docs/09 #86-88):** T-shirt sleeves own their pixels (no seams/doubled edge), clipped below the
      shoulder slope line; halo fix once on the outer contour; cap colour from the shoulder rows; smooth neck edge;
      `TRYON_NECK_GAP_FILL` (default 1). Demo rebuilt. 212 backend tests pass.
      Neck-gap fill runs for admin avatars only (`render_tryon(source="avatar")`), never for an own body (docs/09 #89).
      Dropped-shoulder one-piece warp for #36 built behind `TRYON_DROPPED_SHOULDER_SINGLE`, default 0 (sleeves shear
      below the armpit; docs/09 #90).
      T-shirt hem rule `TRYON_HEM_RULE` (default 1, proposed, docs/09 #91): hem at hip + 0.35 x (crotch - hip).
      **2026-11-11 (docs/09 #93-98):** per-garment `fit_mode` + `gender`; gender enforced in try-on (`GENDER_MISMATCH`,
      `BODY_SEX_REQUIRED`, `for_sex`); MLS single-field T-shirt warp in `apps/tryon_engine/mls.py` behind
      `TRYON_WARP=parts|mls` (default `parts`, falls back with `mls_fallback`). keep_shape = preset A only on `mls`.
      **Owner to decide: parts vs MLS as default, and the hem rule (#91 / docs/09 "Still open").**
      **2026-11-12 round 8 (docs/06, NOT production, uncommitted):** MLS sleeve variants r7|A|B|C as the keyword
      `mls.tshirt_layer(sleeve_variant=)` (default r7, pixel-identical: `MlsR7RegressionTests`, gitignored fixture).
      Table + sheets in `tools/warp-benchmark/out/` (`run_sleeve8.py`). Owner to review; no winner picked.
      **2026-11-12 round 10 (docs/06, NOT production, uncommitted):** side coverage floor, keyword
      `mls.tshirt_layer(side_floor=)` (default False, pixel-identical: `MlsSideFloorOffRegressionTests`). `table10.md` +
      `sheet_sidefloor_<id>.png` (`run_sidefloor10.py`). Oversized on/off not negligible (see docs/06). No winner picked.
      **Update:** oversized path restored: default 0 px (#44/#45, 24 renders); side_floor disabled for keep_shape;
      adapt + side_floor on #44/#45 still differs (owner to decide). Round 10 work paused until the owner says so.
      **2026-11-12 round 8b (docs/06):** sleeve variants re-measured with re-marked landmarks + `shoulder_top_skin_px`
      (`run_sleeve8b.py`, `table8b.md`, `sheet_sleeve8b_<id>.png`). No winner picked.
      **2026-11-12 neckline (docs/06 "V-neck opening"):** `mls.tshirt_layer(neckline_variant=r7|clear|clear_skin)`,
      default r7 (0 px), `run_neck.py`, `table_neck.md`, `sheet_neck_<id>.png`. No winner picked.
      **Decided 2026-11-12 (docs/09 #99):** avatars re-shot as real photos in one low round-neck tank; V necks use
      `hole` + `neck_clip` (benchmark), the skin-fill variants are not used. Waiting for the new avatar photos.
      **2026-11-13 (docs/09 #100-101):** owner polygon `hole` works for V, crew (#28) and square (#47) necks; `clear` is
      not used when a polygon exists; `neck_clip` NOT used (clips the crew shoulder). **Collar floor is the MLS default**
      (`collar_floor_on=True`, regression fixtures pinned with False). 301 backend tests pass. Open: who marks the polygon.
      **2026-11-13 (docs/09 #102, uncommitted):** neckline hole in the product: every owner marks it, two-step T-shirt
      editor (step 2 `/garments/{id}/neck`: collar points + polygon), `landmarks.neck_hole.polygon`, `neck_complete`,
      render wiring MLS + adapt only behind `TRYON_NECK_HOLE` (default 1), `neck_hole_invalid` warning. **The hole works
      only with TRYON_WARP=mls.** Suggestion: shape buttons V / Dumaloq / Toʻrtburchak, created once, two edit modes.
      324 backend tests, 78 vitest, tsc clean.
      **2026-11-13 (docs/09 #103, uncommitted):** the hole applies to keep_shape too (the adapt-only check in
      `warp._neck_hole_kwargs` removed); no polygon = pixel-identical as before.
      **2026-11-13 round 9 / 9b (docs/06 "Shoulder line fit, round 9"):** shoulder line benchmark (keywords
      `shoulder_variant`, `shoulder_fractions`, `shoulder_ease`, `shoulder_edge_alpha`, all default off / round 9).
      **Decided (docs/09 #104): production MLS uses sleeve variant C** (`TRYON_MLS_SLEEVE`, default C), shoulder line
      not used. 335 backend tests pass.
      **2026-11-15 rounds 11 / 12 / 12b (docs/06, NOT production, uncommitted):** benchmark keywords `sleeve_mode`,
      `side_floor_mode`, `hem_mode` (smooth | garment), `tube_arm` (r11 | fit), `hem_c_pair`, all default off. "mask"
      now never uncovers the landmark floor layer (local map blend + last guard). Runner `run_hem12b.py`. No winner
      picked; owner reviews the 12b sheets. 353 backend tests pass.
      **2026-11-15 round 13 (docs/06, NOT production, uncommitted):** `tube_arm` finished (a + b) failed the gate
      (18 / 18, cuff-edge halo band); fallback finished_a: 0 new holes. `run_tube13.py`. 355 backend tests pass.
      **Round 13b:** a + b kept, cut edge out of remove_halo, enclosed sleeve holes filled: GATE 0 / 18.
      **Round 13c (armpit):** armpit_zone + inner widening + zone inpaint: GATE 0 / 18; slim wedge below the cuff
      (arm side) and a seam line along the tube inner edge still open. 356 backend tests pass.
      **2026-11-15 round 14 (docs/06 "Armpit wedge, round 14", NOT production, uncommitted):** keyword
      `armpit_mode` (off | r13c | r14, default off; replaces `armpit_fix`, so "finished" = 13b again). r14 = the
      garment's torso seam pinned to the arm/torso boundary (cuff row -> crease) in a local window + arm-side cut:
      #28 wedge 0 px on 12 / 12 sides; gate fails 8 / 18 (#43 arm skin under its curved cuff, 1 px on #40).
      `run_armpit14.py`, `debug_armpit14.py`. Owner agreed to delete r13c after the review. 363 backend tests pass.
      **2026-11-15 production wiring (docs/09 #105, docs/06 "Production wiring"):** `TRYON_WARP` default `mls`; adapt
      T-shirts get the round 14 config through `render_tryon`; flags `TRYON_MLS_TUBE` / `_SIDE_FLOOR` / `_ARMPIT` /
      `_HEM` (off = before); `tube_fallback`; job result `tshirt_config` + `render_ms`; r13c deleted. Gates: production
      = benchmark 0 px (18 pairs), keep_shape 0 px. Known issues in #105 (gate 8 / 18, ~1.1 s render, demo results
      stale). Check tools: `tools/tryon_check/prod_vs_bench.py`, `post_path.py`. 369 backend tests, 78 vitest, tsc.
      **2026-11-15 rounds 15 / 16 + production (docs/09 #106, docs/06 "Cuff hem, round 15", "Tube fringe, round 16",
      uncommitted):** keywords `cuff_mode` (chord | hem) and `tube_fringe` (keep | drop), tube sleeves only. hem = the
      garment's real sleeve hem lands on the cuff line (owner option A): gate 0 / 18 (before 8 / 18), arm skin above
      the cuff 0 px, spikes 233 -> 82. drop = the tube's photo-fringe px over solid fabric are not drawn (the faint
      line on the sleeve's inner edge): 606 line px -> 0, 0 new holes. **Both in production:** flags `TRYON_MLS_CUFF`
      (hem | chord), `TRYON_MLS_FRINGE` (drop | keep), `tshirt_config.cuff` / `.fringe`; production = benchmark 0 px
      (18 pairs), keep_shape 0 px. `run_cuff15.py`, `run_fringe16.py`. 379 backend tests, 78 vitest, tsc.
      Still open: stepped torso edge on #28, render ~1.2 s, r14 skip on older landmarks, demo results stale.
      **2026-11-16 round 17 + production (docs/09 #107, docs/06 "Finish pass, round 17", uncommitted):** keyword
      `render_tryon(finish="r60" | "r17")`; r17 = `smooth_edges` (nothing eroded) + form shading from the garment
      outline + contact shadow (also on the arm under the cuff). **In production for T-shirts only:** setting
      `TRYON_FINISH` (r17 | off, default r17), job result `finish`; pants untouched (their own round after the owner
      uploads 2-4 pants). Gates: production = benchmark r17 0 px, off = before 0 px, new holes 0 / 30
      (`run_finish17.py`, `VARIANTS=off,r17,prod,setting_off`). 389 backend tests, 78 vitest, tsc.
      **2026-11-16 rounds 17b / 17c + production (docs/09 #108, docs/06 "Finish pass on pants, round 17b",
      "Finish pass on outfits, round 17c", uncommitted):** `render_tryon(finish_pants=True)`; pants #18, #48, #49,
      #51 x 6 avatars and 5 T-shirt + pants outfits x 6: 0 new holes. **In production:** setting
      `TRYON_FINISH_PANTS` (1 | 0, default 1, needs `TRYON_FINISH=r17`). Gates 0 px (`run_finish17.py` with
      `PANTS=1`, `run_finish17c.py`). 390 backend tests, 78 vitest, tsc. Not measured: shorts, white / black pants.
      **2026-11-16 round 18 + production (docs/09 #109, docs/06 "Pants under the T-shirt, round 18"):** an adapt MLS
      T-shirt hangs over the pants (`warp.drape_over_pants` + `tuck_pants`, setting `TRYON_PANTS_TUCK`, default 1);
      pants px beside the T-shirt 57043 -> 6359 on 18 adapt renders, figure px uncovered 0; keep_shape untouched.
      `run_tuck18.py`.
      **2026-11-16 round 19 + production (docs/09 #112, docs/06 "keep_shape scale, round 19"):** keep_shape T-shirts
      scaled by `mls.keep_shape_scale` (setting `TRYON_MLS_KEEP_SCALE`, default fit): body covered, hem below the hip;
      worse: the garment floats higher over the shoulders and the sleeves stand out more (next: seam on the arm,
      sleeves along the arm). 402 backend tests.
- [ ] 9. Test suite (list in Conventions), demo mode, README commands verified.
      **2026-11-10:** demo mode done (docs/09 #58, README "Demo mode"; 18 results: 1 T-shirt + 1 pants x 6 avatars).
      README rewritten (run, demo, architecture, known limits). 123 backend tests, tsc, 35 vitest pass.
      **2026-11-12:** 267 backend tests, tsc, 57 vitest pass. Check tools added: `tools/tryon_check/landmarks_overlay.py`
      (landmark overlays + docs/03 checks, read-only), `neck_regress.py` (TRYON_NECK_FIX off/on diff). No ESLint yet.
- [ ] 10. P1 if time: realistic render (prompt 05).

Open questions for the owner (ask once, then log the answers in docs/09):
which build day we are on; whether real avatar photos exist; scanline instead of mesh warp OK.
Environment: everything runs in Docker (OrbStack). The Mac has git but no host Python/Node: run Python and npm inside the
containers (`docker compose exec -T backend ...`, `docker compose exec -T frontend ...`). Add `~/.orbstack/bin` to PATH.

Known gaps that are not bugs in the contract: screens 3, 6, 8, 9 are simpler than the design (docs/09 #111). Avatars are real photos (`./avatars`, not in git); the drawn placeholders are only created when an avatar is missing.
