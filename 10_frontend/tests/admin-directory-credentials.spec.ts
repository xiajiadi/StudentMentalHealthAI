import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AdminDirectoryStudio from '@/components/school/AdminDirectoryStudio.vue'

const api = vi.hoisted(() => ({
  getSchoolAdminDirectory: vi.fn(),
  listSchoolMembers: vi.fn(),
  getSchoolAccountBatch: vi.fn(),
  updateSchoolDisplayName: vi.fn(),
  updateSchoolClassDisplayName: vi.fn(),
  updateSchoolMemberDisplayName: vi.fn(),
  previewSchoolAccountImport: vi.fn(),
  importSchoolAccounts: vi.fn(),
  createSchoolClass: vi.fn(),
  assignSchoolStudent: vi.fn(),
  assignSchoolTeacher: vi.fn(),
}))

vi.mock('@/services/mock-api', () => ({ frontendApi: api }))

const envelope = <T,>(data: T) => ({ request_id: 'REQ_admin_directory', trace_id: 'TRACE_admin_directory', data })

describe('AdminDirectoryStudio credential handoff', () => {
  let router: ReturnType<typeof createRouter>

  beforeEach(async () => {
    vi.clearAllMocks()
    api.getSchoolAdminDirectory.mockResolvedValue(envelope({
      school: { school_ref: 'SCHOOL_SYNTHETIC', display_name: '合成学校' },
      classes: [],
      members: [{
        user_id: 'USER_PENDING_SYNTHETIC', display_name: '待首次登录学生', role: 'student',
        account_status: 'ACTIVE', provisioning_status: 'PENDING_ACTIVATION',
      }],
    }))
    api.listSchoolMembers.mockImplementation(async (role: string) => envelope([{
      user_id: `USER_${role.toUpperCase()}_SYNTHETIC`, role, subject_id: null, display_name: `合成${role}`,
    }]))
    router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/admin/users', component: { template: '<div />' } }] })
    await router.push('/admin/users')
    await router.isReady()
  })

  afterEach(() => vi.restoreAllMocks())

  it('removes direct password controls and routes a pending account to one-time credentials', async () => {
    const wrapper = mount(AdminDirectoryStudio, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.find('input[type="password"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('设置密码')
    expect(wrapper.text()).not.toContain('激活账号')
    expect(wrapper.text()).toContain('一次性凭据中批量发行')

    await wrapper.get('.directory-studio__pending-list button').trigger('click')
    expect(wrapper.emitted('open-credentials')).toHaveLength(1)
    wrapper.unmount()
  })
})
