import { afterEach, describe, expect, it, vi } from 'vitest'

const ResponseConstructor = globalThis.Response
const URLConstructor = globalThis.URL
type TestRequest = InstanceType<typeof globalThis.Request>

const envelope = (data: unknown, status = 200) => new ResponseConstructor(
  JSON.stringify({ request_id: 'REQ_directory', trace_id: 'TRACE_directory', data }),
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

describe('RealApiProvider school directory', () => {
  it('strictly maps only same-school display-name directory metadata', async () => {
    const { provider } = await createProvider((request) => {
      expect(new URLConstructor(request.url).pathname).toBe('/api/v1/school/admin/directory')
      return envelope({
        school: { school_ref: 'SCHOOL_1', display_name: '合成学校' },
        classes: [{ class_ref: 'CLASS_1', status: 'ACTIVE', active_student_count: 2, active_teacher_count: 1, display_name: '一年级一班' }],
        members: [{ user_id: 'USER_1', display_name: '合成学生', role: 'student', account_status: 'SUSPENDED', provisioning_status: 'PENDING_ACTIVATION' }],
      })
    })
    await expect(provider.getSchoolAdminDirectory()).resolves.toMatchObject({
      data: {
        school: { school_ref: 'SCHOOL_1', display_name: '合成学校' },
        classes: [{ class_ref: 'CLASS_1', display_name: '一年级一班', active_student_count: 2 }],
        members: [{ user_id: 'USER_1', display_name: '合成学生', role: 'student', provisioning_status: 'PENDING_ACTIVATION' }],
      },
    })
  })

  it('fails closed if directory members include psychological/private fields', async () => {
    const { provider } = await createProvider(() => envelope({
      school: { school_ref: 'SCHOOL_1', display_name: null },
      classes: [],
      members: [{ user_id: 'USER_1', display_name: '合成学生', role: 'student', account_status: 'ACTIVE', provisioning_status: null, subject_id: 'SUBJ_private' }],
    }))
    await expect(provider.getSchoolAdminDirectory()).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })

  it('uses fixed CSRF write routes and reuses the caller idempotency key for whole-batch import', async () => {
    const batch = {
      batch_ref: 'BATCH_1', created_count: 1,
      accounts: [{ row_no: 1, user_id: 'USER_new', display_name: '合成学生', role: 'student', status: 'PENDING_ACTIVATION' }],
    }
    const { provider, fetchMock } = await createProvider((request) => {
      const url = new URLConstructor(request.url)
      if (url.pathname === '/api/v1/auth/csrf') return envelope({ csrf_token: 'csrf-synthetic' })
      if (url.pathname.endsWith('/preview')) return envelope({ valid: true, row_count: 1, errors: [] })
      if (url.pathname.endsWith('/import')) return envelope(batch, 201)
      if (url.pathname.endsWith('/batches/BATCH_1')) return envelope(batch)
      if (url.pathname.endsWith('/activate')) return envelope({ activated: true })
      if (url.pathname.endsWith('/name')) return envelope({ display_name: '更新名称' })
      throw new Error('unexpected route')
    })
    const rows = [{ row_no: 1, login_name: 'SYNTHETIC_student_1', display_name: '合成学生', role: 'student' as const }]

    await provider.previewSchoolAccountImport(null, rows)
    await expect(provider.importSchoolAccounts(null, rows, 'import-synthetic-replay-key')).resolves.toMatchObject({ data: batch })
    await expect(provider.getSchoolAccountBatch('BATCH_1')).resolves.toMatchObject({ data: batch })
    await provider.updateSchoolDisplayName('更新名称')

    const writes = fetchMock.mock.calls.map(([request]) => request).filter((request) => request.method === 'POST')
    const importWrite = writes.find((request) => new URLConstructor(request.url).pathname.endsWith('/import'))!
    expect(importWrite.headers.get('X-CSRF-Token')).toBe('csrf-synthetic')
    expect(importWrite.headers.get('Idempotency-Key')).toBe('import-synthetic-replay-key')
    await expect(importWrite.clone().json()).resolves.toEqual({ class_ref: null, rows })
    const previewWrite = writes.find((request) => new URLConstructor(request.url).pathname.endsWith('/preview'))!
    expect(previewWrite.headers.get('X-CSRF-Token')).toBe('csrf-synthetic')
    expect(previewWrite.headers.get('Idempotency-Key')).toBeNull()
  })

  it('sends activation password only in the one-time body, never URL or idempotency receipt', async () => {
    const password = 'Synthetic-Only-Passphrase-123!'
    const { provider, fetchMock } = await createProvider((request) => {
      const url = new URLConstructor(request.url)
      if (url.pathname === '/api/v1/auth/csrf') return envelope({ csrf_token: 'csrf-synthetic' })
      if (url.pathname.endsWith('/activate')) return envelope({ activated: true })
      throw new Error('unexpected route')
    })
    await provider.activateSchoolAccount('USER_pending', password)
    const request = fetchMock.mock.calls.map(([item]) => item).find((item) => item.method === 'POST')!
    expect(new URLConstructor(request.url).search).toBe('')
    expect(request.headers.get('X-CSRF-Token')).toBe('csrf-synthetic')
    expect(request.headers.get('Idempotency-Key')).toBeNull()
    await expect(request.clone().json()).resolves.toEqual({ new_password: password })
  })
})
