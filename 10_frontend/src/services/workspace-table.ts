/* global File */

import { parseCsvRecords, readCsvText } from './csv-import'

export type NumericColumn = {
  column: number
  count: number
  min: number
  max: number
  mean: number
  sum: number
}
export type WorkspaceTableSummary = { rows: number; columns: NumericColumn[] }
export type LocalWorkspaceTable = { rows: number; columns: (NumericColumn & { label: string })[] }
export type LocalWorkspaceSheet = { name: string; table: LocalWorkspaceTable }
export type WorkbookResult = { sheets: LocalWorkspaceSheet[] } | { error: string }

export const WORKSPACE_TABLE_ROWS = 2000
export const WORKSPACE_TABLE_COLUMNS = 40
export const WORKBOOK_BYTES = 2 * 1024 * 1024
export const WORKBOOK_INVALID = 'Excel 暂时无法读取，请检查文件是否损坏或受保护'
export const WORKBOOK_FILE_LIMIT = '请选择不超过 2 MiB 的 XLSX 文件'
export const WORKBOOK_CONTENT_LIMIT = '请选择内容更少的 XLSX 文件'

const numeric = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i

export async function readWorkspaceCsv(file: File): Promise<LocalWorkspaceTable> {
  if (!file.size || file.size > 512 * 1024) throw new Error('请选择不超过 512 KiB 的 CSV 文件')
  const [header, ...rows] = parseCsvRecords(await readCsvText(file), true)
  if (!header?.length || header.length > WORKSPACE_TABLE_COLUMNS || !rows.length || rows.length > WORKSPACE_TABLE_ROWS
    || rows.some((row) => row.length !== header.length)) {
    throw new Error('请选择首行为列名、最多 40 列和 2000 行数据的矩形 CSV')
  }
  const table = summarizeWorkspaceRows(header, rows, (cell) => (
    typeof cell === 'string' && numeric.test(cell) ? Number(cell) : NaN
  ))
  if (!table.columns.length) throw new Error('请选择含普通数字的 CSV 表格')
  return table
}

export function summarizeWorkspaceRows(
  header: readonly unknown[],
  rows: readonly (readonly unknown[])[],
  parse: (cell: unknown) => number,
): LocalWorkspaceTable {
  const columns: LocalWorkspaceTable['columns'] = []
  header.forEach((label, index) => {
    const values = rows.flatMap((row) => {
      const value = parse(row[index])
      return Number.isFinite(value) && Math.abs(value) <= 1e9 ? [value] : []
    })
    if (!values.length) return
    const sum = values.reduce((total, value) => total + value, 0)
    columns.push({
      column: index + 1, label: typeof label === 'string' ? label.slice(0, 180) : '',
      count: values.length, min: Math.min(...values),
      max: Math.max(...values), mean: sum / values.length, sum,
    })
  })
  return { rows: rows.length, columns }
}
