import { describe, expect, it } from 'vitest'
import { readWorkspaceGeometry } from '@/services/workspace-image-geometry'

type Point = [x: number, y: number]

function fixture() {
  const width = 540, height = 380
  const raster = { data: new Uint8ClampedArray(width * height * 4), width, height, scale: 0.5 }
  const triangle: Point[] = [[80, 80], [280, 80], [80, 230]]
  function dot(x: number, y: number) {
    raster.data.set([27, 38, 64, 255], (width * y + x) * 4)
  }
  function stroke(a: Point, b: Point) {
    const steps = Math.max(Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1]))
    for (let index = 0; index <= steps; index += 1) {
      const x = Math.round(a[0] + (b[0] - a[0]) * index / steps)
      const y = Math.round(a[1] + (b[1] - a[1]) * index / steps)
      for (let dy = -1; dy <= 1; dy += 1) {
        for (let dx = -1; dx <= 1; dx += 1) dot(x + dx, y + dy)
      }
    }
  }
  function outline(points: Point[]) {
    points.forEach((point, index) => stroke(point, points[(index + 1) % points.length]))
  }
  return { raster, triangle, outline, stroke, dot }
}

function letter(text: string, x: number, y: number, confidence = 90) {
  return { text, confidence, bbox: { x0: 2 * x - 5, y0: 2 * y - 8, x1: 2 * x + 5, y1: 2 * y + 8 } }
}

function ellipse(center: Point, rx: number, ry = rx) {
  return Array.from({ length: 72 }, (_, index): Point => {
    const angle = index * Math.PI / 36
    return [Math.round(center[0] + rx * Math.cos(angle)), Math.round(center[1] + ry * Math.sin(angle))]
  })
}

describe('workspace geometry image notes', () => {
  it('estimates angles and associates nearby distinct labels in original image coordinates', () => {
    const { raster, triangle, outline } = fixture()
    outline(triangle)
    const text = readWorkspaceGeometry(raster, [
      letter('A', 60, 60), letter('B', 305, 65), letter('C', 64, 248), letter('D', 520, 345),
    ])
    expect(text).toContain('以题目给出的条件为准')
    expect(text).toContain('三角形，A（左上）约 90°，B（右上）约 35°，C（左下）约 55°')
    expect(text).not.toContain('D')
  })

  it('describes separate shapes without guessing unreadable or ambiguous labels', () => {
    const { raster, triangle, outline } = fixture()
    outline(triangle)
    outline([[355, 132], [462, 157], [437, 275], [330, 250]])
    const text = readWorkspaceGeometry(raster, [
      letter('A', 66, 68, 15), letter('X', 305, 65), letter('Y', 310, 80),
    ])
    expect(text).toContain('图形 1：三角形，左上约 90°')
    expect(text).toContain('图形 2：四边形')
    expect(text).not.toMatch(/[AXY]/)
  })

  it('ignores open polygons and polygons with substantial internal lines', () => {
    const { raster, triangle, outline, stroke } = fixture()
    stroke(triangle[0], triangle[1])
    stroke(triangle[0], triangle[2])
    expect(readWorkspaceGeometry(raster, [])).toBeUndefined()
    const square: Point[] = [[35, 40], [250, 40], [250, 315], [35, 315]]
    outline(square)
    stroke(square[0], square[2])
    stroke(square[1], square[3])
    expect(readWorkspaceGeometry(raster, [])).toBeUndefined()
  })

  it('identifies a labeled diameter and a separate radius on the same circle', () => {
    const { raster, outline, stroke } = fixture()
    outline(ellipse([270, 180], 115))
    stroke([155, 180], [385, 180])
    stroke([270, 180], [270, 65])
    const text = readWorkspaceGeometry(raster, [
      letter('A', 140, 183), letter('B', 402, 180), letter('C', 270, 49), letter('O', 284, 198),
    ])
    expect(text).toContain('图形 1：圆')
    expect(text).toContain('从A（左侧圆周）经过O（圆心）到B（右侧圆周）画有直径')
    expect(text).toContain('从O（圆心）到C（上侧圆周）画有半径')
  })

  it('keeps a plain circle and does not turn an off-center chord into a diameter', () => {
    const { raster, outline, stroke } = fixture()
    outline(ellipse([270, 180], 100))
    expect(readWorkspaceGeometry(raster, [])?.split('\n').at(-1)).toBe('图形 1：圆')
    stroke([184, 130], [356, 130])
    expect(readWorkspaceGeometry(raster, [])?.split('\n').at(-1)).toBe('图形 1：圆')
  })

  it('identifies a slanted diameter drawn through the center', () => {
    const { raster, outline, stroke } = fixture()
    outline(ellipse([220, 175], 114))
    stroke([139, 94], [301, 256])
    const text = readWorkspaceGeometry(raster, [])
    expect(text).toContain('左上侧圆周')
    expect(text).toContain('右下侧圆周')
    expect(text).toContain('画有直径')
    expect(text).not.toContain('画有半径')
  })

  it('leaves an open arc and a visibly stretched ellipse unsupported', () => {
    const { raster, outline, stroke } = fixture()
    const arc = ellipse([155, 185], 80).slice(0, 57)
    arc.slice(1).forEach((point, index) => stroke(arc[index], point))
    outline(ellipse([386, 180], 95, 62))
    expect(readWorkspaceGeometry(raster, [])).toBeUndefined()
  })

  it('does not infer a geometry outline from a filled chart bar', () => {
    const { raster, dot } = fixture()
    for (let x = 60; x < 200; x += 1) {
      for (let y = 35; y < 325; y += 1) dot(x, y)
    }
    expect(readWorkspaceGeometry(raster, [])).toBeUndefined()
  })
})
