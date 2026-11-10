import { describe, expect, it } from 'vitest'
import { MIN_GAP, fromLandmarks, movePoint, toLandmarks } from './geometry'
import { BODY_GROUPS, BODY_RULES } from './bodyGroups'

const B = { w: 600, h: 1200 }

// Same figure as backend apps/avatars/tests_staff.full_landmarks().
const BODY = {
  head_top: { y: 60, left_x: 280, right_x: 320 },
  neck: { y: 220, left_x: 270, right_x: 330 },
  shoulder: { y: 260, left_x: 200, right_x: 400 },
  armpit: { y: 345, left_x: 215, right_x: 385 },
  chest: { y: 380, left_x: 210, right_x: 390, width: 180 },
  waist: { y: 480, left_x: 220, right_x: 380 },
  hip: { y: 640, left_x: 205, right_x: 395 },
  crotch: { y: 670, left_x: 205, center_x: 300, right_x: 395 },
  knee: { y: 860, left_leg: { left_x: 218, right_x: 287, y: 860 }, right_leg: { left_x: 313, right_x: 383, y: 860 } },
  ankle: { left_leg: { y: 1040, left_x: 230, right_x: 275 }, right_leg: { y: 1040, left_x: 325, right_x: 370 } },
  foot_bottom: { y: 1150, left_x: 230, right_x: 370 },
}

describe('body groups', () => {
  it('has the eleven lines of docs/03 and every line has left and right edge points', () => {
    expect(BODY_GROUPS.map((g) => g.id)).toEqual([
      'head_top', 'neck', 'shoulder', 'armpit', 'chest', 'waist', 'hip', 'crotch', 'knee', 'ankle', 'foot_bottom',
    ])
    for (const g of BODY_GROUPS) {
      expect(g.points.some((p) => p.side === 'left'), g.id).toBe(true)
      expect(g.points.some((p) => p.side === 'right'), g.id).toBe(true)
    }
  })

  it('loads every point from a full record and round-trips it unchanged', () => {
    const { state, loaded } = fromLandmarks(BODY, BODY_GROUPS, B)
    expect(loaded.length).toBe(BODY_GROUPS.reduce((n, g) => n + g.points.length, 0))
    expect(toLandmarks(BODY, state, BODY_GROUPS)).toEqual(BODY)
  })

  it('a line stops at its neighbour; armpit may reach the chest line', () => {
    const { state } = fromLandmarks(BODY, BODY_GROUPS, B)
    const hip = movePoint(state, BODY_GROUPS, 'hip.left_x', 205, 400, B, false, BODY_RULES)
    expect(hip.ys.hip).toBe(480 + MIN_GAP)
    const armpit = movePoint(state, BODY_GROUPS, 'armpit.left_x', 215, 500, B, false, BODY_RULES)
    expect(armpit.ys.armpit).toBe(380)
    const knee = movePoint(state, BODY_GROUPS, 'knee.left_leg.right_x', 400, 860, B, false, BODY_RULES)
    expect(knee.xs['knee.left_leg.right_x']).toBe(313 - MIN_GAP)
  })
})
