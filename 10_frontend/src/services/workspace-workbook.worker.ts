/* global File, MessageEvent, self */

import type { WorkbookResult } from './workspace-table'
import { readWorkspaceWorkbook, workbookError } from './workspace-workbook'

self.onmessage = async (event: MessageEvent<File>) => {
  let result: WorkbookResult
  try {
    result = { sheets: await readWorkspaceWorkbook(await event.data.arrayBuffer()) }
  } catch (error) {
    result = { error: workbookError(error) }
  }
  self.postMessage(result)
}
