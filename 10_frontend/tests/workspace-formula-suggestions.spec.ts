import { describe, expect, it } from 'vitest'
import type { ChartWord } from '@/services/workspace-image-chart'
import { suggestWorksheetFormulaRegions } from '@/services/workspace-formula-suggestions'

function worksheet() {
  const width = 520, height = 530
  const data = new Uint8ClampedArray(width * height * 4).fill(255)
  const raster = { width, height, data, scale: 1 }
  function ink(left: number, top: number, columns: number, rows: number) {
    for (let y = top; y < top + rows; y += 1) {
      for (let x = left; x < left + columns; x += 1) data.set([20, 25, 31, 255], (y * width + x) * 4)
    }
  }
  function fractions(top: number) {
    for (const left of [145, 310]) {
      ink(left, top + 44, 70, 4)
      ink(left + 15, top + 8, 5, 27)
      ink(left + 15, top + 19, 28, 4)
      ink(left + 19, top + 61, 5, 29)
      ink(left + 20, top + 82, 31, 4)
    }
  }
  return { raster, ink, fractions }
}

function word(text: string, x: number, y: number, width = 20): ChartWord {
  return { text, confidence: 95, bbox: { x0: x, x1: x + width, y0: y, y1: y + 20 } }
}

describe('local worksheet formula suggestions', () => {
  it('separates the two rows of handwritten fractions and excludes a page header', () => {
    const { raster, ink, fractions } = worksheet()
    ink(20, 45, 260, 6)
    fractions(145)
    fractions(345)
    const candidates = suggestWorksheetFormulaRegions(raster, [])
    expect(candidates).toHaveLength(2)
    expect(candidates[0].left).toBeLessThan(145 / 520 * 100)
    expect(candidates[0].right).toBeGreaterThan(380 / 520 * 100)
    expect(candidates[0].top).toBeGreaterThan(20)
    expect(candidates[0].bottom).toBeLessThan(60)
    expect(candidates[1].top).toBeGreaterThan(60)
  })

  it('takes just the OCR equation from a line containing prose and ignores dates', () => {
    const { raster } = worksheet()
    const candidates = suggestWorksheetFormulaRegions(raster, [
      [word('Date', 20, 52), word('11/28/2026', 56, 52, 75)],
      [word('Solve', 40, 145, 50), word('2x', 102, 145), word('+', 126, 145, 10),
        word('7', 141, 145, 10), word('=', 158, 145, 10), word('19', 175, 145)],
      [word('Explain', 35, 202, 80), word('your', 120, 202, 30), word('answer', 156, 202, 55)],
    ])
    expect(candidates).toEqual([{ left: 18.7, right: 38.5, top: 26.4, bottom: 32.1 }])
  })

  it('does not propose an underline without numerator and denominator or a solid dark picture', () => {
    const { raster, ink } = worksheet()
    ink(100, 150, 70, 4)
    ink(108, 120, 20, 10)
    expect(suggestWorksheetFormulaRegions(raster, [])).toEqual([])
    ink(0, 0, raster.width, raster.height)
    expect(suggestWorksheetFormulaRegions(raster, [])).toEqual([])
  })

  it('does not offer duplicate overlapping crops for a fraction read by both methods', () => {
    const { raster, fractions } = worksheet()
    fractions(145)
    const result = suggestWorksheetFormulaRegions(raster, [[word('1/4+1/2', 150, 170, 210)]])
    expect(result).toHaveLength(1)
    expect(result[0].bottom).toBeGreaterThan(42)
  })
})
