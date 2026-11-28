/* global ImageBitmap */

import type { ChartWord } from './workspace-image-chart'
import { hasFormulaRegion, type FormulaRegion } from './workspace-formula-region'

type Box = { left: number; top: number; right: number; bottom: number }
type Raster = { data: Uint8ClampedArray; width: number; height: number; scale: number }
const maxSuggestions = 8

function inkBounds(ink: Uint8Array, width: number, box: Box): Box | undefined {
  let left = box.right, right = box.left, top = box.bottom, bottom = box.top
  for (let y = box.top; y < box.bottom; y += 1) {
    for (let x = box.left; x < box.right; x += 1) {
      if (!ink[y * width + x]) continue
      left = Math.min(left, x)
      right = Math.max(right, x + 1)
      top = Math.min(top, y)
      bottom = Math.max(bottom, y + 1)
    }
  }
  if (left < right && top < bottom) return { left, top, right, bottom }
}

function fractionStrokes(ink: Uint8Array, width: number, height: number) {
  const strokes: Box[] = []
  const minLength = Math.max(16, Math.round(width * 0.026))
  const maxLength = Math.round(width * 0.24)
  for (let y = 1; y < height - 1; y += 1) {
    let start = -1
    for (let x = 0; x <= width; x += 1) {
      // Three rows keep slightly tilted hand-drawn strokes connected.
      if (x < width && (ink[y * width + x] || ink[(y - 1) * width + x] || ink[(y + 1) * width + x])) {
        if (start < 0) start = x
        continue
      }
      if (start < 0) continue
      if (x - start >= minLength && x - start <= maxLength) {
        const match = strokes.findLast((stroke) => stroke.bottom >= y - 1
          && Math.abs(stroke.left - start) <= 5 && Math.abs(stroke.right - x) <= 5)
        if (match) {
          match.bottom = y + 1
          match.left = Math.min(match.left, start)
          match.right = Math.max(match.right, x)
        } else {
          strokes.push({ left: start, right: x, top: y, bottom: y + 1 })
          if (strokes.length > 160) return []
        }
      }
      start = -1
    }
  }
  const distinct: Box[] = []
  strokes.sort((a, b) => (b.right - b.left) - (a.right - a.left))
  for (const stroke of strokes) {
    // At the ends of a slanted fraction bar, consecutive scanlines can see
    // only part of the same stroke. Prefer the longest continuous segment.
    if (!distinct.some((other) => Math.abs(stroke.top - other.top) <= 8
      && Math.min(stroke.right, other.right) - Math.max(stroke.left, other.left)
        >= (stroke.right - stroke.left) * 0.65)) distinct.push(stroke)
  }
  return distinct
}

function fractionBoxes({ data, width, height }: Raster): Box[] {
  const ink = new Uint8Array(width * height)
  let lightPixels = 0
  for (let index = 0; index < ink.length; index += 1) {
    const offset = index * 4
    const lightness = (data[offset] + data[offset + 1] + data[offset + 2]) / 3
    if (data[offset + 3] < 200 || lightness > 220) lightPixels += 1
    else if (lightness < 135) ink[index] = 1
  }
  if (lightPixels < ink.length * 0.7) return []

  const fractions = fractionStrokes(ink, width, height).flatMap((stroke) => {
    const length = stroke.right - stroke.left
    if (stroke.bottom - stroke.top > Math.max(10, length * 0.2)) return []
    const depth = Math.round(length * 0.94)
    const above = inkBounds(ink, width, {
      ...stroke, top: Math.max(0, stroke.top - depth), bottom: stroke.top - 3,
    })
    const below = inkBounds(ink, width, {
      ...stroke, top: stroke.bottom + 3, bottom: Math.min(height, stroke.bottom + depth),
    })
    const operandWidth = Math.max(5, Math.min(11, length * 0.18))
    if (!above || !below || [above, below].some((box) => box.right - box.left < operandWidth
      || box.bottom - box.top < 5)) return []
    return [{ stroke, length, content: { ...stroke, top: above.top, bottom: below.bottom } }]
  }).sort((a, b) => a.stroke.left - b.stroke.left)

  const groups: typeof fractions[] = []
  for (const fraction of fractions) {
    const group = groups.find((items) => {
      const last = items[items.length - 1]
      // Nearby structures on the same baseline can form one fraction expression.
      return Math.abs(last.stroke.top - fraction.stroke.top) <= Math.max(4, height * 0.014)
        && fraction.stroke.left - last.stroke.right <= Math.max(last.length, fraction.length) * 1.65
    })
    if (group) group.push(fraction)
    else groups.push([fraction])
  }
  return groups.filter((group) => group.length <= 4).map((group) => {
    const length = Math.max(...group.map((item) => item.length))
    return {
      left: Math.min(...group.map(({ content }) => content.left)) - length * 0.52,
      right: Math.max(...group.map(({ content }) => content.right)) + length * 0.52,
      top: Math.min(...group.map(({ content }) => content.top)) - length * 0.23,
      bottom: Math.max(...group.map(({ content }) => content.bottom)) + length * 0.23,
    }
  })
}

const equationToken = /^(?:(?:sin|cos|tan|log|ln|sqrt)|[\dA-Za-zα-ω\s()[\]{}=+−\-×÷*/^√.≤≥≠])+$/u
function inlineBoxes(lines: ChartWord[][], scale: number, height: number): Box[] {
  return lines.flatMap((line) => {
    const expressions: ChartWord[][] = []
    let current: ChartWord[] = []
    for (const word of line) {
      const token = word.text.trim()
      const previous = current.at(-1)
      const math = word.confidence >= 45 && equationToken.test(token)
        && !/[a-z]{2,}/i.test(token.replace(/sin|cos|tan|log|sqrt|ln/gi, ''))
      if (!math || (previous && (word.bbox.x0 - previous.bbox.x1) * scale > Math.max(12, height * 0.027))) {
        if (current.length) expressions.push(current)
        current = []
      }
      if (math) current.push(word)
    }
    if (current.length) expressions.push(current)
    return expressions.flatMap((words) => {
      const text = words.map((word) => word.text).join(' ')
      if (!/\d/.test(text) || !/[=+×÷*^√≤≥≠]|\s[-−]\s|[\da-z]\/\d/i.test(text)
        || /^\d{2,4}\/\d{1,2}\/\d{1,4}$/.test(text) || !/[\da-zα-ω].*[\da-zα-ω]/i.test(text)) return []
      const padding = Math.max(5, height * 0.008)
      return [{
        left: Math.min(...words.map((word) => word.bbox.x0)) * scale - padding,
        right: Math.max(...words.map((word) => word.bbox.x1)) * scale + padding,
        top: Math.min(...words.map((word) => word.bbox.y0)) * scale - padding,
        bottom: Math.max(...words.map((word) => word.bbox.y1)) * scale + padding,
      }]
    })
  })
}

function overlaps(a: Box, b: Box) {
  const width = Math.min(a.right, b.right) - Math.max(a.left, b.left)
  const height = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
  return width > 0 && height > 0 && width * height > Math.min(
    (a.right - a.left) * (a.bottom - a.top), (b.right - b.left) * (b.bottom - b.top),
  ) * 0.4
}

export function suggestWorksheetFormulaRegions(raster: Raster, lines: ChartWord[][]): FormulaRegion[] {
  const { width, height, scale } = raster
  const distinct: Box[] = []
  for (const box of [...fractionBoxes(raster), ...inlineBoxes(lines, scale, height)]) {
    if (!distinct.some((candidate) => overlaps(candidate, box))) distinct.push(box)
  }
  const percent = (point: number, size: number) => Math.round(Math.min(100, Math.max(0, point / size * 100)) * 10) / 10
  return distinct.sort((a, b) => a.top - b.top || a.left - b.left).map((box) => ({
    left: percent(box.left, width), right: percent(box.right, width),
    top: percent(box.top, height), bottom: percent(box.bottom, height),
  })).filter(hasFormulaRegion).slice(0, maxSuggestions)
}

export function readWorksheetFormulaRegions(bitmap: ImageBitmap, lines: ChartWord[][]): FormulaRegion[] {
  const scale = Math.min(1, 720 / Math.max(bitmap.width, bitmap.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(bitmap.width * scale))
  canvas.height = Math.max(1, Math.round(bitmap.height * scale))
  const context = canvas.getContext('2d', { willReadFrequently: true })
  if (!context) return []
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  const { data } = context.getImageData(0, 0, canvas.width, canvas.height)
  return suggestWorksheetFormulaRegions({ data, width: canvas.width, height: canvas.height, scale }, lines)
}
