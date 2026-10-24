/* global File, HTMLButtonElement */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AccountLifecycleWorkspace from '@/views/admin/AccountLifecycleWorkspace.vue'

const api = vi.hoisted(() => ({
  getLifecycleAccountSummary: vi.fn(), getSchoolAdminDirectory: vi.fn(), listRecoveryRequests: vi.fn(),
  previewLifecycleRoster: vi.fn(), importLifecycleRoster: vi.fn(), inviteSchoolStaff: vi.fn(),
  issueLifecycleCredentials: vi.fn(), approveRecoveryRequest: vi.fn(), reauthenticate: vi.fn(),
  listStaffInvitations: vi.fn(), revokeStaffInvitation: vi.fn(), reissueStaffInvitation: vi.fn(),
  issueStaffRecoveryCredential: vi.fn(),
  updateSchoolAccountStatus: vi.fn(),
}))
vi.mock('@/services/mock-api', () => ({ frontendApi: api }))

const envelope = <T,>(data: T) => ({ request_id: 'REQ_UI', trace_id: 'TRACE_UI', data })

describe('管理员账号生命周期工作区', () => {
  beforeEach(() => {
    Object.values(api).forEach((mock) => mock.mockReset())
    api.getLifecycleAccountSummary.mockResolvedValue(envelope({ total_accounts: 4, active_accounts: 2, pending_activation: 1, suspended_accounts: 1, classes: 1, invitations_issued: 0, invitations_accepted: 0, invitations_expired: 0, invitations_revoked: 0, recovery_queue_count: 0 }))
    api.getSchoolAdminDirectory.mockResolvedValue(envelope({ school: { school_ref: 'SCHOOL_SYNTHETIC', display_name: '合成学校' }, classes: [{ class_ref: 'CLASS_SYNTHETIC', status: 'ACTIVE', active_student_count: 1, active_teacher_count: 1, display_name: '合成班级' }], members: [
      { user_id: 'USER_STUDENT', display_name: '合成学生', role: 'student', account_status: 'ACTIVE', provisioning_status: 'PENDING_ACTIVATION' },
    ] }))
    api.listRecoveryRequests.mockResolvedValue(envelope([]))
    api.listStaffInvitations.mockResolvedValue(envelope([]))
    api.reauthenticate.mockResolvedValue(envelope({ reauthenticated_at: '2026-10-24T00:00:00Z' }))
  })

  it('只展示后端汇总和账号元数据', async () => {
    const wrapper = mount(AccountLifecycleWorkspace)
    await flushPromises()
    expect(wrapper.text()).toContain('账号总数')
    expect(wrapper.text()).not.toContain('原始回答内容')
    wrapper.unmount()
  })

  it('花名册必须先请求服务端预览，通过后才开放确认导入', async () => {
    api.previewLifecycleRoster.mockResolvedValue(envelope({ valid: true, row_count: 1, errors: [], class_groups: [{ class_ref: 'CLASS_SYNTHETIC', row_count: 1 }] }))
    api.importLifecycleRoster.mockResolvedValue(envelope({ run_ref: 'RUN_SYNTHETIC', valid: true, row_count: 1, errors: [], created_count: 1, skipped_count: 0, status: 'COMPLETED' }))
    const wrapper = mount(AccountLifecycleWorkspace)
    await flushPromises()
    await wrapper.findAll('[role="tab"]')[1]!.trigger('click')
    const fileInput = wrapper.get('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', { value: [new File(['# psynova_student_roster_template_v1\nstudent_number,display_name,class_ref,grade_level\nS-1,"合成,学生",CLASS_SYNTHETIC,7'], 'roster.csv', { type: 'text/csv' })] })
    await fileInput.trigger('change')
    await flushPromises()
    expect(wrapper.text()).toContain('合成,学生')
    const confirm = wrapper.findAll('button').find((button) => button.text() === '确认导入')!
    expect((confirm.element as HTMLButtonElement).disabled).toBe(true)
    await wrapper.findAll('button').find((button) => button.text() === '服务端预览')!.trigger('click')
    await flushPromises()
    expect(api.previewLifecycleRoster).toHaveBeenCalledWith([{ row_no: 1, student_number: 'S-1', display_name: '合成,学生', class_ref: 'CLASS_SYNTHETIC', grade_level: '7' }])
    expect((confirm.element as HTMLButtonElement).disabled).toBe(false)
    await confirm.trigger('click')
    await flushPromises()
    expect(api.importLifecycleRoster).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('RUN_SYNTHETIC')
    wrapper.unmount()
  })

  it('邀请凭据只暂存在页面内存并进入加密下载流程', async () => {
    api.inviteSchoolStaff.mockResolvedValue(envelope({ invitation_ref: 'INV_SYNTHETIC', user_id: 'USER_STAFF', login_name: 'STAFF_SYNTHETIC', credential: 'secret-once', expires_at: '2026-10-25T00:00:00Z', status: 'ISSUED', delivery_channel: 'MANUAL_HANDOFF_REQUIRED' }))
    const wrapper = mount(AccountLifecycleWorkspace)
    await flushPromises()
    await wrapper.findAll('[role="tab"]')[2]!.trigger('click')
    const inputs = wrapper.findAll('input')
    await inputs[0]!.setValue('EMP_SYNTHETIC')
    await inputs[1]!.setValue('合成教师')
    await inputs[2]!.setValue('synthetic@example.test')
    await wrapper.get('input[type="password"]').setValue('synthetic-admin-password')
    await wrapper.get('input[type="checkbox"]').setValue(true)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(api.inviteSchoolStaff).toHaveBeenCalledWith(expect.objectContaining({ verified: true, delivery_channel: 'MANUAL' }))
    expect(api.reauthenticate).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('加密下载')
    expect(wrapper.text()).not.toContain('secret-once')
    wrapper.unmount()
  })

  it('管理员恢复队列只提供管理员审批，不提供教师核验操作', async () => {
    api.listRecoveryRequests.mockResolvedValue(envelope([{ ticket_ref: 'TICKET_SYNTHETIC', user_id: 'USER_STUDENT', username: 'STUDENT_SYNTHETIC', display_name: '合成学生', class_ref: 'CLASS_SYNTHETIC', role: 'student', status: 'TEACHER_VERIFIED', created_at: '2026-10-24T00:00:00Z' }]))
    api.approveRecoveryRequest.mockResolvedValue(envelope({ credential: 'synthetic-once', expires_at: '2026-10-25T00:00:00Z' }))
    const wrapper = mount(AccountLifecycleWorkspace)
    await flushPromises()
    await wrapper.findAll('[role="tab"]')[3]!.trigger('click')
    expect(wrapper.text()).toContain('教师核验后，由管理员审批')
    expect(wrapper.text()).not.toContain('教师验证')
    expect(wrapper.text()).toContain('管理员审批')
    await wrapper.get('input[type="password"]').setValue('synthetic-admin-password')
    await wrapper.get('input[required]').setValue('SYNTHETIC_APPROVAL')
    await wrapper.findAll('button').find((button) => button.text() === '管理员审批')!.trigger('click')
    await flushPromises()
    expect(api.reauthenticate).toHaveBeenCalledOnce()
    expect(api.approveRecoveryRequest).toHaveBeenCalledWith('TICKET_SYNTHETIC', 'SYNTHETIC_APPROVAL')
    expect(wrapper.text()).not.toContain('synthetic-once')
    wrapper.unmount()
  })

  it('发行初始凭据前要求管理员重新认证', async () => {
    api.issueLifecycleCredentials.mockResolvedValue(envelope({ credentials: [{ user_id: 'USER_STUDENT', login_name: 'STUDENT_SYNTHETIC', display_name: '合成学生', class_ref: 'CLASS_SYNTHETIC', credential: 'synthetic-once', expires_at: '2026-10-25T00:00:00Z' }] }))
    const wrapper = mount(AccountLifecycleWorkspace)
    await flushPromises()
    await wrapper.findAll('[role="tab"]')[4]!.trigger('click')
    await wrapper.get('input[type="checkbox"][aria-label="选择合成学生"]').setValue(true)
    await wrapper.get('input[type="password"]').setValue('synthetic-admin-password')
    await wrapper.findAll('button').find((button) => button.text() === '发行凭据')!.trigger('click')
    await flushPromises()
    expect(api.reauthenticate).toHaveBeenCalledOnce()
    expect(api.issueLifecycleCredentials).toHaveBeenCalledWith(['USER_STUDENT'])
    expect(wrapper.text()).not.toContain('synthetic-once')
    wrapper.unmount()
  })

  it('邀请记录仅展示元数据，重签后把一次性凭据送入加密下载页', async () => {
    api.listStaffInvitations.mockResolvedValue(envelope([{
      invitation_ref: 'INV_SYNTHETIC', user_id: 'USER_STAFF', login_name: 'STAFF_SYNTHETIC',
      display_name: '合成教师', employee_ref: 'EMP_SYNTHETIC', role: 'teacher', status: 'EXPIRED',
      delivery_channel: 'MANUAL', class_refs: ['CLASS_SYNTHETIC'],
      created_at: '2026-10-24T00:00:00Z', expires_at: '2026-10-24T01:00:00Z',
    }]))
    api.reissueStaffInvitation.mockResolvedValue(envelope({
      invitation_ref: 'INV_SYNTHETIC', user_id: 'USER_STAFF', login_name: 'STAFF_SYNTHETIC',
      status: 'ISSUED', delivery_channel: 'MANUAL_HANDOFF_REQUIRED', credential: 'secret-once',
      expires_at: '2026-10-25T00:00:00Z',
    }))
    const wrapper = mount(AccountLifecycleWorkspace)
    await flushPromises()
    await wrapper.findAll('[role="tab"]')[2]!.trigger('click')
    expect(wrapper.text()).toContain('合成教师')
    expect(wrapper.text()).toContain('已过期')
    expect(wrapper.text()).not.toContain('secret-once')
    await wrapper.get('input[autocomplete="current-password"]').setValue('synthetic-admin-password')
    await wrapper.findAll('button').find((button) => button.text() === '重签凭据')!.trigger('click')
    await flushPromises()
    expect(api.reauthenticate).toHaveBeenCalledOnce()
    expect(api.reissueStaffInvitation).toHaveBeenCalledWith('INV_SYNTHETIC', 'ADMINISTRATIVE_REISSUE')
    expect(wrapper.findAll('[role="tab"]')[4]!.attributes('aria-selected')).toBe('true')
    expect(wrapper.text()).toContain('凭据已暂存')
    expect(wrapper.find('.lifecycle__credential-records').exists()).toBe(true)
    expect(wrapper.find('.lifecycle__issues').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('secret-once')
    wrapper.unmount()
  })

  it('撤销未接受邀请前要求管理员重新认证', async () => {
    api.listStaffInvitations.mockResolvedValue(envelope([{
      invitation_ref: 'INV_SYNTHETIC', user_id: 'USER_STAFF', login_name: 'STAFF_SYNTHETIC',
      display_name: '合成教师', employee_ref: 'EMP_SYNTHETIC', role: 'teacher', status: 'ISSUED',
      delivery_channel: 'MANUAL', class_refs: ['CLASS_SYNTHETIC'],
      created_at: '2026-10-24T00:00:00Z', expires_at: '2026-10-25T00:00:00Z',
    }]))
    api.revokeStaffInvitation.mockResolvedValue(envelope({ status: 'REVOKED' }))
    const wrapper = mount(AccountLifecycleWorkspace)
    await flushPromises()
    await wrapper.findAll('[role="tab"]')[2]!.trigger('click')
    await wrapper.get('input[autocomplete="current-password"]').setValue('synthetic-admin-password')
    await wrapper.findAll('button').find((button) => button.text() === '撤销邀请')!.trigger('click')
    await flushPromises()
    expect(api.reauthenticate).toHaveBeenCalledOnce()
    expect(api.revokeStaffInvitation).toHaveBeenCalledWith('INV_SYNTHETIC', 'ADMINISTRATIVE_REVOCATION')
    expect(wrapper.text()).toContain('邀请已撤销')
    wrapper.unmount()
  })

  it('已接受教职工的密码恢复需先核验、重新认证并进入加密凭据交付', async () => {
    api.listStaffInvitations.mockResolvedValue(envelope([{
      invitation_ref: 'INV_ACTIVE', user_id: 'USER_TEACHER', login_name: 'STAFF_TEACHER',
      display_name: '合成教师', employee_ref: 'EMP_TEACHER', role: 'teacher', status: 'ACCEPTED',
      delivery_channel: 'MANUAL', class_refs: ['CLASS_SYNTHETIC'],
      created_at: '2026-10-24T00:00:00Z', expires_at: '2026-10-25T00:00:00Z',
    }]))
    api.issueStaffRecoveryCredential.mockResolvedValue(envelope({
      user_id: 'USER_TEACHER', login_name: 'STAFF_TEACHER', status: 'ISSUED',
      delivery_channel: 'MANUAL_HANDOFF_REQUIRED', credential: 'reset-secret-once',
      expires_at: '2026-10-25T00:15:00Z',
    }))
    const wrapper = mount(AccountLifecycleWorkspace, { global: { stubs: {
      DialogRoot: { props: { open: Boolean }, template: '<div v-if="open"><slot /></div>' },
      DialogPortal: { template: '<div><slot /></div>' },
      DialogOverlay: { template: '<div />' },
      DialogContent: { template: '<section role="dialog"><slot /></section>' },
      DialogTitle: { template: '<h2><slot /></h2>' },
      DialogDescription: { template: '<p><slot /></p>' },
      DialogClose: { template: '<div><slot /></div>' },
    } } })
    await flushPromises()
    await wrapper.findAll('[role="tab"]')[2]!.trigger('click')
    await wrapper.get('input[autocomplete="current-password"]').setValue('synthetic-admin-password')
    await wrapper.findAll('button').find((button) => button.text() === '重置凭据')!.trigger('click')
    const dialog = wrapper.get('[role="dialog"]')
    await dialog.get('input[type="checkbox"]').setValue(true)
    await dialog.findAll('button').find((button) => button.text() === '签发一次性凭据')!.trigger('click')
    await flushPromises()
    expect(api.reauthenticate).toHaveBeenCalledOnce()
    expect(api.issueStaffRecoveryCredential).toHaveBeenCalledWith('USER_TEACHER', {
      reason_code: 'CREDENTIAL_LOST',
      verification_method: 'IN_PERSON',
      identity_verified: true,
    })
    expect(wrapper.findAll('[role="tab"]')[4]!.attributes('aria-selected')).toBe('true')
    expect(wrapper.text()).toContain('加密下载')
    expect(wrapper.text()).not.toContain('reset-secret-once')
    wrapper.unmount()
  })

  it('账号状态列表支持 200 人搜索和分页', async () => {
    const members = Array.from({ length: 200 }, (_, index) => ({
      user_id: `USER_${String(index + 1).padStart(3, '0')}`,
      display_name: `合成学生${String(index + 1).padStart(3, '0')}`,
      role: 'student', account_status: 'ACTIVE', provisioning_status: null,
    }))
    api.getSchoolAdminDirectory.mockResolvedValue(envelope({
      school: { school_ref: 'SCHOOL_SYNTHETIC', display_name: '合成学校' },
      classes: [], members,
    }))
    api.updateSchoolAccountStatus.mockResolvedValue(envelope({ status: 'DISABLED' }))
    const wrapper = mount(AccountLifecycleWorkspace)
    await flushPromises()
    await wrapper.findAll('[role="tab"]')[5]!.trigger('click')
    expect(wrapper.findAll('.lifecycle__table-wrap tbody tr')).toHaveLength(25)
    expect(wrapper.find('select').exists()).toBe(false)
    await wrapper.get('input[type="search"]').setValue('USER_200')
    expect(wrapper.findAll('.lifecycle__table-wrap tbody tr')).toHaveLength(1)
    await wrapper.get('input[type="radio"]').setValue(true)
    await wrapper.findAll('input[autocomplete="off"]')[1]!.setValue('SYNTHETIC_ADMIN_ACTION')
    await wrapper.get('input[autocomplete="current-password"]').setValue('synthetic-admin-password')
    await wrapper.findAll('button').find((button) => button.text() === '停用账号')!.trigger('click')
    await flushPromises()
    expect(api.reauthenticate).toHaveBeenCalledOnce()
    expect(api.updateSchoolAccountStatus).toHaveBeenCalledWith('USER_200', 'DISABLED', 'SYNTHETIC_ADMIN_ACTION')
    wrapper.unmount()
  })
})
