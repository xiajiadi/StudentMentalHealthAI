import { afterEach, describe, expect, it, vi } from 'vitest'

const actorSubjectId = 'SUBJ_authenticated_actor_001'

function envelope(data: unknown) {
  return { request_id: 'REQ_subject_test', trace_id: 'TRACE_subject_test', data }
}

function createBackendFetch(subjectId: string | null) {
  return vi.fn(async (request: Request) => {
    const url = new URL(request.url)
    const response = (data: unknown) => new Response(JSON.stringify(envelope(data)), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })

    if (url.pathname === '/api/v1/auth/login' && request.method === 'POST') {
      return response({
        actor: { user_id: 'USER_test', username: 'student_test', role: 'student', subject_id: subjectId },
        csrf_token: 'csrf-test-token',
      })
    }
    if (url.pathname === '/api/v1/assessments' && request.method === 'POST') {
      return response({ assessment_id: 'ASSESS_test_001' })
    }
    if (url.pathname === '/api/v1/assessments/ASSESS_test_001/state') {
      return response({
        assessment_id: 'ASSESS_test_001',
        subject_id: subjectId,
        status: 'in_progress',
        current_index: 0,
        answered_count: 0,
        can_complete: false,
        max_items: 8,
        current_item: { item_id: 'ITEM_test_001', prompt: '合成项目', options: [{ value: 'A', label: '选项 A' }] },
      })
    }
    return new Response(JSON.stringify({ detail: 'Unexpected test route' }), {
      status: 404,
      headers: { 'Content-Type': 'application/json' },
    })
  })
}

async function createProvider(subjectId: string | null) {
  vi.resetModules()
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8080')
  const fetchMock = createBackendFetch(subjectId)
  vi.stubGlobal('fetch', fetchMock)
  const { RealApiProvider } = await import('@/services/real-api')
  return { provider: new RealApiProvider(), fetchMock }
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('RealApiProvider assessment subject binding', () => {
  it('uses the authenticated actor subject in the assessment create payload', async () => {
    const { provider, fetchMock } = await createProvider(actorSubjectId)
    const login = await provider.login({ account: 'student_test', password: 'synthetic', role: 'student' })
    expect(login.data.subjectId).toBe(actorSubjectId)

    await provider.startAssessment()

    const createRequest = fetchMock.mock.calls
      .map(([request]) => request)
      .find((request) => new URL(request.url).pathname === '/api/v1/assessments' && request.method === 'POST')
    expect(createRequest).toBeDefined()
    await expect(createRequest?.clone().json()).resolves.toMatchObject({ subject_id: actorSubjectId })
  })

  it('fails clearly and does not create an assessment when the actor has no subject', async () => {
    const { provider, fetchMock } = await createProvider(null)
    await provider.login({ account: 'student_test', password: 'synthetic', role: 'student' })

    await expect(provider.startAssessment()).rejects.toMatchObject({ code: 'AUTH_SUBJECT_MISSING' })
    expect(fetchMock.mock.calls.some(([request]) => (
      new URL(request.url).pathname === '/api/v1/assessments' && request.method === 'POST'
    ))).toBe(false)
  })
})
