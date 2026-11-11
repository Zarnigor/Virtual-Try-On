import { describe, expect, it } from 'vitest'
import {
  MIN_GAP, activeRules, fromLandmarks, movePoint, nudgePoint, saveState, snapCenters, toLandmarks,
  type Bounds, type EditorState, type Rules,
} from './geometry'
import { PANTS_GROUPS, PANTS_RULES, TSHIRT_GROUPS, TSHIRT_RULES, rulesFor } from './garmentGroups'

const B: Bounds = { w: 480, h: 640 }

const TSHIRT = {
  shoulder: { y: 198, left_x: 124, right_x: 356 },
  chest: { y: 326, left_x: 140, right_x: 340, width: 200 },
  waist: { y: 416, left_x: 150, right_x: 330 },
  hem: { y: 488, left_x: 142, right_x: 338 },
  sleeve_cuff_outer: { left: { x: 20, y: 270 }, right: { x: 460, y: 270 } },
  sleeve_cuff_inner: { left: { x: 60, y: 310 }, right: { x: 420, y: 310 } },
}

const PANTS = {
  waist: { y: 30, left_x: 120, right_x: 360, center_x: 240 },
  hip: { y: 160, left_x: 110, right_x: 370 },
  crotch: { y: 250, center_x: 238 },
  knee: {
    y: 420,
    left_leg: { left_x: 80, right_x: 200, y: 420 },
    right_leg: { left_x: 280, right_x: 400, y: 420 },
  },
  hem: {
    left_leg: { left_x: 90, right_x: 190, y: 610 },
    right_leg: { left_x: 290, right_x: 390, y: 610 },
  },
}

const pants = () => fromLandmarks(PANTS, PANTS_GROUPS, B).state
const tshirt = () => fromLandmarks(TSHIRT, TSHIRT_GROUPS, B).state
/** The rules the editor applies to the sample record (its optional groups are not placed). */
const T_RULES = activeRules(TSHIRT_RULES, TSHIRT_GROUPS, new Set(fromLandmarks(TSHIRT, TSHIRT_GROUPS, B).loaded))
const withX = (s: EditorState, xs: Record<string, number>): EditorState => ({ ...s, xs: { ...s.xs, ...xs } })

/** Rules a state breaks (empty = all kept with the editor gap). */
function broken(s: EditorState, rules: Rules): string[] {
  return [
    ...rules.x.filter((r) => s.xs[r.b] - s.xs[r.a] < r.gap).map((r) => `${r.a} < ${r.b}`),
    ...rules.y.filter((r) => s.ys[r.b] - s.ys[r.a] < r.gap).map((r) => `${r.a} < ${r.b}`),
  ]
}

const move = (s: EditorState, id: string, x: number, y: number, sym = false) =>
  movePoint(s, PANTS_GROUPS, id, x, y, B, sym, PANTS_RULES)

describe('rule tables', () => {
  it('every rule names a real point / group', () => {
    for (const [groups, rules] of [[TSHIRT_GROUPS, TSHIRT_RULES], [PANTS_GROUPS, PANTS_RULES]] as const) {
      const points = new Set(groups.flatMap((g) => g.points.map((p) => p.id)))
      const ids = new Set(groups.map((g) => g.id))
      for (const r of rules.x) expect(points.has(r.a) && points.has(r.b), `${r.a} ${r.b}`).toBe(true)
      for (const r of rules.y) expect(ids.has(r.a) && ids.has(r.b), `${r.a} ${r.b}`).toBe(true)
    }
    expect(rulesFor('pants')).toBe(PANTS_RULES)
    expect(rulesFor('tshirt')).toBe(TSHIRT_RULES)
  })

  it('the sample records and the defaults keep every rule', () => {
    expect(broken(tshirt(), T_RULES)).toEqual([])
    expect(broken(pants(), PANTS_RULES)).toEqual([])
    expect(broken(fromLandmarks({}, TSHIRT_GROUPS, B).state, TSHIRT_RULES)).toEqual([])
    expect(broken(fromLandmarks({}, PANTS_GROUPS, B).state, PANTS_RULES)).toEqual([])
  })
})

describe('x order: a drag stops at the neighbour', () => {
  it('left point stops 4 px before the right point / the waist center', () => {
    expect(movePoint(tshirt(), TSHIRT_GROUPS, 'shoulder.left_x', 400, 198, B, false, TSHIRT_RULES).xs['shoulder.left_x'])
      .toBe(356 - MIN_GAP)
    expect(move(pants(), 'waist.left_x', 400, 30).xs['waist.left_x']).toBe(240 - MIN_GAP)
    expect(move(pants(), 'waist.right_x', 10, 30).xs['waist.right_x']).toBe(240 + MIN_GAP)
  })

  it('legs: Sol-Sol < Sol-Oʻng < Oʻng-Sol < Oʻng-Oʻng', () => {
    expect(move(pants(), 'knee.left_leg.right_x', 300, 420).xs['knee.left_leg.right_x']).toBe(276)
    expect(move(pants(), 'knee.right_leg.left_x', 100, 420).xs['knee.right_leg.left_x']).toBe(204)
    expect(move(pants(), 'hem.left_leg.left_x', 470, 610).xs['hem.left_leg.left_x']).toBe(186)
  })

  it('nudge stops at the neighbour too', () => {
    let s = tshirt()
    for (let i = 0; i < 100; i++) s = nudgePoint(s, TSHIRT_GROUPS, 'chest.left_x', 5, 0, B, false, TSHIRT_RULES)
    expect(s.xs['chest.left_x']).toBe(340 - MIN_GAP)
  })

  it('no valid place: the point stays where it is', () => {
    const tight = withX(pants(), { 'waist.left_x': 238, 'waist.right_x': 242 }) // no room for the center
    expect(move(tight, 'waist.center_x', 300, 30).xs['waist.center_x']).toBe(240)
  })
})

describe('pants waist center range (warp.py: center ± 5 inside the hip)', () => {
  const wide = () => withX(pants(), { 'waist.left_x': 50, 'waist.right_x': 430 })

  it('left side: waist.left_x + 4 and hip.left_x + 5 + 4', () => {
    expect(move(pants(), 'waist.center_x', 0, 30).xs['waist.center_x']).toBe(124) // waist wins
    expect(move(wide(), 'waist.center_x', 0, 30).xs['waist.center_x']).toBe(110 + 5 + MIN_GAP) // hip wins
  })

  it('right side: waist.right_x - 4 and hip.right_x - 5 - 4', () => {
    expect(move(pants(), 'waist.center_x', 480, 30).xs['waist.center_x']).toBe(356)
    expect(move(wide(), 'waist.center_x', 480, 30).xs['waist.center_x']).toBe(370 - 5 - MIN_GAP)
  })

  it('moving the hip cannot pass the center either', () => {
    expect(move(pants(), 'hip.left_x', 300, 160).xs['hip.left_x']).toBe(240 - 5 - MIN_GAP)
    expect(move(pants(), 'hip.right_x', 100, 160).xs['hip.right_x']).toBe(240 + 5 + MIN_GAP)
  })

  it('symmetry: the axis is used only when it is inside the range, otherwise the center stays', () => {
    expect(move(withX(pants(), { 'waist.center_x': 250 }), 'waist.center_x', 300, 30, true).xs['waist.center_x'])
      .toBe(240)
    const off = withX(pants(), { 'waist.left_x': 250, 'waist.center_x': 270, 'waist.right_x': 300 })
    expect(move(off, 'waist.center_x', 300, 30, true).xs['waist.center_x']).toBe(270)
    expect(snapCenters(off, PANTS_GROUPS, B, PANTS_RULES).xs['waist.center_x']).toBe(270)
    expect(snapCenters(off, PANTS_GROUPS, B, PANTS_RULES).xs['crotch.center_x']).toBe(240) // free: snaps
  })
})

describe('vertical order', () => {
  it('a group stops 4 px from the group above and below', () => {
    expect(move(pants(), 'hip.left_x', 110, 0).ys.hip).toBe(30 + MIN_GAP)
    expect(move(pants(), 'hip.left_x', 110, 600).ys.hip).toBe(250 - MIN_GAP)
    expect(move(pants(), 'hem.left_leg.left_x', 90, 0).ys.hem).toBe(420 + MIN_GAP)
  })

  it('tshirt chain and sleeves below the shoulder', () => {
    const t = (id: string, x: number, y: number) => movePoint(tshirt(), TSHIRT_GROUPS, id, x, y, B, false, T_RULES)
    expect(t('chest.left_x', 140, 100).ys.chest).toBe(198 + MIN_GAP)
    expect(t('waist.left_x', 150, 640).ys.waist).toBe(488 - MIN_GAP)
    expect(t('sleeve_cuff_outer.left.x', 20, 0).ys.sleeve_cuff_outer).toBe(198 + MIN_GAP)
    expect(t('sleeve_cuff_inner.left.x', 60, 0).ys.sleeve_cuff_inner).toBe(198 + MIN_GAP)
    // the shoulder is held by the chest and the cuffs (outer cuff at 270, chest at 326)
    expect(t('shoulder.left_x', 124, 640).ys.shoulder).toBe(270 - MIN_GAP)
  })

  it('a blocked y does not block the x of the same move', () => {
    const s = move(pants(), 'hip.left_x', 100, 0)
    expect([s.xs['hip.left_x'], s.ys.hip]).toEqual([100, 34])
  })
})

describe('symmetry keeps the pair symmetric while clamping', () => {
  it('a pair stops at the axis minus half the gap', () => {
    const s = movePoint(tshirt(), TSHIRT_GROUPS, 'shoulder.left_x', 300, 198, B, true, TSHIRT_RULES)
    expect([s.xs['shoulder.left_x'], s.xs['shoulder.right_x']]).toEqual([238, 242])
  })

  it('inner leg points meet at the axis with the gap', () => {
    const s = move(pants(), 'hem.left_leg.right_x', 300, 610, true)
    expect([s.xs['hem.left_leg.right_x'], s.xs['hem.right_leg.left_x']]).toEqual([238, 242])
  })

  it('when the mirror would cross its own neighbour, both stop together', () => {
    // asymmetric start: Oʻng-Sol far right, so Oʻng-Oʻng (mirror of Sol-Sol) must stay >= 384
    const start = withX(pants(), { 'knee.right_leg.left_x': 380 })
    const s = move(start, 'knee.left_leg.left_x', 150, 420, true)
    expect(s.xs['knee.left_leg.left_x']).toBe(96)
    expect(s.xs['knee.right_leg.right_x']).toBe(384)
    expect(broken(s, { x: PANTS_RULES.x.filter((r) => r.a.startsWith('knee')), y: [] })).toEqual([])
  })

  it('no valid symmetric place: both stay where they are', () => {
    const start = withX(pants(), { 'knee.right_leg.left_x': 478 }) // mirror would need x <= -2
    const s = move(start, 'knee.left_leg.left_x', 50, 420, true)
    expect(s.xs['knee.left_leg.left_x']).toBe(80)
    expect(s.xs['knee.right_leg.right_x']).toBe(400)
  })
})

describe('old records with a 1-3 px gap', () => {
  const old = () => {
    const r = structuredClone(TSHIRT)
    r.shoulder.right_x = r.shoulder.left_x + 2 // 2 px gap (the backend accepts it)
    r.chest.y = r.shoulder.y + 1
    r.sleeve_cuff_outer.left.y = r.sleeve_cuff_outer.right.y = r.shoulder.y + 3
    r.sleeve_cuff_inner.left.y = r.sleeve_cuff_inner.right.y = r.shoulder.y + 3
    return r
  }

  it('loading and saving without moving keeps the record exactly', () => {
    const { state } = fromLandmarks(old(), TSHIRT_GROUPS, B)
    expect(toLandmarks(old(), state, TSHIRT_GROUPS)).toEqual(old())
  })

  it('moving another group does not touch them', () => {
    const { state } = fromLandmarks(old(), TSHIRT_GROUPS, B)
    const s = movePoint(state, TSHIRT_GROUPS, 'hem.left_x', 150, 500, B, false, TSHIRT_RULES)
    const out = toLandmarks(old(), s, TSHIRT_GROUPS) as typeof TSHIRT
    expect(out.shoulder).toEqual(old().shoulder)
    expect(out.chest.y).toBe(old().chest.y)
  })

  it('moving one of them clamps it to the editor gap', () => {
    const { state } = fromLandmarks(old(), TSHIRT_GROUPS, B)
    const s = nudgePoint(state, TSHIRT_GROUPS, 'shoulder.left_x', 1, 0, B, false, TSHIRT_RULES)
    expect(s.xs['shoulder.left_x']).toBe(126 - MIN_GAP)
  })
})

describe('Save gating', () => {
  it('needs every point placed', () => {
    expect(saveState(3, 12)).toEqual({ canSave: false, hint: 'Saqlash uchun barcha nuqtalarni qoʻying (3 / 12).' })
    expect(saveState(11, 12).canSave).toBe(false)
    expect(saveState(12, 12)).toEqual({ canSave: true, hint: '' })
    expect(saveState(0, 0).canSave).toBe(false)
  })

  it('a complete record counts as placed, an empty one does not', () => {
    const total = (g: typeof PANTS_GROUPS) => g.reduce((n, x) => n + x.points.length, 0)
    expect(saveState(fromLandmarks(PANTS, PANTS_GROUPS, B).loaded.length, total(PANTS_GROUPS)).canSave).toBe(true)
    expect(saveState(fromLandmarks({}, PANTS_GROUPS, B).loaded.length, total(PANTS_GROUPS)).canSave).toBe(false)
  })
})
