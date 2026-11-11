# 06. Try-on engine (backend, Python + OpenCV)

This is a proposal; confirm the approach with the owner before building.

**MVP scope: T-shirt (short sleeve) + pants.** The body photo is taken in a short-sleeved or sleeveless top and
shorts/tight leggings, so no old sleeves or trouser legs show around the new garment.
**The garment adapts to the body** per its `fit_mode` (docs/09 #93): `adapt` is what the engine does; `keep_shape`
is accepted (`render_tryon(fit_modes=...)`) but warped like `adapt` until the MLS benchmark decides the method. There
is no size-mismatch display and no fit label.

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
3. **T-shirt torso** (`warp_tshirt`, part `torso`): row warp of the garment without its sleeve regions (it samples
   3 px past the armhole line, so its clipped edge lies inside the sleeve's territory, never on the join).
4. **Rigid sleeves** (parts `sleeve_left`, `sleeve_right`), each pixel from exactly one piece (round 4, docs/09 #86):
   - Region in the garment (`sleeve_regions`): everything outward of the armhole line (shoulder point -> armpit
     point) down to the armpit row; below it, what lies outside the torso's own run. Rows where the sleeve is still
     joined to the torso (#17, #28) are split along a straight line from the armpit point to the torso edge of the
     first free row ("joined" = the run reaches more than 6 % of the chest span past the torso's median edge).
   - Placement: uniform scale s, rotated so shoulder -> sleeve_end follows the figure's outer edge line, pivot at the
     shoulder point, shifted sideways so the hem half is centred on the arm.
   - **Territory** = the sleeve's own garment pixels (+2 px soft edge) + 3 px past the armhole line, mapped by the
     rigid transform, thresholded at 0.5 (no feather). The sleeve is sampled from the WHOLE garment image, so across
     the join its alpha is the garment's own (opaque): no clipped soft edge meets another soft edge, no lightness dip.
     Outward of the armhole line only the sleeve exists (its contour is drawn once); inward of it (the 3 px overlap,
     the underarm) the sleeve is drawn over the torso.
   - **Shoulder slope clip** (`shoulder_slope_line`): the line fitted to the torso's top edge over the outer half of
     the shoulder (15-60 % of the way from the shoulder point to the centre). Within one armhole length of the
     shoulder point (fading out to 1.4x) the sleeve is clipped below it, antialiased: the rotated sleeve's top corner
     never rises above the shoulder (the boxy "pad"). Further down the arm the line says nothing (it cut across
     sleeves on avatars with spread arms).
   - The hem line (for the hands layer) is across the arm, just past the last sleeve pixel.
   Then, once, on the composited torso + sleeves: fill holes, and the **edge fix on the outer contour only**
   (`remove_halo(outer_only=True)`: alpha eroded 2 px, the next 2 px recoloured from the nearest interior pixel; holes
   and internal joins untouched). The torso rows that cover the avatar's own top are widened by those 2 px.
5. **Shoulder cap** (`shoulder_cap_layer`, flag `TRYON_SHOULDER_CAP`, default 1), composited UNDER the T-shirt layer
   (it shows only where the garment does not): a small polygon per side between the collar (the garment's highest
   top pixel on that side, or neck + 6 px if further in) and the shoulder point, from the garment's top edge up by at
   most 3 % of the figure height, never above the collar top, never inside the opened neckline, figure pixels only,
   3 px under the garment's top edge (no gap). Colour: per column the median of the garment's solid pixels 3..15 rows
   under its top edge, median-filtered along the shoulder (9 px): never skin, never black, a stitch line is ignored.
   It is added after the edge fix (it has no photo fringe; eroding it would bare a 2 px rim of skin).
6. **Neck-gap fill** (`neck_gap_fill_fn`, flag `TRYON_NECK_GAP_FILL`, default 1): see "Neck zone".
7. **Head and neck** of the avatar (one smooth lower edge, see "Neck zone").
8. **Hands and forearms** of the avatar beyond the sleeve hem line.

Shared steps, each done once per garment in `garment_layer`: fill holes -> area-resample to about the final size when
the uniform scale is below 0.8 (`_prescale`; a 1500 px photo squeezed by the bilinear warp alone aliases) -> halo
removal (`remove_halo`, flag `TRYON_HALO_REMOVAL`, default 1: alpha eroded 2 px, the next 4 px ring recoloured from the
nearest interior pixel; deeper pixels untouched) -> warp -> fill warp seams. T-shirt: the halo removal runs after the
warp, on the outer contour of the composited pieces (step 4 above), not on the source.

Row warp (`_warp_rows`, replaces the integer `_scanline_strip`): control rows every 3 px, (y, left edge, right edge)
for source and destination, interpolated per pixel row and sampled with `cv2.remap` (bilinear, premultiplied):
positions and widths are sub-pixel, edges antialiased, nothing is drawn outside the rows. Span edges are averaged over
5 control rows (`_smooth_rows`): per-row silhouette jitter of 1 px made stair steps in every oblique line of a print.
The last row continues to the garment's own bottom edge (`_tail_rows`), so trims below the hem landmark are kept.

Width rules (unchanged, now symmetric): row width = max(garment * s, body + ease), spread evenly around the row
centre, also when the body run in the mask forces it wider. Body under a T-shirt includes the pants: a T-shirt row
that overlaps the pants layer is at least as wide as the pants there (no waistband beside the hem).

Hem length rule (flag `TRYON_HEM_RULE`, default 1, docs/09 #91, proposed): the T-shirt's bottom edge lands on
`body_hem_y` = hip + 0.35 x (crotch - hip), at most crotch - 10 px (settings `TRYON_HEM_HIP_FRACTION`,
`TRYON_HEM_CROTCH_MARGIN`), + the 2 px the edge fix takes off. Uniform scale down to the chest row, then the chest ->
hem rows are stretched or squeezed; widths unchanged; no crotch cut, no hem snap, no tail rows (the trims below the hem
landmark are part of the fitted length). With the flag off, the rules below apply.

Hem over waistband (`hem_over`, flag `TRYON_HEM_SNAP`, default 1): a hem that ends 0..(12 px + 4 % of the shoulder
width) above the pants top is moved to 6 px past it (plus the waistband's centre dip) by stretching the rows below
the chest row; nothing is repeated. A crop top further up is left alone.

Shoulder landmarks on the sleeves (`normalize_tshirt_landmarks`): when the garment's shoulder span is more than
1.35 x its chest span (#28: 1.55 x, the points are on the hanging sleeves' outer edge), the armhole tops are estimated
at 12 % of the chest span outward of each armpit, on the top outline, with a warning. Otherwise the uniform scale
shrank the whole garment (torso "distorted 1.45x wider") and the armhole line cut each sleeve in two.

### Neck zone (2026-11-10, docs/09 #85, flag `TRYON_NECK_FIX`, default 1)
Neck zone = neck row .. shoulder row, +- 6 % of the figure height (`neck_zone_rows`). The T-shirt layer's alpha, the
head/neck edge and (neck-gap fill) a thin strip of the avatar's own tank collar change there; nothing else.
- **Inner back collar transparent** (`back_collar_geometry`, `clear_back_collar`): a ghost-mannequin photo shows the
  inside of the back of the collar through the neck hole. It is the area between the back rim (the run of columns whose
  top pixel is within 3 px of the highest one, around the centre) and the front neckline, modelled as a half ellipse
  0.33 x rim width deep, 10 % narrower than the rim on each side so the collar ring stays. Applied only if the rim is
  crew-neck sized (12-58 % of the chest span) AND the inside is at least 10 % darker (mean luminance) than the ring below
  it; otherwise nothing is removed. The region (a column above the rim line + the half ellipse) is made transparent in
  the finished layer (alpha only, edge antialiased ~1.5 px), so the avatar's own neck shows through.
- **Head/neck overlay** stays on top (`head_neck_overlay`, round 4): one smooth, antialiased lower edge: the U under
  the chin, continued upward outside the neck at 3 px per px (no vertical wall: the steps and the rectangular edge
  under the chin came from the walls at neck +- 6 px). Feather sigma 1.0 px (about 3 px 10-90 %, `NECK_FEATHER_FIX`).
  With an opened neckline the edge stays at least 1 px above the inner edge of the front collar band (band visible).
- **Neck-gap fill** (`neck_gap_fill_fn`, flag `TRYON_NECK_GAP_FILL`, default 1): where the avatar's own non-skin
  pixels (the grey tank collar sitting higher than the garment's collar) remain between the head/neck overlay and the
  garment, inside the neck columns (the opening rim, else neck + 6 px) and above the shoulder row, they are painted in
  the skin colour sampled from the neck centre (median), feathered ~2 px. "Not skin" = Lab chroma below 45 % of the
  skin's, or hue more than 30 degrees away (brightness ignored: the shadow under the chin is skin). On the 6 avatars x
  3 T-shirts it touches 0-90 px per render. It is a small redraw of the avatar's clothes at the neckline, only where a
  T-shirt is drawn: `TRYON_NECK_GAP_FILL=0` turns it off (the grey collar then shows).
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
- **Dropped-shoulder one-piece warp** (`TRYON_DROPPED_SHOULDER_SINGLE`, default 0, docs/09 #90): removes the shoulder
  pad on #36 but shears the sleeves below the armpit into stepped blocks, so it is off; #36 uses the torso + rigid
  sleeves path described above (with its shoulder corner).
- **Dropped-shoulder T-shirts** (white oversized #36): the torso's shoulder line runs out past the body's shoulder
  and the rigid sleeve then hangs down at the arm angle, so the outline has a corner at the shoulder. No sleeve pixel is
  above the shoulder line (measured: 0.0 px on 6 avatars x 3 T-shirts); the corner is the garment's own silhouette
  meeting a rigid sleeve. A bending sleeve (mesh) would be needed to round it.
- **A print crossing the shoulder join** (a stitch from torso into sleeve) is split there by a few px: torso and
  rigid sleeve map it differently. The edge fix's 2 px ring takes the nearest interior colour, so a stitch lying right
  at the edge is smeared into the ring.
- **The avatar's grey top beside the torso** where the arm still touches the body (1-4 px strips below the armpit,
  female slim/average): those rows are not widened (the mask run includes the arm). Same as before this round.
- **Neck-gap fill is for admin avatars only** (docs/09 #89, docs/02 rule 12): `render_tryon(source=...)` runs it only for
  `source="avatar"`; an own body (`"body"`, also the default) never gets it, whatever `TRYON_NECK_GAP_FILL` says.
- **Hem rule squeezes or stretches** the chest -> hem rows (docs/09 #91): a garment much longer or shorter than the
  rule (a peplum blouse like #17, a crop top) loses its own proportions below the chest; crop tops no longer show
  as crop tops while `TRYON_HEM_RULE=1`.
- **Too long T-shirts** (hem rule off) are cut flat at crotch + 35 % (the hem trim is lost: #17 on male plus).
- **Demo results** precomputed before this change are stale until `build_demo` is run again.
- **Neck fix on V necks and blouses**: a garment with a dark inside that passes the crew-neck size test (blouse #17) gets
  a scoop neckline instead of its V. Garments whose inner back is as bright as the ring (white shirts without shading)
  keep the old look (a flat patch under the chin). `TRYON_NECK_FIX=0` restores the previous behaviour.

### MLS single-field benchmark (2026-11-11, `tools/warp-benchmark/`, NOT the production path)
Method: the whole T-shirt warped by ONE rigid MLS field (Schaefer et al. 2006), inverse: control points p = body,
q = garment, f(v) = R(v - p*) + q* with the weighted best rotation; garment points pre-scaled by the shoulder-width
ratio (rigid MLS has no scale). Field on a 1/4-resolution grid, upsampled, one `cv2.remap`; alpha 1.0 and 1.5. No
torso/sleeve/cap parts, no fills. Pairs: neck (collar edges + bottom centre, auto, weight 5, targets by the uniform
scale), shoulder seam -> shoulder, armpit (auto: deepest outline convexity defect) -> armpit, chest/waist edges, hem
(rule in docs/09 "Still open"), 2 cuff corners per sleeve (auto) -> along the arm direction (shoulder -> arm centre
at armpit + 10 % of the figure height), length and width by the torso ratios. Pairs breaking the row or left/right
order are rejected. A chest pair whose garment chest is at or above the garment armpit (marked `armpit.y` or the
detected corner), or whose vertical order against another row pair differs between garment and body, is dropped
(`drop_crossing_chest`, docs/09 #94): never a crossing pair, never a rejected garment. Tests: `test_mls.py`.
Then the edge fix once on the outer contour and the production neck/head and hands overlays.
Run: `tools/warp-benchmark/run.py` (sheets `out/sheet_mls.png`, `out/sheet_production.png`, `out/results.json`).

Results (6 avatars):
- **Garments skipped**: the sky-blue V-neck #39, #36 and #17. Their neckline cannot be auto-detected: the alpha
  outline has a flat top and no darker inner back (centre-column colour distance to the fabric <= 5 on #36, noisy
  10-20 on #39/#17). No values were invented. Only #28 (black, crew neck with a darker inner back) ran.
- #28 auto: neck crew (inner back), armpits at garment y 166/174 (the sleeves hang joined below the real underarm),
  cuffs auto. The chest pairs were rejected by the order check (garment chest y 122 is above those armpits).
- Fold ratio (inverse Jacobian det < 0, garment pixels): alpha 1.0: 0.1-0.6 %; alpha 1.5: 2.7-4.5 %. Local scale
  p1..p99: about 0.4-0.7 .. 6.5-11.8 (alpha 1.0); the extremes are at the underarm / sleeve-torso junction.
- Pixels above the shoulder slope line outside the shoulder +4 px: 0 everywhere. Floating components: 0 (alpha 1.0);
  11 px on female plus at alpha 1.5. Runtime 0.06-0.07 s per render (target < 2 s).
- Looks: no shoulder pad, but the sleeves flare out horizontally like bat wings (the cuff targets pull the sleeve,
  the torso points pull the side, nothing holds the region between), the outer shoulder/deltoid is bare above the
  sleeve on most avatars, crescent holes at both underarms, the torso sides pinch in below the armpit so the avatar's
  grey top shows, and the hem is curved. Production is clearly better on #28 on all 6 avatars.

