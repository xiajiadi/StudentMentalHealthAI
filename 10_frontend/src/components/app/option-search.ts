function normalize(value: string) {
  return value.normalize('NFKC').toLocaleLowerCase().normalize('NFD').replace(/\p{M}/gu, '')
}

export function matchesOption(text: string, query: string, reference = '') {
  const candidate = normalize(text)
  const identifier = normalize(reference)
  return normalize(query).trim().split(/\s+/).every((token) => {
    if (candidate.includes(token) || identifier.includes(token)) return true
    if (token.length < 2) return false
    let position = 0
    for (const part of token.match(/\p{N}+|[^\p{N}]/gu) ?? []) {
      const index = candidate.indexOf(part, position)
      if (index === -1) return false
      position = index + part.length
    }
    return true
  })
}
