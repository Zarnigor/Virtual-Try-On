import { describe, expect, it } from 'vitest'
import { circumferenceFromWidth, ellipsePerimeter, estimateCircumferences, figurePx, widthCm } from './bodyMeasure'

const LM = {
  head_top: { y: 50, left_x: 290, right_x: 310 },
  foot_bottom: { y: 1150, left_x: 230, right_x: 370 },
  shoulder: { y: 260, left_x: 190, right_x: 410 }, // 220 px
  chest: { y: 380, left_x: 210, right_x: 390 },
  waist: { y: 480, left_x: 225, right_x: 375 },
  hip: { y: 640, left_x: 205, right_x: 395 },
  knee: { y: 860, left_leg: { left_x: 218, right_x: 287 }, right_leg: { left_x: 313, right_x: 383 } },
}

describe('body measurements', () => {
  it('width in cm = px width x height / figure px', () => {
    expect(figurePx(LM)).toBe(1100)
    expect(widthCm(LM, 176, 'shoulder')).toBeCloseTo(220 * 176 / 1100, 6) // 35.2 cm
    expect(widthCm(LM, 176, 'knee', 'left_leg')).toBeCloseTo(69 * 0.16, 6)
  })

  it('missing data or height gives undefined', () => {
    expect(widthCm(LM, 0, 'chest')).toBeUndefined()
    expect(widthCm(LM, 170, 'neck')).toBeUndefined()
    expect(widthCm({ ...LM, foot_bottom: { y: 40 } }, 170, 'chest')).toBeUndefined()
  })

  it('ellipse perimeter: a circle is pi x d, depth 0.6 x width matches Ramanujan', () => {
    expect(ellipsePerimeter(10, 10)).toBeCloseTo(Math.PI * 10, 9)
    // a = 15, b = 9: pi (3*24 - sqrt(54 * 42)) = 77.07...
    expect(circumferenceFromWidth(30)).toBeCloseTo(Math.PI * (72 - Math.sqrt(54 * 42)), 9)
    expect(circumferenceFromWidth(30)).toBeGreaterThan(75)
  })

  it('estimates the four circumferences rounded to 0.5 cm', () => {
    const est = estimateCircumferences(LM, 176)
    expect(Object.keys(est)).toEqual(['shoulder', 'chest', 'waist', 'hip'])
    expect(est.shoulder).toBe(Math.round(circumferenceFromWidth(35.2) * 2) / 2)
    for (const v of Object.values(est)) expect(v! * 2).toBe(Math.round(v! * 2))
    expect(estimateCircumferences(LM, 0)).toEqual({})
  })
})
