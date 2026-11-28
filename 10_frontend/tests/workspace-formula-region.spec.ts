import { describe, expect, it } from 'vitest'
import { formulaPixelBounds, hasFormulaRegion } from '@/services/workspace-formula-region'

describe('worksheet formula crop', () => {
  it('uses the original image dimensions and rounds inside the selected region', () => {
    expect(formulaPixelBounds(520, 530, { left: 19.2, top: 27.3, right: 81.2, bottom: 58.4 }))
      .toEqual({ left: 100, top: 145, width: 322, height: 164 })
    expect(formulaPixelBounds(201, 203, { left: 10, top: 10, right: 90, bottom: 90 }))
      .toEqual({ left: 21, top: 21, width: 159, height: 161 })
  })

  it('keeps the dimensions of a separately cropped single formula', () => {
    expect(formulaPixelBounds(322, 164)).toEqual({ left: 0, top: 0, width: 322, height: 164 })
  })

  it.each([
    { left: 50, top: 10, right: 49, bottom: 90 },
    { left: 0, top: 0, right: 100, bottom: 1 },
    { left: -1, top: 10, right: 90, bottom: 90 },
    { left: 0, top: 0, right: 101, bottom: 90 },
    { left: 0, top: 0, right: 100, bottom: NaN },
  ])('rejects a selection with unusable edges %o', (region) => {
    expect(hasFormulaRegion(region)).toBe(false)
    expect(() => formulaPixelBounds(520, 530, region)).toThrow('请框选一整道公式')
  })

  it('rejects a selection too small to contain an isolated formula at the source resolution', () => {
    expect(() => formulaPixelBounds(70, 60, { left: 0, top: 0, right: 2, bottom: 2 }))
      .toThrow('选区太小')
  })
})
