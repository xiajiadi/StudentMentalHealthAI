import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AdminSchoolOperations from '@/components/school/AdminSchoolOperations.vue'
import StudentAssignedTasks from '@/components/school/StudentAssignedTasks.vue'
import TeacherOverviewView from '@/views/teacher/TeacherOverviewView.vue'

const api = vi.hoisted(() => ({
  listSchoolClasses: vi.fn(),
  listSchoolMembers: vi.fn(),
  createSchoolClass: vi.fn(),
  assignSchoolStudent: vi.fn(),
  assignSchoolTeacher: vi.fn(),
  listSchoolTasks: vi.fn(),
  publishSchoolTask: vi.fn(),
  listStudentSchoolTasks: vi.fn(),
  listStudentSchoolTaskHistory: vi.fn(),
  startStudentSchoolTask: vi.fn(),
  listTeacherSchoolTaskProgress: vi.fn(),
  listSchoolTaskEnrollments: vi.fn(),
  revokeSchoolTaskEnrollment: vi.fn(),
}))

vi.mock('@/services/mock-api', () => ({ frontendApi: api }))

const envelope = <T,>(data: T) => ({ request_id: 'REQ_school_ui', trace_id: 'TRACE_school_ui', data })
const task = {
  task_ref: 'TASK_synthetic_123456',
  class_ref: 'CLASS_synthetic_123456',
  status: 'PUBLISHED',
  opens_at: '2026-10-11T00:00:00Z',
  due_at: null,
  assessment_id: null,
  assessment_status: null,
}
const teacherTask = {
  class_ref: task.class_ref,
  task_ref: task.task_ref,
  task_status: 'PUBLISHED',
  opens_at: task.opens_at,
  due_at: null,
  published_enrollment_count: 3,
  active_enrollment_count: 2,
  revoked_enrollment_count: 1,
  not_started_count: 1,
  created_count: 0,
  in_progress_count: 1,
  completed_count: 1,
  abandoned_count: 0,
  invalid_count: 0,
}

const makeStudentRouter = async () => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/student/assessments', component: { template: '<main>assessments</main>' } },
      { path: '/student/assessment/:id', component: { template: '<main>assessment</main>' } },
      { path: '/student/assessment/:id/result', component: { template: '<main>result</main>' } },
    ],
  })
  await router.push('/student/assessments')
  await router.isReady()
  return router
}

beforeEach(() => {
  api.listSchoolClasses.mockResolvedValue(envelope([{ class_ref: task.class_ref, status: 'ACTIVE', active_student_count: 1, active_teacher_count: 1 }]))
  api.listSchoolMembers.mockImplementation(async (role: string) => envelope([
    { user_id: role === 'student' ? 'USER_student' : 'USER_teacher', role, subject_id: role === 'student' ? 'SUBJ_student' : null },
  ]))
  api.createSchoolClass.mockResolvedValue(envelope({ class_ref: 'CLASS_new', status: 'ACTIVE' }))
  api.assignSchoolStudent.mockResolvedValue(envelope({}))
  api.assignSchoolTeacher.mockResolvedValue(envelope({}))
  api.listSchoolTasks.mockResolvedValue(envelope([{
    task_ref: task.task_ref, class_ref: task.class_ref, status: 'PUBLISHED', opens_at: task.opens_at,
    due_at: null, published_at: task.opens_at, published_enrollment_count: 2,
    active_enrollment_count: 2, revoked_enrollment_count: 0,
    instrument_id: 'INSTRUMENT_SYNTHETIC', instrument_version: 'v1',
  }]))
  api.publishSchoolTask.mockResolvedValue(envelope({}))
  api.listSchoolTaskEnrollments.mockResolvedValue(envelope([{ enrollment_ref: 'ENROLL_123456', status: 'ACTIVE' }]))
  api.revokeSchoolTaskEnrollment.mockResolvedValue(envelope({ enrollment_ref: 'ENROLL_123456', status: 'REVOKED' }))
  api.listStudentSchoolTasks.mockResolvedValue(envelope([task]))
  api.listStudentSchoolTaskHistory.mockResolvedValue(envelope([]))
  api.listTeacherSchoolTaskProgress.mockResolvedValue(envelope([teacherTask]))
  api.startStudentSchoolTask.mockResolvedValue(envelope({
    task_ref: task.task_ref, assessment_id: 'ASSESS_synthetic_1', subject_id: 'SUBJ_synthetic_1',
    status: 'in_progress', selected_item_id: null, current_item: null,
    answered_count: 0, administered_count: 0, can_complete: false, max_items: 8,
  }))
})

afterEach(() => { vi.clearAllMocks(); vi.unstubAllGlobals() })

describe('学校测评任务页面', () => {
  it('管理端能读取组织信息并完成班级人员分配与任务报名撤销', async () => {
    vi.stubGlobal('crypto', { randomUUID: () => 'synthetic-uuid-1234' })
    api.createSchoolClass.mockImplementation(async (classRef: string) => {
      api.listSchoolClasses.mockResolvedValueOnce(envelope([
        { class_ref: task.class_ref, status: 'ACTIVE', active_student_count: 1, active_teacher_count: 1 },
        { class_ref: classRef, status: 'ACTIVE', active_student_count: 0, active_teacher_count: 0 },
      ]))
      return envelope({ class_ref: classRef, status: 'ACTIVE' })
    })
    const wrapper = mount(AdminSchoolOperations)
    await flushPromises()

    expect(wrapper.text()).toContain('班级 123456')
    await wrapper.get('.school-create-class').trigger('click')
    await flushPromises()
    expect(api.createSchoolClass).toHaveBeenCalledWith('CLASS_syntheticuuid1234')
    await wrapper.get('#school-student-select').setValue('USER_student')
    await wrapper.get('#school-student-select + button').trigger('click')
    await flushPromises()
    expect(api.assignSchoolStudent).toHaveBeenCalledWith('CLASS_syntheticuuid1234', 'USER_student')
    expect(api.assignSchoolStudent.mock.contexts[0]).toBe(api)

    await wrapper.get('.school-task-list .app-button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('报名 123456')
    await wrapper.get('.school-task__enrollment .app-button').trigger('click')
    await flushPromises()
    expect(api.revokeSchoolTaskEnrollment).toHaveBeenCalledWith(task.task_ref, 'ENROLL_123456')
    expect(wrapper.text()).toContain('该报名已撤销')
  })

  it('管理端权限被拒绝时明确显示错误，不显示空班级或成功状态', async () => {
    api.listSchoolClasses.mockRejectedValueOnce({ code: 'forbidden' })
    const wrapper = mount(AdminSchoolOperations)
    await flushPromises()

    expect(wrapper.text()).toContain('当前账号暂时没有此项操作权限')
    expect(wrapper.text()).not.toContain('当前没有可用班级')
    expect(wrapper.text()).not.toContain('已创建')
  })

  it('学生任务列表失败时保留错误状态，不伪装成没有任务', async () => {
    api.listStudentSchoolTasks.mockRejectedValueOnce({ code: 'NETWORK_UNAVAILABLE' })
    const wrapper = mount(StudentAssignedTasks)
    await flushPromises()

    expect(wrapper.text()).toContain('暂时无法读取分配给你的任务')
    expect(wrapper.text()).not.toContain('当前没有分配给你的任务')
  })

  it('学生历史空列表和拒绝访问分别显示对应状态', async () => {
    api.listStudentSchoolTaskHistory.mockResolvedValueOnce(envelope([]))
    const emptyWrapper = mount(StudentAssignedTasks)
    await flushPromises()
    expect(emptyWrapper.find('.task-history').text()).toContain('当前没有任务历史')
    emptyWrapper.unmount()

    api.listStudentSchoolTaskHistory.mockRejectedValueOnce({ code: 'forbidden' })
    const deniedWrapper = mount(StudentAssignedTasks)
    await flushPromises()
    expect(deniedWrapper.find('.task-history').text()).toContain('当前账号暂时无法查看任务历史')
    expect(deniedWrapper.find('.task-history').text()).not.toContain('当前没有任务历史')
    deniedWrapper.unmount()
  })

  it('学生历史仅显示生命周期元数据，不提供测评或报告链接', async () => {
    api.listStudentSchoolTaskHistory.mockResolvedValueOnce(envelope([{
      task_ref: 'TASK_synthetic_987654', class_ref: 'CLASS_synthetic_123456',
      task_status: 'EXPIRED', enrollment_status: 'REVOKED', assessment_status: 'completed',
      started_at: '2026-10-01T09:00:00Z', completed_at: '2026-10-01T09:12:00Z',
    }]))
    const wrapper = mount(StudentAssignedTasks)
    await flushPromises()
    const history = wrapper.find('.task-history')
    expect(history.text()).toContain('任务 987654')
    expect(history.text()).toContain('报名已撤销')
    expect(history.text()).toContain('开始于')
    expect(history.text()).toContain('完成于')
    expect(history.findAll('a')).toHaveLength(0)
    expect(history.findAll('button')).toHaveLength(1) // 刷新历史
    expect(history.text()).not.toMatch(/测评结果|查看报告|分数|得分/)
    wrapper.unmount()
  })

  it('学生双击任务只发送一次启动请求并进入既有测评路由', async () => {
    const router = await makeStudentRouter()
    let completeStart: ((value: ReturnType<typeof envelope>) => void) | undefined
    api.startStudentSchoolTask.mockReturnValueOnce(new Promise((resolve) => {
      completeStart = resolve as (value: ReturnType<typeof envelope>) => void
    }))
    const wrapper = mount(StudentAssignedTasks, { global: { plugins: [router] } })
    await flushPromises()

    const startButton = wrapper.get('.assigned-task .app-button')
    await startButton.trigger('click')
    await startButton.trigger('click')
    expect(api.startStudentSchoolTask).toHaveBeenCalledTimes(1)
    completeStart?.(envelope({
      task_ref: task.task_ref, assessment_id: 'ASSESS_synthetic_1', subject_id: 'SUBJ_synthetic_1',
      status: 'in_progress', selected_item_id: null, current_item: null,
      answered_count: 0, administered_count: 0, can_complete: false, max_items: 8,
    }))
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe('/student/assessment/ASSESS_synthetic_1')
    wrapper.unmount()
  })

  it('教师只看到任务级汇总，DOM不含个体标识字段', async () => {
    const wrapper = mount(TeacherOverviewView)
    await flushPromises()

    expect(wrapper.text()).toContain('已分配任务')
    expect(wrapper.text()).toContain('已撤销')
    expect(wrapper.text()).toContain('1')
    expect(wrapper.text()).not.toContain('SUBJ_')
    expect(wrapper.text()).not.toContain('ASSESS_')
    expect(wrapper.text()).not.toContain('USER_')
  })
})
