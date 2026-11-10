import { MIN_GAP, type GroupDef, type PointDef, type Rules } from './geometry'
import { C, chain, legChain, legs, lr, pair } from './garmentGroups'

/**
 * Body landmark groups (names fixed by docs/03) on the 600x1200 canvas. Every line has left/right points
 * on the body edge; crotch also has its center; knee and ankle have both edges of each leg.
 * Same rules as the backend apps/bodies/landmark_checks.py, plus the editor's MIN_GAP (armpit <= chest: gap 0).
 */

const span = (id: string, name: string, color: { light: string; deep: string }, defY: number, l: number, r: number): GroupDef => ({
  id, name, ...color, yPaths: [`${id}.y`], defY, points: pair(name, id, l, r),
})

const crotchPoints: PointDef[] = [
  pair('Qoʻshilish', 'crotch', 0.33, 0.67)[0],
  { id: 'crotch.center_x', label: 'Qoʻshilish-Markaz', side: 'center', xPath: 'crotch.center_x', defX: 0.5 },
  pair('Qoʻshilish', 'crotch', 0.33, 0.67)[1],
]

export const BODY_GROUPS: GroupDef[] = [
  span('head_top', 'Bosh tepasi', C.teal, 0.042, 0.47, 0.53),
  span('neck', 'Boʻyin', C.cyan, 0.17, 0.45, 0.55),
  span('shoulder', 'Yelka', C.orange, 0.21, 0.33, 0.67),
  span('armpit', 'Qoʻltiq', C.purple, 0.28, 0.36, 0.64),
  span('chest', 'Koʻkrak', C.pink, 0.31, 0.35, 0.65),
  span('waist', 'Bel', C.green, 0.4, 0.37, 0.63),
  span('hip', 'Son', C.blue, 0.52, 0.34, 0.66),
  { id: 'crotch', name: 'Qoʻshilish', ...C.pink, yPaths: ['crotch.y'], defY: 0.56, points: crotchPoints },
  {
    id: 'knee', name: 'Tizza', ...C.cyan, yPaths: ['knee.y', 'knee.left_leg.y', 'knee.right_leg.y'], defY: 0.74,
    points: legs('Tizza', 'knee', [0.36, 0.48, 0.52, 0.64]),
  },
  {
    id: 'ankle', name: 'Toʻpiq', ...C.teal, yPaths: ['ankle.left_leg.y', 'ankle.right_leg.y'], defY: 0.9,
    points: legs('Toʻpiq', 'ankle', [0.39, 0.46, 0.54, 0.61]),
  },
  span('foot_bottom', 'Oyoq tagi', C.orange, 0.958, 0.37, 0.63),
]

const SPANS = ['head_top', 'neck', 'shoulder', 'armpit', 'chest', 'waist', 'hip', 'crotch', 'foot_bottom']

export const BODY_RULES: Rules = {
  x: [
    ...SPANS.map(lr),
    { a: 'crotch.left_x', b: 'crotch.center_x', gap: MIN_GAP },
    { a: 'crotch.center_x', b: 'crotch.right_x', gap: MIN_GAP },
    ...legChain('knee'), ...legChain('ankle'),
  ],
  y: [
    ...chain('head_top', 'neck', 'shoulder', 'armpit'),
    { a: 'armpit', b: 'chest', gap: 0 },
    ...chain('chest', 'waist', 'hip', 'crotch', 'knee', 'ankle', 'foot_bottom'),
  ],
}
