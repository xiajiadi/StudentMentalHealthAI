import { strToU8, zipSync } from 'fflate'

const main = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
const rel = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
const packageRel = 'http://schemas.openxmlformats.org/package/2006/relationships'
const contentType = 'application/vnd.openxmlformats-officedocument.spreadsheetml'

const xml = (text: string) => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;')

export function workbook(sheets: { name: string; rows: (string | number | null)[][] }[]) {
  const definitions = sheets.map(({ name }, index) =>
    `<sheet name="${xml(name)}" sheetId="${index + 1}" r:id="rId${index + 1}"/>`,
  )
  const mappings = sheets.map((_, index) =>
    `<Relationship Id="rId${index + 1}" Type="${rel}/worksheet" Target="worksheets/sheet${index + 1}.xml"/>`,
  )
  const types = sheets.map((_, index) =>
    `<Override PartName="/xl/worksheets/sheet${index + 1}.xml" ContentType="${contentType}.worksheet+xml"/>`,
  )
  const entries: Record<string, Uint8Array> = {
    '[Content_Types].xml': strToU8(
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      + `<Override PartName="/xl/workbook.xml" ContentType="${contentType}.sheet.main+xml"/>`
      + types.join('') + '</Types>',
    ),
    '_rels/.rels': strToU8(
      `<Relationships xmlns="${packageRel}"><Relationship Id="rId1" Type="${rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>`,
    ),
    'xl/workbook.xml': strToU8(`<workbook xmlns="${main}" xmlns:r="${rel}"><sheets>${definitions.join('')}</sheets></workbook>`),
    'xl/_rels/workbook.xml.rels': strToU8(`<Relationships xmlns="${packageRel}">${mappings.join('')}</Relationships>`),
  }
  sheets.forEach(({ rows }, sheetIndex) => {
    const rowsXml = rows.map((cells, rowIndex) => {
      const cellsXml = cells.map((value, columnIndex) => {
        const address = String.fromCharCode(65 + columnIndex) + (rowIndex + 1)
        if (value === null) return ''
        return typeof value === 'number'
          ? `<c r="${address}"><v>${value}</v></c>`
          : `<c r="${address}" t="inlineStr"><is><t>${xml(value)}</t></is></c>`
      })
      return `<row r="${rowIndex + 1}">${cellsXml.join('')}</row>`
    })
    entries[`xl/worksheets/sheet${sheetIndex + 1}.xml`] = strToU8(
      `<worksheet xmlns="${main}"><sheetData>${rowsXml.join('')}</sheetData></worksheet>`,
    )
  })
  return zipSync(entries)
}
