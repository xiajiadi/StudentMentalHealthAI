export type FormulaRegion = { left: number; top: number; right: number; bottom: number }

export function hasFormulaRegion({ left, top, right, bottom }: FormulaRegion): boolean {
  return [left, top, right, bottom].every((edge) => Number.isFinite(edge) && edge >= 0 && edge <= 100)
    && right - left >= 2 && bottom - top >= 2
}

export function formulaPixelBounds(width: number, height: number, region?: FormulaRegion) {
  if (!region) return { left: 0, top: 0, width, height }
  if (!hasFormulaRegion(region)) throw new Error('请框选一整道公式')
  // Round inwards so pixels outside the preview selection are never uploaded.
  const left = Math.ceil(width * region.left / 100)
  const top = Math.ceil(height * region.top / 100)
  const cropWidth = Math.floor(width * region.right / 100) - left
  const cropHeight = Math.floor(height * region.bottom / 100) - top
  if (cropWidth < 12 || cropHeight < 12) throw new Error('选区太小，请框选一整道公式')
  return { left, top, width: cropWidth, height: cropHeight }
}
