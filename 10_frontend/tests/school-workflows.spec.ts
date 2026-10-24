import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AdminSchoolOperations from '@/components/school/AdminSchoolOperations.vue'
import AdminSchoolDirectory from '@/components/school/AdminSchoolDirectory.vue'
import StudentAssignedTasks from '@/components/school/StudentAssignedTasks.vue'
import TeacherOverviewView from '@/views/teacher/TeacherOverviewView.vue'

const api = vi.hoisted(() => ({
  getSchoolAdminDirectory: vi.fn(),
  updateSchoolDisplayName: vi.fn(),
  updateSchoolClassDisplayName: vi.fn(),
  updateSchoolMemberDisplayName: vi.fn(),
  previewSchoolAccountImport: vi.fn(),
  importSchoolAccounts: vi.fn(),
  getSchoolAccountBatch: vi.fn(),
  listSchoolClasses: vi.fn(),
  listSchoolMembers: vi.fn(),
  createSchoolClass: vi.fn(),
  assignSchoolStudent: vi.fn(),
  assignSchoolTeacher: vi.fn(),
  listSchoolTasks: vi.fn(),
  publishSchoolTask: vi.fn(),
  listActivations: vi.fn(),
  listStudentSchoolTasks: vi.fn(),
  listStudentSchoolTaskHistory: vi.fn(),
  startStudentSchoolTask: vi.fn(),
  listTeacherSchoolTaskProgress: vi.fn(),
  listSchoolTaskEnrollments: vi.fn(),
  revokeSchoolTaskEnrollment: vi.fn(),
}))

vi.mock('@/services/mock-api', () => ({ frontendApi: api }))
vi.mock('@/components/charts/TeacherProgressChart.vue', () => ({
  default: { template: '<div aria-hidden="true" />' },
}))
vi.mock('@/services/school-cat-activations', () => ({
  schoolCatActivations: { list: api.listActivations },
}))

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
const eligibleActivation = {
  activation_ref: 'CACT_12345678-1234-1234-1234-123456789012',
  plan_version_ref: 'CPVER_12345678-1234-1234-1234-123456789012',
  bank_version_ref: 'CBVER_12345678-1234-1234-1234-123456789012',
  plan_name: '合成方案', plan_version_number: 2, bank_name: '合成题库', bank_version_number: 3,
  status: 'ACTIVE', revision: 1, created_at: '2026-10-12T00:00:00Z', revoked_at: null,
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
  api.getSchoolAdminDirectory.mockResolvedValue(envelope({
    school: { school_ref: 'SCHOOL_synthetic', display_name: '合成学校' },
    classes: [{ class_ref: task.class_ref, status: 'ACTIVE', active_student_count: 1, active_teacher_count: 1, display_name: '合成一班' }],
    members: [{ user_id: 'USER_student', display_name: '合成学生', role: 'student', account_status: 'ACTIVE', provisioning_status: 'ACTIVE' }],
  }))
  api.updateSchoolDisplayName.mockResolvedValue(envelope({}))
  api.updateSchoolClassDisplayName.mockResolvedValue(envelope({}))
  api.updateSchoolMemberDisplayName.mockResolvedValue(envelope({}))
  api.previewSchoolAccountImport.mockResolvedValue(envelope({ valid: true, row_count: 2, errors: [] }))
  api.importSchoolAccounts.mockResolvedValue(envelope({ batch_ref: 'BATCH_123456', created_count: 2, accounts: [
    { row_no: 1, user_id: 'USER_new_student', display_name: '新合成学生', role: 'student', status: 'PENDING_ACTIVATION' },
    { row_no: 2, user_id: 'USER_new_teacher', display_name: '新合成教师', role: 'teacher', status: 'PENDING_ACTIVATION' },
  ] }))
  api.getSchoolAccountBatch.mockResolvedValue(envelope({ batch_ref: 'BATCH_123456', created_count: 0, accounts: [] }))
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
  api.listActivations.mockResolvedValue({ items: [], has_more: false, engineering_only: true, psychological_interpretation_allowed: false })
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
  it('学校目录按当前同校服务端数据编辑学校、班级和人员显示名称', async () => {
    const wrapper = mount(AdminSchoolDirectory)
    await flushPromises()
    expect((wrapper.get('#school-display-name').element as { value: string }).value).toBe('合成学校')
    expect((wrapper.get(`#class-name-${task.class_ref}`).element as { value: string }).value).toBe('合成一班')
    expect((wrapper.get('#member-name-USER_student-student').element as { value: string }).value).toBe('合成学生')
    await wrapper.get('#school-display-name').setValue('更新后的合成学校')
    await wrapper.get('#school-display-name + .app-button').trigger('click')
    await flushPromises()
    expect(api.updateSchoolDisplayName).toHaveBeenCalledWith('更新后的合成学校')
    expect(api.getSchoolAdminDirectory).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('同一账号的多个角色使用不同输入ID并共享成员名称', async () => {
    api.getSchoolAdminDirectory.mockResolvedValue(envelope({
      school: { school_ref: 'SCHOOL_synthetic', display_name: '合成学校' },
      classes: [],
      members: ['student', 'teacher'].map((role) => ({
        user_id: 'USER_multi', display_name: '合成成员', role,
        account_status: 'ACTIVE', provisioning_status: null,
      })),
    }))
    const wrapper = mount(AdminSchoolDirectory)
    await flushPromises()
    await wrapper.get('#member-name-USER_multi-student').setValue('合成新名称')
    expect((wrapper.get('#member-name-USER_multi-teacher').element as { value: string }).value).toBe('合成新名称')
    expect(wrapper.findAll('[id="member-name-USER_multi-student"]')).toHaveLength(1)
    expect(wrapper.findAll('[id="member-name-USER_multi-teacher"]')).toHaveLength(1)
    wrapper.unmount()
  })

  it('CSV服务端预览后整批幂等导入，并将待首次登录账号交给一次性凭据流程', async () => {
    vi.stubGlobal('crypto', { randomUUID: () => 'import-test-uuid' })
    api.importSchoolAccounts
      .mockRejectedValueOnce(new Error('network unavailable after submit'))
      .mockResolvedValueOnce(envelope({ batch_ref: 'BATCH_123456', created_count: 2, accounts: [
        { row_no: 1, user_id: 'USER_new_student', display_name: '新合成学生', role: 'student', status: 'PENDING_ACTIVATION' },
        { row_no: 2, user_id: 'USER_new_teacher', display_name: '新合成教师', role: 'teacher', status: 'PENDING_ACTIVATION' },
      ] }))
    const wrapper = mount(AdminSchoolDirectory)
    await flushPromises()
    const csv = 'login_name,display_name,role\nSYNTHETIC_student1,新合成学生,student\nSYNTHETIC_teacher1,新合成教师,teacher'
    const file = new globalThis.File([csv], 'synthetic-accounts.csv', { type: 'text/csv' })
    Object.defineProperty(file, 'arrayBuffer', { value: async () => new globalThis.TextEncoder().encode(csv).buffer })
    const input = wrapper.get('#school-account-csv').element as { files?: ArrayLike<globalThis.File> }
    Object.defineProperty(input, 'files', { configurable: true, value: [file] })
    await wrapper.get('#school-account-csv').trigger('change')
    await flushPromises()
    expect(wrapper.text()).not.toContain('SYNTHETIC_student1')
    await wrapper.get('.directory-actions .app-button').trigger('click')
    await flushPromises()
    expect(api.previewSchoolAccountImport).toHaveBeenCalledWith(null, [
      { row_no: 1, login_name: 'SYNTHETIC_student1', display_name: '新合成学生', role: 'student' },
      { row_no: 2, login_name: 'SYNTHETIC_teacher1', display_name: '新合成教师', role: 'teacher' },
    ])
    const importButton = wrapper.get('.directory-actions .app-button:last-child')
    await importButton.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('导入结果尚未确认')
    await importButton.trigger('click')
    await flushPromises()
    expect(api.importSchoolAccounts).toHaveBeenCalledTimes(2)
    expect(api.importSchoolAccounts.mock.calls[0]![2]).toBe(api.importSchoolAccounts.mock.calls[1]![2])
    expect(wrapper.text()).toContain('新合成学生')
    expect(wrapper.text()).toContain('待激活')
    expect(wrapper.text()).toContain('一次性凭据中批量发行登录凭据')
    expect(wrapper.find('input[type="password"]').exists()).toBe(false)
    await wrapper.get('.directory-account-row .app-button').trigger('click')
    expect(wrapper.emitted('open-credentials')).toHaveLength(1)
    wrapper.unmount()
  })

  it('待首次登录账号提供一次性凭据入口，目录中不再收集密码', async () => {
    api.getSchoolAdminDirectory.mockResolvedValue(envelope({
      school: { school_ref: 'SCHOOL_synthetic', display_name: '合成学校' },
      classes: [],
      members: [{ user_id: 'USER_pending', display_name: '待激活学生', role: 'student', account_status: 'SUSPENDED', provisioning_status: 'PENDING_ACTIVATION' }],
    }))
    const wrapper = mount(AdminSchoolDirectory)
    await flushPromises()
    expect(wrapper.text()).toContain('在一次性凭据中批量发行登录凭据')
    expect(wrapper.find('input[type="password"]').exists()).toBe(false)
    await wrapper.get('.directory-account-row .app-button').trigger('click')
    expect(wrapper.emitted('open-credentials')).toHaveLength(1)
    wrapper.unmount()
  })

  it('目录接口失败时显示服务错误且不显示演示目录数据', async () => {
    api.getSchoolAdminDirectory.mockRejectedValueOnce(new Error('synthetic network failure'))
    const wrapper = mount(AdminSchoolDirectory)
    await flushPromises()
    expect(wrapper.text()).toContain('暂时无法读取当前学校目录')
    expect(wrapper.text()).not.toContain('合成学校')
    expect(wrapper.find('#school-account-csv').exists()).toBe(false)
    wrapper.unmount()
  })

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

    await wrapper.findAll('.school-task__actions .app-button')[1].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('报名 123456')
    await wrapper.get('.school-task__enrollment .app-button').trigger('click')
    await flushPromises()
    expect(api.revokeSchoolTaskEnrollment).toHaveBeenCalledWith(task.task_ref, 'ENROLL_123456')
    expect(wrapper.text()).toContain('该报名已撤销')
  })

  it('fixture task publication keeps the existing three-argument request', async () => {
    api.publishSchoolTask.mockResolvedValueOnce(envelope({
      task_ref: 'TASK_published_fixture', plan_name: null, plan_version_number: null,
    }))
    const wrapper = mount(AdminSchoolOperations)
    await flushPromises()
    await wrapper.get('.school-task-step-actions button:last-child').trigger('click')
    await wrapper.get('#school-task-opens').setValue('2026-10-15T09:00')
    await wrapper.get('.school-task-step-actions button:last-child').trigger('click')
    await wrapper.get('.school-form--dates').trigger('submit')
    await flushPromises()
    expect(api.publishSchoolTask).toHaveBeenCalledOnce()
    expect(api.publishSchoolTask.mock.calls[0]).toHaveLength(3)
    expect(wrapper.text()).toContain('已发布')
    wrapper.unmount()
  })

  it('saved-version publication pages metadata and binds only the selected activation', async () => {
    const earlierActivation = {
      ...eligibleActivation,
      activation_ref: 'CACT_87654321-4321-4321-4321-210987654321',
      plan_name: '較早方案',
    }
    api.listActivations.mockResolvedValueOnce({
      items: [earlierActivation], has_more: true, engineering_only: true, psychological_interpretation_allowed: false,
    }).mockResolvedValueOnce({
      items: [eligibleActivation], has_more: false, engineering_only: true, psychological_interpretation_allowed: false,
    })
    api.publishSchoolTask.mockResolvedValueOnce(envelope({
      task_ref: 'TASK_published_saved', plan_name: '合成方案', plan_version_number: 2,
    }))
    const wrapper = mount(AdminSchoolOperations)
    await flushPromises()
    await wrapper.get('#school-task-mode-saved').setValue(true)
    await flushPromises()
    expect(api.listActivations).toHaveBeenCalledWith({ skip: 0, limit: 30 })
    await wrapper.get('.school-task-activation button').trigger('click')
    await flushPromises()
    expect(api.listActivations).toHaveBeenLastCalledWith({ skip: 1, limit: 30 })
    expect(wrapper.text()).toContain('合成方案 v2，合成题库 v3')
    expect(wrapper.text()).not.toContain(eligibleActivation.activation_ref)
    await wrapper.get('#school-task-activation').setValue(eligibleActivation.activation_ref)
    await wrapper.get('.school-task-step-actions button:last-child').trigger('click')
    await wrapper.get('#school-task-opens').setValue('2026-10-15T09:00')
    await wrapper.get('.school-task-step-actions button:last-child').trigger('click')
    await wrapper.get('.school-form--dates').trigger('submit')
    await flushPromises()
    expect(api.publishSchoolTask).toHaveBeenCalledWith(
      task.class_ref, '2026-10-15T01:00:00.000Z', null, eligibleActivation.activation_ref,
    )
    expect(wrapper.text()).toContain('绑定 合成方案 v2')
    wrapper.unmount()
  })

  it('does not fall back to fixture mode when eligible activation metadata fails to load', async () => {
    api.listActivations.mockRejectedValueOnce({ code: 'NETWORK_UNAVAILABLE' })
    const wrapper = mount(AdminSchoolOperations)
    await flushPromises()
    await wrapper.get('#school-task-mode-saved').setValue(true)
    await flushPromises()
    expect(wrapper.text()).toContain('暂时无法读取可用于新任务')
    expect(wrapper.get('.school-task-step-actions button').attributes('disabled')).toBeDefined()
    await wrapper.get('.school-form--dates').trigger('submit')
    await flushPromises()
    expect(api.publishSchoolTask).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('任务不会按其他版本发布')
    expect(wrapper.text()).not.toContain('已收到服务端确认')
    wrapper.unmount()
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

  it('学生任务空态和访问拒绝分别显示对应状态', async () => {
    api.listStudentSchoolTasks.mockResolvedValueOnce(envelope([]))
    const emptyWrapper = mount(StudentAssignedTasks)
    await flushPromises()
    expect(emptyWrapper.find('.assigned-tasks__state').text()).toContain('当前没有分配给你的任务')
    emptyWrapper.unmount()

    api.listStudentSchoolTasks.mockRejectedValueOnce({ code: 'forbidden' })
    const deniedWrapper = mount(StudentAssignedTasks)
    await flushPromises()
    expect(deniedWrapper.find('.assigned-tasks__state').text()).toContain('当前任务暂不可访问')
    expect(deniedWrapper.find('.assigned-tasks__state').text()).not.toContain('当前没有分配给你的任务')
    deniedWrapper.unmount()
  })

  it('学生任务卡片不展示测评分数或原始回答', async () => {
    api.listStudentSchoolTasks.mockResolvedValueOnce(envelope([{
      ...task, task_ref: 'TASK_synthetic_987654', assessment_id: 'ASSESS_synthetic_987654',
      assessment_status: 'completed',
    }]))
    const wrapper = mount(StudentAssignedTasks)
    await flushPromises()
    expect(wrapper.text()).toContain('班级任务 987654')
    expect(wrapper.text()).toContain('已完成')
    expect(wrapper.text()).not.toMatch(/测评结果|查看报告|分数|得分|原始回答/)
    expect(api.listStudentSchoolTaskHistory).not.toHaveBeenCalled()
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
    window.localStorage.removeItem('psynova.teacher.preview.dataMode')
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/teacher/overview', component: TeacherOverviewView }],
    })
    await router.push('/teacher/overview')
    await router.isReady()
    const wrapper = mount(TeacherOverviewView, { global: { plugins: [router] } })
    await flushPromises()
    await vi.waitFor(() => expect(wrapper.find('.overview-board').exists()).toBe(true))

    expect(wrapper.text()).toContain('进行中任务')
    expect(wrapper.text()).toContain('测评完成率')
    expect(wrapper.text()).not.toContain('SUBJ_')
    expect(wrapper.text()).not.toContain('ASSESS_')
    expect(wrapper.text()).not.toContain('USER_')
  })
})
