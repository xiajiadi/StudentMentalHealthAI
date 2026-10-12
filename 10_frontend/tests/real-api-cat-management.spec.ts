import { afterEach, describe, expect, it, vi } from 'vitest'

const ResponseConstructor = globalThis.Response
const URLConstructor = globalThis.URL
type TestRequest = InstanceType<typeof globalThis.Request>
const envelope = (data: unknown) => new ResponseConstructor(JSON.stringify({
  request_id: 'REQ_cat', trace_id: 'TRACE_cat', data,
}), { status: 200, headers: { 'Content-Type': 'application/json' } })

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('CAT management shared transport', () => {
  it('uses CSRF without a mutation key for stateless saved-version computation', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8088')
    const paths: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (request: TestRequest) => {
      const path = new URLConstructor(request.url).pathname
      paths.push(path)
      if (path === '/api/v1/auth/csrf') return envelope({ csrf_token: 'csrf_saved_test' })
      expect(path).toBe('/api/v1/school/cat-assets/plan-versions/CPVER_demo/simulations')
      expect(request.method).toBe('POST')
      expect(request.credentials).toBe('include')
      expect(request.headers.get('X-CSRF-Token')).toBe('csrf_saved_test')
      expect(request.headers.get('Idempotency-Key')).toBeNull()
      expect(await request.json()).toEqual({ n_examinees: 100 })
      return envelope({ n_examinees: 100 })
    }))
    const { RealApiProvider } = await import('@/services/real-api')
    await expect(new RealApiProvider().requestSchoolCatSavedSimulation({
      path: '/api/v1/school/cat-assets/plan-versions/CPVER_demo/simulations', body: { n_examinees: 100 },
    })).resolves.toMatchObject({ data: { n_examinees: 100 } })
    expect(paths).toHaveLength(2)
  })

  it('rejects non-plan-version simulation paths before requesting CSRF', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const { RealApiProvider } = await import('@/services/real-api')
    await expect(new RealApiProvider().requestSchoolCatSavedSimulation({
      path: '/api/v1/school/cat-assets/bank-versions/CBVER_demo/simulations', body: { n_examinees: 100 },
    })).rejects.toMatchObject({ code: 'API_INVALID_REQUEST' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('obtains CSRF for one explicit simulation request and preserves cookies', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8088')
    const paths: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (request: TestRequest) => {
      const path = new URLConstructor(request.url).pathname
      paths.push(path)
      expect(request.credentials).toBe('include')
      if (path === '/api/v1/auth/csrf') return envelope({ csrf_token: 'csrf_cat_test' })
      expect(path).toBe('/api/v1/school/cat-management/simulations')
      expect(request.method).toBe('POST')
      expect(request.headers.get('X-CSRF-Token')).toBe('csrf_cat_test')
      expect(await request.json()).toEqual({ n_examinees: 100 })
      return envelope({ n_examinees: 100 })
    }))
    const { RealApiProvider } = await import('@/services/real-api')
    const provider = new RealApiProvider()
    await expect(provider.requestSchoolCatManagement({ method: 'POST',
      path: '/api/v1/school/cat-management/simulations', body: { n_examinees: 100 },
    })).resolves.toMatchObject({ data: { n_examinees: 100 } })
    expect(paths).toEqual(['/api/v1/auth/csrf', '/api/v1/school/cat-management/simulations'])
  })

  it('rejects other paths before fetching', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const { RealApiProvider } = await import('@/services/real-api')
    await expect(new RealApiProvider().requestSchoolCatManagement({ method: 'POST',
      path: '/api/v1/school/cat-management/catalog',
    })).rejects.toMatchObject({ code: 'API_INVALID_REQUEST' })
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
