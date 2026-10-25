/* global URL */
import { afterEach, describe, expect, it, vi } from 'vitest'

const ResponseConstructor = globalThis.Response
type TestRequest = InstanceType<typeof globalThis.Request>
const envelope = (data: unknown) => new ResponseConstructor(
  JSON.stringify({ request_id: 'REQ_lifecycle', trace_id: 'TRACE_lifecycle', data }),
  { status: 200, headers: { 'Content-Type': 'application/json' } },
)

async function providerFor(handler: (request: TestRequest) => Response | Promise<Response>) {
  vi.resetModules()
  vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8088')
  const fetchMock = vi.fn((request: TestRequest) => handler(request))
  vi.stubGlobal('fetch', fetchMock)
  const { RealApiProvider } = await import('@/services/real-api')
  return { provider: new RealApiProvider(), fetchMock }
}

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.resetModules() })

describe('RealApiProvider account lifecycle endpoints', () => {
  it('requests real account summary and sends roster v1 rows to server preview', async () => {
    const { provider, fetchMock } = await providerFor(async (request) => {
      const url = new URL(request.url)
      if (url.pathname === '/api/v1/auth/csrf') return envelope({ csrf_token: 'csrf-test' })
      if (url.pathname === '/api/v1/school/admin/accounts/summary') return envelope({ total_accounts: 12, active_accounts: 8, pending_activation: 3, suspended_accounts: 1, classes: 2, invitations_issued: 2, invitations_accepted: 1, invitations_expired: 0, invitations_revoked: 1, recovery_queue_count: 3 })
      if (url.pathname === '/api/v1/school/admin/roster/preview') {
        expect(request.method).toBe('POST')
        expect(await request.json()).toEqual({ rows: [{ row_no: 1, student_number: 'S-1', display_name: '合成学生', class_ref: 'C-1' }] })
        return envelope({ valid: true, row_count: 1, errors: [], class_groups: [{ class_ref: 'C-1', row_count: 1 }] })
      }
      throw new Error(`Unexpected lifecycle endpoint: ${url.pathname}`)
    })
    await expect(provider.getLifecycleAccountSummary()).resolves.toMatchObject({ data: { total_accounts: 12, invitations_issued: 2, recovery_queue_count: 3 } })
    await expect(provider.previewLifecycleRoster([{ row_no: 1, student_number: 'S-1', display_name: '合成学生', class_ref: 'C-1' }])).resolves.toMatchObject({ data: { valid: true, row_count: 1 } })
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('uses a caller idempotency key for roster import and fixes delivery channel to MANUAL', async () => {
    const { provider } = await providerFor(async (request) => {
      const url = new URL(request.url)
      if (url.pathname === '/api/v1/auth/csrf') return envelope({ csrf_token: 'csrf-test' })
      if (url.pathname === '/api/v1/school/admin/roster/import') {
        expect(request.headers.get('Idempotency-Key')).toBe('roster-test-key')
        expect(request.headers.get('X-CSRF-Token')).toBe('csrf-test')
        return envelope({ run_ref: 'RUN-1', status: 'QUEUED', row_count: 1, created_count: 0, skipped_count: 0, valid: true, errors: [] })
      }
      if (url.pathname === '/api/v1/school/admin/staff/invitations') {
        expect(await request.json()).toMatchObject({ role: 'teacher', verified: true, delivery_channel: 'MANUAL' })
        return envelope({ invitation_ref: 'INV-1', user_id: 'USER-1', login_name: 'STAFF-1', credential: 'one-time-secret', expires_at: '2026-11-01T00:00:00Z', status: 'ISSUED', delivery_channel: 'MANUAL_HANDOFF_REQUIRED' })
      }
      throw new Error(`Unexpected lifecycle endpoint: ${url.pathname}`)
    })
    await provider.importLifecycleRoster([{ row_no: 1, student_number: 'S-1', display_name: '合成学生', class_ref: 'C-1' }], 'roster-test-key')
    await provider.inviteSchoolStaff({ employee_ref: 'E-1', display_name: '合成教师', role: 'teacher', work_contact: 'synthetic@example.test', verified: true, class_refs: ['C-1'], delivery_channel: 'MANUAL' })
  })

  it('submits a mixed synthetic staff roster and validates its first-login credentials', async () => {
    const rows = [
      { row_no: 1, employee_ref: 'T-1', display_name: '合成教师', role: 'teacher' as const, class_refs: ['C-1'] },
      { row_no: 2, employee_ref: 'P-1', display_name: '合成心理教师', role: 'psychological_specialist' as const, class_refs: [] },
    ]
    const { provider, fetchMock } = await providerFor(async (request) => {
      const url = new URL(request.url)
      if (url.pathname === '/api/v1/auth/csrf') return envelope({ csrf_token: 'csrf-test' })
      expect(url.pathname).toBe('/api/v1/school/admin/staff/import')
      expect(request.method).toBe('POST')
      expect(request.headers.get('X-CSRF-Token')).toBe('csrf-test')
      expect(await request.json()).toEqual({ rows })
      return envelope({
        created_count: 1,
        delivery_status: 'MANUAL_HANDOFF_REQUIRED',
        credentials: [{
          invitation_ref: 'INV-P-1', user_id: 'USER-P-1', login_name: 'P-1',
          display_name: '合成心理教师', role: 'psychological_specialist', class_refs: [],
          credential: 'one-time-credential', expires_at: '2026-11-01T00:00:00Z',
        }],
      })
    })

    await expect(provider.importLifecycleStaff(rows)).resolves.toMatchObject({
      data: {
        created_count: 1,
        credentials: [{ role: 'psychological_specialist', login_name: 'P-1' }],
      },
    })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('lists invitations without credentials and supports reason-coded revoke and reissue', async () => {
    const calls: Array<{ method: string; path: string; body?: unknown }> = []
    const { provider, fetchMock } = await providerFor(async (request) => {
      const url = new URL(request.url)
      if (url.pathname === '/api/v1/auth/csrf') return envelope({ csrf_token: 'csrf-test' })
      const body = request.method === 'GET' ? undefined : await request.json()
      calls.push({ method: request.method, path: url.pathname, body })
      if (request.method === 'GET' && url.pathname === '/api/v1/school/admin/staff/invitations') {
        return envelope([{
          invitation_ref: 'INV-1', user_id: 'USER-1', login_name: 'STAFF-1', display_name: '合成教师',
          employee_ref: 'EMP-1', role: 'teacher', status: 'ISSUED', delivery_channel: 'MANUAL',
          class_refs: ['CLASS-1'], created_at: '2026-10-24T00:00:00Z', expires_at: '2026-11-01T00:00:00Z',
        }])
      }
      if (request.method === 'POST' && url.pathname.endsWith('/INV-1/revoke')) return envelope({ status: 'REVOKED' })
      if (request.method === 'POST' && url.pathname.endsWith('/INV-1/reissue')) {
        return envelope({ invitation_ref: 'INV-1', user_id: 'USER-1', login_name: 'STAFF-1', credential: 'synthetic-once', expires_at: '2026-11-01T00:00:00Z', status: 'ISSUED', delivery_channel: 'MANUAL_HANDOFF_REQUIRED' })
      }
      throw new Error(`Unexpected lifecycle endpoint: ${url.pathname}`)
    })
    const listed = await provider.listStaffInvitations()
    expect(listed.data[0]).toMatchObject({ invitation_ref: 'INV-1', class_refs: ['CLASS-1'], status: 'ISSUED' })
    expect(listed.data[0]).not.toHaveProperty('credential')
    await expect(provider.revokeStaffInvitation('INV-1', 'SYNTHETIC_REVOKE')).resolves.toMatchObject({ data: { status: 'REVOKED' } })
    await expect(provider.reissueStaffInvitation('INV-1', 'SYNTHETIC_REISSUE')).resolves.toMatchObject({ data: { credential: 'synthetic-once', delivery_channel: 'MANUAL_HANDOFF_REQUIRED' } })
    expect(calls).toEqual([
      { method: 'GET', path: '/api/v1/school/admin/staff/invitations' },
      { method: 'POST', path: '/api/v1/school/admin/staff/invitations/INV-1/revoke', body: { reason_code: 'SYNTHETIC_REVOKE' } },
      { method: 'POST', path: '/api/v1/school/admin/staff/invitations/INV-1/reissue', body: { reason_code: 'SYNTHETIC_REISSUE' } },
    ])
    expect(fetchMock).toHaveBeenCalledTimes(4)
  })

  it('sends first-login credential only to the specified auth endpoint', async () => {
    const { provider, fetchMock } = await providerFor(async (request) => {
      const url = new URL(request.url)
      expect(url.pathname).toBe('/api/v1/auth/first-login')
      expect(request.headers.get('X-CSRF-Token')).toBeNull()
      expect(await request.json()).toEqual({ school_ref: 'SCHOOL-1', username: 'SYNTHETIC-1', credential: 'one-time', new_password: 'new password', confirm_password: 'new password' })
      return envelope({ completed: true })
    })
    await provider.completeFirstLogin({ school_ref: 'SCHOOL-1', username: 'SYNTHETIC-1', credential: 'one-time', new_password: 'new password', confirm_password: 'new password' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('uses public-origin guarded writes for unauthenticated lifecycle flows', async () => {
    const paths: string[] = []
    const { provider, fetchMock } = await providerFor(async (request) => {
      const path = new URL(request.url).pathname
      paths.push(path)
      expect(request.method).toBe('POST')
      expect(request.headers.get('X-CSRF-Token')).toBeNull()
      return envelope({ accepted: true })
    })

    await provider.completeFirstLogin({ school_ref: 'SCHOOL-1', username: 'STUDENT-1', credential: 'once', new_password: 'new password', confirm_password: 'new password' })
    await provider.acceptStaffInvitation({ invitation_ref: 'INV-1', credential: 'once', new_password: 'new password', confirm_password: 'new password' })
    await provider.createRecoveryRequest({ school_ref: 'SCHOOL-1', username: 'STUDENT-1', class_ref: 'CLASS-1', reason_code: 'SYNTHETIC_RECOVERY' })
    await provider.completePasswordReset({ school_ref: 'SCHOOL-1', username: 'STUDENT-1', credential: 'once', new_password: 'new password', confirm_password: 'new password' })

    expect(paths).toEqual([
      '/api/v1/auth/first-login',
      '/api/v1/auth/staff-invitations/accept',
      '/api/v1/auth/recovery-requests',
      '/api/v1/auth/password/reset/complete',
    ])
    expect(fetchMock).toHaveBeenCalledTimes(4)
  })

  it('covers credential, recovery, reset, status and reauthentication endpoint paths', async () => {
    const expectedPaths = [
      '/api/v1/school/admin/roster/imports/RUN-1',
      '/api/v1/school/admin/accounts/credentials/issue',
      '/api/v1/school/admin/staff/invitations',
      '/api/v1/school/admin/staff/USER-1/recovery-credential',
      '/api/v1/auth/staff-invitations/accept',
      '/api/v1/auth/recovery-requests',
      '/api/v1/school/admin/recovery-requests',
      '/api/v1/school/teacher/recovery-requests/TICKET-1/verify',
      '/api/v1/school/admin/recovery-requests/TICKET-1/approve',
      '/api/v1/auth/password/reset/complete',
      '/api/v1/school/admin/accounts/USER-1/status',
      '/api/v1/auth/reauthenticate',
    ]
    const { provider } = await providerFor(async (request) => {
      const path = new URL(request.url).pathname
      if (path === '/api/v1/auth/csrf') return envelope({ csrf_token: 'csrf-test' })
      expect(expectedPaths).toContain(path)
      if (path === '/api/v1/auth/reauthenticate') expect(await request.json()).toEqual({ current_password: 'admin-password' })
      if (path === '/api/v1/school/admin/accounts/credentials/issue') return envelope({ credentials: [{ user_id: 'USER-1', login_name: 'SYNTHETIC-1', display_name: '合成学生', class_ref: 'CLASS-1', credential: 'one-time', expires_at: '2026-11-01T00:00:00Z' }] })
      if (path === '/api/v1/school/admin/recovery-requests') return envelope([])
      if (path === '/api/v1/school/admin/staff/USER-1/recovery-credential') {
        expect(await request.json()).toEqual({
          reason_code: 'CREDENTIAL_LOST',
          verification_method: 'IN_PERSON',
          identity_verified: true,
        })
        return envelope({
          user_id: 'USER-1', login_name: 'STAFF-1', status: 'ISSUED',
          delivery_channel: 'MANUAL_HANDOFF_REQUIRED', credential: 'once',
          expires_at: '2026-11-01T00:00:00Z',
        })
      }
      if (path === '/api/v1/school/admin/recovery-requests/TICKET-1/approve') return envelope({ credential: 'recovery-once', expires_at: '2026-11-01T00:00:00Z' })
      return envelope({ accepted: true })
    })
    await provider.getLifecycleRosterImport('RUN-1')
    await provider.issueLifecycleCredentials(['USER-1'])
    await provider.inviteSchoolStaff({ employee_ref: 'EMP-1', display_name: '合成教师', role: 'teacher', work_contact: 'synthetic@example.test', verified: true, class_refs: ['CLASS-1'], delivery_channel: 'MANUAL' })
    await provider.acceptStaffInvitation({ invitation_ref: 'INV-1', credential: 'one-time', new_password: 'new password', confirm_password: 'new password' })
    await provider.createRecoveryRequest({ school_ref: 'SCHOOL-1', username: 'STUDENT-1', class_ref: 'CLASS-1', reason_code: 'SYNTHETIC_RECOVERY' })
    await provider.listRecoveryRequests()
    await expect(provider.issueStaffRecoveryCredential('USER-1', {
      reason_code: 'CREDENTIAL_LOST',
      verification_method: 'IN_PERSON',
      identity_verified: true,
    })).resolves.toMatchObject({ data: { status: 'ISSUED', delivery_channel: 'MANUAL_HANDOFF_REQUIRED' } })
    await provider.verifyRecoveryRequest('TICKET-1', 'SYNTHETIC_CHECK')
    await provider.approveRecoveryRequest('TICKET-1', 'SYNTHETIC_APPROVAL')
    await provider.completePasswordReset({ school_ref: 'SCHOOL-1', username: 'STUDENT-1', credential: 'one-time', new_password: 'new password', confirm_password: 'new password' })
    await provider.updateSchoolAccountStatus('USER-1', 'DISABLED', 'SYNTHETIC_ADMIN_REASON')
    await provider.reauthenticate('admin-password')
  })
})
