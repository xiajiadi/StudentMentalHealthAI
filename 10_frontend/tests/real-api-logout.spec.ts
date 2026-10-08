import { afterEach, describe, expect, it, vi } from 'vitest'

const ResponseConstructor = globalThis.Response
const URLConstructor = globalThis.URL
type TestRequest = InstanceType<typeof globalThis.Request>

function envelope(data: unknown) {
  return { request_id: 'REQ_logout_test', trace_id: 'TRACE_logout_test', data }
}

async function createProvider() {
  vi.resetModules()
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8080')
  const fetchMock = vi.fn(async (request: TestRequest) => {
    const url = new URLConstructor(request.url)
    if (url.pathname === '/api/v1/auth/login' && request.method === 'POST') {
      return new ResponseConstructor(JSON.stringify(envelope({
        actor: { user_id: 'USER_synthetic_logout', username: 'student_demo', role: 'student', subject_id: 'SUBJ_demo_logout' },
        csrf_token: 'csrf-synthetic-test',
      })), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    if (url.pathname === '/api/v1/auth/logout' && request.method === 'POST') {
      return new ResponseConstructor(JSON.stringify(envelope({ logged_out: true })), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }
    return new ResponseConstructor(JSON.stringify({ detail: 'Unexpected test route' }), {
      status: 404,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  const { RealApiProvider } = await import('@/services/real-api')
  return { provider: new RealApiProvider(), fetchMock }
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('RealApiProvider logout', () => {
  it('revokes the server session with the session-bound CSRF token', async () => {
    const { provider, fetchMock } = await createProvider()
    await provider.login({ account: 'student_demo', password: 'synthetic-test', role: 'student' })

    await expect(provider.logout()).resolves.toMatchObject({ data: { logged_out: true } })

    const logoutRequest = fetchMock.mock.calls
      .map(([request]) => request)
      .find((request) => new URLConstructor(request.url).pathname === '/api/v1/auth/logout')
    expect(logoutRequest?.method).toBe('POST')
    expect(logoutRequest?.headers.get('X-CSRF-Token')).toBe('csrf-synthetic-test')
  })
})
