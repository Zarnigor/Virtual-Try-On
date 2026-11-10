# 06. Try-on engine (backend, Python + OpenCV)

This is a proposal; confirm the approach with the owner before building.

**MVP scope: T-shirt (short sleeve) + pants.** The body photo is taken in a short-sleeved or sleeveless top and
shorts/tight leggings, so no old sleeves or trouser legs show around the new garment.
**The garment always adapts to the body** (decision): there is no size-mismatch display and no fit label.

Inputs: body (image + landmarks + optional height_cm) or avatar (image + landmarks + required measurements),
garment (transparent PNG + landmarks by type).

## Steps
1. **Target landmarks**: own body = its marked landmarks. Avatar path = nearest avatar's landmarks adjusted to the entered measurements.
2. **Deformation (mesh / piecewise warp)**: pair garment landmark rows with body landmark rows by identical names
   and interpolate between them. Split the garment into parts, each with its own warp:
   - T-shirt: torso, left sleeve, right sleeve (sleeves are rotated/bent to the arm direction; A-pose arms are not parallel to the body)
   - Pants: waist-hip region, left leg, right leg (each leg to its own thigh/knee/ankle line)
3. **Composite**: place the deformed garment over the torso/legs; keep head, neck, hands and forearms on top or outside the garment.
   Feather edges; clip with the body mask.
4. **Output**: 600x1200 image.

## Known risks of mesh warp (be honest in the demo)
- Sleeves: flat-lay sleeves point about 20-30 degrees down, A-pose arms differ. Warp sleeves as separate parts.
- Stretch: because the garment always adapts, large scale changes distort prints/text. Quality guard (proposal, confirm thresholds):
  warn beyond about 1.4x or below 0.6x instead of distorting further.
- Mesh folding: wrong or crossing landmark pairs fold the mesh. Validate order and monotonicity before warping.
- Hem length: the body has no hem landmark. Use a rule (proportion from hip/crotch) or let the user mark it.
- Pants: leg angles, knee position and crotch are the hardest part; thighs touching breaks crotch detection.
- A warped garment looks flat (no wrinkles/shadows); the optional realistic render partially fixes this.

## Day-1 experiment (before building any pages)
One T-shirt and the three male avatars (slim, average, plus), then one pair of pants and the same avatars.
Pass criteria:
- shoulder and waist lines of the garment land on the body edge,
- sleeves sit on the arms,
- text/print is not visibly stretched,
- mesh does not fold or tear.
If it fails, stop and discuss the approach before continuing.

## Fallbacks if mesh warp is not good enough
1. Scanline warp: a separate horizontal scale per row between landmark rows, sleeves rotated separately. Simpler and predictable.
2. Narrow the demo to well-behaved garments (plain T-shirts, straight pants).
3. Lean more on the realistic AI pass to hide artifacts (cost and variability go up).

## Avatar path
- Pick the avatar by sex and the nearest build from the (required) measurements.
- The garment is warped to the entered measurements; the displayed body is the nearest avatar image.

## Performance
Result in under about 2 s without AI. AI is only for the optional realistic pass.
Libraries: `scikit-image` PiecewiseAffineTransform, or OpenCV `remap` / thin-plate spline.

## Engine as built (2026-11-10, `apps/tryon_engine/warp.py`, entry point `render_tryon`)
Scanline strips (torso, pants) + rigid affine sleeves. Diagnosed on the 6 real avatars with
`tools/tryon_check/run.py` (before/after images in `tools/tryon_check/out/compare/`, not in git). Rules:
- **Lengths follow the garment, widths follow the body.** One vertical scale per piece (T-shirt: body/garment
  shoulder width; pants: waist->crotch rise, both anchored). Every row's width is the body's span at that row
  (landmarks for the torso, the figure mask for the legs). Pinning each garment row to the same-named body row
  (day-1 version) distorted the garment wherever the two disagree (body hip = widest row just above the crotch).
- **T-shirt hem** = the garment's own length (was `hip + 0.3*(crotch-hip)` for every garment). Cut, not
  squeezed, if it would end more than 35 % of crotch->knee below the crotch. The collar above the shoulder line is kept.
- **Sleeves**: rigid piece (uniform scale + rotation), outer edge along the figure's outer silhouette edge
  (deltoid, then arm), attached at the shoulder. Shortened along the arm (warning) if it would pass half the
  arm. The body `armpit` landmark is not used: it is where the arms separate in the mask, far below the
  anatomical armpit (was: fixed `±22 px` sliver from shoulder to `armpit + 0.5*(crotch-chest)`).
- **Pants**: full length if the hem lands within 5 % of figure height of the ankle (it breaks over the shoe),
  else it ends where the garment ends. Below the knee the hem keeps the garment's own flare relative to its knee
  (was: squeezed to ankle width, 0.25x). Inner leg edges start at the crotch point (was `±5`/`±10 px`).
- **Hands and forearms above the garment**: arm runs from the figure mask beyond the sleeve hem are copied back
  from the base after compositing. Arms touching the body cannot be separated (warning "arm ... not separated").
- **Warnings** report distortion (horizontal / vertical scale of one segment > 1.4x), not width change.
- Order: pants under the T-shirt.

### Pants fit (2026-11-10, docs/09 #59, `warp_pants`, `pants_width`)
- One uniform scale `s` for both axes: garment waist..hem -> body waist..ankle (full length) or the rise (shorter pants).
  The garment keeps its own leg width, taper and cuffs (loose joggers stay loose).
- Waistband: body waist + 4 % ease, smoothly blended (smoothstep) to the garment's own scaled width at its hip row.
- Below the hip: `pants_width = min(max(garment * s, body + 4 %), 1.8 * ref)`, `ref` = the row's body width, or the
  body knee width below the knee (a flared cuff is not squeezed to the ankle). The body leg in the mask is always covered.
- Each leg is centred on the body leg's centreline (crotch -> knee -> ankle landmarks), so wide stances get legs on legs;
  near the crotch the leg blends into the waist block. A full-length hem sits on the ankle line.
- Warning: a row's horizontal scale vs `s` beyond 1.3x (e.g. narrow pants widened over a plus-size body).

### Realism pass (2026-11-10, docs/09 #60, `render_tryon`)
All three effects are OFF by default (docs/09 #63): `TRYON_SHADING`, `TRYON_CONTACT_SHADOW`, `TRYON_EDGE_FEATHER`
(env, read by `flags.render_flags()`). With all off the result is the warped, opaque garment over the avatar.
- Shading: `shading_map` = avatar luminance / its blur (sigma 25, normalised to the garment area), clipped 0.75..1.2,
  smoothed; garment RGB *= shade ** 0.7 (`shading_strength`, 0 = off). Alpha is never changed.
- Edges: the 1 px rim is dropped (photo background fringe) and the alpha feathered by ~1 px (colour grown from inside).
- Contact shadow: blurred garment alpha, 2 px inward and 3 px down, opacity 0.25, only on the figure, under the garment.
- Pants hang: leg centre = w * body leg line + (1 - w) * straight drop from the crotch row; w = 1 when the garment row is
  within 1.15x of the leg, 0.5 from 1.35x (linear between). The body leg in the mask is still always covered.
- Waistband: the top edge dips 4 % of the waist width at the centre (content bent with `cv2.remap`, fading by the hip).

### Loose-leg centreline (2026-11-10, docs/09 #61, `leg_centerline`)
- Once per garment (docs/09 #62): looseness t = smoothstep of the MEAN knee ratio (garment knee width * s / body knee
  width, both legs) over 1.05x .. 1.15x. Both legs use the same t, so a symmetric garment fits symmetrically.
  Centre = (1 - t) * tight line + t * loose curve; hang weight = 1 - 0.5 t.
- Tight: the centre follows the piecewise crotch -> knee -> ankle line (hugs the leg).
- Loose: a quadratic Bezier from the crotch-row centre to the ankle centre; the knee pulls it by at most 25 % of its
  offset from the straight line, and the control point is clamped between the ends, so the edges are monotonic (no kink
  or bulge at inward knees, e.g. male_plus).

### Opaque garments (2026-11-10, docs/09 #63, `garment_layer`, `fill_alpha_holes`)
- After rembg (`_rembg_clean`) and again after warping: alpha = 255 inside the largest outer contour, except its outer
  1 px edge. A hole is kept open only if its colour matches the photo background (median of the transparent pixels
  outside the garment, distance <= 40): e.g. a real neck hole. Openings are warped with the garment and stay open.
- Compositing is straight-alpha "over" and rows are resized premultiplied, so empty (black) pixels never darken
  edges or strip overlaps; newly opaque and soft-edge pixels take the colour of the nearest opaque garment pixel.

### T-shirt fit (2026-11-10, docs/09 #64, `warp_tshirt`, `head_neck_overlay`)
- One uniform scale `s` for both axes, set by the shoulder line: garment shoulder width * s = body shoulder + 4 %.
  (A length-based scale would put every hem at the same body row and stretch crop tops; the hem is the garment's own
  scaled length, cut, never squeezed, below crotch + 35 % of crotch->knee.)
- Rows: `tshirt_row_width` = body + 4 % at the shoulder line, smoothstep to max(garment * s, body + 4 %) by the
  garment's chest row, capped at 1.8x body. Below the arm separation the torso run in the mask is covered (+2 px).
- Looseness once per garment (mean chest/waist ratio, smoothstep 1.05x..1.15x): the row centre goes from the torso
  centre (tight) to the shoulder centre straight down (loose); both sides alike.
- Collar above the shoulder line: same uniform scale, centred, not fitted.
- Sleeves: rigid (s + rotation onto the upper-arm edge line), shortened with a warning past half the arm; the armhole
  edge reaches past the torso edge by the measured gap + 4 px and the cap 4 px up (garment fabric, sampled rigidly).
- Head and neck: figure pixels within neck width + 6 px and above a downward arc (the `neck` row, 0.25 x neck width
  deeper at the centre, like a crew collar) are drawn over all garments, feathered ~3 px; ghost-mannequin back
  collars never cover the neck. Hands/forearms below the sleeve hem as before.
- Shoulder cap (docs/09 #65): bare figure pixels between the neck column and the shoulder edges, below the neck
  row, on the shoulder side of the sleeve hems and above the T-shirt hem, are filled UNDER the garment with the
  nearest colour of the garment's shoulder row (feathered ~2 px), so no skin sliver shows at the shoulders.
- With pants (docs/09 #66): pants first, then the T-shirt. Pants are cropped above their own waist row (wide pants
  left maroon lines beside the shirt). A hem 0..12 px above the pants waist is extended down by repeating its last
  opaque row (alpha 255) to 6 px past the pants top in each column; a crop top further up stays as is.
- Warning: a row's width vs garment * s beyond 1.3x (e.g. a fitted blouse widened over broad hips).

### Solid colours (2026-11-10, docs/09 #67)
- `GARMENT_FLATTEN_LIGHTING=1` (default): at cleaning (`_rembg_clean`, and `build_demo` on import) a near-solid
  garment (`apps/garments/lighting.py`: saturation std <= 20, saturation-weighted hue std <= 12 deg unless grey,
  high-frequency luminance = L minus its blur (sigma 8 % of the width): std <= 16 AND share of |value| > 25 <= 1.5 %)
  gets pixel - 0.8 * (lowfreq - median) per channel. The outlier share catches small text/logos (docs/09 #68).
  Prints and multi-colour garments are untouched; alpha never changes.
- With all TRYON_* flags 0 the warp only resamples: rows and sleeves are resized/warped premultiplied, so interior
  pixels keep the source colour exactly (test `SolidColourTests`).
