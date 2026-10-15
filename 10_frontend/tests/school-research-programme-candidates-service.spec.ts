import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SchoolResearchProgrammeCandidateService } from '@/services/school-research-programme-candidates'

const envelope = (data: unknown) => ({ request_id: 'REQ_synthetic', trace_id: 'TRACE_synthetic', data })
const response = (data: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => data,
}) as Response

const batchReceipt = {
  batch_ref: `REJBATCH_${'b'.repeat(64)}`,
  job_refs: [`REJ_${'a'.repeat(64)}`, `REJ_${'c'.repeat(64)}`],
  job_count: 2,
  next_cursor: `REJ_${'c'.repeat(64)}`,
  policy_version: 'RESEARCH_STAFF_PROGRAMME_POLICY_V1',
  purpose: 'RESEARCH_SIMULATION',
  research_only: true,
  publication_status: 'not_approved_for_publication_or_operational_use',
  student_feedback_eligible: false,
}

const statusCounts = {
  QUEUED: 1, LEASED: 0, RETRY: 1, HELD: 0, ABSTAINED: 0,
  REVIEW_REQUIRED: 0, CRISIS_ROUTED: 0, FAILED: 0, CANCELLED: 0,
}

const jobPage = {
  items: [{
    job_ref: `REJ_${'a'.repeat(64)}`,
    status: 'QUEUED',
    attempt_count: 0,
    updated_at: '2026-10-15T08:00:00Z',
    last_error_code: null,
  }],
  offset: 0,
  limit: 25,
  total: 2,
  has_more: true,
  status_counts: statusCounts,
  policy_version: 'RESEARCH_STAFF_PROGRAMME_POLICY_V1',
  purpose: 'RESEARCH_SIMULATION',
  research_only: true,
  publication_status: 'not_approved_for_publication_or_operational_use',
  student_feedback_eligible: false,
}

describe('SchoolResearchProgrammeCandidateService batch queue and job status', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => vi.unstubAllGlobals())

  it('posts a bounded batch with CSRF and the stable page idempotency key', async () => {
    fetchMock
      .mockResolvedValueOnce(response(envelope({ csrf_token: 'csrf-synthetic' })))
      .mockResolvedValueOnce(response(envelope(batchReceipt)))
    const service = new SchoolResearchProgrammeCandidateService()

    const result = await service.queueGenerationBatch(
      'TASK_synthetic_1', 'batch-page-key', 25, `REJ_${'9'.repeat(64)}`,
    )

    expect(result.job_count).toBe(2)
    expect(result.next_cursor).toBe(batchReceipt.next_cursor)
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain('/api/v1/auth/csrf')
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ method: 'GET', credentials: 'include' })
    const [url, init] = fetchMock.mock.calls[1] as [unknown, RequestInit]
    expect(String(url)).toContain('/api/v1/school/research-programme-candidates/tasks/TASK_synthetic_1/queue-generation/batch')
    expect(init.method).toBe('POST')
    expect(init.credentials).toBe('include')
    expect(init.headers).toMatchObject({
      'Content-Type': 'application/json',
      'X-CSRF-Token': 'csrf-synthetic',
      'Idempotency-Key': 'batch-page-key',
    })
    expect(JSON.parse(String(init.body))).toEqual({ limit: 25, after_job_ref: `REJ_${'9'.repeat(64)}` })
  })

  it('reads task-scoped status pages and preserves the server aggregate including RETRY', async () => {
    fetchMock.mockResolvedValueOnce(response(envelope({ ...jobPage, offset: 25, limit: 25, items: [], has_more: false })))
    const service = new SchoolResearchProgrammeCandidateService()

    const result = await service.listGenerationJobs('TASK_synthetic_1', 25, 25)

    expect(result.total).toBe(2)
    expect(result.status_counts.RETRY).toBe(1)
    expect(result.items).toEqual([])
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain('/api/v1/school/research-programme-candidates/tasks/TASK_synthetic_1/generation-jobs?offset=25&limit=25')
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ method: 'GET', credentials: 'include' })
  })

  it('rejects job status payloads outside the staff research-only boundary', async () => {
    fetchMock.mockResolvedValueOnce(response(envelope({ ...jobPage, student_feedback_eligible: true })))
    const service = new SchoolResearchProgrammeCandidateService()

    await expect(service.listGenerationJobs('TASK_synthetic_1')).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })
})
