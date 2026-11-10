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
- Sleeves: rigid (s + rotation), see "Layer order" below (replaces the armhole reach-in and the 4 px cap).
- Head and neck: figure pixels within neck width + 6 px and above a U-shaped edge (half ellipse: 0.25 x neck width
  below the `neck` row at the centre, 0.3 x neck width above it at the sides, like a collar that wraps the neck) are
  drawn over all garments, feathered ~3 px; ghost-mannequin back collars never cover the neck.
- Shoulder cap: see "Layer order" (replaces the #65 band fill, which painted everything below the neck row).
- With pants: see "Layer order" (the hem is snapped by stretching; the #66 row repetition is gone).
- Warning: a row's width vs garment * s beyond 1.3x (e.g. a fitted blouse widened over broad hips).

### Solid colours (2026-11-10, docs/09 #67)
- `GARMENT_FLATTEN_LIGHTING=1` (default): at cleaning (`_rembg_clean`, and `build_demo` on import) a near-solid
  garment (`apps/garments/lighting.py`: saturation std <= 20, saturation-weighted hue std <= 12 deg unless grey,
  high-frequency luminance = L minus its blur (sigma 8 % of the width): std <= 16 AND share of |value| > 25 <= 1.5 %)
  gets pixel - 0.8 * (lowfreq - median) per channel. The outlier share catches small text/logos (docs/09 #68).
  Prints and multi-colour garments are untouched; alpha never changes.
- With all TRYON_* flags 0 the warp only resamples: rows and sleeves are resized/warped premultiplied, so interior
  pixels keep the source colour exactly (test `SolidColourTests`).

### Pants keep their own row widths (2026-11-10, docs/09 #70, `_garment_span`)
- Each source row's span is read from the garment's silhouette (alpha), not interpolated between the crotch, knee
  and hem landmarks: a balloon lower panel and a gathered cuff keep their shape. Legs: the leg's run split at the
  crotch axis; waist..crotch: the extent within the landmark span +-15 %. Landmark span = fallback.
- Final width = max(garment span * s, body + ease) (capped); only the centreline is smoothed. Below the knee the
  rows keep the single vertical scale (full-length legs: hem snapped to the ankle, one linear map per leg).

### Layer order (2026-11-10, docs/09 #79-#84, `render_tryon`, `LAYER_ORDER`)
One compositing order, bottom to top; every layer is clipped to its own region and has its own unit tests
(`RowWarpTests`, `HaloTests`, `TshirtLayerTests`, `TshirtFitTests`). The stacked patches (armpit fill, shoulder band
fill, hem row repetition, sleeve reach-in) were removed, not extended.

1. **Avatar.**
2. **Pants**: only from their own waist row down (`result[:waist] = 0`). Waist block + two legs, each leg warped from
   its own half of the garment.
3. **Shoulder cap** (`shoulder_cap_layer`, flag `TRYON_SHOULDER_CAP`, default 1): figure pixels above the T-shirt's own
   top edge, between each collar top point (the garment's highest pixel on that side) and the shoulder point, at most
   3 % of the figure height deep, never above the collar top, never inside the neckline. Colour: the garment pixel just
   below in the same column. It only fills what the T-shirt leaves bare, so it sits under the T-shirt's soft edge.
4. **T-shirt torso** (`warp_tshirt`, part `torso`): the garment without its sleeve regions, row warp.
5. **Rigid sleeves** (parts `sleeve_left`, `sleeve_right`): each drawn exactly once. Region in the garment
   (`sleeve_regions`): everything outward of the armhole line (shoulder point -> armpit point) down to the armpit row;
   below it, what lies outside the torso's own run. Rows where the sleeve is still joined to the torso (no background
   gap, e.g. sleeves hanging along the body: #17, #28) are split along a straight line from the armpit point to the
   torso edge of the first free row; "joined" = the run reaches more than 6 % of the chest span past the torso's median
   edge (waist..hem). Placement: uniform scale s, rotated so shoulder -> sleeve_end follows the figure's outer edge
   line, pivot at the shoulder point, then shifted sideways so the sleeve's hem half is centred on the arm (arm centre =
   outer edge - half the arm width): a sleeve wider than the arm spreads evenly to both sides. It overlaps the torso by
   3 px past the armhole line; the torso rows widen to the sleeve's armhole edge where that lies outside them.
   The hem line (for the hands layer) is across the arm, just past the last sleeve pixel.
6. **Head and neck** of the avatar (U-shaped, feathered lower edge).
7. **Hands and forearms** of the avatar beyond the sleeve hem line.

Shared steps, each done once per garment in `garment_layer`: fill holes -> area-resample to about the final size when
the uniform scale is below 0.8 (`_prescale`; a 1500 px photo squeezed by the bilinear warp alone aliases) -> halo
removal (`remove_halo`, flag `TRYON_HALO_REMOVAL`, default 1: alpha eroded 2 px, the next 4 px ring recoloured from the
nearest interior pixel; deeper pixels untouched) -> warp -> fill warp seams.

Row warp (`_warp_rows`, replaces the integer `_scanline_strip`): control rows every 3 px, (y, left edge, right edge)
for source and destination, interpolated per pixel row and sampled with `cv2.remap` (bilinear, premultiplied):
positions and widths are sub-pixel, edges antialiased, nothing is drawn outside the rows. Span edges are averaged over
5 control rows (`_smooth_rows`): per-row silhouette jitter of 1 px made stair steps in every oblique line of a print.
The last row continues to the garment's own bottom edge (`_tail_rows`), so trims below the hem landmark are kept.

Width rules (unchanged, now symmetric): row width = max(garment * s, body + ease), spread evenly around the row
centre, also when the body run in the mask forces it wider. Body under a T-shirt includes the pants: a T-shirt row
that overlaps the pants layer is at least as wide as the pants there (no waistband beside the hem).

Hem over waistband (`hem_over`, flag `TRYON_HEM_SNAP`, default 1): a hem that ends 0..(12 px + 4 % of the shoulder
width) above the pants top is moved to 6 px past it (plus the waistband's centre dip) by stretching the rows below
the chest row; nothing is repeated. A crop top further up is left alone.

Shoulder landmarks on the sleeves (`normalize_tshirt_landmarks`): when the garment's shoulder span is more than
1.35 x its chest span (#28: 1.55 x, the points are on the hanging sleeves' outer edge), the armhole tops are estimated
at 12 % of the chest span outward of each armpit, on the top outline, with a warning. Otherwise the uniform scale
shrank the whole garment (torso "distorted 1.45x wider") and the armhole line cut each sleeve in two.

### Neck zone (2026-11-10, docs/09 #85, flag `TRYON_NECK_FIX`, default 1)
Neck zone = neck row .. shoulder row, +- 6 % of the figure height (`neck_zone_rows`). Only the T-shirt layer's alpha
and the head/neck edge change there; the avatar is never repainted, other layers are untouched.
- **Inner back collar transparent** (`back_collar_geometry`, `clear_back_collar`): a ghost-mannequin photo shows the
  inside of the back of the collar through the neck hole. It is the area between the back rim (the run of columns whose
  top pixel is within 3 px of the highest one, around the centre) and the front neckline, modelled as a half ellipse
  0.33 x rim width deep, 10 % narrower than the rim on each side so the collar ring stays. Applied only if the rim is
  crew-neck sized (12-58 % of the chest span) AND the inside is at least 10 % darker (mean luminance) than the ring below
  it; otherwise nothing is removed. The region (a column above the rim line + the half ellipse) is made transparent in
  the finished layer (alpha only, edge antialiased ~1.5 px), so the avatar's own neck shows through.
- **Head/neck overlay** stays on top; its feather is sigma 0.6 px (1-2 px ramp) instead of 1.5 px (`NECK_FEATHER_FIX`).
- **Shoulder edge** (`smooth_shoulder_alpha`): in the neck zone rows the binary alpha is blurred (sigma 1.5) and
  re-thresholded with a ~1.5 px ramp; newly visible pixels take the local mean of solid garment colour; the solid
  interior is untouched.
- The shoulder cap skips the columns of the opened neckline (it painted a black lip beside it).
- Check tool: `tools/tryon_check/neck.py` (before/after crops, 3x, `out/neck/`).

### Known limits (draft, 2026-11-10; contact sheets: `tools/tryon_check/matrix.py`)
- **The avatar's own clothes show wherever the garment does not cover them** (never redrawn, hard rule): the grey
  top under a crop top that ends more than ~20 px above the pants (female plus + #34), and its straps beside a wide
  neckline on broad shoulders (male average / male plus + #34).
- **A garment much wider than the body at the hip** keeps its own width (one uniform scale, set by the length): the
  waistband is fitted to the body and the pants widen to their own hip width, which reads as a bulge on slim
  avatars (#25 on female slim / average, male slim).
- **Sleeves are rigid**: a puff sleeve (#17) stands off the arm like a box; folds do not follow the arm. Above the
  arm separation row the arm is not known from the mask, so the sleeve is centred from the outer edge and the arm
  width measured lower down.
- **Mis-marked shoulder landmarks** are only estimated (see above); marking the armhole tops is still better.
- **Halo removal** assumes a fringe of at most ~6 px at the warped size; details thinner than 4 px (drawstrings, lace
  tips) lose 2 px. `TRYON_HALO_REMOVAL=0` keeps the cleaned image as is.
- **Too long T-shirts** are cut flat at crotch + 35 % (the hem trim is lost: #17 on male plus).
- **Demo results** precomputed before this change are stale until `build_demo` is run again.
- **Neck fix on V necks and blouses**: a garment with a dark inside that passes the crew-neck size test (blouse #17) gets
  a scoop neckline instead of its V. Garments whose inner back is as bright as the ring (white shirts without shading)
  keep the old look (a flat patch under the chin). `TRYON_NECK_FIX=0` restores the previous behaviour.

