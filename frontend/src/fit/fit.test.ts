import { describe, expect, it } from 'vitest'
import type { FitZoneCheck } from '../api/types'
import { fitLines, formatCm, zoneLine } from './fitMessages'
import { changedKeys, validateFitMeasurements, FIT_MEASUREMENT_FIELDS } from './measurementFields'
import { fitNotice, fitWarningBlocks } from './fitNotice'
import { GARMENT_SIZE_FIELDS, parseCm, sizesToValues, validateSizes } from './sizeFields'

const check = (over: Partial<FitZoneCheck>): FitZoneCheck => ({
  zone: 'chest', garment_cm: 94, body_cm: 100, ease_cm: -6, verdict: 'too_small', limit_cm: 100, ...over,
})

describe('size form validation (docs/11 ranges)', () => {
  it('accepts the required keys and every boundary', () => {
    expect(validateSizes('tshirt', { chest_width: '52', length: '70', shoulder_width: '46' })).toEqual({
      sizes: { chest_width: 52, length: 70, shoulder_width: 46 }, errors: {}, ok: true,
    })
    for (const type of ['tshirt', 'pants'] as const) {
      for (const f of GARMENT_SIZE_FIELDS[type]) {
        const base = Object.fromEntries(GARMENT_SIZE_FIELDS[type].filter((x) => x.required)
          .map((x) => [x.key, String(x.min)]))
        for (const v of [f.min, f.max]) expect(validateSizes(type, { ...base, [f.key]: String(v) }).ok).toBe(true)
        for (const v of [f.min - 0.1, f.max + 0.1]) {
          const r = validateSizes(type, { ...base, [f.key]: String(v) })
          expect(r.ok).toBe(false)
          expect(r.errors[f.key]).toContain(`${f.min} dan ${f.max} sm`)
        }
      }
    }
  })

  it('flags missing required, non-numbers; optional may stay empty; comma decimals', () => {
    const r = validateSizes('pants', { waist_width: '', hip_width: 'abc', inseam: '78,5', thigh_width: '' })
    expect(r.ok).toBe(false)
    expect(r.errors.waist_width).toBe('Bel kengligi: kiriting.')
    expect(r.errors.hip_width).toBe('Son kengligi: son kiriting.')
    expect(r.sizes).toEqual({ inseam: 78.5 })
    expect(r.errors.thigh_width).toBeUndefined()
    expect(parseCm(' ')).toBeNull()
  })

  it('ignores keys of the other type and round-trips stored sizes', () => {
    const r = validateSizes('tshirt', { chest_width: '52', length: '70', shoulder_width: '46', inseam: '80' } as never)
    expect(r.sizes).not.toHaveProperty('inseam')
    expect(sizesToValues('tshirt', { chest_width: 52, length: 70, shoulder_width: 46 })).toEqual({
      chest_width: '52', length: '70', shoulder_width: '46', waist_width: '', sleeve_length: '',
    })
    expect(sizesToValues('pants', null).waist_width).toBe('')
  })
})

describe('fit message rendering (same as backend messages.py)', () => {
  it('formats cm with the trailing .0 dropped', () => {
    expect(formatCm(6)).toBe('6')
    expect(formatCm(6.0)).toBe('6')
    expect(formatCm(2.5)).toBe('2.5')
    expect(formatCm(2.04)).toBe('2')
  })

  it('tor / keng, qisqa / uzun, ok zones skipped', () => {
    expect(zoneLine(check({}))).toBe('Bu kiyim sizga mos emas: koʻkrak 6 sm tor.')
    expect(zoneLine(check({ garment_cm: 122.5, limit_cm: 120, verdict: 'too_large' })))
      .toBe('Bu kiyim sizga katta: koʻkrak 2.5 sm keng.')
    expect(zoneLine(check({ zone: 'inseam', garment_cm: 70, limit_cm: 75 })))
      .toBe('Bu kiyim sizga mos emas: uzunlik 5 sm qisqa.')
    expect(zoneLine(check({ zone: 'inseam', garment_cm: 90, limit_cm: 88, verdict: 'too_large' })))
      .toBe('Bu kiyim sizga katta: uzunlik 2 sm uzun.')
    expect(zoneLine(check({ verdict: 'ok', limit_cm: null }))).toBeNull()
  })

  it('several zones: one line each, in check order', () => {
    expect(fitLines([
      check({ zone: 'waist', garment_cm: 60, limit_cm: 76 }),
      check({ zone: 'hip', verdict: 'ok', limit_cm: null }),
      check({ zone: 'inseam', garment_cm: 60, limit_cm: 75 }),
    ])).toEqual([
      'Bu kiyim sizga mos emas: bel 16 sm tor.',
      'Bu kiyim sizga mos emas: uzunlik 15 sm qisqa.',
    ])
  })
})

describe('body sizes validation (measurements page)', () => {
  const full = { height_cm: '175', chest: '100', waist: '80', hip: '100', shoulder_width: '44' }

  it('complete when every required value is valid; inseam optional', () => {
    const r = validateFitMeasurements(full)
    expect(r.complete).toBe(true)
    expect(r.measurements).toEqual({ height_cm: 175, chest: 100, waist: 80, hip: 100, shoulder_width: 44 })
    expect(FIT_MEASUREMENT_FIELDS.find((f) => f.key === 'inseam')?.required).toBe(false)
  })

  it('invalid values are not sent; missing required marks incomplete', () => {
    const r = validateFitMeasurements({ ...full, chest: '20', shoulder_width: '' })
    expect(r.complete).toBe(false)
    expect(r.measurements.chest).toBeUndefined()
    expect(r.errors.chest).toBe('Koʻkrak aylanasi: 70 dan 150 sm gacha boʻlishi kerak.')
    expect(r.errors.shoulder_width).toBe('Yelka kengligi: kiriting.')
    expect(validateFitMeasurements({}, false).errors).toEqual({})
  })

})

describe('which body keys changed (PATCH merges)', () => {
  const stored = { height_cm: 175, measurements: { chest: 98, shoulder_width: 44 } }

  it('only changed values are sent', () => {
    expect(changedKeys(stored, { height_cm: '175', measurements: { chest: '100', shoulder_width: '44' } }))
      .toEqual({ measurements: { chest: 100 } })
    expect(changedKeys(stored, { height_cm: '180', measurements: { chest: '98' } })).toEqual({ height_cm: 180 })
    expect(changedKeys(stored, { height_cm: '175', measurements: { inseam: '80' } }))
      .toEqual({ measurements: { inseam: 80 } })
  })

  it('nothing changed, emptied or invalid fields -> nothing sent', () => {
    expect(changedKeys(stored, { height_cm: '175', measurements: { chest: '98', shoulder_width: '44' } })).toEqual({})
    expect(changedKeys(stored, { height_cm: '', measurements: { chest: '', shoulder_width: 'x' } })).toEqual({})
    expect(changedKeys({ height_cm: null, measurements: null }, { height_cm: '', measurements: {} })).toEqual({})
  })
})

describe('fit notice (red / yellow / none)', () => {
  const small = check({})
  const big = check({ zone: 'shoulder', garment_cm: 54, body_cm: 44, ease_cm: 10, verdict: 'too_large', limit_cm: 50 })
  const ok = check({ zone: 'shoulder', garment_cm: 45, body_cm: 44, ease_cm: 1, verdict: 'ok', limit_cm: null })

  it('too small -> red with the zone lines', () => {
    expect(fitNotice({ fits: false, checks: [small, ok], warnings: [] })).toEqual({
      kind: 'red', lines: ['Bu kiyim sizga mos emas: koʻkrak 6 sm tor.'],
    })
  })

  it('too small + too large -> red with both lines, in check order', () => {
    expect(fitNotice({ fits: false, checks: [small, big], warnings: [big] })).toEqual({
      kind: 'red', lines: ['Bu kiyim sizga mos emas: koʻkrak 6 sm tor.', 'Bu kiyim sizga katta: yelka 4 sm keng.'],
    })
  })

  it('warnings only -> yellow; warnings taken from checks when absent', () => {
    const yellow = { kind: 'yellow', lines: ['Bu kiyim sizga katta: yelka 4 sm keng.'] }
    expect(fitNotice({ fits: true, checks: [ok, big], warnings: [big] })).toEqual(yellow)
    expect(fitNotice({ fits: true, checks: [ok, big] })).toEqual(yellow)
  })

  it('fits without warnings -> none', () => {
    expect(fitNotice({ fits: true, checks: [ok], warnings: [] })).toEqual({ kind: 'none', lines: [] })
    expect(fitNotice({ fits: true, checks: [] })).toEqual({ kind: 'none', lines: [] })
  })
})

describe('job result fit_warnings -> yellow blocks', () => {
  const big = check({ zone: 'hip', garment_cm: 130, body_cm: 100, ease_cm: 30, verdict: 'too_large', limit_cm: 120 })
  const names = (id: number) => (id === 7 ? 'Koʻk shim' : `#${id}`)

  it('one garment: no title; several: the garment name', () => {
    const result = { fit_warnings: [{ garment_id: 7, checks: [big], detail: 'x' }] }
    expect(fitWarningBlocks(result, 1, names)).toEqual([
      { garmentId: 7, title: null, lines: ['Bu kiyim sizga katta: son 10 sm keng.'] },
    ])
    expect(fitWarningBlocks(result, 2, names)[0].title).toBe('Koʻk shim')
  })

  it('missing / empty / malformed -> nothing; detail used when checks are missing', () => {
    expect(fitWarningBlocks(null, 1, names)).toEqual([])
    expect(fitWarningBlocks({}, 1, names)).toEqual([])
    expect(fitWarningBlocks({ fit_warnings: [] }, 1, names)).toEqual([])
    expect(fitWarningBlocks({ fit_warnings: 'x' }, 1, names)).toEqual([])
    expect(fitWarningBlocks({ fit_warnings: [null, { checks: [big] }, { garment_id: 3, checks: [] }] }, 1, names))
      .toEqual([])
    expect(fitWarningBlocks({ fit_warnings: [{ garment_id: 3, detail: 'A\nB' }] }, 1, names))
      .toEqual([{ garmentId: 3, title: null, lines: ['A', 'B'] }])
  })
})
