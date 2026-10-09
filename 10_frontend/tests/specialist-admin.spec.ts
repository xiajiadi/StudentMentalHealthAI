import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AdminWorkspaceView from '@/views/admin/AdminWorkspaceView.vue'
import SpecialistWorkspaceView from '@/views/specialist/SpecialistWorkspaceView.vue'

const health = vi.hoisted(() => ({ readDependencyHealth: vi.fn() }))
vi.mock('@/views/admin/health', () => health)

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
  beforeEach(() => health.readDependencyHealth.mockReset())

  it('专业工作事项明确显示未接入，不产生虚构的复核成功状态', async () => {
    const wrapper = await mountAt('/specialist/tasks', SpecialistWorkspaceView)

    expect(wrapper.text()).toContain('案例查看与处理尚未开放')
    expect(wrapper.text()).toContain('不会调用安全复核接口，也不会模拟审核成功')
    expect(wrapper.text()).toContain('没有待办数量或个案详情')
    expect(wrapper.text()).not.toContain('已通过')
    expect(wrapper.findAll('button')).toHaveLength(0)
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

  it('学校账号页面显示管理接口不可用，且不把只读健康检查当作账号操作', async () => {
    const wrapper = await mountAt('/admin/users', AdminWorkspaceView)

    expect(wrapper.text()).toContain('账号与角色管理尚不可用')
    expect(wrapper.text()).toContain('不会读取用户目录、创建账号、调整权限或模拟保存成功')
    expect(wrapper.text()).toContain('安全复核员（REVIEWER）是独立角色')
    expect(wrapper.findAll('button')).toHaveLength(0)
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
