import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const service = vi.hoisted(() => ({
  listTasks: vi.fn(),
  list: vi.fn(),
  get: vi.fn(),
  transition: vi.fn(),
  queueGeneration: vi.fn(),
  queueGenerationBatch: vi.fn(),
  listGenerationJobs: vi.fn(),
}))
const keyFactory = vi.hoisted(() => vi.fn(() => 'programme-candidate-synthetic-key'))
const batchKeyFactory = vi.hoisted(() => vi.fn(() => 'programme-batch-synthetic-key'))

vi.mock('@/services/school-research-programme-candidates', () => ({
  schoolResearchProgrammeCandidates: service,
  newProgrammeCandidateIdempotencyKey: keyFactory,
  newProgrammeGenerationBatchIdempotencyKey: batchKeyFactory,
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
    programme_ref: candidate.programme_ref, content_origin: 'VERIFIED_SOURCE_METADATA',
    generation_mode: 'MODEL_SOURCE_SELECTION', title: '合成校园联结参考框架',
    body: '仅用于教职工研究模拟参考；资料未构成个体化建议或经验证的效果结论。',
    citations: [{ citation_id: 'S1', source_title: '公开来源标题', source_organization: '公开机构', source_url: 'https://example.org/source', source_locator: '第 2 节' }],
  },
}
const emptyStatusCounts = {
  QUEUED: 0, LEASED: 0, RETRY: 0, HELD: 0, ABSTAINED: 0,
  REVIEW_REQUIRED: 0, CRISIS_ROUTED: 0, FAILED: 0, CANCELLED: 0,
}
const emptyGenerationJobPage = {
  items: [], offset: 0, limit: 25, total: 0, has_more: false,
  status_counts: emptyStatusCounts,
  policy_version: 'RESEARCH_STAFF_PROGRAMME_POLICY_V1' as const,
  purpose: 'RESEARCH_SIMULATION' as const,
  research_only: true as const,
  publication_status: 'not_approved_for_publication_or_operational_use' as const,
  student_feedback_eligible: false as const,
}
const batchReceipt = {
  batch_ref: `REJBATCH_${'b'.repeat(64)}`,
  job_refs: [`REJ_${'a'.repeat(64)}`, `REJ_${'c'.repeat(64)}`],
  job_count: 2,
  next_cursor: null,
  policy_version: 'RESEARCH_STAFF_PROGRAMME_POLICY_V1' as const,
  purpose: 'RESEARCH_SIMULATION' as const,
  research_only: true as const,
  publication_status: 'not_approved_for_publication_or_operational_use' as const,
  student_feedback_eligible: false as const,
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
    service.queueGenerationBatch.mockResolvedValue(batchReceipt)
    service.listGenerationJobs.mockResolvedValue(emptyGenerationJobPage)
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
    expect(wrapper.text()).toContain('来源索引，模型仅选择来源')
    expect(wrapper.text()).not.toContain('旧版模型撰写文本')
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

  it('labels legacy candidates as model-authored text instead of the source-index mode', async () => {
    const { pinia } = specialistSession()
    service.get.mockResolvedValue({
      ...detail,
      content: {
        ...detail.content,
        content_origin: 'LEGACY_MODEL_TEXT',
        generation_mode: 'LEGACY_MODEL_AUTHORED_PASSAGES',
      },
    })
    const wrapper = mount(SpecialistResearchProgrammeCandidates, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.find('button.programme-candidates__task').trigger('click')
    await flushPromises()
    await wrapper.find('button.programme-candidates__row').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('旧版模型撰写文本')
    expect(wrapper.text()).not.toContain('来源索引，模型仅选择来源')
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

  it('queues one bounded batch after separate confirmation and renders service status counts', async () => {
    const { pinia } = specialistSession()
    batchKeyFactory.mockReturnValueOnce('programme-batch-page-1')
    service.listGenerationJobs
      .mockResolvedValueOnce(emptyGenerationJobPage)
      .mockResolvedValueOnce({
        ...emptyGenerationJobPage,
        items: [
          {
            job_ref: `REJ_${'d'.repeat(64)}`, status: 'QUEUED', attempt_count: 0,
            updated_at: '2026-10-15T08:00:00Z', last_error_code: null,
          },
          {
            job_ref: `REJ_${'e'.repeat(64)}`, status: 'RETRY', attempt_count: 1,
            updated_at: '2026-10-15T08:01:00Z', last_error_code: 'DEPENDENCY_UNAVAILABLE',
          },
        ],
        total: 2,
        status_counts: { ...emptyStatusCounts, QUEUED: 1, RETRY: 1 },
      })
    const wrapper = mount(SpecialistResearchProgrammeCandidates, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.find('button.programme-candidates__task').trigger('click')
    await flushPromises()

    const batchButton = wrapper.findAll('button').find((button) => button.text().includes('请求首批'))!
    expect(batchButton.attributes('disabled')).toBeDefined()
    const batchConsent = wrapper.findAll('input[type="checkbox"]').find((input) =>
      input.element.parentElement?.textContent?.includes('不发布学生反馈'))!
    await batchConsent.setValue(true)
    await batchButton.trigger('click')
    await flushPromises()

    expect(service.queueGenerationBatch).toHaveBeenCalledWith(task.task_ref, 'programme-batch-page-1', 25, null)
    expect(service.listGenerationJobs).toHaveBeenLastCalledWith(task.task_ref, 0, 25)
    expect(wrapper.text()).toContain('回执包含 2 项任务记录（可能包含已有任务）')
    expect(wrapper.text()).toContain('已排队，1')
    expect(wrapper.text()).toContain('待重试，1')
    expect(wrapper.text()).toContain('共 2 项任务')
    expect(wrapper.text()).not.toContain(batchReceipt.batch_ref)
    wrapper.unmount()
  })

  it('retries the same batch page with the same idempotency key', async () => {
    const { pinia } = specialistSession()
    batchKeyFactory.mockReturnValueOnce('programme-batch-retry-key')
    service.queueGenerationBatch
      .mockRejectedValueOnce({ code: 'NETWORK_UNAVAILABLE', retryable: true })
      .mockResolvedValueOnce(batchReceipt)
    const wrapper = mount(SpecialistResearchProgrammeCandidates, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.find('button.programme-candidates__task').trigger('click')
    await flushPromises()
    const batchConsent = wrapper.findAll('input[type="checkbox"]').find((input) =>
      input.element.parentElement?.textContent?.includes('不发布学生反馈'))!
    await batchConsent.setValue(true)
    await wrapper.findAll('button').find((button) => button.text().includes('请求首批'))!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('使用相同请求重试')
    expect(service.queueGenerationBatch).toHaveBeenCalledTimes(1)

    await wrapper.findAll('button').find((button) => button.text().includes('使用相同请求重试'))!.trigger('click')
    await flushPromises()
    expect(service.queueGenerationBatch).toHaveBeenNthCalledWith(2, task.task_ref, 'programme-batch-retry-key', 25, null)
    expect(wrapper.text()).toContain('回执包含 2 项任务记录')
    wrapper.unmount()
  })

  it('uses a new idempotency key for the next cursor page', async () => {
    const { pinia } = specialistSession()
    const firstPage = { ...batchReceipt, next_cursor: batchReceipt.job_refs[1] }
    const lastPage = { ...batchReceipt, batch_ref: `REJBATCH_${'f'.repeat(64)}`, next_cursor: null }
    batchKeyFactory.mockReturnValueOnce('programme-batch-page-one').mockReturnValueOnce('programme-batch-page-two')
    service.queueGenerationBatch.mockResolvedValueOnce(firstPage).mockResolvedValueOnce(lastPage)
    const wrapper = mount(SpecialistResearchProgrammeCandidates, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.find('button.programme-candidates__task').trigger('click')
    await flushPromises()

    const consent = () => wrapper.findAll('input[type="checkbox"]').find((input) =>
      input.element.parentElement?.textContent?.includes('不发布学生反馈'))!
    await consent().setValue(true)
    await wrapper.findAll('button').find((button) => button.text().includes('请求首批'))!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('请求下一批（最多 25 项）')
    await consent().setValue(true)
    await wrapper.findAll('button').find((button) => button.text().includes('请求下一批'))!.trigger('click')
    await flushPromises()

    expect(service.queueGenerationBatch).toHaveBeenNthCalledWith(1, task.task_ref, 'programme-batch-page-one', 25, null)
    expect(service.queueGenerationBatch).toHaveBeenNthCalledWith(2, task.task_ref, 'programme-batch-page-two', 25, batchReceipt.job_refs[1])
    expect(batchKeyFactory).toHaveBeenNthCalledWith(1, 25)
    expect(batchKeyFactory).toHaveBeenNthCalledWith(2, 25)
    expect(wrapper.text()).toContain('当前授权范围没有更多批次')
    wrapper.unmount()
  })

  it('resets the batch cursor and uses a fresh key when the batch size changes', async () => {
    const { pinia } = specialistSession()
    const firstPage = { ...batchReceipt, next_cursor: batchReceipt.job_refs[1] }
    batchKeyFactory.mockReturnValueOnce('programme-batch-size-25').mockReturnValueOnce('programme-batch-size-2')
    service.queueGenerationBatch.mockResolvedValueOnce(firstPage).mockResolvedValueOnce(batchReceipt)
    const wrapper = mount(SpecialistResearchProgrammeCandidates, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.find('button.programme-candidates__task').trigger('click')
    await flushPromises()

    const consent = () => wrapper.findAll('input[type="checkbox"]').find((input) =>
      input.element.parentElement?.textContent?.includes('不发布学生反馈'))!
    await consent().setValue(true)
    await wrapper.findAll('button').find((button) => button.text().includes('请求首批（最多 25 项）'))!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('请求下一批（最多 25 项）')

    await wrapper.find('select[aria-label="每批生成任务数量"]').setValue('2')
    await flushPromises()
    expect(wrapper.text()).not.toContain('回执包含 2 项任务记录')
    expect(wrapper.text()).toContain('请求首批（最多 2 项）')
    expect((consent().element as { checked: boolean }).checked).toBe(false)
    await consent().setValue(true)
    await wrapper.findAll('button').find((button) => button.text().includes('请求首批（最多 2 项）'))!.trigger('click')
    await flushPromises()

    expect(service.queueGenerationBatch).toHaveBeenNthCalledWith(1, task.task_ref, 'programme-batch-size-25', 25, null)
    expect(service.queueGenerationBatch).toHaveBeenNthCalledWith(2, task.task_ref, 'programme-batch-size-2', 2, null)
    expect(batchKeyFactory).toHaveBeenNthCalledWith(1, 25)
    expect(batchKeyFactory).toHaveBeenNthCalledWith(2, 2)
    wrapper.unmount()
  })

  it('clears the batch receipt and confirmation when changing authorized tasks', async () => {
    const { pinia } = specialistSession()
    const secondTask = { ...task, task_ref: 'TASK_reference_2', class_ref: 'CLASS_reference_2', class_display_name: '第二合成事项' }
    service.listTasks.mockResolvedValue([task, secondTask])
    const wrapper = mount(SpecialistResearchProgrammeCandidates, { global: { plugins: [pinia] } })
    await flushPromises()
    await wrapper.findAll('button.programme-candidates__task')[0].trigger('click')
    await flushPromises()
    const consent = () => wrapper.findAll('input[type="checkbox"]').find((input) =>
      input.element.parentElement?.textContent?.includes('不发布学生反馈'))!
    await consent().setValue(true)
    await wrapper.findAll('button').find((button) => button.text().includes('请求首批'))!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('回执包含 2 项任务记录')

    await wrapper.findAll('button.programme-candidates__task')[1].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('第二合成事项')
    expect(wrapper.text()).not.toContain('回执包含 2 项任务记录')
    expect(wrapper.text()).toContain('请求首批（最多 25 项）')
    expect((consent().element as { checked: boolean }).checked).toBe(false)
    wrapper.unmount()
  })

  it('ignores old job-status reads after the selected task changes', async () => {
    const { pinia } = specialistSession()
    const secondTask = { ...task, task_ref: 'TASK_reference_2', class_ref: 'CLASS_reference_2', class_display_name: '第二合成事项' }
    let finishFirstRead: ((value: unknown) => void) | undefined
    service.listTasks.mockResolvedValue([task, secondTask])
    service.listGenerationJobs.mockImplementation((taskRef: string) => {
      if (taskRef === task.task_ref) return new Promise((resolve) => { finishFirstRead = resolve })
      return Promise.resolve({ ...emptyGenerationJobPage, total: 2, status_counts: { ...emptyStatusCounts, FAILED: 2 } })
    })
    const wrapper = mount(SpecialistResearchProgrammeCandidates, { global: { plugins: [pinia] } })
    await flushPromises()
    const taskButtons = wrapper.findAll('button.programme-candidates__task')
    await taskButtons[0].trigger('click')
    await flushPromises()
    await wrapper.findAll('button.programme-candidates__task')[1].trigger('click')
    await flushPromises()
    finishFirstRead?.({
      ...emptyGenerationJobPage,
      total: 1,
      status_counts: { ...emptyStatusCounts, HELD: 1 },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('第二合成事项')
    expect(wrapper.text()).toContain('共 2 项任务')
    expect(wrapper.text()).toContain('处理失败，2')
    expect(wrapper.text()).not.toContain('候选已保存，1')
    wrapper.unmount()
  })

  it('ignores stale A-to-B-to-A batch completions and preserves the current busy and retry state', async () => {
    const { pinia, session } = specialistSession()
    const secondTask = { ...task, task_ref: 'TASK_reference_2', class_ref: 'CLASS_reference_2', class_display_name: '第二合成事项' }
    let settles: Array<{ resolve: (value: unknown) => void; reject: (reason?: unknown) => void }> = []
    service.queueGenerationBatch.mockImplementation(() => new Promise((resolve, reject) => {
      settles.push({ resolve, reject })
    }))
    const wrapper = mount(SpecialistResearchProgrammeCandidates, { global: { plugins: [pinia] } })
    await flushPromises()

    const batchConsent = () => wrapper.findAll('input[type="checkbox"]').find((input) =>
      input.element.parentElement?.textContent?.includes('不发布学生反馈'))!
    const startBatch = async () => {
      await batchConsent().setValue(true)
      await wrapper.findAll('button').find((button) => button.text().includes('请求首批'))!.trigger('click')
      await flushPromises()
    }
    const setIdentity = (role: 'teacher' | 'psychological_specialist', schoolRef: string) => {
      session.signIn({
        userId: role === 'teacher' ? 'USER_synthetic_teacher' : 'USER_synthetic_specialist',
        role, subjectId: null, displayName: 'Synthetic User', initials: 'S',
        activeContext: { role, schoolRef },
      })
    }

    await wrapper.find('button.programme-candidates__task').trigger('click')
    await flushPromises()
    await startBatch()
    expect(settles).toHaveLength(1)

    service.listTasks.mockResolvedValue([secondTask])
    setIdentity('teacher', 'SCHOOL_synthetic')
    await flushPromises()
    setIdentity('psychological_specialist', 'SCHOOL_B')
    await flushPromises()
    await wrapper.find('button.programme-candidates__task').trigger('click')
    await flushPromises()
    await startBatch()
    expect(settles).toHaveLength(2)

    service.listTasks.mockResolvedValue([task])
    setIdentity('teacher', 'SCHOOL_B')
    await flushPromises()
    setIdentity('psychological_specialist', 'SCHOOL_A')
    await flushPromises()
    await wrapper.find('button.programme-candidates__task').trigger('click')
    await flushPromises()
    await startBatch()
    expect(settles).toHaveLength(3)

    settles[0]?.resolve({ ...batchReceipt, job_count: 99 })
    await flushPromises()
    expect(wrapper.findAll('button').find((button) => button.text().includes('请求首批'))!.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).not.toContain('回执包含 99 项任务记录')
    expect(wrapper.text()).not.toContain('使用相同请求重试')

    settles[1]?.reject({ code: 'NETWORK_UNAVAILABLE', retryable: true })
    await flushPromises()
    expect(wrapper.findAll('button').find((button) => button.text().includes('请求首批'))!.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).not.toContain('批次请求未完成')
    expect(wrapper.text()).not.toContain('使用相同请求重试')

    settles[2]?.resolve(batchReceipt)
    await flushPromises()
    expect(wrapper.text()).toContain('回执包含 2 项任务记录')
    expect(wrapper.text()).not.toContain('回执包含 99 项任务记录')
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

  it('does not let an old single-job completion overwrite a new same-task request', async () => {
    const { pinia, session } = specialistSession()
    const resolves: Array<(value: unknown) => void> = []
    service.queueGeneration.mockImplementation(() => new Promise((resolve) => { resolves.push(resolve) }))
    const wrapper = mount(SpecialistResearchProgrammeCandidates, { global: { plugins: [pinia] } })
    await flushPromises()
    const enterTask = async () => {
      await wrapper.find('button.programme-candidates__task').trigger('click')
      await flushPromises()
    }
    const generationConsent = () => wrapper.findAll('input[type="checkbox"]').find((input) =>
      input.element.parentElement?.textContent?.includes('我确认请求仅用于此授权事项中的教职工参考资料'))!
    const startSingle = async () => {
      await generationConsent().setValue(true)
      await wrapper.findAll('button').find((button) => button.text().includes('请求生成参考候选'))!.trigger('click')
      await flushPromises()
    }
    const setIdentity = (role: 'teacher' | 'psychological_specialist') => {
      session.signIn({
        userId: role === 'teacher' ? 'USER_synthetic_teacher' : 'USER_synthetic_specialist',
        role, subjectId: null, displayName: 'Synthetic User', initials: 'S',
        activeContext: { role, schoolRef: 'SCHOOL_synthetic' },
      })
    }

    await enterTask()
    await startSingle()
    setIdentity('teacher')
    await flushPromises()
    setIdentity('psychological_specialist')
    await flushPromises()
    await enterTask()
    await startSingle()
    expect(resolves).toHaveLength(2)

    resolves[0]?.({
      job_ref: 'REJOB_stale_synthetic', status: 'FAILED', policy_version: 'RESEARCH_STAFF_PROGRAMME_POLICY_V1',
      purpose: 'RESEARCH_SIMULATION', research_only: true,
      publication_status: 'not_approved_for_publication_or_operational_use', student_feedback_eligible: false,
    })
    await flushPromises()
    expect(wrapper.findAll('button').find((button) => button.text().includes('请求生成参考候选'))!.attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('.programme-candidates__receipt').some((receipt) => receipt.text().includes('处理失败'))).toBe(false)
    expect(wrapper.text()).not.toContain('REJOB_stale_synthetic')

    resolves[1]?.({
      job_ref: 'REJOB_current_synthetic', status: 'QUEUED', policy_version: 'RESEARCH_STAFF_PROGRAMME_POLICY_V1',
      purpose: 'RESEARCH_SIMULATION', research_only: true,
      publication_status: 'not_approved_for_publication_or_operational_use', student_feedback_eligible: false,
    })
    await flushPromises()
    expect(wrapper.text()).toContain('已排队')
    expect(wrapper.text()).not.toContain('REJOB_current_synthetic')
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
