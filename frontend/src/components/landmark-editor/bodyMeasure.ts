/**
 * Pure px -> cm helpers for the staff avatar editor (no React). Unit-tested in bodyMeasure.test.ts.
 *
 * width_cm = (right_x - left_x) * height_cm / (foot_bottom.y - head_top.y)
 * Circumference ESTIMATE: the body section is taken as an ellipse whose depth = 0.6 x width (front view only
 * shows the width), perimeter by Ramanujan's approximation. Labelled "taxmin" in the UI; staff may edit it.
 */

export const DEPTH_RATIO = 0.6
export const CIRCUMFERENCE_LINES = ['shoulder', 'chest', 'waist', 'hip'] as const
export type CircumferenceLine = (typeof CIRCUMFERENCE_LINES)[number]

type Json = Record<string, unknown>

const num = (v: unknown): number | undefined => (typeof v === 'number' && Number.isFinite(v) ? v : undefined)
const at = (lm: unknown, ...path: string[]): number | undefined => {
  let cur: unknown = lm
  for (const k of path) {
    if (cur == null || typeof cur !== 'object') return undefined
    cur = (cur as Json)[k]
  }
  return num(cur)
}

/** Figure height in image px (foot_bottom.y - head_top.y), or undefined if it is not positive. */
export function figurePx(lm: unknown): number | undefined {
  const top = at(lm, 'head_top', 'y'), bottom = at(lm, 'foot_bottom', 'y')
  if (top === undefined || bottom === undefined || bottom <= top) return undefined
  return bottom - top
}

/** Width in cm of a span ([line] or [line, leg]) for a person of heightCm. */
export function widthCm(lm: unknown, heightCm: number, ...path: string[]): number | undefined {
  const fig = figurePx(lm)
  const l = at(lm, ...path, 'left_x'), r = at(lm, ...path, 'right_x')
  if (!fig || !(heightCm > 0) || l === undefined || r === undefined) return undefined
  return ((r - l) * heightCm) / fig
}

/** Perimeter of an ellipse with full width w and full depth d (Ramanujan I). */
export function ellipsePerimeter(w: number, d: number): number {
  const a = w / 2, b = d / 2
  return Math.PI * (3 * (a + b) - Math.sqrt((3 * a + b) * (a + 3 * b)))
}

/** Circumference estimate (cm) from a front width (cm): ellipse with depth = DEPTH_RATIO x width. */
export const circumferenceFromWidth = (wCm: number, depthRatio = DEPTH_RATIO) => ellipsePerimeter(wCm, wCm * depthRatio)

const round = (v: number, step = 0.5) => Math.round(v / step) * step

/** Estimated shoulder / chest / waist / hip circumferences in cm (rounded to 0.5), only lines that can be measured. */
export function estimateCircumferences(lm: unknown, heightCm: number): Partial<Record<CircumferenceLine, number>> {
  const out: Partial<Record<CircumferenceLine, number>> = {}
  for (const line of CIRCUMFERENCE_LINES) {
    const w = widthCm(lm, heightCm, line)
    if (w !== undefined && w > 0) out[line] = round(circumferenceFromWidth(w))
  }
  return out
}

/** Rows for the width table: label path -> cm (rounded to 0.1). */
export const WIDTH_ROWS: { label: string; path: string[] }[] = [
  { label: 'Boʻyin', path: ['neck'] },
  { label: 'Yelka', path: ['shoulder'] },
  { label: 'Qoʻltiq', path: ['armpit'] },
  { label: 'Koʻkrak', path: ['chest'] },
  { label: 'Bel', path: ['waist'] },
  { label: 'Son', path: ['hip'] },
  { label: 'Tizza (sol)', path: ['knee', 'left_leg'] },
  { label: 'Tizza (oʻng)', path: ['knee', 'right_leg'] },
  { label: 'Toʻpiq (sol)', path: ['ankle', 'left_leg'] },
  { label: 'Toʻpiq (oʻng)', path: ['ankle', 'right_leg'] },
]
