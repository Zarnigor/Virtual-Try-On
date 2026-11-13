/**
 * Neckline hole polygon (docs/09 #102): pure helpers, no React. Unit-tested in neckHole.test.ts.
 *
 * The polygon is stored as `landmarks.neck_hole.polygon` = [[x, y], ...] in pixels of the cleaned garment PNG.
 * The rules mirror backend apps/garments/landmark_checks.py `neck_hole_problem` (the server stays the authority).
 */
import { getPath } from './geometry'

export type Pt = [number, number]

/** Suggestion shapes (docs/09 #102): the user picks one; `guessNeckShape` only sets the default. */
export type NeckShape = 'v' | 'round' | 'square'
/** Default-shape guess from collar depth / collar width (the three collar points cannot tell V from square for sure:
 * #47 square 0.56, #40 V 0.82, crews #28 / #43 0.19). */
export const ROUND_BELOW = 0.35
export const V_FROM = 0.65
/** The collar points sit on the band's OUTER edge; the hole follows the INNER edge: sides and bottom move inward by
 * this x the collar width (the engine's NECKLINE_INSET, backend mls.py), at least NECK_INSET_MIN px. */
export const NECK_INSET = 0.06
export const NECK_INSET_MIN = 3
/** Points on the curved part of a round suggestion. */
export const CURVE_POINTS = 10

// Same limits as the backend (landmark_checks.py NECK_HOLE_*).
export const NECK_HOLE_MIN_POINTS = 3
export const NECK_HOLE_MAX_POINTS = 64
export const NECK_HOLE_MAX_AREA = 0.25
export const NECK_HOLE_TOP = 0.4
export const NECK_HOLE_ABOVE = 3

export type HoleProblem = 'hole_points' | 'bounds' | 'hole_self' | 'hole_empty' | 'hole_area' | 'hole_top'

export interface AlphaInfo {
  /** Visible pixels (alpha > 0), inclusive. */
  bbox: { x0: number; y0: number; x1: number; y1: number } | null
  /** Solid pixels (alpha > 128): the area rule. */
  area: number | null
}

/** The three collar landmarks, or null while one of them is missing. */
export function collarPoints(lm: unknown): { L: Pt; R: Pt; B: Pt } | null {
  const y = getPath(lm, 'collar.y'), l = getPath(lm, 'collar.left_x'), r = getPath(lm, 'collar.right_x')
  const bx = getPath(lm, 'collar_bottom.x'), by = getPath(lm, 'collar_bottom.y')
  if ([y, l, r, bx, by].some((v) => v === undefined)) return null
  return { L: [l!, y!], R: [r!, y!], B: [bx!, by!] }
}

export function guessNeckShape(lm: unknown): NeckShape {
  const c = collarPoints(lm)
  if (!c) return 'round'
  const ratio = (c.B[1] - c.L[1]) / Math.max(c.R[0] - c.L[0], 1)
  return ratio < ROUND_BELOW ? 'round' : ratio < V_FROM ? 'square' : 'v'
}

/**
 * Suggested hole (garment px, integers): the collar points' INNER outline (sides and bottom inset by NECK_INSET x the
 * collar width) closed along the garment's top edge `top` (alpha bbox y0), so the inner back is inside the hole like
 * the owner polygon 40-2.json. V: tip above collar_bottom. Round: a parabola. Square: straight sides with corners at
 * the collar_bottom row, side and bottom midpoints as extra handles. null while the collar points are incomplete or
 * out of order.
 */
export function suggestNeckHole(lm: unknown, shape: NeckShape, top?: number | null): Pt[] | null {
  const c = collarPoints(lm)
  if (!c) return null
  const { L, R, B } = c
  const width = R[0] - L[0]
  if (!(width > 0) || !(B[1] > L[1]) || !(L[0] < B[0] && B[0] < R[0])) return null
  const i = Math.max(NECK_INSET_MIN, Math.round(NECK_INSET * width))
  const lx = L[0] + i, rx = R[0] - i, cy = L[1]
  const by = Math.max(B[1] - i, cy + 2)
  if (!(rx - lx > 4)) return null
  // the top edge: the garment's top when it is clearly above the collar line, else the collar line itself
  const t = top != null && top < cy - 2 ? top : null
  const head: Pt[] = t != null ? [[lx, t], [rx, t]] : []
  const r = (pts: Pt[]) => pts.map(([x, y]) => [Math.round(x), Math.round(y)] as Pt)
  if (shape === 'v') {
    const tip = Math.max(B[1] - Math.round(1.5 * i), cy + 2)
    return r([...head, [rx, cy], [B[0], tip], [lx, cy]])
  }
  if (shape === 'square') {
    const mid = (cy + by) / 2
    return r([...head, [rx, cy], [rx, mid], [rx, by], [B[0], by], [lx, by], [lx, mid], [lx, cy]])
  }
  // round: parabola through (rx, cy), (B.x, by), (lx, cy), right to left
  const yAt = (x: number) => {
    const [x0, y0, x1, y1, x2, y2] = [rx, cy, B[0], by, lx, cy]
    return y0 * ((x - x1) * (x - x2)) / ((x0 - x1) * (x0 - x2)) +
      y1 * ((x - x0) * (x - x2)) / ((x1 - x0) * (x1 - x2)) +
      y2 * ((x - x0) * (x - x1)) / ((x2 - x0) * (x2 - x1))
  }
  const curve: Pt[] = []
  for (let k = 0; k < CURVE_POINTS; k++) {
    const x = rx - ((rx - lx) * k) / (CURVE_POINTS - 1)
    curve.push([x, k === 0 || k === CURVE_POINTS - 1 ? cy : yAt(x)])
  }
  return r([...head, ...curve])
}

export function polygonArea(pts: Pt[]): number {
  let s = 0
  for (let i = 0; i < pts.length; i++) {
    const [ax, ay] = pts[i], [bx, by] = pts[(i + 1) % pts.length]
    s += ax * by - bx * ay
  }
  return Math.abs(s) / 2
}

const orient = (a: Pt, b: Pt, c: Pt) => Math.sign((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
const onSeg = (a: Pt, b: Pt, c: Pt) =>
  Math.min(a[0], b[0]) <= c[0] && c[0] <= Math.max(a[0], b[0]) && Math.min(a[1], b[1]) <= c[1] && c[1] <= Math.max(a[1], b[1])

function segmentsTouch(p1: Pt, p2: Pt, p3: Pt, p4: Pt): boolean {
  const d1 = orient(p3, p4, p1), d2 = orient(p3, p4, p2), d3 = orient(p1, p2, p3), d4 = orient(p1, p2, p4)
  if (d1 * d2 < 0 && d3 * d4 < 0) return true
  return (d1 === 0 && onSeg(p3, p4, p1)) || (d2 === 0 && onSeg(p3, p4, p2)) ||
    (d3 === 0 && onSeg(p1, p2, p3)) || (d4 === 0 && onSeg(p1, p2, p4))
}

/** Two non-adjacent edges touch or cross, or a vertex repeats (same rule as the backend). */
export function selfIntersects(pts: Pt[]): boolean {
  const n = pts.length
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      if (j === i + 1 || (i === 0 && j === n - 1)) continue
      if (segmentsTouch(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n])) return true
    }
  }
  return new Set(pts.map(([x, y]) => `${x},${y}`)).size < n
}

/** null when the polygon passes every rule, else the reason (mirror of landmark_checks.neck_hole_problem). */
export function neckHoleProblem(poly: unknown, w: number, h: number, alpha?: AlphaInfo | null): HoleProblem | null {
  if (!Array.isArray(poly) || poly.length < NECK_HOLE_MIN_POINTS || poly.length > NECK_HOLE_MAX_POINTS) return 'hole_points'
  if (!poly.every((p) => Array.isArray(p) && p.length === 2 && p.every((c) => typeof c === 'number' && Number.isFinite(c)))) {
    return 'hole_points'
  }
  const pts = poly as Pt[]
  if (!pts.every(([x, y]) => x >= 0 && x <= w && y >= 0 && y <= h)) return 'bounds'
  if (selfIntersects(pts)) return 'hole_self'
  const area = polygonArea(pts)
  if (!(area > 0)) return 'hole_empty'
  if (area > NECK_HOLE_MAX_AREA * (alpha?.area ? alpha.area : w * h)) return 'hole_area'
  const b = alpha?.bbox ?? { x0: 0, y0: 0, x1: w - 1, y1: h - 1 }
  const top = b.y0 + NECK_HOLE_TOP * (b.y1 - b.y0 + 1)
  if (!pts.every(([, y]) => y >= b.y0 - NECK_HOLE_ABOVE && y <= top)) return 'hole_top'
  return null
}

/** The stored polygon of a landmarks record, or null. */
export function storedPolygon(lm: unknown): Pt[] | null {
  const hole = (lm as { neck_hole?: { polygon?: unknown } } | null)?.neck_hole
  const poly = hole?.polygon
  return Array.isArray(poly) ? (poly as Pt[]).map(([x, y]) => [x, y] as Pt) : null
}

/** Insert a vertex after edge `i` (between vertex i and i + 1) at `p`. */
export function insertVertex(pts: Pt[], i: number, p: Pt): Pt[] {
  return [...pts.slice(0, i + 1), [Math.round(p[0]), Math.round(p[1])], ...pts.slice(i + 1)]
}

/** Delete vertex `i`, never below NECK_HOLE_MIN_POINTS. */
export function deleteVertex(pts: Pt[], i: number): Pt[] {
  return pts.length <= NECK_HOLE_MIN_POINTS ? pts : pts.filter((_, k) => k !== i)
}

/** Move vertex `i` to `p`, clamped to the image. */
export function moveVertex(pts: Pt[], i: number, p: Pt, w: number, h: number): Pt[] {
  const c = (v: number, hi: number) => Math.min(hi, Math.max(0, Math.round(v)))
  return pts.map((q, k) => (k === i ? [c(p[0], w), c(p[1], h)] : q))
}

/** Landmarks with the polygon written in (a copy; every other key kept as is). */
export function withNeckHole(lm: Record<string, unknown>, poly: Pt[] | null): Record<string, unknown> {
  if (!poly) return lm
  return { ...lm, neck_hole: { polygon: poly.map(([x, y]) => [x, y]) } }
}

/** Auto-zoom for step 2: the top centre of the garment (image px), from the alpha bbox or the image size. */
export function neckView(w: number, h: number, bbox?: AlphaInfo['bbox']): { x: number; y: number; w: number; h: number } {
  const b = bbox ?? { x0: 0, y0: 0, x1: w - 1, y1: h - 1 }
  const bw = b.x1 - b.x0 + 1, bh = b.y1 - b.y0 + 1
  const vw = Math.round(bw * 0.7), vh = Math.round(bh * 0.5)
  return { x: Math.round(b.x0 + (bw - vw) / 2), y: Math.round(b.y0 - bh * 0.05), w: vw, h: vh }
}
