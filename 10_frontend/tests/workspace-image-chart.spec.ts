import { describe, expect, it } from 'vitest'
import { readWorkspaceLineChart, type ChartWord } from '@/services/workspace-image-chart'

function word(text: string, x: number, y: number, width = 28): ChartWord {
  return {
    text, confidence: 95,
    bbox: { x0: x, x1: x + width, y0: y - 6, y1: y + 6 },
  }
}

function fixture(ticks: string[]) {
  const width = 480
  const height = 330
  const raster = { data: new Uint8ClampedArray(width * height * 4), width, height, scale: 1 }
  const words = ticks.map((tick, index) => word(tick, 10, 30 + index * 80))
  const points = [{ x: 90, y: 210 }, { x: 240, y: 110 }, { x: 390, y: 70 }]
  points.forEach(({ x }, index) => words.push(word(['April', 'May', 'June'][index], x - 18, 299, 36)))
  for (let index = 1; index < points.length; index += 1) {
    const first = points[index - 1], last = points[index]
    for (let x = first.x; x <= last.x; x += 1) {
      const y = Math.round(first.y + (last.y - first.y) * (x - first.x) / (last.x - first.x))
      raster.data.set([25, 90, 200, 255], (y * width + x) * 4)
    }
  }
  return { raster, words }
}

describe('workspace line chart estimates', () => {
  it('calibrates a signed axis and returns only values at recognised labels', () => {
    const { raster, words } = fixture(['30', '10', '−10', '-30'])
    expect(readWorkspaceLineChart(raster, words)?.split('\n').slice(1))
      .toEqual(['April 约 -15', 'May 约 10', 'June 约 20'])
  })

  it('leaves a non-linear set of ticks as text', () => {
    const { raster, words } = fixture(['100', '10', '1', '0.1'])
    expect(readWorkspaceLineChart(raster, words)).toBeUndefined()
  })

  it('leaves an ambiguous or interrupted drawing as text', () => {
    const { raster, words } = fixture(['30', '10', '-10', '-30'])
    for (let y = 0; y < raster.height; y += 1) {
      for (let x = 166; x <= 178; x += 1) raster.data[(y * raster.width + x) * 4 + 3] = 0
    }
    expect(readWorkspaceLineChart(raster, words)).toBeUndefined()
  })
})
