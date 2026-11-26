/* global AbortSignal, File, MessageEvent, URL, Worker */

import {
  WORKBOOK_BYTES, WORKBOOK_CONTENT_LIMIT, WORKBOOK_FILE_LIMIT, WORKBOOK_INVALID, type WorkbookResult,
} from './workspace-table'

export function readWorkspaceXlsx(file: File, signal: AbortSignal) {
  if (!file.size || file.size > WORKBOOK_BYTES) throw new Error(WORKBOOK_FILE_LIMIT)
  signal.throwIfAborted()
  const worker = new Worker(new URL('./workspace-workbook.worker.ts', import.meta.url), { type: 'module' })
  let cancel: () => void = () => undefined
  let deadline: number
  const result = new Promise<WorkbookResult>((resolve, reject) => {
    cancel = () => reject(signal.reason)
    signal.addEventListener('abort', cancel, { once: true })
    worker.onmessage = (event: MessageEvent<WorkbookResult>) => resolve(event.data)
    worker.onerror = () => reject(new Error(WORKBOOK_INVALID))
    deadline = window.setTimeout(() => reject(new Error(WORKBOOK_CONTENT_LIMIT)), 15_000)
    worker.postMessage(file)
  })
  return result.then((reply) => {
    if ('error' in reply) throw new Error(reply.error)
    return reply.sheets
  }).finally(() => {
    signal.removeEventListener('abort', cancel)
    window.clearTimeout(deadline)
    worker.terminate()
  })
}
