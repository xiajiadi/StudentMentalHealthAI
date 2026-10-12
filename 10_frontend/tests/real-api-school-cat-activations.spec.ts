import { afterEach, expect, it, vi } from 'vitest'

const ResponseConstructor = globalThis.Response
const URLConstructor = globalThis.URL
type TestRequest = InstanceType<typeof globalThis.Request>
const envelope = (data: unknown) => new ResponseConstructor(JSON.stringify({
  request_id: 'REQ_activation_transport', trace_id: 'TRACE_activation_transport', data,
}), { status: 200, headers: { 'Content-Type': 'application/json' } })

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.resetModules()
})

it('allows only activation paths and sends CSRF plus stable idempotency keys', async () => {
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8088')
  const calls: TestRequest[] = []
  const activation = {
    activation_ref: 'CACT_12345678-1234-1234-1234-123456789012',
    plan_version_ref: 'CPVER_12345678-1234-1234-1234-123456789012',
    bank_version_ref: 'CBVER_12345678-1234-1234-1234-123456789012',
    plan_name: '合成方案', plan_version_number: 2, bank_name: '合成题库', bank_version_number: 3,
    status: 'ACTIVE', revision: 1, created_at: '2026-10-13T00:00:00Z', revoked_at: null,
  }
  vi.stubGlobal('fetch', vi.fn(async (request: TestRequest) => {
    const path = new URLConstructor(request.url).pathname
    calls.push(request)
    if (path === '/api/v1/auth/csrf') return envelope({ csrf_token: 'csrf_activation_test' })
    if (path === '/api/v1/school/cat-assets/activations') return envelope({
      engineering_only: true, psychological_interpretation_allowed: false, items: [activation], has_more: false,
    })
    if (path.endsWith('/activations') && request.method === 'POST') return envelope({
      engineering_only: true, psychological_interpretation_allowed: false, activation,
    })
    if (path.endsWith(`/${activation.activation_ref}`) && request.method === 'PATCH') return envelope({
      engineering_only: true, psychological_interpretation_allowed: false,
      activation: { ...activation, status: 'REVOKED', revision: 2, revoked_at: '2026-10-13T01:00:00Z' },
    })
    throw new Error('unexpected route')
  }))
  const { RealApiProvider } = await import('@/services/real-api')
  const provider = new RealApiProvider()

  await provider.requestSchoolCatAssets({ method: 'GET', path: '/api/v1/school/cat-assets/activations', query: { limit: 30, skip: 0 } })
  await provider.requestSchoolCatAssets({
    method: 'POST', path: `/api/v1/school/cat-assets/plan-versions/${activation.plan_version_ref}/activations`,
    body: {}, idempotencyKey: 'stable_create_key',
  })
  await provider.requestSchoolCatAssets({
    method: 'PATCH', path: `/api/v1/school/cat-assets/activations/${activation.activation_ref}`,
    body: { expected_revision: 1, status: 'REVOKED' }, idempotencyKey: 'stable_revoke_key',
  })

  expect(calls).toHaveLength(4)
  expect(calls[0]!.url).toContain('limit=30')
  expect(calls[2]!.headers.get('X-CSRF-Token')).toBe('csrf_activation_test')
  expect(calls[2]!.headers.get('Idempotency-Key')).toBe('stable_create_key')
  expect(await calls[2]!.clone().json()).toEqual({})
  expect(calls[3]!.headers.get('X-CSRF-Token')).toBe('csrf_activation_test')
  expect(calls[3]!.headers.get('Idempotency-Key')).toBe('stable_revoke_key')
  expect(await calls[3]!.clone().json()).toEqual({ expected_revision: 1, status: 'REVOKED' })
})

it('rejects unsupported activation paths and writes without keys before fetch', async () => {
  const fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  const { RealApiProvider } = await import('@/services/real-api')
  const provider = new RealApiProvider()
  await expect(provider.requestSchoolCatAssets({ method: 'GET', path: '/api/v1/school/cat-assets/activations/CACT_bad' }))
    .rejects.toMatchObject({ code: 'API_INVALID_REQUEST' })
  await expect(provider.requestSchoolCatAssets({
    method: 'POST', path: '/api/v1/school/cat-assets/plan-versions/CPVER_12345678-1234-1234-1234-123456789012/activations',
  })).rejects.toMatchObject({ code: 'API_INVALID_REQUEST' })
  expect(fetchMock).not.toHaveBeenCalled()
})
