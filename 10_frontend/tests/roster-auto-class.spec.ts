/* global File, HTMLButtonElement */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it, vi } from 'vitest'
import AccountLifecycleWorkspace from '@/views/admin/AccountLifecycleWorkspace.vue'
import type { LifecycleRosterRow } from '@/api/client'

const api = vi.hoisted(() => ({
  getLifecycleAccountSummary: vi.fn(), getSchoolAdminDirectory: vi.fn(),
  previewLifecycleRoster: vi.fn(), importLifecycleRoster: vi.fn(),
  issueLifecycleCredentials: vi.fn(), listRecoveryRequests: vi.fn(),
}))
vi.mock('@/services/mock-api', () => ({ frontendApi: api }))
const envelope = <T,>(data: T) => ({ request_id: 'REQ_TEST', trace_id: 'TRACE_TEST', data })
const className = '合成新班'
const classRef = 'ROSTER_CLASS_TEST'

describe('学生名单自动建班和账号交付', () => {
  it('800人分四批预检、确认、自动签发并下载全部凭据', async () => {
    api.getLifecycleAccountSummary.mockResolvedValue(envelope({ total_accounts: 0, active_accounts: 0, pending_activation: 0, suspended_accounts: 0, classes: 0, invitations_issued: 0, invitations_accepted: 0, invitations_expired: 0, invitations_revoked: 0, recovery_queue_count: 0 }))
    api.getSchoolAdminDirectory.mockResolvedValue(envelope({ school: { school_ref: 'SCHOOL_SYNTHETIC', display_name: '合成学校', data_origin: 'SYNTHETIC' }, classes: [], members: [] }))
    api.listRecoveryRequests.mockResolvedValue(envelope([]))
    api.previewLifecycleRoster.mockImplementation(async (rows: LifecycleRosterRow[]) => envelope({
      valid: true, row_count: rows.length, errors: [],
      class_plan: [{ input_ref: className, class_ref: classRef, display_name: className, grade_level: 'U2', action: 'CREATE', row_count: rows.length }],
    }))
    api.importLifecycleRoster.mockImplementation(async (rows: LifecycleRosterRow[]) => envelope({
      run_ref: 'RUN_SYNTHETIC', row_count: rows.length, status: 'COMPLETED',
      created_count: rows.length, skipped_count: 0,
      accounts: rows.map(row => ({ row_no: row.row_no, user_id: 'USER_' + row.student_number, display_name: row.display_name, class_ref: classRef, status: 'PENDING_ACTIVATION' })),
    }))
    api.issueLifecycleCredentials.mockImplementation(async (ids: string[]) => envelope({
      credentials: ids.map(id => ({ user_id: id, login_name: 'LOGIN_' + id, display_name: '合成学生', class_ref: classRef, credential: 'PN-test-' + id, expires_at: '2026-12-01T00:00:00Z' })),
    }))
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(AccountLifecycleWorkspace, { global: { plugins: [createPinia(), router] } })
    let download: Blob | undefined
    const createObjectURL = vi.fn((blob: Blob) => { download = blob; return 'blob:roster-test' })
    const anchor = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const originalCreate = URL.createObjectURL
    const originalRevoke = URL.revokeObjectURL
    URL.createObjectURL = createObjectURL
    URL.revokeObjectURL = vi.fn()
    try {
      await flushPromises()
      await wrapper.findAll('[role="tab"]').find(tab => tab.text().includes('学生名单'))!.trigger('click')
      const csv = 'student_number,display_name,class_ref,grade_level\n' + Array.from({ length: 800 }, (_, i) => 'S' + i + ',合成学生' + i + ',' + className + ',大二').join('\n')
      const bytes = new TextEncoder().encode(csv)
      const file = new File([csv], 'roster.csv', { type: 'text/csv' })
      Object.defineProperty(file, 'arrayBuffer', { value: async () => bytes.buffer })
      const fileInput = wrapper.get('input[type="file"]')
      Object.defineProperty(fileInput.element, 'files', { value: [file] })
      await fileInput.trigger('change')
      await flushPromises()
      expect(api.previewLifecycleRoster).toHaveBeenCalledTimes(4)
      expect(api.importLifecycleRoster).not.toHaveBeenCalled()
      expect(wrapper.text()).toContain('自动新建')
      expect(wrapper.text()).toContain('800')
      const confirm = wrapper.findAll('button').find(button => button.text() === '导入并生成初始账号')!
      expect((confirm.element as HTMLButtonElement).disabled).toBe(false)
      await confirm.trigger('click')
      await flushPromises()
      expect(api.importLifecycleRoster).toHaveBeenCalledTimes(4)
      expect(api.issueLifecycleCredentials).toHaveBeenCalledTimes(4)
      expect(wrapper.text()).toContain('已导入 800 名学生并生成初始账号')
      expect(wrapper.text()).not.toContain('PN-test-')
      await wrapper.findAll('button').find(button => button.text().includes('下载账号 CSV（800 份）'))!.trigger('click')
      expect(anchor).toHaveBeenCalledOnce()
      const result = await download!.text()
      expect(result).toContain('学号')
      expect(result).toContain(className)
      expect(result).toContain('LOGIN_USER_S799')
      expect(result).toContain('PN-test-USER_S799')
      expect(result.trim().split('\r\n')).toHaveLength(801)
      expect(wrapper.text()).not.toContain('下载账号 CSV（800 份）')
    } finally {
      wrapper.unmount()
      anchor.mockRestore()
      URL.createObjectURL = originalCreate
      URL.revokeObjectURL = originalRevoke
    }
  })
})
