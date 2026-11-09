import type { GarmentType } from '../../api/types'
import type { GroupDef, PointDef } from './geometry'

/**
 * Landmark groups per garment type (names fixed by docs/03). Point ids are their x paths.
 * Image-left is "Sol" (left_x / left_leg), image-right is "Oʻng".
 * Colors follow design artboard "VariantC" (light = chip dot, deep = line and point).
 */

const pair = (name: string, base: string, l: number, r: number): PointDef[] => [
  { id: `${base}.left_x`, label: `${name}-Sol`, side: 'left', xPath: `${base}.left_x`, mirror: `${base}.right_x`, defX: l },
  { id: `${base}.right_x`, label: `${name}-Oʻng`, side: 'right', xPath: `${base}.right_x`, mirror: `${base}.left_x`, defX: r },
]

/** Four points across two legs: outer edges mirror each other, inner edges mirror each other. */
const legs = (name: string, base: string, d: [number, number, number, number]): PointDef[] => {
  const L = `${base}.left_leg`, R = `${base}.right_leg`
  return [
    { id: `${L}.left_x`, label: `${name}-Sol-Sol`, side: 'left', xPath: `${L}.left_x`, mirror: `${R}.right_x`, defX: d[0] },
    { id: `${L}.right_x`, label: `${name}-Sol-Oʻng`, side: 'left', xPath: `${L}.right_x`, mirror: `${R}.left_x`, defX: d[1] },
    { id: `${R}.left_x`, label: `${name}-Oʻng-Sol`, side: 'right', xPath: `${R}.left_x`, mirror: `${L}.right_x`, defX: d[2] },
    { id: `${R}.right_x`, label: `${name}-Oʻng-Oʻng`, side: 'right', xPath: `${R}.right_x`, mirror: `${L}.left_x`, defX: d[3] },
  ]
}

const C = {
  orange: { light: '#F4A24A', deep: '#D9730D' },
  purple: { light: '#B07CF5', deep: '#8B4FE0' },
  pink: { light: '#EE5F7A', deep: '#D63A5A' },
  green: { light: '#5FD38A', deep: '#1FA564' },
  blue: { light: '#6A9CF8', deep: '#3B78E8' },
  cyan: { light: '#6FDCEF', deep: '#1AA7C0' },
  teal: { light: '#7FE0D2', deep: '#2FB3A0' },
}

export const TSHIRT_GROUPS: GroupDef[] = [
  { id: 'shoulder', name: 'Yelka', ...C.orange, yPaths: ['shoulder.y'], defY: 0.1, points: pair('Yelka', 'shoulder', 0.25, 0.75) },
  {
    id: 'sleeve_end', name: 'Yeng', ...C.purple,
    yPaths: ['sleeve_end.left.y', 'sleeve_end.right.y'], defY: 0.3,
    points: [
      { id: 'sleeve_end.left.x', label: 'Yeng-Sol', side: 'left', xPath: 'sleeve_end.left.x', mirror: 'sleeve_end.right.x', defX: 0.05 },
      { id: 'sleeve_end.right.x', label: 'Yeng-Oʻng', side: 'right', xPath: 'sleeve_end.right.x', mirror: 'sleeve_end.left.x', defX: 0.95 },
    ],
  },
  { id: 'chest', name: 'Koʻkrak', ...C.pink, yPaths: ['chest.y'], defY: 0.25, points: pair('Koʻkrak', 'chest', 0.3, 0.7) },
  { id: 'waist', name: 'Bel', ...C.green, yPaths: ['waist.y'], defY: 0.5, points: pair('Bel', 'waist', 0.325, 0.675) },
  { id: 'hem', name: 'Pastki', ...C.blue, yPaths: ['hem.y'], defY: 0.9, points: pair('Pastki', 'hem', 0.325, 0.675) },
]

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
