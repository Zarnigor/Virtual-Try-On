# Diagrams

UML activity diagrams with swimlanes (Foydalanuvchi, Tizim, AI). AI steps are tinted purple.

| Diagram | Source | Rendered |
|---|---|---|
| Own body creation (one time, then locked) | activity-1-body-creation.puml | .png / .svg |
| Garment upload, cleaning, public/private, moderation | activity-2-garment-upload.puml | .png / .svg |
| Try-on, realistic render, save outfit | activity-3-try-on.puml | .png / .svg |

Source of truth is the `.puml` files (PlantUML). `_style.puml` holds shared styling.

## Re-render
```
java -jar plantuml.jar -charset UTF-8 -tpng activity-*.puml
java -jar plantuml.jar -charset UTF-8 -tsvg activity-*.puml
```
(plantuml.jar: https://github.com/plantuml/plantuml/releases). Any PlantUML editor or the VS Code
PlantUML extension also works.
No Java on the Mac: render with Docker (verified with 1.2025.4, 2026-11-12):
```
docker run --rm -v "$PWD":/data -w /data plantuml/plantuml:1.2025.4 -charset UTF-8 -tpng activity-*.puml
docker run --rm -v "$PWD":/data -w /data plantuml/plantuml:1.2025.4 -charset UTF-8 -tsvg activity-*.puml
```
Syntax notes: colour an AI step as `#E6DDF8:text;` (the old `:text; <<#E6DDF8>>` form breaks the parser), and do not
change swimlanes inside `switch` cases (use `if / elseif`).

If you change a flow in code or docs, update the matching `.puml` in the same change.
