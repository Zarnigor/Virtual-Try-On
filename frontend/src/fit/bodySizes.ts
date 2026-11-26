/** Body confirm sizes (docs/09 #130). Pure helpers; the backend checks again and its message wins. */
import type { BodyConfirmRequest, Measurements } from '../api/types'
import { BODY_SIZE_LABELS, FIT_TEXT } from '../locale/uz'
import { FIT_MEASUREMENT_FIELDS, validateFitMeasurements, type MeasurementValues } from './measurementFields'

/** Required at POST body/confirm/; inseam optional, shoulder_width computed by the backend when not sent. */
export const CONFIRM_REQUIRED = ['height_cm', 'chest', 'waist', 'hip'] as const

/** The confirm form fields in display order (ranges from FIT_MEASUREMENT_FIELDS). */
export const CONFIRM_FIELDS = FIT_MEASUREMENT_FIELDS.map((f) => ({
  ...f, required: (CONFIRM_REQUIRED as readonly string[]).includes(f.key),
}))

type Line = { y?: unknown; left_x?: unknown; right_x?: unknown; width?: unknown }

const num = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/** Same rule as backend apps/sizing/body_sizes.py shoulder_width_cm (docs/09 #76, #129):
 *  shoulder px width x height_cm / (foot_bottom.y - head_top.y), 1 decimal; null when it cannot be computed. */
export function shoulderWidthCm(landmarks: unknown, heightCm: number | null): number | null {
  if (!landmarks || typeof landmarks !== 'object' || !num(heightCm) || heightCm <= 0) return null
  const lm = landmarks as Record<string, Line | undefined>
  const s = lm.shoulder
  const px = s && num(s.left_x) && num(s.right_x) ? s.right_x - s.left_x : s && num(s.width) ? s.width : null
  const top = lm.head_top?.y
  const foot = lm.foot_bottom?.y
  if (px === null || px <= 0 || !num(top) || !num(foot) || foot - top <= 0) return null
  return Math.round((px * heightCm / (foot - top)) * 10) / 10
}

export interface ConfirmSizesResult {
  /** The request part of POST body/confirm/ (only valid values). */
  request: Pick<BodyConfirmRequest, 'height_cm' | 'measurements'>
  errors: MeasurementValidationErrors
  ok: boolean
}

type MeasurementValidationErrors = Partial<Record<keyof MeasurementValues, string>>

/** `shoulderTouched` false = the user kept the estimate: shoulder_width is NOT sent, so the backend computes it from
 *  the confirmed landmarks and marks it estimated (docs/09 #130). */
export function confirmSizes(values: MeasurementValues, shoulderTouched: boolean): ConfirmSizesResult {
  const { measurements, errors } = validateFitMeasurements(
    shoulderTouched ? values : { ...values, shoulder_width: '' }, false)
  for (const key of CONFIRM_REQUIRED) {
    if (measurements[key] === undefined && !errors[key]) errors[key] = FIT_TEXT.required(BODY_SIZE_LABELS[key])
  }
  const { height_cm: height, ...rest } = measurements
  const m: Measurements = rest
  return {
    request: { height_cm: height ?? null, measurements: m },
    errors,
    ok: Object.keys(errors).length === 0,
  }
}
