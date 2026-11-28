/* global AbortSignal, Blob, File, URL, createImageBitmap */

import { createWorker, OEM, PSM, type Page } from 'tesseract.js'
import {
  detectWorkspaceBarChart, readWorkspaceBarChart, readWorkspaceLineChart, workspaceChartRaster,
} from './workspace-image-chart'

export type WorkspaceChartPreview = { kind: 'bar' | 'stacked-bar' | 'line'; text: string }

function readWords(page: Page) {
  return page.blocks?.flatMap((block) => block.paragraphs.flatMap((paragraph) =>
    paragraph.lines.flatMap((line) => line.words),
  )) ?? []
}

export async function readWorkspaceImage(file: File, signal: AbortSignal): Promise<{ text: string; chart?: WorkspaceChartPreview }> {
  if (!file.size || file.size > 4 * 1024 * 1024) {
    throw new Error('请选择不超过 4 MiB 的 PNG、JPEG 或 WebP 图片')
  }
  const header = new Uint8Array(await file.slice(0, 12).arrayBuffer())
  const png = [137, 80, 78, 71, 13, 10, 26, 10].every((byte, index) => header[index] === byte)
  const jpeg = header[0] === 255 && header[1] === 216 && header[2] === 255
  const webp = String.fromCharCode(...header.slice(0, 4)) === 'RIFF'
    && String.fromCharCode(...header.slice(8, 12)) === 'WEBP'
  if (!png && !jpeg && !webp) throw new Error('请选择有效的 PNG、JPEG 或 WebP 图片')
  signal.throwIfAborted()

  const bitmap = await createImageBitmap(file)
  const assets = new URL(`${import.meta.env.BASE_URL}assets/ocr-v7`, window.location.origin).href
  let worker: Awaited<ReturnType<typeof createWorker>> | undefined
  let expired = false
  let abortReading: () => void = () => undefined
  const interruption = new Promise<never>((_, reject) => {
    abortReading = () => reject(new Error('图片识别已中止'))
    signal.addEventListener('abort', abortReading, { once: true })
  })
  const deadline = window.setTimeout(abortReading, 45_000)
  try {
    if (bitmap.width * bitmap.height > 12_000_000) throw new Error('请选择像素较少的图片')
    signal.throwIfAborted()
    const loading = createWorker(['eng', 'chi_sim'], OEM.LSTM_ONLY, {
      workerPath: `${assets}/worker.min.js`,
      corePath: assets,
      langPath: assets,
      workerBlobURL: false,
      errorHandler: abortReading,
    }).then(async (loaded) => {
      if (signal.aborted || expired) {
        await loaded.terminate()
        throw new Error('图片识别已中止')
      }
      return loaded
    })
    worker = await Promise.race([loading, interruption])
    const result = await Promise.race([worker.recognize(file, {}, { blocks: true }), interruption])
    const content = result.data.text.trim()
    if (!content) return { text: '' }
    if (content.length > 3_000) throw new Error('请选择只包含所需文字的图片')
    const words = readWords(result.data)
    const raster = workspaceChartRaster(bitmap, words)
    if (!raster) return { text: content }
    const barChart = detectWorkspaceBarChart(raster, words)
    let barValues = barChart && readWorkspaceBarChart(barChart, words)
    if (barChart && !barValues) {
      await Promise.race([worker.setParameters({
        tessedit_pageseg_mode: PSM.SINGLE_BLOCK,
        tessedit_char_whitelist: '0123456789.%−-',
      }), interruption])
      const rectangle = { left: 0, top: 0, width: barChart.axisWidth, height: bitmap.height }
      const axis = await Promise.race([worker.recognize(file, { rectangle }, { blocks: true }), interruption])
      barValues = readWorkspaceBarChart(barChart, words, readWords(axis.data))
    }
    if (barChart && barValues) return { text: content, chart: { kind: barChart.kind, text: barValues } }
    const lineValues = readWorkspaceLineChart(raster, words)
    return { text: content, chart: lineValues ? { kind: 'line', text: lineValues } : undefined }
  } finally {
    expired = true
    bitmap.close()
    window.clearTimeout(deadline)
    signal.removeEventListener('abort', abortReading)
    await worker?.terminate()
  }
}

export async function encodeWorkspaceFormulaImage(file: File, signal: AbortSignal): Promise<Blob> {
  const bitmap = await createImageBitmap(file)
  try {
    signal.throwIfAborted()
    const scale = Math.min(1, 640 / Math.max(bitmap.width, bitmap.height))
    const surface = document.createElement('canvas')
    surface.width = Math.max(1, Math.round(bitmap.width * scale))
    surface.height = Math.max(1, Math.round(bitmap.height * scale))
    const context = surface.getContext('2d', { alpha: false })
    if (!context) throw new Error('无法准备公式图片')
    context.fillStyle = '#fff'
    context.fillRect(0, 0, surface.width, surface.height)
    context.drawImage(bitmap, 0, 0, surface.width, surface.height)
    const encoded = await new Promise<Blob | null>((resolve) => surface.toBlob(resolve, 'image/png'))
    signal.throwIfAborted()
    if (!encoded || encoded.size > 768 * 1024) throw new Error('请选择只包含一道公式的清晰图片')
    return encoded
  } finally {
    bitmap.close()
  }
}
