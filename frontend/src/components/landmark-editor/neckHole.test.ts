import { describe, expect, it } from 'vitest'
import { fromLandmarks, toLandmarks, type Bounds } from './geometry'
import {
  TSHIRT_MAIN_GROUPS, TSHIRT_MAIN_RULES, TSHIRT_NECK_GROUPS, TSHIRT_NECK_RULES, mainGroupsFor, PANTS_GROUPS,
} from './garmentGroups'
import { checkTshirt } from './garmentChecks'
import {
  CURVE_POINTS, deleteVertex, guessNeckShape, insertVertex, moveVertex, neckHoleProblem, neckView, polygonArea,
  selfIntersects, storedPolygon, suggestNeckHole, withNeckHole, type AlphaInfo, type Pt,
} from './neckHole'
import { CHECK_MESSAGES, GARMENT_GROUP_NAMES } from '../../locale/uz'

/** docs/09 #102: two-step T-shirt editor, neckline hole polygon. Same rules as backend landmark_checks.py. */
const B: Bounds = { w: 480, h: 640 }
const N = GARMENT_GROUP_NAMES.tshirt
const MAIN = {
  shoulder: { y: 198, left_x: 124, right_x: 356 },
  armpit: { y: 300, left_x: 130, right_x: 350 },
  chest: { y: 326, left_x: 140, right_x: 340 },
  waist: { y: 416, left_x: 150, right_x: 330 },
  hem: { y: 488, left_x: 142, right_x: 338 },
  sleeve_cuff_outer: { left: { x: 20, y: 270 }, right: { x: 460, y: 270 } },
  sleeve_cuff_inner: { left: { x: 60, y: 310 }, right: { x: 420, y: 310 } },
}
const CREW = { collar: { y: 190, left_x: 200, right_x: 280 }, collar_bottom: { x: 240, y: 214 } } // depth/width 0.3
const VNECK = { collar: { y: 190, left_x: 200, right_x: 280 }, collar_bottom: { x: 240, y: 245 } } // 0.69
const SQUARE = { collar: { y: 190, left_x: 200, right_x: 280 }, collar_bottom: { x: 240, y: 230 } } // 0.5
const HOLE: Pt[] = [[200, 186], [280, 186], [270, 205], [240, 212], [210, 205]]
const FULL = { ...MAIN, ...CREW, neck_hole: { polygon: HOLE } }
// garment: visible 18..462 x 186..490 (h 305), solid area 80 000 px
const ALPHA: AlphaInfo = { bbox: { x0: 18, y0: 186, x1: 462, y1: 490 }, area: 80000 }
const hole = { w: B.w, h: B.h, alpha: ALPHA }

describe('suggested polygon (inset to the band inner edge, closed along the garment top)', () => {
  // collar width 80: inset max(3, round(0.06 x 80)) = 5 -> sides x 205 / 275; garment top y 186
  it('guesses the default shape from collar depth / width', () => {
    expect(guessNeckShape(CREW)).toBe('round') // 0.3
    expect(guessNeckShape(SQUARE)).toBe('square') // 0.5 (#47 square neck: 0.56)
    expect(guessNeckShape(VNECK)).toBe('v') // 0.69 (#40: 0.82)
    expect(guessNeckShape({})).toBe('round')
  })

  it('V: top edge, inner sides, tip 1.5 x inset above collar_bottom', () => {
    expect(suggestNeckHole(VNECK, 'v', 186)).toEqual([[205, 186], [275, 186], [275, 190], [240, 237], [205, 190]])
  })

  it('square: corners at the inner bottom row, side and bottom handles', () => {
    const pts = suggestNeckHole(SQUARE, 'square', 186)!
    expect(pts).toEqual([
      [205, 186], [275, 186], [275, 190], [275, 208], [275, 225], [240, 225], [205, 225], [205, 208], [205, 190],
    ])
    expect(neckHoleProblem(pts, B.w, B.h, ALPHA)).toBeNull()
  })

  it('round: a parabola of CURVE_POINTS points under the top edge', () => {
    const pts = suggestNeckHole(CREW, 'round', 186)!
    expect(pts).toHaveLength(2 + CURVE_POINTS)
    expect(pts.slice(0, 3)).toEqual([[205, 186], [275, 186], [275, 190]])
    expect(pts[pts.length - 1]).toEqual([205, 190])
    expect(Math.max(...pts.map(([, y]) => y))).toBe(209) // collar_bottom 214 - inset 5
    expect(neckHoleProblem(pts, B.w, B.h, ALPHA)).toBeNull()
  })

  it('every shape is valid for every record, and none sits on a collar point', () => {
    for (const rec of [CREW, SQUARE, VNECK]) {
      for (const sh of ['v', 'round', 'square'] as const) {
        const pts = suggestNeckHole(rec, sh, 186)!
        expect(neckHoleProblem(pts, B.w, B.h, ALPHA)).toBeNull()
        const collar = [[200, 190], [280, 190], [240, rec.collar_bottom.y]]
        expect(pts.some(([x, y]) => collar.some(([cx, cy]) => cx === x && cy === y))).toBe(false)
      }
    }
  })

  it('without a usable top it closes along the collar line', () => {
    expect(suggestNeckHole(VNECK, 'v', null)).toEqual([[275, 190], [240, 237], [205, 190]])
    expect(suggestNeckHole(VNECK, 'v', 189)).toEqual([[275, 190], [240, 237], [205, 190]]) // not clearly above
  })

  it('needs all three collar points, in order', () => {
    expect(suggestNeckHole({ collar: CREW.collar }, 'round', 186)).toBeNull()
    expect(suggestNeckHole({ ...CREW, collar_bottom: { x: 240, y: 180 } }, 'round', 186)).toBeNull()
    expect(suggestNeckHole({ ...CREW, collar_bottom: { x: 290, y: 214 } }, 'round', 186)).toBeNull()
  })
})

describe('polygon validation (same rules as the server)', () => {
  const ok = (p: unknown, a: AlphaInfo | null = ALPHA) => expect(neckHoleProblem(p, B.w, B.h, a)).toBeNull()
  const bad = (p: unknown, reason: string, a: AlphaInfo | null = ALPHA) => expect(neckHoleProblem(p, B.w, B.h, a)).toBe(reason)

  it('accepts a valid hole', () => ok(HOLE))
  it('needs 3..64 finite [x, y] points', () => {
    bad([[200, 190], [280, 190]], 'hole_points')
    bad(Array.from({ length: 65 }, (_, i) => [200 + i, 190 + (i % 2)]), 'hole_points')
    bad([[200, 190], [280, 190], [240, Number.NaN]], 'hole_points')
    bad([[200, 190], [280, 190], [240]], 'hole_points')
    bad('x', 'hole_points')
  })
  it('keeps every point inside the image', () => bad([[200, 190], [481, 190], [240, 210]], 'bounds'))
  it('rejects a self-intersection and a repeated vertex', () => {
    bad([[200, 190], [280, 210], [280, 190], [200, 210]], 'hole_self') // bow tie
    bad([[200, 190], [280, 190], [240, 210], [280, 190]], 'hole_self')
    expect(selfIntersects(HOLE)).toBe(false)
  })
  it('rejects an empty area', () => bad([[200, 190], [240, 190], [280, 190]], 'hole_empty'))
  it('caps the area at 25 % of the solid alpha', () => {
    const big: Pt[] = [[100, 190], [380, 190], [380, 300], [100, 300]] // 30 800 px
    expect(polygonArea(big)).toBe(30800)
    bad(big, 'hole_area')
    ok(big, { ...ALPHA, area: 130000 })
  })
  it('keeps every vertex in the top 40 % of the alpha bbox, up to 3 px above it', () => {
    // top = 186 + 0.4 * 305 = 308
    ok([[200, 183], [280, 183], [240, 308]])
    bad([[200, 182], [280, 183], [240, 300]], 'hole_top')
    bad([[200, 190], [280, 190], [240, 309]], 'hole_top')
  })
  it('client check reports the Uzbek message naming the group (step 2 only)', () => {
    const rec = { ...FULL, neck_hole: { polygon: [[200, 190], [280, 210], [280, 190], [200, 210]] } }
    expect(checkTshirt(rec, ALPHA.bbox, 'neck', hole).errors).toEqual([CHECK_MESSAGES.hole_self(N.neck_hole)])
    expect(checkTshirt(rec, ALPHA.bbox, 'main', hole).errors).toEqual([])
    expect(checkTshirt(FULL, ALPHA.bbox, 'neck', hole).errors).toEqual([])
  })
})

describe('two steps (docs/09 #102)', () => {
  it('step 1 has no collar group or collar rule; step 2 has exactly the collar ones', () => {
    expect(TSHIRT_MAIN_GROUPS.map((g) => g.id)).not.toContain('collar')
    expect(TSHIRT_MAIN_GROUPS.map((g) => g.id)).not.toContain('collar_bottom')
    expect(TSHIRT_NECK_GROUPS.map((g) => g.id)).toEqual(['collar', 'collar_bottom'])
    expect(TSHIRT_NECK_GROUPS.every((g) => !g.optional)).toBe(true)
    const all = [...TSHIRT_MAIN_RULES.x, ...TSHIRT_MAIN_RULES.y].flatMap((r) => [r.a, r.b])
    expect(all.some((id) => id.startsWith('collar'))).toBe(false)
    expect(TSHIRT_NECK_RULES.x).toHaveLength(3)
    expect(TSHIRT_NECK_RULES.y).toEqual([{ a: 'collar', b: 'collar_bottom', gap: 4 }])
    expect(mainGroupsFor('pants')).toBe(PANTS_GROUPS)
  })

  it('step 1 checks ignore a broken collar (not editable there)', () => {
    const rec = { ...MAIN, collar: { y: 190, left_x: 280, right_x: 200 } }
    expect(checkTshirt(rec, null, 'main').errors).toEqual([])
    expect(checkTshirt(rec, null, 'neck').errors).toEqual([CHECK_MESSAGES.x_order(N.collar)])
  })

  it('step 1 round trip keeps collar, collar_bottom and neck_hole untouched', () => {
    const { state, loaded } = fromLandmarks(FULL, TSHIRT_MAIN_GROUPS, B)
    const out = toLandmarks(FULL, state, TSHIRT_MAIN_GROUPS, new Set(loaded))
    expect(out).toEqual(FULL)
    expect(out.neck_hole).toEqual({ polygon: HOLE })
  })

  it('step 2 writes the collar points and the polygon and keeps the main set', () => {
    const { state, loaded } = fromLandmarks(FULL, TSHIRT_NECK_GROUPS, B)
    const base = toLandmarks(FULL, { ...state, ys: { ...state.ys, collar_bottom: 220 } }, TSHIRT_NECK_GROUPS, new Set(loaded))
    const poly: Pt[] = [[200, 186], [280, 186], [240, 220]]
    const out = withNeckHole(base, poly)
    expect(out).toEqual({ ...FULL, collar_bottom: { x: 240, y: 220 }, neck_hole: { polygon: poly } })
    expect(storedPolygon(out)).toEqual(poly)
    expect(storedPolygon(MAIN)).toBeNull()
    expect(withNeckHole(MAIN, null)).toBe(MAIN)
  })
})

describe('polygon editing', () => {
  const tri: Pt[] = [[0, 0], [10, 0], [5, 8]]
  it('inserts after an edge, deletes down to 3, moves inside the image', () => {
    expect(insertVertex(tri, 0, [5.4, -0.2])).toEqual([[0, 0], [5, -0], [10, 0], [5, 8]])
    expect(deleteVertex(insertVertex(tri, 1, [8, 4]), 2)).toEqual(tri)
    expect(deleteVertex(tri, 0)).toBe(tri) // never below 3
    expect(moveVertex(tri, 2, [600, -4], B.w, B.h)).toEqual([[0, 0], [10, 0], [480, 0]])
  })
  it('zooms to the top centre of the garment', () => {
    expect(neckView(480, 640, ALPHA.bbox)).toEqual({ x: 85, y: 171, w: 312, h: 153 }) // 0.7 x 445 = 311.5 -> 312
  })
})
