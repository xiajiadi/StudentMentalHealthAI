import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SpecialistTaskReviews from '@/components/school/SpecialistTaskReviews.vue'
import { useSessionStore } from '@/stores/session'

const reviewApi = vi.hoisted(() => ({
  listTasks: vi.fn(), listEligibleEnrollments: vi.fn(), listCases: vi.fn(), getCase: vi.fn(),
  createCase: vi.fn(), openCase: vi.fn(), decideCase: vi.fn(), newKey: vi.fn(),
}))
const feedbackApi = vi.hoisted(() => ({ listCase: vi.fn(), createDraft: vi.fn(), publish: vi.fn(), revoke: vi.fn() }))
vi.mock('@/services/professional-reviews', () => ({
  professionalReviews: {
    listTasks: reviewApi.listTasks,
    listEligibleEnrollments: reviewApi.listEligibleEnrollments,
    listCases: reviewApi.listCases,
    getCase: reviewApi.getCase,
    createCase: reviewApi.createCase,
    openCase: reviewApi.openCase,
    decideCase: reviewApi.decideCase,
  },
  newProfessionalReviewIdempotencyKey: reviewApi.newKey,
}))
vi.mock('@/services/school-feedback', () => ({
  schoolFeedback: {
    listCase: feedbackApi.listCase,
    createDraft: feedbackApi.createDraft,
    publish: feedbackApi.publish,
    revoke: feedbackApi.revoke,
  },
  newSchoolFeedbackIdempotencyKey: vi.fn(() => 'stable-feedback-test-key'),
}))

const task = { task_ref: 'TASK_SYNTHETIC_1', class_ref: 'CLASS_SYNTHETIC_1', class_display_name: null as string | null, published_at: '2026-10-12T00:00:00Z' }
const enrollment = { enrollment_ref: 'ENROLLMENT_SYNTHETIC_1', assessment_ref: 'ASSESSMENT_SYNTHETIC_1', completed_at: '2026-10-11T03:00:00Z', case_ref: null as string | null }
const reviewCase = {
  case_ref: 'PCR_SYNTHETIC_1', task_ref: task.task_ref, enrollment_ref: enrollment.enrollment_ref,
  assessment_ref: enrollment.assessment_ref, status: 'OPEN' as 'OPEN' | 'IN_REVIEW' | 'APPROVED',
  publication_status: 'NOT_PUBLISHED' as const, version: 1, created_at: '2026-10-12T01:00:00Z', updated_at: '2026-10-12T01:00:00Z',
  decision: null as 'APPROVED' | null, review_note: null as string | null,
}
const page = (items: unknown[]) => ({ items, total: items.length })

function prepare() {
  const pinia = createPinia()
  setActivePinia(pinia)
  useSessionStore(pinia).signIn({
    userId: 'USER_SYNTHETIC_SPECIALIST', role: 'psychological_specialist', subjectId: null,
    displayName: '合成心理老师', initials: '专',
    activeContext: { role: 'psychological_specialist', schoolRef: 'SCHOOL_SYNTHETIC_A' },
  })
  reviewApi.listTasks.mockResolvedValue([task])
  reviewApi.listEligibleEnrollments.mockResolvedValue(page([enrollment]))
  reviewApi.listCases.mockResolvedValue(page([]))
  reviewApi.getCase.mockResolvedValue(reviewCase)
  reviewApi.newKey.mockReturnValue('stable-synthetic-key')
  feedbackApi.listCase.mockResolvedValue({ items: [], total: 0 })
  return mount(SpecialistTaskReviews, { global: { plugins: [pinia] } })
}

async function selectFirstRecord(wrapper: ReturnType<typeof mount>) {
  await flushPromises()
  await wrapper.get('.task-option').trigger('click')
  await flushPromises()
  await wrapper.get('.record-option').trigger('click')
  await flushPromises()
}

afterEach(() => vi.clearAllMocks())

describe('specialist task review workflow', () => {
  it('creates, opens and decides with server versions while keeping technical IDs and publication out of the UI', async () => {
    const wrapper = prepare()
    await selectFirstRecord(wrapper)
    expect(wrapper.text()).toContain('任务 01')

    const created = { ...reviewCase }
    reviewApi.createCase.mockResolvedValueOnce(created)
    reviewApi.listEligibleEnrollments.mockResolvedValue(page([{ ...enrollment, case_ref: created.case_ref }]))
    reviewApi.listCases.mockResolvedValue(page([created]))
    await wrapper.get('button').trigger('click') // refresh task list, then select the task below
    await wrapper.get('.task-option').trigger('click')
    await flushPromises()
    await wrapper.get('.record-option').trigger('click')
    await flushPromises()
    await wrapper.get('.case-create .reviews-button').trigger('click')
    await flushPromises()
    expect(reviewApi.createCase).toHaveBeenCalledWith(task.task_ref, enrollment.enrollment_ref, 'stable-synthetic-key')

    reviewApi.openCase.mockResolvedValueOnce({ ...created, status: 'IN_REVIEW', version: 2 })
    await wrapper.get('.case-detail .reviews-button').trigger('click')
    await flushPromises()
    expect(reviewApi.openCase).toHaveBeenCalledWith(task.task_ref, created.case_ref, 1, 'stable-synthetic-key')

    const textarea = wrapper.get('#professional-review-note')
    await textarea.setValue('合成演示工作流备注')
    reviewApi.decideCase.mockResolvedValueOnce({ ...created, status: 'APPROVED', decision: 'APPROVED', version: 3, review_note: '合成演示工作流备注' })
    const approve = wrapper.findAll('button').find((button) => button.text() === '确认完成')
    expect(approve).toBeTruthy()
    await approve!.trigger('click')
    await flushPromises()
    expect(reviewApi.decideCase).toHaveBeenCalledWith(task.task_ref, created.case_ref, 2, 'APPROVED', '合成演示工作流备注', 'stable-synthetic-key')
    expect(wrapper.text()).toContain('复核决定不会自动发布；学生反馈需在下方单独发布。')
    expect(wrapper.text()).not.toContain(task.task_ref)
    expect(wrapper.text()).not.toContain(enrollment.enrollment_ref)
    expect(wrapper.text()).not.toContain(created.case_ref)
    reviewApi.listTasks.mockResolvedValueOnce([])
    await wrapper.get('.reviews-toolbar button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('合成演示工作流备注')
    expect(wrapper.text()).toContain('已清除本页缓存')
    wrapper.unmount()
  })

  it('retains the exact failed request and only retries after an explicit action', async () => {
    const wrapper = prepare()
    await selectFirstRecord(wrapper)
    const failure = Object.assign(new Error('连接暂不可用'), { code: 'NETWORK_UNAVAILABLE', retryable: true })
    reviewApi.createCase.mockRejectedValueOnce(failure).mockResolvedValueOnce(reviewCase)
    await wrapper.get('.case-create .reviews-button').trigger('click')
    await flushPromises()
    expect(reviewApi.createCase).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('使用相同请求重试')
    const retry = wrapper.findAll('button').find((button) => button.text() === '使用相同请求重试')
    await retry!.trigger('click')
    await flushPromises()
    expect(reviewApi.createCase).toHaveBeenCalledTimes(2)
    expect(reviewApi.createCase.mock.calls[0]).toEqual(reviewApi.createCase.mock.calls[1])
    wrapper.unmount()
  })

  it('locks task navigation while a write is unresolved so its retry cannot target a stale selection', async () => {
    const wrapper = prepare()
    await selectFirstRecord(wrapper)
    let finish!: (value: typeof reviewCase) => void
    reviewApi.createCase.mockReturnValueOnce(new Promise((resolve) => { finish = resolve }))
    await wrapper.get('.case-create .reviews-button').trigger('click')
    await flushPromises()
    expect(wrapper.get('.task-option').attributes('disabled')).toBeDefined()
    finish({ ...reviewCase })
    await flushPromises()
    expect(wrapper.get('.task-option').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('does not replace a case automatically on a version conflict; refresh is explicit', async () => {
    const wrapper = prepare()
    await selectFirstRecord(wrapper)
    reviewApi.createCase.mockResolvedValueOnce(reviewCase)
    reviewApi.listEligibleEnrollments.mockResolvedValue(page([{ ...enrollment, case_ref: reviewCase.case_ref }]))
    reviewApi.listCases.mockResolvedValue(page([reviewCase]))
    await wrapper.get('.case-create .reviews-button').trigger('click')
    await flushPromises()
    reviewApi.openCase.mockRejectedValueOnce(Object.assign(new Error('状态已变化'), { code: 'workflow_conflict' }))
    await wrapper.get('.case-detail .reviews-button').trigger('click')
    await flushPromises()
    expect(reviewApi.getCase).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('记录状态已变化')
    expect(wrapper.text()).not.toContain('使用相同请求重试')
    const refresh = wrapper.findAll('button').find((button) => button.text() === '刷新服务端状态')
    await refresh!.trigger('click')
    await flushPromises()
    expect(reviewApi.getCase).toHaveBeenCalledWith(task.task_ref, reviewCase.case_ref)
    wrapper.unmount()
  })
})
