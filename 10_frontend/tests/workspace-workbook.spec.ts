import { strFromU8, strToU8, unzipSync, zipSync } from 'fflate'
import { describe, expect, it } from 'vitest'
import { readRosterWorkbook, readWorkspaceWorkbook } from '../src/services/workspace-workbook'
import { rosterTemplateMarker, STAFF_ROSTER_COLUMNS, STAFF_ROSTER_MARKER } from '../src/services/school-roster-file'
import { workbook } from './fixtures/workbook'

describe('workspace workbook analysis', () => {
  it('returns local summaries for the usable sheets, leaving text identifiers out of calculations', async () => {
    const file = workbook([
      { name: 'Instructions', rows: [['Notes'], ['Read the second sheet']] },
      { name: '练习', rows: [['编号', '时间'], ['0007', 12], ['0008', -3], ['0009', '30'], ['0010', 9]] },
      { name: '班会', rows: [['项目数'], [0], [18]] },
    ])
    const result = await readWorkspaceWorkbook(file.buffer)
    expect(result).toEqual([
      { name: '练习', table: { rows: 4, columns: [
        { column: 2, label: '时间', count: 3, min: -3, max: 12, mean: 6, sum: 18 },
      ] } },
      { name: '班会', table: { rows: 2, columns: [
        { column: 1, label: '项目数', count: 2, min: 0, max: 18, mean: 9, sum: 18 },
      ] } },
    ])
  })

  it('rejects sparse coordinates beyond the processing limit before materializing rows', async () => {
    const entries = unzipSync(workbook([{ name: 'Sparse', rows: [['Values'], [42]] }]))
    const path = 'xl/worksheets/sheet1.xml'
    entries[path] = strToU8(strFromU8(entries[path]).replace('r="2"', 'r="1048576"').replace('r="A2"', 'r="A1048576"'))
    await expect(readWorkspaceWorkbook(zipSync(entries).buffer)).rejects.toThrow('每表 40 列和 2000 行')
  })

  it('rejects XML parts with excessive expanded size even when the workbook is small on disk', async () => {
    const entries = unzipSync(workbook([{ name: 'Expanded', rows: [['Values'], [42]] }]))
    entries['xl/extra.xml'] = strToU8('<data>' + 'a'.repeat(9 * 1024 * 1024) + '</data>')
    const file = zipSync(entries)
    expect(file.byteLength).toBeLessThan(2 * 1024 * 1024)
    await expect(readWorkspaceWorkbook(file.buffer)).rejects.toThrow('请选择内容更少的 XLSX 文件')
  })
})

describe('private roster workbook', () => {
  it('reads only the first sheet, keeping a text identifier and an empty class cell', async () => {
    const file = workbook([
      { name: '教职工', rows: [
        [STAFF_ROSTER_MARKER],
        STAFF_ROSTER_COLUMNS,
        ['0007', '合成教师', 'teacher', 'C1|C2'],
        ['0008', '合成心理教师', 'psychological_specialist', null],
      ] },
      { name: '说明', rows: [['不属于名单的私有备注'], [900]] },
    ])
    const records = await readRosterWorkbook(file.buffer)
    expect(rosterTemplateMarker(records[0], '# psynova_staff_roster_template_')).toBe(STAFF_ROSTER_MARKER)
    expect(records.slice(1)).toEqual([
      STAFF_ROSTER_COLUMNS,
      ['0007', '合成教师', 'teacher', 'C1|C2'],
      ['0008', '合成心理教师', 'psychological_specialist', ''],
    ])
  })

  it('keeps the 3000 data rows allowed by the existing import workflow', async () => {
    const staff = Array.from({ length: 3000 }, (_, index) => [`EMP-${index}`, '合成教师', 'teacher', 'C1'])
    const file = workbook([{ name: '教职工', rows: [[STAFF_ROSTER_MARKER], STAFF_ROSTER_COLUMNS, ...staff] }])
    await expect(readRosterWorkbook(file.buffer)).resolves.toHaveLength(3002)
    const larger = workbook([{ name: '教职工', rows: [[STAFF_ROSTER_MARKER], STAFF_ROSTER_COLUMNS, ...staff, staff[0]] }])
    await expect(readRosterWorkbook(larger.buffer)).rejects.toThrow('最多 3000 条记录')
  })
})
