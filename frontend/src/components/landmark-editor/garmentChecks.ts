import type { GarmentType } from '../../api/types'
import { CHECK_MESSAGES, CHECK_WARNINGS, GARMENT_GROUP_NAMES } from '../../locale/uz'
import { getPath } from './geometry'

/**
 * Client copy of the T-shirt sanity checks in backend apps/garments/landmark_checks.py (same rules, same
 * messages). The server stays the authority; this lets the editor show a problem before Save.
 * errors block Save (order violations); warnings do not (ranges).
 */

export interface CheckResult { errors: string[]; warnings: string[] }
/** Visible pixels of the garment PNG (alpha > 0), inclusive. */
export interface BBox { x0: number; y0: number; x1: number; y1: number }

export const COLLAR_NEAR_SHOULDER = 0.15
export const BBOX_TOLERANCE = 2

const N = GARMENT_GROUP_NAMES.tshirt
type TGroup = keyof typeof N

const has = (lm: unknown, g: string) =>
  getPath(lm, `${g}.y`) !== undefined || getPath(lm, `${g}.x`) !== undefined || getPath(lm, `${g}.left.x`) !== undefined

export function checkGarment(type: GarmentType, lm: unknown, bbox?: BBox | null): CheckResult {
  return type === 'tshirt' ? checkTshirt(lm, bbox) : { errors: [], warnings: bboxWarnings(lm, bbox, 'pants') }
}

export function checkTshirt(lm: unknown, bbox?: BBox | null): CheckResult {
  const errors: string[] = []
  const v = (path: string) => getPath(lm, path) ?? NaN
  const lt = (a: string, b: string, msg: string) => { if (!(v(a) < v(b))) errors.push(msg) }

  for (const g of ['shoulder', 'armpit', 'chest', 'waist', 'hem', 'collar'] as TGroup[]) {
    if (has(lm, g)) lt(`${g}.left_x`, `${g}.right_x`, CHECK_MESSAGES.x_order(N[g]))
  }
  lt('shoulder.y', 'chest.y', CHECK_MESSAGES.y_order(N.chest, N.shoulder))
  lt('chest.y', 'waist.y', CHECK_MESSAGES.y_order(N.waist, N.chest))
  lt('waist.y', 'hem.y', CHECK_MESSAGES.y_order(N.hem, N.waist))
  if (has(lm, 'armpit')) {
    lt('shoulder.y', 'armpit.y', CHECK_MESSAGES.y_order(N.armpit, N.shoulder)) // no armpit <= chest rule (docs/09 #94)
  }
  if (has(lm, 'collar_bottom') && has(lm, 'collar')) {
    lt('collar.y', 'collar_bottom.y', CHECK_MESSAGES.y_order(N.collar_bottom, N.collar))
    lt('collar.left_x', 'collar_bottom.x', CHECK_MESSAGES.center(N.collar_bottom))
    lt('collar_bottom.x', 'collar.right_x', CHECK_MESSAGES.center(N.collar_bottom))
  }
  if (has(lm, 'sleeve_cuff_outer') && has(lm, 'sleeve_cuff_inner')) {
    const cx = (v('shoulder.left_x') + v('shoulder.right_x')) / 2
    for (const g of ['sleeve_cuff_outer', 'sleeve_cuff_inner'] as TGroup[]) {
      if (!(v(`${g}.left.x`) < cx && cx < v(`${g}.right.x`))) errors.push(CHECK_MESSAGES.cuff_side(N[g]))
      for (const side of ['left', 'right']) lt('shoulder.y', `${g}.${side}.y`, CHECK_MESSAGES.y_order(N[g], N.shoulder))
    }
    // the axis shoulder -> cuff midpoint separates the corners: the outer one lies away from the torso centre
    for (const side of ['left', 'right']) {
      const sx = v(`shoulder.${side}_x`), sy = v('shoulder.y')
      const mx = (v(`sleeve_cuff_outer.${side}.x`) + v(`sleeve_cuff_inner.${side}.x`)) / 2
      const my = (v(`sleeve_cuff_outer.${side}.y`) + v(`sleeve_cuff_inner.${side}.y`)) / 2
      const cross = (px: number, py: number) => (mx - sx) * (py - sy) - (my - sy) * (px - sx)
      if (!(cross(cx, v('chest.y')) * cross(v(`sleeve_cuff_outer.${side}.x`), v(`sleeve_cuff_outer.${side}.y`)) < 0)) {
        errors.push(CHECK_MESSAGES.cuff_order(N.sleeve_cuff_outer))
        break
      }
    }
  }
  const warnings: string[] = []
  if (has(lm, 'collar')) {
    const span = v('shoulder.right_x') - v('shoulder.left_x')
    if (Math.abs(v('collar.y') - v('shoulder.y')) > COLLAR_NEAR_SHOULDER * span) warnings.push(CHECK_WARNINGS.collar_far(N.collar))
  }
  return { errors: [...new Set(errors)], warnings: [...warnings, ...bboxWarnings(lm, bbox, 'tshirt')] }
}

/** One warning per group with a value outside the garment's visible bounding box (+ tolerance). */
function bboxWarnings(lm: unknown, bbox: BBox | null | undefined, type: GarmentType): string[] {
  if (!bbox || !lm || typeof lm !== 'object') return []
  const names = GARMENT_GROUP_NAMES[type] as Record<string, string>
  const out: string[] = []
  const walk = (obj: unknown, path: string, group: string): boolean => {
    if (typeof obj === 'number') {
      const leaf = path.split('.').pop() ?? ''
      if (!['x', 'y', 'left_x', 'right_x', 'center_x'].includes(leaf)) return false // extra keys (e.g. width)
      const isX = leaf.endsWith('x')
      const lo = (isX ? bbox.x0 : bbox.y0) - BBOX_TOLERANCE, hi = (isX ? bbox.x1 : bbox.y1) + BBOX_TOLERANCE
      return obj < lo || obj > hi
    }
    if (!obj || typeof obj !== 'object') return false
    return Object.entries(obj as Record<string, unknown>).some(([k, val]) => walk(val, `${path}.${k}`, group))
  }
  for (const [group, val] of Object.entries(lm as Record<string, unknown>)) {
    if (names[group] && walk(val, group, group)) out.push(CHECK_WARNINGS.outside_garment(names[group]))
  }
  return out
}

/** Names of the T-shirt groups a record still lacks (for the "add the missing points" banner). */
export function missingTshirtGroups(lm: unknown): string[] {
  const need: TGroup[] = ['collar', 'collar_bottom', 'armpit', 'sleeve_cuff_outer', 'sleeve_cuff_inner']
  return need.filter((g) => !has(lm, g)).map((g) => N[g])
}
