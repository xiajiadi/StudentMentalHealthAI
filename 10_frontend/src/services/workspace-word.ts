/* global Blob, URL */
import {
  AlignmentType, BorderStyle, Document, ExternalHyperlink, HeadingLevel, LevelFormat,
  Packer, Paragraph, Table, TableCell, TableLayoutType, TableRow, TextRun, VerticalAlignTable,
  WidthType, type ILevelOptions, type IParagraphOptions, type IRunOptions, type ParagraphChild,
} from 'docx'
import { marked, type Token, type Tokens } from 'marked'

const page = { width: 12_240, height: 15_840 }
const margin = { top: 1_100, bottom: 1_100, left: 1_100, right: 1_100 }
const textWidth = page.width - margin.left - margin.right
const font = { ascii: 'Calibri', hAnsi: 'Calibri', eastAsia: 'Microsoft YaHei' }
const headingLevels = [
  HeadingLevel.HEADING_1, HeadingLevel.HEADING_1, HeadingLevel.HEADING_2,
  HeadingLevel.HEADING_3, HeadingLevel.HEADING_4, HeadingLevel.HEADING_5, HeadingLevel.HEADING_6,
] as const

function xmlText(value: string) {
  // XML 1.0 cannot store these literal characters in a text node.
  // eslint-disable-next-line no-control-regex
  return value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\uD800-\uDFFF\uFFFE\uFFFF]/gu, '')
}

function sourceLink(href: string) {
  try {
    const url = new URL(href)
    if (['http:', 'https:'].includes(url.protocol) && url.hostname && !url.username && !url.password) {
      return url.href
    }
  } catch { /* Relative and malformed destinations stay as text. */ }
}

function inline(tokens: Token[], style: IRunOptions = {}): ParagraphChild[] {
  return tokens.flatMap((token): ParagraphChild[] => {
    switch (token.type) {
      case 'strong': return inline((token as Tokens.Strong).tokens, { ...style, bold: true })
      case 'em': return inline((token as Tokens.Em).tokens, { ...style, italics: true })
      case 'del': return inline((token as Tokens.Del).tokens, { ...style, strike: true })
      case 'br': return [new TextRun({ break: 1 })]
      case 'link': {
        const { href, tokens: label } = token as Tokens.Link
        const link = sourceLink(href)
        if (!link) return inline(label, style)
        return [new ExternalHyperlink({
          link, children: inline(label, { ...style, style: 'Hyperlink' }),
        })]
      }
      case 'codespan':
        return [new TextRun({ ...style, font: { ...font, ascii: 'Consolas', hAnsi: 'Consolas' },
          text: xmlText((token as Tokens.Codespan).text) })]
      default: {
        const text = 'text' in token && typeof token.text === 'string' ? token.text : token.raw
        return [new TextRun({ ...style, text: xmlText(text).replace(/\r?\n/g, ' ') })]
      }
    }
  })
}

function textRuns(token: Token, style?: IRunOptions): ParagraphChild[] {
  return 'tokens' in token && Array.isArray(token.tokens) ? inline(token.tokens, style)
    : inline([token], style)
}

function wordTable(table: Tokens.Table) {
  const rows = [table.header, ...table.rows]
  const weight = table.header.map((_, index) => Math.min(24, Math.max(5, ...rows.map((row) =>
    Array.from(row[index]?.text ?? '').length))))
  const totalWeight = weight.reduce((sum, value) => sum + value, 0)
  const minimum = Math.min(1050, Math.floor(textWidth / weight.length))
  const flexibleWidth = textWidth - minimum * weight.length
  const widths = weight.map((value) => minimum + Math.floor(flexibleWidth * value / totalWeight))
  widths[widths.length - 1] += textWidth - widths.reduce((sum, value) => sum + value, 0)
  const border = { style: BorderStyle.SINGLE, size: 4, color: 'D9D9D9' }
  return new Table({
    layout: TableLayoutType.FIXED,
    width: { size: textWidth, type: WidthType.DXA },
    columnWidths: widths,
    margins: { top: 90, bottom: 90, left: 125, right: 125 },
    borders: {
      top: border, bottom: border, left: border, right: border,
      insideHorizontal: border, insideVertical: border,
    },
    rows: rows.map((row, rowIndex) => new TableRow({
      tableHeader: rowIndex === 0,
      children: widths.map((width, column) => new TableCell({
        width: { size: width, type: WidthType.DXA },
        verticalAlign: VerticalAlignTable.CENTER,
        ...(rowIndex === 0 ? { shading: { fill: 'E8EEF7' } } : {}),
        children: [new Paragraph({
          style: 'ReportTableText',
          alignment: table.align[column] === 'right' ? AlignmentType.RIGHT
            : table.align[column] === 'center' ? AlignmentType.CENTER : AlignmentType.LEFT,
          children: inline(row[column]?.tokens ?? [], { bold: rowIndex === 0 }),
        })],
      })),
    })),
  })
}

type Numbering = { reference: string; levels: ILevelOptions[] }[]
type Block = Paragraph | Table

function listBlocks(list: Tokens.List, numbering: Numbering, depth: number): Block[] {
  const reference = `report-list-${numbering.length}`
  const left = 420 + 325 * depth
  numbering.push({ reference, levels: [{
    level: 0,
    start: typeof list.start === 'number' ? list.start : 1,
    format: list.ordered ? LevelFormat.DECIMAL : LevelFormat.BULLET,
    text: list.ordered ? '%1.' : '•',
    alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left, hanging: 265 } } },
  }] })
  return list.items.flatMap((item): Block[] => {
    const tokens = item.tokens.filter((token) => token.type !== 'space' && token.type !== 'checkbox')
    const first = tokens[0]
    const hasOpening = first?.type === 'text' || first?.type === 'paragraph'
    const opening = new Paragraph({
      numbering: { reference, level: 0 },
      children: [
        ...(item.task ? [new TextRun(item.checked ? '☑ ' : '☐ ')] : []),
        ...(hasOpening ? textRuns(first) : []),
      ],
    })
    return [opening, ...blocks(hasOpening ? tokens.slice(1) : tokens, numbering, depth + 1)]
  })
}

function blocks(tokens: Token[], numbering: Numbering, depth = 0): Block[] {
  const result: Block[] = []
  const first = tokens.find((token) => !['space', 'def', 'hr'].includes(token.type))
  const hasTitle = depth === 0 && first?.type === 'heading' && (first as Tokens.Heading).depth === 1
  for (const token of tokens) {
    if (token.type === 'space' || token.type === 'def' || token.type === 'hr') continue
    if (token.type === 'list') {
      result.push(...listBlocks(token as Tokens.List, numbering, depth))
      continue
    }
    if (token.type === 'table') {
      result.push(wordTable(token as Tokens.Table))
      continue
    }
    if (token.type === 'blockquote') {
      result.push(...blocks((token as Tokens.Blockquote).tokens, numbering, depth + 1))
      continue
    }
    const paragraph: IParagraphOptions = depth ? { indent: { left: depth * 325 } } : {}
    if (token.type === 'heading') {
      const { depth: level, tokens: contents } = token as Tokens.Heading
      result.push(new Paragraph({
        ...paragraph,
        heading: hasTitle && token === first ? HeadingLevel.TITLE
          : headingLevels[Math.max(1, level - Number(hasTitle))] || HeadingLevel.HEADING_6,
        children: inline(contents),
      }))
    } else if (token.type === 'code') {
      const lines = xmlText((token as Tokens.Code).text).split(/\r?\n/)
      result.push(new Paragraph({
        ...paragraph, style: 'ReportCode',
        children: lines.map((text, index) => new TextRun({ text, break: index > 0 ? 1 : 0 })),
      }))
    } else {
      result.push(new Paragraph({ ...paragraph, children: textRuns(token) }))
    }
  }
  return result
}

function headingStyle(size: number, before: number, after: number) {
  return {
    run: { font, size, bold: true, color: '000000' },
    paragraph: { keepNext: true, spacing: { before, after } },
  }
}

export async function workspaceWordDocument(markdown: string): Promise<Blob> {
  if (!markdown.trim() || markdown.length > 8_000) throw new Error('Invalid report size')
  const numbering: Numbering = []
  const content = blocks(marked.lexer(markdown, { gfm: true }), numbering)
  if (!content.length) throw new Error('Empty report')
  const document = new Document({
    creator: 'PsyNova',
    numbering: { config: numbering },
    styles: {
      default: {
        document: { run: { font, size: 22, color: '000000' }, paragraph: { spacing: { after: 130, line: 330 } } },
        title: headingStyle(40, 0, 300),
        heading1: headingStyle(30, 250, 130),
        heading2: headingStyle(26, 190, 110),
        heading3: headingStyle(24, 150, 100),
        heading4: headingStyle(23, 150, 100),
        heading5: headingStyle(22, 150, 100),
        heading6: headingStyle(22, 150, 100),
      },
      paragraphStyles: [
        { id: 'ReportTableText', name: 'Table text', basedOn: 'Normal',
          paragraph: { spacing: { before: 0, after: 0, line: 290 } }, run: { font, size: 21 } },
        { id: 'ReportCode', name: 'Code', basedOn: 'Normal',
          run: { font: { ...font, ascii: 'Consolas', hAnsi: 'Consolas' }, size: 21 } },
      ],
    },
    sections: [{ properties: { page: { size: page, margin } }, children: content }],
  })
  return Packer.toBlob(document)
}
