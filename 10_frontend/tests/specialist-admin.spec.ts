import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AdminWorkspaceView from '@/views/admin/AdminWorkspaceView.vue'
import SpecialistWorkspaceView from '@/views/specialist/SpecialistWorkspaceView.vue'

const health = vi.hoisted(() => ({ readDependencyHealth: vi.fn() }))
vi.mock('@/views/admin/health', () => health)

const professionalReviewTransport = vi.hoisted(() => ({ request: vi.fn() }))
vi.mock('@/services/real-api', () => ({
  RealApiError: class RealApiError extends Error {
    constructor(public code: string, message: string) { super(message) }
  },
  requestProfessionalReview: professionalReviewTransport.request,
}))

const response = (data: unknown) => ({
  request_id: 'REQ_synthetic_review',
  trace_id: 'TRACE_synthetic_review',
  data,
})

const mountAt = async (path: string, component: typeof AdminWorkspaceView | typeof SpecialistWorkspaceView) => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:role/:section', component }],
  })
  await router.push(path)
  await router.isReady()
  const wrapper = mount(component, { global: { plugins: [router, createPinia()] } })
  await flushPromises()
  return wrapper
}

describe('Specialist 与学校管理员工作区', () => {
  beforeEach(() => {
    health.readDependencyHealth.mockReset()
    professionalReviewTransport.request.mockReset()
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
    expect(health.readDependencyHealth).not.toHaveBeenCalled()
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
    expect(health.readDependencyHealth).not.toHaveBeenCalled()
  })

  it('专业资料页不把未审核资料呈现为可用内容', async () => {
    const wrapper = await mountAt('/specialist/resources', SpecialistWorkspaceView)

    expect(wrapper.text()).toContain('资料目录当前不可读取')
    expect(wrapper.text()).toContain('来源、权利状态和专业审核状态未在此确认')
    expect(wrapper.findAll('a[href*="resource"]')).toHaveLength(0)
  })

  it('两个角色都展示各自的原始插画资源', async () => {
    const specialist = await mountAt('/specialist/overview', SpecialistWorkspaceView)
    const admin = await mountAt('/admin/overview', AdminWorkspaceView)

    expect(specialist.findAll('img').map((image) => image.attributes('src'))).toContain('/assets/heartbridge/card-specialist-original.png')
    expect(admin.findAll('img').map((image) => image.attributes('src'))).toContain('/assets/heartbridge/card-admin-original.png')
    expect(specialist.findAll('img').map((image) => image.attributes('src'))).toContain('/assets/heartbridge/hero-flow-original.png')
    expect(admin.findAll('img').map((image) => image.attributes('src'))).toContain('/assets/heartbridge/hero-flow-original.png')
  })

  it('学校账号页面在缺少组织接口时显示不可用，不返回演示账号或成功状态', async () => {
    const wrapper = await mountAt('/admin/users', AdminWorkspaceView)

    expect(wrapper.text()).toContain('当前运行环境未提供学校组织服务')
    expect(wrapper.text()).not.toContain('USER_')
    expect(wrapper.text()).not.toContain('已加入班级')
    expect(wrapper.text()).toContain('安全复核员（REVIEWER）是独立角色')
    expect(health.readDependencyHealth).not.toHaveBeenCalled()
  })

  it('系统设置读取失败时展示未知状态，不填入演示健康结果', async () => {
    health.readDependencyHealth.mockRejectedValueOnce('offline')
    const wrapper = await mountAt('/admin/settings', AdminWorkspaceView)

    expect(wrapper.text()).toContain('GET /health/dependencies')
    expect(wrapper.text()).toContain('状态未知，不以本地占位值代替')
    expect(wrapper.text()).not.toContain('Backend 可用')
    expect(health.readDependencyHealth).toHaveBeenCalledTimes(1)
  })

  it('健康端点返回非对象时显示未知状态，不在渲染中抛错', async () => {
    health.readDependencyHealth.mockResolvedValueOnce(undefined)
    const wrapper = await mountAt('/admin/settings', AdminWorkspaceView)

    expect(wrapper.text()).toContain('状态未知，不以本地占位值代替')
    expect(wrapper.text()).not.toContain('正在读取服务端状态')
  })
})
