/* global AbortSignal, File, MessageEvent, URL, Worker */

import {
  ROSTER_WORKBOOK_BYTES, ROSTER_WORKBOOK_FILE_LIMIT, WORKBOOK_BYTES,
  WORKBOOK_CONTENT_LIMIT, WORKBOOK_FILE_LIMIT, WORKBOOK_INVALID, type WorkbookMode, type WorkbookResult,
} from './workspace-table'

function readInWorkbookWorker(file: File, mode: WorkbookMode, signal: AbortSignal) {
  const roster = mode === 'roster'
  if (!file.size || file.size > (roster ? ROSTER_WORKBOOK_BYTES : WORKBOOK_BYTES)) {
    throw new Error(roster ? ROSTER_WORKBOOK_FILE_LIMIT : WORKBOOK_FILE_LIMIT)
  }
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
    worker.postMessage({ file, mode })
  })
  return result.finally(() => {
    signal.removeEventListener('abort', cancel)
    window.clearTimeout(deadline)
    worker.terminate()
  })
}

export async function readWorkspaceXlsx(file: File, signal: AbortSignal) {
  const result = await readInWorkbookWorker(file, 'statistics', signal)
  if ('sheets' in result) return result.sheets
  throw new Error('error' in result ? result.error : WORKBOOK_INVALID)
}

export async function readRosterXlsx(file: File, signal: AbortSignal) {
  const result = await readInWorkbookWorker(file, 'roster', signal)
  if ('records' in result) return result.records
  throw new Error('error' in result ? result.error : WORKBOOK_INVALID)
}
