import { describe, expect, it } from 'vitest'
import { garmentFitsSex } from './garments'

/** Same rule as backend apps/tryon_engine/views.garment_fits_sex (docs/09 #97). */
describe('garment gender vs base sex', () => {
  it('matches, unisex always passes, the other gender does not', () => {
    expect(garmentFitsSex('male', 'male')).toBe(true)
    expect(garmentFitsSex('female', 'female')).toBe(true)
    expect(garmentFitsSex('unisex', 'male')).toBe(true)
    expect(garmentFitsSex('unisex', 'female')).toBe(true)
    expect(garmentFitsSex('female', 'male')).toBe(false)
    expect(garmentFitsSex('male', 'female')).toBe(false)
  })
})
