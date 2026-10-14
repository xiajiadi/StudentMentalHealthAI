import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SchoolResearchFeedbackService } from '@/services/school-research-feedback'

const task = {
  task_ref: 'TASK_research_1',
  class_ref: 'CLASS_synthetic_1',
  class_display_name: '合成班级',
  published_at: '2026-10-14T08:00:00Z',
}

const completedSession = {
  session_ref: 'RSES_synthetic_1',
  task_ref: 'TASK_research_1',
  status: 'COMPLETED',
  items_answered: 8,
  completed_at: '2026-10-14T08:30:00Z',
  case_ref: null,
}

const reviewCase = {
  case_ref: 'RCASE_synthetic_1',
  task_ref: 'TASK_research_1',
  session_ref: 'RSES_synthetic_1',
  status: 'IN_REVIEW',
  version: 2,
  created_at: '2026-10-14T08:40:00Z',
  updated_at: '2026-10-14T08:45:00Z',
  review_note: '合成流程备注',
}

const draft = {
  feedback_ref: 'RFEED_synthetic_1',
  case_ref: 'RCASE_synthetic_1',
  session_ref: 'RSES_synthetic_1',
  feedback_kind: 'GENERAL_EDUCATIONAL_SUPPORT',
  purpose: 'RESEARCH_SIMULATION',
  research_only: true,
  psychological_interpretation_allowed: false,
  publication_status: 'not_approved_for_publication_or_operational_use',
  content_revision: 1,
  case_version: 3,
  state_version: 1,
  status: 'DRAFT',
  title: '合成教育反馈',
  body: '只用于当前演示学生账户的教育支持内容。',
  created_at: '2026-10-14T08:50:00Z',
  published_at: null,
  revoked_at: null,
}

const published = {
  ...draft,
  state_version: 2,
  status: 'PUBLISHED',
  published_at: '2026-10-14T09:00:00Z',
}

const studentPublished = {
  feedback_ref: published.feedback_ref,
  session_ref: published.session_ref,
  feedback_kind: published.feedback_kind,
  purpose: published.purpose,
  research_only: true,
  psychological_interpretation_allowed: false,
  publication_status: published.publication_status,
  content_revision: 1,
  state_version: 2,
  status: 'PUBLISHED',
  title: published.title,
  body: published.body,
  created_at: published.created_at,
  published_at: published.published_at,
}

const envelope = (data: unknown) => ({ request_id: 'REQ_synthetic', trace_id: 'TRACE_synthetic', data })
const response = (data: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => data,
}) as Response

describe('SchoolResearchFeedbackService API contract', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => vi.unstubAllGlobals())

  it('uses research-only endpoints and bounded paging for specialist data', async () => {
    fetchMock
      .mockResolvedValueOnce(response(envelope({ items: [task] })))
      .mockResolvedValueOnce(response(envelope({ items: [completedSession], total: 1 })))
      .mockResolvedValueOnce(response(envelope({ items: [reviewCase], total: 1 })))
    const service = new SchoolResearchFeedbackService()

    expect((await service.listTasks())[0]?.task_ref).toBe(task.task_ref)
    expect((await service.listEligibleSessions(task.task_ref, 20, 20)).items[0]?.status).toBe('COMPLETED')
    expect((await service.listCases(task.task_ref, 0, 20, 'IN_REVIEW')).items[0]?.version).toBe(2)
    expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([
      expect.stringContaining('/api/v1/school/research-feedback/tasks'),
      expect.stringContaining('/tasks/TASK_research_1/eligible-sessions?offset=20&limit=20'),
      expect.stringContaining('/tasks/TASK_research_1/cases?offset=0&limit=20&status=IN_REVIEW'),
    ])
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({ method: 'GET', credentials: 'include' })
  })

  it('sends CSRF, idempotency, and optimistic version fields on a case transition', async () => {
    fetchMock
      .mockResolvedValueOnce(response(envelope({ csrf_token: 'csrf-synthetic' })))
      .mockResolvedValueOnce(response(envelope({ ...reviewCase, status: 'APPROVED', version: 3 })))
    const result = await new SchoolResearchFeedbackService().transitionCase(
      task.task_ref, reviewCase.case_ref, 2, 'APPROVED', '合成流程完成备注', 'research-feedback-key',
    )

    expect(result.version).toBe(3)
    const [url, options] = fetchMock.mock.calls[1] as [string, RequestInit]
    expect(url).toContain('/tasks/TASK_research_1/cases/RCASE_synthetic_1/decision')
    expect(options.headers).toMatchObject({
      'X-CSRF-Token': 'csrf-synthetic',
      'Idempotency-Key': 'research-feedback-key',
    })
    expect(JSON.parse(String(options.body))).toEqual({
      expected_version: 2, status: 'APPROVED', note: '合成流程完成备注',
    })
  })

  it('separates specialist publication from student projection', async () => {
    fetchMock
      .mockResolvedValueOnce(response(envelope({ csrf_token: 'csrf-synthetic' })))
      .mockResolvedValueOnce(response(envelope(published)))
      .mockResolvedValueOnce(response(envelope({ items: [studentPublished], total: 1 })))
    const service = new SchoolResearchFeedbackService()

    const row = await service.publish(draft as never, 'research-publish-key')
    const studentPage = await service.listStudent()
    expect(row.status).toBe('PUBLISHED')
    expect(studentPage.items[0]?.status).toBe('PUBLISHED')
    expect(studentPage.items[0]).not.toHaveProperty('case_ref')
    const [publishUrl, publishOptions] = fetchMock.mock.calls[1] as [string, RequestInit]
    expect(publishUrl).toContain('/feedback/RFEED_synthetic_1/publish')
    expect(JSON.parse(String(publishOptions.body))).toEqual({ expected_state_version: 1, expected_case_version: 3 })
    expect(fetchMock.mock.calls[2]?.[0]).toContain('/school/research-feedback/student?offset=0&limit=20')
  })

  it('rejects nonresearch, unpublished, or expanded student payloads', async () => {
    const service = new SchoolResearchFeedbackService()
    for (const item of [
      { ...studentPublished, status: 'DRAFT' },
      { ...studentPublished, case_ref: 'RCASE_private' },
      { ...studentPublished, psychological_interpretation_allowed: true },
      { ...studentPublished, publication_status: 'approved' },
    ]) {
      fetchMock.mockResolvedValueOnce(response(envelope({ items: [item], total: 1 })))
      await expect(service.listStudent()).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
    }
  })

  it('rejects invalid refs and page sizes before network access', async () => {
    const service = new SchoolResearchFeedbackService()
    await expect(service.listCases('../task')).rejects.toMatchObject({ code: 'API_INVALID_REQUEST' })
    await expect(service.listStudent(0, 100)).rejects.toMatchObject({ code: 'VALIDATION_FAILED' })
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
