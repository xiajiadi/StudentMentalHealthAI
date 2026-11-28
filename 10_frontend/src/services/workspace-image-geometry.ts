/* global ImageBitmap */

import type { ChartWord } from './workspace-image-chart'

type Point = { x: number; y: number }
type Raster = { data: Uint8ClampedArray; width: number; height: number; scale: number }
type Outline = { corners: Point[]; center: Point; span: number }
type Bounds = { left: number; right: number; top: number; bottom: number }

const geometryHeading = '图形轮廓（按图片估算，以题目给出的条件为准）'

const turn = (a: Point, b: Point, c: Point) => (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)

function convexHull(points: Point[]) {
  const sorted = points.sort((a, b) => a.x - b.x || a.y - b.y)
  function half(ordered: Point[]) {
    const edge: Point[] = []
    for (const point of ordered) {
      while (edge.length >= 2 && turn(edge[edge.length - 2], edge[edge.length - 1], point) <= 0) edge.pop()
      edge.push(point)
    }
    return edge.slice(0, -1)
  }
  return [...half(sorted), ...half(sorted.reverse())]
}

function distanceFromLine(point: Point, a: Point, b: Point) {
  return Math.abs(turn(a, b, point)) / Math.hypot(a.x - b.x, a.y - b.y)
}

function fitOutline(
  indices: Int32Array, count: number, width: number, height: number, { left, right, top, bottom }: Bounds,
): Outline | undefined {
  const boxWidth = right - left + 1, boxHeight = bottom - top + 1
  const span = Math.min(boxWidth, boxHeight)
  if (span < 52 || count > boxWidth * boxHeight * 0.20
      || left <= 1 || top <= 1 || right >= width - 2 || bottom >= height - 2) return

  const leftByRow = new Int32Array(boxHeight).fill(width)
  const rightByRow = new Int32Array(boxHeight).fill(-1)
  for (let index = 0; index < count; index += 1) {
    const x = indices[index] % width
    const row = Math.floor(indices[index] / width) - top
    leftByRow[row] = Math.min(leftByRow[row], x)
    rightByRow[row] = Math.max(rightByRow[row], x)
  }
  const outerPixels: Point[] = []
  for (let row = 0; row < boxHeight; row += 1) {
    if (rightByRow[row] < 0) continue
    outerPixels.push({ x: leftByRow[row], y: top + row })
    if (rightByRow[row] !== leftByRow[row]) outerPixels.push({ x: rightByRow[row], y: top + row })
  }
  const corners = convexHull(outerPixels)
  const tolerance = Math.min(10, Math.max(3, span * 0.025))
  while (corners.length > 3) {
    const distances = corners.map((point, index) => distanceFromLine(
      point, corners.at(index - 1)!, corners[(index + 1) % corners.length],
    ))
    const nearest = Math.min(...distances)
    if (nearest > tolerance) break
    corners.splice(distances.indexOf(nearest), 1)
  }
  if (corners.length < 3 || corners.length > 4) return
  const area = Math.abs(corners.reduce((sum, point, index) => {
    const next = corners[(index + 1) % corners.length]
    return sum + point.x * next.y - next.x * point.y
  }, 0)) / 2
  if (area < boxWidth * boxHeight * 0.24) return

  const sides = corners.map((start, index) => {
    const end = corners[(index + 1) % corners.length]
    const dx = end.x - start.x, dy = end.y - start.y
    return { start, end, dx, dy, lengthSquared: dx * dx + dy * dy, coverage: new Uint8Array(16) }
  })
  if (sides.some(({ lengthSquared }) => lengthSquared < (span * 0.27) ** 2)) return
  let onOutline = 0
  for (let index = 0; index < count; index += 1) {
    const point = { x: indices[index] % width, y: Math.floor(indices[index] / width) }
    let nearSide = false
    for (const side of sides) {
      const projection = ((point.x - side.start.x) * side.dx + (point.y - side.start.y) * side.dy) / side.lengthSquared
      if (projection < -0.04 || projection > 1.04
          || distanceFromLine(point, side.start, side.end) > tolerance * 1.45) continue
      side.coverage[Math.max(0, Math.min(15, Math.floor(projection * 16)))] = 1
      nearSide = true
    }
    onOutline += Number(nearSide)
  }
  if (onOutline < count * 0.88 || sides.some(({ coverage }) => coverage.reduce((sum, bin) => sum + bin, 0) < 15)) return

  const first = corners.reduce((best, point, index) => {
    const a = corners[best]
    return point.y < a.y - tolerance || (Math.abs(point.y - a.y) <= tolerance && point.x < a.x) ? index : best
  }, 0)
  return {
    corners: [...corners.slice(first), ...corners.slice(0, first)],
    center: { x: (left + right) / 2, y: (top + bottom) / 2 },
    span,
  }
}

function findOutlines({ data, width, height }: Raster) {
  const unvisited = new Uint8Array(width * height)
  for (let index = 0; index < unvisited.length; index += 1) {
    const offset = 4 * index
    const lightness = 0.2126 * data[offset] + 0.7152 * data[offset + 1] + 0.0722 * data[offset + 2]
    unvisited[index] = Number(data[offset + 3] >= 200 && lightness < 150)
  }
  const queue = new Int32Array(unvisited.length)
  const outlines: Outline[] = []
  for (let index = 0; index < unvisited.length; index += 1) {
    if (!unvisited[index]) continue
    unvisited[index] = 0
    queue[0] = index
    let size = 1, left = width, right = 0, top = height, bottom = 0
    for (let head = 0; head < size; head += 1) {
      const x = queue[head] % width, y = Math.floor(queue[head] / width)
      left = Math.min(left, x)
      right = Math.max(right, x)
      top = Math.min(top, y)
      bottom = Math.max(bottom, y)
      for (let row = Math.max(0, y - 1); row <= Math.min(y + 1, height - 1); row += 1) {
        for (let col = Math.max(0, x - 1); col <= Math.min(x + 1, width - 1); col += 1) {
          const neighbor = row * width + col
          if (!unvisited[neighbor]) continue
          unvisited[neighbor] = 0
          queue[size++] = neighbor
        }
      }
    }
    const outline = fitOutline(queue, size, width, height, { left, right, top, bottom })
    if (outline) outlines.push(outline)
    if (outlines.length > 4) return []
  }
  return outlines.sort((a, b) => a.center.y - b.center.y || a.center.x - b.center.x)
}

function cornerPosition(corner: Point, center: Point, span: number) {
  const dx = corner.x - center.x, dy = corner.y - center.y
  const vertical = Math.abs(dy) < span * 0.17 ? '' : dy < 0 ? '上' : '下'
  const horizontal = Math.abs(dx) < span * 0.17 ? '' : dx < 0 ? '左' : '右'
  return horizontal + vertical || '中间'
}

function cornerAngle(corner: Point, a: Point, b: Point) {
  const ax = a.x - corner.x, ay = a.y - corner.y, bx = b.x - corner.x, by = b.y - corner.y
  const cosine = (ax * bx + ay * by) / (Math.hypot(ax, ay) * Math.hypot(bx, by))
  return Math.round(Math.acos(Math.max(-1, Math.min(1, cosine))) * 36 / Math.PI) * 5
}

export function readWorkspaceGeometry(raster: Raster, words: ChartWord[]): string | undefined {
  const outlines = findOutlines(raster)
  if (!outlines.length) return
  const labelPoints = words.filter(({ text, confidence }) => /^[A-Z]$/.test(text.trim()) && confidence >= 55)
    .map(({ text, bbox }) => ({
      name: text.trim(),
      x: (bbox.x0 + bbox.x1) / 2 * raster.scale,
      y: (bbox.y0 + bbox.y1) / 2 * raster.scale,
    }))
  const notes = outlines.map(({ corners, center, span }, index) => {
    const positions = corners.map((corner) => cornerPosition(corner, center, span))
    const labels = corners.map((corner) => {
      const nearby = labelPoints.filter((label) => Math.hypot(label.x - corner.x, label.y - corner.y) <= span * 0.23)
      return nearby.length === 1 ? nearby[0].name : undefined
    })
    const descriptions = corners.map((corner, cornerIndex) => {
      const label = labels[cornerIndex]
      const position = positions[cornerIndex]
      const name = label && labels.indexOf(label) === labels.lastIndexOf(label) ? `${label}（${position}）`
        : positions.indexOf(position) === positions.lastIndexOf(position) ? position : `顶点 ${cornerIndex + 1}（${position}）`
      return `${name}约 ${cornerAngle(corner, corners.at(cornerIndex - 1)!, corners[(cornerIndex + 1) % corners.length])}°`
    })
    return `图形 ${index + 1}：${corners.length === 3 ? '三角形' : '四边形'}，${descriptions.join('，')}`
  })
  return [geometryHeading, ...notes].join('\n')
}

export function readWorkspaceImageGeometry(bitmap: ImageBitmap, words: ChartWord[]) {
  const scale = Math.min(1, 840 / Math.max(bitmap.width, bitmap.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(bitmap.width * scale))
  canvas.height = Math.max(1, Math.round(bitmap.height * scale))
  const context = canvas.getContext('2d', { willReadFrequently: true })
  if (!context) return
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  const { data, width, height } = context.getImageData(0, 0, canvas.width, canvas.height)
  return readWorkspaceGeometry({ data, width, height, scale }, words)
}
