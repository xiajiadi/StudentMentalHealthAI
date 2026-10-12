import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import TeacherOverviewView from '@/views/teacher/TeacherOverviewView.vue'
import TeacherStudentsView from '@/views/teacher/TeacherStudentsView.vue'
import TeacherStudentDetailView from '@/views/teacher/TeacherStudentDetailView.vue'

const api = vi.hoisted(() => ({
  getTeacherOverview: vi.fn(),
  getTeacherStudent: vi.fn(),
  listTeacherSchoolTaskProgress: vi.fn(),
}))

vi.mock('@/services/mock-api', () => ({ frontendApi: api }))

describe('Teacher Scope A views', () => {
  it('shows only assigned task aggregates and never renders personal fields', async () => {
    api.listTeacherSchoolTaskProgress.mockResolvedValue({
      request_id: 'REQ_teacher', trace_id: 'TRACE_teacher', data: [{
        class_ref: 'CLASS_syn123', task_ref: 'TASK_syn456', task_status: 'PUBLISHED',
        opens_at: '2026-10-11T00:00:00Z', due_at: null,
        published_enrollment_count: 4, active_enrollment_count: 3, revoked_enrollment_count: 1,
        not_started_count: 1, created_count: 0, in_progress_count: 1, completed_count: 2,
        abandoned_count: 0, invalid_count: 0,
      }],
    })
    const wrapper = mount(TeacherOverviewView)
    await flushPromises()

    expect(wrapper.text()).toContain('班级任务进度')
    expect(wrapper.text()).toContain('任务 syn456')
    expect(wrapper.text()).toContain('进行中')
    expect(wrapper.text()).not.toContain('ASSESS_')
    expect(wrapper.text()).not.toContain('SUBJ_')
    expect(wrapper.text()).not.toContain('USER_')
    expect(api.listTeacherSchoolTaskProgress).toHaveBeenCalledTimes(1)
    expect(api.getTeacherStudent).not.toHaveBeenCalled()
  })

  it('shows a denied aggregate as an error instead of an empty class result', async () => {
    api.listTeacherSchoolTaskProgress.mockRejectedValueOnce({ code: 'forbidden' })
    const wrapper = mount(TeacherOverviewView)
    await flushPromises()

    expect(wrapper.text()).toContain('当前账号暂时无法查看这些任务')
    expect(wrapper.text()).not.toContain('当前没有分配给你的班级任务')
    expect(wrapper.text()).not.toContain('SUBJ_')
  })

  it.each([
    ['task progress list', TeacherStudentsView],
    ['individual detail route', TeacherStudentDetailView],
  ])('does not disclose individual assessment history on the %s page', (_name, view) => {
    const wrapper = mount(view)

    expect(wrapper.text()).toContain('任务级')
    expect(wrapper.text()).not.toContain('ASSESS_')
    expect(wrapper.text()).not.toContain('SUBJ_')
    expect(api.getTeacherOverview).not.toHaveBeenCalled()
    expect(api.getTeacherStudent).not.toHaveBeenCalled()
  })
})
