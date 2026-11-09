import { describe, expect, it } from 'vitest'
import {
  fromLandmarks, movePoint, nudgePoint, snapCenters, toLandmarks, type Bounds,
} from './geometry'
import { PANTS_GROUPS, TSHIRT_GROUPS } from './garmentGroups'

const B: Bounds = { w: 480, h: 640 }

const TSHIRT = {
  shoulder: { y: 198, left_x: 124, right_x: 356 },
  chest: { y: 326, left_x: 140, right_x: 340, width: 200 },
  waist: { y: 416, left_x: 150, right_x: 330 },
  hem: { y: 488, left_x: 142, right_x: 338 },
  sleeve_end: { left: { x: 20, y: 290 }, right: { x: 460, y: 290 } },
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

describe('round-trip keeps the payload unchanged', () => {
  it('tshirt (unknown fields like width survive)', () => {
    const { state } = fromLandmarks(TSHIRT, TSHIRT_GROUPS, B)
    expect(toLandmarks(TSHIRT, state, TSHIRT_GROUPS)).toEqual(TSHIRT)
  })

  it('pants', () => {
    const { state } = fromLandmarks(PANTS, PANTS_GROUPS, B)
    expect(toLandmarks(PANTS, state, PANTS_GROUPS)).toEqual(PANTS)
  })

  it('does not mutate the original object', () => {
    const copy = structuredClone(TSHIRT)
    const { state } = fromLandmarks(TSHIRT, TSHIRT_GROUPS, B)
    toLandmarks(TSHIRT, movePoint(state, TSHIRT_GROUPS, 'waist.left_x', 1, 1, B, false), TSHIRT_GROUPS)
    expect(TSHIRT).toEqual(copy)
  })

  it('marks every point as loaded for a complete record', () => {
    const { loaded } = fromLandmarks(PANTS, PANTS_GROUPS, B)
    expect(loaded).toHaveLength(PANTS_GROUPS.reduce((n, g) => n + g.points.length, 0))
  })
})

describe('old and empty records', () => {
  it('old pants without crotch.center_x load with x = w / 2 and save it', () => {
    const old = structuredClone(PANTS) as Record<string, any>
    delete old.crotch.center_x
    const { state, loaded } = fromLandmarks(old, PANTS_GROUPS, B)
    expect(state.xs['crotch.center_x']).toBe(240)
    expect(loaded).not.toContain('crotch.center_x')
    const out = toLandmarks(old, state, PANTS_GROUPS) as typeof PANTS
    expect(out.crotch).toEqual({ y: 250, center_x: 240 })
  })

  it('empty landmarks get defaults inside the image', () => {
    const { state, loaded } = fromLandmarks({}, TSHIRT_GROUPS, B)
    expect(loaded).toEqual([])
    for (const x of Object.values(state.xs)) expect(x).toBeGreaterThanOrEqual(0)
    for (const x of Object.values(state.xs)) expect(x).toBeLessThanOrEqual(B.w)
    for (const y of Object.values(state.ys)) expect(y).toBeLessThanOrEqual(B.h)
  })

  it('sides with different y in old data load with their average, then save equal', () => {
    const old = structuredClone(TSHIRT)
    old.sleeve_end.left.y = 280
    old.sleeve_end.right.y = 301
    const { state } = fromLandmarks(old, TSHIRT_GROUPS, B)
    expect(state.ys.sleeve_end).toBe(291)
    const out = toLandmarks(old, state, TSHIRT_GROUPS) as typeof TSHIRT
    expect(out.sleeve_end.left.y).toBe(291)
    expect(out.sleeve_end.right.y).toBe(291)
  })
})

describe('moves', () => {
  const start = () => fromLandmarks(PANTS, PANTS_GROUPS, B).state

  it('moving one point moves the y of its whole group (all yPaths saved equal)', () => {
    const s = movePoint(start(), PANTS_GROUPS, 'knee.left_leg.left_x', 85, 430, B, false)
    const out = toLandmarks(PANTS, s, PANTS_GROUPS) as typeof PANTS
    expect(out.knee.y).toBe(430)
    expect(out.knee.left_leg.y).toBe(430)
    expect(out.knee.right_leg.y).toBe(430)
    expect(out.knee.left_leg.left_x).toBe(85)
    expect(out.knee.right_leg.right_x).toBe(400) // no symmetry: the mirror stays
  })

  it('clamps to the image bounds and rounds to whole pixels', () => {
    const s = movePoint(start(), PANTS_GROUPS, 'hip.left_x', -50.4, 9999, B, false)
    expect(s.xs['hip.left_x']).toBe(0)
    expect(s.ys.hip).toBe(B.h)
    const t = movePoint(start(), PANTS_GROUPS, 'hip.right_x', 300.6, 100.2, B, false)
    expect(t.xs['hip.right_x']).toBe(301)
    expect(t.ys.hip).toBe(100)
  })

  it('symmetry mirrors x around w / 2', () => {
    const s = movePoint(start(), PANTS_GROUPS, 'hip.left_x', 100, 160, B, true)
    expect(s.xs['hip.right_x']).toBe(380)
    const legs = movePoint(start(), PANTS_GROUPS, 'hem.left_leg.right_x', 200, 610, B, true)
    expect(legs.xs['hem.right_leg.left_x']).toBe(280)
  })

  it('symmetry snaps center points to the axis', () => {
    const s = movePoint(start(), PANTS_GROUPS, 'crotch.center_x', 300, 255, B, true)
    expect(s.xs['crotch.center_x']).toBe(240)
    expect(s.ys.crotch).toBe(255)
    const snapped = snapCenters({ ...start(), xs: { ...start().xs, 'waist.center_x': 251 } }, PANTS_GROUPS, B)
    expect(snapped.xs['waist.center_x']).toBe(240)
  })

  it('nudge moves by the step and stays clamped', () => {
    const s = nudgePoint(start(), PANTS_GROUPS, 'waist.left_x', 5, -1, B, false)
    expect(s.xs['waist.left_x']).toBe(125)
    expect(s.ys.waist).toBe(29)
    let t = start()
    for (let i = 0; i < 10; i++) t = nudgePoint(t, PANTS_GROUPS, 'waist.left_x', 0, -5, B, false)
    expect(t.ys.waist).toBe(0)
  })

  it('unknown point id is a no-op', () => {
    const s = start()
    expect(movePoint(s, PANTS_GROUPS, 'nope', 1, 1, B, false)).toBe(s)
  })
})
