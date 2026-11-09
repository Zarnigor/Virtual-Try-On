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

## Commands (not verified yet: no Docker/Node/Python on the dev Mac at the time of writing)
```
cp .env.example .env                                   # then fill GEMINI_API_KEY
docker compose up --build                              # db, redis, backend :8000, worker, frontend :5173
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py seed_avatars   # placeholder avatars until real photos exist
docker compose exec backend python manage.py test           # no tests yet
docker compose exec frontend npx tsc --noEmit                # type check
python3 tools/warp_experiment/run.py                         # day-1 warp experiment -> tools/warp_experiment/out/
```
