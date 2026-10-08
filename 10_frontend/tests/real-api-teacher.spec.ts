import { afterEach, describe, expect, it, vi } from 'vitest'

const ResponseConstructor = globalThis.Response
const URLConstructor = globalThis.URL
type TestRequest = InstanceType<typeof globalThis.Request>

function envelope(data: unknown) {
  return { request_id: 'REQ_teacher_test', trace_id: 'TRACE_teacher_test', data }
}

async function createProvider() {
  vi.resetModules()
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8080')
  const fetchMock = vi.fn(async (request: TestRequest) => {
    const path = new URLConstructor(request.url).pathname
    const data = path === '/api/v1/teacher/overview'
      ? {
          subjects_count: 1,
          assessments_count: 2,
          completed_count: 1,
          in_progress_count: 1,
          reports_count: 0,
          report_status_counts: {},
          review_status_counts: {},
          students: [],
        }
      : {
          subject_id: 'SUBJ_demo_a',
          assessment_count: 1,
          completed_count: 1,
          in_progress_count: 0,
          assessments: [],
        }
    return new ResponseConstructor(JSON.stringify(envelope(data)), {
      status: 200,
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

describe('RealApiProvider teacher projection', () => {
  it('uses the authenticated teacher endpoints and encodes subject identifiers', async () => {
    const { provider, fetchMock } = await createProvider()

    await expect(provider.getTeacherOverview()).resolves.toMatchObject({
      data: { subjects_count: 1, assessments_count: 2 },
    })
    await expect(provider.getTeacherStudent('SUBJ demo/a')).resolves.toMatchObject({
      data: { subject_id: 'SUBJ_demo_a' },
    })

    const requests = fetchMock.mock.calls.map(([request]) => request)
    expect(requests.map((request) => new URLConstructor(request.url).pathname)).toEqual([
      '/api/v1/teacher/overview',
      '/api/v1/teacher/students/SUBJ%20demo%2Fa',
    ])
    expect(requests.every((request) => request.method === 'GET')).toBe(true)
  })
})
