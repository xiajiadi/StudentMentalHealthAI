/* global File, TextDecoder */

export const parseCsvRecords = (text: string, strict = false): string[][] => {
  const result: string[][] = []
  let record: string[] = []; let field = ''; let quoted = false
  let quoteClosed = false
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index]!
    if (strict && quoteClosed && char !== ',' && char !== '\n' && char !== '\r') {
      if (char === ' ' || char === '\t') continue
      throw new Error('CSV 引号格式错误')
    }
    quoteClosed = false
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') { field += '"'; index += 1 }
      else if (char === '"') { quoted = false; quoteClosed = true }
      else field += char
    } else if (char === '"') {
      if (field) throw new Error('CSV 引号格式错误')
      quoted = true
    } else if (char === ',') { record.push(field.trim()); field = '' }
    else if (char === '\n' || char === '\r') {
      if (char === '\r' && text[index + 1] === '\n') index += 1
      record.push(field.trim()); field = ''
      if (record.some((value) => value)) result.push(record)
      record = []
    } else field += char
  }
  if (quoted) throw new Error('CSV 存在未闭合的引号')
  record.push(field.trim())
  if (record.some((value) => value)) result.push(record)
  return result
}

export const readCsvText = async (file: File): Promise<string> => {
  const bytes = new Uint8Array(await file.arrayBuffer())
  const decode = (encoding: string) => new TextDecoder(encoding, { fatal: true }).decode(bytes)
  if (bytes[0] === 0xff && bytes[1] === 0xfe) return decode('utf-16le')
  if (bytes[0] === 0xfe && bytes[1] === 0xff) return decode('utf-16be')
  try { return decode('utf-8') }
  catch {
    if (bytes[0] !== 0xef || bytes[1] !== 0xbb || bytes[2] !== 0xbf) {
      try { return decode('gb18030') } catch { /* Unsupported encoding */ }
    }
    throw new Error('无法读取 CSV 编码，请另存为 CSV UTF-8 后重试')
  }
}
