/* global AbortSignal, File, URL, createImageBitmap */

import { createWorker, OEM, PSM, type Page } from 'tesseract.js'
import { detectWorkspaceBarChart, readWorkspaceBarChart } from './workspace-image-chart'

function readWords(page: Page) {
  return page.blocks?.flatMap((block) => block.paragraphs.flatMap((paragraph) =>
    paragraph.lines.flatMap((line) => line.words),
  )) ?? []
}

export async function readWorkspaceImage(file: File, signal: AbortSignal): Promise<{ text: string; chart?: string }> {
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
    if (!content) throw new Error('图片中未识别到文字')
    if (content.length > 3_000) throw new Error('请选择只包含所需文字的图片')
    const words = readWords(result.data)
    const barChart = detectWorkspaceBarChart(bitmap, words)
    if (!barChart) return { text: content }

    let chart = readWorkspaceBarChart(barChart, words)
    if (!chart) {
      await Promise.race([worker.setParameters({
        tessedit_pageseg_mode: PSM.SINGLE_BLOCK,
        tessedit_char_whitelist: '0123456789.%−-',
      }), interruption])
      const rectangle = { left: 0, top: 0, width: barChart.axisWidth, height: bitmap.height }
      const axis = await Promise.race([worker.recognize(file, { rectangle }, { blocks: true }), interruption])
      chart = readWorkspaceBarChart(barChart, words, readWords(axis.data))
    }
    return { text: content, chart }
  } finally {
    expired = true
    bitmap.close()
    window.clearTimeout(deadline)
    signal.removeEventListener('abort', abortReading)
    await worker?.terminate()
  }
}
