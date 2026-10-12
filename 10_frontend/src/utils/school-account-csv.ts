import type { SchoolAccountImportRow, SchoolMemberRole } from '@/api/client'

export type SchoolAccountCsvErrorCode =
  | 'CSV_TOO_LARGE'
  | 'CSV_INVALID_UTF8'
  | 'CSV_MALFORMED'
  | 'CSV_INVALID_HEADER'
  | 'CSV_TOO_MANY_ROWS'
  | 'CSV_INVALID_ROW'
  | 'LOGIN_NAME_INVALID'
  | 'LOGIN_NAME_DUPLICATE'
  | 'DISPLAY_NAME_INVALID'
  | 'ROLE_INVALID'

export type SchoolAccountCsvResult =
  | { ok: true; rows: SchoolAccountImportRow[] }
  | { ok: false; code: SchoolAccountCsvErrorCode }

const maxCsvBytes = 500 * 1024
const expectedHeader = ['login_name', 'display_name', 'role']

const decodeCsv = (input: string | Uint8Array): { text: string; code?: SchoolAccountCsvErrorCode } => {
  if (typeof input === 'string') {
    if (new globalThis.TextEncoder().encode(input).byteLength > maxCsvBytes) return { text: '', code: 'CSV_TOO_LARGE' }
    return { text: input }
  }
  if (input.byteLength > maxCsvBytes) return { text: '', code: 'CSV_TOO_LARGE' }
  try {
    return { text: new globalThis.TextDecoder('utf-8', { fatal: true }).decode(input) }
  } catch {
    return { text: '', code: 'CSV_INVALID_UTF8' }
  }
}

const parseRecords = (text: string): string[][] | null => {
  const records: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false
  let quoteClosed = false
  let pendingRecord = false

  const finishField = () => {
    row.push(field)
    field = ''
    quoteClosed = false
  }
  const finishRecord = () => {
    finishField()
    records.push(row)
    row = []
    pendingRecord = false
  }

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]!
    if (char === '\uFEFF') return null
    if (quoted) {
      if (char === '"') {
        if (text[index + 1] === '"') {
          field += '"'
          index += 1
        } else {
          quoted = false
          quoteClosed = true
        }
      } else if (char === '\r') {
        if (text[index + 1] !== '\n') return null
        field += '\r\n'
        index += 1
      } else {
        field += char
      }
      pendingRecord = true
      continue
    }

    if (quoteClosed) {
      if (char === ',') {
        finishField()
        pendingRecord = true
      } else if (char === '\n') {
        finishRecord()
      } else if (char === '\r' && text[index + 1] === '\n') {
        index += 1
        finishRecord()
      } else {
        return null
      }
      continue
    }

    if (char === '"') {
      if (field !== '') return null
      quoted = true
      pendingRecord = true
    } else if (char === ',') {
      finishField()
      pendingRecord = true
    } else if (char === '\n') {
      finishRecord()
    } else if (char === '\r') {
      if (text[index + 1] !== '\n') return null
      index += 1
      finishRecord()
    } else {
      field += char
      pendingRecord = true
    }
  }

  if (quoted) return null
  if (pendingRecord || row.length > 0 || field !== '' || quoteClosed) finishRecord()
  return records
}

export function parseSchoolAccountCsv(input: string | Uint8Array): SchoolAccountCsvResult {
  const decoded = decodeCsv(input)
  if (decoded.code) return { ok: false, code: decoded.code }
  const text = decoded.text.startsWith('\uFEFF') ? decoded.text.slice(1) : decoded.text
  const records = parseRecords(text)
  if (!records || records.length === 0) return { ok: false, code: 'CSV_MALFORMED' }
  if (JSON.stringify(records[0]) !== JSON.stringify(expectedHeader)) return { ok: false, code: 'CSV_INVALID_HEADER' }
  const dataRows = records.slice(1)
  if (dataRows.length === 0 || dataRows.length > 100) return { ok: false, code: dataRows.length > 100 ? 'CSV_TOO_MANY_ROWS' : 'CSV_INVALID_ROW' }

  const seenLogins = new Set<string>()
  const rows: SchoolAccountImportRow[] = []
  for (let index = 0; index < dataRows.length; index += 1) {
    const values = dataRows[index]!
    if (values.length !== expectedHeader.length) return { ok: false, code: 'CSV_INVALID_ROW' }
    const loginName = values[0]!
    const displayName = values[1]!.trim()
    const roleText = values[2]!
    if (!/^SYNTHETIC_[A-Za-z0-9_]{1,100}$/.test(loginName)) return { ok: false, code: 'LOGIN_NAME_INVALID' }
    const normalizedLogin = loginName.toLocaleLowerCase('en-US')
    if (seenLogins.has(normalizedLogin)) return { ok: false, code: 'LOGIN_NAME_DUPLICATE' }
    seenLogins.add(normalizedLogin)
    if (!displayName || displayName.length > 120 || /[\r\n]/.test(displayName)) {
      return { ok: false, code: 'DISPLAY_NAME_INVALID' }
    }
    if (roleText !== 'student' && roleText !== 'teacher') return { ok: false, code: 'ROLE_INVALID' }
    rows.push({ row_no: index + 1, login_name: loginName, display_name: displayName, role: roleText as SchoolMemberRole })
  }
  return { ok: true, rows }
}
