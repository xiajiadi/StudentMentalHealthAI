/* global File */

import { parseCsvRecords, readCsvText } from './csv-import'

export type RosterKind = 'student_roster' | 'staff_roster'
export type RosterAttachment = { file: File; kind: RosterKind }

export const STAFF_ROSTER_MARKER = '# psynova_staff_roster_template_v1'
export const STAFF_ROSTER_COLUMNS = ['employee_ref', 'display_name', 'role', 'class_refs']

export async function identifyRosterFile(file: File): Promise<RosterKind> {
  if (!/\.csv$/i.test(file.name)) return 'student_roster'
  try {
    const text = await readCsvText(file)
    const header = text.split(/\r\n|\r|\n/).find((line) => line.trim()) ?? ''
    if (header.trim().startsWith('# psynova_staff_roster_template_')
      || JSON.stringify(parseCsvRecords(header)[0]) === JSON.stringify(STAFF_ROSTER_COLUMNS)) {
      return 'staff_roster'
    }
  } catch {
    // Let the existing import workbench display its file validation error.
  }
  return 'student_roster'
}
