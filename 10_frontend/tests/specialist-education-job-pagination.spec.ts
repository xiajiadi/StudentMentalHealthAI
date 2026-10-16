import { beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const service = vi.hoisted(() => ({ list: vi.fn(), listJobs: vi.fn() }))
vi.mock('@/services/school-research-education-candidates', () => ({ schoolResearchEducationCandidates: service }))
import Candidates from '@/components/school/SpecialistResearchEducationCandidates.vue'
import { useSessionStore } from '@/stores/session'

beforeEach(() => {
  vi.clearAllMocks()
  service.list.mockResolvedValue({ items: [], offset: 0, has_more: false })
  service.listJobs.mockImplementation(async (_task, offset) => ({
    items: [{ job_ref: `REJ_synthetic_${offset}`, generation_round: 0, status: 'FAILED', attempt_count: 1, last_error_code: 'GENERATION_FAILED' }],
    offset, total: 21, has_more: offset === 0, status_counts: { FAILED: 21 },
  }))
})

it('loads later job pages without enqueueing and clears paging when the task changes', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  useSessionStore().signIn({ userId: 'USER_synthetic', role: 'psychological_specialist', subjectId: null, displayName: 'Synthetic', initials: 'S', activeContext: { role: 'psychological_specialist', schoolRef: 'SCHOOL_synthetic' } })
  const wrapper = mount(Candidates, {
    props: { taskRef: 'TASK_synthetic_1', canUseSource: false },
    global: { plugins: [pinia], stubs: { SpecialistResearchEducationInputReviews: true, SpecialistResearchEducationOutputReviews: true } },
  })
  await flushPromises()
  const next = wrapper.findAll('button').find((button) => button.text() === '下一页任务')!
  await next.trigger('click')
  await flushPromises()
  expect(service.listJobs).toHaveBeenLastCalledWith('TASK_synthetic_1', 20, 20)
  expect(wrapper.text()).toContain('任务 21：')
  expect(wrapper.text()).toContain('刷新页面不会自动重新生成')
  expect(wrapper.findAll('button').find((button) => button.text() === '下一页任务')!.attributes('disabled')).toBeDefined()
  await wrapper.setProps({ taskRef: 'TASK_synthetic_2' })
  await flushPromises()
  expect(service.listJobs).toHaveBeenLastCalledWith('TASK_synthetic_2', 0, 20)
  wrapper.unmount()
})
