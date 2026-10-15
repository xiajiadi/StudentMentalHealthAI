import { afterEach, describe, expect, it, vi } from 'vitest'

const ResponseConstructor = globalThis.Response
const URLConstructor = globalThis.URL
type TestRequest = InstanceType<typeof globalThis.Request>

const review = {
  package_status: 'ENGINEERING_REVIEWED_RESEARCH_ONLY', reviewer_kind: 'AI_ENGINEERING',
  review_status: 'pending', professional_approval: false,
  ethics_approval: false, clinical_approval: false, psychometric_approval: false,
  publication_eligible: false, production_use: false,
}
const summary = {
  source_ref: 'SRC_POLICY',
  title: 'Policy source',
  organization: 'Public agency',
  publication_date: '2024',
  canonical_url: 'https://example.org/policy',
  source_population_scope: 'Adolescents in the source policy scope',
  source_language: 'English',
  layers: ['policy'],
  rights_status: 'VERIFIED_WITH_CONDITIONS',
  retrieval_eligible: true,
}
const detail = {
  ...summary,
  license: 'CC BY 4.0',
  license_url: 'https://creativecommons.org/licenses/by/4.0/',
  attribution: 'Public agency, CC BY 4.0',
  rights_evidence_url: 'https://example.org/policy/rights',
  rights_evidence_sha256: 'a'.repeat(64),
  rights_scope_note: 'Noncommercial use with attribution',
  source_capture_sha256: null,
  review,
}
const page = {
  schema_version: 'school.research-source-catalog.v1',
  source_package_ref: 'student-source-package-r3',
  manifest_sha256: 'b'.repeat(64),
  study_ref: 'school-source-study',
  consumer_age_min: 14,
  consumer_age_max: 17,
  review,
  items: [summary],
  total: 1,
  limit: 20,
  offset: 0,
  has_more: false,
}

const envelope = (data: unknown, status = 200) => new ResponseConstructor(
  JSON.stringify({ request_id: 'REQ_sources', trace_id: 'TRACE_sources', data }),
  { status, headers: { 'Content-Type': 'application/json' } },
)

async function createProvider(handler: (request: TestRequest) => Response | Promise<Response>) {
  vi.resetModules()
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8088')
  const fetchMock = vi.fn((request: TestRequest) => handler(request))
  vi.stubGlobal('fetch', fetchMock)
  const { RealApiProvider } = await import('@/services/real-api')
  return { provider: new RealApiProvider(), fetchMock }
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('RealApiProvider research source catalog', () => {
  it('uses the fixed read-only routes and maps the exact catalogue projection', async () => {
    const { provider, fetchMock } = await createProvider((request) => {
      const url = new URLConstructor(request.url)
      expect(request.method).toBe('GET')
      if (url.pathname.endsWith('/catalog')) {
        expect(url.pathname).toBe('/api/v1/school/research-sources/catalog')
        expect(url.searchParams.get('limit')).toBe('20')
        expect(url.searchParams.get('offset')).toBe('0')
        return envelope(page)
      }
      expect(url.pathname).toBe('/api/v1/school/research-sources/SRC_POLICY')
      return envelope(detail)
    })

    await expect(provider.listResearchSourceCatalog()).resolves.toMatchObject({ data: page })
    await expect(provider.getResearchSource('SRC_POLICY')).resolves.toMatchObject({ data: detail })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('rejects added source fields instead of exposing file paths or source excerpt text', async () => {
    const { provider } = await createProvider(() => envelope({
      ...detail,
      source_path: 'private/local/path',
      excerpt_text: 'source body',
    }))
    await expect(provider.getResearchSource('SRC_POLICY')).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })

  it('rejects unsafe links, invented approvals, or a retrieval flag inconsistent with rights state', async () => {
    const unsafeUrl = await createProvider(() => envelope({ ...detail, canonical_url: 'javascript:alert(1)' }))
    await expect(unsafeUrl.provider.getResearchSource('SRC_POLICY')).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })

    const inventedApproval = await createProvider(() => envelope({ ...detail, review: { ...review, professional_approval: true } }))
    await expect(inventedApproval.provider.getResearchSource('SRC_POLICY')).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })

    const inconsistentRights = await createProvider(() => envelope({ ...detail, rights_status: 'PENDING', retrieval_eligible: true }))
    await expect(inconsistentRights.provider.getResearchSource('SRC_POLICY')).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })

  it('rejects a response that does not match the requested source reference', async () => {
    const { provider } = await createProvider(() => envelope({ ...detail, source_ref: 'SRC_OTHER' }))
    await expect(provider.getResearchSource('SRC_POLICY')).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })
})
