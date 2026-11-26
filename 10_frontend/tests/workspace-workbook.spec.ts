import { strFromU8, strToU8, unzipSync, zipSync } from 'fflate'
import { describe, expect, it } from 'vitest'
import { readWorkspaceWorkbook } from '../src/services/workspace-workbook'
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
