# Landmark editor prototype

`body-landmarks.html`: standalone page (no build). Drop an image, lines are auto-detected from the
silhouette, drag lines/ticks to correct, press OK to export JSON for 6 slots (male/female x slim/average/plus).

Purpose: reference implementation to PORT to a React component (`LandmarkEditor`), not to ship as is.

Port notes:
- The prototype export is already on the project canvas: **600x1200**, `axis_x = 300`, figure 50..1150.
- Landmark set must depend on type (body vs garment types), see docs/03-landmarks-and-coordinates.md.
- Move segmentation to the backend (rembg), the editor should only adjust lines.
- Keep: edge snapping, per-leg knee/ankle ticks, sanity checks, keyboard nudging, zoom.
- Texts are Uzbek. Keep user-facing text in a locale file.
