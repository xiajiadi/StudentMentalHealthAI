import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import TeacherOverviewView from '@/views/teacher/TeacherOverviewView.vue'
import TeacherStudentsView from '@/views/teacher/TeacherStudentsView.vue'
import TeacherProgressChart from '@/components/charts/TeacherProgressChart.vue'
import router from '@/router'
import { useSessionStore } from '@/stores/session'

const api = vi.hoisted(() => ({
  getTeacherOverview: vi.fn(),
  getTeacherStudent: vi.fn(),
  listTeacherSchoolTaskProgress: vi.fn(),
}))

vi.mock('@/services/mock-api', () => ({ frontendApi: api }))

async function teacherRoute(path: string) {
  const pinia = createPinia()
  useSessionStore(pinia).signIn({
    userId: 'USER_TEACHER_TEST', role: 'teacher', subjectId: null, displayName: '合成教师', initials: '教',
    activeContext: { role: 'teacher', schoolRef: 'SCHOOL_SYNTHETIC_A' },
  })
  await router.push(path)
  return { plugins: [pinia, router], stubs: { TeacherProgressChart: true } }
}

describe('Teacher Scope A views', () => {
  beforeEach(() => {
    api.listTeacherSchoolTaskProgress.mockReset()
    window.localStorage.setItem('psynova.teacher.preview.dataMode', 'real')
  })
  afterEach(() => window.localStorage.removeItem('psynova.teacher.preview.dataMode'))

  it('shows only assigned task aggregates and never renders personal fields', async () => {
    api.listTeacherSchoolTaskProgress.mockResolvedValue({
      request_id: 'REQ_teacher', trace_id: 'TRACE_teacher', data: [{
        class_ref: 'CLASS_syn123', task_ref: 'TASK_syn456', task_status: 'PUBLISHED',
        opens_at: '2026-10-11T00:00:00Z', due_at: null,
        published_enrollment_count: 4, active_enrollment_count: 3, revoked_enrollment_count: 1,
        not_started_count: 0, created_count: 0, in_progress_count: 1, completed_count: 2,
        abandoned_count: 0, invalid_count: 0,
        subject_id: 'SUBJ_PRIVATE_TEST', assessment_id: 'ASSESS_PRIVATE_TEST',
        student_id: 'USER_PRIVATE_TEST',
      }],
    })
    const wrapper = mount(TeacherOverviewView, { global: await teacherRoute('/teacher/overview') })
    await flushPromises()

    expect(wrapper.get('[aria-label="班级测评进度数据看板"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('66.7%')
    expect(wrapper.text()).toContain('进行中')
    expect(wrapper.text()).not.toContain('ASSESS_')
    expect(wrapper.text()).not.toContain('SUBJ_')
    expect(wrapper.text()).not.toContain('USER_')
    expect(api.listTeacherSchoolTaskProgress).toHaveBeenCalledTimes(1)
    expect(api.getTeacherStudent).not.toHaveBeenCalled()
    const options = wrapper.findAllComponents(TeacherProgressChart).map((chart) => chart.props('option'))
    expect(options.length).toBeGreaterThan(0)
    expect(JSON.stringify(options)).not.toMatch(/SUBJ_PRIVATE_TEST|ASSESS_PRIVATE_TEST|USER_PRIVATE_TEST/)
    wrapper.unmount()
  })

  it('shows a denied aggregate as an error instead of an empty class result', async () => {
    api.listTeacherSchoolTaskProgress.mockRejectedValueOnce({ code: 'FORBIDDEN' })
    const wrapper = mount(TeacherOverviewView, { global: await teacherRoute('/teacher/overview') })
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('暂时无法载入工作概览')
    expect(wrapper.text()).not.toContain('暂无可展示的班级任务进度')
    expect(wrapper.text()).not.toContain('SUBJ_')
    wrapper.unmount()
  })

  it.each([
    '/teacher/students',
    '/teacher/students/SUBJ_PRIVATE_TEST',
  ])('redirects the legacy %s path to aggregate class progress without reading a student record', async (path) => {
    api.listTeacherSchoolTaskProgress.mockResolvedValue({ request_id: 'REQ_teacher', trace_id: 'TRACE_teacher', data: [] })
    const global = await teacherRoute(path)
    expect(router.currentRoute.value.path).toBe('/teacher/classes')
    const wrapper = mount(TeacherStudentsView, { global })
    await flushPromises()

    expect(wrapper.text()).toContain('授权班级任务汇总')
    expect(wrapper.text()).not.toContain('ASSESS_')
    expect(wrapper.text()).not.toContain('SUBJ_')
    expect(api.getTeacherOverview).not.toHaveBeenCalled()
    expect(api.getTeacherStudent).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
