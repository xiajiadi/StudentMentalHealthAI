import { describe, expect, it } from 'vitest'
import { readWorkspaceLineChart, type ChartWord } from '@/services/workspace-image-chart'

const blue = [25, 90, 200, 255]
const orange = [227, 120, 26, 255]
const months = ['April', 'May', 'June']

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
  const labels = [90, 240, 390]
  labels.forEach((x, index) => words.push(word(months[index], x - 18, 299, 36)))
  function stroke(heights: number[], color: number[]) {
    for (let index = 1; index < labels.length; index += 1) {
      const left = labels[index - 1], right = labels[index]
      const first = heights[index - 1], last = heights[index]
      for (let x = left; x <= right; x += 1) {
        const y = Math.round(first + (last - first) * (x - left) / (right - left))
        raster.data.set(color, (y * width + x) * 4)
      }
    }
  }
  function legend(title: string, x: number, color: number[]) {
    words.push(word(title, x, 11, 46))
    for (let column = x - 28; column < x - 7; column += 1) {
      raster.data.set(color, (11 * width + column) * 4)
    }
  }
  stroke([210, 110, 70], blue)
  return { raster, words, stroke, legend }
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

  it('reads two separate colors, associates their legend labels and follows them through a crossing', () => {
    const { raster, words, stroke, legend } = fixture(['30', '10', '-10', '-30'])
    for (let x = 236; x <= 244; x += 1) {
      for (let y = 90; y <= 140; y += 1) raster.data[(y * raster.width + x) * 4 + 3] = 0
    }
    stroke([100, 110, 150], orange)
    legend('North', 150, blue)
    words.push(word('Campus', 199, 11, 43))
    legend('South', 290, orange)
    const lines = readWorkspaceLineChart(raster, words)?.split('\n').slice(1)
    expect(lines).toHaveLength(8)
    expect(lines?.slice(0, 5)).toEqual([
      '橙线 · South', 'April 约 12.5', 'May 约 10', 'June 约 0', '蓝线 · North Campus',
    ])
    expect(lines?.[5]).toBe('April 约 -15')
    expect(Math.abs(Number(lines?.[6].split('约 ')[1]) - 10)).toBeLessThan(0.3)
    expect(lines?.[7]).toBe('June 约 20')
  })

  it.each([3, 4])('keeps %i series identifiable by color when no legend is available', (count) => {
    const { raster, words, stroke } = fixture(['30', '10', '-10', '-30'])
    stroke([150, 160, 165], orange)
    stroke([243, 230, 220], [30, 155, 78, 255])
    if (count === 4) stroke([40, 48, 60], [114, 40, 180, 255])
    const result = readWorkspaceLineChart(raster, words)?.split('\n').slice(1)
    expect(result?.filter((line) => line.endsWith('线'))).toEqual(['橙线', '绿线', '蓝线', '紫线'].slice(0, count))
    expect(result).toHaveLength(count * 4)
  })

  it('does not silently drop a fifth visible series', () => {
    const { raster, words, stroke } = fixture(['30', '10', '-10', '-30'])
    stroke([150, 160, 165], orange)
    stroke([243, 230, 220], [30, 155, 78, 255])
    stroke([40, 48, 60], [114, 40, 180, 255])
    stroke([252, 256, 260], [220, 40, 60, 255])
    expect(readWorkspaceLineChart(raster, words)).toBeUndefined()
  })

  it('does not estimate when the same hue belongs to two lines', () => {
    const { raster, words, stroke } = fixture(['30', '10', '-10', '-30'])
    stroke([230, 180, 120], blue)
    expect(readWorkspaceLineChart(raster, words)).toBeUndefined()
  })

  it('does not apply the left scale to a chart with a separate right scale', () => {
    const { raster, words, stroke } = fixture(['30', '10', '-10', '-30'])
    stroke([150, 160, 165], orange)
    words.push(word('60%', 430, 30), word('40%', 430, 110), word('20%', 430, 190))
    expect(readWorkspaceLineChart(raster, words)).toBeUndefined()
  })
})
