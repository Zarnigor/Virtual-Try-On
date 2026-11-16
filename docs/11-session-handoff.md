# Session handoff (last updated 2026-11-15)

Read this first in a new session, together with CLAUDE.md "Status and next step". It records what is finished,
what is NOT finished, and what to do next. Details and numbers: docs/06 (engine rounds), docs/09 (decisions).

## 0. Next session (written 2026-11-15, end of day): start here

**State.** Branch `tshirt-mls-default` (from `landmark-editor-variant-c`, not merged, not pushed): `9584166` bench:
rounds 11-14, `104c891` feat: MLS default + adapt config in production (docs/09 #105). On top of it (2026-11-16): one
`feat:` commit with rounds 15 / 16 (docs/09 #106) and the round 17 finish (docs/09 #107), one `bench:` commit with
the runners `run_cuff15.py`, `run_fringe16.py`, `run_finish17.py`; where sections below say "uncommitted" for
rounds 15-17, that is history. Rounds 11-14 are CLOSED by
#105 (sections 1 and 3 below describe them as open / uncommitted: history only). `smt.txt` stays untracked. This
section itself is not committed yet.

**First, ask the owner** what they saw when testing on localhost:5173 after the wiring, and log it in docs/09.

**Open work, in the order proposed (owner decides; plan first, one item per round):**
1. Render time of an adapt T-shirt, about 1.0-1.5 s (was about 0.15 s). Likely the side floor "mask" last guard,
   which builds a second full layer (`mls.tshirt_layer` calls itself), plus the second MLS solve of r14. Measure per
   step first; the output must stay pixel-identical (`ProductionTshirtConfigTests`, `tools/tryon_check/prod_vs_bench.py`).
2. **DONE, in production, uncommitted (docs/09 #106): rounds 15 (cuff hem) and 16 (tube fringe drop).** Flags
   `TRYON_MLS_CUFF`, `TRYON_MLS_FRINGE`; gates 0 / 18, production = benchmark 0 px, 379 backend tests. Ask the owner
   whether to commit (suggested: one `bench:` commit for the keywords + runners, one `feat:` commit for the wiring).
   The item as it was before round 15:
   #43 cuff slivers: arm skin 2.5-5.8 px above the nominal cuff line under the garment's curved cuff (round 14
   gate fails on 8 / 18 runs; also #40 m-plus, 1 px on #40 m-slim). A cuff-shape change in the tube (the tube maps
   the straight chord between the cuff landmarks to the cuff line), not the armpit code.
2b. **Round 17, finish pass (2026-11-16, benchmark only, uncommitted; docs/06 "Finish pass, round 17"):**
   `render_tryon(finish="r17")` + `warp.soft_coverage` / `smooth_edges` / `form_shading_map`, runner
   `tools/warp-benchmark/run_finish17.py`, tests `FinishR17Tests`. Defaults unchanged (realism flags 0, finish r60).
   **Owner chose r17; in production for T-shirts only (docs/09 #107, uncommitted):** setting `TRYON_FINISH`
   (r17 | off), job result `finish`, tests `FinishWiringTests`; 389 backend tests, 78 vitest, tsc. Pants: their own
   round after the owner uploads 2-4 pants (only #18 exists). The reference layers of #43 / #40 changed by
   4-44 hard edge px between the 10:36 and 11:25 runs on 2026-11-16: the owner re-marked their landmarks in
   between (confirmed), not an engine change.
   **Round 17b, pants (benchmark only, uncommitted; docs/06 "Finish pass on pants, round 17b"):** the owner
   uploaded pants #48, #49, #51; `render_tryon(finish_pants=True)` + `run_finish17.py` with `PANTS=1`: r17 0 new
   holes on 24 renders; round 17c (`run_finish17c.py`, 5 outfits x 6 avatars): 0 new holes. **In production
   (docs/09 #108, uncommitted):** setting `TRYON_FINISH_PANTS` (1 | 0). 390 backend tests, 78 vitest, tsc. Not
   measured: shorts, white / black pants. The pants #48, #49, #51 are stored as `unisex`. Ideas after it, in the proposed order: side ease + smooth side line, hem rule (#91),
   armpit / cuff leftovers, keep_shape shoulder triangle, 2x resampling for moire.
3. Stepped torso edge (2-5 px) beside the gap below the armpit on #28 (seen in the `POST tryon/` check sheet).
4. Robustness of r14: it skips a side when `torso_side_edges` finds no arm-touch rows (older landmarks); r14 without
   a tube is built but not benchmarked (production switches the armpit mode off without the tube).
5. Demo mode: the 18 stored results were built with `parts` and are stale; rebuild with `build_demo` only when the
   owner says so.
6. Still undecided: the T-shirt hem rule (docs/09 #91). Merge / push of `tshirt-mls-default`: owner's call.
7. Then back to the 10-step plan in CLAUDE.md: 3b (owner's findings with real clothes), 4 (own-body pipeline, spec in
   docs/09 #22-36), 5 (BodyConfirm wiring), 6 (garment pipeline: quality check, Save / Cancel), 7 (avatar path).

**How to check by hand:** localhost:5173, log in as the garments' owner, try #28 on a male avatar, #43 / #40 on a
female avatar, #44 / #45 (keep_shape) on any; the job result (`GET /api/jobs/{id}/`) shows `tshirt_config` and
`render_ms`. Old behaviour for comparison: set `TRYON_MLS_TUBE=0`, `TRYON_MLS_SIDE_FLOOR=off`, `TRYON_MLS_ARMPIT=off`,
`TRYON_MLS_HEM=mls` in `.env`, then `docker compose up -d backend worker`.

## 1. Git state

- Branch: `landmark-editor-variant-c` (not merged to main, not pushed).
- Last commits:
  - `3a775c8` feat: MLS sleeve variant C in production (`TRYON_MLS_SLEEVE`, docs/09 #104); shoulder line keywords
  - `0495dab` bench: shoulder line rounds 9 / 9b runners
  - `6eee109` fix: neckline hole for keep_shape too (docs/09 #103)
  - `50ae5c8` feat: owner neckline hole, two-step T-shirt editor, collar floor (docs/09 #99-102)
  - `1cf6963` bench: rounds 8/8b, 10, neckline runners
- **UNCOMMITTED (rounds 11 and 12, benchmark only, nothing in production):**
  - `backend/apps/tryon_engine/mls.py`: keywords `sleeve_mode` ("mls" | "tube" | "tube_perp"), `side_floor_mode`
    ("landmarks" | "mask"), `hem_mode` ("off" | "smooth"); helpers `tube_sleeves`, `torso_side_edges`,
    `_add_side_floor_mask_pairs`, `smooth_hem`, `hem_bottom`, `_gauss1d`. All defaults = old behaviour, pixel-identical.
  - `backend/apps/tryon_engine/tests_mls.py`: `TubeSleeveTests`, `SideFloorMaskTests`, `HemSmoothTests`, helper `tube_zone`.
  - `docs/06-try-on-engine.md`: sections "Tube sleeve, round 11" and "Side coverage, round 12" (numbers only).
  - New tools: `tools/warp-benchmark/run_tube11.py`, `debug_tube11.py`, `render_tube11.py`, `run_side12.py`,
    `debug_side12.py`.
  - `smt.txt` = the owner's personal notes (garment links). Never commit it unless the owner asks.
- Tests at the end: **346 backend tests pass, none skipped** (`docker compose exec -T backend python manage.py test apps`).
  Frontend: 78 vitest, `tsc --noEmit` clean (last checked after the neck editor work).
- Ask the owner whether to commit the round 11 / 12 work (suggested: one `bench:` commit, it changes no defaults).

### Update 2026-11-15: round 12b (uncommitted, benchmark only; details and numbers in docs/06 "Hem and tube, round 12b")
- New keywords in `mls.tshirt_layer` (all default off, adapt only, render_tryon never passes them): `tube_arm`
  ("r11" | "fit": arm fit floor + clamp to arm x 1.25 + MLS px beyond the cuff cleared), `hem_mode="garment"`,
  `hem_c_pair`. side_floor_mode "mask" changed: local blend back to the landmark floor map + last guard (builds the
  landmark floor layer, ~2x runtime) -> 0 new holes in all 18 reference runs.
- Runner `tools/warp-benchmark/run_hem12b.py` (exit 1 while + hem_c fails: 18 runs, by design of that pair).
  Sheets `out/sheet_hem12b_<id>.png`, `out/sheet_tube12b_40.png`.
- Tests: `Round12bKeywordTests`, `TubeArmFitTests`, `SideFloorMaskNoNewHolesTests`, `HemGarmentTests`, `HemCPairTests`.
  353 backend tests pass, none skipped.
- Open: owner visual check of the 12b sheets; the underarm side strip on plus avatars is still open (the round 12
  "grey hole" island is gone, the open strip of the round 12 reference remains).

### Update 2026-11-15: round 13, tube finished (uncommitted, benchmark only; docs/06 "Tube sleeve finished, round 13")
- `tube_arm` "finished" (rules a + b, protected underarm zone) and "finished_a" (rule a only). Gate failed for a + b
  (18 / 18, 3-162 px, the 2 px halo band above the cuff line); fallback a: 0 new holes, jagged cuff px stay.
- Fix 4: the "mask" last guard compares with the same tube_arm. Runner `run_tube13.py`. 355 backend tests pass.
- Round 13b: a + b kept; the rule (b) cut is out of remove_halo, enclosed sleeve-zone holes filled (rule #63):
  GATE 0 / 18, holes enclosed 0. 355 backend tests pass.
- Round 13c (armpit): tube may draw in the armpit zone + inner widening + zone inpaint: GATE 0 / 18. Open: the
  slim avatars' grey wedge below the cuff on the arm side of the inner edge line, a light seam along the tube's
  inner edge. `run_armpit13c.py`. 356 backend tests pass.
- Round 14 (armpit wedge, docs/06 "Armpit wedge, round 14"): keyword `armpit_mode` ("off" | "r13c" | "r14",
  default "off"; replaces `armpit_fix`, tube_arm "finished" alone = round 13b again). Root cause: the garment's
  notch lands 1-74 px above the body's arm/torso crease, nothing owns the px between. r14 pins the garment's torso
  seam to the arm/torso boundary from the cuff row to the crease (local window, arm-side cut, local guard; no
  widening / inpaint). Wedge (L / R, 18 runs) 2952 / 2075 -> 55 / 145, #28 0 px on 12 / 12 sides, fragments 0,
  neck 0. Gate fails 8 / 18: #43 (6 runs) + #40 m-plus = arm skin 2.5-5.8 px above the nominal cuff line under the
  garment's curved cuff; #40 m-slim 1 px. Runtime + 0.23-0.43 s. `run_armpit14.py`, `debug_armpit14.py`,
  sheets `out/sheet_armpit14_<id>.png`, `out/sheet_armpit14_full_<id>.png`. 363 backend tests pass, none skipped.
  r13c was deleted with the production wiring (below); the #43 cuff slivers are a recorded known issue.
- **Production wiring (docs/09 #105, docs/06 "Production wiring"):** `TRYON_WARP` default `mls`; adapt T-shirts =
  sleeve C + tube "finished" + armpit r14 + side floor "mask" + garment hem via `render_tryon`
  (`warp._mls_adapt_kwargs`); settings `TRYON_MLS_TUBE`, `TRYON_MLS_SIDE_FLOOR`, `TRYON_MLS_ARMPIT`, `TRYON_MLS_HEM`
  (off value = before); `tube_fallback`; job result `tshirt_config`, `render_ms` (docs/04, types.ts, uz.ts).
  Gates passed (production = benchmark 0 px on 18 pairs, keep_shape 0 px, flags off = before, 369 backend tests, 78
  vitest, tsc). Check tools: `tools/tryon_check/prod_vs_bench.py`, `tools/tryon_check/post_path.py` (real
  `POST tryon/`, sheets in `tools/tryon_check/out/post_path/`). Known issues: round 14 gate 8 / 18, render ~1.1 s per
  adapt T-shirt (optimize the "mask" last guard later), demo results stale (owner: do not rebuild).
  After changing compose env: `docker compose up -d backend worker`.
- Pending owner: visual check of `out/sheet_tube13_<id>.png`, `out/sheet_armpit13c_<id>.png`; the production wiring is done (docs/09 #105).

## 2. What is DONE and in production (committed)

- **Neckline hole** (docs/09 #99-103): every garment owner draws the "Yoqa teshigi" polygon in step 2 of the T-shirt
  editor (`/garments/{id}/neck`), stored as `landmarks.neck_hole.polygon`; server rules in
  `apps/garments/landmark_checks.py`; `render_tryon` passes `neckline_variant="hole"` for MLS (adapt AND keep_shape),
  flag `TRYON_NECK_HOLE` (default 1); invalid polygon -> quality warning `neck_hole_invalid`. Polygons exist in the DB
  for #28, #40, #43, #45, #47.
- **Collar floor** is the MLS default (docs/09 #100).
- **MLS sleeve variant C** in production (docs/09 #104): setting `TRYON_MLS_SLEEVE` (default C).
- `TRYON_WARP` defaults to `mls` since docs/09 #105 (2026-11-15, committed in `104c891`);
  `parts` = pants, the MLS fallback, or `TRYON_WARP=parts`. The hem rule (#91) is still open.
- Not in production (render_tryon never passes them): `side_floor` (round 10), shoulder line (round 9 / 9b),
  tube sleeves (round 11), side_floor_mode / hem_mode (round 12).

## 3. Benchmark rounds: status

### Round 9 / 9b, shoulder line: CLOSED
Owner chose C (sleeve variant C, shoulder line off) -> docs/09 #104, in production.

### Round 11, tube sleeves: OPEN (no winner)
- Built: ruled strip "tube" and "tube_perp"; fixes 1-3 (cuff on the MLS cuff targets, width ramp with arm floor,
  axis_dev from `_arm_at`); layering fix (tube drawn OVER the MLS layer; MLS sleeve px cleared only over the background
  beyond arm + ease). Test "no new holes" in the shoulder / armpit / sleeve zone passes (0 px).
- Latest numbers (docs/06): tube arm-band skin 3273 / 3745 vs reference 5239 / 5541 (better); balloon 9564 / 8279 vs
  1607 / 2654 (worse); excess worse; 18 / 18 runs worse on at least one metric. tube_perp: skin slits at the shoulder
  join; worse.
- **Known problem:** jagged "MLS" cuffs are the MLS sleeve px left beside the tube over the arm. Clearing them over the
  arm (beyond half the axis) opened 117-144 px holes, because the tube's arm floor is too narrow (the arm extent is
  measured only outward of the armhole line). Reverted.
- **Next fix to propose (not built):** take the tube's arm floor from the real arm width (`mls._arm_at` = straight fit
  through the separated arm rows) instead of the march cut at the armhole line; then clear the MLS sleeve px beside
  the tube safely. #40 sleeves look puffy because tube width = garment width x s.

### Round 12, side coverage + hem: OPEN (no winner)
- Owner decision (visual check): **keep `side_floor_mode="mask"` as the base** (it removes the grey side strips).
- "mask" = landmark floor pairs (side_a, side_b, side_hip) PLUS pairs every 12 px from the mask torso edge
  (arm-touch rows interpolated, garment edge at HARD_EDGE alpha, 2 px ease), no rows in the hem band (8 % of torso
  length).
- Numbers (all garments): side strip 17359 / 7987 -> 10040 / 4423 (mask) -> 9635 / 4019 (mask + smooth).
- **Still broken:**
  1. **Hem tongue**: with "mask" the hem centre hangs down between the legs. hem_tongue max 16.0 (ref) -> 27.6 (mask),
     #28 7.5 -> 20.8. Removing the hem-band rows did NOT fix it. Hypothesis (not verified): the mask side pairs pull
     the hem sides out / up while `hem_c` stays.
  2. **New holes**: mask uncovers figure px the reference covered: side rows 2710 / 2985, hem band 18603 (the hem rises
     5-7 px between the hem pairs).
  3. **hem_mode="smooth"** helps only a little (hem wave 11.2 -> 9.5, ref 6.9); it never uncovers figure px, so it
     cannot lift the tongue where it lies over the legs.
  4. Fold up on #43 (0.0020 -> 0.0096).
- **Next steps to propose (not built):** extra hem pairs (hem quarter points) or stop the mask pairs at the hip row;
  then re-measure tongue / new holes; then the tube arm-floor fix above.

## 4. How to run (Docker via OrbStack; add `~/.orbstack/bin` to PATH; no host Python/Node)

- Backend tests: `docker compose exec -T backend python manage.py test apps`
- Frontend: `docker compose exec -T frontend npx vitest run` and `npx tsc --noEmit`
- After changing engine code: `docker compose restart worker` (Celery does not reload); after changing compose env:
  `docker compose up -d backend worker`.
- Benchmarks (pattern for every runner):
  ```
  docker compose exec -T backend rm -rf /tmp/warp-benchmark /tmp/warp_benchmark
  docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
  docker compose exec -T -e EXPORT_ROOT=/tmp/warp-benchmark/data/<round> backend python manage.py shell \
      < tools/warp-benchmark/export_sleeve8b.py      # re-export from the DB when landmarks changed
  docker compose exec -T [-e CLEAN=1 | -e FULL=1] backend python manage.py shell < tools/warp-benchmark/run_<round>.py
  docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/
  ```
  - `run_tube11.py` (CLEAN=1 = no overlays), `render_tube11.py` (full real render_tryon images), `run_side12.py`
    (FULL=1 = whole T-shirt sheets), `debug_tube11.py`, `debug_side12.py`.
  - `tools/warp-benchmark/out/` and `data/` are gitignored; previous runs are kept in sub-folders of `out/`
    (`tube11_*`, `side12_*`, `shoulder9*`).
- Regression fixtures (gitignored, real avatar photos): `backend/apps/tryon_engine/testdata/mls_r7`, `mls_r10`,
  `tryon_neck`. Without them the fixture tests skip (they must not skip on the owner's Mac).
- Screenshots of the frontend: Chrome extension was not available; Playwright in Docker worked:
  `mcr.microsoft.com/playwright:v1.49.1-noble` with `--network container:<frontend container>` and routing
  `localhost:8000` -> `backend:8000` (script pattern in the session; token via simplejwt in the Django shell).

## 5. Working rules the owner gave (keep following)

- Plan first, wait for OK; one round at a time; numbers only in docs, no verdict unless the owner decides.
- Benchmark work: no production wiring, no commit unless asked; defaults must stay pixel-identical; keep_shape no-op.
- "No new holes" vs the reference is a hard requirement for sleeve / side changes.
- The owner reviews in Uzbek; code / docs in English.
- When the owner asks to "see" results: open the PNGs in Preview (`open -a Preview ...`); clean sheets (CLEAN /
  FULL modes) are preferred for visual checks.
