import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SchoolFeedbackService, type SchoolFeedback } from '@/services/school-feedback'

const feedback = {
  feedback_ref: 'FEED_synthetic_1',
  case_ref: 'PCR_synthetic_case',
  assessment_ref: 'ASSESS_synthetic_1',
  level: 'L3',
  synthetic_only: true,
  content_revision: 1,
  state_version: 1,
  case_version: 3,
  status: 'DRAFT',
  title: '合成反馈标题',
  body: '合成反馈正文。',
  created_at: '2026-10-13T01:02:00Z',
  published_at: null,
  revoked_at: null,
}

const studentFeedback = {
  feedback_ref: 'FEED_synthetic_1',
  assessment_ref: 'ASSESS_synthetic_1',
  level: 'L3',
  synthetic_only: true,
  content_revision: 1,
  state_version: 2,
  status: 'PUBLISHED',
  title: '已发布的合成反馈',
  body: '只对当前学生可见的合成正文。',
  created_at: '2026-10-13T01:02:00Z',
  published_at: '2026-10-13T02:03:00Z',
}

const envelope = (data: unknown) => ({ request_id: 'REQ_synthetic', trace_id: 'TRACE_synthetic', data })
const response = (data: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => data,
}) as Response

describe('SchoolFeedbackService transport and mapping', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => vi.unstubAllGlobals())

  it('maps specialist allowlists and sends the exact case path and bounded page query', async () => {
    fetchMock.mockResolvedValue(response(envelope({ items: [feedback], total: 1 })))
    const service = new SchoolFeedbackService()

    const result = await service.listCase('PCR_synthetic_case', 10, 30)

    expect(result.items[0]?.case_ref).toBe('PCR_synthetic_case')
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/school/feedback/cases/PCR_synthetic_case?offset=10&limit=30'),
      expect.objectContaining({ method: 'GET', credentials: 'include' }),
    )
  })

  it('fetches CSRF and sends strict draft data with the supplied idempotency key', async () => {
    fetchMock
      .mockResolvedValueOnce(response(envelope({ csrf_token: 'csrf-synthetic' })))
      .mockResolvedValueOnce(response(envelope(feedback)))
    const service = new SchoolFeedbackService()

    const result = await service.createDraft(
      'PCR_synthetic_case', 3, '合成反馈标题', '合成反馈正文。', 'stable-draft-key',
    )

    expect(result.status).toBe('DRAFT')
    expect(fetchMock).toHaveBeenNthCalledWith(1, expect.stringContaining('/api/v1/auth/csrf'), expect.any(Object))
    const [url, options] = fetchMock.mock.calls[1] as [string, RequestInit]
    expect(url).toContain('/api/v1/school/feedback/cases/PCR_synthetic_case')
    expect(options.headers).toMatchObject({
      'X-CSRF-Token': 'csrf-synthetic',
      'Idempotency-Key': 'stable-draft-key',
    })
    expect(JSON.parse(String(options.body))).toEqual({
      expected_case_version: 3, title: '合成反馈标题', body: '合成反馈正文。',
    })
  })

  it('publishes and revokes the exact immutable row using both server versions', async () => {
    const published = { ...feedback, status: 'PUBLISHED', state_version: 2, published_at: '2026-10-13T02:00:00Z' }
    const revoked = { ...published, status: 'REVOKED', state_version: 3, revoked_at: '2026-10-13T03:00:00Z' }
    fetchMock
      .mockResolvedValueOnce(response(envelope({ csrf_token: 'csrf-synthetic' })))
      .mockResolvedValueOnce(response(envelope(published)))
      .mockResolvedValueOnce(response(envelope({ csrf_token: 'csrf-synthetic' })))
      .mockResolvedValueOnce(response(envelope(revoked)))
    const service = new SchoolFeedbackService()

    const draftRow = { ...feedback, status: 'DRAFT' } as SchoolFeedback
    const publishedRow = await service.publish(draftRow, 'publish-key')
    const revokedRow = await service.revoke(publishedRow, 'revoke-key')

    expect(publishedRow.state_version).toBe(2)
    expect(revokedRow.state_version).toBe(3)
    const [, publishOptions, , revokeOptions] = fetchMock.mock.calls.map((call) => call[1] as RequestInit)
    expect(JSON.parse(String(publishOptions?.body))).toEqual({
      expected_case_version: 3, expected_state_version: 1,
    })
    expect(publishOptions?.headers).toMatchObject({ 'Idempotency-Key': 'publish-key' })
    expect(JSON.parse(String(revokeOptions?.body))).toEqual({
      expected_case_version: 3, expected_state_version: 2,
    })
    expect(revokeOptions?.headers).toMatchObject({ 'Idempotency-Key': 'revoke-key' })
  })

  it('rejects unallowlisted student data, draft status, and false synthetic flags', async () => {
    const service = new SchoolFeedbackService()
    for (const row of [
      { ...studentFeedback, status: 'DRAFT' },
      { ...studentFeedback, case_ref: 'PCR_private_case' },
      { ...studentFeedback, synthetic_only: false },
    ]) {
      fetchMock.mockResolvedValueOnce(response(envelope({ items: [row], total: 1 })))
      await expect(service.listStudent()).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
    }
  })

  it('rejects fabricated references and invalid drafts before network access', async () => {
    const service = new SchoolFeedbackService()
    await expect(service.listCase('CASE_not_a_feedback_case')).rejects.toMatchObject({ code: 'API_INVALID_REQUEST' })
    await expect(service.createDraft('PCR_synthetic_case', 3, ' ', 'body', 'key'))
      .rejects.toMatchObject({ code: 'VALIDATION_FAILED' })
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
