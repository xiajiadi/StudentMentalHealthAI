import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent, h, nextTick } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import AdminWorkspaceView from '@/views/admin/AdminWorkspaceView.vue'

const api = vi.hoisted(() => ({
  getSchoolAdminDirectory: vi.fn(),
  listSchoolMembers: vi.fn(),
}))

vi.mock('@/services/mock-api', () => ({ frontendApi: api }))

describe('AdminWorkspaceView one-time credential handoff', () => {
  it('opens the lifecycle credential section when the directory emits its handoff event', async () => {
    const openCredentials = vi.fn()
    api.getSchoolAdminDirectory.mockResolvedValue({
      request_id: 'REQ_admin_directory', trace_id: 'TRACE_admin_directory',
      data: {
        school: { school_ref: 'SCHOOL_SYNTHETIC', display_name: '合成学校' },
        classes: [],
        members: [{ user_id: 'USER_PENDING', display_name: '待首次登录学生', role: 'student', account_status: 'ACTIVE', provisioning_status: 'PENDING_ACTIVATION' }],
      },
    })
    api.listSchoolMembers.mockResolvedValue({ request_id: 'REQ_admin_directory', trace_id: 'TRACE_admin_directory', data: [] })
    const LifecycleStub = defineComponent({
      setup(_props, { expose }) {
        expose({ openCredentials })
        return () => h('div', { class: 'lifecycle-stub' })
      },
    })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/admin/:section', component: AdminWorkspaceView }],
    })
    await router.push('/admin/users')
    await router.isReady()
    const wrapper = mount(AdminWorkspaceView, {
      global: {
        plugins: [createPinia(), router],
        stubs: { AccountLifecycleWorkspace: LifecycleStub },
      },
    })
    await flushPromises()
    await flushPromises()
    await wrapper.get('.directory-studio__pending-list button').trigger('click')
    await nextTick()
    expect(openCredentials).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
