import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { RealApiError } from '@/services/real-api'

const service = vi.hoisted(() => ({
  listTasks: vi.fn(),
  listEligibleSessions: vi.fn(),
  listCases: vi.fn(),
  getCase: vi.fn(),
  createCase: vi.fn(),
  transitionCase: vi.fn(),
  listFeedback: vi.fn(),
  createDraft: vi.fn(),
  publish: vi.fn(),
  revoke: vi.fn(),
  listStudent: vi.fn(),
}))
const keyFactory = vi.hoisted(() => vi.fn(() => 'research-feedback-synthetic-key'))

vi.mock('@/services/school-research-feedback', () => ({
  schoolResearchFeedback: service,
  newResearchFeedbackIdempotencyKey: keyFactory,
}))

import SpecialistResearchFeedback from '@/components/school/SpecialistResearchFeedback.vue'
import StudentResearchFeedback from '@/components/school/StudentResearchFeedback.vue'
import { useSessionStore } from '@/stores/session'

const task = {
  task_ref: 'TASK_research_1', class_ref: 'CLASS_synthetic_1',
  class_display_name: '合成班级', published_at: '2026-10-14T08:00:00Z',
}
const completedSession = {
  session_ref: 'RSES_private_synthetic', task_ref: task.task_ref, status: 'COMPLETED',
  items_answered: 8, completed_at: '2026-10-14T08:30:00Z', case_ref: 'RCASE_private_synthetic',
}
const reviewCase = {
  case_ref: 'RCASE_private_synthetic', task_ref: task.task_ref, session_ref: completedSession.session_ref,
  status: 'OPEN', version: 1, created_at: '2026-10-14T08:40:00Z', updated_at: '2026-10-14T08:40:00Z', review_note: null,
}
const studentFeedback = {
  feedback_ref: 'RFEED_private_synthetic', session_ref: 'RSES_private_synthetic',
  feedback_kind: 'GENERAL_EDUCATIONAL_SUPPORT', purpose: 'RESEARCH_SIMULATION', research_only: true,
  psychological_interpretation_allowed: false,
  publication_status: 'not_approved_for_publication_or_operational_use',
  content_revision: 1, state_version: 1, status: 'PUBLISHED', title: '合成教育反馈标题',
  body: '仅用于当前合成演示账户的教育支持内容。', created_at: '2026-10-14T08:50:00Z',
  published_at: '2026-10-14T09:00:00Z',
}

function signIn(role: 'psychological_specialist' | 'student') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const session = useSessionStore()
  session.signIn({
    userId: `USER_synthetic_${role}`, role, subjectId: role === 'student' ? 'SUBJ_synthetic' : null,
    displayName: 'Synthetic User', initials: 'S',
    activeContext: { role, schoolRef: 'SCHOOL_synthetic' },
  })
  return { pinia, session }
}

describe('research feedback views', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    service.listTasks.mockResolvedValue([task])
    service.listEligibleSessions.mockResolvedValue({ items: [completedSession], total: 1 })
    service.listCases.mockResolvedValue({ items: [reviewCase], total: 1 })
    service.getCase.mockResolvedValue(reviewCase)
    service.listFeedback.mockResolvedValue({ items: [], total: 0 })
    service.listStudent.mockResolvedValue({ items: [studentFeedback], total: 1 })
  })

  it('keeps the specialist flow task-scoped and gates student publication behind separate review', async () => {
    const { pinia } = signIn('psychological_specialist')
    const wrapper = mount(SpecialistResearchFeedback, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('合成班级'))!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('复核 1'))!.trigger('click')
    await flushPromises()

    expect(service.listEligibleSessions).toHaveBeenCalledWith(task.task_ref, 0, 20)
    expect(service.listCases).toHaveBeenCalledWith(task.task_ref, 0, 20)
    expect(wrapper.text()).toContain('待开始')
    expect(wrapper.text()).not.toContain(completedSession.session_ref)
    expect(wrapper.text()).not.toContain(completedSession.case_ref)
    expect(wrapper.find('form.research-feedback__draft').exists()).toBe(false)

    await wrapper.get('textarea').setValue('合成流程备注')
    service.transitionCase.mockResolvedValue({ ...reviewCase, status: 'IN_REVIEW', version: 2, review_note: '合成流程备注' })
    await wrapper.findAll('button').find((button) => button.text().includes('开始处理'))!.trigger('click')
    await flushPromises()
    expect(service.transitionCase).toHaveBeenCalledWith(
      task.task_ref, reviewCase.case_ref, 1, 'IN_REVIEW', '合成流程备注', 'research-feedback-synthetic-key',
    )
    expect(wrapper.text()).toContain('研究模拟 · 教育支持工作流')
    wrapper.unmount()
  })

  it('renders only the server-projected published student content and clears it on role change', async () => {
    const { pinia, session } = signIn('student')
    const wrapper = mount(StudentResearchFeedback, { global: { plugins: [pinia] } })
    await flushPromises()

    expect(service.listStudent).toHaveBeenCalledWith(0, 20)
    expect(wrapper.text()).toContain('合成教育反馈标题')
    expect(wrapper.text()).toContain('仅用于当前合成演示账户的教育支持内容。')
    expect(wrapper.text()).toContain('未获准用于正式发布或运营')
    expect(wrapper.text()).not.toContain(studentFeedback.session_ref)
    expect(wrapper.text()).not.toContain(studentFeedback.feedback_ref)

    session.signIn({
      userId: 'USER_synthetic_teacher', role: 'teacher', subjectId: null,
      displayName: 'Synthetic Teacher', initials: 'T',
      activeContext: { role: 'teacher', schoolRef: 'SCHOOL_synthetic' },
    })
    await flushPromises()
    expect(wrapper.text()).not.toContain('合成教育反馈标题')
    expect(service.listStudent).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('shows backend errors without fabricating a feedback result', async () => {
    const { pinia } = signIn('student')
    service.listStudent.mockRejectedValue(new RealApiError('FORBIDDEN', '当前账号无权查看。'))
    const wrapper = mount(StudentResearchFeedback, { global: { plugins: [pinia] } })
    await flushPromises()
    expect(wrapper.text()).toContain('研究演示反馈暂不可用')
    expect(wrapper.text()).not.toContain('合成教育反馈标题')
    wrapper.unmount()
  })
})
