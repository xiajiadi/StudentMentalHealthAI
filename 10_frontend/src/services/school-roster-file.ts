/* global AbortSignal, File */

import { parseCsvRecords, readCsvText } from './csv-import'

export type RosterKind = 'student_roster' | 'staff_roster'
export type RosterAttachment = { file: File; kind: RosterKind }

export const STAFF_ROSTER_MARKER = '# psynova_staff_roster_template_v1'
export const STAFF_ROSTER_COLUMNS = ['employee_ref', 'display_name', 'role', 'class_refs']

export function rosterTemplateMarker(row: readonly string[] | undefined, prefix: string) {
  return row?.[0]?.startsWith(prefix) && row.slice(1).every((cell) => !cell) ? row[0] : undefined
}

function isStaffRosterHeader(row: readonly string[] | undefined) {
  return Boolean(rosterTemplateMarker(row, '# psynova_staff_roster_template_'))
    || (row?.length === STAFF_ROSTER_COLUMNS.length && STAFF_ROSTER_COLUMNS.every((column, index) => row[index] === column))
}

export async function readSchoolRosterRecords(file: File, signal: AbortSignal): Promise<string[][]> {
  if (/\.xlsx$/i.test(file.name)) {
    const { readRosterXlsx } = await import('./workspace-workbook-client')
    return await readRosterXlsx(file, signal)
  }
  if (!/\.csv$/i.test(file.name)) throw new Error('请选择 CSV 或 XLSX 名单')
  const text = await readCsvText(file)
  signal.throwIfAborted()
  return parseCsvRecords(text)
}

export async function identifyRosterFile(file: File, signal: AbortSignal): Promise<RosterKind> {
  if (/\.xlsx$/i.test(file.name)) {
    const [first] = await readSchoolRosterRecords(file, signal)
    return isStaffRosterHeader(first) ? 'staff_roster' : 'student_roster'
  }
  try {
    const text = await readCsvText(file)
    signal.throwIfAborted()
    const header = text.split(/\r\n|\r|\n/).find((line) => line.trim()) ?? ''
    if (header.trim().startsWith('# psynova_staff_roster_template_')
      || isStaffRosterHeader(parseCsvRecords(header)[0])) {
      return 'staff_roster'
    }
  } catch {
    signal.throwIfAborted()
    // Let the existing import workbench display its file validation error.
  }
  return 'student_roster'
}
