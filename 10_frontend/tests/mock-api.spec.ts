import { beforeEach, describe, expect, it } from 'vitest'
import { MockApiError, MockApiProvider } from '@/services/mock-api'

describe('Mock API 适配器', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/')
  })

  it('按接口边界完成测评会话，并在达到条件后允许结束', async () => {
    const api = new MockApiProvider()
    const started = await api.startAssessment()

    expect(started.data.current_index).toBe(0)
    expect(started.data.can_complete).toBe(false)

    let current = started.data
    for (let index = 0; index < 3; index += 1) {
      const response = await api.submitAssessmentResponse(current.assessment_id, current.question?.item_id || '', '2')
      current = response.data
    }

    expect(current.answered_count).toBe(3)
    expect(current.can_complete).toBe(true)
    const completed = await api.completeAssessment(current.assessment_id)
    expect(completed.data.status).toBe('completed')
  })

  it('保留可恢复的登录错误分类', async () => {
    const api = new MockApiProvider()
    await expect(api.login({ account: 'demo', password: 'wrong', role: 'student' })).rejects.toMatchObject({ code: 'AUTH_UNAUTHORIZED' })

    try {
      await api.login({ account: 'demo', password: 'network', role: 'student' })
    } catch (error) {
      expect(error).toBeInstanceOf(MockApiError)
      expect((error as MockApiError).code).toBe('NETWORK_UNAVAILABLE')
      expect((error as MockApiError).retryable).toBe(true)
    }
  })

  it('提交复核后拒绝重复写入', async () => {
    const api = new MockApiProvider()
    const detail = await api.getReviewDetail('REVIEW_demo_001')
    const result = await api.submitReview(detail.data.case.report_id, { decision: 'approved', note: '合成验收记录' })

    expect(result.data.status).toBe('APPROVED')
    await expect(api.submitReview(detail.data.case.report_id, { decision: 'approved', note: '' })).rejects.toMatchObject({ code: 'CONFLICT_IDEMPOTENCY' })
  })
})
