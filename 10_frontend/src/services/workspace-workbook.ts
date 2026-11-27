/* global TextDecoder */

import { unzipSync, zipSync } from 'fflate'
import readXlsxFile, { readSheet } from 'read-excel-file/universal'
import { Parser } from 'saxen'
import {
  ROSTER_WORKBOOK_BYTES, ROSTER_WORKBOOK_FILE_LIMIT, SCHOOL_ROSTER_ROWS, summarizeWorkspaceRows, WORKBOOK_BYTES,
  WORKBOOK_CONTENT_LIMIT, WORKBOOK_FILE_LIMIT, WORKBOOK_INVALID,
  WORKSPACE_TABLE_COLUMNS, WORKSPACE_TABLE_ROWS, type LocalWorkspaceSheet, type WorkbookMode,
} from './workspace-table'

const EXPANDED_BYTES = 8 * 1024 * 1024
const WORKBOOK_PARTS = 200
const WORKBOOK_SHEETS = 8
const WORKBOOK_LIMIT = '请选择最多 8 个工作表、每表 40 列和 2000 行数据的 XLSX'
const ROSTER_WORKBOOK_LIMIT = '请选择最多 3000 条记录、每表不超过 40 列的 XLSX 名单'
const NO_NUMERIC_SHEETS = '请选择含数字单元格的 XLSX 工作表'
const UNSAFE_PARTS = new Set(['.', '..', '__proto__', 'constructor', 'prototype'])
const WORKBOOK_ERRORS = new Set([
  WORKBOOK_INVALID, WORKBOOK_FILE_LIMIT, WORKBOOK_LIMIT, WORKBOOK_CONTENT_LIMIT, NO_NUMERIC_SHEETS,
  ROSTER_WORKBOOK_FILE_LIMIT, ROSTER_WORKBOOK_LIMIT,
])

export function workbookError(error: unknown): string {
  return error instanceof Error && WORKBOOK_ERRORS.has(error.message) ? error.message : WORKBOOK_INVALID
}

function validateSheetCoordinates(xml: string, rowLimit: number, limitMessage: string): number {
  const parser = new Parser()
  let dataSections = 0
  let rowCount = 0
  parser.on('error', () => { throw new Error(WORKBOOK_INVALID) })
  parser.on('openTag', (qualifiedName, getAttributes, decode) => {
    const name = qualifiedName.slice(qualifiedName.lastIndexOf(':') + 1)
    if (name === 'sheetData') dataSections++
    if (!dataSections || (name !== 'row' && name !== 'c')) return

    // The reader materializes gaps in row and column coordinates as empty cells.
    const attributes = getAttributes()
    const refs = Object.keys(attributes).filter((key) => key === 'r' || key.endsWith(':r'))
    if (refs.length > 1) throw new Error(WORKBOOK_INVALID)
    const address = refs.length ? decode(attributes[refs[0]] ?? '') : ''
    if (name === 'row') {
      rowCount++
      if (rowCount > rowLimit || (address && (
        !/^[1-9][0-9]{0,3}$/.test(address) || Number(address) > rowLimit
      ))) throw new Error(limitMessage)
      return
    }
    const match = /^([A-Z]{1,2})([1-9][0-9]{0,3})$/.exec(address)
    if (!match) throw new Error(limitMessage)
    const column = [...match[1]].reduce((value, character) => value * 26 + character.charCodeAt(0) - 64, 0)
    if (column > WORKSPACE_TABLE_COLUMNS || Number(match[2]) > rowLimit) {
      throw new Error(limitMessage)
    }
  })
  parser.parse(xml)
  return dataSections
}

function openBoundedWorkbook(buffer: ArrayBuffer, mode: WorkbookMode) {
  const roster = mode === 'roster'
  const bytes = roster ? ROSTER_WORKBOOK_BYTES : WORKBOOK_BYTES
  const fileError = roster ? ROSTER_WORKBOOK_FILE_LIMIT : WORKBOOK_FILE_LIMIT
  const rowLimit = roster ? SCHOOL_ROSTER_ROWS + 2 : WORKSPACE_TABLE_ROWS + 1
  const sectionLimit = roster ? WORKBOOK_PARTS : WORKBOOK_SHEETS
  const limitMessage = roster ? ROSTER_WORKBOOK_LIMIT : WORKBOOK_LIMIT
  if (!buffer.byteLength || buffer.byteLength > bytes) throw new Error(fileError)
  const seen = new Set<string>()
  let expanded = 0
  const entries = unzipSync(new Uint8Array(buffer), {
    filter(entry) {
      const { name, compression, size, originalSize } = entry
      if (!name || name.startsWith('/') || name.includes('\\') || seen.has(name)
        || name.split('/').some((part) => UNSAFE_PARTS.has(part))
        || (compression !== 0 && compression !== 8)
        || (compression === 0 && size !== originalSize)) throw new Error(WORKBOOK_INVALID)
      seen.add(name)
      if (seen.size > WORKBOOK_PARTS) throw new Error(WORKBOOK_CONTENT_LIMIT)
      if (!name.endsWith('.xml') && !name.endsWith('.xml.rels')) return false
      expanded += originalSize
      if (expanded > EXPANDED_BYTES) throw new Error(WORKBOOK_CONTENT_LIMIT)
      return true
    },
  })
  if (!Object.hasOwn(entries, '[Content_Types].xml')) throw new Error(WORKBOOK_INVALID)
  const decoder = new TextDecoder()
  let sections = 0
  for (const entry of Object.values(entries)) {
    sections += validateSheetCoordinates(decoder.decode(entry), rowLimit, limitMessage)
    if (sections > sectionLimit) throw new Error(limitMessage)
  }
  // Stored ZIP entries let the existing reader reuse the bounded content without spawning
  // independent decompression workers. It handles shared strings, styles and sheet mappings.
  return zipSync(entries, { level: 0 }).buffer
}

export async function readRosterWorkbook(buffer: ArrayBuffer): Promise<string[][]> {
  const rows = await readSheet(openBoundedWorkbook(buffer, 'roster'))
  return rows.map((row) => row.map((cell) => cell == null ? '' : String(cell).trim()))
}

export async function readWorkspaceWorkbook(buffer: ArrayBuffer): Promise<LocalWorkspaceSheet[]> {
  const sheets = await readXlsxFile(openBoundedWorkbook(buffer, 'statistics'))
  if (sheets.length > WORKBOOK_SHEETS) throw new Error(WORKBOOK_LIMIT)
  const result: LocalWorkspaceSheet[] = []
  for (const sheet of sheets) {
    const [header, ...rows] = sheet.data
    if (!header?.length || !rows.length) continue
    if (header.length > WORKSPACE_TABLE_COLUMNS || rows.length > WORKSPACE_TABLE_ROWS) {
      throw new Error(WORKBOOK_LIMIT)
    }
    const table = summarizeWorkspaceRows(header, rows, (cell) => typeof cell === 'number' ? cell : NaN)
    if (table.columns.length) result.push({ name: sheet.sheet.slice(0, 160), table })
  }
  if (!result.length) throw new Error(NO_NUMERIC_SHEETS)
  return result
}
