import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ requestProfessionalReview: vi.fn() }))
vi.mock('@/services/real-api', () => ({
  RealApiError: class RealApiError extends Error {
    constructor(public code: string, message: string) { super(message) }
  },
  requestProfessionalReview: transport.requestProfessionalReview,
}))

const assignmentApi = vi.hoisted(() => ({
  listSpecialists: vi.fn(), listAssignments: vi.fn(), assign: vi.fn(), revoke: vi.fn(), newKey: vi.fn(),
}))
vi.mock('@/services/professional-assignments', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    professionalAssignments: {
      listSpecialists: assignmentApi.listSpecialists,
      listAssignments: assignmentApi.listAssignments,
      assign: assignmentApi.assign,
      revoke: assignmentApi.revoke,
    },
    newProfessionalAssignmentIdempotencyKey: assignmentApi.newKey,
  }
})

import AdminProfessionalAssignments from '@/components/school/AdminProfessionalAssignments.vue'
import { ProfessionalAssignmentsService } from '@/services/professional-assignments'

const envelope = (data: unknown) => ({ request_id: 'REQ_synthetic_assignment', trace_id: 'TRACE_synthetic_assignment', data })
const specialist = { user_id: 'USER_SYNTHETIC_SPECIALIST_1', display_name: null }
const assignment = {
  assignment_ref: 'ASSIGN_SYNTHETIC_1', task_ref: 'TASK_SYNTHETIC_1', specialist_user_id: specialist.user_id,
  status: 'ACTIVE' as const, assigned_at: '2026-10-11T03:00:00Z', revoked_at: null,
}
const tasks = [
  { task_ref: 'TASK_SYNTHETIC_1', opens_at: '2026-10-10T00:00:00Z', due_at: '2026-10-20T00:00:00Z' },
  { task_ref: 'TASK_SYNTHETIC_2', opens_at: '2026-10-21T00:00:00Z', due_at: null },
] as never[]

function prepare() {
  assignmentApi.listSpecialists.mockResolvedValue([specialist])
  assignmentApi.listAssignments.mockResolvedValue([])
  assignmentApi.assign.mockResolvedValue(assignment)
  assignmentApi.revoke.mockResolvedValue({ ...assignment, status: 'REVOKED', revoked_at: '2026-10-12T03:00:00Z' })
  assignmentApi.newKey.mockReturnValue('stable-synthetic-assignment-key')
  return mount(AdminProfessionalAssignments, { props: { tasks } })
}

afterEach(() => vi.clearAllMocks())

describe('professional assignment transport', () => {
  it('uses the constrained routes, caller idempotency keys and required request bodies', async () => {
    transport.requestProfessionalReview
      .mockResolvedValueOnce(envelope([specialist]))
      .mockResolvedValueOnce(envelope([assignment]))
      .mockResolvedValueOnce(envelope(assignment))
      .mockResolvedValueOnce(envelope({ ...assignment, status: 'REVOKED', revoked_at: '2026-10-12T03:00:00Z' }))
    const service = new ProfessionalAssignmentsService()

    await service.listSpecialists()
    await service.listAssignments()
    await service.assign(assignment.task_ref, specialist.user_id, 'assign-key')
    await service.revoke(assignment.task_ref, assignment.assignment_ref, 'revoke-key')

    expect(transport.requestProfessionalReview.mock.calls.map(([request]) => request)).toEqual([
      { method: 'GET', path: '/api/v1/school/professional-reviews/specialists' },
      { method: 'GET', path: '/api/v1/school/professional-reviews/assignments' },
      { method: 'POST', path: '/api/v1/school/professional-reviews/tasks/TASK_SYNTHETIC_1/assignments', body: { specialist_user_id: specialist.user_id }, idempotencyKey: 'assign-key' },
      { method: 'POST', path: '/api/v1/school/professional-reviews/tasks/TASK_SYNTHETIC_1/assignments/ASSIGN_SYNTHETIC_1/revoke', body: {}, idempotencyKey: 'revoke-key' },
    ])
  })

  it('rejects malformed status and date metadata', async () => {
    transport.requestProfessionalReview
      .mockResolvedValueOnce(envelope([{ ...assignment, status: 'IN_REVIEW' }]))
      .mockResolvedValueOnce(envelope([{ ...assignment, assigned_at: 'unknown' }]))
    const service = new ProfessionalAssignmentsService()
    await expect(service.listAssignments()).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
    await expect(service.listAssignments()).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })
})

describe('administrator professional assignment controls', () => {
  it('uses task dates and order, neutral specialist labels, and hides technical references', async () => {
    assignmentApi.listAssignments.mockResolvedValue([assignment])
    const wrapper = prepare()
    await flushPromises()

    expect(wrapper.text()).toContain('第 1 项')
    expect(wrapper.text()).toContain('2026年10月10日')
    expect(wrapper.text()).toContain('专员 1')
    expect(wrapper.text()).not.toContain(assignment.assignment_ref)
    expect(wrapper.text()).not.toContain(assignment.task_ref)
    expect(wrapper.text()).not.toContain(specialist.user_id)
    expect(wrapper.text()).not.toContain('合成私密个案')
    wrapper.unmount()
  })

  it('retries an uncertain mutation only on explicit action with the same arguments and key', async () => {
    const wrapper = prepare()
    await flushPromises()
    await wrapper.get('#professional-assignment-specialist').setValue(specialist.user_id)
    assignmentApi.assign.mockRejectedValueOnce(Object.assign(new Error('network unavailable'), { code: 'NETWORK_UNAVAILABLE', retryable: true }))
      .mockResolvedValueOnce(assignment)
    await wrapper.findAll('button').find((button) => button.text() === '分配')!.trigger('click')
    await flushPromises()

    expect(assignmentApi.assign).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('使用相同请求重试')
    await wrapper.findAll('button').find((button) => button.text() === '使用相同请求重试')!.trigger('click')
    await flushPromises()
    expect(assignmentApi.assign).toHaveBeenCalledTimes(2)
    expect(assignmentApi.assign.mock.calls[0]).toEqual(assignmentApi.assign.mock.calls[1])
    expect(assignmentApi.listAssignments).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('prevents a second write while one is pending', async () => {
    const wrapper = prepare()
    await flushPromises()
    await wrapper.get('#professional-assignment-specialist').setValue(specialist.user_id)
    let resolveWrite!: (value: typeof assignment) => void
    assignmentApi.assign.mockReturnValueOnce(new Promise((resolve) => { resolveWrite = resolve }))
    const action = wrapper.findAll('button').find((button) => button.text() === '分配')!
    await action.trigger('click')
    await action.trigger('click')
    expect(assignmentApi.assign).toHaveBeenCalledTimes(1)
    resolveWrite(assignment)
    await flushPromises()
    wrapper.unmount()
  })

  it('shows a readable service error and ignores stale refresh responses', async () => {
    let resolveInitial!: (value: typeof assignment[]) => void
    assignmentApi.listSpecialists.mockResolvedValue([specialist])
    assignmentApi.listAssignments.mockReturnValueOnce(new Promise((resolve) => { resolveInitial = resolve }))
      .mockResolvedValueOnce([assignment])
    const wrapper = mount(AdminProfessionalAssignments, { props: { tasks } })
    await flushPromises()
    expect(wrapper.text()).toContain('正在读取分配记录')

    await wrapper.findAll('button').find((button) => button.text() === '刷新')!.trigger('click')
    await flushPromises()
    resolveInitial([])
    await flushPromises()

    expect(wrapper.text()).toContain('专员 1')
    expect(wrapper.text()).not.toContain('这个任务还没有专员分配记录')
    wrapper.unmount()

    assignmentApi.listSpecialists.mockRejectedValueOnce(new Error('service unavailable'))
    const failed = mount(AdminProfessionalAssignments, { props: { tasks } })
    await flushPromises()
    expect(failed.text()).toContain('暂时无法读取可分配的同校专员')
    failed.unmount()
  })

  it.each([
    ['FORBIDDEN', '重新登录'],
    ['RESOURCE_NOT_FOUND', '刷新分配记录'],
    ['WORKFLOW_CONFLICT', '刷新分配记录'],
  ])('does not offer idempotent retry for definite %s failures', async (code, guidance) => {
    const wrapper = prepare()
    await flushPromises()
    await wrapper.get('#professional-assignment-specialist').setValue(specialist.user_id)
    assignmentApi.assign.mockRejectedValueOnce(Object.assign(new Error('request rejected'), { code, retryable: false }))
    await wrapper.findAll('button').find((button) => button.text() === '分配')!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain(guidance)
    expect(wrapper.text()).not.toContain('使用相同请求重试')
    expect(assignmentApi.assign).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('clears prior task data and retry state when the task scope changes', async () => {
    assignmentApi.listSpecialists.mockResolvedValue([specialist])
    assignmentApi.listAssignments.mockResolvedValueOnce([assignment]).mockResolvedValue([])
    assignmentApi.assign.mockResolvedValue(assignment)
    assignmentApi.revoke.mockResolvedValue({ ...assignment, status: 'REVOKED', revoked_at: '2026-10-12T03:00:00Z' })
    assignmentApi.newKey.mockReturnValue('stable-synthetic-assignment-key')
    const wrapper = mount(AdminProfessionalAssignments, { props: { tasks } })
    await flushPromises()
    expect(wrapper.text()).toContain('当前有效')

    assignmentApi.revoke.mockRejectedValueOnce(Object.assign(new Error('network unavailable'), { code: 'NETWORK_UNAVAILABLE', retryable: true }))
    await wrapper.findAll('button').find((button) => button.text() === '撤销分配')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('使用相同请求重试')

    await wrapper.setProps({ tasks: [] })
    await flushPromises()
    expect(wrapper.text()).toContain('当前班级还没有已发布任务')
    expect(wrapper.text()).not.toContain('当前有效')
    expect(wrapper.text()).not.toContain('使用相同请求重试')

    await wrapper.setProps({ tasks: [{ ...tasks[0], task_ref: 'TASK_SYNTHETIC_NEW_SCOPE' }] as never[] })
    await flushPromises()
    expect(assignmentApi.listAssignments).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).not.toContain('当前有效')
    wrapper.unmount()
  })
})
