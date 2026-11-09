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
