import { afterEach, describe, expect, it, vi } from 'vitest'

const ResponseConstructor = globalThis.Response
const URLConstructor = globalThis.URL
type TestRequest = InstanceType<typeof globalThis.Request>

const envelope = (data: unknown, status = 200) => new ResponseConstructor(
  JSON.stringify({ request_id: 'REQ_school', trace_id: 'TRACE_school', data }),
  { status, headers: { 'Content-Type': 'application/json' } },
)

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

describe('RealApiProvider school task endpoints', () => {
  it('maps same-school class directory without inventing member names', async () => {
    const { provider, fetchMock } = await createProvider((request) => {
      const url = new URLConstructor(request.url)
      if (url.pathname === '/api/v1/school/classes') return envelope([{ class_ref: 'CLASS_1', status: 'ACTIVE', active_student_count: 2, active_teacher_count: 1 }])
      if (url.pathname === '/api/v1/school/members' && url.searchParams.get('role') === 'student') {
        return envelope([{ user_id: 'USER_synthetic1', role: 'student', subject_id: 'SUBJ_synthetic1' }])
      }
      throw new Error('unexpected route')
    })

    await expect(provider.listSchoolClasses()).resolves.toMatchObject({
      data: [{ class_ref: 'CLASS_1', active_student_count: 2 }],
    })
    await expect(provider.listSchoolMembers('student')).resolves.toMatchObject({
      data: [{ user_id: 'USER_synthetic1', role: 'student', subject_id: 'SUBJ_synthetic1' }],
    })
    expect(fetchMock.mock.calls.map(([request]) => new URLConstructor(request.url).pathname)).toEqual([
      '/api/v1/school/classes', '/api/v1/school/members',
    ])
  })

  it('creates a class with an opaque class reference and maps the complete server DTO', async () => {
    const { provider, fetchMock } = await createProvider((request) => {
      const url = new URLConstructor(request.url)
      if (url.pathname === '/api/v1/auth/csrf') return envelope({ csrf_token: 'csrf-synthetic' })
      if (url.pathname === '/api/v1/school/classes') {
        return envelope({ class_ref: 'CLASS_generated', status: 'ACTIVE', active_student_count: 0, active_teacher_count: 0 }, 201)
      }
      throw new Error('unexpected route')
    })

    await expect(provider.createSchoolClass('CLASS_generated')).resolves.toMatchObject({
      data: { class_ref: 'CLASS_generated', active_student_count: 0, active_teacher_count: 0 },
    })
    const write = fetchMock.mock.calls.map(([request]) => request).find((request) => request.method === 'POST')!
    await expect(write.clone().json()).resolves.toEqual({ class_ref: 'CLASS_generated' })
    expect(write.headers.get('X-CSRF-Token')).toBe('csrf-synthetic')
    expect(write.headers.get('Idempotency-Key')).toBeTruthy()
  })

  it('uses CSRF and request keys for member assignment and task publication', async () => {
    const { provider, fetchMock } = await createProvider(async (request) => {
      const url = new URLConstructor(request.url)
      if (url.pathname === '/api/v1/auth/csrf') return envelope({ csrf_token: 'csrf-synthetic' })
      if (url.pathname.endsWith('/students')) return envelope({ class_ref: 'CLASS_A', user_id: 'USER_student' })
      if (url.pathname.endsWith('/tasks')) return envelope({
        task_ref: 'TASK_A', class_ref: 'CLASS_A', status: 'PUBLISHED',
        opens_at: '2026-10-12T01:00:00.000Z', due_at: null, published_at: '2026-10-11T02:00:00.000Z',
        published_enrollment_count: 2, active_enrollment_count: 2, revoked_enrollment_count: 0,
        instrument_id: 'INSTRUMENT_A', instrument_version: '1',
      }, 201)
      throw new Error('unexpected route')
    })

    await provider.assignSchoolStudent('CLASS A', 'USER_student')
    await expect(provider.publishSchoolTask('CLASS A', '2026-10-12T01:00:00.000Z', null)).resolves.toMatchObject({
      data: { task_ref: 'TASK_A', published_enrollment_count: 2 },
    })

    const writes = fetchMock.mock.calls.map(([request]) => request).filter((request) => request.method === 'POST')
    expect(writes).toHaveLength(2)
    expect(writes.every((request) => request.headers.get('X-CSRF-Token') === 'csrf-synthetic')).toBe(true)
    expect(writes.every((request) => Boolean(request.headers.get('Idempotency-Key')))).toBe(true)
    expect(new URLConstructor(writes[0]!.url).pathname).toBe('/api/v1/school/classes/CLASS%20A/students')
    await expect(writes[0]!.clone().json()).resolves.toEqual({ student_user_id: 'USER_student' })
    await expect(writes[1]!.clone().json()).resolves.toEqual({ opens_at: '2026-10-12T01:00:00.000Z', due_at: null })
  })

  it('keeps fixture publication unchanged and includes only an explicitly selected activation', async () => {
    const { provider, fetchMock } = await createProvider((request) => {
      const url = new URLConstructor(request.url)
      if (url.pathname === '/api/v1/auth/csrf') return envelope({ csrf_token: 'csrf-synthetic' })
      if (url.pathname.endsWith('/tasks')) return envelope({
        task_ref: 'TASK_A', class_ref: 'CLASS_A', status: 'PUBLISHED',
        opens_at: '2026-10-12T01:00:00.000Z', due_at: null, published_at: '2026-10-11T02:00:00.000Z',
        published_enrollment_count: 2, active_enrollment_count: 2, revoked_enrollment_count: 0,
        instrument_id: 'INSTRUMENT_A', instrument_version: '1',
        activation_ref: 'CACT_12345678-1234-1234-1234-123456789012',
        plan_name: '合成方案', plan_version_number: 2,
      }, 201)
      throw new Error('unexpected route')
    })

    await provider.publishSchoolTask('CLASS_A', '2026-10-12T01:00:00.000Z', null)
    await expect(provider.publishSchoolTask(
      'CLASS_A', '2026-10-12T01:00:00.000Z', null,
      'CACT_12345678-1234-1234-1234-123456789012',
    )).resolves.toMatchObject({ data: {
      activation_ref: 'CACT_12345678-1234-1234-1234-123456789012',
      plan_name: '合成方案', plan_version_number: 2,
    } })
    const writes = fetchMock.mock.calls.map(([request]) => request).filter((request) => request.method === 'POST')
    expect(writes).toHaveLength(2)
    await expect(writes[0]!.clone().json()).resolves.toEqual({
      opens_at: '2026-10-12T01:00:00.000Z', due_at: null,
    })
    await expect(writes[1]!.clone().json()).resolves.toEqual({
      opens_at: '2026-10-12T01:00:00.000Z', due_at: null,
      activation_ref: 'CACT_12345678-1234-1234-1234-123456789012',
    })
    const invalidProvider = await createProvider(() => envelope({}))
    await expect(invalidProvider.provider.publishSchoolTask(
      'CLASS_A', '2026-10-12T01:00:00.000Z', null, 'CACT_bad',
    )).rejects.toMatchObject({ code: 'API_INVALID_REQUEST' })
    expect(invalidProvider.fetchMock).not.toHaveBeenCalled()
  })

  it('starts a task through the bound backend route and maps only the returned session', async () => {
    const item = { item_id: 'ITEM_1', prompt: '合成题目', options: [{ value: 'A', label: '选项 A' }] }
    const { provider, fetchMock } = await createProvider((request) => {
      const url = new URLConstructor(request.url)
      if (url.pathname === '/api/v1/auth/csrf') return envelope({ csrf_token: 'csrf-synthetic' })
      if (url.pathname === '/api/v1/school/tasks/TASK_1/start') return envelope({
        task_ref: 'TASK_1', assessment_id: 'ASSESS_1', subject_id: 'SUBJ_1', status: 'in_progress',
        selected_item_id: 'ITEM_1', current_item: item, answered_count: 0, administered_count: 1,
        can_complete: false, max_items: 8,
      })
      throw new Error('unexpected route')
    })

    const result = await provider.startStudentSchoolTask('TASK_1')

    expect(result.data).toMatchObject({ task_ref: 'TASK_1', assessment_id: 'ASSESS_1', status: 'in_progress', current_item: item })
    const write = fetchMock.mock.calls.map(([request]) => request).find((request) => request.method === 'POST')!
    expect(write.headers.get('X-CSRF-Token')).toBe('csrf-synthetic')
    expect(write.headers.get('Idempotency-Key')).toBeTruthy()
    await expect(write.clone().json()).resolves.toEqual({})
  })

  it('rejects teacher task DTOs that contain per-person fields', async () => {
    const { provider } = await createProvider(() => envelope([{
      class_ref: 'CLASS_1', task_ref: 'TASK_1', task_status: 'PUBLISHED',
      opens_at: '2026-10-11T00:00:00Z', due_at: null,
      published_enrollment_count: 1, active_enrollment_count: 1, revoked_enrollment_count: 0,
      not_started_count: 1, created_count: 0, in_progress_count: 0, completed_count: 0,
      abandoned_count: 0, invalid_count: 0, subject_id: 'SUBJ_private',
    }]))

    await expect(provider.listTeacherSchoolTaskProgress()).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })

  it('maps only the student-owned task lifecycle history fields', async () => {
    const { provider, fetchMock } = await createProvider((request) => {
      const url = new URLConstructor(request.url)
      if (url.pathname === '/api/v1/school/tasks/student/history') return envelope([
        {
          task_ref: 'TASK_1', class_ref: 'CLASS_1', task_status: 'EXPIRED', enrollment_status: 'REVOKED',
          assessment_status: 'completed', started_at: '2026-10-01T09:00:00Z', completed_at: '2026-10-01T09:10:00Z',
        },
        { task_ref: 'TASK_2', class_ref: 'CLASS_1', task_status: 'CLOSED', enrollment_status: 'ACTIVE' },
      ])
      throw new Error('unexpected route')
    })

    await expect(provider.listStudentSchoolTaskHistory()).resolves.toMatchObject({ data: [{
      task_ref: 'TASK_1', task_status: 'EXPIRED', enrollment_status: 'REVOKED',
      assessment_status: 'completed', started_at: '2026-10-01T09:00:00Z', completed_at: '2026-10-01T09:10:00Z',
    }, {
      task_ref: 'TASK_2', task_status: 'CLOSED', enrollment_status: 'ACTIVE',
      assessment_status: null, started_at: null, completed_at: null,
    }] })
    expect(new URLConstructor(fetchMock.mock.calls[0]![0].url).pathname).toBe('/api/v1/school/tasks/student/history')
  })

  it('fails closed if student history contains private assessment fields', async () => {
    const { provider } = await createProvider(() => envelope([{
      task_ref: 'TASK_1', class_ref: 'CLASS_1', task_status: 'CLOSED', enrollment_status: 'ACTIVE',
      assessment_status: 'completed', started_at: null, completed_at: null,
      assessment_id: 'ASSESS_private', score: 99,
    }]))

    await expect(provider.listStudentSchoolTaskHistory()).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })

  it.each([
    ['forbidden', 403],
    ['resource_not_found', 404],
    ['workflow_conflict', 409],
  ])('preserves the safe service error code for %s', async (code, status) => {
    const { provider } = await createProvider(() => new ResponseConstructor(
      JSON.stringify({ code, status, detail: 'safe synthetic error', retryable: false }),
      { status, headers: { 'Content-Type': 'application/json' } },
    ))

    await expect(provider.listStudentSchoolTasks()).rejects.toMatchObject({ code })
  })
})
