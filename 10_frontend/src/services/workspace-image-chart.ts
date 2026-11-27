/* global ImageBitmap */

export type ChartWord = {
  text: string
  confidence: number
  bbox: { x0: number; x1: number; y0: number; y1: number }
}
type Bar = { left: number; right: number; top: number; bottom: number }
type BarChart = { bars: Bar[]; scale: number; axisWidth: number }
type ChartRaster = { data: Uint8ClampedArray; width: number; height: number; scale: number }

function isColored(data: Uint8ClampedArray, offset: number) {
  const red = data[offset], green = data[offset + 1], blue = data[offset + 2]
  return data[offset + 3] > 200 && Math.max(red, green, blue) - Math.min(red, green, blue) >= 45
}

export function workspaceChartRaster(bitmap: ImageBitmap, words: ChartWord[]): ChartRaster | undefined {
  if (words.filter((word) => linearTickPattern.test(word.text.trim())).length < 2) return
  const scale = Math.min(1, 1200 / Math.max(bitmap.width, bitmap.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(bitmap.width * scale))
  canvas.height = Math.max(1, Math.round(bitmap.height * scale))
  const context = canvas.getContext('2d', { willReadFrequently: true })
  if (!context) return
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  const { data } = context.getImageData(0, 0, canvas.width, canvas.height)
  return { data, width: canvas.width, height: canvas.height, scale }
}

function findBars(pixels: Uint8ClampedArray, width: number, height: number): Bar[] {
  const marked = new Uint8Array(width * height)
  for (let i = 0; i < marked.length; i += 1) {
    if (isColored(pixels, i * 4)) marked[i] = 1
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

export function detectWorkspaceBarChart(raster: ChartRaster, words: ChartWord[]): BarChart | undefined {
  const numericWords = words.filter((word) => tickPattern.test(word.text.trim()))
  if (numericWords.length < 2) return
  const { data, width, height, scale } = raster
  const bars = findBars(data, width, height)
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
    y: (bbox.y0 + bbox.y1) * scale / 2, left: bbox.x0 * scale, right: bbox.x1 * scale,
  }))
}

const linearTickPattern = /^[−+-]?(?:\d{1,9}|\d{1,3}(?:,\d{3}){1,2})(?:\.\d{1,4})?%?$/
type LocatedWord = ReturnType<typeof locateWords>[number]

function lineAxis(words: LocatedWord[], width: number) {
  const ticks = words.filter((word) => word.right < width * 0.37 && linearTickPattern.test(word.text))
    .map((word) => ({
      ...word,
      value: Number.parseFloat(word.text.replaceAll(',', '').replace('−', '-')),
      percent: word.text.endsWith('%'),
    }))
  // Numeric Y labels share a right edge. Reject ambiguous columns instead of choosing a scale.
  const groups: (typeof ticks)[] = []
  for (const tick of ticks.sort((a, b) => b.right - a.right)) {
    const group = groups.at(-1)
    if (group && group[0].right - tick.right <= 12) group.push(tick)
    else groups.push([tick])
  }
  const axes = groups.filter((group) => group.length >= 3).flatMap((group) => {
    const right = group[0].right
    group.sort((a, b) => a.y - b.y)
    const highest = group[0], lowest = group[group.length - 1]
    const range = lowest.y - highest.y
    const unitsPerPixel = (highest.value - lowest.value) / range
    if (range < 45 || unitsPerPixel <= 0 || group.some((tick, index) => (
      tick.percent !== lowest.percent
      || (index > 0 && (tick.y - group[index - 1].y < 10 || tick.value >= group[index - 1].value))
      || Math.abs(lowest.y - tick.y - (tick.value - lowest.value) / unitsPerPixel) > 4
    ))) return []
    return [{ highest, lowest, unitsPerPixel, right }]
  })
  return axes.length === 1 ? axes[0] : undefined
}

function lineLabels(words: LocatedWord[], axisRight: number, bottom: number, height: number) {
  const below = words.filter((word) => word.x > axisRight + 12
    && word.y > bottom + 8 && word.y < bottom + height * 0.14 && /[\p{L}\p{N}]/u.test(word.text))
  const first = Math.min(...below.map((word) => word.y))
  const row = below.filter((word) => word.y <= first + 8).sort((a, b) => a.left - b.left)
  const labels: LocatedWord[] = []
  for (const word of row) {
    const previous = labels.at(-1)
    if (previous && word.left - previous.right <= 9) {
      previous.text += ` ${word.text}`
      previous.right = Math.max(previous.right, word.right)
      previous.x = (previous.left + previous.right) / 2
    } else {
      labels.push({ ...word })
    }
  }
  return labels
}

export function readWorkspaceLineChart(raster: ChartRaster, words: ChartWord[]): string | undefined {
  const { data, width, height, scale } = raster
  const positioned = locateWords(words, scale)
  const axis = lineAxis(positioned, width)
  if (!axis) return
  const { highest, lowest, unitsPerPixel } = axis
  const labels = lineLabels(positioned, axis.right, lowest.y, height)
  if (labels.length < 3 || labels.length > 20) return
  const left = Math.round(labels[0].x), right = Math.round(labels[labels.length - 1].x)
  if (right - left < width * 0.25 || left < 0 || right >= width) return

  const top = Math.max(0, Math.floor(highest.y - 7))
  const bottom = Math.min(height - 1, Math.ceil(lowest.y + 7))
  const centers = new Map<number, number>()
  const maxStrokeHeight = Math.max(16, (bottom - top) * 0.07)
  let gap = 0
  for (let x = left; x <= right; x += 1) {
    let first = -1, last = -1, coloredPixels = 0
    for (let y = top; y <= bottom; y += 1) {
      if (!isColored(data, (y * width + x) * 4)) continue
      if (first < 0) first = y
      last = y
      coloredPixels += 1
    }
    if (first < 0) {
      // A few edge pixels may be missing when a label is slightly wider on one side.
      gap += 1
      if (gap > 3) return
      continue
    }
    if (last - first > maxStrokeHeight || last - first + 1 - coloredPixels > 2
      || first === top || last === bottom) return
    gap = 0
    centers.set(x, (first + last) / 2)
  }
  const precision = Math.max(0, Math.min(2, Math.ceil(-Math.log10(unitsPerPixel))))
  const format = new Intl.NumberFormat('en-US', { useGrouping: false, maximumFractionDigits: precision })
  const output = []
  for (const label of labels) {
    const x = Math.round(label.x)
    const y = centers.get(x) ?? centers.get(x - 1) ?? centers.get(x + 1)
      ?? centers.get(x - 2) ?? centers.get(x + 2)
    if (y === undefined) return
    const value = lowest.value + (lowest.y - y) * unitsPerPixel
    output.push(`${label.text} 约 ${format.format(value)}${lowest.percent ? '%' : ''}`)
  }
  return ['折线图读数（按刻度和识别到的彩色线估算）', ...output].join('\n')
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
