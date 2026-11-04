import { describe, it, expect } from 'vitest';
import { computeFit, itemTransform } from './fit.js';
import { BASE, REGION } from '../config/body.js';

const baseF = BASE.female;
const baseM = BASE.male;
const regionF = REGION.female;
const regionM = REGION.male;

describe('computeFit – female base', () => {
  it('returns ~1.0 scales at female BASE values', () => {
    const fit = computeFit({ height: 165, weight: 60, shoulder: 38, chest: 88, waist: 68, hip: 95 }, baseF);
    expect(fit.torsoScaleX).toBeCloseTo(1.0, 1);
    expect(fit.legsScaleX).toBeCloseTo(1.0, 1);
    expect(fit.scaleY).toBeCloseTo(1.0, 2);
  });

  it('clamps torsoScaleX to max 1.25', () => {
    const fit = computeFit({ height: 165, weight: 100, shoulder: 50, chest: 150, waist: 110, hip: 130 }, baseF);
    expect(fit.torsoScaleX).toBeLessThanOrEqual(1.25);
    expect(fit.legsScaleX).toBeLessThanOrEqual(1.25);
  });

  it('clamps to min 0.85 for small measurements', () => {
    const fit = computeFit({ height: 165, weight: 38, shoulder: 28, chest: 60, waist: 50, hip: 65 }, baseF);
    expect(fit.torsoScaleX).toBeGreaterThanOrEqual(0.85);
    expect(fit.legsScaleX).toBeGreaterThanOrEqual(0.85);
  });

  it('scaleY stays within 0.9–1.15', () => {
    const short = computeFit({ height: 140, weight: 55, shoulder: 36, chest: 84, waist: 64, hip: 90 }, baseF);
    const tall  = computeFit({ height: 195, weight: 70, shoulder: 42, chest: 94, waist: 74, hip: 100 }, baseF);
    expect(short.scaleY).toBeGreaterThanOrEqual(0.9);
    expect(tall.scaleY).toBeLessThanOrEqual(1.15);
  });
});

describe('computeFit – male base', () => {
  it('returns reasonable scales at male BASE values', () => {
    // Male BASE BMI ≈ 23.7, so fullness ≈ 1.077 — scales will be slightly above 1
    const fit = computeFit({ height: 178, weight: 75, shoulder: 46, chest: 100, waist: 85, hip: 98 }, baseM);
    expect(fit.torsoScaleX).toBeGreaterThanOrEqual(0.95);
    expect(fit.torsoScaleX).toBeLessThanOrEqual(1.15);
    expect(fit.legsScaleX).toBeGreaterThanOrEqual(0.95);
    expect(fit.legsScaleX).toBeLessThanOrEqual(1.15);
    expect(fit.scaleY).toBeCloseTo(1.0, 2);
  });

  it('clamps torsoScaleX to max 1.25 for large male chest', () => {
    const fit = computeFit({ height: 178, weight: 120, shoulder: 56, chest: 160, waist: 120, hip: 130 }, baseM);
    expect(fit.torsoScaleX).toBeLessThanOrEqual(1.25);
  });

  it('scaleY stays within 0.9–1.15', () => {
    const short = computeFit({ height: 155, weight: 65, shoulder: 42, chest: 94, waist: 78, hip: 92 }, baseM);
    const tall  = computeFit({ height: 205, weight: 90, shoulder: 50, chest: 110, waist: 92, hip: 106 }, baseM);
    expect(short.scaleY).toBeGreaterThanOrEqual(0.9);
    expect(tall.scaleY).toBeLessThanOrEqual(1.15);
  });
});

describe('itemTransform', () => {
  it('returns a transform string for female torso region', () => {
    const fit = computeFit({ height: 165, weight: 60, shoulder: 38, chest: 88, waist: 68, hip: 95 }, baseF);
    const t = itemTransform('torso', fit, regionF);
    expect(typeof t).toBe('string');
    expect(t).toContain('translate');
    expect(t).toContain('scale');
  });

  it('returns a transform string for male legs region', () => {
    const fit = computeFit({ height: 178, weight: 75, shoulder: 46, chest: 100, waist: 85, hip: 98 }, baseM);
    const t = itemTransform('legs', fit, regionM);
    expect(t.length).toBeGreaterThan(0);
  });

  it('returns empty string for unknown region', () => {
    const fit = computeFit({ height: 165, weight: 60, shoulder: 38, chest: 88, waist: 68, hip: 95 }, baseF);
    expect(itemTransform('shoes', fit, regionF)).toBe('');
  });
});
