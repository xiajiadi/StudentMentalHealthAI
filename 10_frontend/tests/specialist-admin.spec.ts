import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AdminWorkspaceView from '@/views/admin/AdminWorkspaceView.vue'
import SpecialistWorkspaceView from '@/views/specialist/SpecialistWorkspaceView.vue'
import AdminSchoolOperations from '@/components/school/AdminSchoolOperations.vue'
import { useSessionStore } from '@/stores/session'

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

  it('管理员学校上下文变化时重建任务页组件，清除上一个学校的本地选择', async () => {
    health.readDependencyHealth.mockResolvedValue({})
    const wrapper = await mountAt('/admin/tasks', AdminWorkspaceView)
    const session = useSessionStore(wrapper.vm.$pinia)
    session.signIn({
      userId: 'USER_synthetic_admin', role: 'school_admin', subjectId: null,
      displayName: '合成管理员', initials: 'A',
      activeContext: { role: 'school_admin', schoolRef: 'SCHOOL_synthetic_alpha' },
    })
    await flushPromises()
    const previous = wrapper.findComponent(AdminSchoolOperations).vm
    session.signIn({
      userId: 'USER_synthetic_admin', role: 'school_admin', subjectId: null,
      displayName: '合成管理员', initials: 'A',
      activeContext: { role: 'school_admin', schoolRef: 'SCHOOL_synthetic_beta' },
    })
    await flushPromises()
    expect(wrapper.findComponent(AdminSchoolOperations).vm).not.toBe(previous)
    wrapper.unmount()
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

  it('专业资料页明确区分工程审核元数据与专业批准', async () => {
    const wrapper = await mountAt('/specialist/resources', SpecialistWorkspaceView)

    expect(wrapper.text()).toContain('工程审核状态不等于专业批准')
    expect(wrapper.text()).toContain('当前无法读取经过校验的来源目录')
    expect(wrapper.findAll('a[href*="resource"]')).toHaveLength(0)
  })

  it('两个角色工作区呈现各自的工作入口', async () => {
    const specialist = await mountAt('/specialist/overview', SpecialistWorkspaceView)
    const admin = await mountAt('/admin/overview', AdminWorkspaceView)

    expect(specialist.text()).toContain('专业复核与反馈')
    expect(admin.text()).toContain('班级管理')
  })

  it('学校账号页面在缺少组织接口时显示不可用，不返回演示账号或成功状态', async () => {
    const wrapper = await mountAt('/admin/users', AdminWorkspaceView)

    expect(wrapper.text()).toContain('当前运行环境没有提供学校目录服务')
    expect(wrapper.text()).not.toContain('USER_')
    expect(wrapper.text()).not.toContain('已加入班级')
    expect(wrapper.text()).toContain('目录暂时无法读取')
    expect(health.readDependencyHealth).not.toHaveBeenCalled()
  })

  it('系统设置读取失败时展示未知状态，不填入演示健康结果', async () => {
    health.readDependencyHealth.mockRejectedValueOnce('offline')
    const wrapper = await mountAt('/admin/settings', AdminWorkspaceView)

    expect(wrapper.text()).toContain('GET /health/dependencies')
    expect(wrapper.text()).toContain('当前各项状态均未知')
    expect(wrapper.text()).not.toContain('Backend 可用')
    expect(health.readDependencyHealth).toHaveBeenCalledTimes(1)
  })

  it('健康端点返回非对象时显示未知状态，不在渲染中抛错', async () => {
    health.readDependencyHealth.mockResolvedValueOnce(undefined)
    const wrapper = await mountAt('/admin/settings', AdminWorkspaceView)

    expect(wrapper.text()).toContain('当前各项状态均未知')
    expect(wrapper.text()).not.toContain('正在读取服务端状态')
  })
})
