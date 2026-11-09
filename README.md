# TryOn Studio: project pack for Claude Code

Everything decided so far in one folder: instructions, requirements, flows (activity diagrams),
AI prompts, the landmark-editor prototype and the avatar-prep script.

## Use
1. Unzip, `cd tryon-studio`, run `claude` (Claude Code) in this folder. It reads `CLAUDE.md` automatically.
2. Suggested first message:
   > Read CLAUDE.md and everything in docs/ and prompts/, and look at design/previews/*.png. Follow the "First task for Claude Code" section.
3. Answer the questions in `docs/09-open-questions.md`, then confirm the plan step by step.

## Contents
```
CLAUDE.md                       instructions and hard rules for Claude Code
docs/                           product, decisions, landmarks, API, AI pipeline, engine, security, roadmap, open questions
docs/diagrams/                  3 UML activity diagrams (PlantUML source + PNG + SVG)
design/                         UI design: 12 desktop screens (PNG previews + sources), design tokens
docs/10-frontend-and-design.md  screen map; all images come from the backend API
prompts/                        5 AI prompts (.txt) + config + Uzbek error messages
tools/landmark-editor-prototype working landmark editor (vanilla JS) to port to React
tools/avatar-prep/              background removal + 600x1200 normalization script
seed/avatars.reference.json     landmark JSON schema example (not final data)
```

## Status (2026-11-09)
Scaffold exists (backend/, frontend/, docker-compose.yml). The API contract is fixed: `docs/04` + `frontend/src/api/types.ts`.
No flow works end to end yet. Current progress and the next step are tracked in `CLAUDE.md` ("Status and next step").

## Environment and commands (verified 2026-11-09 on macOS arm64 + OrbStack)
Docker runs in **OrbStack** (`~/.orbstack/bin` must be on PATH). OrbStack needs macOS permission for the Desktop folder
(System Settings -> Privacy & Security -> Files & Folders), otherwise containers fail with "Operation not permitted".
The first garment job downloads the rembg model (about 176 MB) into the `u2net` volume (kept across rebuilds).
```
docker compose up -d --build                              # db, redis, backend :8000, worker, frontend :5173
                                                          # backend entrypoint runs migrate + seed_avatars automatically
docker compose exec -T backend python manage.py check
docker compose exec -T backend python manage.py makemigrations --check --dry-run
docker compose exec -T backend python manage.py test apps   # 77 tests (real HTTP is blocked in tests)
docker compose exec -T frontend npx tsc --noEmit          # type check
docker compose exec -T frontend npm test                  # vitest (landmark-editor geometry)
docker compose logs -f backend worker
docker compose down                                       # stop (add -v to wipe db + media)
```
Optional: `cp .env.example .env` and set `GEMINI_API_KEY` and `GEMINI_VALIDATION_MODEL` (the garment check, prompt 01, is
wired; the body check is a stub until step 4). `AI_DEV_BYPASS=1` (the docker default) skips the AI; set `AI_DEV_BYPASS=0`
in .env to call Gemini. Optional `GEMINI_TIMEOUT_S` (minimum 60).
