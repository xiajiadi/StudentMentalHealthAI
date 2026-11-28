/* global ImageBitmap */

export type ChartWord = {
  text: string
  confidence: number
  bbox: { x0: number; x1: number; y0: number; y1: number }
}
type Bar = { left: number; right: number; top: number; bottom: number }
type BarSegment = { top: number; bottom: number; hue: number }
type BarChart = { bars: Bar[]; raster: ChartRaster; axisWidth: number } & (
  { kind: 'bar' } | { kind: 'stacked-bar'; stacks: BarSegment[][] }
)
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
  const candidates = findBars(data, width, height)
  if (!candidates.length) return
  const baseline = Math.max(...candidates.map((bar) => bar.bottom))
  const bars = candidates.filter((bar) => baseline - bar.bottom <= 4)
  if (bars.length < 2 || bars.length > 20) return
  const widths = bars.map(({ left, right }) => right - left + 1)
  if (Math.max(...widths) > Math.min(...widths) * 1.35
    || bars.some((bar, index) => index > 0 && bar.left <= bars[index - 1].right)) return
  const plotLeft = Math.floor(bars[0].left / scale)
  const leftTicks = numericWords.filter(({ bbox }) => bbox.x1 < plotLeft)
  if (leftTicks.length < 2) return
  const farthestTick = Math.max(...leftTicks.map(({ bbox }) => bbox.x1))
  const plotTop = Math.min(...leftTicks.map(({ bbox }) => (bbox.y0 + bbox.y1) * scale / 2))
  // Small legend swatches above the scale are not observations. An unrelated
  // rectangle within the plotting region makes the interpretation ambiguous.
  if (candidates.some((bar) => baseline - bar.bottom > 4 && (
    bar.bottom >= plotTop - 4 || bar.right - bar.left + 1 > Math.min(...widths) / 2
  ))) return
  const axisWidth = Math.min(plotLeft, farthestTick + Math.round(12 / scale))
  const stacks: BarSegment[][] = []
  for (const bar of bars) {
    const segments = barSegments(raster, bar)
    if (!segments) return
    stacks.push(segments)
  }
  const reference = stacks[0]
  if (stacks.every((segments) => segments.length === 1)) return { kind: 'bar', bars, raster, axisWidth }
  if (reference.length < 2 || stacks.some((segments) => segments.length !== reference.length
    || segments.some((segment, index) => hueDistance(segment.hue, reference[index].hue) > 2))) return
  return { kind: 'stacked-bar', bars, raster, axisWidth, stacks }
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

const hueBins = 36

function pixelHue(data: Uint8ClampedArray, offset: number) {
  if (!isColored(data, offset)) return -1
  const red = data[offset], green = data[offset + 1], blue = data[offset + 2]
  const peak = Math.max(red, green, blue)
  const range = peak - Math.min(red, green, blue)
  const sector = peak === red ? (green - blue) / range
    : peak === green ? 2 + (blue - red) / range : 4 + (red - green) / range
  return (Math.round(sector * 6) + hueBins) % hueBins
}

function hueDistance(a: number, b: number) {
  const difference = Math.abs(a - b)
  return Math.min(difference, hueBins - difference)
}

function barSegments({ data, width, height }: ChartRaster, bar: Bar): BarSegment[] | undefined {
  const samples = [0.2, 0.35, 0.5, 0.65, 0.8].map((position) =>
    Math.round(bar.left + (bar.right - bar.left) * position))
  const segments: BarSegment[] = []
  for (let y = bar.bottom; y >= bar.top; y -= 1) {
    const row = samples.map((x) => pixelHue(data, (y * width + x) * 4)).filter((hue) => hue >= 0)
    const hue = row.find((candidate) => row.filter((entry) => hueDistance(entry, candidate) <= 1).length >= 4)
    if (hue === undefined) return
    const current = segments.at(-1)
    if (current && hueDistance(current.hue, hue) <= 2) {
      current.top = y
      continue
    }
    if (segments.length === 4 || segments.some((segment) => hueDistance(segment.hue, hue) < 5)) return
    segments.push({ top: y, bottom: y, hue })
  }
  const minimumHeight = Math.max(6, height * 0.012)
  if (segments.some((segment) => segment.bottom - segment.top + 1 < minimumHeight)) return
  return segments
}

type Plot = { left: number; right: number; top: number; bottom: number }

function plotTracks({ data, width }: ChartRaster, { left, right, top, bottom }: Plot) {
  const columns = right - left + 1
  const height = bottom - top + 1
  const pixels = new Int8Array(height * columns).fill(-1)
  const histogram = new Uint32Array(hueBins)
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < columns; x += 1) {
      const hue = pixelHue(data, ((top + y) * width + left + x) * 4)
      pixels[y * columns + x] = hue
      if (hue >= 0) histogram[hue] += 1
    }
  }
  // Antialiased stroke edges may spill into adjacent bins.
  const peaks: number[] = []
  const candidates = Array.from(histogram, (count, hue) => ({ count, hue }))
    .sort((a, b) => b.count - a.count)
  for (const { hue, count } of candidates) {
    if (count < columns * 0.5) break
    if (peaks.every((peak) => hueDistance(peak, hue) > 3)) peaks.push(hue)
  }
  if (!peaks.length || peaks.length > 4) return
  const groups = Array.from(histogram, (_, hue) => {
    const nearest = peaks.reduce((best, peak) =>
      hueDistance(peak, hue) < hueDistance(best, hue) ? peak : best)
    return hueDistance(nearest, hue) <= 2 ? peaks.indexOf(nearest) : -1
  })
  const tracks = peaks.map((hue) => ({ hue, centers: new Float64Array(columns).fill(NaN) }))
  const maxStrokeHeight = Math.max(16, (height - 1) * 0.07)
  const first = new Int16Array(tracks.length)
  const last = new Int16Array(tracks.length)
  const counts = new Int16Array(tracks.length)
  let otherColorColumns = 0
  for (let x = 0; x < columns; x += 1) {
    first.fill(-1)
    counts.fill(0)
    let otherColor = false
    for (let y = 0; y < height; y += 1) {
      const hue = pixels[y * columns + x]
      if (hue < 0) continue
      const group = groups[hue]
      if (group < 0) {
        otherColor = true
        continue
      }
      if (first[group] < 0) first[group] = y
      last[group] = y
      counts[group] += 1
    }
    if (otherColor) otherColorColumns += 1
    for (const [i, { centers }] of tracks.entries()) {
      if (!counts[i]) continue
      const band = last[i] - first[i]
      if (band > maxStrokeHeight || first[i] === 0 || last[i] === height - 1) return
      if (band + 1 - counts[i] > 2) {
        const covered = tracks.some((_, other) => other !== i && counts[other] > 0
          && first[other] <= last[i] && last[other] >= first[i])
        if (!covered) return
        continue
      }
      const center = top + (first[i] + last[i]) / 2
      if (Math.abs(center - centers[x - 1]) > maxStrokeHeight) return
      centers[x] = center
    }
  }
  if (otherColorColumns > columns / 4) return
  for (const track of tracks) {
    const { centers } = track
    for (let i = 0; i < columns; i += 1) {
      if (Number.isFinite(centers[i])) continue
      const start = i
      while (i + 1 < columns && Number.isNaN(centers[i + 1])) i += 1
      const gap = i - start + 1
      if (gap <= 3) continue
      const previous = centers[start - 1], next = centers[i + 1]
      if (gap > 14 || !Number.isFinite(previous) || !Number.isFinite(next)
        || Math.abs(previous - next) > maxStrokeHeight) return
      const middle = Math.floor((start + i) / 2)
      const between = (x: number) => previous + (next - previous) * (x - start + 1) / (gap + 1)
      const crossed = tracks.some((other) => other !== track
        && (previous - other.centers[start - 1]) * (next - other.centers[i + 1]) < 0
        && Math.abs(between(middle) - other.centers[middle]) <= 5)
      if (!crossed) return
      for (let x = start; x <= i; x += 1) centers[x] = between(x)
    }
  }
  return tracks.sort((a, b) => a.hue - b.hue)
}

const colorNames = [
  [15, '红'], [45, '橙'], [70, '黄'], [165, '绿'], [195, '青'],
  [250, '蓝'], [295, '紫'], [345, '粉'],
] as const

function chartCaption(hue: number, raster: ChartRaster, words: LocatedWord[], top: number) {
  const { data, width } = raster
  const color = colorNames.find(([upper]) => hue * 10 < upper)?.[1] ?? '红'
  const legendWords = words.filter((word) => word.y >= 6 && word.y < top - 6
    && word.left >= 15 && word.right <= width && /\p{L}/u.test(word.text))
  const labels = legendWords.filter((word) => {
    const x = Math.floor(word.left), y = Math.round(word.y)
    // Look for a short horizontal swatch immediately before the legend text.
    for (let row = y - 5; row <= y + 5; row += 1) {
      let run = 0
      for (let column = Math.max(0, x - 60); column < x - 2; column += 1) {
        const pixel = pixelHue(data, (row * width + column) * 4)
        run = pixel >= 0 && hueDistance(pixel, hue) <= 2 ? run + 1 : 0
        if (run >= 9 && column >= x - 25) return true
      }
    }
    return false
  })
  if (labels.length !== 1) return { color, name: undefined }
  const first = labels[0]
  const neighbors = legendWords.filter((word) => word.left >= first.left
    && Math.abs(word.y - first.y) <= 5).sort((a, b) => a.left - b.left)
  const name = [first.text]
  let right = first.right
  for (const word of neighbors.slice(1)) {
    if (word.left - right > 10) break
    name.push(word.text)
    right = word.right
  }
  return { color, name: name.join(' ') }
}

function hasRightAxis(words: LocatedWord[], right: number, top: number, bottom: number) {
  const ticks = words.filter((word) => word.left > right + 12 && word.y >= top
    && word.y <= bottom && linearTickPattern.test(word.text))
  return ticks.some((tick, index) => ticks.slice(index + 1).some((other) =>
    Math.abs(tick.y - other.y) >= 10 && (Math.abs(tick.left - other.left) <= 10
      || Math.abs(tick.right - other.right) <= 10)))
}

export function readWorkspaceLineChart(raster: ChartRaster, words: ChartWord[]): string | undefined {
  const { width, height, scale } = raster
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
  if (hasRightAxis(positioned, right, top, bottom)) return
  const tracks = plotTracks(raster, { left, right, top, bottom })
  if (!tracks) return

  const precision = Math.max(0, Math.min(2, Math.ceil(-Math.log10(unitsPerPixel))))
  const format = new Intl.NumberFormat('en-US', { useGrouping: false, maximumFractionDigits: precision })
  const output = ['折线图读数（按刻度和识别到的彩色线估算）']
  const captions = tracks.map(({ hue }) => chartCaption(hue, raster, positioned, top))
  for (const [index, { hue, centers }] of tracks.entries()) {
    if (tracks.length > 1) {
      const { color, name } = captions[index]
      const repeatedColor = captions.filter((caption) => caption.color === color).length > 1
      const reference = repeatedColor ? `${color}线（色相约 ${hue * 10}°）` : `${color}线`
      output.push(name ? `${reference} · ${name}` : reference)
    }
    for (const label of labels) {
      const x = Math.round(label.x) - left
      const y = [0, -1, 1, -2, 2].map((offset) => centers[x + offset]).find(Number.isFinite)
      if (y === undefined) return
      const value = lowest.value + (lowest.y - y) * unitsPerPixel
      output.push(`${label.text} 约 ${format.format(value)}${lowest.percent ? '%' : ''}`)
    }
  }
  const text = output.join('\n')
  if (text.length <= 2_900) return text
}

export function readWorkspaceBarChart(chart: BarChart, words: ChartWord[], axisWords = words): string | undefined {
  const { bars, raster } = chart
  const { scale } = raster
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
  if (hasRightAxis(labels, bars[bars.length - 1].right, highest.y - 7, baseline + 7)) return

  const precision = Math.max(0, Math.min(2, Math.ceil(-Math.log10(unitsPerPixel))))
  const format = new Intl.NumberFormat('en-US', { useGrouping: false, maximumFractionDigits: precision })
  const readHeight = (top: number, bottom: number) =>
    format.format((bottom - top + 1) * unitsPerPixel) + (zero.percent ? '%' : '')
  const captions = chart.kind === 'stacked-bar'
    ? chart.stacks[0].map(({ hue }) => chartCaption(hue, raster, labels, highest.y))
    : []
  const colorReferences = captions.map(({ color }, index) => (
    captions.some((caption, other) => other !== index && caption.color === color)
      ? `${color}色段 ${index + 1}` : `${color}色段`
  ))
  const legend = captions.flatMap(({ name }, index) => (
    name && captions.every((other, entry) => entry === index || other.name !== name)
      ? [`${colorReferences[index]} · ${name}`] : []
  ))
  const output = bars.map((bar, index) => {
    const center = (bar.left + bar.right) / 2
    const label = labels.filter((word) => Math.abs(word.x - center) <= (bar.right - bar.left + 1) / 2
      && word.y > baseline + 3 && word.y < baseline + Math.max(25, range * 0.16))
      .sort((a, b) => a.x - b.x).map((word) => word.text).join(' ')
    const reference = `第 ${index + 1} 根${label ? `（${label}）` : ''}`
    if (chart.kind === 'bar') return `${reference}约 ${readHeight(bar.top, bar.bottom)}`
    const segments = chart.stacks[index].map(({ top, bottom }, segment) =>
      `${colorReferences[segment]}约 ${readHeight(top, bottom)}`)
    return [`${reference}合计约 ${readHeight(bar.top, bar.bottom)}`, ...segments].join('，')
  })
  const title = chart.kind === 'stacked-bar' ? '堆叠柱状图读数（各段按刻度和颜色边界估算）' : '柱状图读数（按刻度和柱高估算）'
  const text = [title, ...legend, ...output].join('\n')
  if (text.length <= 2_900) return text
}
