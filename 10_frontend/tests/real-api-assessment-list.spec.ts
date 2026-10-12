import { afterEach, describe, expect, it, vi } from 'vitest'
import { syntheticAssessment } from '@/mocks/fixtures'

const ResponseConstructor = globalThis.Response
const URLConstructor = globalThis.URL
type TestRequest = InstanceType<typeof globalThis.Request>

const envelope = (data: unknown, status = 200) => new ResponseConstructor(
  JSON.stringify({ request_id: 'REQ_assessment_list', trace_id: 'TRACE_assessment_list', data }),
  { status, headers: { 'Content-Type': 'application/json' } },
)

const schoolStudent = {
  user_id: 'USER_synthetic_student', username: 'student_demo', role: 'STUDENT', subject_id: 'SUBJ_synthetic_student',
  available_contexts: [{ role: 'STUDENT', school_ref: 'SCHOOL_synthetic' }],
  active_context: { role: 'STUDENT', school_ref: 'SCHOOL_synthetic' },
}

async function createProvider(handler: (request: TestRequest) => Response | Promise<Response>) {
  vi.resetModules()
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8088')
  const fetchMock = vi.fn((request: TestRequest) => handler(request))
  vi.stubGlobal('fetch', fetchMock)
  const { RealApiProvider } = await import('@/services/real-api')
  return { provider: new RealApiProvider(), fetchMock }
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('RealApiProvider assessment list metadata', () => {
  it('rejects timestamps without an explicit timezone', async () => {
    const { provider } = await createProvider((request) => {
      const url = new URLConstructor(request.url)
      if (url.pathname === '/api/v1/auth/me') return envelope({ actor: schoolStudent })
      return envelope([{
        assessment_id: 'ASSESS_synthetic', status: 'in_progress', items_answered: 1,
        started_at: '2026-10-11T12:30:45', completed_at: null,
      }])
    })
    await provider.getCurrentUser()
    await expect(provider.listAssessmentEntries()).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })

  it('uses the school metadata route and preserves a CREATED row with a null start time', async () => {
    const row = {
      assessment_id: 'ASSESS_created_synthetic', status: 'created', items_answered: 0,
      started_at: null, completed_at: null,
    }
    const { provider, fetchMock } = await createProvider((request) => {
      const url = new URLConstructor(request.url)
      if (url.pathname === '/api/v1/auth/me') return envelope({ actor: schoolStudent })
      if (url.pathname === '/api/v1/school/assessments') return envelope([row])
      throw new Error(`unexpected route ${url.pathname}`)
    })

    await provider.getCurrentUser()
    await expect(provider.listAssessmentEntries({ limit: 30, skip: 0, status: 'created' })).resolves.toMatchObject({ data: [row] })

    const request = fetchMock.mock.calls.map(([call]) => call).find((call) => new URLConstructor(call.url).pathname === '/api/v1/school/assessments')
    expect(request && new URLConstructor(request.url).searchParams.toString()).toBe('limit=30&skip=0&status=created')
    expect(fetchMock.mock.calls.some(([call]) => new URLConstructor(call.url).pathname === '/api/v1/assessments')).toBe(false)
  })

  it('rejects extra psychological fields and does not retry through the legacy endpoint', async () => {
    const { provider, fetchMock } = await createProvider((request) => {
      const url = new URLConstructor(request.url)
      if (url.pathname === '/api/v1/auth/me') return envelope({ actor: schoolStudent })
      if (url.pathname === '/api/v1/school/assessments') return envelope([{
        assessment_id: 'ASSESS_synthetic', status: 'created', items_answered: 0,
        started_at: null, completed_at: null, risk: { level: 'high' },
      }])
      throw new Error(`unexpected route ${url.pathname}`)
    })

    await provider.getCurrentUser()
    await expect(provider.listAssessmentEntries()).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
    expect(fetchMock.mock.calls.filter(([call]) => new URLConstructor(call.url).pathname === '/api/v1/school/assessments')).toHaveLength(1)
    expect(fetchMock.mock.calls.some(([call]) => new URLConstructor(call.url).pathname === '/api/v1/assessments')).toBe(false)
  })

  it('keeps the legacy list route for a non-school actor and projects only list fields', async () => {
    const assessment = structuredClone(syntheticAssessment)
    const { provider, fetchMock } = await createProvider((request) => {
      const url = new URLConstructor(request.url)
      if (url.pathname === '/api/v1/auth/me') return envelope({ actor: {
        user_id: 'USER_legacy_synthetic', username: 'legacy_demo', role: 'STUDENT', subject_id: 'SUBJ_synthetic',
      } })
      if (url.pathname === '/api/v1/assessments') return envelope([assessment])
      throw new Error(`unexpected route ${url.pathname}`)
    })

    await provider.getCurrentUser()
    const response = await provider.listAssessmentEntries({ limit: 30, skip: 0 })
    expect(response.data).toEqual([{
      assessment_id: assessment.assessment_id,
      status: assessment.status,
      items_answered: assessment.response_summary.items_answered,
      started_at: assessment.timestamps.started_at,
      completed_at: assessment.timestamps.completed_at,
    }])
    expect(fetchMock.mock.calls.some(([call]) => new URLConstructor(call.url).pathname === '/api/v1/school/assessments')).toBe(false)
  })

  it('clears the active school selector after a refreshed context change and logout', async () => {
    let actor: Record<string, unknown> | null = schoolStudent
    const { provider, fetchMock } = await createProvider((request) => {
      const url = new URLConstructor(request.url)
      if (url.pathname === '/api/v1/auth/me') return envelope(actor ? { actor } : {})
      if (url.pathname === '/api/v1/auth/csrf') return envelope({ csrf_token: 'csrf-synthetic' })
      if (url.pathname === '/api/v1/auth/logout') {
        actor = null
        return envelope({ logged_out: true })
      }
      if (url.pathname === '/api/v1/school/assessments') return envelope([])
      if (url.pathname === '/api/v1/assessments') return envelope([structuredClone(syntheticAssessment)])
      throw new Error(`unexpected route ${url.pathname}`)
    })

    await provider.getCurrentUser()
    await provider.listAssessmentEntries()
    actor = {
      user_id: 'USER_synthetic_teacher', username: 'teacher_demo', role: 'TEACHER', subject_id: null,
      available_contexts: [{ role: 'TEACHER', school_ref: 'SCHOOL_synthetic' }],
      active_context: { role: 'TEACHER', school_ref: 'SCHOOL_synthetic' },
    }
    await provider.getCurrentUser()
    await provider.listAssessmentEntries()
    expect(fetchMock.mock.calls.filter(([call]) => new URLConstructor(call.url).pathname === '/api/v1/assessments')).toHaveLength(1)

    await provider.logout()
    await provider.getCurrentUser()
    await provider.listAssessmentEntries()
    expect(fetchMock.mock.calls.filter(([call]) => new URLConstructor(call.url).pathname === '/api/v1/school/assessments')).toHaveLength(1)
    expect(fetchMock.mock.calls.filter(([call]) => new URLConstructor(call.url).pathname === '/api/v1/assessments')).toHaveLength(2)
  })

  it('reselects the list route after an explicit context switch', async () => {
    const { provider, fetchMock } = await createProvider(async (request) => {
      const url = new URLConstructor(request.url)
      if (url.pathname === '/api/v1/auth/me') return envelope({ actor: schoolStudent })
      if (url.pathname === '/api/v1/auth/csrf') return envelope({ csrf_token: 'csrf-synthetic' })
      if (url.pathname === '/api/v1/auth/active-context') return envelope({
        user_id: 'USER_synthetic_teacher', username: 'teacher_demo', role: 'TEACHER', subject_id: null,
        available_contexts: [{ role: 'TEACHER', school_ref: 'SCHOOL_synthetic' }],
        active_context: { role: 'TEACHER', school_ref: 'SCHOOL_synthetic' },
      })
      if (url.pathname === '/api/v1/assessments') return envelope([structuredClone(syntheticAssessment)])
      throw new Error(`unexpected route ${url.pathname}`)
    })

    await provider.getCurrentUser()
    await provider.switchActiveContext({ role: 'teacher', schoolRef: 'SCHOOL_synthetic' })
    await provider.listAssessmentEntries()

    expect(fetchMock.mock.calls.some(([call]) => new URLConstructor(call.url).pathname === '/api/v1/school/assessments')).toBe(false)
    expect(fetchMock.mock.calls.filter(([call]) => new URLConstructor(call.url).pathname === '/api/v1/assessments')).toHaveLength(1)
  })

  it('surfaces school route failures without falling back to the legacy endpoint', async () => {
    const { provider, fetchMock } = await createProvider((request) => {
      const url = new URLConstructor(request.url)
      if (url.pathname === '/api/v1/auth/me') return envelope({ actor: schoolStudent })
      if (url.pathname === '/api/v1/school/assessments') {
        return new ResponseConstructor(JSON.stringify({ code: 'SERVICE_UNAVAILABLE', status: 503, detail: 'synthetic outage' }), {
          status: 503, headers: { 'Content-Type': 'application/json' },
        })
      }
      throw new Error(`unexpected route ${url.pathname}`)
    })

    await provider.getCurrentUser()
    await expect(provider.listAssessmentEntries()).rejects.toMatchObject({ code: 'SERVICE_UNAVAILABLE' })
    expect(fetchMock.mock.calls.filter(([call]) => new URLConstructor(call.url).pathname === '/api/v1/assessments')).toHaveLength(0)
  })
})
