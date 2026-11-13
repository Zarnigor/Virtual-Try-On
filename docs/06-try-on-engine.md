# 06. Try-on engine (backend, Python + OpenCV)

This is a proposal; confirm the approach with the owner before building.

**MVP scope: T-shirt (short sleeve) + pants.** The body photo is taken in a short-sleeved or sleeveless top and
shorts/tight leggings, so no old sleeves or trouser legs show around the new garment.
**The garment adapts to the body** per its `fit_mode` (docs/09 #93): `adapt` is what the engine does; `keep_shape`
is used by the MLS engine (setting `TRYON_WARP=mls`, see "MLS engine" at the end); the default `parts` engine warps
it like `adapt`. **Decided
2026-11-11 (docs/09 #96): `keep_shape` = MLS preset A** (see "keep_shape decision" at the end of this file). There
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


### MLS single-field benchmark, round 2: marked landmarks + fit strength k (2026-11-11, NOT the production path)
Module `tools/warp-benchmark/mls_landmarks.py` (`warp(garment_rgba, garment_lm, body_lm, out_size, alpha, k)`),
runner `run_landmarks.py` (exports the garments read-only to `tools/warp-benchmark/data/`, not in git). Same rigid
MLS solver, grid, remap, edge fix and neck handling as round 1, but every control point comes from the **marked**
garment landmarks (docs/09 #92 set), paired by name: collar edges + collar_bottom (V tip on a V neck; anchors, weight
5, alignment only), shoulder seam, armpit, chest and waist edges, hem (benchmark rule, docs/09 "Still open"),
sleeve_cuff_outer/inner -> derived along the arm direction (length by the shoulder-to-hem ratio, width by the chest
width ratio, cuff line perpendicular to the arm). A garment missing any of these is skipped, never filled in.
Pairs are checked before warping (`drop_crossing_chest`, then the row and left/right order).

**Fit strength k:** the garment is first aligned by ONE uniform scale (body / garment shoulder width) + translation
(shoulder-line centres together; the neck anchors ride on it). Each target = aligned point + k x (body point -
aligned point). k = 1 full fit, k = 0 the aligned garment unchanged.

Results (6 avatars: male + female slim/average/plus; alpha 1.0, k 1.0 unless noted; `out/results2.json`):
| garment | fold ratio | local scale p1..p99 | floating px | above shoulder line | runtime |
|---|---|---|---|---|---|
| #28 black (male) | 0-0.56 % | 0.53-0.73 .. 2.1-3.1 | 0 | 0 | 0.06-0.08 s |
| #44 green print, oversized | 2.2-3.3 % | 0.16-0.22 .. 4.7-5.4 | 0 | 0 | 0.06 s |
| #44 alpha 1.5 | 1.4-3.3 % | 0.14-0.18 .. 5.5-8.5 | 0 | 0 | 0.06-0.07 s |
| #44 k 0.5 | 0-0.11 % | 0.33-0.40 .. 1.9-2.4 | 0 | 0 | 0.06 s |
| #43 white fitted (female) | 0-0.50 % | 0.29-0.40 .. 1.8-2.8 | 0 | 0 | 0.06-0.07 s |
| #40 sky-blue V-neck | 0.18-0.92 % | 0.18-0.24 .. 1.2-2.1 | 0 | 0 | 0.06-0.07 s |
- **#45 white oversized skipped**: no `collar` landmark marked (collar_bottom only). So alpha 1.5 and k 0.5 ran on #44 only.
- #44: chest is marked above the armpit (oversized), so both chest pairs are dropped on every avatar. Local scale at
  the armpit / inner-cuff targets (they almost touch, not moved or merged): min 0.37-0.59, max 0.70-1.05 (k 1),
  inner cuff down to 0.31 on female average; k 0.5: 0.54-0.80. Worst fold: #44 on female slim (3.3 %),
  `out/crop_worst.png`.
- Looks (k 1): no floating strips anywhere (production has skin slits between its rigid sleeves and the torso on most
  cells of #43, #40, #44). #44 is pulled into an hourglass: balloon "pad" sleeves, S-shaped folds down both torso
  sides, the print squeezed at the waist. #28/#43/#40 read as T-shirts but the outer shoulder is bare above the
  sleeve on male plus, the sleeve edges are ragged/rippled (#43, #40), and the avatar's grey top shows beside the
  torso at the waist on the plus avatars.
- k 0.5 vs 1.0 (#44): k 0.5 keeps the boxy oversized shape, no folds, print undistorted; but the garment no longer
  follows the body (bare skin at the top of the shoulders on female slim, wider than the body everywhere). A per-
  garment k (keep_shape ~ 0.5, adapt 1.0) is an option for docs/09 #93, the owner's choice.
Sheets: `out/sheet_mls_k1.png`, `out/sheet_production.png` (same layout), `out/sheet_k05_vs_k1.png`.

### MLS single-field benchmark, round 3: `keep_shape` proposal = per-point fit strength (2026-11-11, NOT production)
`mls_landmarks.warp(..., k_map=...)`: the single k becomes a per-point, per-axis k. Same alignment (uniform scale +
translation) and pair names; target = aligned point + (kx, ky) * (body point - aligned point). `k_map` = group ->
number or `{"x", "y"}`; groups neck, shoulder, armpit, chest, waist, hem, cuff (both cuff corners; their derived
arm-direction targets are kept, only weighted by k); an unnamed group uses `k`. Neck targets are the alignment itself,
so their k has no effect. Presets (`mls_landmarks.PRESETS`):
- **A**: neck 1.0; shoulder x 0.5, y 1.0; armpit, chest, waist 0.3; hem x 0.3, y 0.5; cuff 0.3.
- **B**: as A with shoulder x 0.8; armpit, chest, waist 0.5; cuff 0.5.
New metrics: `bare_shoulder_px` (figure pixels not covered by the garment in the band from the line collar edge target
-> body shoulder point down 0.15 x shoulder width) and `print_distortion` (std / mean of the forward local area scale
over the pixels sampled from the detected print box; #44 only). Runner `run_keep_shape.py` (k 1.0 | k 0.5 | A | B on
all avatars, sheet `out/sheet_keep_shape.png`, crop `out/crop_keep_shape_worst.png`, `out/results3.json`).

**Gate (fixed 2026-11-11, docs/09 #95):** only a missing required landmark skips a garment. A chest above the armpit
runs with the chest pair not used ("chest not used" in `results3.json`; never moved or swapped): the torso is driven by
armpit, waist and hem. The first run of 0f2d35f wrongly refused that case.

Results (#44 on the 6 avatars; **#45 skipped: no `collar` landmark**; #44 "chest not used" in every run):
| variant | fold ratio | local scale p1..p99 | bare-shoulder px | print distortion | runtime |
|---|---|---|---|---|---|
| k 1.0 | 2.2-3.3 % | 0.16-0.22 .. 4.7-5.4 | 39-125 | 0.17-0.28 | 0.06-0.07 s |
| k 0.5 | 0-0.11 % | 0.33-0.40 .. 1.9-2.4 | 67-175 | 0.06-0.08 | 0.06-0.07 s |
| A | 0 % | 0.44-0.53 .. 1.1-1.3 | 81-192 | 0.035-0.043 | 0.06-0.07 s |
| B | 0-0.11 % | 0.33-0.40 .. 1.9-2.3 | 67-175 | 0.06-0.09 | 0.06 s |
- Floating components 0 and pixels above the shoulder slope line 0 in every run. Local scale at the armpit / inner
  cuff targets (not moved or merged): A 0.61-0.83, B 0.54-0.86, k 1.0 down to 0.31.
- Looks: A and B keep the boxy oversized shape, no balloon sleeves, no S-folds, print not squeezed (A is the least
  distorted). k 1.0 is the hourglass of round 2. **Bare shoulders remain in every variant** (A even slightly more than
  k 1.0): a skin triangle between the collar and the sleeve top, clearest on male plus and female slim (worst A/B case
  `out/crop_keep_shape_worst.png`: B, female slim, fold 0.11 %).
- Why the presets do not fix it: the alignment already puts the garment shoulder line on the body's, so the shoulder
  y k has no effect, and B differs from uniform k 0.5 only by shoulder x 0.8 (nearly identical results). The gap is the
  garment's own top edge sloping down from the collar faster than the body's shoulder (#44 shoulder points are marked
  inside the chest width). Not tested here: a control pair on the shoulder slope (collar edge -> shoulder midpoint).
Sheet `out/sheet_keep_shape.png` (#44 only: k 1.0 | k 0.5 | A | B x male slim, male plus, female average).

### MLS keep_shape benchmark, round 4: bare-shoulder triangle (2026-11-11, NOT production)
Base preset A (`mls_landmarks.py`, runner `run_shoulder_slope.py`, `out/results4.json`). Variants:
- **V1 = A + shoulder_slope pair** (`slope_l|r`, k 1.0): garment point = the garment's top edge (first alpha row) at
  50 % between collar_* and shoulder_* in x (measured, never entered); body point = 50 % along the slope line neck
  edge @ neck.y -> shoulder point, raised (never lowered) to the figure's own top edge at that x, plus 3 px for the edge
  fix. `validate_slope`: between collar and shoulder in x, above armpit and cuffs, on both sides, else dropped.
- **V2 = A + alignment tweak**: uniform scale x 1.05, then the alignment moves up (never down) until the aligned garment
  top edge at the slope x is not below that body point. The neck opening follows the same alignment.
- **V3 = V1 + V2.**
New metric `excess_px`: garment pixels over the background above the slope line (garment floating above the shoulder).

Results (#44 on the 6 avatars; **#45 skipped: still no `collar` landmark**; "chest not used" in every run):
| variant | bare-shoulder px | excess px | fold | local scale p1..p99 | print distortion | runtime |
|---|---|---|---|---|---|---|
| A | 81-192 | 0 | 0 % | 0.44-0.53 .. 1.11-1.29 | 0.035-0.043 | 0.06-0.07 s |
| V1 | 56-166 | 0 | 0 % | 0.44-0.53 .. 1.11-1.30 | 0.035-0.043 | 0.06-0.07 s |
| V2 | 0-89 | 133-340 | 0 % | 0.46-0.56 .. 1.13-1.31 | 0.037-0.045 | 0.06-0.07 s |
| V3 | 0-85 | 73-187 | 0 % | 0.46-0.55 .. 1.13-1.31 | 0.037-0.046 | 0.06-0.07 s |
- Local scale min/max is at the sleeve near the waist/hip rows in every variant (V3 min on 2 avatars at the torso near
  the shoulder, 0.44-0.48). Floating 0, pixels above the shoulder line outside the shoulder 0 everywhere.
- V1 helps only 15-30 %: one point at 50 % pulls the edge up there, but the outer half (slope point -> deltoid) still
  shows a skin triangle (worst V1-V3: V1 on male plus, 166 px, `out/crop_shoulder_slope_worst.png`).
- V2/V3 close the gap on male average, female average/plus (0-13 px) and halve it on the slim avatars, but male plus
  keeps 85-89 px. The price is the garment sitting above the shoulder over the background (excess): V3 about half of
  V2 (the slope pair holds the edge on the body instead of letting the whole garment rise).
Sheet `out/sheet_shoulder_slope.png` (#44: A | V1 | V2 | V3 x male slim, male plus, female slim).

### MLS keep_shape benchmark, round 5: re-marked oversized landmarks (2026-11-11, NOT production)
Same code as round 4 (`run_shoulder_slope.py`, now re-exporting #44/#45 from the DB first and adding uniform k 1.0 /
0.5 references; `out/results4.json` overwritten). Re-marked: shoulder_* at the sleeve seam on both, #45 has collar
points, #45 chest at armpit height (486 vs 483: chest used); #44 chest 309 still above armpit 374: chest not used.
| garment / variant | bare-shoulder px | excess px | fold | local scale p1..p99 | print distortion |
|---|---|---|---|---|---|
| #44 k 1.0 | 0-2 | 1658-3840 | 2.2-3.5 % | 0.19-0.25 .. 3.0-4.7 | 0.087-0.185 |
| #44 A (V0) | 0-2 | 1679-3719 | 0 % | 0.36-0.46 .. 0.85-0.97 | 0.021-0.029 |
| #44 V1 slope pair | 0-2 | 818-2023 | 0 % | 0.35-0.44 .. 0.84-0.97 | 0.021-0.029 |
| #44 V2 align tweak | 0 | 2403-4822 | 0 % | 0.37-0.48 .. 0.80-0.92 | 0.023-0.031 |
| #44 V3 both | 0 | 1270-2735 | 0 % | 0.37-0.45 .. 0.80-0.96 | 0.023-0.030 |
| #44 k 0.5 | 0-2 | 1653-3719 | 0.02-0.62 % | 0.28-0.38 .. 1.08-1.45 | 0.028-0.046 |
| #45 k 1.0 | 0-6 | 1152-3067 | 0.44-1.30 % | 0.15-0.20 .. 1.5-2.8 | - |
| #45 A (V0) | 0-3 | 1047-2744 | 0-0.07 % | 0.26-0.35 .. 0.51-0.59 | - |
| #45 V1 | 0-5 | 489-1533 | 0-0.07 % | 0.26-0.33 .. 0.51-0.59 | - |
| #45 V2 | 0 | 1659-3704 | 0-0.06 % | 0.28-0.36 .. 0.49-0.60 | - |
| #45 V3 | 0 | 894-2199 | 0-0.06 % | 0.27-0.34 .. 0.49-0.63 | - |
| #45 k 0.5 | 0-6 | 1069-2802 | 0-0.29 % | 0.22-0.29 .. 0.56-0.72 | - |
Floating 0 everywhere; runtime 0.06-0.08 s. Local scale min mostly on the sleeve near the waist rows; V1/V3 on #45 at the
torso near the shoulder (0.24-0.30). Scale < 1 = the large garment photos are shrunk.
- **The re-marking closes the bare-shoulder gap by itself** (A: 0-3 px; was 81-192 in round 4). Worst A/V1-V3: #45 V1
  male slim, 5 px (`out/crop_shoulder_slope_worst.png`, a sliver at the outer shoulder edge).
- The cost is excess: the garment's own sloped top now sits above the body's shoulder line over the background
  (rounded, raised shoulders). V1 halves it (the slope pair pins the top edge to the body), V2 raises it, V3 is between.
  None is 0. Visually A/V1 look like a natural dropped shoulder; V1/V3 on male plus pull the top edge up towards the jaw.
- Specks (violet/grey dots at the old shoulder-gap edges on #44): garment edge pixels with partial alpha 87-173 left by
  the 2 px edge fix, blended over skin/white. Not alpha holes (#44 has none) and not the avatar's photo edge.
Sheet `out/sheet_shoulder_slope.png` (rows #44, #45; k1.0 | A | V1 | V2 | V3 x male slim, male plus, female slim).

### keep_shape decision (owner, 2026-11-11, docs/09 #96)
`fit_mode = keep_shape` = the single-field rigid MLS warp (`tools/warp-benchmark/mls_landmarks.py`) with the per-point,
per-axis fit strength **preset A**: target = aligned point + k x (body point - aligned point), alignment = one uniform
scale (shoulder widths) + translation (shoulder-line centres).
| group | k |
|---|---|
| neck (collar_left/right, collar_bottom) | 1.0 (anchors: target = alignment) |
| shoulder | x 0.5, y 1.0 |
| armpit, chest, waist | 0.3 |
| hem | x 0.3, y 0.5 |
| sleeve cuffs (outer, inner; arm-direction targets) | 0.3 |
`adapt` = k 1.0 everywhere (unchanged). No shoulder_slope pair, no alignment tweak (rejected, docs/09 "Rejected").
**Landmark requirement:** `shoulder_*` marked at the sleeve seam (on dropped shoulders: where the sleeve starts, out on
the arm), collar points present; a chest above the armpit is allowed (warning only) and its pair is not used.
With the old marking (shoulder inside the chest width) preset A leaves a bare-shoulder triangle (round 3/4).
Evidence: `tools/warp-benchmark/out/sheet_shoulder_slope.png` (column A), round 5 table above: bare shoulders 0-3 px,
fold 0-0.07 %, print distortion 0.021-0.029 (#44). Known cost: the garment's own sloped top sits above the body's
shoulder line (excess 1000-3700 px, a natural dropped-shoulder look). Hem: benchmark assumption, still open (docs/09).

### MLS benchmark, round 6: fitted T-shirts, sleeves/hem/coverage and fit strength k (2026-11-11, NOT production)
`tools/warp-benchmark/mls_fitted.py` (retarget hook on `mls_landmarks.warp`), runner `run_fitted.py`
(`out/results6.json`). #28, #43, #40 re-exported from the DB (re-marked). 6 avatars. #28 chest above armpit: chest not
used. Before = round-2 MLS (k 1.0, no retargeting) on the same landmarks.
Changes: (1) cuff width = min(garment cuff width x torso ratio, perpendicular arm width x 1.1), cuff centre on the arm
centre line (fitted through the first 20 separated arm rows and extrapolated up: short sleeves end above the row where
the arm separates from the torso in the mask), cuff line perpendicular to the arm; (2) so the inner/outer corners land
on (or 5 % past) the arm's edges; (3) hem x = torso silhouette at hem_y + 2 % (landmark span when the run merges with
the arms) and a hem centre pair `hem_c`; (4) shoulder target moved out to the acromion (outer silhouette edge 4 px
below the shoulder line) when it is further out; (5) after the 2 px erosion, alpha < 0.9 is removed (no soft specks).
Per-point k: neck and shoulder 1.0, armpit/chest/waist/hem/cuff = the run's k.
New metrics (`coverage_metrics`): uncovered body px (shoulder line -> hem row, arms beyond the cuff excluded), excess px
(garment outside the silhouette dilated by 2 % of the shoulder width), sleeve-torso gap px (below the armpit), hem
curvature (max deviation of the bottom edge from a straight line, central 90 %).

Means over the 6 avatars (ranges in `results6.json`):
| garment | run | uncovered | excess | gap | hem curve px | fold | runtime |
|---|---|---|---|---|---|---|---|
| #28 | before k 1.0 | 6255 | 1189 | 324 | 2.7-23.5 | 0-0.27 % | 0.06-0.07 s |
| #28 | after k 1.0 | 6149 | 186 | 334 | 4.0-12.8 | 0-0.56 % | 0.08 s |
| #28 | after k 0.7 | 6798 | 145 | 281 | 3.0-7.0 | 0-0.01 % | 0.08 s |
| #28 | after k 0.5 | 7297 | 151 | 250 | 3.0-4.0 | 0 % | 0.08-0.09 s |
| #43 | before k 1.0 | 10226 | 568 | 1316 | 12.0-31.6 | 0-0.50 % | 0.06-0.07 s |
| #43 | after k 1.0 | 9523 | 52 | 1224 | 7.5-17.8 | 0.03-0.64 % | 0.08-0.09 s |
| #43 | after k 0.7 | 8897 | 57 | 417 | 6.9-9.0 | 0-0.22 % | 0.08-0.09 s |
| #43 | after k 0.5 | 8542 | 95 | 211 | 6.0-7.6 | 0-0.04 % | 0.08-0.09 s |
| #40 | before k 1.0 | 5554 | 2374 | 993 | 2.0-18.6 | 0.18-0.92 % | 0.07 s |
| #40 | after k 1.0 | 5824 | 1288 | 493 | 4.0-10.0 | 0.42-1.43 % | 0.08-0.09 s |
| #40 | after k 0.7 | 4819 | 1323 | 58 | 3.0-7.0 | 0.11-0.69 % | 0.08-0.09 s |
| #40 | after k 0.5 | 4193 | 1841 | 19 | 3.0-5.8 | 0.01-0.30 % | 0.08-0.09 s |
Floating components 0 (two runs: 2 and 9 px). Local scale extremes stay at the armpit / sleeve-torso junction and the
chest rows; p99 drops with k (#28 2.2-4.4 at k 1.0 -> 1.3-1.8 at k 0.5).
- Fixed: sleeves no longer flare past the arm (excess down 3-10x on #28/#43), hem much straighter (worst 31.6 -> 17.8
  px at k 1.0, <= 9 px at k 0.7/0.5), no soft specks. Lower k closes the sleeve-torso slit (#40 gap 493 -> 19).
- Still wrong: the body (the avatar's own grey top) shows beside the torso from the armpit to the hem on every avatar,
  worst on the plus avatars (uncovered 14-18k px; worst crop `out/crop_fitted_worst.png`, #43 k 0.5 female plus): the
  torso side targets sit ON the body edge (no ease) and a lower k pulls them back to the garment's own narrower width,
  so uncovered rises as k falls on #28/#43. A notch remains at the armpit (#43). #40's puffed sleeve caps at k 1.0.
  Synthetic check: a long hem with three hem points still waves between them (16.5 vs 38.6 px before).
- k is NOT decided (owner picks by eye): k 1.0 follows the body but keeps the slit; k 0.5 has the cleanest sleeves and
  hem but uncovers more of a larger body.
Sheets: `out/sheet_fitted_k1_before_after.png` (left 6 columns before, right 6 after, k 1.0), `out/sheet_fitted_k.png`
(k 1.0 | 0.7 | 0.5 x male slim, male plus, female slim).

### MLS benchmark, round 7: torso side ease, underarm notch, mid-sleeve pairs (2026-11-11, NOT production)
`mls_fitted.warp(..., round7=True)` (round7=False reproduces round 6), runner `run_fitted7.py` (`out/results7.json`).
#28, #43, #40 x 6 avatars, k 1.0 and 0.7. Before = round 6 at k 1.0.
- **Ease + side floor:** armpit/chest/waist/hem x targets = torso silhouette edge at that body row (mask run through the
  axis; landmark span when merged with the arms) pushed out by 1.5 % of the body width there; k moves only their y,
  the x never comes inside edge + ease.
- **#43 armpit notch, cause:** the inner cuff target crossed the armpit target in x (garment: inner cuff outward of the
  armpit; body: inward of it, e.g. 213 vs 199 on male slim), a crossing pair that folds the underarm. Two parts to the
  fix: the armpit target is now the torso edge at the first row where the arm is separate in the mask (at the armpit
  row the arms are still merged, so the landmark span put it outward of the arm's inner edge), and an inner cuff target
  that still crosses is clamped 2 px outward of the armpit target (inner mid point recomputed). The armpit pair is
  dropped only if something still crosses: 1 of 54 runs (#28 male slim, right side).
- **Mid-sleeve pairs** `smid_out|in`: outer = arm centre line halfway between the shoulder point and the cuff centre +
  arm width x 1.1 / 2; inner = halfway along the sleeve underside (armpit -> inner cuff) on both garment and body
  (the arm's inner side is still joined to the torso at that height, a perpendicular target would land on the torso).

Means over 6 avatars:
| garment | run | uncovered | excess | gap | hem curve px | fold | runtime |
|---|---|---|---|---|---|---|---|
| #28 | round 6 k 1.0 | 6149 | 186 | 334 | 4.0-12.8 | 0-0.56 % | 0.08-0.10 s |
| #28 | round 7 k 1.0 | 6384 | 119 | 473 | 4.0-13.2 | 0-0.28 % | 0.08-0.09 s |
| #28 | round 7 k 0.7 | 5779 | 107 | 300 | 3.0-9.8 | 0-0.03 % | 0.08-0.10 s |
| #43 | round 6 k 1.0 | 9523 | 52 | 1224 | 7.5-17.8 | 0.03-0.64 % | 0.08-0.09 s |
| #43 | round 7 k 1.0 | 9492 | 2 | 1208 | 7.5-18.7 | 0.01-0.36 % | 0.09 s |
| #43 | round 7 k 0.7 | 7983 | 15 | 354 | 7.0-12.8 | 0-0.10 % | 0.09 s |
| #40 | round 6 k 1.0 | 5824 | 1288 | 493 | 4.0-10.0 | 0.42-1.43 % | 0.08-0.09 s |
| #40 | round 7 k 1.0 | 5610 | 725 | 658 | 4.0-9.8 | 0.31-0.68 % | 0.09-0.10 s |
| #40 | round 7 k 0.7 | 4613 | 1013 | 82 | 3.0-8.0 | 0.07-0.23 % | 0.09-0.10 s |
Floating 0 except one 1 px piece. Local scale extremes at the armpit / chest rows (sleeve and torso).
- Better: the #43 notch is gone (the underarm no longer folds); folds halve; #40 sleeve tops are flatter; excess down.
- **Not fixed / new:** uncovered barely moves at k 1.0. The avatar's grey top still shows at the sides from the waist
  to the hip on the plus avatars: the rigid field only has side points at the armpit, chest, waist and hem rows and
  does not widen the garment between them (worst `out/crop_fitted7_worst.png`, #43 k 1.0 female plus, 17239 px).
  The mid-sleeve pair opens a window of skin under the shoulder on the upper sleeve (gap and uncovered higher with it:
  #43 female plus gap 637 vs 337 without, uncovered 17239 vs 15194; #28 female slim 609 vs 301), while it lowers the
  fold (0.20 % vs 0.45 %). Its outer target (extrapolated arm centre line + half width) sits inside the deltoid.
- k stays the owner's choice: k 0.7 has the smaller gap (#43 354 vs 1208) and fewer folds; k 1.0 follows the body.
Sheets: `out/sheet_fitted7_k1_before_after.png` (left 6 columns round 6, right 6 round 7, k 1.0),
`out/sheet_fitted7_k.png` (k 1.0 | 0.7 x male slim, male plus, female plus).

### MLS engine in the try-on service (2026-11-11, docs/09 #98, flag `TRYON_WARP`, default `parts`)
`apps/tryon_engine/mls.py` (ported from `tools/warp-benchmark/` at c3f6883; no imports from tools/). Setting
`TRYON_WARP = parts | mls` from env (default `parts`; any other value stops startup with ImproperlyConfigured),
passed through docker-compose to the backend and the Celery worker. T-shirt only; pants and the body flow unchanged.
- `mls`: the T-shirt is one rigid MLS field from its landmarks (collar_*, collar_bottom, shoulder_*, armpit_*, chest,
  waist, hem, sleeve_cuff_*). fit_mode mapping: **keep_shape -> preset A** (per-point k_map; chest pair not used when
  chest.y < armpit.y); **adapt -> the fitted-garment MLS (round 7) at k 1.0** (known gaps beside the torso on the plus
  avatars, not fixed here). Edge fix once, inner back collar cleared, head/neck and hands on top; no shoulder cap and
  no neck-gap fill (as in the benchmark).
- **Fallback to `parts`** with `quality_warnings: ["mls_fallback"]` when `landmarks_complete` is false (the task does
  not try MLS), or when a core pair (neck, shoulder, waist, hem) fails validation or the body landmarks cannot be
  used (render_tryon catches `MlsUnavailable`).
- Output unchanged: 600x1200 result image, same endpoint. `POST tryon/` adds `engine` (the engine asked for); the
  job result adds `engine` (actually used) and `quality_warnings`.
- Hem row: hip + 0.35 x (crotch - hip), at most crotch - 10 px (`TRYON_HEM_HIP_FRACTION` / `TRYON_HEM_CROTCH_MARGIN`),
  still the benchmark assumption (docs/09 "Still open").

### MLS sleeve variants, round 8 (2026-11-12, NOT production, no winner picked)
Problem (round 7, fitted / `adapt`, k 1.0): bare skin between the shoulder and the sleeve, and a wavy sleeve bottom
edge. Suspected causes: the `smid_out` target (extrapolated arm centre line + half width) lies inside the deltoid;
the cuff has only two control points. Variants are a keyword argument of `mls.tshirt_layer(..., sleeve_variant=)`
(default `"r7"`; no env var, no flag, `render_tryon` never passes it, so production is unchanged):
- **r7**: round 7 as shipped behind `TRYON_WARP=mls`.
- **A**: no `smid_out|in` pairs (round 6 sleeve).
- **B**: `smid_out` target = the arm's outer silhouette edge on its row (outermost mask run, the deltoid edge) + the
  existing `CUFF_ARM_EASE` share of the arm width measured lower down (`_arm_at`); `smid_in` unchanged. No edge found
  -> r7 target kept (noted in `rejected`).
- **C**: B + `cuff_mid` pair (garment cuff-corner midpoint -> body cuff-target midpoint), computed after
  `_validate_fitted` and `validate`; dropped when the corners are < 2 px apart, it is not strictly between cuff_out and
  cuff_in in x, or it crosses the armpit in x order.
Torso sides, hem, keep_shape preset A, pants and the parts engine untouched. No new landmarks.

Runner `tools/warp-benchmark/run_sleeve8.py` (production `tshirt_layer`, #28, #43, #40 x 6 avatars x 4 variants);
outputs `out/results8.json`, `out/table8.md`, `out/sheet_sleeve8_<id>.png` (rows = avatars, r7 | A | B | C, grey =
measured arm band), `out/crop_sleeve8_worst_<v>.png` (2x). Metrics (`mls_fitted.py`):
- `arm_band_skin_px`: figure (body mask) px not covered by the garment inside the body-target quadrilateral
  shoulder (acromion) -> cuff_out -> cuff_in -> armpit, per side; the r7 run's quad for every variant (A/B/C do not
  move those targets); background px do not count. Skin ABOVE the shoulder point (top of the shoulder near the neck,
  visible on #43 female slim/average in every variant) is outside the quad and not counted.
- `cuff_wave_px`: max deviation of the sleeve bottom edge from the straight line through its end samples, along the
  body cuff line (central 90 %). Rewards a straight cuff; a real hem may be slightly curved, so not a verdict alone.
- gap / excess (round 6 `coverage_metrics`), fold (`debug_map=True`), runtime.

| variant | arm-band skin px (sum / max) | gap px (sum) | excess px (sum) | fold (max) | cuff wave px (median / max) | runtime s (max) | dropped |
|---|---|---|---|---|---|---|---|
| r7 | 21838 / 2070 | 14328 | 4278 | 0.00688 | 14.4 / 27.4 | 0.07 | - |
| A | 13687 / 1518 | 11773 | 7930 | 0.00890 | 14.1 / 28.9 | 0.07 | - |
| B | 16312 / 1555 | 13778 | 4623 | 0.00676 | 12.9 / 28.7 | 0.07 | - |
| C | 11113 / 1154 | 8831 | 4284 | 0.00660 | 10.2 / 27.0 | 0.08 | - |

Per run: `out/table8.md`. Observations (not a decision), counted over the 18 runs: every variant has less
arm-band skin than r7 on every run; lowest skin: C 14, A 4 (all four on #40: male slim, female slim/average/plus).
Lowest gap: C 11, A 7. A has 1.85x the r7 excess in total (sleeves pushed past the arm, mostly #40); excess is
lowest with r7 on 13 runs. Waviness: C lowest on 9 runs but worse than r7 on 6 (#28 male average/plus, #43 male
slim, female slim/average/plus); every variant still shows a jagged cuff edge on the sheets. Regression: `tests_mls.MlsR7RegressionTests` checks that the
default (r7) stays pixel-identical to the layer exported before this change (#28, #43, #40 x 6 avatars; fixture
`backend/apps/tryon_engine/testdata/mls_r7/`, gitignored because it holds the avatar photos; the test skips without
it; export with `tools/warp-benchmark/export_r7_regression.py` on the pre-change code only).

### MLS side coverage floor, round 10 (2026-11-12, NOT production, no winner picked)
Problem: on plus avatars the garment is narrower than the torso and the avatar's grey top shows in strips from the
armpit to the hem (keep_shape k 0.3 pulls the side targets back to the garment's own width; adapt has side points only
at the armpit, chest, waist and hem rows). Keyword `mls.tshirt_layer(..., side_floor=False)` (default off; no env var,
no flag; `render_tryon` never passes it, test `SideFloorTests.test_render_tryon_does_not_pass_it`).
- **Floor** at body row y = torso silhouette edge -/+ `SIDE_EASE` (1.5 %, round 7) x the torso width
  (`_torso_floor`; edge = the mask run through the axis, or the landmark span `prod.body_span` when the run is > 1.3x
  the span, i.e. an arm touches the torso).
- **keep_shape:** the x targets of armpit, chest, waist and hem are clamped to the floor at their target row; k still
  sets y; preset A values unchanged.
- **Both modes, two stages:** solve 1 with the pairs above (keep_shape: already clamped). Garment points at 1/3 and 2/3
  of the way from max(armpit, chest) to the hem row, plus the body hip row's fraction, on the garment's measured alpha
  edge (run through the garment centre; landmark span when the run is > 1.3x it, a sleeve joined to the torso). Where
  solve 1 puts each point (nearest body px, at most 3 garment px off, else dropped) gives the new pair
  `side_a|side_b|side_hip` + `_l|_r` with x = max(landing, floor) (left: min). Solve 2 with them. New pairs that break
  the vertical order of the side pairs (garment vs body, > 1 px apart) or left < right are dropped
  (`_validate_side_floor`). Shoulder, sleeve, neck pairs, pants and the parts engine untouched. No new landmarks.

Runner `tools/warp-benchmark/run_sidefloor10.py`: production `tshirt_layer`, #28, #43, #40 (fitted) and #44, #45
(oversized) x 6 avatars x {adapt k 1.0, keep_shape A} x floor {off, on} = 120 runs. Outputs `out/results10.json`,
`out/table10.md` (every run), `out/sheet_sidefloor_<id>.png` (rows = avatars; adapt off | on | keep_shape off | on;
armpit-to-hem crop, grey dots = the floor), `out/crop_sidefloor_worst_<mode>.png` (2x, off | on).
New metric `side_strip_px` (`mls_fitted.py`): figure px not covered by the garment within 3 % of the figure height
inward of the torso silhouette edge (same edge source as the floor), from the body armpit row to the run's hem target
row (keep_shape hems end above the body hem rule by design: counting down to the body hem row measured garment
length, not side coverage).

| garment | mode | floor | side strip px | uncovered px | excess px | fold | print dist | hem curve px (max) | changed px (max %) | runtime s |
|---|---|---|---|---|---|---|---|---|---|---|
| #28 | adapt | off / on | 16863 / 11043 | 38305 / 32808 | 720 / 760 | 0.0028 / 0.0026 | - | 13.2 / 12.2 | 9424 (4.01 %) | 0.07 / 0.12 |
| #28 | keep_shape | off / on | 26746 / 6984 | 44586 / 26148 | 2879 / 3277 | 0 / 0 | - | 9.0 / 10.6 | 27927 (12.99 %) | 0.06 / 0.11 |
| #43 | adapt | off / on | 21030 / 12790 | 56952 / 49255 | 14 / 40 | 0.0036 / 0.0041 | - | 18.7 / 18.8 | 13004 (4.41 %) | 0.07 / 0.13 |
| #43 | keep_shape | off / on | 24152 / 4379 | 50543 / 32820 | 2035 / 2256 | 0 / 0.0001 | - | 11.0 / 13.0 | 27426 (13.59 %) | 0.06 / 0.11 |
| #40 | adapt | off / on | 6025 / 4336 | 34465 / 32626 | 3544 / 4719 | 0.0069 / 0.0072 | - | 10.0 / 7.8 | 7457 (2.39 %) | 0.07 / 0.13 |
| #40 | keep_shape | off / on | 5902 / 1085 | 19781 / 14909 | 20381 / 21331 | 0.0003 / 0.0004 | - | 13.6 / 11.6 | 10258 (6.14 %) | 0.06 / 0.12 |
| #44 (oversized) | adapt | off / on | 8210 / 6416 | 36675 / 35644 | 15608 / 17465 | 0.0182 / 0.0186 | 0.132 / 0.147 | 25.3 / 25.0 | 12190 (3.38 %) | 0.07 / 0.13 |
| #44 (oversized) | keep_shape | off / on | 2780 / 3356 | 22042 / 24379 | 56167 / 56087 | 0 / 0 | 0.029 / 0.028 | 19.5 / 20.5 | 6654 (2.1 %) | 0.06 / 0.10 |
| #45 (oversized) | adapt | off / on | 8441 / 6109 | 31781 / 30137 | 11513 / 12851 | 0.0155 / 0.0166 | - | 17.8 / 17.8 | 9977 (2.78 %) | 0.08 / 0.14 |
| #45 (oversized) | keep_shape | off / on | 4058 / 1395 | 16532 / 15319 | 33210 / 34031 | 0.0007 / 0.0030 | - | 16.0 / 16.0 | 9417 (4.59 %) | 0.07 / 0.12 |

Sums over the 6 avatars (fold, print distortion, hem curve, runtime: max). Observations (not a decision):
- Fitted garments: side strip and uncovered drop in both modes, most in keep_shape (#28 -74 %, #43 -82 %, #40 -82 %);
  the grey strip is mostly gone on the plus avatars; what is left sits just under the armpit (the floor there follows
  the arm/torso junction).
- **Oversized: on/off is NOT negligible everywhere.** #44 / #45 keep_shape: on the 7 runs where the floor moved no
  target at all (#44 all but female plus, #45 male slim/average), 564-1132 alpha px still change (on 5 of the 7 mostly
  removed: the garment gets slightly narrower): a pair that
  "confirms" the first solve is exact only at its own point; it still changes the rigid fits around it. #44
  keep_shape gets slightly worse (side strip 2780 -> 3356, uncovered +2337). Where the floor did move targets
  (female plus on #44 / #45, female slim on #45: one target 38.6 px) the change is a real fix (#45 female plus side
  strip 3584 -> 768). #45 keep_shape fold rises 0.0007 -> 0.0030. Not tried: adding a new pair only when the floor
  actually moves its target (would leave oversized garments that need no floor pixel-identical).
- The visible garment edge lands about 3-4 px inside a floored target (outer-contour halo fix + alpha boundary), so the
  1.5 % ease is mostly used up.
- Runtime: two solves, max 0.15 s.
Regression: `tests_mls.MlsSideFloorOffRegressionTests`, default off pixel-identical to the layers exported before the
change (#28, #43, #40, #44, #45 x 6 avatars x adapt + keep_shape; gitignored fixture `testdata/mls_r10/`, export
`tools/warp-benchmark/export_r10_regression.py` on pre-change code only). 282 backend tests pass.
**Update 2026-11-12 (owner: oversized path restored):** (1) a new side pair is added only where the floor moves its
target (the garment already reaching the floor adds no pair; the second solve runs only when a pair was added);
(2) **side_floor is disabled for keep_shape for now** (`tshirt_layer` ignores it). Default output: #44 / #45 x 6
avatars x adapt + keep_shape = 0 px from the pre-round-10 export (24 renders, also 0 px against the committed HEAD
`mls.py`); keep_shape with side_floor=True = 0 px (12). **Open:** adapt with side_floor=True still changes #44 / #45
on 8 of 12 renders (the floor really pushes there: #44 avatars 1/3/4/6, #45 avatars 3-6, mostly the left side). The
round 10 table above was measured before this update and is stale (`run_sidefloor10.py` not re-run).

### MLS sleeve variants, round 8b: re-marked landmarks + shoulder-top skin (2026-11-12, NOT production, no winner)
Round 8 re-measured after the owner re-marked landmarks. Export `tools/warp-benchmark/export_sleeve8b.py` ->
`data/sleeve8b/` (gitignored; the regression fixtures in `testdata/` are untouched); runner `run_sleeve8b.py` reads the
export, production `tshirt_layer`, adapt k 1.0, side_floor off, r7 | A | B | C, 72 runs. Outputs
`out/results8b.json`, `out/table8b.md` (every run), `out/sheet_sleeve8b_<id>.png` (grey = arm band, blue =
shoulder-top band), `out/crop_sleeve8b_worst_<v>.png`. Round 8 files (`results8.json`, `table8.md`, `sheet_sleeve8_*`)
kept, stale.
Landmarks that differ from the round 8 snapshot: avatar 2 (chest), avatar 3 (hip, crotch), #28 chest, #40 chest
(now y 343, ABOVE its armpit 355: the #40 chest pairs are dropped on every avatar, as #28's). Avatars 1, 4, 5, 6 and
#43 are unchanged.
New metric `shoulder_top_skin_px` (`mls_fitted.py`, owner 2026-11-12): figure px not covered by the garment in the
band from the body neck edge to the acromion (the run's shoulder target), from the NECK landmark row down to the
shoulder line + 0.08 x shoulder width, arm-band quadrilateral excluded; r7 boxes for every variant; left and right
reported separately.

| variant | arm-band skin px (sum / max) | shoulder-top skin px (sum L / R, max) | gap px | excess px | fold (max) | cuff wave px (median / max) | runtime s |
|---|---|---|---|---|---|---|---|
| r7 | 21920 / 2070 | 3519 / 4233, 898 | 14412 | 3741 | 0.0066 | 14.4 / 25.9 | 0.07 |
| A | 12936 / 1513 | 3413 / 4111, 828 | 10971 | 6703 | 0.0109 | 11.7 / 27.4 | 0.07 |
| B | 16141 / 1524 | 3464 / 4153, 871 | 13771 | 4204 | 0.0068 | 12.5 / 27.4 | 0.07 |
| C | 10850 / 1111 | 3518 / 4213, 896 | 8457 | 3976 | 0.0071 | 9.6 / 29.7 | 0.08 |

Observations over the 18 runs (not a decision): arm-band skin lower than r7 for A, B and C on every run; lowest: C 12,
A 6. Shoulder-top skin barely moves between variants (at most 91 px apart on a run; the variants only touch the
sleeve), so none of them addresses it; it is larger on the right on 12 of 18 runs and largest on #43 (female
slim/average, male average: 780-900 px). Gap lowest: A 9, C 9. Excess lowest with r7 on 14 runs; A has 1.8x the r7
excess. Cuff wave: C lowest on 9 runs but worse than r7 on 7. Arm-band numbers changed vs round 8 on 35 of 72 runs
(#40 all avatars, #28 male plus, #43 male average/plus).

### V-neck opening: neckline variants (2026-11-12, NOT production, no winner picked)
Problem: on #40 (V neck, ghost-mannequin photo) the inside of the V shows the garment's inner back; the r7 back-collar
clearing runs only for crew-sized rims that are >= 10 % darker inside, so V necks are never cleared. Keywords
`mls.tshirt_layer(..., neckline_variant="r7" | "clear" | "clear_skin", source="body", base=None)` (default r7; no env
var or flag; `render_tryon` passes none of them, tested). Owner decisions 2026-11-12:
- **clear:** r7 back-collar clearing kept, union with the new opening: between the collar line (neck_l -> neck_r body
  targets) and the sides (V: triangle through neck_l -> neck_c -> neck_r when the garment's collar depth / width >=
  `NECKLINE_V_RATIO` 0.45; else the parabola through the same three targets), the sides inset by `NECKLINE_INSET` 6 % of
  the collar width (the collar landmarks sit on the band's outer edge on #40), alpha 0 inside, ~1.5 px ramp
  (`NECKLINE_AA`). Neck pairs missing or out of order -> nothing (r7). Alpha only; RGB untouched.
- **clear_skin:** clear + the avatar's own non-skin pixels inside the opening (`warp.skin_like` against the neck-centre
  median skin colour, as the neck-gap fill samples it) painted in that colour, feathered (`NECK_GAP_FEATHER`), returned
  as `info["neck_fill"]` (BGRA overlay, composited under the head/neck overlay). `source != "avatar"` -> exactly clear.
Depth / width: #40 0.819 (V; 0.686 before the owner re-marked its collar on 2026-11-12), #28 0.188, #43 0.188 (curve).
Runner `tools/warp-benchmark/run_neck.py` (adapt k 1.0, 6 avatars; re-run 2026-11-12 on `data/neck/`, the DB after
#40's collar was re-marked: collar y 21 -> 10, x 247/527 -> 241/529, collar_bottom y 213 -> 246; #28, #43 and the
avatars unchanged, their rows identical; the first run is kept in `out/neck_before_40/`): `out/results_neck.json`,
`out/table_neck.md`, `out/sheet_neck_<id>.png` (r7 | clear | clear_skin, 3x; thin grey = the un-inset opening outline,
drawn by the runner), `out/crop_neck_worst_<v>.png`.

| garment | shape | variant | fabric in opening px (sum, all = visible) | changed vs r7 px | changed outside neck zone px | skin fill px | runtime s (max) |
|---|---|---|---|---|---|---|---|
| #40 | V | r7 / clear / clear_skin | 28240 / 0 / 0 | 0 / 29085 / 29314 | 0 / 0 / 0 | 0 / 0 / 11581 | 0.08 / 0.08 / 0.13 |
| #28 | curve | r7 / clear / clear_skin | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0.08 / 0.09 / 0.09 |
| #43 | curve | r7 / clear / clear_skin | 1971 / 0 / 0 | 0 / 2285 / 2285 | 0 / 0 / 0 | 0 / 0 / 0 | 0.09 / 0.09 / 0.10 |

Observations (not a decision):
- #40: clear removes all fabric in the opening (the label and inner back gone, the rib band kept); the avatar's own grey
  tank then shows in the V on 4 of 6 avatars (male slim/average/plus, female average). clear_skin covers it with ONE flat
  colour (no shading or texture): a large flat triangle on male average / female average / male plus; on male slim the
  colour is visibly darker than the neck.
- #28 (black crew): 0 px difference: the r7 back-collar clearing runs on #28 (inside darker) and already covers the
  whole inset opening, so the union equals r7.
- #43 (white crew): the r7 clearing does NOT run (the inside is not 10 % darker), so r7 leaves 254-492 px of inner back
  per avatar; clear removes them. Its collar_bottom sits on the band's INNER edge, so the inset leaves a visible strip of
  inner fabric above the front band: 6-8 px thick at the centre column, 553-839 px per avatar, all of it visible.
- Default (r7) stays 0 px against the r7 and round 10 fixtures, incl. #44 / #45 (24 renders); 292 backend tests pass.
**neck_clip (2026-11-12, benchmark, keyword `tshirt_layer(neck_clip=False)`):** in the box rows neck-zone top .. body
shoulder row x columns between the shoulder (acromion) targets, the finished layer's alpha is clipped to the figure mask
dilated by `NECK_CLIP_DILATE` 2 px (~0.7 px soft edge; never lowered over the figure itself, alpha only). #40 (collar
y 31, x 210/557), clear, 6 avatars: garment px over the background beyond the 2 px ring in the box 151-844 -> 0; nothing
changes outside the box. Collar band fragments that sit over the avatar's own neck/shoulder skin (top corners, cut off
by the opening's collar line) are NOT removed by the clip.
**Hole mask, step 1 (2026-11-12, benchmark):** `neckline_variant="hole" | "hole_skin"`: the neckline interior as a mask
in garment px, warped with the garment's own field (`cv2.remap` with mx, my), cleared in union with the r7 back collar.
(a) GrabCut restricted to a `NECK_HOLE_BELT` 15 px belt around the landmark polygon (`neckline_hole`): **failed the
owner's check on #40**: the hole eats the rib band in the lower V and at the V tip, with stepped edges (overlays
`out/overlay_hole_40_garment.png`, `out/overlay_hole_40.png`); on #28 it cannot run (the crew polygon, ~16 px deep, is
thinner than the belt). Per the owner's rule the fallback is (b): an owner-drawn polygon, keyword `neck_hole_polygon`
(garment px), benchmark file `tools/warp-benchmark/data/neck_hole/<id>.json` `{"polygon": [[x, y], ...]}` read by
`run_neck_hole.py`; a zero-area polygon = no hole (r7). No polygon files exist yet.
**Hole mask (b), owner polygon (2026-11-12):** `data/neck_hole/40.json` (29 points, drawn with
`tools/warp-benchmark/pick_neck_hole.html` along the band's inner edge; top edge along the back band's lower edge).
#40 (collar y 30, x 208/557, collar_bottom 386, 247), 6 avatars: fabric left in the warped hole 0-5 px (edge rounding),
band px removed 0, changes outside the neck zone 0, 0.07-0.08 s; the landmark V `clear` leaves 847-1582 px inside the
same hole. Seen on the overlays: the V band edge is clean and the V tip is kept; the BACK neck band (excluded by the
polygon) now stays as a horizontal strip across the avatar's neck base on all 6 avatars (most visible on male plus,
female plus); neck_clip does not remove it (it lies over the figure). The avatar's grey tank still shows in the V.
**Owner polygon v2 (2026-11-12):** `data/neck_hole/40-2.json` (19 points; top edge at the garment's top, y 13, so the
back band is part of the hole), run with `NECK_HOLE_NAME={gid}-2.json`. 6 avatars: fabric left in the hole 1-4 px, band
px removed 0, changes outside the neck zone 0, 0.07-0.08 s. On the overlays the back-band strip across the neck is gone,
the V band is clean on both sides and at the tip, and no band fragments float at the top corners (the landmark `clear`
still shows them). The avatar's grey tank still shows in the V (male slim/average/plus, female slim/average).
**Decision (owner, 2026-11-12, docs/09 #99):** the avatars are re-shot in one low round-neck tank; `clear_skin` /
`hole_skin` are not used; the V-neck direction is `hole` + `neck_clip` (still benchmark only).

### Neckline hole for every shape + collar floor (2026-11-13, docs/09 #100-101)
Polygons (garment px of the cleaned PNG, `tools/warp-benchmark/data/neck_hole/<id>.json`): #28 (crew, black) and #47
(square neck, new garment) were drawn by the owner on the ORIGINAL photos (`40-4.json`, `40-3.json`) and moved to the
cleaned image by template matching (scale 1, offset #28 (57, 22), #47 (143, 267)). Runner `run_neck_hole.py`: with a
polygon the `clear` column is dropped (r7 | hole | hole+clip); `NECK_COLLAR_FLOOR` (default 1). Out:
`out/overlay_hole_<id>.png`, `out/table_neck_hole_floor.md`; before the floor `out/neck_hole_no_floor/`, with the
clear column `out/neck_hole_with_clear/`.

| garment | shape | hole: fabric left px | hole: band px removed | hole+clip: changed outside neck zone px | collar raised px |
|---|---|---|---|---|---|
| #47 | square | 3-6 | 0 | 14-407 | 1.5-10.7 |
| #28 | crew | 0 | 0-2 | 859-2043 | 0.3-9.8 |
| #40 | V (polygon v1) | 0-4 | 0 | 111-871 | 0 |

- The hole is shape-agnostic: the polygon is filled in garment px and warped with the garment's own field; the square
  corners stay sharp, the label and the inner back are gone.
- `clear` (landmark triangle/curve) on #47 guesses a V and leaves 7618-12379 px inside the square opening.
- **Collar floor:** the collar targets are placed by the shoulder alignment only (`control_points`). #47's collar sits
  only 32 garment px above its shoulder points (x 0.46-0.57 = ~15 px on the canvas), the body's contour is higher, so
  the collar corners landed 5-9 px BELOW the contour (#40: 9-17 px above). Now raised onto the contour; the garment's
  top corners reach the shoulder, the tank strap above them is covered.
- `neck_clip` removes the crew T-shirt's shoulder overhang (wavy shoulder line, #28); not used (#101).
- Seen, not fixed: the square opening is wide and deep, the avatar's grey tank shows as a large block (accepted,
  #99); on female slim / average the opening's lower edge reaches mid-chest.

### Neckline hole in the product (2026-11-13, docs/09 #102)
`warp.render_tryon` -> `_neck_hole_kwargs` -> `mls.tshirt_layer(neckline_variant="hole", neck_hole_polygon=...)` when
`TRYON_WARP=mls`, `TRYON_NECK_HOLE=1` and `landmark_checks.neck_hole_problem` passes (adapt and keep_shape since
2026-11-13, docs/09 #103; keep_shape was excluded at first) (same rules as
PATCH, alpha from the garment image). Otherwise the call is exactly as before (tested: no keyword passed). **Works only
with `TRYON_WARP=mls`; the default `parts` engine ignores the polygon.** Never `neck_clip` (#101). Regression fixture
`backend/apps/tryon_engine/testdata/tryon_neck/` (gitignored, `export_neck_hole_regression.py`, exported before the
wiring): 108 renders (6 garments x 6 avatars x mls adapt / mls keep_shape / parts), all 0 px without a polygon, with
the flag off, for keep_shape and for parts. Manual check `tools/warp-benchmark/run_tryon_neck.py` ->
`out/tryon_neck_<id>.png` (before | after, 3x neck crop), `out/tryon_neck.md`:

| garment | changed px after vs before | fabric left in the hole px | runtime s |
|---|---|---|---|
| #40 (V, `40-2.json`) | 6733-10523 | 1-4 | 0.11-0.12 |
| #28 (crew) | 6-91 | 0 | 0.11-0.12 |
| #43 (crew, no polygon) | 0 | - | 0.10-0.12 |
| #47 (square) | 12063-18947 | 3-6 | 0.11-0.12 |
