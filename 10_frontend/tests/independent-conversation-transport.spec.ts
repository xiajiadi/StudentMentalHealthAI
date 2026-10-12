import { afterEach, describe, expect, it, vi } from 'vitest'

const ResponseConstructor = globalThis.Response
const URLConstructor = globalThis.URL
type TestRequest = InstanceType<typeof globalThis.Request>

const envelope = (data: unknown) => new ResponseConstructor(
  JSON.stringify({ request_id: 'REQ_conversation_transport', trace_id: 'TRACE_conversation_transport', data }),
  { status: 200, headers: { 'Content-Type': 'application/json' } },
)

async function loadTransport(handler: (request: TestRequest) => Response | Promise<Response>, mode = 'test') {
  vi.resetModules()
  vi.stubEnv('MODE', mode)
  vi.stubEnv('VITE_API_MODE', 'real')
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8088')
  const fetchMock = vi.fn((request: TestRequest) => handler(request))
  vi.stubGlobal('fetch', fetchMock)
  const realApi = await import('@/services/real-api')
  const mockApi = await import('@/services/mock-api')
  return { ...realApi, frontendApi: mockApi.frontendApi, fetchMock }
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('independent conversation API transport', () => {
  it('shares the real provider session, login CSRF token, and credentialed client', async () => {
    const { frontendApi, realApiProvider, requestIndependentConversation, fetchMock } = await loadTransport((request) => {
      const url = new URLConstructor(request.url)
      if (url.pathname === '/api/v1/auth/login') {
        return envelope({
          actor: { user_id: 'USER_synthetic', username: 'student_synthetic', role: 'STUDENT', subject_id: 'SUBJ_synthetic' },
          csrf_token: 'csrf-synthetic-login',
        })
      }
      if (url.pathname === '/api/v1/student/conversations') return envelope({ items: [], total: 0, has_more: false })
      throw new Error('unexpected test route')
    }, 'production')

    expect(frontendApi).toBe(realApiProvider)
    await frontendApi.login({ account: 'student_synthetic', password: 'synthetic-only' })
    await requestIndependentConversation({
      method: 'POST',
      path: '/api/v1/student/conversations',
      body: {},
      idempotencyKey: 'synthetic-create-key',
    })

    const requests = fetchMock.mock.calls.map(([request]) => request)
    expect(requests).toHaveLength(2)
    const loginRequest = requests[0]!
    const createRequest = requests[1]!
    expect(new URLConstructor(loginRequest.url).pathname).toBe('/api/v1/auth/login')
    expect(createRequest.method).toBe('POST')
    expect(new URLConstructor(createRequest.url).pathname).toBe('/api/v1/student/conversations')
    expect(createRequest.credentials).toBe('include')
    expect(createRequest.headers.get('X-CSRF-Token')).toBe('csrf-synthetic-login')
    expect(createRequest.headers.get('Idempotency-Key')).toBe('synthetic-create-key')
    await expect(createRequest.clone().json()).resolves.toEqual({})
  })

  it('sends GET pagination as query parameters without mutation headers', async () => {
    const { RealApiProvider, fetchMock } = await loadTransport((_request) => envelope({ items: [], total: 0, has_more: false }))
    const provider = new RealApiProvider()

    await provider.requestIndependentConversation({
      method: 'GET',
      path: '/api/v1/student/conversations',
      query: { offset: 30, limit: 10 },
    })

    const request = fetchMock.mock.calls[0]![0]
    const url = new URLConstructor(request.url)
    expect(request.method).toBe('GET')
    expect(url.pathname).toBe('/api/v1/student/conversations')
    expect(url.searchParams.get('offset')).toBe('30')
    expect(url.searchParams.get('limit')).toBe('10')
    expect(request.headers.get('X-CSRF-Token')).toBeNull()
    expect(request.headers.get('Idempotency-Key')).toBeNull()
    expect(request.credentials).toBe('include')
  })

  it('rejects unsupported paths and POST without a key before making a request', async () => {
    const { RealApiProvider, fetchMock } = await loadTransport(() => envelope({}))
    const provider = new RealApiProvider()

    await expect(provider.requestIndependentConversation({
      method: 'GET', path: '/api/v1/student/conversations/../reports',
    })).rejects.toMatchObject({ code: 'API_INVALID_REQUEST' })
    await expect(provider.requestIndependentConversation({
      method: 'POST', path: '/api/v1/student/conversations', body: {}, idempotencyKey: '  ',
    })).rejects.toMatchObject({ code: 'API_INVALID_REQUEST' })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('propagates a network failure without retrying or falling back', async () => {
    const networkFailure = new TypeError('synthetic network failure')
    const { RealApiProvider, fetchMock } = await loadTransport(() => Promise.reject(networkFailure))
    const provider = new RealApiProvider()

    await expect(provider.requestIndependentConversation({
      method: 'GET', path: '/api/v1/student/conversations', query: { offset: 0, limit: 20 },
    })).rejects.toMatchObject({ code: 'API_ERROR' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
