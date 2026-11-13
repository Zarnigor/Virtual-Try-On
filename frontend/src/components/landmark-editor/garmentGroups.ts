import type { GarmentType } from '../../api/types'
import { GARMENT_GROUP_NAMES, SIDE } from '../../locale/uz'
import { MIN_GAP, type GroupDef, type PointDef, type Rules, type XRule, type YRule } from './geometry'

/**
 * Landmark groups per garment type (names fixed by docs/03). Point ids are their x paths.
 * Image-left is "Sol" (left_x / left_leg), image-right is "Oʻng".
 * Colors follow design artboard "VariantC" (light = chip dot, deep = line and point).
 */

export const pair = (name: string, base: string, l: number, r: number): PointDef[] => [
  { id: `${base}.left_x`, label: `${name}-Sol`, side: 'left', xPath: `${base}.left_x`, mirror: `${base}.right_x`, defX: l },
  { id: `${base}.right_x`, label: `${name}-Oʻng`, side: 'right', xPath: `${base}.right_x`, mirror: `${base}.left_x`, defX: r },
]

/** Four points across two legs: outer edges mirror each other, inner edges mirror each other. */
export const legs = (name: string, base: string, d: [number, number, number, number]): PointDef[] => {
  const L = `${base}.left_leg`, R = `${base}.right_leg`
  return [
    { id: `${L}.left_x`, label: `${name}-Sol-Sol`, side: 'left', xPath: `${L}.left_x`, mirror: `${R}.right_x`, defX: d[0] },
    { id: `${L}.right_x`, label: `${name}-Sol-Oʻng`, side: 'left', xPath: `${L}.right_x`, mirror: `${R}.left_x`, defX: d[1] },
    { id: `${R}.left_x`, label: `${name}-Oʻng-Sol`, side: 'right', xPath: `${R}.left_x`, mirror: `${L}.right_x`, defX: d[2] },
    { id: `${R}.right_x`, label: `${name}-Oʻng-Oʻng`, side: 'right', xPath: `${R}.right_x`, mirror: `${L}.left_x`, defX: d[3] },
  ]
}

export const C = {
  orange: { light: '#F4A24A', deep: '#D9730D' },
  purple: { light: '#B07CF5', deep: '#8B4FE0' },
  pink: { light: '#EE5F7A', deep: '#D63A5A' },
  green: { light: '#5FD38A', deep: '#1FA564' },
  blue: { light: '#6A9CF8', deep: '#3B78E8' },
  cyan: { light: '#6FDCEF', deep: '#1AA7C0' },
  teal: { light: '#7FE0D2', deep: '#2FB3A0' },
}

const T = GARMENT_GROUP_NAMES.tshirt

/** One point per image side at a shared y (the sleeve cuff corners): `${base}.left|right.{x,y}`. */
const sides = (name: string, base: string, l: number, r: number): PointDef[] => [
  { id: `${base}.left.x`, label: `${name}-${SIDE.left}`, side: 'left', xPath: `${base}.left.x`, mirror: `${base}.right.x`, defX: l },
  { id: `${base}.right.x`, label: `${name}-${SIDE.right}`, side: 'right', xPath: `${base}.right.x`, mirror: `${base}.left.x`, defX: r },
]

/**
 * T-shirt set (docs/03, docs/09 #92), in the order the user marks them, top to bottom. Optional for now:
 * collar, collar_bottom, armpit. The cuff corners replace the legacy `sleeve_end` (read only, never written).
 */
export const TSHIRT_GROUPS: GroupDef[] = [
  { id: 'collar', name: T.collar, ...C.teal, yPaths: ['collar.y'], defY: 0.08, optional: true, points: pair(T.collar, 'collar', 0.4, 0.6) },
  { id: 'shoulder', name: T.shoulder, ...C.orange, yPaths: ['shoulder.y'], defY: 0.1, points: pair(T.shoulder, 'shoulder', 0.25, 0.75) },
  {
    id: 'collar_bottom', name: T.collar_bottom, ...C.cyan, yPaths: ['collar_bottom.y'], defY: 0.16, optional: true,
    points: [{ id: 'collar_bottom.x', label: `${T.collar_bottom}-${SIDE.center}`, side: 'center', xPath: 'collar_bottom.x', defX: 0.5 }],
  },
  { id: 'armpit', name: T.armpit, ...C.blue, yPaths: ['armpit.y'], defY: 0.22, optional: true, points: pair(T.armpit, 'armpit', 0.28, 0.72) },
  {
    id: 'sleeve_cuff_outer', name: T.sleeve_cuff_outer, ...C.purple,
    yPaths: ['sleeve_cuff_outer.left.y', 'sleeve_cuff_outer.right.y'], defY: 0.28,
    points: sides(T.sleeve_cuff_outer, 'sleeve_cuff_outer', 0.04, 0.96),
  },
  {
    id: 'sleeve_cuff_inner', name: T.sleeve_cuff_inner, ...C.purple,
    yPaths: ['sleeve_cuff_inner.left.y', 'sleeve_cuff_inner.right.y'], defY: 0.33,
    points: sides(T.sleeve_cuff_inner, 'sleeve_cuff_inner', 0.12, 0.88),
  },
  { id: 'chest', name: T.chest, ...C.pink, yPaths: ['chest.y'], defY: 0.25, points: pair(T.chest, 'chest', 0.3, 0.7) },
  { id: 'waist', name: T.waist, ...C.green, yPaths: ['waist.y'], defY: 0.5, points: pair(T.waist, 'waist', 0.325, 0.675) },
  { id: 'hem', name: T.hem, ...C.blue, yPaths: ['hem.y'], defY: 0.9, points: pair(T.hem, 'hem', 0.325, 0.675) },
]

/** Collar groups: step 2 of the T-shirt editor (docs/09 #102). Required there (not optional). */
const NECK_IDS = new Set(['collar', 'collar_bottom'])
/** Step 1: every T-shirt group except the collar points (they move to step 2 with the neckline hole). */
export const TSHIRT_MAIN_GROUPS: GroupDef[] = TSHIRT_GROUPS.filter((g) => !NECK_IDS.has(g.id))
/** Step 2: collar left/right + collar_bottom, all three needed for Save. */
export const TSHIRT_NECK_GROUPS: GroupDef[] = TSHIRT_GROUPS.filter((g) => NECK_IDS.has(g.id))
  .map((g) => ({ ...g, optional: false }))

export const PANTS_GROUPS: GroupDef[] = [
  {
    id: 'waist', name: 'Bel', ...C.green, yPaths: ['waist.y'], defY: 0.05,
    points: [
      ...pair('Bel', 'waist', 0.25, 0.75).slice(0, 1),
      { id: 'waist.center_x', label: 'Bel-Markaz', side: 'center', xPath: 'waist.center_x', defX: 0.5 },
      ...pair('Bel', 'waist', 0.25, 0.75).slice(1),
    ],
  },
  { id: 'hip', name: 'Son', ...C.blue, yPaths: ['hip.y'], defY: 0.25, points: pair('Son', 'hip', 0.225, 0.775) },
  {
    id: 'crotch', name: 'Qoʻshilish', ...C.pink, yPaths: ['crotch.y'], defY: 0.4,
    points: [{ id: 'crotch.center_x', label: 'Qoʻshilish', side: 'center', xPath: 'crotch.center_x', defX: 0.5 }],
  },
  {
    id: 'knee', name: 'Tizza', ...C.cyan, yPaths: ['knee.y', 'knee.left_leg.y', 'knee.right_leg.y'], defY: 0.65,
    points: legs('Tizza', 'knee', [0.15, 0.35, 0.65, 0.85]),
  },
  {
    id: 'hem', name: 'Pocha', ...C.teal, yPaths: ['hem.left_leg.y', 'hem.right_leg.y'], defY: 0.95,
    points: legs('Pocha', 'hem', [0.175, 0.325, 0.675, 0.825]),
  },
]

export const groupsFor = (type: GarmentType): GroupDef[] => (type === 'pants' ? PANTS_GROUPS : TSHIRT_GROUPS)

// ---------- order rules (same as backend apps/garments/landmark_checks.py, plus the editor's MIN_GAP) ----------

export const lr = (base: string): XRule => ({ a: `${base}.left_x`, b: `${base}.right_x`, gap: MIN_GAP })
/** Top-to-bottom chain of group ids. */
export const chain = (...ids: string[]): YRule[] => ids.slice(1).map((b, i) => ({ a: ids[i], b, gap: MIN_GAP }))
/** Left-to-right chain across both legs: Sol-Sol < Sol-Oʻng < Oʻng-Sol < Oʻng-Oʻng. */
export const legChain = (base: string): XRule[] => {
  const ids = [`${base}.left_leg.left_x`, `${base}.left_leg.right_x`, `${base}.right_leg.left_x`, `${base}.right_leg.right_x`]
  return ids.slice(1).map((b, i) => ({ a: ids[i], b, gap: MIN_GAP }))
}
/** warp.py uses waist.center_x - 5 / + 5 as the inner crotch edges, so it must stay 5 px inside the hip. */
export const CENTER_HIP_MARGIN = 5

export const TSHIRT_RULES: Rules = {
  x: [
    lr('collar'), lr('shoulder'), lr('armpit'), lr('chest'), lr('waist'), lr('hem'),
    { a: 'collar.left_x', b: 'collar_bottom.x', gap: MIN_GAP },
    { a: 'collar_bottom.x', b: 'collar.right_x', gap: MIN_GAP },
    { a: 'sleeve_cuff_outer.left.x', b: 'sleeve_cuff_outer.right.x', gap: MIN_GAP },
    { a: 'sleeve_cuff_inner.left.x', b: 'sleeve_cuff_inner.right.x', gap: MIN_GAP },
  ],
  y: [
    { a: 'collar', b: 'collar_bottom', gap: MIN_GAP },
    { a: 'shoulder', b: 'armpit', gap: MIN_GAP },
    ...chain('shoulder', 'chest', 'waist', 'hem'),
    { a: 'shoulder', b: 'sleeve_cuff_outer', gap: MIN_GAP },
    { a: 'shoulder', b: 'sleeve_cuff_inner', gap: MIN_GAP },
  ],
}

export const PANTS_RULES: Rules = {
  x: [
    lr('waist'), lr('hip'),
    { a: 'waist.left_x', b: 'waist.center_x', gap: MIN_GAP },
    { a: 'waist.center_x', b: 'waist.right_x', gap: MIN_GAP },
    { a: 'hip.left_x', b: 'waist.center_x', gap: CENTER_HIP_MARGIN + MIN_GAP },
    { a: 'waist.center_x', b: 'hip.right_x', gap: CENTER_HIP_MARGIN + MIN_GAP },
    ...legChain('knee'), ...legChain('hem'),
  ],
  y: chain('waist', 'hip', 'crotch', 'knee', 'hem'),
}

export const rulesFor = (type: GarmentType): Rules => (type === 'pants' ? PANTS_RULES : TSHIRT_RULES)

const touches = (ids: Set<string>, r: { a: string; b: string }) =>
  [r.a, r.b].some((v) => ids.has(v) || ids.has(v.split('.')[0]))
/** Rules between the step-1 groups only (no collar rule: those points are not in step 1). */
export const TSHIRT_MAIN_RULES: Rules = {
  x: TSHIRT_RULES.x.filter((r) => !touches(NECK_IDS, r)),
  y: TSHIRT_RULES.y.filter((r) => !touches(NECK_IDS, r)),
}
/** Rules between the collar points (step 2): left < bottom < right, collar above collar_bottom. */
export const TSHIRT_NECK_RULES: Rules = {
  x: TSHIRT_RULES.x.filter((r) => touches(NECK_IDS, r) && [r.a, r.b].every((v) => NECK_IDS.has(v.split('.')[0]))),
  y: TSHIRT_RULES.y.filter((r) => NECK_IDS.has(r.a) && NECK_IDS.has(r.b)),
}

/** Groups and rules of the main editor (step 1 for T-shirts; pants have one step). */
export const mainGroupsFor = (type: GarmentType): GroupDef[] => (type === 'pants' ? PANTS_GROUPS : TSHIRT_MAIN_GROUPS)
export const mainRulesFor = (type: GarmentType): Rules => (type === 'pants' ? PANTS_RULES : TSHIRT_MAIN_RULES)

