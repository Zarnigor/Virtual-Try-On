/** Fit-check lines, same wording and rounding as backend apps/sizing/messages.py (docs/11). */
import type { FitZoneCheck } from '../api/types'
import { FIT_ZONE_NAMES } from '../locale/uz'

/** 1 decimal, trailing .0 dropped: 6 -> "6", 2.5 -> "2.5". */
export function formatCm(value: number): string {
  const text = (Math.round(value * 10) / 10).toFixed(1)
  return text.endsWith('.0') ? text.slice(0, -2) : text
}

/** "Bu kiyim sizga mos emas: koʻkrak 6 sm tor." for a failing zone; null when the zone is ok. */
export function zoneLine(c: FitZoneCheck): string | null {
  if (c.verdict === 'ok' || c.limit_cm == null) return null
  const [small, large] = c.zone === 'inseam' ? ['qisqa', 'uzun'] : ['tor', 'keng']
  const word = c.verdict === 'too_small' ? small : large
  const n = formatCm(Math.abs(c.garment_cm - c.limit_cm))
  return `Bu kiyim sizga mos emas: ${FIT_ZONE_NAMES[c.zone]} ${n} sm ${word}.`
}

/** One line per failing zone, in the backend's zone order (the order of `checks`). */
export function fitLines(checks: FitZoneCheck[]): string[] {
  return checks.map(zoneLine).filter((l): l is string => l !== null)
}
