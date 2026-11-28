import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AdminWorkspaceView from '@/views/admin/AdminWorkspaceView.vue'
import SpecialistWorkspaceView from '@/views/specialist/SpecialistWorkspaceView.vue'
import AdminTaskDispatch from '@/components/school/AdminTaskDispatch.vue'
import { useSessionStore } from '@/stores/session'

const health = vi.hoisted(() => ({ getHealth: vi.fn() }))
vi.mock('@/api/generated/sdk.gen', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/api/generated/sdk.gen')>(),
  getHealth: health.getHealth,
}))

const workspaceApi = vi.hoisted(() => ({ listResearchSourceCatalog: vi.fn() }))
vi.mock('@/services/mock-api', () => ({ frontendApi: workspaceApi }))

const professionalReviewTransport = vi.hoisted(() => ({ request: vi.fn() }))
vi.mock('@/services/real-api', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/services/real-api')>(),
  requestProfessionalReview: professionalReviewTransport.request,
}))

const response = (data: unknown) => ({
  request_id: 'REQ_synthetic_review',
  trace_id: 'TRACE_synthetic_review',
  data,
})

enableAutoUnmount(afterEach)

const mountAt = async (path: string, component: typeof AdminWorkspaceView | typeof SpecialistWorkspaceView) => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:role/:section', component }],
  })
  await router.push(path)
  await router.isReady()
  const pinia = createPinia()
  const role = path.startsWith('/admin/') ? 'school_admin' : 'psychological_specialist'
  useSessionStore(pinia).signIn({
    userId: 'USER_synthetic_staff', role, subjectId: null, displayName: '合成用户', initials: '合',
    activeContext: { role, schoolRef: 'SCHOOL_synthetic_alpha' },
  })
  const wrapper = mount(component, { global: { plugins: [router, pinia] } })
  await vi.dynamicImportSettled()
  await flushPromises()
  return wrapper
}

describe('Specialist 与学校管理员工作区', () => {
  beforeEach(() => {
    health.getHealth.mockReset().mockResolvedValue({
      data: response({ dependencies: { backend: { status: 'OK', integration: 'REAL_HTTP' } } }),
    })
    workspaceApi.listResearchSourceCatalog.mockReset()
    professionalReviewTransport.request.mockReset()
  })

  it('管理员学校上下文变化时重建任务页组件，清除上一个学校的本地选择', async () => {
    const wrapper = await mountAt('/admin/tasks', AdminWorkspaceView)
    const session = useSessionStore(wrapper.vm.$pinia)
    const previous = wrapper.getComponent(AdminTaskDispatch).vm
    session.signIn({
      userId: 'USER_synthetic_staff', role: 'school_admin', subjectId: null,
      displayName: '合成用户', initials: '合',
      activeContext: { role: 'school_admin', schoolRef: 'SCHOOL_synthetic_beta' },
    })
    await flushPromises()
    expect(wrapper.getComponent(AdminTaskDispatch).vm).not.toBe(previous)
  })

  it('专业工作事项使用后端空完成记录，不伪造复核成功状态', async () => {
    professionalReviewTransport.request.mockImplementation((request: { path: string }) => {
      if (request.path === '/api/v1/school/professional-reviews/tasks') {
        return Promise.resolve(response([{
          task_ref: 'TASK_SYNTHETIC_1',
          class_ref: 'CLASS_SYNTHETIC_1',
          class_display_name: null,
          published_at: '2026-10-12T00:00:00Z',
        }]))
      }
      if (request.path.endsWith('/eligible-enrollments')) {
        return Promise.resolve(response({ items: [], total: 0 }))
      }
      if (request.path.endsWith('/cases')) {
        return Promise.resolve(response({ items: [], total: 0 }))
      }
      throw new Error(`Unexpected professional review request: ${request.path}`)
    })
    const wrapper = await mountAt('/specialist/tasks', SpecialistWorkspaceView)

    expect(professionalReviewTransport.request).toHaveBeenCalledWith({
      method: 'GET', path: '/api/v1/school/professional-reviews/tasks',
    })
    await wrapper.get('.task-option').trigger('click')
    await flushPromises()

    expect(professionalReviewTransport.request).toHaveBeenCalledWith({
      method: 'GET',
      path: '/api/v1/school/professional-reviews/tasks/TASK_SYNTHETIC_1/eligible-enrollments',
      query: { offset: 0, limit: 10 },
    })
    expect(professionalReviewTransport.request).toHaveBeenCalledWith({
      method: 'GET',
      path: '/api/v1/school/professional-reviews/tasks/TASK_SYNTHETIC_1/cases',
      query: { offset: 0, limit: 10 },
    })
    expect(wrapper.text()).toContain('此任务当前没有可处理的完成记录')
    expect(wrapper.text()).toContain('此任务尚无复核记录')
    expect(wrapper.text()).not.toContain('案例查看与处理尚未开放')
    expect(wrapper.text()).not.toContain('不会调用安全复核接口，也不会模拟审核成功')
    expect(wrapper.text()).not.toContain('已通过')
    expect(wrapper.text()).not.toContain('个案详情')
    expect(wrapper.text()).not.toContain('报告状态：已发布')
    expect(wrapper.text()).not.toContain('建立复核记录')
    expect(health.getHealth).not.toHaveBeenCalled()
  })

  it('专业工作事项遇到后端拒绝时显示访问状态，不显示成功或空列表假象', async () => {
    professionalReviewTransport.request.mockRejectedValueOnce(
      Object.assign(new Error('当前访问状态已变化'), { code: 'FORBIDDEN' }),
    )
    const wrapper = await mountAt('/specialist/tasks', SpecialistWorkspaceView)

    expect(professionalReviewTransport.request).toHaveBeenCalledWith({
      method: 'GET', path: '/api/v1/school/professional-reviews/tasks',
    })
    expect(wrapper.text()).toContain('当前访问状态已变化')
    expect(wrapper.text()).toContain('已清除本页缓存')
    expect(wrapper.text()).not.toContain('当前没有可显示的已指派任务')
    expect(wrapper.text()).not.toContain('已通过')
    expect(wrapper.text()).not.toContain('已完成记录')
    expect(wrapper.text()).not.toContain('个案详情')
    expect(health.getHealth).not.toHaveBeenCalled()
  })

  it('专业资料页明确显示来源目录尚未提供，且不渲染资料链接', async () => {
    workspaceApi.listResearchSourceCatalog.mockRejectedValueOnce(Object.assign(
      new Error('private error detail'), { code: 'RESEARCH_SERVICE_UNAVAILABLE' },
    ))
    const wrapper = await mountAt('/specialist/resources', SpecialistWorkspaceView)

    expect(workspaceApi.listResearchSourceCatalog).toHaveBeenCalledWith(expect.objectContaining({ offset: 0, limit: 20 }))
    expect(wrapper.text()).toContain('来源目录尚未提供')
    expect(wrapper.text()).not.toContain('private error detail')
    expect(wrapper.findAll('.specialist-resources a[target="_blank"]')).toHaveLength(0)
  })

  it('两个角色工作区呈现各自的工作入口', async () => {
    const specialist = await mountAt('/specialist/overview', SpecialistWorkspaceView)
    const admin = await mountAt('/admin/overview', AdminWorkspaceView)

    expect(specialist.get('[aria-label="专业工作地图"]').text()).toContain('任务复核')
    expect(specialist.text()).toContain('研究反馈')
    expect(admin.get('[aria-label="学校运营工作区"]').text()).toContain('班级')
  })

  it('学校账号页面在缺少组织接口时显示不可用，不返回演示账号或成功状态', async () => {
    const wrapper = await mountAt('/admin/users', AdminWorkspaceView)

    expect(wrapper.text()).toContain('账号生命周期服务不可用')
    expect(wrapper.text()).not.toContain('USER_')
    expect(wrapper.text()).not.toContain('已加入班级')
    expect(wrapper.text()).toContain('暂无账号汇总')
    expect(health.getHealth).not.toHaveBeenCalled()
  })

  it('系统设置读取失败时展示未知状态，不填入演示健康结果', async () => {
    health.getHealth.mockResolvedValueOnce({ error: { code: 'offline' }, response: { status: 503 } })
    const wrapper = await mountAt('/admin/settings', AdminWorkspaceView)

    expect(wrapper.get('[role="alert"]').text()).toContain('无法获取当前状态')
    expect(wrapper.find('[aria-label="依赖服务目录"]').exists()).toBe(false)
    expect(health.getHealth).toHaveBeenCalledTimes(1)
    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(health.getHealth).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[aria-label="服务详情"]').text()).toContain('GET /api/v1/health')
  })

  it('管理员任务、运营和系统状态页不显示 banner 与已移除说明卡', async () => {
    const tasks = await mountAt('/admin/tasks', AdminWorkspaceView)
    expect(tasks.find('.student-page-hero').exists()).toBe(false)
    tasks.unmount()

    const audit = await mountAt('/admin/audit', AdminWorkspaceView)
    expect(audit.find('.student-page-hero').exists()).toBe(false)
    expect(audit.text()).not.toContain('按事务类型查看')
    audit.unmount()

    const settings = await mountAt('/admin/settings', AdminWorkspaceView)
    expect(settings.find('.student-page-hero').exists()).toBe(false)
    expect(settings.find('.health-disclosure').exists()).toBe(false)
    expect(settings.find('.health-scope').exists()).toBe(false)
    settings.unmount()
  })

  it('健康端点返回非对象时显示未知状态，不在渲染中抛错', async () => {
    health.getHealth.mockResolvedValueOnce({ data: response({ dependencies: 'malformed' }) })
    const wrapper = await mountAt('/admin/settings', AdminWorkspaceView)

    expect(wrapper.get('[role="alert"]').text()).toContain('健康端点返回的数据无法识别')
    expect(wrapper.find('[aria-label="服务目录，可使用鼠标滚轮或方向键浏览"]').exists()).toBe(false)
  })
})
