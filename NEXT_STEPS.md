# Next steps (written 2026-11-16, end of day)

Start the next session here. This file lists only what is still to do and how to pick it up. The history of
every round is in `docs/06-try-on-engine.md` (engine) and `docs/09-open-questions.md` (decisions, last #115).
Working rules: `CLAUDE.md` "How to work with me" and the memory note `owner-working-rules`
(plan first and wait for OK, one item per round, numbers only, no new holes, clean full images to review).

Qisqacha (oʻzbekcha): loyiha jonli demoga tayyor. Keyingi ish: (1) yenglar, (2) oversize futbolkalar,
(3) futbolka choʻzilishi va etak qoidasi, (4) shimdagi qoldiqlar, (5) mahsulotdagi ochiq qismlar.
Har bir bandni boshlashdan oldin reja koʻrsatiladi va egasining roziligi kutiladi.

## 1. State

- Branch `tshirt-mls-default`; `main` was fast-forwarded to it. **No git remote, nothing pushed.**
- Last commit: `fix: pants leftovers in warp_pants_fit (docs/09 #115)`. 407 backend tests, 78 vitest, `tsc` clean.
- Not committed on purpose: `prompts/04-garment-cleaning.txt` (a stray "is" on line 1, ask the owner or revert it)
  and `smt.txt` (the owner's notes: garment ids and names).
- The project is shown as a **live demo on the owner's machine** (2026-11-17). README "Live demo" has the
  pre-flight check and the walk-through.
- Local `.env` (not in git): `AI_DEV_BYPASS=1`, `BODY_AI_CHECK_ENABLED=0`, `DEMO_MODE` unset (0).
- Production engine settings (all default on, the second value = the behaviour before; full list in
  `.env.example` and README):
  `TRYON_WARP=mls`, `TRYON_MLS_SLEEVE=C`, `TRYON_MLS_TUBE=1`, `TRYON_MLS_SIDE_FLOOR=mask`, `TRYON_MLS_ARMPIT=r14`,
  `TRYON_MLS_HEM=garment`, `TRYON_MLS_CUFF=hem`, `TRYON_MLS_FRINGE=drop`, `TRYON_FINISH=r17`,
  `TRYON_FINISH_PANTS=1`, `TRYON_PANTS_TUCK=1` (#109), `TRYON_MLS_KEEP_SCALE=fit` (#112),
  `TRYON_MLS_TUBE_CLIP=arm` (#113), `TRYON_PANTS_ENGINE=rows` (#116; `fit` = #114, #115), `TRYON_PANTS_FIT_X=1` (#118).
- Garments in the DB used for checks: T-shirts #28 (black, male), #40 (blue V, female), #43 (white fitted,
  female), #47 (brown square neck, female), #44 / #45 (oversized; #44 keep_shape, #45 currently stored as
  adapt); pants #18 (demo), #48 (slit-hem jeans), #49 (pink), #51 (red joggers). 6 avatars: m/f x slim/average/plus.

## 2. First thing in the next session

1. `export PATH=$PATH:~/.orbstack/bin`, `docker compose up -d`, wait for `http://localhost:5173`.
2. `docker compose exec -T backend python manage.py shell < tools/tryon_check/own_body_path.py` must print `ALL OK`.
3. **Ask the owner what they saw in the live demo / in the browser** and log it in docs/09 (#116 onward). Fix
   those reports before anything below. Claude has not opened the new pages (Tana, Profil, Bosh sahifa, body
   confirm editor, avatar measurements form) in a browser: check them by hand or with the owner.

## 3. Open work, in the proposed order (owner decides)

### 3.1 Sleeves (the owner said they are in a very bad state; round 20 fixed the chest flap only)
- **keep_shape sleeves stand out sideways** (#44): keep_shape has no tube, the sleeve keeps the photo's angle.
  Idea: a tube for keep_shape too (`mls.tube_sleeves`, today wired only for adapt in `warp._mls_adapt_kwargs`),
  with the garment's own sleeve width (no arm fit) and the axis turned to the arm direction (`arm_direction`).
- **#40 pinched cuff** (fabric lines squeezed at the sleeve end).
- **Dark dot at the armpit crease** (seen on #43 / #47 / #40, also before round 20).
- **#47 skin at the top of the shoulder**; **#45 ragged cuff px**.
- Gates as in round 20: `tools/warp-benchmark/run_clip20.py` style (new holes 0, px changed outside the sleeve
  band 0), sheets per garment x 6 avatars.

### 3.2 Oversized (keep_shape) T-shirts (report given to the owner on 2026-11-16, directions 1-3)
- Direction 1 (scale) is done (#112). Left: **direction 2**, the dropped shoulder seam laid along the arm line
  instead of standing above it (the garment floats 5-66 px above the shoulder / arm, most on the plus woman), and
  **direction 3**, sleeves along the arm (same as 3.1 first bullet).
- **The fit scale is wrong for narrow garments used as keep_shape** (#47 as keep_shape becomes far too big). Idea:
  apply `keep_shape_scale` only when the garment is really wide (its chest width / shoulder width ratio), else the
  shoulder scale. Needs the owner's OK (it changes keep_shape output).

### 3.3 Adapt T-shirt stretch and the hem rule
- Adapt stretches a short, fitted T-shirt (#47 x1.17-1.28 in length, x1.60 at the hem on the plus woman), so its
  ruching / stripes bend. Idea: cap the length stretch (about x1.10, a short T-shirt stays short).
  **Blocked by the hem rule decision (docs/09 #91, still open): ask the owner.**
- **#47 hem corners stick out ("ears") on the plus woman**; `drape_over_pants` (#109) enlarges them about x1.25.
  Fix: exclude the hem's own corner rows from the drape stretch (`warp.drape_over_pants`), then rerun
  `run_tuck18.py` (gate: figure px uncovered 0).
- Stepped torso edge (2-5 px) beside the armpit gap on #28.

### 3.4 Pants (rounds 21-22 done)
- Slim jeans #48 on the plus woman need 1.75 x the garment width (limit `PANTS_FIT_MAX` 1.7, a warning): decide
  whether to raise the limit or accept it.
- #48's own hem slit leaves 223 px of ankle visible versus the old engine: the owner should confirm this is right.
- Shorts and white / black pants are not measured (ask the owner to upload some).
- Runners: `tools/warp-benchmark/run_pants21.py` (rows vs fit, alone), `run_tuck18.py` (with a T-shirt).

### 3.5 Performance and demo data
- Adapt T-shirt render about 1.1-1.5 s (was 0.15 s): measure per step (side floor last guard, second MLS solve of
  r14); output must stay pixel-identical (`tools/tryon_check/prod_vs_bench.py`).
- Demo results (`build_demo`) were built before rounds 19-22 and use a T-shirt with the old landmark set: rebuild
  only when the owner wants `DEMO_MODE=1`.

### 3.6 Product (step list in CLAUDE.md, none blocks the demo)
- Body AI check (prompt 02) is not wired: `apps/jobs/tasks.py:_ask_body_validation` returns None; spec in docs/09
  #22-36. Needs a Gemini key and the owner's OK for a real API check.
- Garment AI cleaning (prompt 04) off (no image credits); realistic render (prompt 05) not built.
- Garment upload has no Save / Cancel preview (screen 8); outfits are stored by every try-on (no explicit save).
- Avatar path: landmarks are not adjusted to the entered measurements; screens 3, 6, 8, 9 are simpler than design.
- Public garments, moderation (prompt 03), report button, admin queue (P2). No ESLint config.
- Hand-in: decide with the owner whether to add a git remote and push.

## 4. Commands

```
export PATH=$PATH:~/.orbstack/bin
docker compose up -d                                   # db, redis, backend :8000, worker, frontend :5173
docker compose exec -T backend python manage.py test apps --noinput      # 407 tests, about 5 min
docker compose exec -T frontend npx tsc --noEmit
docker compose exec -T frontend npm test -- --run
docker compose exec -T backend python manage.py shell < tools/tryon_check/own_body_path.py   # ALL OK
docker compose restart worker                          # after engine changes: the worker runs the old code otherwise
# benchmark runners write to /tmp/warp_benchmark in the container:
docker compose exec -T backend rm -rf /tmp/warp_benchmark
docker compose exec -T backend python manage.py shell < tools/warp-benchmark/<runner>.py
docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/
```
Engine changes follow one pattern: a keyword whose own default is the old behaviour, a runner with before | after
sheets and a gate (new holes 0), then a setting in `settings/base.py` (+ `flags.py`, `docker-compose.yml` x2,
`.env.example`, README, `frontend/src/api/types.ts` if the job result changes), regression fixtures in
`tests_neck_hole.py` pinned to the old values, docs/06 + docs/09 entries, CLAUDE.md status line.
