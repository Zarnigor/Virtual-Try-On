import { describe, expect, it } from 'vitest'
import { BODY_GROUPS } from './bodyGroups'
import { PANTS_GROUPS, TSHIRT_GROUPS } from './garmentGroups'
import { LINE_HINTS, hintFor } from './lineHints'

describe('line hints', () => {
  it('every body and garment line has a definition', () => {
    for (const g of [...BODY_GROUPS, ...TSHIRT_GROUPS, ...PANTS_GROUPS]) expect(hintFor(g.id), g.id).not.toBe('')
  })

  it('body and garment use the same definition for the same line', () => {
    const shared = ['shoulder', 'chest', 'waist', 'hip', 'crotch', 'knee']
    for (const id of shared) {
      expect(BODY_GROUPS.some((g) => g.id === id)).toBe(true)
      expect([...TSHIRT_GROUPS, ...PANTS_GROUPS].some((g) => g.id === id)).toBe(true)
    }
    expect(LINE_HINTS.hip).toContain('eng keng')
    expect(LINE_HINTS.waist).toContain('eng ingichka')
    expect(LINE_HINTS.chest).toContain('eng toʻla')
    expect(LINE_HINTS.crotch).toContain('oyoqlar ajraladigan')
  })
})
