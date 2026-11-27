/* global File, MessageEvent, self */

import type { WorkbookMode, WorkbookResult } from './workspace-table'
import { readRosterWorkbook, readWorkspaceWorkbook, workbookError } from './workspace-workbook'

self.onmessage = async (event: MessageEvent<{ file: File; mode: WorkbookMode }>) => {
  let result: WorkbookResult
  try {
    const buffer = await event.data.file.arrayBuffer()
    result = event.data.mode === 'roster'
      ? { records: await readRosterWorkbook(buffer) }
      : { sheets: await readWorkspaceWorkbook(buffer) }
  } catch (error) {
    result = { error: workbookError(error) }
  }
  self.postMessage(result)
}
