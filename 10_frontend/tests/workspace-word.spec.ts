import { strFromU8, unzipSync } from 'fflate'
import { describe, expect, it } from 'vitest'
import { workspaceWordDocument } from '@/services/workspace-word'

async function unpack(markdown: string) {
  const blob = await workspaceWordDocument(markdown)
  expect(blob.type).toBe('application/vnd.openxmlformats-officedocument.wordprocessingml.document')
  const files = unzipSync(new Uint8Array(await blob.arrayBuffer()))
  return {
    document: strFromU8(files['word/document.xml']),
    relationships: strFromU8(files['word/_rels/document.xml.rels']),
    numbering: strFromU8(files['word/numbering.xml']),
  }
}

describe('editable workspace Word export', () => {
  it('preserves Chinese headings, ordered lists, table cells and a clickable citation', async () => {
    const result = await unpack([
      '# 班级测评完成情况', '', '## 本次统计', '',
      '3. 已提交人次：42', '4. 有效参测人次：60', '',
      '| 班级 | 已提交 |', '| --- | ---: |', '| 高一 1 班 | **42** |', '',
      '[世界卫生组织｜压力](https://www.who.int/zh/news-room/questions-and-answers/item/stress)',
    ].join('\n'))
    expect(result.document).toContain('<w:pStyle w:val="Title"')
    expect(result.document).toContain('<w:pStyle w:val="Heading1"')
    expect(result.document).toContain('<w:numPr>')
    expect(result.numbering).toContain('<w:start w:val="3"')
    expect(result.document).toContain('<w:tbl>')
    expect(result.document).toContain('<w:tblHeader')
    expect(result.document).toContain('高一 1 班')
    expect(result.document).toContain('世界卫生组织｜压力')
    expect(result.relationships).toContain('https://www.who.int/zh/news-room/questions-and-answers/item/stress')
  })

  it('keeps unsafe links and HTML as plain content without creating external relationships for them', async () => {
    const result = await unpack([
      '# 合成示例', '',
      '[本机文件](file:///C:/test.txt) [脚本](javascript:alert(1))', '',
      '<script>alert(1)</script>', '',
      '![图片说明](https://example.net/remote.png)',
    ].join('\n'))
    expect(result.document).toContain('本机文件')
    expect(result.document).toContain('脚本')
    expect(result.document).toContain('&lt;script&gt;')
    expect(result.document).toContain('图片说明')
    expect(result.relationships).not.toMatch(/file:|javascript:|remote\.png/)
  })
})
