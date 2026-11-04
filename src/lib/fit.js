function clamp(val, min, max) {
  return Math.min(Math.max(val, min), max);
}

export function computeFit({ height, weight, shoulder, chest, waist, hip }, base) {
  const bmi = weight / Math.pow(height / 100, 2);
  const fullness = clamp(bmi / 22, 0.8, 1.4);

  const torsoScaleX = clamp(fullness * chest / base.chest, 0.85, 1.25);
  const legsScaleX  = clamp(fullness * hip   / base.hip,   0.85, 1.25);
  const scaleY      = clamp(height / base.height,           0.9,  1.15);
  const shoulderScale = clamp(shoulder / base.shoulder,     0.85, 1.25);

  return { torsoScaleX, legsScaleX, scaleY, shoulderScale, bmi, fullness };
}

export function itemTransform(region, fit, regionGeom) {
  const r = regionGeom[region];
  if (!r) return '';
  const sx = region === 'torso' ? fit.torsoScaleX : fit.legsScaleX;
  const sy = fit.scaleY;
  const { cx, top } = r;
  return `translate(${cx},${top}) scale(${sx},${sy}) translate(${-cx},${-top})`;
}
