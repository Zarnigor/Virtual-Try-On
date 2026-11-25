/** The person's sizes (cm, docs/11 "Body sizes"). Ranges mirror backend apps/sizing/measurements.py: UX only. */
import type { FitMeasurements, Measurements } from '../api/types'
import { BODY_SIZE_LABELS, FIT_TEXT } from '../locale/uz'
import { parseCm } from './sizeFields'

export type FitKey = keyof FitMeasurements

export interface MeasurementField {
  key: FitKey
  required: boolean
  min: number
  max: number
}

/** Avatar path "Your sizes" form: required as docs/11 lists them; inseam optional (estimated from height). */
export const FIT_MEASUREMENT_FIELDS: MeasurementField[] = [
  { key: 'height_cm', required: true, min: 140, max: 210 },
  { key: 'chest', required: true, min: 70, max: 150 },
  { key: 'waist', required: true, min: 55, max: 150 },
  { key: 'hip', required: true, min: 75, max: 160 },
  { key: 'shoulder_width', required: true, min: 30, max: 60 },
  { key: 'inseam', required: false, min: 55, max: 100 },
]

export type MeasurementValues = Partial<Record<FitKey, string>>

export interface MeasurementValidation {
  measurements: FitMeasurements
  errors: Partial<Record<FitKey, string>>
  /** Every required field is filled and valid. */
  complete: boolean
}

/** Only valid values go into `measurements` (an invalid one would make the backend answer 400). */
export function validateFitMeasurements(values: MeasurementValues, requireAll = true): MeasurementValidation {
  const measurements: FitMeasurements = {}
  const errors: MeasurementValidation['errors'] = {}
  let complete = true
  for (const f of FIT_MEASUREMENT_FIELDS) {
    const n = parseCm(values[f.key])
    const label = BODY_SIZE_LABELS[f.key]
    if (n === null) {
      if (f.required) complete = false
      if (f.required && requireAll) errors[f.key] = FIT_TEXT.required(label)
    } else if (Number.isNaN(n)) {
      errors[f.key] = FIT_TEXT.notNumber(label)
      complete = false
    } else if (n < f.min || n > f.max) {
      errors[f.key] = FIT_TEXT.range(label, f.min, f.max)
      complete = false
    } else {
      measurements[f.key] = n
    }
  }
  return { measurements, errors, complete }
}

/** Body measurements page: which values actually changed. PATCH body/measurements/ merges (docs/09 #127), so only
 *  these are sent. An emptied field is NOT a change (null is rejected, nothing can be removed). */
export function changedKeys(
  stored: { height_cm: number | null; measurements: Measurements | null },
  edited: { height_cm: string; measurements: Partial<Record<keyof Measurements, string>> },
): { height_cm?: number; measurements?: Measurements } {
  const out: { height_cm?: number; measurements?: Measurements } = {}
  const h = parseCm(edited.height_cm)
  if (h !== null && !Number.isNaN(h) && h !== stored.height_cm) out.height_cm = h
  const m: Measurements = {}
  for (const [key, raw] of Object.entries(edited.measurements) as Array<[keyof Measurements, string]>) {
    const n = parseCm(raw)
    if (n !== null && !Number.isNaN(n) && n !== (stored.measurements?.[key] ?? null)) m[key] = n
  }
  if (Object.keys(m).length > 0) out.measurements = m
  return out
}

const SESSION_KEY = 'tryon.fitSizes'

/** sessionStorage can be missing or throw (private mode, quota): every access is wrapped. */
export function loadSessionSizes(storage: Storage | undefined = safeSession()): MeasurementValues {
  try {
    const raw = storage?.getItem(SESSION_KEY)
    if (!raw) return {}
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return {}
    const out: MeasurementValues = {}
    for (const f of FIT_MEASUREMENT_FIELDS) {
      const v = (parsed as Record<string, unknown>)[f.key]
      if (typeof v === 'string') out[f.key] = v
    }
    return out
  } catch {
    return {}
  }
}

export function saveSessionSizes(values: MeasurementValues, storage: Storage | undefined = safeSession()): void {
  try {
    storage?.setItem(SESSION_KEY, JSON.stringify(values))
  } catch {
    // ignore: the sizes then only live in the page state
  }
}

function safeSession(): Storage | undefined {
  try {
    return typeof window !== 'undefined' ? window.sessionStorage : undefined
  } catch {
    return undefined
  }
}
