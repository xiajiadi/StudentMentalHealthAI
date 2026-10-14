import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const service = vi.hoisted(() => ({
  listTasks: vi.fn(),
  list: vi.fn(),
  get: vi.fn(),
  transition: vi.fn(),
  queueGeneration: vi.fn(),
}))
const keyFactory = vi.hoisted(() => vi.fn(() => 'programme-candidate-synthetic-key'))

vi.mock('@/services/school-research-programme-candidates', () => ({
  schoolResearchProgrammeCandidates: service,
  newProgrammeCandidateIdempotencyKey: keyFactory,
}))

import SpecialistResearchProgrammeCandidates from '@/components/school/SpecialistResearchProgrammeCandidates.vue'
import { useSessionStore } from '@/stores/session'

const task = {
  task_ref: 'TASK_reference_1', class_ref: 'CLASS_reference_1',
  class_display_name: '合成教职工事项', published_at: '2026-10-14T08:00:00Z',
}
const candidate = {
  candidate_ref: 'PRGC_synthetic_1', programme_ref: 'PROGRAMME_REFERENCE_V1', status: 'HELD' as const,
  state_version: 1, student_feedback_eligible: false as const, output_boundary: 'STAFF_REFERENCE_ONLY' as const,
  created_at: '2026-10-14T08:15:00Z',
}
const detail = {
  ...candidate, purpose: 'RESEARCH_SIMULATION' as const, research_only: true as const,
  psychological_interpretation_allowed: false as const,
  publication_status: 'not_approved_for_publication_or_operational_use' as const,
  content: {
    programme_ref: candidate.programme_ref, title: '合成校园联结参考框架',
    body: '仅用于教职工研究模拟参考；资料未构成个体化建议或经验证的效果结论。',
    citations: [{ citation_id: 'S1', source_title: '公开来源标题', source_organization: '公开机构', source_url: 'https://example.org/source', source_locator: '第 2 节' }],
  },
}

function specialistSession() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const session = useSessionStore()
  session.signIn({
    userId: 'USER_synthetic_specialist', role: 'psychological_specialist', subjectId: null,
    displayName: 'Synthetic Specialist', initials: 'S',
    activeContext: { role: 'psychological_specialist', schoolRef: 'SCHOOL_synthetic' },
  })
  return { pinia, session }
}

describe('specialist research programme candidates', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    service.listTasks.mockResolvedValue([task])
    service.list.mockResolvedValue([candidate])
    service.get.mockResolvedValue(detail)
    service.transition.mockResolvedValue({ ...candidate, status: 'ADOPTED', state_version: 2 })
    service.queueGeneration.mockResolvedValue({
      job_ref: 'REJOB_private_synthetic', status: 'QUEUED', policy_version: 'RESEARCH_STAFF_PROGRAMME_POLICY_V1',
      purpose: 'RESEARCH_SIMULATION', research_only: true,
      publication_status: 'not_approved_for_publication_or_operational_use', student_feedback_eligible: false,
    })
  })

  it('loads only authorized task candidates and requires explicit confirmation before adopting', async () => {
    const { pinia } = specialistSession()
    const wrapper = mount(SpecialistResearchProgrammeCandidates, { global: { plugins: [pinia] } })
    await flushPromises()
    expect(service.listTasks).toHaveBeenCalledOnce()
    await wrapper.find('button.programme-candidates__task').trigger('click')
    await flushPromises()
    expect(service.list).toHaveBeenCalledWith(task.task_ref, 0, 20)
    expect(wrapper.text()).toContain('教职工参考资料')
    expect(wrapper.text()).toContain('待教职工查看')
    expect(wrapper.text()).not.toContain('发布给学生')

    await wrapper.find('button.programme-candidates__row').trigger('click')
    await flushPromises()
    expect(service.get).toHaveBeenCalledWith(task.task_ref, candidate.candidate_ref)
    expect(wrapper.text()).toContain(detail.content.title)
    expect(wrapper.text()).toContain('公开来源标题')

    const adopt = wrapper.findAll('button').find((button) => button.text().includes('采纳为参考'))!
    expect(adopt.attributes('disabled')).toBeDefined()
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await adopt.trigger('click')
    await flushPromises()
    expect(service.transition).toHaveBeenCalledWith(
      task.task_ref,
      { ...candidate, state_version: detail.state_version },
      'adopt',
      'programme-candidate-synthetic-key',
    )
    expect(service.list).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('clears candidate content when specialist school context changes', async () => {
    const { pinia, session } = specialistSession()
    const wrapper = mount(SpecialistResearchProgrammeCandidates, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.find('button.programme-candidates__task').trigger('click')
    await flushPromises()
    await wrapper.find('button.programme-candidates__row').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain(detail.content.title)

    session.signIn({
      userId: 'USER_synthetic_specialist', role: 'psychological_specialist', subjectId: null,
      displayName: 'Synthetic Specialist', initials: 'S',
      activeContext: { role: 'psychological_specialist', schoolRef: 'SCHOOL_other_synthetic' },
    })
    await flushPromises()
    expect(wrapper.text()).not.toContain(detail.content.title)
    expect(wrapper.text()).toContain('当前身份或学校范围已变化')
    wrapper.unmount()
  })

  it('does not fabricate candidate content when the API is unavailable', async () => {
    const { pinia } = specialistSession()
    service.list.mockRejectedValue(new Error('unavailable'))
    const wrapper = mount(SpecialistResearchProgrammeCandidates, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.find('button.programme-candidates__task').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('候选列表暂不可用')
    expect(wrapper.text()).not.toContain(detail.content.title)
    wrapper.unmount()
  })

  it('shows a local unavailable state when the candidate service returns dependency-unavailable', async () => {
    const { pinia } = specialistSession()
    service.list.mockRejectedValue({ code: 'DEPENDENCY_UNAVAILABLE' })
    const wrapper = mount(SpecialistResearchProgrammeCandidates, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.find('button.programme-candidates__task').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('参考候选功能当前未启用或暂不可用')
    expect(wrapper.text()).not.toContain(detail.content.title)
    wrapper.unmount()
  })

  it('queues generation only after task-scoped confirmation and shows the server receipt status', async () => {
    const { pinia } = specialistSession()
    const wrapper = mount(SpecialistResearchProgrammeCandidates, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.find('button.programme-candidates__task').trigger('click')
    await flushPromises()

    const queue = wrapper.findAll('button').find((button) => button.text().includes('请求生成参考候选'))!
    expect(queue.attributes('disabled')).toBeDefined()
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await queue.trigger('click')
    await flushPromises()

    expect(service.queueGeneration).toHaveBeenCalledWith(task.task_ref, 'programme-candidate-synthetic-key')
    expect(wrapper.text()).toContain('已排队')
    expect(wrapper.text()).toContain('未获准用于学生发布或正式运营')
    expect(wrapper.text()).not.toContain('REJOB_private_synthetic')
    expect(service.list).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('clears old task state when identity changes during an in-flight queue request', async () => {
    const { pinia, session } = specialistSession()
    let finishQueue: ((value: unknown) => void) | undefined
    service.queueGeneration.mockImplementation(() => new Promise((resolve) => { finishQueue = resolve }))
    const wrapper = mount(SpecialistResearchProgrammeCandidates, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.find('button.programme-candidates__task').trigger('click')
    await flushPromises()
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await wrapper.findAll('button').find((button) => button.text().includes('请求生成参考候选'))!.trigger('click')
    await flushPromises()

    expect(wrapper.findAll('button').find((button) => button.text().includes('刷新授权'))!.attributes('disabled')).toBeDefined()
    session.signIn({
      userId: 'USER_synthetic_teacher', role: 'teacher', subjectId: null,
      displayName: 'Synthetic Teacher', initials: 'T',
      activeContext: { role: 'teacher', schoolRef: 'SCHOOL_other_synthetic' },
    })
    await flushPromises()
    finishQueue?.({
      job_ref: 'REJOB_private_synthetic', status: 'QUEUED', policy_version: 'RESEARCH_STAFF_PROGRAMME_POLICY_V1',
      purpose: 'RESEARCH_SIMULATION', research_only: true,
      publication_status: 'not_approved_for_publication_or_operational_use', student_feedback_eligible: false,
    })
    await flushPromises()

    expect(wrapper.text()).not.toContain('请求生成参考候选')
    expect(wrapper.text()).not.toContain('已排队')
    expect(wrapper.text()).not.toContain('合成教职工事项')
    wrapper.unmount()
  })

  it('clears the selected task and candidate data when queueing is forbidden', async () => {
    const { pinia } = specialistSession()
    service.queueGeneration.mockRejectedValue({ code: 'FORBIDDEN' })
    const wrapper = mount(SpecialistResearchProgrammeCandidates, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.find('button.programme-candidates__task').trigger('click')
    await flushPromises()
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await wrapper.findAll('button').find((button) => button.text().includes('请求生成参考候选'))!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('当前任务授权已变化')
    expect(wrapper.text()).not.toContain('请求生成参考候选')
    expect(wrapper.text()).not.toContain('已排队')
    wrapper.unmount()
  })

  it('drops a same-key retry when refreshing authorization removes its task', async () => {
    const { pinia } = specialistSession()
    service.queueGeneration.mockRejectedValue({ code: 'NETWORK_UNAVAILABLE', retryable: true })
    const wrapper = mount(SpecialistResearchProgrammeCandidates, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.find('button.programme-candidates__task').trigger('click')
    await flushPromises()
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await wrapper.findAll('button').find((button) => button.text().includes('请求生成参考候选'))!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('使用相同请求重试')

    service.listTasks.mockResolvedValue([])
    await wrapper.findAll('button').find((button) => button.text().includes('刷新授权'))!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('当前任务授权已变化')
    expect(wrapper.text()).not.toContain('使用相同请求重试')
    expect(service.queueGeneration).toHaveBeenCalledOnce()
    wrapper.unmount()
  })
})
