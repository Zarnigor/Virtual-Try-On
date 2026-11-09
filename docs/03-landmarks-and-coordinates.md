# 03. Landmarks and coordinates

## Coordinate system (master canvas)
- Canvas 600 x 1200 px, `axis_x` = 300 (vertical symmetry axis), y grows downward.
- The figure spans `figure_top = 50` (head top) to `figure_bottom` (about 1150, feet bottom).
- Source photo is normalized to this canvas (scale so figure height is about 1100 px).
- Stored coordinates use half-pixel precision.
- Ratios `width / figure_height` are stored too, for px->cm conversion with the user's height.

## Body landmarks (names are fixed; garments reuse the same names)
| Name | Kind | Definition |
|---|---|---|
| head_top | y only | first row of the figure |
| neck | span | mid-neck: just above trapezius onset, below the chin |
| shoulder | span | acromion points on the silhouette: where the edge turns from the sloping trapezius to the near-vertical deltoid |
| armpit | y only | first row where arms separate from the torso (>= 3 separate segments) |
| chest | span | armpit + about 2.5% of height; torso only, arms excluded; always >= armpit |
| waist | span | narrowest torso row between 35% and 70% of armpit->crotch |
| hip | span | widest torso row between waist and crotch |
| crotch | y only | seam junction at the body centre line (darkest point), not "first background row" (fails when thighs touch) |
| knee | y + 2 legs | each leg measured separately, y about foot_bottom - 0.285 * height |
| ankle | per leg y + width | narrowest leg row above the shoe top; each leg has its own y |
| foot_bottom | y only | last row of the figure |

"span" = `{y, left_x, right_x, width, center_x}`. Knee: `{y, left_leg:{left_x,right_x,width}, right_leg:{...}}`.
Never store the "both legs together" width: it measures the gap, not the leg.

Optional later: `bust` (fullest chest, armpit + 5-8%) separate from `chest` (underarm). Not in MVP.

## Garment landmark sets (same names, by type)
MVP types:
| Garment type | Landmarks |
|---|---|
| tshirt | shoulder, chest, waist, hem (etak), sleeve_end (left and right) |
| pants | waist, hip, crotch, knee (per leg), hem (per leg) |
Later (not MVP): skirt, dress, outerwear, long sleeves.
Deformation pairs garment and body landmarks by identical names.

## Sanity checks (frontend AND backend)
- Vertical order: head_top < neck < shoulder < armpit <= chest < waist < hip < crotch < knee < ankle < foot_bottom
- Anatomical ranges as % of figure height (warn outside): neck 12-19, shoulder 16-23, armpit 25-35,
  chest 27-38, waist 34-47, hip 46-59, crotch 49-61, knee 68-76, ankle 84-95.
- Every tick lies on the silhouette edge (within 2 px).
- shoulder width < 1.6 x chest width; one knee width < 0.5 x hip width; ankle < knee; left/right knee and ankle within 15%.

### Garment landmark checks (backend `apps/garments/landmark_checks.py`, editor `garmentGroups.ts` rules)
Required keys = what `tryon_engine/warp.py` reads:
- tshirt: `shoulder|chest|waist|hem {y, left_x, right_x}`, `sleeve_end.left|right {x, y}`.
- pants: `waist {y, left_x, right_x, center_x}`, `hip {y, left_x, right_x}`, `crotch {y, center_x}`,
  `knee {y, left_leg|right_leg {left_x, right_x}}`, `hem.left_leg|right_leg {y, left_x, right_x}`.

Rules (backend strict `<`; the editor keeps a 4 px gap and stops a drag at the neighbour, but never clamps on load):
- finite numbers only; x in [0, width], y in [0, height] of the cleaned PNG.
- `left_x < right_x` for every pair (also `sleeve_end.left.x < sleeve_end.right.x`); pants knee and hem:
  `left_leg.right_x < right_leg.left_x`.
- pants: `waist.left_x < waist.center_x < waist.right_x` and `hip.left_x + 5 < waist.center_x < hip.right_x - 5`
  (warp.py uses `center_x ± 5` as the inner crotch edges).
- vertical: tshirt `shoulder < chest < waist < hem` and each `sleeve_end.y > shoulder.y`;
  pants `waist < hip < crotch < knee < max(hem leg y)`.
- unknown extra keys are kept untouched. Failure: 400 `LANDMARKS_INVALID`.

## Previous bugs to never reintroduce
- Shoulder line drawn at neck height while its width was measured lower (arms included).
- Chest line fixed at a height ratio above the armpit.
- Knee/ankle measured as the span across both legs.
- Ankle landing on the shoe collar.
- Crotch found as "first background row" (breaks when thighs touch).
- Hip taken from a fixed ratio instead of the silhouette.

## Detection algorithm (prototype)
See `tools/landmark-editor-prototype/body-landmarks.html`: background colour from image borders ->
mask -> largest connected component -> row scans. Auto-detect, then the user drags lines
(ticks snap to the silhouette edge) and confirms. Arrow keys nudge by 1 px (Shift: 5 px). All points of a group share one Y; symmetry mirrors X around w / 2 (docs/09 #37-39).
In production: do segmentation on the backend (rembg), return the mask/landmarks, editor only adjusts.

## Reference data
`seed/avatars.reference.json` was computed from a collage of test images and converted to the 600x1200
canvas. It documents the schema only. Regenerate the real 6 avatars from the real photos
(`tools/avatar-prep/prep.py` then the landmark editor), do not ship it as final data.
