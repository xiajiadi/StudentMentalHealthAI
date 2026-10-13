import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { RealApiError } from '@/services/real-api'
import type { SchoolFeedback, StudentSchoolFeedback } from '@/services/school-feedback'

const api = vi.hoisted(() => ({
  listAssessmentEntries: vi.fn(),
  listAssessments: vi.fn(),
  listReports: vi.fn(),
}))
const feedback = vi.hoisted(() => ({
  listCase: vi.fn(),
  createDraft: vi.fn(),
  publish: vi.fn(),
  revoke: vi.fn(),
  listStudent: vi.fn(),
}))
const keyFactory = vi.hoisted(() => vi.fn(() => 'school-feedback-synthetic-key'))

vi.mock('@/services/mock-api', () => ({ frontendApi: api }))
vi.mock('@/services/school-feedback', () => ({
  schoolFeedback: feedback,
  newSchoolFeedbackIdempotencyKey: keyFactory,
}))

import SpecialistFeedbackPanel from '@/components/school/SpecialistFeedbackPanel.vue'
import StudentFeedbackView from '@/views/student/StudentFeedbackView.vue'
import { useSessionStore } from '@/stores/session'

function specialistDto(overrides: Partial<SchoolFeedback> = {}): SchoolFeedback {
  return {
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
    ...overrides,
  }
}

function studentDto(overrides: Partial<StudentSchoolFeedback> = {}): StudentSchoolFeedback {
  return {
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
    ...overrides,
  }
}

describe('SpecialistFeedbackPanel interactions', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    feedback.listCase.mockResolvedValue({ items: [], total: 0 })
  })

  const mountPanel = (caseStatus: 'OPEN' | 'IN_REVIEW' | 'APPROVED' | 'REJECTED' = 'APPROVED') => mount(SpecialistFeedbackPanel, {
    props: { caseRef: 'PCR_synthetic_case', caseVersion: 3, caseStatus },
    global: { plugins: [createPinia()] },
  })

  it('shows an empty state and only permits draft creation after case approval', async () => {
    const wrapper = mountPanel('IN_REVIEW')
    await flushPromises()
    expect(wrapper.text()).toContain('还没有独立反馈')
    expect(wrapper.text()).toContain('复核获批后')
    expect(wrapper.find('form.feedback-draft').exists()).toBe(false)
    wrapper.unmount()
  })

  it('creates immutable draft data and displays the returned revision state', async () => {
    feedback.createDraft.mockResolvedValue(specialistDto())
    feedback.listCase
      .mockResolvedValueOnce({ items: [], total: 0 })
      .mockResolvedValueOnce({ items: [specialistDto()], total: 1 })
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.get('#feedback-title').setValue('合成反馈标题')
    await wrapper.get('#feedback-body').setValue('合成反馈正文。')
    await wrapper.get('form.feedback-draft').trigger('submit')
    await flushPromises()

    expect(feedback.createDraft).toHaveBeenCalledWith(
      'PCR_synthetic_case', 3, '合成反馈标题', '合成反馈正文。', 'school-feedback-synthetic-key',
    )
    expect(wrapper.text()).toContain('草稿')
    expect(wrapper.text()).toContain('修订 1')
    wrapper.unmount()
  })

  it('reloads and replaces the private history when the selected case changes', async () => {
    feedback.listCase
      .mockResolvedValueOnce({ items: [specialistDto()], total: 1 })
      .mockResolvedValueOnce({ items: [specialistDto({ case_ref: 'PCR_next_case', title: '下一条合成反馈' })], total: 1 })
    const wrapper = mount(SpecialistFeedbackPanel, {
      props: { caseRef: 'PCR_synthetic_case', caseVersion: 3, caseStatus: 'APPROVED' },
      global: { plugins: [createPinia()] },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('合成反馈正文。')
    await wrapper.setProps({ caseRef: 'PCR_next_case', caseVersion: 4 })
    await flushPromises()
    expect(feedback.listCase).toHaveBeenCalledTimes(2)
    expect(feedback.listCase).toHaveBeenLastCalledWith('PCR_next_case')
    expect(wrapper.text()).toContain('下一条合成反馈')
    expect(wrapper.text()).not.toContain('合成反馈标题')
    wrapper.unmount()
  })

  it('requires explicit publication acknowledgement and reuses an uncertain request key', async () => {
    feedback.listCase
      .mockResolvedValueOnce({ items: [specialistDto()], total: 1 })
      .mockResolvedValueOnce({ items: [specialistDto({ status: 'PUBLISHED', state_version: 2, published_at: '2026-10-13T02:00:00Z' })], total: 1 })
    feedback.publish
      .mockRejectedValueOnce(new RealApiError('NETWORK_UNAVAILABLE', 'unavailable', true))
      .mockResolvedValueOnce(specialistDto({ status: 'PUBLISHED', state_version: 2, published_at: '2026-10-13T02:00:00Z' }))
    const wrapper = mountPanel()
    await flushPromises()
    const publishButton = () => wrapper.findAll('button').find((button) => button.text().includes('发布给当前学生'))!
    expect(publishButton().attributes('disabled')).toBeDefined()
    await wrapper.get('input[type="radio"]').setValue()
    expect(publishButton().attributes('disabled')).toBeUndefined()
    await publishButton().trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('使用相同请求重试')
    const firstCall = feedback.publish.mock.calls[0]
    await wrapper.findAll('button').find((button) => button.text().includes('使用相同请求重试'))!.trigger('click')
    await flushPromises()
    expect(feedback.publish.mock.calls[1]).toEqual(firstCall)
    expect(wrapper.text()).toContain('已发布')
    wrapper.unmount()
  })

  it('requires explicit revoke confirmation for a published version', async () => {
    const published = specialistDto({ status: 'PUBLISHED', state_version: 2, published_at: '2026-10-13T02:00:00Z' })
    feedback.listCase
      .mockResolvedValueOnce({ items: [published], total: 1 })
      .mockResolvedValueOnce({ items: [specialistDto({ ...published, status: 'REVOKED', state_version: 3, revoked_at: '2026-10-13T03:00:00Z' })], total: 1 })
    feedback.revoke.mockResolvedValue(specialistDto({ ...published, status: 'REVOKED', state_version: 3, revoked_at: '2026-10-13T03:00:00Z' }))
    const wrapper = mountPanel()
    await flushPromises()
    const revokeButton = () => wrapper.findAll('button').find((button) => button.text().includes('撤回学生可见反馈'))!
    expect(revokeButton().attributes('disabled')).toBeDefined()
    await wrapper.get('input[type="radio"]').setValue()
    expect(revokeButton().attributes('disabled')).toBeUndefined()
    await revokeButton().trigger('click')
    await flushPromises()
    expect(feedback.revoke).toHaveBeenCalledWith(published, 'school-feedback-synthetic-key')
    expect(wrapper.text()).toContain('已撤回')
    wrapper.unmount()
  })

  it('clears private cached feedback when the active role changes', async () => {
    feedback.listCase.mockResolvedValue({ items: [specialistDto()], total: 1 })
    const pinia = createPinia()
    const session = useSessionStore(pinia)
    const wrapper = mount(SpecialistFeedbackPanel, {
      props: { caseRef: 'PCR_synthetic_case', caseVersion: 3, caseStatus: 'APPROVED' },
      global: { plugins: [pinia] },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('合成反馈正文。')
    session.signIn({
      userId: 'USER_synthetic_teacher', role: 'teacher', subjectId: null,
      displayName: 'Synthetic Teacher', initials: 'S',
    })
    await flushPromises()
    expect(wrapper.text()).not.toContain('合成反馈正文。')
    expect(wrapper.text()).toContain('身份已变化')
    wrapper.unmount()
  })

  it('clears and reloads private feedback when the active context object changes within the same school and role', async () => {
    feedback.listCase
      .mockResolvedValueOnce({ items: [specialistDto()], total: 1 })
      .mockResolvedValueOnce({ items: [], total: 0 })
    const pinia = createPinia()
    const session = useSessionStore(pinia)
    session.signIn({
      userId: 'USER_synthetic_specialist', role: 'psychological_specialist', subjectId: null,
      displayName: 'Synthetic Specialist', initials: 'S',
      activeContext: { role: 'psychological_specialist', schoolRef: 'SCHOOL_ALPHA_SYNTHETIC' },
    })
    const wrapper = mount(SpecialistFeedbackPanel, {
      props: { caseRef: 'PCR_synthetic_case', caseVersion: 3, caseStatus: 'APPROVED' },
      global: { plugins: [pinia] },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('合成反馈正文。')
    session.signIn({
      userId: 'USER_synthetic_specialist', role: 'psychological_specialist', subjectId: null,
      displayName: 'Synthetic Specialist', initials: 'S',
      activeContext: { role: 'psychological_specialist', schoolRef: 'SCHOOL_ALPHA_SYNTHETIC' },
    })
    await flushPromises()
    expect(feedback.listCase).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).not.toContain('合成反馈正文。')
    wrapper.unmount()
  })
})

describe('StudentFeedbackView published feedback section', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.listAssessmentEntries.mockResolvedValue({ data: [{
      assessment_id: 'ASSESS_synthetic_completed', status: 'completed', items_answered: 4,
      started_at: null, completed_at: '2026-10-12T01:00:00Z',
    }] })
    api.listAssessments.mockResolvedValue({ data: [] })
    api.listReports.mockResolvedValue({ data: { items: [] } })
    feedback.listStudent.mockResolvedValue({ items: [studentDto()], total: 1 })
  })

  it('renders only published plaintext, synthetic L3 label, timestamp and keeps L1 completion metadata', async () => {
    const wrapper = mount(StudentFeedbackView, {
      global: { plugins: [createPinia()], stubs: { RouterLink: true } },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('已发布的学生反馈')
    expect(wrapper.text()).toContain('合成演示 · L3')
    expect(wrapper.text()).toContain('只对当前学生可见的合成正文。')
    expect(wrapper.text()).toContain('已完成的合成测评')
    expect(wrapper.text()).toContain('发布于')
    expect(wrapper.find('.feedback-section--completed').text()).toContain('暂无测量报告')
    expect(wrapper.find('.feedback-section--completed').text()).toContain('这项测评尚未提供可查看的测量报告')
    expect(wrapper.text()).not.toContain('当前没有获准发布的反馈')
    expect(wrapper.text()).not.toContain('PCR_')
    wrapper.unmount()
  })

  it('shows an explicit empty state when the published list has no rows', async () => {
    feedback.listStudent.mockResolvedValue({ items: [], total: 0 })
    const wrapper = mount(StudentFeedbackView, {
      global: { plugins: [createPinia()], stubs: { RouterLink: true } },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('目前没有单独发布的反馈')
    expect(wrapper.find('.published-feedback__row').exists()).toBe(false)
    wrapper.unmount()
  })

  it('shows feedback API errors separately and preserves existing completion metadata', async () => {
    feedback.listStudent.mockRejectedValue(new RealApiError('NETWORK_UNAVAILABLE', 'network unavailable', true))
    const wrapper = mount(StudentFeedbackView, {
      global: { plugins: [createPinia()], stubs: { RouterLink: true } },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('已发布反馈暂时无法加载')
    expect(wrapper.text()).toContain('已完成的合成测评')
    expect(wrapper.text()).not.toContain('只对当前学生可见的合成正文。')
    wrapper.unmount()
  })

  it('clears and reloads student feedback on same-school active-context replacement', async () => {
    const pinia = createPinia()
    const session = useSessionStore(pinia)
    feedback.listStudent
      .mockResolvedValueOnce({ items: [studentDto()], total: 1 })
      .mockResolvedValueOnce({ items: [studentDto()], total: 1 })
      .mockResolvedValueOnce({ items: [], total: 0 })
    const wrapper = mount(StudentFeedbackView, {
      global: { plugins: [pinia], stubs: { RouterLink: true } },
    })
    await flushPromises()
    session.signIn({
      userId: 'USER_synthetic_student', role: 'student', subjectId: 'SUBJ_synthetic',
      displayName: 'Synthetic Student', initials: 'S',
      activeContext: { role: 'student', schoolRef: 'SCHOOL_ALPHA_SYNTHETIC' },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('只对当前学生可见的合成正文。')
    session.signIn({
      userId: 'USER_synthetic_student', role: 'student', subjectId: 'SUBJ_synthetic',
      displayName: 'Synthetic Student', initials: 'S',
      activeContext: { role: 'student', schoolRef: 'SCHOOL_ALPHA_SYNTHETIC' },
    })
    await flushPromises()
    expect(feedback.listStudent).toHaveBeenCalledTimes(3)
    expect(wrapper.text()).not.toContain('只对当前学生可见的合成正文。')
    wrapper.unmount()
  })
})
