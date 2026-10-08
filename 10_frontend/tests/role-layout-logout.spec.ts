import { defineComponent } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import TeacherLayout from '@/layouts/TeacherLayout.vue'
import ReviewerLayout from '@/layouts/ReviewerLayout.vue'
import { useSessionStore } from '@/stores/session'

const api = vi.hoisted(() => ({ logout: vi.fn() }))

vi.mock('@/services/mock-api', () => ({ frontendApi: api }))

const SidebarStub = defineComponent({
  emits: ['logout', 'update:mobileOpen'],
  template: '<button type="button" class="test-logout" @click="$emit(\'logout\')">退出</button>',
})

async function mountRoleLayout(
  layout: typeof TeacherLayout | typeof ReviewerLayout,
  role: 'teacher' | 'reviewer',
) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: `/${role}/home`, component: { template: '<div>工作区</div>' } },
      { path: '/login', component: { template: '<div>登录</div>' } },
    ],
  })
  await router.push(`/${role}/home`)
  await router.isReady()

  const pinia = createPinia()
  setActivePinia(pinia)
  const session = useSessionStore()
  session.signIn({
    userId: `USER_${role}`,
    role,
    subjectId: null,
    displayName: '合成用户',
    initials: role === 'teacher' ? '师' : '复',
  })

  const wrapper = mount(layout, {
    global: {
      plugins: [pinia, router],
      stubs: { RoleSidebar: SidebarStub },
    },
  })
  return { wrapper, router, session }
}

afterEach(() => vi.clearAllMocks())

describe('teacher and reviewer session logout', () => {
  it.each([
    { layout: TeacherLayout, role: 'teacher' as const },
    { layout: ReviewerLayout, role: 'reviewer' as const },
  ])('revokes the server session before leaving the $role workspace', async ({ layout, role }) => {
    api.logout.mockResolvedValue({ data: { logged_out: true } })
    const { wrapper, router, session } = await mountRoleLayout(layout, role)

    await wrapper.get('.test-logout').trigger('click')
    await flushPromises()

    expect(api.logout).toHaveBeenCalledOnce()
    expect(router.currentRoute.value.path).toBe('/login')
    expect(session.isAuthenticated).toBe(false)
    wrapper.unmount()
  })

  it('keeps the local session and reports a retryable message when logout cannot reach the backend', async () => {
    api.logout.mockRejectedValue(new Error('synthetic network failure'))
    const { wrapper, router, session } = await mountRoleLayout(TeacherLayout, 'teacher')

    await wrapper.get('.test-logout').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/teacher/home')
    expect(session.isAuthenticated).toBe(true)
    expect(wrapper.text()).toContain('暂时无法退出')
    wrapper.unmount()
  })
})
