import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const URLConstructor = globalThis.URL
const RequestConstructor = globalThis.Request
const HeadersConstructor = globalThis.Headers
type FetchInput = Parameters<typeof fetch>[0]

const response = (data: unknown, status = 200) => new Response(JSON.stringify({
  request_id: 'REQ_independent_education', trace_id: 'TRACE_independent_education', data,
}), { status, headers: { 'Content-Type': 'application/json' } })

const reviewRef = 'EDUREV_0123456789abcdef0123456789abcdef'
const conversationRef = 'CONV_synthetic_1'
const sourceCard = {
  chunk_id: 'CHUNK_synthetic_1', record_id: 'RECORD_synthetic_1', source_id: 'SOURCE_synthetic_1',
  title: '合成公开来源', organization: '合成机构', canonical_url: 'https://example.org/source',
  record_locator: 'section 1', source_population_scope: 'general population', source_language: 'en',
  license: 'CC BY 4.0', license_url: 'https://creativecommons.org/licenses/by/4.0/', attribution: 'synthetic attribution',
  excerpt_sha256: 'a'.repeat(64), excerpt_text: '公开来源摘录', consumer_age_min: 14, consumer_age_max: 17,
}
const citation = {
  citation_id: 'CITE_synthetic_1', chunk_id: sourceCard.chunk_id, document_id: 'DOC_synthetic_1',
  title: sourceCard.title, organization: sourceCard.organization, locator: sourceCard.record_locator,
  rank: 1, source_version: '1', source_hash: `sha256:${sourceCard.excerpt_sha256}`,
}
const publishedContent = {
  title: '一般教育信息', body: '仅供合成演示。', citations: [citation], source_cards: [sourceCard], published_at: '2026-10-16T10:00:00Z',
}
const studentReview = {
  review_ref: reviewRef, status: 'PUBLISHED', state_version: 4, created_at: '2026-10-16T08:00:00Z',
  updated_at: '2026-10-16T10:00:00Z', reviewer_ref: 'MEMROLE_synthetic_1', published_content: publishedContent,
}
const provenance = {
  purpose: 'RESEARCH_SIMULATION', research_only: true, source_study_ref: 'STUDY_synthetic',
  source_package_ref: 'PACKAGE_synthetic', source_manifest_sha256: 'b'.repeat(64), retrieval_id: 'RETR_synthetic',
  retrieval_bundle_sha256: 'c'.repeat(64), prompt_id: 'PROMPT_synthetic', prompt_version: '1.0.0', prompt_sha256: null,
  model_id: 'MODEL_synthetic', logical_model_id: 'LOGICAL_synthetic', model_version: '1.0', model_digest_sha256: 'd'.repeat(64),
  runtime_version: 'runtime-synthetic', trace_id: 'TRACE_synthetic', input_safety_action: 'PROCEED', input_safety_reason_codes: [],
  retrieval_safety_action: 'PROCEED', retrieval_safety_reason_codes: [], output_safety_action: 'PROCEED',
  output_safety_reason_codes: [], claim_boundary_status: 'ACCEPTED', citation_binding_status: 'BOUND',
}
const candidate = {
  schema_version: 'independent-research-education-candidate.v1',
  content: { summary: '原始候选摘要', observations: [], suggestions: [], disclaimer: '仅供研究演示。' },
  citations: [citation], source_cards: [sourceCard], provenance,
}
const specialistDetail = {
  review_ref: reviewRef, status: 'SHARED', state_version: 2, created_at: '2026-10-16T08:00:00Z',
  updated_at: '2026-10-16T09:00:00Z', shared_at: '2026-10-16T09:00:00Z', candidate, reviewed_draft: null,
}

async function loadService(handler: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  vi.resetModules()
  vi.stubEnv('MODE', 'production')
  vi.stubEnv('VITE_API_MODE', 'real')
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8088')
  const observed: Array<{ url: string; init: RequestInit }> = []
  const fetchMock = vi.fn(async (input: FetchInput, init?: RequestInit) => {
    const request = input instanceof RequestConstructor ? input : null
    const url = typeof input === 'string' ? input : input instanceof URLConstructor ? input.toString() : input.url
    const normalizedInit: RequestInit = init ?? (request ? {
      method: request.method,
      headers: request.headers,
      credentials: request.credentials,
      body: request.method === 'GET' || request.method === 'HEAD' ? undefined : await request.clone().text(),
    } : {})
    observed.push({ url, init: normalizedInit })
    return handler(url, normalizedInit)
  })
  vi.stubGlobal('fetch', fetchMock)
  const module = await import('@/services/independent-education-reviews')
  return { ...module, fetchMock, observed }
}

beforeEach(() => { vi.stubGlobal('crypto', { randomUUID: () => 'synthetic-key' }) })
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.resetModules() })

describe('independent education review service', () => {
  it('maps student pages with published content only and sends exact consent/version body', async () => {
    const { StudentIndependentEducationReviewService, observed } = await loadService((url, init) => {
      const path = new URLConstructor(url).pathname
      if (path === '/api/v1/auth/csrf') return response({ csrf_token: 'csrf-synthetic' })
      if (path.endsWith('/education-reviewers')) return response({ items: [{ reviewer_ref: 'MEMROLE_synthetic_1', display_name: '合成心理老师' }], offset: 0, limit: 20, total: 1, has_more: false })
      if (init?.method === 'POST') return response({ education_review: { ...studentReview, status: 'SHARED', state_version: 2, published_content: null } })
      return response({ items: [studentReview], offset: 0, limit: 20, total: 1, has_more: false })
    })
    const service = new StudentIndependentEducationReviewService()
    const page = await service.list(conversationRef)
    const reviewers = await service.listReviewers(conversationRef)
    const shared = await service.share(conversationRef, { ...page.items[0]!, status: 'HELD', state_version: 1, reviewer_ref: null, published_content: null }, reviewers.items[0]!.reviewer_ref, 'share-key')

    expect(page.items[0]?.published_content?.body).toBe('仅供合成演示。')
    expect(reviewers.items[0]?.display_name).toBe('合成心理老师')
    expect(shared.status).toBe('SHARED')
    const post = observed.find((item) => item.init.method === 'POST')!
    expect(new URLConstructor(post.url).pathname).toContain(`/education-reviews/${reviewRef}/share`)
    const postHeaders = new HeadersConstructor(post.init.headers)
    expect(postHeaders.get('X-CSRF-Token')).toBe('csrf-synthetic')
    expect(postHeaders.get('Idempotency-Key')).toBe('share-key')
    expect(JSON.parse(String(await post.init?.body))).toEqual({ expected_version: 1, reviewer_ref: 'MEMROLE_synthetic_1', consent: true })
  })

  it('rejects any nonpublished student payload containing candidate or reviewer content', async () => {
    const { StudentIndependentEducationReviewService } = await loadService(() => response({
      items: [{ ...studentReview, status: 'HELD', published_content: null, candidate }], offset: 0, limit: 20, total: 1, has_more: false,
    }))
    await expect(new StudentIndependentEducationReviewService().list(conversationRef)).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })

  it('maps assigned specialist detail while preserving original content and validated source pins', async () => {
    const { SpecialistIndependentEducationReviewService } = await loadService(() => response(specialistDetail))
    const detail = await new SpecialistIndependentEducationReviewService().get(reviewRef)
    expect(detail.candidate.content.summary).toBe('原始候选摘要')
    expect(detail.candidate.provenance.prompt_sha256).toBeNull()
    expect(detail.candidate.source_cards[0]?.excerpt_sha256).toBe(sourceCard.excerpt_sha256)
    expect(detail.reviewed_draft).toBeNull()
  })

  it('rejects an unknown specialist detail field and a citation/source mismatch', async () => {
    const { SpecialistIndependentEducationReviewService } = await loadService(() => response({ ...specialistDetail, conversation_ref: conversationRef }))
    await expect(new SpecialistIndependentEducationReviewService().get(reviewRef)).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })

    const mismatch = { ...specialistDetail, candidate: { ...candidate, citations: [{ ...citation, chunk_id: 'CHUNK_other' }] } }
    const second = await loadService(() => response(mismatch))
    await expect(new second.SpecialistIndependentEducationReviewService().get(reviewRef)).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })
})
