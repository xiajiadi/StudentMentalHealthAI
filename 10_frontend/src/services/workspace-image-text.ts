/* global AbortSignal, File, URL, createImageBitmap */

import { createWorker, OEM } from 'tesseract.js'

export async function readWorkspaceImage(file: File, signal: AbortSignal): Promise<string> {
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
  try {
    if (bitmap.width * bitmap.height > 12_000_000) throw new Error('请选择像素较少的图片')
  } finally {
    bitmap.close()
  }
  signal.throwIfAborted()

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
    const result = await Promise.race([worker.recognize(file), interruption])
    const content = result.data.text.trim()
    if (!content) throw new Error('图片中未识别到文字')
    if (content.length > 3_000) throw new Error('请选择只包含所需文字的图片')
    return content
  } finally {
    expired = true
    window.clearTimeout(deadline)
    signal.removeEventListener('abort', abortReading)
    await worker?.terminate()
  }
}
