import { afterEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ requestProfessionalReview: vi.fn() }))
vi.mock('@/services/real-api', () => ({
  RealApiError: class RealApiError extends Error {
    constructor(public code: string, message: string) { super(message) }
  },
  requestProfessionalReview: transport.requestProfessionalReview,
}))

import { ProfessionalReviewsService } from '@/services/professional-reviews'

const envelope = (data: unknown) => ({ request_id: 'REQ_synthetic_review', trace_id: 'TRACE_synthetic_review', data })
const caseDto = {
  case_ref: 'PCR_SYNTHETIC_1', task_ref: 'TASK_SYNTHETIC_1', enrollment_ref: 'ENROLLMENT_SYNTHETIC_1',
  assessment_ref: 'ASSESSMENT_SYNTHETIC_1', status: 'OPEN', publication_status: 'NOT_PUBLISHED', version: 1,
  created_at: '2026-10-12T01:00:00Z', updated_at: '2026-10-12T01:00:00Z', decision: null, review_note: null,
}

afterEach(() => vi.clearAllMocks())

describe('professional review transport adapter', () => {
  it('uses the assigned-task routes and maps date-only labels without exposing unapproved response fields', async () => {
    transport.requestProfessionalReview
      .mockResolvedValueOnce(envelope([{ task_ref: 'TASK_SYNTHETIC_1', class_ref: 'CLASS_SYNTHETIC_1', class_display_name: null, published_at: '2026-10-12T00:00:00Z' }]))
      .mockResolvedValueOnce(envelope({ items: [{ enrollment_ref: 'ENROLLMENT_SYNTHETIC_1', assessment_ref: 'ASSESSMENT_SYNTHETIC_1', completed_at: '2026-10-11T03:00:00Z', case_ref: null }], total: 1 }))
      .mockResolvedValueOnce(envelope({ items: [caseDto], total: 1 }))
      .mockResolvedValueOnce(envelope(caseDto))
    const service = new ProfessionalReviewsService()

    await expect(service.listTasks()).resolves.toMatchObject([{ class_display_name: null }])
    await expect(service.listEligibleEnrollments('TASK_SYNTHETIC_1', 20, 10)).resolves.toMatchObject({ total: 1 })
    await expect(service.listCases('TASK_SYNTHETIC_1')).resolves.toMatchObject({ items: [{ publication_status: 'NOT_PUBLISHED' }] })
    await expect(service.getCase('TASK_SYNTHETIC_1', 'PCR_SYNTHETIC_1')).resolves.toMatchObject({ version: 1 })
    expect(transport.requestProfessionalReview.mock.calls.map(([request]) => request)).toEqual([
      { method: 'GET', path: '/api/v1/school/professional-reviews/tasks' },
      { method: 'GET', path: '/api/v1/school/professional-reviews/tasks/TASK_SYNTHETIC_1/eligible-enrollments', query: { offset: 20, limit: 10 } },
      { method: 'GET', path: '/api/v1/school/professional-reviews/tasks/TASK_SYNTHETIC_1/cases', query: { offset: 0, limit: 20 } },
      { method: 'GET', path: '/api/v1/school/professional-reviews/tasks/TASK_SYNTHETIC_1/cases/PCR_SYNTHETIC_1' },
    ])
  })

  it('sends caller-owned idempotency keys and the expected server version on every write', async () => {
    transport.requestProfessionalReview
      .mockResolvedValueOnce(envelope(caseDto))
      .mockResolvedValueOnce(envelope({ ...caseDto, status: 'IN_REVIEW', version: 2 }))
      .mockResolvedValueOnce(envelope({ ...caseDto, status: 'APPROVED', decision: 'APPROVED', version: 3, review_note: '合成工作流备注' }))
    const service = new ProfessionalReviewsService()
    await service.createCase('TASK_SYNTHETIC_1', 'ENROLLMENT_SYNTHETIC_1', 'stable-create-key')
    await service.openCase('TASK_SYNTHETIC_1', 'PCR_SYNTHETIC_1', 1, 'stable-open-key')
    await service.decideCase('TASK_SYNTHETIC_1', 'PCR_SYNTHETIC_1', 2, 'APPROVED', '合成工作流备注', 'stable-decision-key')

    expect(transport.requestProfessionalReview.mock.calls.map(([request]) => request)).toEqual([
      { method: 'POST', path: '/api/v1/school/professional-reviews/tasks/TASK_SYNTHETIC_1/cases', body: { enrollment_ref: 'ENROLLMENT_SYNTHETIC_1' }, idempotencyKey: 'stable-create-key' },
      { method: 'POST', path: '/api/v1/school/professional-reviews/tasks/TASK_SYNTHETIC_1/cases/PCR_SYNTHETIC_1/open', body: { expected_version: 1 }, idempotencyKey: 'stable-open-key' },
      { method: 'POST', path: '/api/v1/school/professional-reviews/tasks/TASK_SYNTHETIC_1/cases/PCR_SYNTHETIC_1/decision', body: { expected_version: 2, decision: 'APPROVED', note: '合成工作流备注' }, idempotencyKey: 'stable-decision-key' },
    ])
  })

  it('fails closed if a case response claims publication or an unsupported status', async () => {
    transport.requestProfessionalReview.mockResolvedValueOnce(envelope({ ...caseDto, publication_status: 'PUBLISHED' }))
    const service = new ProfessionalReviewsService()
    await expect(service.getCase('TASK_SYNTHETIC_1', 'PCR_SYNTHETIC_1')).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })

  it('rejects a malformed non-null task label instead of manufacturing a display name', async () => {
    transport.requestProfessionalReview.mockResolvedValueOnce(envelope([{
      task_ref: 'TASK_SYNTHETIC_1', class_ref: 'CLASS_SYNTHETIC_1', class_display_name: 7, published_at: '2026-10-12T00:00:00Z',
    }]))
    await expect(new ProfessionalReviewsService().listTasks()).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })
})
