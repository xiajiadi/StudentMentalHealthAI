/* global ImageBitmap */

type ChartWord = {
  text: string
  confidence: number
  bbox: { x0: number; x1: number; y0: number; y1: number }
}
type Bar = { left: number; right: number; top: number; bottom: number }
type BarChart = { bars: Bar[]; scale: number; axisWidth: number }

function findBars(pixels: Uint8ClampedArray, width: number, height: number): Bar[] {
  const marked = new Uint8Array(width * height)
  for (let i = 0; i < marked.length; i += 1) {
    const offset = i * 4
    const red = pixels[offset], green = pixels[offset + 1], blue = pixels[offset + 2]
    if (pixels[offset + 3] > 200 && Math.max(red, green, blue) - Math.min(red, green, blue) >= 45) {
      marked[i] = 1
    }
  }
  const queue = new Int32Array(marked.length)
  const bars: Bar[] = []
  function enqueue(index: number, end: number) {
    if (!marked[index]) return end
    marked[index] = 0
    queue[end] = index
    return end + 1
  }
  for (let i = 0; i < marked.length; i += 1) {
    if (!marked[i]) continue
    let end = enqueue(i, 0)
    let left = width, right = 0, top = height, bottom = 0
    for (let start = 0; start < end; start += 1) {
      const index = queue[start]
      const x = index % width, y = Math.floor(index / width)
      left = Math.min(left, x)
      right = Math.max(right, x)
      top = Math.min(top, y)
      bottom = Math.max(bottom, y)
      if (x > 0) end = enqueue(index - 1, end)
      if (x + 1 < width) end = enqueue(index + 1, end)
      if (y > 0) end = enqueue(index - width, end)
      if (y + 1 < height) end = enqueue(index + width, end)
    }
    const boxWidth = right - left + 1, boxHeight = bottom - top + 1
    if (boxWidth >= 12 && boxHeight >= Math.max(8, height * 0.025)
      && end >= boxWidth * boxHeight * 0.92) bars.push({ left, right, top, bottom })
  }
  return bars.sort((a, b) => a.left - b.left)
}

const tickPattern = /^\d{1,9}(?:\.\d{1,4})?%?$/

export function detectWorkspaceBarChart(bitmap: ImageBitmap, words: ChartWord[]): BarChart | undefined {
  const numericWords = words.filter((word) => tickPattern.test(word.text.trim()))
  if (numericWords.length < 2) return
  const scale = Math.min(1, 1200 / Math.max(bitmap.width, bitmap.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(bitmap.width * scale))
  canvas.height = Math.max(1, Math.round(bitmap.height * scale))
  const context = canvas.getContext('2d', { willReadFrequently: true })
  if (!context) return
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  const { data } = context.getImageData(0, 0, canvas.width, canvas.height)
  const bars = findBars(data, canvas.width, canvas.height)
  if (bars.length < 2 || bars.length > 20) return
  const baseline = bars[0].bottom
  const widths = bars.map(({ left, right }) => right - left + 1)
  if (Math.max(...widths) > Math.min(...widths) * 1.35
    || bars.some((bar, index) => Math.abs(bar.bottom - baseline) > 4 || (index > 0 && bar.left <= bars[index - 1].right))) return
  const plotLeft = Math.floor(bars[0].left / scale)
  const leftTicks = numericWords.filter(({ bbox }) => bbox.x1 < plotLeft)
  if (leftTicks.length < 2) return
  const farthestTick = Math.max(...leftTicks.map(({ bbox }) => bbox.x1))
  return { bars, scale, axisWidth: Math.min(plotLeft, farthestTick + Math.round(12 / scale)) }
}

function locateWords(words: ChartWord[], scale: number) {
  return words.filter((word) => word.confidence >= 50).map(({ text, bbox }) => ({
    text: text.trim(), x: (bbox.x0 + bbox.x1) * scale / 2,
    y: (bbox.y0 + bbox.y1) * scale / 2, right: bbox.x1 * scale,
  }))
}

export function readWorkspaceBarChart(chart: BarChart, words: ChartWord[], axisWords = words): string | undefined {
  const { bars, scale } = chart
  const baseline = bars[0].bottom
  const labels = locateWords(words, scale)
  const ticks = locateWords(axisWords, scale).filter((word) => word.right < bars[0].left && tickPattern.test(word.text))
    .map((word) => ({ ...word, value: Number.parseFloat(word.text), percent: word.text.endsWith('%') }))
  const zero = ticks.find((tick) => tick.value === 0 && Math.abs(tick.y - baseline) <= 8)
  if (!zero) return
  const axis = ticks.filter((tick) => tick.percent === zero.percent && tick.y <= zero.y + 1
    && Math.abs(tick.right - zero.right) <= 12).sort((a, b) => a.y - b.y)
  if (axis.length < 3 || axis.at(-1) !== zero) return

  const highest = axis[0]
  const range = zero.y - highest.y
  if (range < 40 || highest.value === 0 || bars.some((bar) => bar.top < highest.y - 4)) return
  const unitsPerPixel = highest.value / range
  if (axis.some((tick, index) => (index > 0 && tick.value >= axis[index - 1].value)
    || Math.abs(zero.y - tick.y - tick.value / unitsPerPixel) > 5)) return

  const precision = Math.max(0, Math.min(2, Math.ceil(-Math.log10(unitsPerPixel))))
  const format = new Intl.NumberFormat('en-US', { useGrouping: false, maximumFractionDigits: precision })
  const output = bars.map((bar, index) => {
    const center = (bar.left + bar.right) / 2
    const label = labels.filter((word) => Math.abs(word.x - center) <= (bar.right - bar.left + 1) / 2
      && word.y > baseline + 3 && word.y < baseline + Math.max(25, range * 0.16))
      .sort((a, b) => a.x - b.x).map((word) => word.text).join(' ')
    const value = format.format((baseline - bar.top + 1) * unitsPerPixel)
    return `第 ${index + 1} 根${label ? `（${label}）` : ''}约 ${value}${zero.percent ? '%' : ''}`
  })
  return ['柱状图读数（按刻度和柱高估算）', ...output].join('\n')
}
