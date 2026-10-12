import { afterEach, expect, it, vi } from 'vitest'

const ResponseConstructor = globalThis.Response
const URLConstructor = globalThis.URL
type TestRequest = InstanceType<typeof globalThis.Request>
const envelope = (data: unknown) => new ResponseConstructor(JSON.stringify({
  request_id: 'REQ_assets', trace_id: 'TRACE_assets', data,
}), { status: 200, headers: { 'Content-Type': 'application/json' } })

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.resetModules()
})

it('uses CSRF and caller stable key for asset PATCH with credentials', async () => {
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8088')
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (request: TestRequest) => {
    const path = new URLConstructor(request.url).pathname
    calls.push(path)
    if (path === '/api/v1/auth/csrf') return envelope({ csrf_token: 'csrf_assets_test' })
    expect(path).toBe('/api/v1/school/cat-assets/banks/CBANK_demo')
    expect(request.method).toBe('PATCH')
    expect(request.credentials).toBe('include')
    expect(request.headers.get('X-CSRF-Token')).toBe('csrf_assets_test')
    expect(request.headers.get('Idempotency-Key')).toBe('stable_assets_key')
    expect(await request.json()).toEqual({ expected_revision: 1, status: 'ARCHIVED' })
    return envelope({ revision: 2 })
  }))
  const { RealApiProvider } = await import('@/services/real-api')
  await expect(new RealApiProvider().requestSchoolCatAssets({ method: 'PATCH',
    path: '/api/v1/school/cat-assets/banks/CBANK_demo', idempotencyKey: 'stable_assets_key',
    body: { expected_revision: 1, status: 'ARCHIVED' },
  })).resolves.toMatchObject({ data: { revision: 2 } })
  expect(calls).toHaveLength(2)
})

it('refuses invalid asset paths or missing mutation key before fetching', async () => {
  const fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  const { RealApiProvider } = await import('@/services/real-api')
  const provider = new RealApiProvider()
  await expect(provider.requestSchoolCatAssets({ method: 'POST',
    path: '/api/v1/school/cat-assets/template', idempotencyKey: 'stable',
  })).rejects.toMatchObject({ code: 'API_INVALID_REQUEST' })
  await expect(provider.requestSchoolCatAssets({ method: 'POST',
    path: '/api/v1/school/cat-assets/banks',
  })).rejects.toMatchObject({ code: 'API_INVALID_REQUEST' })
  expect(fetchMock).not.toHaveBeenCalled()
})
