import { describe, expect, it } from 'vitest'
import { activeRules, fromLandmarks, movePoint, requiredCount, toLandmarks, type Bounds } from './geometry'
import { TSHIRT_GROUPS, TSHIRT_RULES } from './garmentGroups'
import { checkTshirt, missingTshirtGroups } from './garmentChecks'
import { CHECK_MESSAGES, CHECK_WARNINGS, GARMENT_GROUP_NAMES } from '../../locale/uz'

/** Extended T-shirt set (docs/09 #92). Same records as backend apps/garments/tests_landmarks.py. */
const B: Bounds = { w: 480, h: 640 }
const N = GARMENT_GROUP_NAMES.tshirt

const TSHIRT = {
  shoulder: { y: 198, left_x: 124, right_x: 356 },
  chest: { y: 326, left_x: 140, right_x: 340 },
  waist: { y: 416, left_x: 150, right_x: 330 },
  hem: { y: 488, left_x: 142, right_x: 338 },
  sleeve_cuff_outer: { left: { x: 20, y: 270 }, right: { x: 460, y: 270 } },
  sleeve_cuff_inner: { left: { x: 60, y: 310 }, right: { x: 420, y: 310 } },
}
const FULL = {
  ...TSHIRT,
  armpit: { y: 300, left_x: 130, right_x: 350 },
  collar: { y: 190, left_x: 200, right_x: 280 },
  collar_bottom: { x: 240, y: 230 },
}
const LEGACY = {
  shoulder: TSHIRT.shoulder, chest: TSHIRT.chest, waist: TSHIRT.waist, hem: TSHIRT.hem,
  sleeve_end: { left: { x: 20, y: 290 }, right: { x: 460, y: 290 } },
}

type Rec = Record<string, any>
const set = (rec: Rec, path: string, value: unknown): Rec => {
  const out = structuredClone(rec)
  const keys = path.split('.')
  let cur = out
  for (const k of keys.slice(0, -1)) cur = cur[k]
  if (value === undefined) delete cur[keys[keys.length - 1]]
  else cur[keys[keys.length - 1]] = value
  return out
}
const ok = (rec: Rec) => expect(checkTshirt(rec).errors).toEqual([])
const fails = (rec: Rec, msg: string) => expect(checkTshirt(rec).errors).toContain(msg)

describe('groups: names, order and optional points', () => {
  it('lists the set top to bottom with the locale names', () => {
    expect(TSHIRT_GROUPS.map((g) => g.id)).toEqual([
      'collar', 'shoulder', 'collar_bottom', 'armpit', 'sleeve_cuff_outer', 'sleeve_cuff_inner', 'chest', 'waist', 'hem',
    ])
    for (const g of TSHIRT_GROUPS) expect(g.name).toBe(N[g.id as keyof typeof N])
    expect(TSHIRT_GROUPS.filter((g) => g.optional).map((g) => g.id)).toEqual(['collar', 'collar_bottom', 'armpit'])
    expect(TSHIRT_GROUPS.some((g) => g.id === 'sleeve_end')).toBe(false)
  })

  it('Save needs only the required points', () => {
    const { loaded } = fromLandmarks(TSHIRT, TSHIRT_GROUPS, B)
    const r = requiredCount(TSHIRT_GROUPS, new Set(loaded))
    expect(r).toEqual({ placed: 12, total: 12 })
  })

  it('an optional group is saved only when all of its points are placed', () => {
    const { state, loaded } = fromLandmarks(TSHIRT, TSHIRT_GROUPS, B)
    const placed = new Set(loaded)
    expect(toLandmarks(TSHIRT, state, TSHIRT_GROUPS, placed)).toEqual(TSHIRT) // defaults are never saved
    placed.add('armpit.left_x')
    expect(toLandmarks(TSHIRT, state, TSHIRT_GROUPS, placed)).not.toHaveProperty('armpit')
    placed.add('armpit.right_x')
    expect(toLandmarks(TSHIRT, state, TSHIRT_GROUPS, placed)).toHaveProperty('armpit')
    // without `placed`: only what the record had
    expect(toLandmarks(FULL, fromLandmarks(FULL, TSHIRT_GROUPS, B).state, TSHIRT_GROUPS)).toEqual(FULL)
  })

  it('an unplaced optional group does not block moves', () => {
    const { state, loaded } = fromLandmarks(TSHIRT, TSHIRT_GROUPS, B)
    const placed = new Set(loaded)
    const rules = activeRules(TSHIRT_RULES, TSHIRT_GROUPS, placed)
    expect(rules.y.some((r) => r.a === 'armpit' || r.b === 'armpit')).toBe(false)
    // the chest may go up to the shoulder + gap, past the default armpit line
    const s = movePoint(state, TSHIRT_GROUPS, 'chest.left_x', 140, 150, B, false, rules)
    expect(s.ys.chest).toBe(202)
    placed.add('armpit.left_x')
    expect(activeRules(TSHIRT_RULES, TSHIRT_GROUPS, placed).y.some((r) => r.b === 'armpit')).toBe(true)
  })

  it('a legacy record loads its required groups; the cuffs still need placing', () => {
    const { loaded } = fromLandmarks(LEGACY, TSHIRT_GROUPS, B)
    expect(requiredCount(TSHIRT_GROUPS, new Set(loaded))).toEqual({ placed: 8, total: 12 })
  })
})

describe('sanity checks (same rules and messages as the server)', () => {
  it('valid records pass', () => {
    ok(TSHIRT)
    ok(FULL)
  })

  it('collar bottom below the collar edges, between them', () => {
    ok(set(FULL, 'collar_bottom.y', 191))
    fails(set(FULL, 'collar_bottom.y', 190), CHECK_MESSAGES.y_order(N.collar_bottom, N.collar))
    fails(set(FULL, 'collar_bottom.x', 199), CHECK_MESSAGES.center(N.collar_bottom))
  })

  it('armpit below the shoulder; oversized: may be below the chest (docs/09 #94)', () => {
    ok(set(FULL, 'armpit.y', 199))
    fails(set(FULL, 'armpit.y', 198), CHECK_MESSAGES.y_order(N.armpit, N.shoulder))
    ok(set(FULL, 'armpit.y', 326))
    expect(checkTshirt(set(FULL, 'armpit.y', 326)).warnings).toEqual([])
    ok(set(FULL, 'armpit.y', 360)) // never an error: a warning only (#95)
    expect(checkTshirt(set(FULL, 'armpit.y', 360)).warnings).toEqual([CHECK_WARNINGS.chest_above_armpit(N.chest, N.armpit)])
  })

  it('chest < waist < hem', () => {
    ok(set(FULL, 'waist.y', 327))
    fails(set(FULL, 'waist.y', 326), CHECK_MESSAGES.y_order(N.waist, N.chest))
    fails(set(FULL, 'hem.y', 416), CHECK_MESSAGES.y_order(N.hem, N.waist))
  })

  it('cuff corners on their own sleeve, outer and inner not swapped', () => {
    ok(set(FULL, 'sleeve_cuff_inner.left.x', 239))
    fails(set(FULL, 'sleeve_cuff_inner.left.x', 240), CHECK_MESSAGES.cuff_side(N.sleeve_cuff_inner))
    const swapped = set(set(FULL, 'sleeve_cuff_outer.left', { x: 60, y: 310 }), 'sleeve_cuff_inner.left', { x: 20, y: 270 })
    fails(swapped, CHECK_MESSAGES.cuff_order(N.sleeve_cuff_outer))
    fails(set(swapped, 'armpit', undefined), CHECK_MESSAGES.cuff_order(N.sleeve_cuff_outer))
  })

  it('range warnings: collar near the shoulder line, points on the garment', () => {
    expect(checkTshirt(set(FULL, 'collar.y', 198 - 34)).warnings).toEqual([])
    expect(checkTshirt(set(FULL, 'collar.y', 198 - 40)).warnings).toEqual([CHECK_WARNINGS.collar_far(N.collar)])
    expect(checkTshirt(FULL, { x0: 18, y0: 188, x1: 462, y1: 490 }).warnings).toEqual([])
    expect(checkTshirt(FULL, { x0: 40, y0: 188, x1: 462, y1: 490 }).warnings)
      .toEqual([CHECK_WARNINGS.outside_garment(N.sleeve_cuff_outer)])
    expect(checkTshirt(set(FULL, 'collar.y', 150)).errors).toEqual([]) // warnings never block
  })

  it('names the missing new groups for the banner', () => {
    expect(missingTshirtGroups(FULL)).toEqual([])
    expect(missingTshirtGroups(TSHIRT)).toEqual([N.collar, N.collar_bottom, N.armpit])
    expect(missingTshirtGroups(LEGACY)).toEqual([N.collar, N.collar_bottom, N.armpit, N.sleeve_cuff_outer, N.sleeve_cuff_inner])
  })
})
