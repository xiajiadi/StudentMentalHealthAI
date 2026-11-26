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

const numeric = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i

export async function readWorkspaceCsv(file: File): Promise<LocalWorkspaceTable> {
  if (!file.size || file.size > 512 * 1024) throw new Error('请选择不超过 512 KiB 的 CSV 文件')
  const [header, ...rows] = parseCsvRecords(await readCsvText(file), true)
  if (!header?.length || header.length > 40 || !rows.length || rows.length > 2000
    || rows.some((row) => row.length !== header.length)) {
    throw new Error('请选择首行为列名、最多 40 列和 2000 行数据的矩形 CSV')
  }
  const columns: LocalWorkspaceTable['columns'] = []
  header.forEach((label, index) => {
    const values = rows.flatMap((row) => {
      const cell = row[index] ?? ''
      const value = Number(cell)
      return numeric.test(cell) && Number.isFinite(value) && Math.abs(value) <= 1e9 ? [value] : []
    })
    if (!values.length) return
    const sum = values.reduce((total, value) => total + value, 0)
    columns.push({
      column: index + 1, label: label.slice(0, 180), count: values.length, min: Math.min(...values),
      max: Math.max(...values), mean: sum / values.length, sum,
    })
  })
  if (!columns.length) throw new Error('请选择含普通数字的 CSV 表格')
  return { rows: rows.length, columns }
}
