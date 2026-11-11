/**
 * Pure landmark-editor logic (no React). Unit-tested in geometry.test.ts.
 *
 * Coordinates are pixels of the image itself (not screen pixels), integers, clamped to [0, w] x [0, h].
 * Every point of a group shares ONE y (docs/09: shared Y for all groups). Each point owns its x.
 * Symmetry mirrors x around axis = w / 2: x' = w - x; single (center) points snap to the axis.
 *
 * Payload shape is unchanged: toLandmarks() starts from a copy of the loaded landmarks and only
 * overwrites the paths the groups manage, so unknown fields survive and a round-trip is identical.
 *
 * Order rules (docs/09 #53): a move is clamped so a point never crosses its neighbour (left x < right x,
 * vertical group order), keeping a gap. Loading never clamps: an old record stays exactly as saved until the
 * user moves a point. The backend checks the same rules with a strict "<" (apps/garments/landmark_checks.py).
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
  /** Optional group: not needed for Save; written only when all of its points are placed, else left out. */
  optional?: boolean
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

/** Gap the editor keeps between ordered points (image px). The backend only needs a strict "<". */
export const MIN_GAP = 4

/** xs[b] - xs[a] >= gap (point ids). */
export interface XRule { a: string; b: string; gap: number }
/** ys[b] - ys[a] >= gap (group ids; b is lower on the image). */
export interface YRule { a: string; b: string; gap: number }
export interface Rules { x: XRule[]; y: YRule[] }

export const NO_RULES: Rules = { x: [], y: [] }

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

/**
 * Write editor state back into a copy of the original landmarks (same shape, unknown fields kept).
 * An optional group is written only when all of its points are placed (`placed`; without it: when the original
 * record had the group); otherwise its top-level keys are left out (a default position is never saved as if the
 * user had marked it).
 */
export function toLandmarks(original: unknown, state: EditorState, groups: GroupDef[], placed?: Set<string>): Json {
  const out: Json =
    original && typeof original === 'object' ? structuredClone(original as Json) : {}
  for (const g of groups) {
    const marked = placed
      ? g.points.every((p) => placed.has(p.id))
      : g.points.every((p) => getPath(original, p.xPath) !== undefined)
    if (g.optional && !marked) {
      for (const path of [...g.yPaths, ...g.points.map((p) => p.xPath)]) delete out[path.split('.')[0]]
      continue
    }
    for (const p of g.yPaths) setPath(out, p, state.ys[g.id])
    for (const pt of g.points) setPath(out, pt.xPath, state.xs[pt.id])
  }
  return out
}

/** Rules that apply now: a rule touching an optional group with no placed point is skipped (its default
 * position must not block the user's moves). */
export function activeRules(rules: Rules, groups: GroupDef[], placed: Set<string>): Rules {
  const idle = new Set<string>()
  for (const g of groups) {
    if (g.optional && !g.points.some((p) => placed.has(p.id))) {
      idle.add(g.id)
      g.points.forEach((p) => idle.add(p.id))
    }
  }
  if (!idle.size) return rules
  const keep = (r: { a: string; b: string }) => !idle.has(r.a) && !idle.has(r.b)
  return { x: rules.x.filter(keep), y: rules.y.filter(keep) }
}

/** Points that count for Save: those of the required groups. */
export function requiredCount(groups: GroupDef[], placed: Set<string>): { placed: number; total: number } {
  const ids = groups.filter((g) => !g.optional).flatMap((g) => g.points.map((p) => p.id))
  return { placed: ids.filter((id) => placed.has(id)).length, total: ids.length }
}

interface Range { lo: number; hi: number }

/** Allowed x for `id` from the rules, ignoring rules that involve `skip` (its mirror, handled separately). */
function xRange(xs: Record<string, number>, id: string, rules: Rules, b: Bounds, skip?: string): Range {
  let lo = 0, hi = b.w
  for (const r of rules.x) {
    if (r.a === skip || r.b === skip) continue
    if (r.b === id) lo = Math.max(lo, xs[r.a] + r.gap)
    if (r.a === id) hi = Math.min(hi, xs[r.b] - r.gap)
  }
  return { lo: Math.ceil(lo), hi: Math.floor(hi) }
}

function yRange(ys: Record<string, number>, groupId: string, rules: Rules, b: Bounds): Range {
  let lo = 0, hi = b.h
  for (const r of rules.y) {
    if (r.b === groupId) lo = Math.max(lo, ys[r.a] + r.gap)
    if (r.a === groupId) hi = Math.min(hi, ys[r.b] - r.gap)
  }
  return { lo: Math.ceil(lo), hi: Math.floor(hi) }
}

/**
 * Allowed x for a point that moves together with its mirror (mirror x = w - x): its own range,
 * the mirror's range mapped through w - x, and the rules between the two.
 */
function mirroredRange(xs: Record<string, number>, id: string, mirror: string, rules: Rules, b: Bounds): Range {
  const own = xRange(xs, id, rules, b, mirror)
  const m = xRange(xs, mirror, rules, b, id)
  let lo = Math.max(own.lo, b.w - m.hi)
  let hi = Math.min(own.hi, b.w - m.lo)
  for (const r of rules.x) {
    if (r.a === id && r.b === mirror) hi = Math.min(hi, Math.floor((b.w - r.gap) / 2)) // (w - x) - x >= gap
    if (r.a === mirror && r.b === id) lo = Math.max(lo, Math.ceil((b.w + r.gap) / 2)) // x - (w - x) >= gap
  }
  return { lo, hi }
}

/** Clamp v into the range; if the range is empty (no valid place), stay at `current`. */
const into = (v: number, r: Range, current: number) => (r.lo > r.hi ? current : clamp(v, r.lo, r.hi))

/**
 * Move one point to (x, y). The y applies to the whole group. With symmetry on, a center point
 * snaps to the axis and a paired point moves its mirror to w - x.
 * With rules, the move stops at the neighbours (keeping the gap) instead of crossing them; a
 * symmetric pair is clamped together so it stays symmetric. If there is no valid place, the point
 * (and its mirror) stay where they are; a center point whose axis is outside its range stays too.
 */
export function movePoint(
  state: EditorState, groups: GroupDef[], pointId: string,
  x: number, y: number, b: Bounds, symmetry: boolean, rules: Rules = NO_RULES,
): EditorState {
  const hit = findPoint(groups, pointId)
  if (!hit) return state
  const { group, point } = hit
  const xs = { ...state.xs }
  const cur = state.xs[point.id]
  if (symmetry && point.side === 'center') {
    const axis = clampX(axisX(b), b)
    const r = xRange(state.xs, point.id, rules, b)
    if (axis >= r.lo && axis <= r.hi) xs[point.id] = axis
  } else if (symmetry && point.mirror) {
    const r = mirroredRange(state.xs, point.id, point.mirror, rules, b)
    if (r.lo <= r.hi) {
      const nx = clamp(clampX(x, b), r.lo, r.hi)
      xs[point.id] = nx
      xs[point.mirror] = mirrorX(nx, b)
    }
  } else {
    xs[point.id] = into(clampX(x, b), xRange(state.xs, point.id, rules, b), cur)
  }
  const ys = { ...state.ys, [group.id]: into(clampY(y, b), yRange(state.ys, group.id, rules, b), state.ys[group.id]) }
  return { ys, xs }
}

/** Arrow-key / button nudge by (dx, dy) image pixels. */
export function nudgePoint(
  state: EditorState, groups: GroupDef[], pointId: string,
  dx: number, dy: number, b: Bounds, symmetry: boolean, rules: Rules = NO_RULES,
): EditorState {
  const hit = findPoint(groups, pointId)
  if (!hit) return state
  return movePoint(
    state, groups, pointId, state.xs[pointId] + dx, state.ys[hit.group.id] + dy, b, symmetry, rules,
  )
}

/**
 * Turning symmetry on snaps every center point to the axis right away (pairs mirror on the next move).
 * A center point whose axis falls outside its allowed range stays where it is.
 */
export function snapCenters(state: EditorState, groups: GroupDef[], b: Bounds, rules: Rules = NO_RULES): EditorState {
  const xs = { ...state.xs }
  const axis = clampX(axisX(b), b)
  for (const g of groups) {
    for (const p of g.points) {
      if (p.side !== 'center') continue
      const r = xRange(xs, p.id, rules, b)
      if (axis >= r.lo && axis <= r.hi) xs[p.id] = axis
    }
  }
  return { ...state, xs }
}

/** Save is allowed only when every point has been placed (loaded from the record or moved by the user). */
export function saveState(placed: number, total: number): { canSave: boolean; hint: string } {
  const canSave = total > 0 && placed >= total
  return {
    canSave,
    hint: canSave ? '' : `Saqlash uchun barcha nuqtalarni qoʻying (${placed} / ${total}).`,
  }
}
