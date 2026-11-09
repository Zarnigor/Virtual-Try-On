/**
 * Pure landmark-editor logic (no React). Unit-tested in geometry.test.ts.
 *
 * Coordinates are pixels of the image itself (not screen pixels), integers, clamped to [0, w] x [0, h].
 * Every point of a group shares ONE y (docs/09: shared Y for all groups). Each point owns its x.
 * Symmetry mirrors x around axis = w / 2: x' = w - x; single (center) points snap to the axis.
 *
 * Payload shape is unchanged: toLandmarks() starts from a copy of the loaded landmarks and only
 * overwrites the paths the groups manage, so unknown fields survive and a round-trip is identical.
 */

export type Side = 'left' | 'right' | 'center'

export interface PointDef {
  id: string
  label: string
  side: Side
  /** Dotted path of this point's x in the landmarks object, e.g. "shoulder.left_x". */
  xPath: string
  /** Point id that mirrors this one under symmetry. */
  mirror?: string
  /** Default x as a fraction of the image width (used when the record has no value). */
  defX: number
}

export interface GroupDef {
  id: string
  name: string
  /** Light tone (chip dot), deep tone (line + point fill). */
  light: string
  deep: string
  /** Every path that stores this group's y. All are written with the same value. */
  yPaths: string[]
  /** Default y as a fraction of the image height. */
  defY: number
  points: PointDef[]
}

export interface EditorState {
  /** y per group id */
  ys: Record<string, number>
  /** x per point id */
  xs: Record<string, number>
}

export interface Bounds {
  w: number
  h: number
}

type Json = Record<string, unknown>

export function getPath(obj: unknown, path: string): number | undefined {
  let cur: unknown = obj
  for (const k of path.split('.')) {
    if (cur == null || typeof cur !== 'object') return undefined
    cur = (cur as Json)[k]
  }
  return typeof cur === 'number' && Number.isFinite(cur) ? cur : undefined
}

function setPath(obj: Json, path: string, val: number): void {
  const keys = path.split('.')
  let cur = obj
  for (const k of keys.slice(0, -1)) {
    const next = cur[k]
    if (next == null || typeof next !== 'object') cur[k] = {}
    cur = cur[k] as Json
  }
  cur[keys[keys.length - 1]] = val
}

export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

const clampX = (x: number, b: Bounds) => clamp(Math.round(x), 0, b.w)
const clampY = (y: number, b: Bounds) => clamp(Math.round(y), 0, b.h)

/** Symmetry axis. Always the image center (also the fallback for old records). */
export const axisX = (b: Bounds) => b.w / 2
export const mirrorX = (x: number, b: Bounds) => clampX(b.w - x, b)

export function findPoint(groups: GroupDef[], pointId: string): { group: GroupDef; point: PointDef } | null {
  for (const group of groups) {
    const point = group.points.find((p) => p.id === pointId)
    if (point) return { group, point }
  }
  return null
}

/**
 * Read landmarks into editor state. Missing values fall back to the defaults
 * (center points: x = w / 2). Old records whose sides had different y's get their average.
 * Returns the ids of points whose x came from the record (for the "placed" counter).
 */
export function fromLandmarks(
  landmarks: unknown, groups: GroupDef[], b: Bounds,
): { state: EditorState; loaded: string[] } {
  const ys: Record<string, number> = {}
  const xs: Record<string, number> = {}
  const loaded: string[] = []
  for (const g of groups) {
    const found = g.yPaths.map((p) => getPath(landmarks, p)).filter((v): v is number => v !== undefined)
    ys[g.id] = clampY(found.length ? found.reduce((a, v) => a + v, 0) / found.length : g.defY * b.h, b)
    for (const p of g.points) {
      const x = getPath(landmarks, p.xPath)
      if (x !== undefined) loaded.push(p.id)
      xs[p.id] = clampX(x ?? (p.side === 'center' ? axisX(b) : p.defX * b.w), b)
    }
  }
  return { state: { ys, xs }, loaded }
}

/** Write editor state back into a copy of the original landmarks (same shape, unknown fields kept). */
export function toLandmarks(original: unknown, state: EditorState, groups: GroupDef[]): Json {
  const out: Json =
    original && typeof original === 'object' ? structuredClone(original as Json) : {}
  for (const g of groups) {
    for (const p of g.yPaths) setPath(out, p, state.ys[g.id])
    for (const pt of g.points) setPath(out, pt.xPath, state.xs[pt.id])
  }
  return out
}

/**
 * Move one point to (x, y). The y applies to the whole group. With symmetry on, a center point
 * snaps to the axis and a paired point moves its mirror to w - x.
 */
export function movePoint(
  state: EditorState, groups: GroupDef[], pointId: string,
  x: number, y: number, b: Bounds, symmetry: boolean,
): EditorState {
  const hit = findPoint(groups, pointId)
  if (!hit) return state
  const { group, point } = hit
  const xs = { ...state.xs }
  let nx = clampX(x, b)
  if (symmetry && point.side === 'center') nx = clampX(axisX(b), b)
  xs[point.id] = nx
  if (symmetry && point.mirror) xs[point.mirror] = mirrorX(nx, b)
  return { ys: { ...state.ys, [group.id]: clampY(y, b) }, xs }
}

/** Arrow-key / button nudge by (dx, dy) image pixels. */
export function nudgePoint(
  state: EditorState, groups: GroupDef[], pointId: string,
  dx: number, dy: number, b: Bounds, symmetry: boolean,
): EditorState {
  const hit = findPoint(groups, pointId)
  if (!hit) return state
  return movePoint(
    state, groups, pointId, state.xs[pointId] + dx, state.ys[hit.group.id] + dy, b, symmetry,
  )
}

/** Turning symmetry on snaps every center point to the axis right away (pairs mirror on the next move). */
export function snapCenters(state: EditorState, groups: GroupDef[], b: Bounds): EditorState {
  const xs = { ...state.xs }
  for (const g of groups) for (const p of g.points) if (p.side === 'center') xs[p.id] = clampX(axisX(b), b)
  return { ...state, xs }
}
