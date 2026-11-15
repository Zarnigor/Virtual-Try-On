# 06. Try-on engine (backend, Python + OpenCV)

This is a proposal; confirm the approach with the owner before building.

**MVP scope: T-shirt (short sleeve) + pants.** The body photo is taken in a short-sleeved or sleeveless top and
shorts/tight leggings, so no old sleeves or trouser legs show around the new garment.
**The garment adapts to the body** per its `fit_mode` (docs/09 #93): `adapt` is what the engine does; `keep_shape`
is used by the MLS engine (setting `TRYON_WARP=mls`, the default since docs/09 #105, see "MLS engine" and "Production
wiring" at the end); the `parts` engine warps it like `adapt`. **Decided
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

### MLS engine in the try-on service (2026-11-11, docs/09 #98, flag `TRYON_WARP`; default `mls` since #105)
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

### Shoulder line fit, round 9 (2026-11-13, NOT production, no winner picked)
Problem: on adapt T-shirts skin shows on the shoulder top between the neck and the shoulder seam (round 8b
`shoulder_top_skin_px` 3518 / 4213 L / R); only two pairs (collar edge, shoulder seam) set the slope between them.
Keyword `mls.tshirt_layer(..., shoulder_variant="off" | "line")` (default "off", pixel-identical; `render_tryon` never
passes it, tested; a no-op in keep_shape, tested against "off" with the same other keywords on #44 / #45 x 6 avatars
x sleeve C / r7, 0 px). "line", per side (`mls.shoulder_line`): garment = the top alpha edge (alpha > 128) in the
column at 25 / 50 / 75 % of collar edge -> shoulder seam; body = in the column at the same fraction of neck edge
(neck.left_x / right_x) -> acromion, the first background -> figure step under the neck row (the collar_floor rule:
head and hair above the neck row are not taken), target moved UP by `SHOULDER_LINE_EASE` = 2 px; 3 pairs
`sline25|50|75_l|r`, weight 1.0 (the shoulder pair's). A side is skipped and reported when a collar / neck point is
missing or a sample has no edge; columns that are figure at the neck row (head / hair) and near-vertical samples
(|dy/dx| > 2 between neighbour columns) are recorded, nothing changed. Base: sleeve variant C, collar_floor on (default),
side_floor off, neckline r7.

Data: the round 8b exporter with `EXPORT_ROOT=.../data/shoulder9` (current DB). Runner `run_shoulder9.py`: #28, #43, #40
x 6 avatars, adapt (#28 is keep_shape in the DB now; the runner forces adapt like round 8b). Both variants are measured
in the C run's bands. `above` = garment px OUTSIDE the figure in the shoulder-top band (fabric sticking up). `res` = max
distance between a line pair's body target and where its garment point actually lands (forward search in the inverse
map), measured in both variants for the same pairs. Out: `out/table_shoulder9.md`, `out/results_shoulder9.json`,
`out/sheet_shoulder9_<id>.png` (C | C + line, 3x; blue = shoulder-top band, green = body target, magenta = where the
garment point landed), `out/crop_shoulder9_worst.png`, `out/crop_shoulder9_neck_40.png`.

| garment | variant | shoulder-top skin L / R | above shoulder L / R | arm-band skin L / R | gap | excess | fold (max) | line residual px (max L / R) |
|---|---|---|---|---|---|---|---|---|
| #28 | C | 384 / 376 | 4144 / 4252 | 459 / 570 | 2423 | 2144 | 0.00309 | 15.0 / 12.4 |
| #28 | C + line | 1076 / 721 | 725 / 955 | 505 / 609 | 2399 | 217 | 0.00308 | 2.2 / 2.2 |
| #43 | C | 967 / 1054 | 749 / 625 | 2355 / 2643 | 3501 | 39 | 0.00343 | 16.8 / 15.5 |
| #43 | C + line | 1562 / 1333 | 166 / 124 | 2491 / 2717 | 3474 | 34 | 0.00337 | 10.8 / 9.5 |
| #40 | C | 1278 / 1573 | 2042 / 1797 | 2575 / 2390 | 2105 | 3168 | 0.00727 | 31.3 / 31.6 |
| #40 | C + line | 1365 / 1415 | 1039 / 975 | 2572 / 2386 | 2086 | 3055 | 0.00920 | 23.5 / 24.5 |
| all | C | 2629 / 3003 | 6935 / 6674 | 5389 / 5603 | 8029 | 5351 | 0.00727 | 31.3 / 31.6 |
| all | C + line | 4003 / 3469 | 1930 / 2054 | 5568 / 5712 | 7959 | 3306 | 0.00920 | 23.5 / 24.5 |

Runtime 0.087 s max in both. Sampling notes: none (no skipped side, no head / hair column, no near-vertical sample).

Observations (not a decision):
- The reference already differs from round 8b (2629 / 3003 vs 3518 / 4213): collar_floor is on by default now, base C.
- "line" does what it aims at geometrically: the garment's top edge follows the body's shoulder edge (residuals down,
  e.g. #28 15.0 -> 2.2 px), fabric above the shoulder drops 6935 / 6674 -> 1930 / 2054 px, excess on #28 2144 -> 217.
- But **shoulder-top skin goes UP** (2629 / 3003 -> 4003 / 3469): with the edge on the contour a 1-3 px skin sliver
  stays along the whole shoulder line (seen on the sheets). Likely cause, NOT verified: the sampled garment edge is
  alpha > 128 but the layer then drops alpha < 230 (HARD_EDGE), so the visible edge may sit ~1-2 px under the target
  and the 2 px ease is not enough. In C the fabric stood ABOVE the shoulder and covered that strip. Worse than C on at least one metric in 18 / 18 runs (all: shoulder-top skin on
  every #28 / #43 run; #40 mostly fold, 0.00727 -> 0.00920 max, and small arm-band / gap / excess increases).
- #40 neck crops: collar_floor raises nothing on #40 (0 px), so it does not fight the 25 % pair there; neck_l / neck_r
  residuals stay ~2 px except m-average right 2.4 -> 6.7. The 25 % pair pulls the fabric next to the collar corner down
  to the shoulder while the neck pair stays up: a visible kink in the V band near the collar corner (m-plus, f-plus).
  On #28 / #43 (collar_floor raises 0.3-9.8 px) the neck residuals do not change (+-1 px).
- Not tried (the owner's call): a larger ease, measuring the garment edge at the HARD_EDGE alpha, dropping the 25 % pair.

**Re-run with the production neckline (owner 2026-11-13).** The table above used the r7 neckline for every garment:
the runner calls `tshirt_layer` directly and passed no neckline keywords, so #40's stored polygon (13 points) was not
applied and the label / inner back stayed in the crops. Now a garment with `neck_hole.polygon` gets
`neckline_variant="hole"` + the polygon in BOTH variants (as `render_tryon` does; no neck_clip; `NECK_HOLE=0` = the
first run). #28 and #43 have no polygon in the DB: unchanged. The warped hole (union of both variants) is taken out of
the shoulder-top band: without that the intended opening counted as skin (#40 sum 2629 -> 8631 L). The r7-neck run is
kept in `out/shoulder9_r7neck/`.

| #40 | shoulder-top skin L / R | above shoulder L / R | arm-band skin L / R | gap | excess | fold (max) |
|---|---|---|---|---|---|---|
| r7 neck, C | 1278 / 1573 | 2042 / 1797 | 2575 / 2390 | 2105 | 3168 | 0.00727 |
| r7 neck, C + line | 1365 / 1415 | 1039 / 975 | 2572 / 2386 | 2086 | 3055 | 0.00920 |
| hole, C | 745 / 953 | 1655 / 1446 | 2575 / 2390 | 2105 | 3057 | 0.00794 |
| hole, C + line | 1182 / 1211 | 547 / 516 | 2572 / 2386 | 2086 | 2966 | 0.00988 |
| all, hole, C | 2096 / 2383 | 6548 / 6323 | 5389 / 5603 | 8029 | 5240 | 0.00794 |
| all, hole, C + line | 3820 / 3265 | 1438 / 1595 | 5568 / 5712 | 7959 | 3217 | 0.00988 |

With the hole, "line" is worse than C on #40's shoulder-top skin too (it was about even with the r7 neck); still 18 / 18
runs worse on at least one metric. `out/crop_shoulder9_neck_40.png`: the opening is clean (label and inner back gone)
in both variants; with "line" the V band still kinks next to the collar corner (m-plus, f-plus).

**Without the 25 % pair (owner 2026-11-13).** Third variant `C+line50/75` = "line" with `shoulder_fractions=(0.5, 0.75)`
(new benchmark keyword on `tshirt_layer`, default 25 / 50 / 75 %, tested; ignored when the variant is off). Same run as
above (production neckline on #40, hole union of all three variants out of the band; that is why C moved a few px).
Residuals are measured on the 25 / 50 / 75 % points in every variant. The two-variant run is kept in
`out/shoulder9_hole_2var/`.

| garment | variant | shoulder-top skin L / R | above shoulder L / R | arm-band skin L / R | gap | excess | fold (max) | neck residual (max) |
|---|---|---|---|---|---|---|---|---|
| #28 | C | 384 / 376 | 4144 / 4252 | 459 / 570 | 2423 | 2144 | 0.00309 | 2.8 |
| #28 | C + line | 1076 / 721 | 725 / 955 | 505 / 609 | 2399 | 217 | 0.00308 | 2.8 |
| #28 | C + line 50/75 | 889 / 665 | 1516 / 1793 | 497 / 596 | 2401 | 651 | 0.00309 | 2.8 |
| #43 | C | 967 / 1054 | 749 / 625 | 2355 / 2643 | 3501 | 39 | 0.00343 | 2.7 |
| #43 | C + line | 1562 / 1333 | 166 / 124 | 2491 / 2717 | 3474 | 34 | 0.00337 | 2.5 |
| #43 | C + line 50/75 | 1459 / 1263 | 215 / 194 | 2460 / 2694 | 3460 | 34 | 0.00342 | 2.8 |
| #40 | C | 737 / 947 | 1655 / 1446 | 2575 / 2390 | 2105 | 3057 | 0.00794 | 2.4 |
| #40 | C + line | 1181 / 1210 | 538 / 506 | 2572 / 2386 | 2086 | 2966 | 0.00988 | 6.7 |
| #40 | C + line 50/75 | 1173 / 1208 | 520 / 472 | 2569 / 2384 | 2088 | 2934 | 0.00808 | 2.4 |
| all | C | 2088 / 2377 | 6548 / 6323 | 5389 / 5603 | 8029 | 5240 | 0.00794 | |
| all | C + line | 3819 / 3264 | 1429 / 1585 | 5568 / 5712 | 7959 | 3217 | 0.00988 | |
| all | C + line 50/75 | 3521 / 3136 | 2251 / 2459 | 5526 / 5674 | 7949 | 3619 | 0.00808 | |

Observations (not a decision):
- Dropping the 25 % pair removes the V-band kink next to the collar corner on #40 (`crop_shoulder9_neck_40.png`,
  third column) and its side effects: fold max 0.00988 -> 0.00808 (C 0.00794), neck residual max 6.7 -> 2.4 px.
- Shoulder-top skin is a little lower than with the 25 % pair but still higher than C on every garment (all
  3521 / 3136 vs C 2088 / 2377); fabric above the shoulder stays far below C (2251 / 2459 vs 6548 / 6323).
- Still worse than C on at least one metric in 18 / 18 runs (both line variants).

**Round 9b: garment edge at the HARD_EDGE alpha (2026-11-13, NOT production, no winner).** Same data / setup (production
neckline on #40). New benchmark keywords on `tshirt_layer` (ignored when the variant is off, tested):
`shoulder_edge_alpha` (default 128; the garment edge = first row with alpha > it) and `shoulder_ease` (default 2 px).
Variants, all full line 25 / 50 / 75 %: `line_hard2` (edge alpha > HARD_EDGE - 1 = 228, i.e. the edge the fitted layer
keeps, ease 2), `line_hard4` (the same, ease 4). shoulder_top_skin is split: **edge skin** = uncovered figure px within
4 px below the body's top edge (first background -> figure step under the neck row, per column: the thin line);
**inner skin** = the rest of the band. Residuals: each line variant on its own pairs. Runner `run_shoulder9b.py` ->
`out/table_shoulder9b.md`, `out/results_shoulder9b.json`, `out/sheet_shoulder9b_<id>.png` (C | C+line | line_hard2 |
line_hard4; #40 also shows the competing pairs' targets in orange with their names).

| | variant | edge skin L / R | inner skin L / R | above shoulder L / R | arm-band skin L / R | gap | excess | fold (max) | line residual max L / R |
|---|---|---|---|---|---|---|---|---|---|
| all | C | 1168 / 1063 | 849 / 1249 | 6548 / 6323 | 5389 / 5603 | 8029 | 5240 | 0.00794 | 31.3 / 31.6 |
| all | C+line | 2901 / 1967 | 840 / 1227 | 1438 / 1595 | 5568 / 5712 | 7959 | 3217 | 0.00988 | 23.5 / 24.5 |
| all | line_hard2 | 2131 / 1310 | 829 / 1219 | 1664 / 1898 | 5567 / 5713 | 7974 | 3240 | 0.01015 | 22.8 / 23.8 |
| all | line_hard4 | 1035 / 748 | 820 / 1211 | 2262 / 3088 | 5551 / 5717 | 7995 | 3295 | 0.00999 | 23.1 / 24.0 |
| #28 | C / C+line / hard2 / hard4 | 158/106, 850/451, 503/242, 189/107 | 226 / 270 (all) | 4144/4252, 725/955, 861/1126, 1203/1687 | | | 2144, 217, 235, 235 | | |
| #43 | C / C+line / hard2 / hard4 | 643/566, 1251/867, 978/590, 489/341 | 324/488 .. 295/450 | 749/625, 166/124, 192/171, 323/529 | | | | | |
| #40 | C / C+line / hard2 / hard4 | 367/391, 800/649, 650/478, 357/300 | 299/491 (all) | 1655/1446, 547/516, 611/601, 736/872 | | | | 0.00794 .. 0.01015 | |

Observations (not a decision):
- The skin increase of round 9 is the thin edge line: inner skin is the same in every variant (+-30 px); only edge
  skin moves. Measuring the garment edge at the HARD_EDGE alpha shrinks it, ease 4 removes it: **line_hard4 has less
  edge skin than C** (1035 / 748 vs 1168 / 1063 summed) and still 2.0 / 2.9x less fabric above the shoulder than C
  (2262 / 3088 vs 6548 / 6323).
- line_hard4 is still worse than C on at least one metric in 18 / 18 runs: arm-band skin (L 15, R 13 runs, +0.5-3 %),
  fold (13 runs, max 0.00794 -> 0.00999, mostly #40), edge skin L (11 runs, small per run although the sum drops), gap
  (7), above (3 / 4: #43 left / right), excess (4).
- **#40 residual 15-24 px, what competes (not fixed):** collar_floor raises nothing on #40 (0 px), so it is not the
  cause. The line pairs fight `neck_l` / `neck_r` (weight 5) and `shoulder_l` / `shoulder_r` (weight 1): per line pair
  the furthest-off stretch |dp| / (s |dq|) is 0.45-0.71 against neck (compressed) and 1.36-1.70 against shoulder
  (stretched); on m-plus the 75 % pairs also pull against `smid_in` (x0.63-0.68). Cause, from the pair positions (C+line,
  m-slim, left): garment `sline25_l` q (210, 32) is OUTSIDE `neck_l` q (240, 12), but its body target p (246, 231) is
  INSIDE neck_l's target (237.8, 225): #40's wide V collar lands outside the body's neck edge, while the line samples
  start AT the neck edge, so the near-neck line pairs cross the neck pairs; the heavier neck pair wins. #28 / #43 (crew)
  residuals: 2.2 px (#28), 9.5-11.7 (#43).
- Re-run without the neck hole (owner 2026-11-13, `NECK_HOLE=0`, r7 neckline on #40; the files in `out/` are this run,
  the hole run is kept in `out/shoulder9b_hole/`): all C 1348 / 1258 edge, 1281 / 1745 inner, 6935 / 6674 above;
  line_hard4 1077 / 793, 938 / 1353, 2894 / 3638; same picture (line_hard4 edge skin below C).
- Final sheets (owner 2026-11-13): `CLEAN=1 NECK_HOLE=1` = as the user sees the result (production neckline: #40's
  hole cut; no bands, dots or pair names). `out/` holds this run (its table = the hole run); the no-hole run with
  overlays is in `out/shoulder9b_nohole/`, the hole run with overlays in `out/shoulder9b_hole/`.
- Re-export after the owner's edits (2026-11-13): female slim / average shoulder points moved (f-slim y 261 -> 253,
  x 175 / 422 -> 182 / 420; f-average y 270 -> 264, x 180 / 424 -> 184 / 422) and #28 / #43 got owner polygons, so
  all three garments now have the hole. Clean sheets regenerated; all C edge 555 / 420, above 7517 / 7173; line_hard4
  edge 598 / 376, above 2518 / 3432. The shoulder-top band follows the shoulder point, so before / after numbers of
  the two female avatars are not like for like. Previous clean run: `out/shoulder9b_clean_before_female_1532/`,
  previous export: `data/shoulder9_prev_*`.
- **Owner decision 2026-11-13 (docs/09 #104): production uses C (sleeve variant C, shoulder line off).** The line
  variants stay benchmark keywords.
- Open (owner): start the body samples at the collar target instead of the neck edge on wide necks; use line_hard4 50/75
  (round 9 showed the 25 % pair kinks the V band); arm-band / fold side effects.

### Tube sleeve, round 11 (2026-11-13, NOT production, no winner picked)
Why: rigid MLS cannot widen the sleeve to the arm (rounds 8 / 8b): skin windows at the shoulder / sleeve join and wavy
cuffs remain with sleeve C. Keyword `mls.tshirt_layer(..., sleeve_mode="mls" | "tube")` (default "mls",
pixel-identical; `render_tryon` never passes it; a no-op in keep_shape, tested on #44 / #45; torso px never change,
tested on #28). "tube" (`mls.tube_sleeves`, per side, adapt only): the sleeve is a ruled strip, t = 0 on the armhole
segment (garment: shoulder seam -> armpit; body: shoulder target -> armpit target), t = 1 on the cuff segment
(garment: cuff_outer -> cuff_inner; body: perpendicular to the arm axis at sleeve length x s), u across (outer /
inner measured separately). At `TUBE_SECTIONS` = 6 cross-sections: output width = max(garment x s, arm extent in the
mask outward of the armhole line x CUFF_ARM_EASE 1.1); t = 0 keeps the armhole segment. The strip is meshed (t x u
36 x 22) and each triangle mapped affinely back to the garment; one `cv2.remap` for the whole garment. Within
`TUBE_BLEND_PX` = 10 px of the body armhole segment the tube map is smoothstep-blended into the MLS map. The tube
domain is clipped to the outward side of the body armhole line; there, px whose MLS source is a sleeve px and that the
tube does not draw are cleared (reported). The first version let the u margin reach inward past the armpit and cleared
34 torso px under the armpit on #28 / m-slim (caught by the torso test); fixed by the clip.

Reference = the owner's adapt: sleeve C + side_floor (both variants; `render_tryon` does not pass side_floor yet),
collar_floor on, the garment's neck_hole polygon. Data: the round 8b exporter with `EXPORT_ROOT=.../data/tube11`.
Runner `run_tube11.py` -> `out/table_tube.md`, `out/results_tube.json`, `out/sheet_tube_<id>.png` (reference | tube,
3x; yellow = body arm axis, cyan = arm centreline from the mask, grey = cross-sections, red = cuff),
`out/crop_tube_armhole_worst.png`, `out/crop_tube_worst.png`.

| garment | variant | arm-band skin L / R | cuff wave median / max L, R | balloon L / R | armhole seam L / R | cleared L / R | gap | excess | fold (max) |
|---|---|---|---|---|---|---|---|---|---|
| #28 | reference | 428 / 554 | 8.0 / 27.0, 12.9 / 29.7 | 212 / 343 | 119 / 37 | - | 2344 | 2260 | 0.00226 |
| #28 | tube | 5877 / 7193 | 1.0 / 20.6, 9.1 / 20.2 | 1009 / 415 | 10 / 4 | 9702 / 10407 | 92 | 2718 | 0.0005 |
| #43 | reference | 2236 / 2615 | 16.2 / 20.9, 9.4 / 11.4 | 117 / 338 | 248 / 32 | - | 3439 | 139 | 0.00274 |
| #43 | tube | 7556 / 8002 | 4.5 / 19.0, 9.3 / 11.2 | 992 / 611 | 256 / 333 | 9146 / 9311 | 110 | 772 | 0.0006 |
| #40 | reference | 2575 / 2372 | 5.1 / 5.5, 7.0 / 8.7 | 1277 / 1957 | 30 / 0 | - | 2217 | 3667 | 0.00609 |
| #40 | tube | 6513 / 6553 | 13.8 / 13.8, 19.6 / 19.6 | 5844 / 5802 | 269 / 281 | 6963 / 7445 | 1201 | 10897 | 0.0015 |
| all | reference | 5239 / 5541 | | 1606 / 2638 | 397 / 69 | - | 8000 | 6066 | 0.00609 |
| all | tube | 19946 / 21748 | | 7845 / 6828 | 535 / 618 | 25811 / 27163 | 1403 | 14387 | 0.0015 |

Runtime: reference max 0.136 s, tube max 0.251 s.

Observations on this FIRST version (before the fixes below; not a decision):
- **The ruled strip degenerates on short sleeves.** The armhole segment is LONGER than the sleeve axis and slanted to
  it (#28: armhole 112 px, axis 67 px, 39 deg; #43: 188 / 85 / 36 deg; #40: 272 / 111 / 46 deg), and the inner edge
  (armpit -> cuff_inner) is only 23-30 px against 111-198 px on the outer edge: the strip is a wedge, not a tube. The
  cross-sections fan out from the underarm (see the grey lines on the sheets); the tube narrows the upper sleeve, so
  the MLS sleeve px that were cleared (7-10 k px per side) are not replaced: arm-band skin x3.8 / 3.9 (L / R), balloon x4.9 / 2.6.
- What improved: gap 8000 -> 1403, fold 0.00609 -> 0.0015, the #28 / #43 cuff is straighter (median wave 8.0 -> 1.0,
  16.2 -> 4.5 on the left); the armhole seam is smaller on #28 only.
- Worse than the reference on at least one metric in 18 / 18 runs.
- axis_dev 10.8-12.0 px on every avatar (all flagged > 5 px): not trustworthy as built, the arm extent inward is cut
  at the armhole line, so the measured "centre" is shifted outward by construction.
- Not tried (owner's call): t = 0 on a line perpendicular to the arm axis through the shoulder seam (the underarm
  triangle left to MLS), cross-sections perpendicular to the axis everywhere, a real arm-centreline axis.

**Debug on #28 / m-average (owner 2026-11-13, `debug_tube11.py`).** The first version did not shift the sleeve
sideways at the cuff (tube cuff midpoint vs the `_arm_at` arm fit: +1.7 / -1.3 px); it was SHORT: body axis 66.4 /
64.5 px (garment axis 67.4 / 65.4 x s 0.985) against 81.1 / 81.0 px from the armhole midpoint to the reference cuff
midpoint (cuff y ~374 vs ~388). The torso is scaled 1.065 vertically, s 0.985, and the body armhole midpoint sits lower
relative to the shoulder than the garment's. The cleared, not re-covered px (952 / 1203) were the band between the two
cuffs. At t = 0 the body armhole (90 px) is shorter than the garment's x s (110 px), so the width jumped 45 -> 51.7 at
t = 0.17. The mask's arm merges with the torso down to y ~392-395 on this avatar, so the first axis_dev (a march along
the slanted cross line) ran into the torso: not valid. Overlay of that version: `out/debug_tube_28_m-average.png`.

**Fixes (owner 2026-11-13) and tube_perp.** (1) The body axis ends on the midpoint of the MLS cuff targets (sleeve C),
the cuff segment perpendicular to the axis there. (2) Output half-width = max(arm extent x CUFF_ARM_EASE, ramp), ramp =
smoothstep over t <= `TUBE_RAMP_T` = 0.33 from the t = 0 width to garment x s; the arm floor holds at every section
after t = 0 (t = 0 is pinned; tested). (3) axis_dev = max |axis x - `_arm_at` x| over the sections with t >= 0.5
(`_arm_at` = the straight fit through the first separated arm rows, extrapolated upward). New mode `tube_perp`: every
cross-section perpendicular to the axis, t = 0 = the perpendicular through the shoulder seam / shoulder target, the
underarm triangle between that line and the armhole stays MLS (never cleared); blend distance measured from the t = 0
segment in both modes. Torso test and keep_shape no-op cover both modes. 340 backend tests pass, none skipped.

Re-run, reference | tube | tube_perp (side_floor on in all, `out/table_tube.md`, sheets `out/sheet_tube_<id>.png`
with three columns, `out/crop_tube_armhole_worst.png`, `out/crop_tube_worst.png`, debug overlays
`out/debug_tube_28_m-average_tube.png` / `_tube_perp.png`):

| garment | variant | arm-band skin L / R | cuff wave median / max L, R | balloon L / R | armhole seam L / R | cleared L / R | gap | excess | fold (max) | axis dev max L / R |
|---|---|---|---|---|---|---|---|---|---|---|
| #28 | reference | 428 / 554 | 8.0 / 27.0, 12.9 / 29.7 | 212 / 343 | 119 / 36 | - | 2344 | 2260 | 0.00226 | - |
| #28 | tube | 605 / 787 | 1.7 / 22.4, 7.9 / 20.8 | 1598 / 552 | 15 / 9 | 1974 / 2741 | 411 | 3130 | 0.00152 | 18.5 / 11.0 |
| #28 | tube_perp | 2672 / 1266 | 19.9 / 22.4, 20.1 / 25.1 | 2080 / 402 | 2552 / 512 | 3426 / 3749 | 624 | 3375 | 0.00136 | 21.5 / 16.6 |
| #43 | reference | 2236 / 2615 | 16.2 / 20.9, 9.4 / 11.4 | 117 / 341 | 248 / 32 | - | 3439 | 139 | 0.00274 | - |
| #43 | tube | 899 / 1509 | 1.0 / 27.0, 4.5 / 14.4 | 1242 / 680 | 38 / 3 | 946 / 992 | 282 | 805 | 0.00178 | 18.1 / 13.5 |
| #43 | tube_perp | 3625 / 3392 | 16.0 / 26.0, 16.3 / 18.6 | 982 / 424 | 3090 / 1882 | 2908 / 2573 | 250 | 584 | 0.00135 | 21.7 / 18.2 |
| #40 | reference | 2575 / 2372 | 5.1 / 5.5, 7.0 / 8.7 | 1278 / 1970 | 30 / 0 | - | 2217 | 3667 | 0.00609 | - |
| #40 | tube | 2883 / 2800 | 6.0 / 7.0, 5.0 / 6.0 | 6698 / 6788 | 8 / 0 | 1228 / 1425 | 579 | 12444 | 0.0023 | 19.7 / 13.8 |
| #40 | tube_perp | 5688 / 5504 | 5.0 / 5.3, 4.4 / 5.0 | 6526 / 6767 | 3667 / 3048 | 4183 / 3850 | 47 | 12619 | 0.00175 | 22.6 / 18.8 |
| all | reference | 5239 / 5541 | 8.0 / 27.0, 8.6 / 29.7 | 1607 / 2654 | 397 / 68 | - | 8000 | 6066 | 0.00609 | - |
| all | tube | 4387 / 5096 | 1.8 / 27.0, 5.0 / 20.8 | 9538 / 8020 | 61 / 12 | 4148 / 5158 | 1272 | 16379 | 0.0023 | 19.7 / 13.8 |
| all | tube_perp | 11985 / 10162 | 5.3 / 26.0, 15.1 / 25.1 | 9588 / 7593 | 9309 / 5442 | 10517 / 10172 | 921 | 16578 | 0.00175 | 22.6 / 18.8 |

Runtime max: reference 0.150 s, tube 0.302 s, tube_perp 0.301 s. Worse than the reference on at least one metric:
tube 17 / 18 runs (arm L 12, arm R 11, balloon L 15, balloon R 14, excess 14, fold 9, wave L 8, wave R 3, seam L 2),
tube_perp 18 / 18 (arm L 18, arm R 17, balloon L 18, balloon R 12, seam L 18, seam R 18, excess 15, fold 7, wave L 6,
wave R 4). #28 / m-average after the fixes: tube axis length 81.1 / 80.9 px (= the reference cuff), cleared not
re-covered 132 / 236 px, px over the background 536 / 511 (reference 96 / 423); tube_perp axis 119.8 / 119.7 px, cleared
not re-covered 474 / 336, over the background 660 / 425. axis_dev is measured against an upward extrapolation of the
lower arm; at the cuff row itself the tube axis is -1.6 / 0.0 px from the `_arm_at` fit.
Clean sheets (owner 2026-11-13, `CLEAN=1`: the garment as the user sees it, no axes / sections / numbers) are in
`out/sheet_tube_<id>.png`; the sheets with the overlays are kept in `out/tube11_overlays/`. Numbers unchanged.

**Layering fix (owner 2026-11-13, #40 underarm).** The grey tank showed under both armpits on #40 (tube): MLS sleeve
px outward of the armhole line were cleared and the underarm triangle was not re-covered by the tube; the torso test
does not see it (outside the torso). Now (both modes) the tube is a separate map drawn OVER the MLS layer
(premultiplied "over", tube wins where both exist, the blend at the armhole kept); an MLS px is cleared only when its
source is a sleeve px, the tube does not draw it, it is outward of the armhole line and over the background beyond
the figure dilated by the arm ease (median arm half-width x (CUFF_ARM_EASE - 1), at least 1 px). New metric and test
"no new holes": figure px uncovered by the garment in the shoulder / armpit / sleeve zone (outward of the reference
armhole line above the lower cuff target + 10 px, plus 15 px around the armhole segment) that the reference covers;
test `TubeSleeveTests.test_no_new_holes_in_the_shoulder_armpit_sleeve_zone` (#28, #40 x 6 avatars x both modes, 0 px).
341 backend tests pass, none skipped. Sheets now carry an underarm crop (both sides, 4x) under each cell; full renders
`out/render_tube_<id>.png` (real `render_tryon`, benchmark keywords added in-process only). Previous outputs:
`out/tube11_before_layering/`.

| garment | variant | arm-band skin L / R | cuff wave median / max L, R | balloon L / R | armhole seam L / R | new holes L / R | cleared L / R | gap | excess | fold (max) |
|---|---|---|---|---|---|---|---|---|---|---|
| #28 | reference | 428 / 554 | 8.0 / 27.0, 12.9 / 29.7 | 212 / 343 | 119 / 36 | 0 / 0 | - | 2344 | 2260 | 0.00226 |
| #28 | tube | 196 / 229 | 21.4 / 23.4, 16.0 / 29.6 | 1610 / 659 | 9 / 7 | 0 / 0 | 72 / 396 | 470 | 3181 | 0.00171 |
| #28 | tube_perp | 197 / 240 | 21.4 / 24.1, 16.0 / 24.8 | 2080 / 606 | 7 / 36 | 0 / 0 | 144 / 1001 | 484 | 3449 | 0.00293 |
| #43 | reference | 2236 / 2615 | 16.2 / 20.9, 9.4 / 11.4 | 117 / 341 | 248 / 32 | 0 / 0 | - | 3439 | 139 | 0.00274 |
| #43 | tube | 730 / 1286 | 12.5 / 27.0, 13.2 / 18.1 | 1247 / 785 | 33 / 1 | 0 / 0 | 42 / 255 | 586 | 885 | 0.002 |
| #43 | tube_perp | 651 / 1035 | 10.8 / 26.0, 13.1 / 19.4 | 1009 / 587 | 45 / 3 | 0 / 0 | 269 / 700 | 577 | 653 | 0.00369 |
| #40 | reference | 2575 / 2372 | 5.1 / 5.5, 7.0 / 8.7 | 1278 / 1970 | 30 / 0 | 0 / 0 | - | 2217 | 3667 | 0.00609 |
| #40 | tube | 2347 / 2230 | 5.8 / 6.7, 5.5 / 6.0 | 6707 / 6835 | 3 / 0 | 0 / 0 | 19 / 112 | 1877 | 12485 | 0.0029 |
| #40 | tube_perp | 2065 / 2011 | 5.2 / 6.8, 8.0 / 8.4 | 6541 / 6845 | 11 / 0 | 0 / 0 | 472 / 527 | 1563 | 12675 | 0.00474 |
| all | reference | 5239 / 5541 | 8.0 / 27.0, 8.6 / 29.7 | 1607 / 2654 | 397 / 68 | 0 / 0 | - | 8000 | 6066 | 0.00609 |
| all | tube | 3273 / 3745 | 9.6 / 27.0, 9.0 / 29.6 | 9564 / 8279 | 45 / 8 | 0 / 0 | 133 / 763 | 2933 | 16551 | 0.0029 |
| all | tube_perp | 2913 / 3286 | 7.9 / 26.0, 9.9 / 24.8 | 9630 / 8038 | 63 / 39 | 0 / 0 | 885 / 2228 | 2624 | 16777 | 0.00474 |

Runtime max: reference 0.173 s, tube 0.266 s, tube_perp 0.464 s. Worse than the reference on at least one metric:
tube 18 / 18 runs, tube_perp 18 / 18 runs (per-run list in `out/table_tube.md`).

For later (not built): `TUBE_SECTIONS` is a parameter so long sleeves could reuse the tube. The MVP stays the
short-sleeve T-shirt (docs/02). Long sleeves would also need: only the hands drawn above the garment (today the
forearms are drawn above it too), a new garment type with its own landmarks and checks, and AI / code validation that
accepts long-sleeved garments.

### Side coverage, round 12 (2026-11-13, NOT production, no winner picked)
Problem: with side_floor on, grey strips of the avatar's own tank show beside the torso, mostly on plus avatars
(round 11 sheets: #28 m-plus, f-plus, #43 f-plus).

**Step 1, where side_floor takes the body edge from (`run`: `mls._torso_edges`, `_add_side_floor_pairs`).** Body edge =
the mask's torso run through the body axis; when that run is > 1.3x the landmark span (`body_span`: an arm touching the
torso) or missing, the landmark span is used. Ease = 1.5 % of the torso width. Floor pairs only on 3 rows per side
(`side_a` = 1/3 and `side_b` = 2/3 of the garment's armpit -> hem rows, `side_hip` = the body hip row), and only where
the first solve leaves the garment edge inside the floor; plus the adapt main pairs (armpit, chest, waist, hem; on #28
f-plus `chest_l` / `chest_r` were dropped). #28 f-plus (round 11 reference + tube, `debug_side12.py`,
`out/debug_side12_28_f-plus.png`): rows 334-406 (and 418 left) use the landmark span (arm touching); there the old
count could not be measured (the run contains the arm). On the mask rows the garment edge sits 1-4 px inside the mask
edge from 430 to 514, and 9-15 px inside from 526 to 574 (left; right 5-11 px): between `side_b` (y 505) and
`side_hip` (y 605) there is no pair. Uncovered torso px on the mask rows: L 2069 / R 664 (rows 505-605: 967 / 588).

**Method.** Keyword `mls.tshirt_layer(..., side_floor_mode="landmarks" | "mask")` (default "landmarks", pixel-identical;
only with side_floor=True; a no-op in keep_shape, tested on #44 / #45; `render_tryon` never passes it). "mask"
(`_add_side_floor_mask_pairs`), in addition to the 3 landmark floor pairs: every `SIDE_FLOOR_STEP` = 12 px from armpit +
2 to the hem target, per side, the torso edge from `torso_side_edges` (the mask's torso run; a side is "clean" when its
edge is <= `SIDE_TOUCH` = 1.3x the landmark half-span from the axis; arm-touch rows are interpolated linearly between
the nearest clean rows of that side, the body armpit landmark is the anchor above when no clean row is above, and
flagged "interp"); garment edge = the outermost px of the first solve's covered run through the axis at alpha >=
HARD_EDGE; where that edge is inside the torso edge: pair q = that px's garment point, p = torso edge
`SIDE_FLOOR_EASE_PX` = 2 px outward, weight 1.0; rows within 6 px of a landmark floor pair are skipped; a pair that
breaks the vertical order of its side (vs the other side pairs) is dropped. Two earlier attempts during the run: replacing
the landmark floor pairs (no `side_hip`) opened the hem corners (2242 new hole px on #28 f-plus); stopping the rows
24 px above the hem made it worse (2555).

Reference = sleeve C + side_floor (landmarks) + sleeve_mode "tube" (layering fix) + collar_floor + the neck_hole
polygon; mask = the same + side_floor_mode "mask". Data: the round 8b exporter with `EXPORT_ROOT=.../data/side12`.
Runner `run_side12.py` -> `out/table_side12.md` (incl. the #28 f-plus per-row tables, reference vs mask),
`out/results_side12.json`, `out/sheet_side12_<id>.png` (reference | mask, 3x side crops), `out/crop_side12_worst.png`.
Side strip = figure px not covered between the torso edge and the axis, rows armpit + 2 -> 20 px above the hem target
(the hem is a later round); new holes split into side rows and the hem band (20 px above the hem target -> 20 below).

| garment | variant | side strip L / R | of it arm-touch rows L / R | new holes side rows L / R | new holes hem band | newly covered | excess | hem curve px (max) | fold (max) |
|---|---|---|---|---|---|---|---|---|---|
| #28 | reference | 6211 / 3109 | 1131 / 1080 | 0 / 0 | 0 | 0 | 3181 | 19.0 | 0.00171 |
| #28 | mask | 2817 / 1831 | 393 / 350 | 361 / 1115 | 5964 | 6078 | 3502 | 17.5 | 0.00359 |
| #43 | reference | 7286 / 3308 | 1627 / 1196 | 0 / 0 | 0 | 0 | 885 | 23.5 | 0.00200 |
| #43 | mask | 4738 / 2261 | 617 / 353 | 1557 / 1763 | 9435 | 6973 | 1149 | 22.6 | 0.00895 |
| #40 | reference | 3862 / 1570 | 2245 / 1155 | 0 / 0 | 0 | 0 | 12485 | 10.2 | 0.00290 |
| #40 | mask | 2088 / 278 | 898 / 240 | 378 / 53 | 2481 | 4144 | 13318 | 9.8 | 0.00350 |
| all | reference | 17359 / 7987 | 5003 / 3431 | 0 / 0 | 0 | 0 | 16551 | 23.5 | 0.00290 |
| all | mask | 9643 / 4370 | 1908 / 943 | 2296 / 2931 | 17880 | 17195 | 17969 | 22.6 | 0.00895 |

Runtime max: reference 0.403 s, mask 0.464 s. #28 f-plus per row (left, uncovered px, reference -> mask): 382: 12 -> 7,
394: 12 -> 3, 538: 14 -> 3, 550: 15 -> 2, 562: 14 -> 3; right 382: 19 -> 16, 538: 10 -> 0; at 598 the garment's hem
reaches the row in mask (L 3 -> 26, R 0 -> 56). Hem bottom on #28 f-plus, measured on the r10 test fixture during the diagnosis (columns 250 / 350 / 400): 611 -> 605 px
(hem_c column 300: 625 -> 624).
Sheets with the whole T-shirt (owner 2026-11-13, `FULL=1`: neck -> below the hem, full width, 2x, short labels) are in
`out/sheet_side12_<id>.png`; the side-crop sheets are kept in `out/side12_side_crops/`. Numbers unchanged.

**Round 12, second pass (owner 2026-11-13: keep "mask" as the base; three issues).**
(1) Hem tongue: no "mask" floor rows in the hem band (`SIDE_FLOOR_HEM_BAND` = 8 % of shoulder -> hem target); the
removed rows are reported (`info["side_floor_mask"]["hem_band_removed_rows"]`, e.g. #28 f-slim 577 / 589 / 601, f-plus
598 / 610). New metric hem_tongue_px = max drop of the bottom edge (alpha >= HARD_EDGE) in the middle 20 % of the torso
hem below the line between its corners (only columns whose bottom is within 60 px of the hem target row; the first
attempt measured the sleeve-level bottoms at the corners and gave 149-267 px: not valid).
(2) Tube in the reference: on (report present, no side skipped); sleeve-source px visible beyond the tube cuff line:
19 / 29 (#28 f-slim). The MLS sleeve px the tube does not draw stay where they lie over the arm (layering fix), next
to the tube. Clearing them over the arm beyond half the axis was tried and reverted: 117-144 px of new holes inside
the sleeve (#28 m-slim / m-average, #40 f-plus), the tube is narrower than the arm there (its arm floor stops at the
armhole line).
(3) `hem_mode="smooth"` (keyword, default "off", adapt only, `smooth_hem`): on the torso-hem columns (bottom within
`HEM_SMOOTH_NEAR` = 60 px of the hem target; the first version also took sleeve-level bottoms, max move 98-107 px),
the bottom edge is low-passed (Gaussian, sigma = `HEM_SMOOTH_WAVE` 0.15 x width / 3); the edge moves down, or up only
where every uncovered row is background; vertical remap of the layer inside `HEM_SMOOTH_BAND` (8 % of the torso
length). Tests: default / keep_shape 0 px, smooth never uncovers a figure px, no mask rows in the hem band. 346 backend
tests pass, none skipped.

| garment | variant | side strip L / R | arm-touch rows L / R | new holes side L / R | new holes hem band | newly covered | hem tongue px (max) | hem wave px (max) | excess | fold (max) |
|---|---|---|---|---|---|---|---|---|---|---|
| #28 | reference | 6211 / 3109 | 1131 / 1080 | 0 / 0 | 0 | 0 | 7.5 | 3.5 | 3181 | 0.00171 |
| #28 | mask | 3032 / 1841 | 393 / 350 | 570 / 1126 | 6541 | 6065 | 20.8 | 7.4 | 3508 | 0.00394 |
| #28 | mask + smooth | 2926 / 1744 | 393 / 350 | 464 / 1029 | 6010 | 6065 | 20.3 | 6.9 | 3508 | 0.00393 |
| #43 | reference | 7286 / 3308 | 1627 / 1196 | 0 / 0 | 0 | 0 | 13.5 | 4.3 | 885 | 0.00200 |
| #43 | mask | 4920 / 2304 | 617 / 353 | 1762 / 1806 | 9581 | 6995 | 27.6 | 11.2 | 1148 | 0.00960 |
| #43 | mask + smooth | 4621 / 1997 | 617 / 353 | 1462 / 1499 | 8975 | 6994 | 25.6 | 9.5 | 1147 | 0.00976 |
| #40 | reference | 3862 / 1570 | 2245 / 1155 | 0 / 0 | 0 | 0 | 16.0 | 6.9 | 12485 | 0.00290 |
| #40 | mask | 2088 / 278 | 898 / 240 | 378 / 53 | 2481 | 4144 | 13.1 | 4.5 | 13318 | 0.00350 |
| #40 | mask + smooth | 2088 / 278 | 898 / 240 | 378 / 53 | 2211 | 4180 | 9.8 | 3.6 | 13316 | 0.00349 |
| all | reference | 17359 / 7987 | 5003 / 3431 | 0 / 0 | 0 | 0 | 16.0 | 6.9 | 16551 | 0.00290 |
| all | mask | 10040 / 4423 | 1908 / 943 | 2710 / 2985 | 18603 | 17204 | 27.6 | 11.2 | 17974 | 0.00960 |
| all | mask + smooth | 9635 / 4019 | 1908 / 943 | 2304 / 2581 | 17196 | 17239 | 25.6 | 9.5 | 17971 | 0.00976 |

Runtime max: reference 0.353 s, mask 0.437 s, mask + smooth 0.450 s. Runs with hem tongue > reference + 1 px: mask 6 /
18, mask + smooth 7 / 18; hem wave > reference + 1 px: 8 / 18 both; smooth max edge move 8 px. Sheets
(`out/sheet_side12_<id>.png`, `FULL=1`): reference | mask | mask + smooth; the two-column run is in `out/side12_2col/`.

### Hem and tube, round 12b (2026-11-15, NOT production, no winner picked)
Owner 2026-11-15: report the tongue, fix every new hole of "mask", tube with the underarm fix in the reference, a
garment-hem mode, an extra hem_c column, the #28 f-plus armpit. Runner `run_hem12b.py` (data: round 8b exporter,
`data/side12`) -> `out/table_hem12b.md`, `out/results_hem12b.json`, `out/sheet_hem12b_<id>.png` (clean, whole T-shirt:
reference | + smooth | + garment | + hem_c), `out/sheet_tube12b_40.png` (tube r11 | tube fit). Exit status 1 when a
run has new holes > 0.

**Round 12 numbers asked for (before 12b).** hem_tongue_px reference / mask / mask + smooth: #28 f-slim 5.5 / 20.8 /
20.3, #43 f-slim 9.5 / 17.0 / 18.0, #43 f-average 10.5 / 27.6 / 25.6, #43 f-plus 10.0 / 14.5 / 16.0, #43 m-plus
13.5 / 19.6 / 16.5, #28 f-plus 5.5 / 9.0 / 10.5; the other 12 runs within 1.1 px of the reference. The hem-band
exclusion was active in every mask run (rows removed: slim 577 / 589 / 601 or 579 / 591, average 605 / 617 or 609 /
621, plus 606 / 618 / 630, f-plus 598 / 610). New holes of mask (vs the landmark floor, whole canvas, alpha >= 128):
#28 m-slim 638 ... #43 f-plus 3602 px; in the round 12 table 18603 of 24298 px (77 %) in the hem band (the hem rises
between corner and centre, components ~100 px wide, 7-41 px high), the rest 1-12 px wide side slivers and 5-18 px
spots at the armpits.

**Why the #28 f-plus "grey hole" was not flagged.** Its px were NOT covered by the round 12 reference either (the
reference leaves the whole underarm strip open there); mask covered more around them and left an island, so it looked
like a hole. "New holes" counts only px the reference covered, so it could not see it. Besides, the counts were
reported, never asserted (no test compared mask with the landmark floor). Now: no island (the 12b reference shows the
open strip of the round 12 reference); the side strip under the arm is still open (side coverage, not solved).

**Method.** All keywords default off (pixel-identical), adapt only (keep_shape 0 px on #44 / #45), render_tryon never
passes them.
- side_floor_mode "mask", no new holes: (1) `_blend_new_holes`: figure px covered by the landmark floor solve and not
  by the mask solve (warped alpha, eroded like remove_halo, >= HARD_EDGE, the owner's neck hole applied) get the
  landmark floor map back locally (region grown 4 px x round, Gaussian ramp sigma 4 px; at most 4 rounds; blend 4666 -
  54261 px, 1-3 rounds, residual 0 in every run). (2) Last guard: the finished landmark floor layer is built too; a
  figure px it covers and the mask layer does not takes its px (`patched_px`: #43 m-plus 13, #43 f-average 1, #40
  m-average 1, others 0). Tried first and dropped: anchor pairs at the holes (4 rounds, 17-597 px left per run, new
  holes at the shoulders); the guard alone on the round 12 mask (2524 px patched on #28 f-plus, visible patch seams).
- `tube_arm="fit"`: arm extents per cross-section also from the straight arm fit (`_arm_fit_extent`, `_arm_at`
  converted to the cross-section direction), max with the march; half-widths clamp(ramp, arm x 1.1, arm x
  TUBE_ARM_MAX 1.25); the MLS sleeve px beyond the tube cuff line (strip of the cuff width x 1.25) cleared. Tried and
  dropped: a round 11 tube map fallback (the last guard does it).
- `hem_mode="garment"` (`garment_hem`): target = line between the hem targets + s x the garment's own hem offset
  (alpha bottom minus the line between its end bottoms; offsets 0-8.8 / 0-25.0 / 0-17.5 garment px on #28 / #43 / #40),
  down freely, up only through background; band max(8 % torso, 2 x largest move). `_hem_column_remap` (shared with
  smooth) puts back a figure px the remap uncovered (garment: 0-124 px per run, slanted corner edges; smooth: 0-1).
- `hem_c_pair=True`: adapt already has hem_c (garment hem landmark row at the centre -> torso centre on the hem target
  row); this replaces q with the garment's alpha bottom at the centre column (5.0 / 14.0 / 15.0 px below the landmark
  row on #28 / #43 / #40) and p with the midpoint of the hem targets.

| garment | variant | hem tongue px (max) | hem wave px (max) | max band stretch | side strip L / R | new holes | beyond cuff px | balloon L / R | arm-band skin L / R | fold (max) | runtime s (max) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| #28 | r12ref | 7.5 | 3.5 | - | 6211 / 3109 | - | - | 1610 / 659 | 196 / 229 | 0.00171 | 0.267 |
| #28 | reference | 7.5 | 3.5 | - | 3551 / 1410 | 0 | 1596 | 563 / 531 | 601 / 785 | 0.01202 | 0.646 |
| #28 | + smooth | 6.5 | 3.5 | - | 3551 / 1410 | 0 | - | 563 / 531 | 601 / 785 | 0.01200 | 0.668 |
| #28 | + garment | 6.2 | 1.2 | 1.5 | 3547 / 1404 | 0 | - | 563 / 531 | 601 / 785 | 0.01152 | 0.716 |
| #28 | + hem_c | 2.0 | 3.2 | - | 3585 / 1423 | 2678 | - | 562 / 531 | 601 / 785 | 0.01005 | 0.647 |
| #43 | r12ref | 13.5 | 4.3 | - | 7286 / 3308 | - | - | 1247 / 785 | 730 / 1286 | 0.00200 | 0.283 |
| #43 | reference | 19.6 | 7.2 | - | 3439 / 605 | 0 | 63 | 310 / 462 | 772 / 1293 | 0.02116 | 0.748 |
| #43 | + smooth | 15.1 | 4.2 | - | 3362 / 530 | 0 | - | 310 / 462 | 772 / 1293 | 0.02112 | 0.75 |
| #43 | + garment | 12.2 | 2.3 | 1.5 | 3286 / 456 | 0 | - | 310 / 462 | 772 / 1293 | 0.01982 | 0.753 |
| #43 | + hem_c | 11.4 | 7.6 | - | 3527 / 727 | 4684 | - | 306 / 459 | 772 / 1293 | 0.01633 | 0.761 |
| #40 | r12ref | 16.0 | 6.9 | - | 3862 / 1570 | - | - | 6707 / 6835 | 2347 / 2230 | 0.00290 | 0.277 |
| #40 | reference | 13.1 | 4.5 | - | 1857 / 359 | 0 | 54 | 1057 / 1157 | 2168 / 1957 | 0.00784 | 0.703 |
| #40 | + smooth | 9.8 | 2.5 | - | 1857 / 359 | 0 | - | 1057 / 1157 | 2168 / 1957 | 0.00784 | 0.696 |
| #40 | + garment | 8.4 | 1.8 | 1.5 | 1857 / 359 | 0 | - | 1057 / 1157 | 2168 / 1957 | 0.00763 | 0.717 |
| #40 | + hem_c | 7.0 | 4.5 | - | 1844 / 297 | 4188 | - | 1057 / 1159 | 2145 / 1910 | 0.00766 | 0.686 |

New holes: reference vs r12ref (px cleared beyond the fit tube cuff not counted, listed as beyond cuff px); the hem
columns vs the reference. FAIL runs: 18 / 72, all + hem_c (365-878 px each: the pair lifts the hem centre over the
body). hem_tongue_px per run, r12ref / reference / + smooth / + garment / + hem_c: #28 f-slim 5.5 / 6.0 / 6.5 / 4.6 /
2.0; #43 f-slim 9.5 / 9.5 / 9.5 / 8.2 / 3.0; #43 f-average 10.5 / 10.5 / 10.0 / 10.2 / 3.0; #43 f-plus 10.0 / 10.0 /
10.0 / 10.2 / 3.5; #43 m-plus 13.5 / 19.6 / 15.1 / 12.2 / 11.4; #28 f-plus 5.5 / 5.5 / 5.5 / 5.2 / 0.5 (all 18 in
`table_hem12b.md`). + garment: max stretch 1.5 in 12 / 18 runs (the 2 x largest move band gives at most 1.5), > 1.25 in
14 / 18; clamped columns 0 except #40 m-plus 186.

**#40 tube before / after** (tube_r11 = reference with tube_arm "r11"): cuff out / in px r11 -> fit, arm out / in in
brackets: m-slim L 38.5 / 38.5 -> 25.0 / 38.5 (20.0 / 34.0), R 39.2 / 41.2 -> 25.5 / 41.2; m-plus L 46.7 / 50.6 ->
35.6 / 50.6 (28.5 / 46.0); f-average L 41.6 / 44.0 -> 28.1 / 44.0 (22.5 / 40.0); f-plus L 39.9 / 39.9 -> 38.1 / 49.8
(30.5 / 45.2). Max (out + in) / arm ratio 1.49-1.94 -> 1.16-1.25. Balloon (#40, all avatars) L / R 6791 / 6973 ->
1057 / 1157; arm-band skin 2141 / 1944 -> 2168 / 1957. Cleared beyond the cuff 133-272 px per side on #40.
Runtime: the last guard builds a second layer, reference max 0.75 s (r12ref 0.28 s).

### Tube sleeve finished, round 13 (2026-11-15, NOT production, no winner picked)
Owner 2026-11-15: underarm fix + leftover cuff px; base (all columns) adapt + sleeve C + side_floor_mode "mask" +
hem_mode "garment" (+ collar_floor, neck_hole polygon). Runner `run_tube13.py` (data `data/side12`) ->
`out/table_tube13.md`, `out/results_tube13.json`, `out/sheet_tube13_<id>.png` (per avatar: no tube | tube a+b | tube a,
whole T-shirt 2x, then 3x crops underarm L / cuff L / underarm R / cuff R).

**Method.** Keyword `tube_arm` (default "r11", pixel-identical; keep_shape 0 px on #44 / #45; render_tryon never
passes it): "finished" = the round 12b fit widths (arm extent from `_arm_at` and the march, half-width clamp(ramp,
arm x 1.1, arm x 1.25)), tube OVER the MLS layer; leftover MLS sleeve px cleared only by (a) over the background beyond
the arm + ease, or (b) over the arm (figure px) below the tube's cuff line (cuff-width strip x 1.25); never in the
protected underarm zone (`_underarm_zone`: armhole line, tube inner edge, cuff line; 108-240 px per side) or inward of
the armhole line. "finished_a" = rule (a) only (the gate fallback). Fix 4: the "mask" last guard now builds its
landmark floor layer with the same tube_arm (before: r11 tube, which patched tube-caused losses back).
Metrics: new holes = figure px covered in "no tube" and not in the tube column, all px (enclosed or open), except the
arm below the cuff line (reported as arm below cuff); holes enclosed = uncovered figure px inside the layer's filled
outer contour, sleeve / underarm zone.

| garment | variant | new holes | arm uncovered below cuff | holes enclosed L / R | arm-band skin L / R | cuff wave max L / R | balloon L / R | fold (max) | runtime s (max) |
|---|---|---|---|---|---|---|---|---|---|
| #28 | no tube | - | - | 0 / 0 | 347 / 514 | 5.9 / 29.8 | 757 / 580 | 0.01344 | 0.5 |
| #28 | tube a+b | 805 | 1177 | 52 / 10 | 601 / 785 | 1.7 / 25.3 | 563 / 531 | 0.01152 | 0.8 |
| #28 | tube a | 0 | 0 | 52 / 10 | 190 / 224 | 2.6 / 29.3 | 563 / 531 | 0.01167 | 0.8 |
| #43 | no tube | - | - | 0 / 0 | 2147 / 2532 | 17.3 / 11.4 | 405 / 677 | 0.02281 | 0.5 |
| #43 | tube a+b | 43 | 17 | 27 / 4 | 772 / 1294 | 27.5 / 38.8 | 310 / 462 | 0.01982 | 0.8 |
| #43 | tube a | 0 | 0 | 27 / 4 | 721 / 1283 | 27.5 / 38.8 | 310 / 462 | 0.01985 | 0.8 |
| #40 | no tube | - | - | 0 / 0 | 2218 / 1987 | 10.3 / 10.2 | 1932 / 2644 | 0.00964 | 0.5 |
| #40 | tube a+b | 108 | 17 | 0 / 0 | 2168 / 1956 | 23.5 / 25.4 | 1057 / 1157 | 0.00763 | 0.8 |
| #40 | tube a | 0 | 0 | 0 / 0 | 2130 / 1931 | 23.5 / 25.4 | 1057 / 1157 | 0.00782 | 0.8 |
| all | no tube | - | - | 0 / 0 | 4712 / 5033 | 17.3 / 29.8 | 3094 / 3901 | 0.02281 | 0.5 |
| all | tube a+b | 956 | 1211 | 79 / 14 | 3541 / 4035 | 27.5 / 38.8 | 1930 / 2150 | 0.01982 | 0.8 |
| all | tube a | 0 | 0 | 79 / 14 | 3041 / 3438 | 27.5 / 38.8 | 1930 / 2150 | 0.01985 | 0.8 |

**GATE (tube a+b): 18 / 18 runs fail**, 3-162 px per run (#28 113-162, #43 3-13, #40 10-36), all at the cuff rows
(y 354-404). On #28 m-slim and #40 f-plus the lost px lie 0-2.0 px ABOVE the cuff line (plus 1-5 px below it on #28
left, outside the cuff-width strip): the remove_halo erosion (2 px) of the new cuff edge that rule (b) creates.
Rule (b) cleared 75-518 px per side. **Fallback (tube a): 0 new holes in 18 / 18 runs**, 0 arm px uncovered below the
cuff; the jagged MLS cuff px below the cuff line stay (crops). Holes enclosed: 0 without the tube, 79 / 14 px with
either tube (#28 52 / 10, #43 27 / 4): px open (uncovered) without the tube that the tube closes around (not new
holes). Cuff wave is measured on each layer's own cuff (MLS pairs vs the tube cuff segment): not comparable between
"no tube" and the tubes. "mask" last guard patched 26 px (a+b) / 16 px (a) over the 18 runs.

**Round 13b (owner 2026-11-15: keep a + b, fix the cut edge, fill enclosed holes).** tube_arm "finished" now (1)
keeps the rule (b) cut out of remove_halo (the cut px count as fabric during the erosion, then go back to transparent;
`rep["cut_b"]`), (2) fills enclosed holes (alpha < 128, not reachable from the canvas border) of the FINAL layer
(torso + tube) inside `sleeve_zone` (rule #63; the neck opening is outside the zone), `info["tube"]["filled_px"]`.
Columns no tube | tube a+b fixed (the round 13 three-column run is kept in `out/tube13_a_b_3col/`).

| garment | variant | new holes | arm uncovered below cuff | holes enclosed L / R | arm-band skin L / R | cuff wave max L / R | balloon L / R | fold (max) | runtime s (max) |
|---|---|---|---|---|---|---|---|---|---|
| #28 | no tube | - | - | 0 / 0 | 347 / 514 | 5.9 / 29.8 | 757 / 580 | 0.01344 | 0.6 |
| #28 | tube a+b fixed | 0 | 728 | 0 / 0 | 136 / 203 | 3.9 / 26.6 | 563 / 531 | 0.01276 | 1.0 |
| #43 | no tube | - | - | 0 / 0 | 2147 / 2532 | 17.3 / 11.4 | 405 / 677 | 0.02281 | 0.5 |
| #43 | tube a+b fixed | 0 | 6 | 0 / 0 | 660 / 1272 | 27.5 / 38.8 | 310 / 462 | 0.01990 | 0.9 |
| #40 | no tube | - | - | 0 / 0 | 2218 / 1987 | 10.3 / 10.2 | 1932 / 2644 | 0.00964 | 0.4 |
| #40 | tube a+b fixed | 0 | 14 | 0 / 0 | 2126 / 1923 | 23.5 / 25.4 | 1057 / 1157 | 0.00795 | 0.8 |
| all | no tube | - | - | 0 / 0 | 4712 / 5033 | 17.3 / 29.8 | 3094 / 3901 | 0.02281 | 0.6 |
| all | tube a+b fixed | 0 | 748 | 0 / 0 | 2922 / 3398 | 27.5 / 38.8 | 1930 / 2150 | 0.01990 | 1.0 |

GATE: 0 / 18 runs fail. Filled px per run: #28 m-plus 11, #28 f-plus 52, #43 m-plus 16, #43 f-plus 27, the other 14
runs 0. Rule (b) cleared 75-518 px per side; "mask" last guard patched 61 px over the 18 runs. Runtime per T-shirt
layer: no tube 0.24-0.60 s, tube a+b fixed 0.62-1.00 s.

### Armpit, round 13c (2026-11-15, NOT production, no winner picked)
Owner 2026-11-15: a small open wedge under both armpits between the sleeve's inner end and the torso (#28). Runner
`run_armpit13c.py` -> `out/table_armpit13c.md`, `out/results_armpit13c.json`, `out/sheet_armpit13c_<id>.png` (per avatar:
no tube L | R, tube fixed L | R, 3x armpit crops). Base as round 13 (sleeve C + "mask" + hem "garment").

**Check before the fix (owner condition 2).** #28 m-plus and f-plus, both sides: the side_floor "mask" targets follow
the interpolated torso edge, which runs along the body (the boundary between torso fabric and arm skin in the crops);
torso fabric is not pulled over the arm. The "crossing" seen earlier came from the straight arm fit (`_arm_at`)
extended above the row where the arm separates, which cuts across the torso there. No interpolation change.
Zone first tried as specified (torso edge -> arm inner edge, armpit row -> cuff line): empty in 11 / 18 runs, the
wedge is not in it. The wedge lies in the protected underarm triangle (armhole line, tube inner edge, cuff line), where
the tube was clipped to the outward side of the armhole line: uncovered there (round 13b tube) #28 f-plus 89 / 107,
#43 m-plus 0 / 51, #43 f-plus 46 / 0, #28 m-plus 0 / 12, #28 m-average 7 / 1, other runs 0.

**Method** (tube_arm "finished", keyword armpit_fix default on; keep_shape 0 px on #44 / #45). Zone `armpit_zone` =
that triangle with the tube's inner edge before widening, continued ARMPIT_BELOW_CUFF = 6 px below the cuff line on
the torso side of the inner edge line extended. (1) `_widen_inner`: per cross-section after t = 0 the inner half-width
grows to the torso edge (`torso_side_edges`) + 2 px, weight 1 - smoothstep(t). (2) The tube may draw in the zone.
(3) `_inpaint_armpit`: figure px of the zone still open: cv2.inpaint (Telea, radius 3), alpha 255, zone px only.
armpit_open_px = uncovered figure px in the zone (same zone for every column).

| garment | avatar | armpit open no tube L / R | tube 13b L / R | tube fixed L / R | covered by widening | inpainted |
|---|---|---|---|---|---|---|
| #28 | m-slim | 2 / 0 | 0 / 0 | 0 / 0 | 0 | 0 |
| #28 | m-average | 34 / 29 | 58 / 32 | 0 / 0 | 0 | 90 |
| #28 | m-plus | 5 / 35 | 0 / 13 | 0 / 0 | 12 | 1 |
| #28 | f-plus | 125 / 132 | 94 / 130 | 0 / 0 | 176 | 48 |
| #43 | m-slim | 5 / 14 | 0 / 0 | 0 / 0 | 0 | 0 |
| #43 | m-average | 18 / 0 | 0 / 0 | 0 / 0 | 0 | 0 |
| #43 | m-plus | 14 / 63 | 0 / 51 | 0 / 0 | 34 | 17 |
| #43 | f-average | 4 / 0 | 0 / 0 | 0 / 0 | 0 | 0 |
| #43 | f-plus | 70 / 11 | 47 / 0 | 0 / 0 | 46 | 1 |
| #40 | f-plus | 8 / 0 | 4 / 0 | 0 / 0 | 0 | 4 |
| other 8 runs | | 0 / 0 | 0 / 0 | 0 / 0 | 0 | 0 |

Totals: no tube 285 / 284, tube 13b 203 / 226, tube fixed 0 / 0; covered by widening 268, inpainted 161. GATE (open
<= 5 per side, new holes = 0): 0 / 18 runs fail. Runtime tube fixed 0.60-0.86 s (no tube 0.22-0.47 s).
**Not in the zone, still visible:** #28 m-slim L 366 and f-slim L 110 uncovered figure px (the avatar's grey tank, base
BGR ~140) within 30 px of the inner cuff end, 0-28 px below the cuff line, all on the arm side of the inner edge line
extended (`out/armpit13c_remaining_28_slim.png`). A thin light line along the tube's inner edge over the torso
fabric (`out/armpit13c_zoom_28_slim.png`).

### Armpit wedge, round 14 (2026-11-15, NOT production, no winner picked)
Owner 2026-11-15: the wedge under the armpits is still open after round 13c (white / grey notches, ragged black
fragments); find the root cause from the pixels, a metric that sees it, a geometric fix. Base for every column: adapt +
sleeve C + side_floor_mode "mask" + hem_mode "garment" + tube "finished" (+ collar_floor, neck_hole polygon); data
`data/side12`. Tools: `debug_armpit14.py` (step 1, read-only) -> `out/debug_armpit14_<id>_<avatar>.png`,
`out/table_debug_armpit14.md`, `out/debug_armpit14.json`; `run_armpit14.py` -> `out/table_armpit14.md`,
`out/results_armpit14.json`, `out/sheet_armpit14_<id>.png` (per avatar: current L | R, 13c L | R, fixed L | R, 3x
armpit crops, clean), `out/sheet_armpit14_full_<id>.png` (current | 13c | fixed, whole T-shirt, 3x);
`OVERLAY=1` = wedge px red, px lost vs current yellow (kept in `out/armpit14_overlay/`).

**Root cause (step 1, #28 / #43 / #40 x 6 avatars x 2 sides, `debug_armpit14.py`).**
- The garment splits into sleeve underside and torso side at its own underarm notch (`garment_notch`: the top of the
  transparent gap on the alpha; 3-19 garment px below the marked armpit landmark). The body splits into arm and torso
  at the crease = the first row where the mask separates them. The MLS solve puts the notch 1-74 px ABOVE the crease
  (#28 1-68, #43 21-74, #40 9-56). On the rows between, the body is one silhouette and the garment is already two
  edges with transparent px between them.
- No layer owns those px: the tube ends on its cuff line (2-59 px above the crease in 35 / 36 sides) and is clipped
  outward of the armhole line; below the cuff only the torso side edge could cover, and it sits 2-19 px inside the
  arm/torso boundary (the rounded cove of the notch bows inward between the floor pairs; "mask" floor rows where the
  sleeve is still joined get no pair at all: the run through the axis ends on the sleeve's outer edge; first pair
  14-86 px below the armpit).
- Made worse by: (1) the inner cuff target inside the torso (#28 f-plus R 15.5 px, m-plus R / f-average R 5.5 px:
  the straight arm fit `_arm_at` is extrapolated above the crease); (2) tube rule (b): its strip of the cuff width x
  1.25 reaches torso px beside the arm and clears MLS sleeve px there (#28: 3-68 px per side that "no tube" covered;
  the round 13 "new holes" gate exempted exactly that strip); (3) on f-plus the round 12b blend back to the landmark
  floor map undoes the floor pairs on these rows (#28 f-plus R: 364 px open, 154 without the blend).
- Side floor suspicion (torso fabric pulled over the arm): not confirmed. The interpolated torso edge
  (`torso_side_edges`, linear from the armpit landmark to the crease row) passes -1.5 .. +3 px from the top of the
  background gap on all 36 sides.
- Round 13c: its zone lies above the cuff line, outward of the armhole line; the wedge lies below the cuff on the
  torso side. It changed 0 px on 29 / 36 sides; where it drew (#28 f-plus R: +102 px tube, +45 px inpaint) it filled
  part of the wedge as a blocky patch.
Uncovered torso px between the inner cuff row and the crease, inward from the boundary (per side, no tube / current):
#28 0-364 / 2-364 (widest gap 2-19 px), #43 6-212 / 6-206 (2-8 px), #40 3-176 / 3-175 (2-12 px).

**Metrics** (`mls.armpit_wedge`, `mls.armpit_ragged`; independent of the tube's zones; arm/torso boundary =
`mls.arm_torso_boundary`).
- wedge px per side = open figure px (alpha < 128) (a) on the torso side of the boundary, <= 25 px from it, rows
  armpit landmark -> crease + 2, plus (b) on the arm side, <= 12 px from it, rows armpit -> crease, more than 2 px
  ABOVE the layer's own cuff line (`info["sleeve_hems"]`). Arm skin at / below the cuff line is never counted.
- ragged: fragment px = garment px of the armpit box not connected to the garment's largest piece; spike px =
  garment px of the box removed by an opening with a 5 px ellipse (teeth, 1-4 px slivers; the garment's own wavy
  sleeve hem gives spike px in every column, so it is reported, not gated).
- new holes = figure px the current column covers and the fixed column does not, whole canvas, except arm skin from
  2 px above the current cuff line down (reported as "+ arm": current covers that skin with leftover fabric, fixed
  cuts it on the boundary). arm covered = arm px more than 1 px below the cuff line that fixed covers and current
  does not. neck = px that differ above the armpit row in the inner 40 % between the shoulders.

**Fix** (keyword `mls.tshirt_layer(armpit_mode="off" | "r13c" | "r14")`, default "off", adapt only, keep_shape 0 px
on #44 / #45, `render_tryon` never passes it; it replaces the boolean `armpit_fix`, so tube_arm "finished" without
the keyword is round 13b again; "r13c" = round 13c unchanged, kept only for this comparison, to be deleted after the
owner's review). "r14" (`_add_armpit_pairs`, needs side_floor), per side:
- J = the row where the sleeve's cuff line meets the arm/torso boundary (the crease when the cuff is lower).
- The garment's torso side seam is pinned to the boundary: body rows every `ARMPIT_STEP` = 4 px, from `ARMPIT_LEAD` =
  4 px above J (and above the inner cuff target by the length of the garment's sleeve underside) down to a row >=
  `ARMPIT_RUN` = 24 px lower and never above the crease; garment rows linear from the notch row + 2 to the first
  solve's garment row at the last body row (the fabric's vertical placement is kept there); q = the torso edge of
  the garment alpha on that row, p = the boundary + `ARMPIT_EASE` = 4 px on the arm side (2 px below the crease).
  The garment's corner so lands on the boundary at the cuff row and the seam follows the arm down to the crease.
- Left out of this solve: the "mask" floor pairs on those rows, side pairs out of order with the new ones (#43: the
  chest pair held the seam inside the boundary), and with a tube the sleeve's inner MLS pairs (cuff_in, smid_in: the
  tube draws the sleeve; they only fought the pinned seam). Without a tube the inner cuff target is moved onto the arm
  side of the seam instead (path not benchmarked).
- The solve is used inside a window only (1 within `ARMPIT_KEEP` = 14 px of the new pairs, Gaussian ramp sigma 6 px,
  0 elsewhere): the first version let the pairs act globally (3627 new hole px, neck px changed).
- Tube rules ("finished"): rule (b) works on the arm side of the boundary only; on the arm-touch rows it is no
  longer limited to the cuff strip / the armhole line; torso fabric the ease puts on the arm below the cuff line is
  cut on the boundary (same cut mechanism as rule (b): kept out of remove_halo; also on the separated arm rows).
- Local guard: inside the window a figure px the map without the armpit pairs covers (eroded like remove_halo;
  not eroded on the arm above the cuff line) and the final layer does not is put back from that map; never arm skin
  below the cuff line. Detached garment pieces <= 8 px inside the window are removed. No widening, no inpaint.
Tried and dropped during the round: global pairs (above); q from the first solve's rows only (the junction stayed
open: the notch row landed below J); inner cuff target moved onto the boundary while its pair stayed (#40: the
sleeve underside is horizontal, a 5-8 px knot stayed open at J); the guard without erosion (0 new holes, but 8
fragment px and + 48 spike px).

| garment | avatar | wedge L / R current | 13c | fixed | fragments L / R 13c | fixed | spikes L / R current | 13c | fixed | new holes fixed (+ arm) | arm covered | neck | runtime s current / fixed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| #28 | m-slim | 149 / 33 | 149 / 33 | 0 / 0 | 0 / 0 | 0 / 0 | 12 / 5 | 12 / 5 | 6 / 6 | 0 (+ 0) | 0 | 0 | 0.74 / 0.99 |
| #28 | m-average | 24 / 1 | 6 / 0 | 0 / 0 | 4 / 24 | 0 / 0 | 4 / 0 | 8 / 24 | 0 / 0 | 0 (+ 0) | 0 | 0 | 0.71 / 0.98 |
| #28 | m-plus | 124 / 123 | 124 / 110 | 0 / 0 | 0 / 0 | 0 / 0 | 3 / 4 | 3 / 4 | 2 / 2 | 0 (+ 0) | 0 | 0 | 0.74 / 1.02 |
| #28 | f-slim | 75 / 16 | 75 / 16 | 0 / 0 | 0 / 0 | 0 / 0 | 3 / 1 | 3 / 1 | 3 / 1 | 0 (+ 0) | 0 | 0 | 0.79 / 1.10 |
| #28 | f-average | 104 / 78 | 104 / 78 | 0 / 0 | 0 / 0 | 0 / 0 | 4 / 4 | 4 / 4 | 2 / 2 | 0 (+ 4) | 0 | 0 | 0.78 / 1.13 |
| #28 | f-plus | 412 / 553 | 312 / 398 | 0 / 0 | 0 / 0 | 0 / 0 | 2 / 2 | 2 / 16 | 0 / 2 | 0 (+ 10) | 0 | 0 | 0.83 / 1.14 |
| #43 | m-slim | 122 / 97 | 122 / 97 | 5 / 21 | 0 / 0 | 0 / 0 | 8 / 7 | 8 / 7 | 9 / 12 | 0 (+ 0) | 0 | 0 | 0.74 / 1.03 |
| #43 | m-average | 53 / 88 | 53 / 88 | 7 / 26 | 0 / 0 | 0 / 0 | 4 / 1 | 4 / 1 | 0 / 5 | 0 (+ 0) | 0 | 0 | 0.83 / 1.14 |
| #43 | m-plus | 162 / 230 | 162 / 171 | 7 / 31 | 0 / 0 | 0 / 0 | 4 / 2 | 4 / 2 | 6 / 4 | 0 (+ 0) | 0 | 0 | 0.85 / 1.20 |
| #43 | f-slim | 72 / 93 | 72 / 93 | 7 / 25 | 0 / 0 | 0 / 0 | 7 / 9 | 7 / 9 | 8 / 14 | 0 (+ 3) | 0 | 0 | 0.76 / 1.16 |
| #43 | f-average | 72 / 103 | 72 / 103 | 5 / 23 | 0 / 0 | 0 / 0 | 9 / 5 | 9 / 5 | 9 / 11 | 0 (+ 13) | 0 | 0 | 0.92 / 1.28 |
| #43 | f-plus | 322 / 126 | 263 / 126 | 4 / 13 | 0 / 0 | 0 / 0 | 2 / 5 | 2 / 5 | 3 / 8 | 0 (+ 23) | 0 | 0 | 0.86 / 1.28 |
| #40 | m-slim | 252 / 63 | 252 / 63 | 3 / 3 | 0 / 0 | 0 / 0 | 11 / 5 | 11 / 5 | 14 / 10 | 1 (+ 5) | 0 | 0 | 0.66 / 0.97 |
| #40 | m-average | 129 / 50 | 129 / 50 | 2 / 0 | 0 / 0 | 0 / 0 | 1 / 6 | 1 / 6 | 6 / 4 | 0 (+ 1) | 0 | 0 | 0.63 / 0.86 |
| #40 | m-plus | 225 / 116 | 225 / 116 | 10 / 1 | 0 / 0 | 0 / 0 | 4 / 1 | 4 / 1 | 13 / 4 | 0 (+ 0) | 0 | 0 | 0.77 / 1.08 |
| #40 | f-slim | 204 / 168 | 204 / 168 | 4 / 0 | 0 / 0 | 0 / 0 | 8 / 14 | 8 / 14 | 15 / 11 | 0 (+ 0) | 0 | 0 | 0.79 / 1.09 |
| #40 | f-average | 190 / 70 | 190 / 70 | 1 / 2 | 0 / 0 | 0 / 0 | 6 / 12 | 6 / 12 | 10 / 18 | 0 (+ 27) | 0 | 0 | 0.63 / 0.93 |
| #40 | f-plus | 261 / 67 | 257 / 67 | 0 / 0 | 0 / 0 | 0 / 0 | 3 / 4 | 3 / 4 | 8 / 5 | 0 (+ 35) | 0 | 0 | 0.81 / 1.24 |

Totals (L / R): wedge current 2952 / 2075 (torso side 2527 / 1659, arm above cuff 425 / 416), 13c 2771 / 1847, fixed
55 / 145 (torso side 5 / 0, arm above cuff 50 / 145); fragments current 0 / 0, 13c 4 / 24, fixed 0 / 0; spikes
current 95 / 87, 13c 99 / 125, fixed 114 / 119 (above current on 21 / 36 sides, by 1-9 px). New holes 13c 0; fixed 1
(+ 121 arm skin px at / below the cuff line). Arm covered 0, neck 0 in 18 / 18 runs.
**GATE (fixed: wedge <= 5 per side, fragments 0, new holes 0): 8 / 18 runs fail.**
- #43, 6 runs (wedge R 13-31, L 7 in three runs) and #40 m-plus (wedge L 10): all arm skin above the nominal cuff
  line, 2.5-5.8 px above it, under the garment's own curved / wavy sleeve hem at its inner end (torso side 0-2 px
  in these runs; the same px are open in current: arm part 7-10 / 33-49 on #43). The tube maps the straight chord
  between the cuff landmarks to the cuff line; the garment's hem rises above that chord near the inner end. Not closed
  by this round (a cuff-shape question, not the torso wedge).
- #40 m-slim: 1 new hole px = a detached 1 px sleeve crumb on the arm above the cuff that current keeps; the crumb
  removal takes it.
Runtime per T-shirt layer: current 0.63-0.92 s (mean 0.77), fixed 0.86-1.28 s (mean 1.09): + 0.23-0.43 s (one more
MLS solve in the layer and one in the "mask" last guard's reference layer, the local guard's remap).
**Limits / not done.** (1) `arm_torso_boundary` relies on the touch test of `torso_side_edges` (edge <= 1.3 x the
landmark half-span): with the older landmarks of the r10 test fixture, f-slim left reports no arm-touch rows and r14
skips that side (reported as skipped; with the `data/side12` landmarks all 12 sides have 41-93 rows). (2) r14
without a tube (sleeve_mode "mls") is built but not benchmarked. (3) Spike px on #43 / #40 are higher than current
(the sleeve's thin hem px on the arm are kept by the guard instead of 2-4 lost px). (4) A faint line along the tube's
inner edge is visible on #28 m-slim L in the 3x crop.
Tests: `ArmpitWedgeTests` (default off, unknown mode, finished = 13b again, keep_shape 0 px for r13c / r14, no-op
without side_floor, wedge / fragments / new holes / arm / outside-window identical on #28 x 4 and #40 x 2 avatars,
helpers); `ArmpitFixTests` now passes armpit_mode="r13c". 363 backend tests pass, none skipped.

### Production wiring of the adapt T-shirt config (2026-11-15, docs/09 #105)
`TRYON_WARP` now defaults to `mls`. For an adapt T-shirt `render_tryon` calls `mls.tshirt_layer` with sleeve C +
`side_floor=True, side_floor_mode="mask"` + `sleeve_mode="tube", tube_arm="finished"` + `armpit_mode="r14"` +
`hem_mode="garment"` (`warp._mls_adapt_kwargs`), i.e. the "fixed" column of round 14; keep_shape is called as before.
Settings `TRYON_MLS_TUBE`, `TRYON_MLS_SIDE_FLOOR`, `TRYON_MLS_ARMPIT`, `TRYON_MLS_HEM` (first value = on, second =
the behaviour before): 1 | 0, mask | off, r14 | off, garment | mls. The armpit mode is off whenever the tube or the
side floor is off. Tube skipped on a side (`info["tube"][side]["skipped"]`): the T-shirt is rendered again without
the tube and the armpit mode, quality warning `tube_fallback`. `debug["tshirt_config"]` / job result `tshirt_config`
= the values actually used; job result `render_ms`. Round 13c (`armpit_mode="r13c"`) is deleted; the 13c numbers
above stay as history, `run_armpit14.py` / `debug_armpit14.py` no longer render a 13c column.
Numbers: production layer vs the benchmark call 0 px on #28 / #43 / #40 x 6 avatars; keep_shape #44 / #45 x 6: 0 px
(`tools/tryon_check/prod_vs_bench.py`). `render_tryon` for an adapt T-shirt 1114-1487 ms (mean 1333) called
directly, `render_ms` 922-1095 ms in the worker; keep_shape 97-137 ms; before this change adapt took about 150 ms.
Through `POST tryon/` (`tools/tryon_check/post_path.py`, sheets `tools/tryon_check/out/post_path/sheet_<id>.png`,
before | after): 21 renders, 9 refused by the gender rule; px that differ before vs after: adapt 59656-99511 per
render, keep_shape 0.
**Known issues (owner 2026-11-15, not blockers):** the round 14 gate fails on 8 of 18 runs (#43 cuff slivers, #40
m-plus, 1 px #40 m-slim); render time about 1.1 s per adapt T-shirt layer (to optimize later, likely the "mask" last
guard's comparison layer, which builds a second full layer); a stepped torso edge (2-5 px) beside the gap below the
armpit on #28; r14 skips a side when `torso_side_edges` finds no arm-touch rows (older landmarks).

