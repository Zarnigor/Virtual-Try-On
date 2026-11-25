/** Garment real-size fields (flat-lay cm, docs/11). Ranges mirror backend apps/garments/size_checks.py: UX only,
 *  the backend checks again and its SIZES_INVALID message wins. */
import type { GarmentSizes, GarmentType } from '../api/types'
import { FIT_TEXT, GARMENT_SIZE_LABELS } from '../locale/uz'

export type GarmentSizeKey = keyof GarmentSizes

export interface SizeField {
  key: GarmentSizeKey
  required: boolean
  min: number
  max: number
}

export const GARMENT_SIZE_FIELDS: Record<GarmentType, SizeField[]> = {
  tshirt: [
    { key: 'chest_width', required: true, min: 30, max: 90 },
    { key: 'length', required: true, min: 40, max: 100 },
    { key: 'shoulder_width', required: true, min: 30, max: 70 },
    { key: 'waist_width', required: false, min: 20, max: 90 },
    { key: 'sleeve_length', required: false, min: 5, max: 40 },
  ],
  pants: [
    { key: 'waist_width', required: true, min: 20, max: 90 },
    { key: 'hip_width', required: true, min: 30, max: 90 },
    { key: 'inseam', required: true, min: 40, max: 100 },
    { key: 'thigh_width', required: false, min: 15, max: 50 },
    { key: 'leg_opening', required: false, min: 8, max: 40 },
  ],
}

/** Form values are the raw input strings; '' = not entered. */
export type SizeValues = Partial<Record<GarmentSizeKey, string>>

export interface SizeValidation {
  sizes: GarmentSizes
  errors: Partial<Record<GarmentSizeKey, string>>
  ok: boolean
}

/** Parse a cm input: '' -> null, '52,5' is accepted as 52.5, anything not finite -> NaN. */
export function parseCm(raw: string | undefined): number | null {
  const text = (raw ?? '').trim().replace(',', '.')
  if (text === '') return null
  const n = Number(text)
  return Number.isFinite(n) ? n : NaN
}

export function validateSizes(type: GarmentType, values: SizeValues): SizeValidation {
  const sizes: GarmentSizes = {}
  const errors: SizeValidation['errors'] = {}
  for (const f of GARMENT_SIZE_FIELDS[type]) {
    const n = parseCm(values[f.key])
    const label = GARMENT_SIZE_LABELS[f.key]
    if (n === null) {
      if (f.required) errors[f.key] = FIT_TEXT.required(label)
    } else if (Number.isNaN(n)) {
      errors[f.key] = FIT_TEXT.notNumber(label)
    } else if (n < f.min || n > f.max) {
      errors[f.key] = FIT_TEXT.range(label, f.min, f.max)
    } else {
      sizes[f.key] = n
    }
  }
  return { sizes, errors, ok: Object.keys(errors).length === 0 }
}

/** Stored sizes -> form values (only this type's keys). */
export function sizesToValues(type: GarmentType, sizes: GarmentSizes | null | undefined): SizeValues {
  const out: SizeValues = {}
  for (const f of GARMENT_SIZE_FIELDS[type]) {
    const v = sizes?.[f.key]
    out[f.key] = v != null ? String(v) : ''
  }
  return out
}
