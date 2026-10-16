import { afterEach, describe, expect, it, vi } from 'vitest'

const ResponseConstructor = globalThis.Response
const URLConstructor = globalThis.URL
type TestRequest = InstanceType<typeof globalThis.Request>

const envelope = (data: unknown) => new ResponseConstructor(
  JSON.stringify({ request_id: 'REQ_education_review', trace_id: 'TRACE_education_review', data }),
  { status: 200, headers: { 'Content-Type': 'application/json' } },
)

async function loadTransport(handler: (request: TestRequest) => Response | Promise<Response>) {
  vi.resetModules()
  vi.stubEnv('MODE', 'production')
  vi.stubEnv('VITE_API_MODE', 'real')
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8088')
  const fetchMock = vi.fn((request: TestRequest) => handler(request))
  vi.stubGlobal('fetch', fetchMock)
  const api = await import('@/services/real-api')
  return { ...api, fetchMock }
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('independent education review transport', () => {
  it('uses bounded GET routes for student and assigned specialist lists/details', async () => {
    const { RealApiProvider, fetchMock } = await loadTransport(() => envelope({ items: [], offset: 20, limit: 20, total: 0, has_more: false }))
    const provider = new RealApiProvider()
    const conversation = 'CONV_synthetic_1'
    const review = 'EDUREV_0123456789abcdef0123456789abcdef'

    await provider.requestIndependentEducationReview({
      method: 'GET', path: `/api/v1/student/research-conversations/${conversation}/education-reviews`, query: { offset: 20, limit: 20 },
    })
    await provider.requestIndependentEducationReview({
      method: 'GET', path: `/api/v1/student/research-conversations/${conversation}/education-reviewers`, query: { offset: 0, limit: 20 },
    })
    await provider.requestIndependentEducationReview({
      method: 'GET', path: '/api/v1/school/independent-education-reviews', query: { offset: 0, limit: 20 },
    })
    await provider.requestIndependentEducationReview({
      method: 'GET', path: `/api/v1/school/independent-education-reviews/${review}`,
    })

    const requests = fetchMock.mock.calls.map(([request]) => request)
    expect(requests).toHaveLength(4)
    expect(new URLConstructor(requests[0]!.url).pathname).toBe(`/api/v1/student/research-conversations/${conversation}/education-reviews`)
    expect(new URLConstructor(requests[0]!.url).search).toBe('?offset=20&limit=20')
    expect(new URLConstructor(requests[1]!.url).pathname).toBe(`/api/v1/student/research-conversations/${conversation}/education-reviewers`)
    expect(new URLConstructor(requests[2]!.url).pathname).toBe('/api/v1/school/independent-education-reviews')
    expect(new URLConstructor(requests[3]!.url).pathname).toBe(`/api/v1/school/independent-education-reviews/${review}`)
    expect(requests.every((request) => request.method === 'GET' && request.credentials === 'include')).toBe(true)
  })

  it('requires CSRF and an idempotency key for exact share, withdraw, draft, publish, and revoke paths', async () => {
    const { RealApiProvider, fetchMock } = await loadTransport((request) => {
      if (new URLConstructor(request.url).pathname === '/api/v1/auth/csrf') return envelope({ csrf_token: 'csrf-synthetic' })
      return envelope({ education_review: { review_ref: 'EDUREV_0123456789abcdef0123456789abcdef' } })
    })
    const provider = new RealApiProvider()
    const conversation = 'CONV_synthetic_1'
    const review = 'EDUREV_0123456789abcdef0123456789abcdef'
    const routes = [
      { path: `/api/v1/student/research-conversations/${conversation}/education-reviews/${review}/share`, body: { expected_version: 1, reviewer_ref: 'ROLE_synthetic', consent: true } },
      { path: `/api/v1/student/research-conversations/${conversation}/education-reviews/${review}/withdraw`, body: { expected_version: 2 } },
      { path: `/api/v1/school/independent-education-reviews/${review}/draft`, body: { expected_version: 2, title: '合成标题', body: '合成正文' } },
      { path: `/api/v1/school/independent-education-reviews/${review}/publish`, body: { expected_version: 3 } },
      { path: `/api/v1/school/independent-education-reviews/${review}/revoke`, body: { expected_version: 4 } },
    ]

    for (const [index, route] of routes.entries()) {
      await provider.requestIndependentEducationReview({ method: 'POST', ...route, idempotencyKey: `education-review-${index}` })
    }

    const mutations = fetchMock.mock.calls.map(([request]) => request).filter((request) => request.method === 'POST')
    expect(mutations).toHaveLength(5)
    for (const [index, request] of mutations.entries()) {
      expect(request.credentials).toBe('include')
      expect(request.headers.get('X-CSRF-Token')).toBe('csrf-synthetic')
      expect(request.headers.get('Idempotency-Key')).toBe(`education-review-${index}`)
      await expect(request.clone().json()).resolves.toEqual(routes[index]!.body)
    }
  })

  it('rejects wrong methods, malformed refs, and unrelated routes before network access', async () => {
    const { RealApiProvider, fetchMock } = await loadTransport(() => envelope({}))
    const provider = new RealApiProvider()
    const invalid = [
      { method: 'GET' as const, path: '/api/v1/student/research-conversations/CONV_bad/education-reviews/EDUREV_0123456789abcdef0123456789abcdef/share' },
      { method: 'POST' as const, path: '/api/v1/student/research-conversations/CONV_synthetic_1/education-reviewers', idempotencyKey: 'key' },
      { method: 'GET' as const, path: '/api/v1/school/independent-education-reviews/EDUREV_0123456789abcdef0123456789abcdef/publish' },
      { method: 'POST' as const, path: '/api/v1/school/independent-education-reviews/EDUREV_bad/draft', idempotencyKey: 'key' },
      { method: 'GET' as const, path: '/api/v1/school/independent-education-reviews/../auth/me' },
    ]
    for (const request of invalid) {
      await expect(provider.requestIndependentEducationReview(request)).rejects.toMatchObject({ code: 'API_INVALID_REQUEST' })
    }
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
