import { describe, expect, it } from 'vitest'
import { CONFIRM_FIELDS, confirmSizes, shoulderWidthCm } from './bodySizes'

const LM = { head_top: { y: 50 }, foot_bottom: { y: 1150 }, shoulder: { y: 260, left_x: 170, right_x: 430 } }

describe('shoulder width estimate (same rule as backend body_sizes.py)', () => {
  it('px width x height / figure px, 1 decimal', () => {
    expect(shoulderWidthCm(LM, 176)).toBe(41.6)  // the backend test's numbers
    expect(shoulderWidthCm({ ...LM, shoulder: { width: 220 } }, 165)).toBe(33)
  })

  it('null without the data', () => {
    expect(shoulderWidthCm(LM, null)).toBeNull()
    expect(shoulderWidthCm(LM, 0)).toBeNull()
    expect(shoulderWidthCm({ shoulder: LM.shoulder }, 170)).toBeNull()
    expect(shoulderWidthCm({ ...LM, foot_bottom: { y: 40 } }, 170)).toBeNull()
    expect(shoulderWidthCm(null, 170)).toBeNull()
  })
})

describe('confirm sizes (docs/09 #130)', () => {
  const full = { height_cm: '178', chest: '100', waist: '86', hip: '100', shoulder_width: '40.4' }

  it('required: height, chest, waist, hip; optional: shoulder width, inseam', () => {
    expect(CONFIRM_FIELDS.filter((f) => f.required).map((f) => f.key)).toEqual(['height_cm', 'chest', 'waist', 'hip'])
    const r = confirmSizes({}, false)
    expect(r.ok).toBe(false)
    expect(Object.keys(r.errors).sort()).toEqual(['chest', 'height_cm', 'hip', 'waist'])
    expect(r.errors.chest).toBe('Koʻkrak aylanasi: kiriting.')
  })

  it('untouched estimate is NOT sent (the backend computes it); a typed value is', () => {
    expect(confirmSizes(full, false)).toEqual({
      request: { height_cm: 178, measurements: { chest: 100, waist: 86, hip: 100 } }, errors: {}, ok: true,
    })
    expect(confirmSizes({ ...full, inseam: '81' }, true).request).toEqual({
      height_cm: 178, measurements: { chest: 100, waist: 86, hip: 100, shoulder_width: 40.4, inseam: 81 },
    })
  })

  it('ranges and non-numbers are errors', () => {
    const r = confirmSizes({ ...full, hip: '20', waist: 'x', shoulder_width: '90' }, true)
    expect(r.ok).toBe(false)
    expect(r.errors.hip).toBe('Son aylanasi: 75 dan 160 sm gacha boʻlishi kerak.')
    expect(r.errors.waist).toBe('Bel aylanasi: son kiriting.')
    expect(r.errors.shoulder_width).toContain('30 dan 60 sm')
    expect(confirmSizes({ ...full, shoulder_width: '90' }, false).ok).toBe(true)  // untouched: never checked
  })
})
