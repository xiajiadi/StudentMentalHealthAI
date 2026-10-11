import { afterEach, expect, it, vi } from 'vitest'

const ResponseConstructor = globalThis.Response
const URLConstructor = globalThis.URL
type TestRequest = InstanceType<typeof globalThis.Request>
const context = { role: 'STUDENT', school_ref: 'SYNTHETIC_SCHOOL_ALPHA' }
const actor = { user_id: 'USER_context', username: 'synthetic', role: 'STUDENT', subject_id: null, available_contexts: [context], active_context: null }

async function providerFor(contexts = [context], switchStatus = 200) {
  vi.resetModules()
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8088')
  const fetchMock = vi.fn(async (request: TestRequest) => {
    const path = new URLConstructor(request.url).pathname
    const envelope = (data: unknown, status = 200) => new ResponseConstructor(JSON.stringify({ request_id: 'REQ_context', trace_id: 'TRACE_context', data }), { status, headers: { 'Content-Type': 'application/json' } })
    if (path === '/api/v1/auth/login') return envelope({ actor: { ...actor, available_contexts: contexts }, csrf_token: 'synthetic-csrf' })
    if (path === '/api/v1/auth/active-context') {
      if (switchStatus !== 200) return new ResponseConstructor(JSON.stringify({ code: 'forbidden', detail: 'denied' }), { status: switchStatus, headers: { 'Content-Type': 'application/json' } })
      return envelope({ ...actor, available_contexts: contexts, active_context: context, subject_id: 'SUBJ_context' })
    }
    throw new Error('unexpected test route')
  })
  vi.stubGlobal('fetch', fetchMock)
  const { RealApiProvider } = await import('@/services/real-api')
  return { provider: new RealApiProvider(), fetchMock }
}

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.resetModules() })

it('activates the sole server context with CSRF before returning login', async () => {
  const { provider, fetchMock } = await providerFor()
  const result = await provider.login({ account: 'synthetic', password: 'synthetic-only' })
  expect(result.data.subjectId).toBe('SUBJ_context')
  expect(result.data.activeContext).toEqual({ role: 'student', schoolRef: context.school_ref })
  const request = fetchMock.mock.calls[1]![0]
  expect(request.method).toBe('POST')
  expect(request.headers.get('X-CSRF-Token')).toBe('synthetic-csrf')
  await expect(request.clone().json()).resolves.toEqual(context)
})

it('does not pick one of multiple school contexts', async () => {
  const { provider, fetchMock } = await providerFor([context, { ...context, school_ref: 'SYNTHETIC_SCHOOL_BETA' }])
  const result = await provider.login({ account: 'synthetic', password: 'synthetic-only' })
  expect(result.data.activeContext).toBeNull()
  expect(result.data.availableContexts).toHaveLength(2)
  expect(fetchMock).toHaveBeenCalledTimes(1)
})

it('does not return an activated session when the server denies selection', async () => {
  const { provider } = await providerFor([context], 403)
  await expect(provider.login({ account: 'synthetic', password: 'synthetic-only' })).rejects.toMatchObject({ code: 'forbidden' })
})
