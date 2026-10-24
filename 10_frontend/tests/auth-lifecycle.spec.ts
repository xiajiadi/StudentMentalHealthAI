import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import router from '@/router'
import LoginView from '@/views/auth/LoginView.vue'

const api = vi.hoisted(() => ({
  login: vi.fn(), getCurrentUser: vi.fn(), switchActiveContext: vi.fn(),
  completeFirstLogin: vi.fn(), createRecoveryRequest: vi.fn(), completePasswordReset: vi.fn(), acceptStaffInvitation: vi.fn(),
}))
vi.mock('@/services/mock-api', () => ({ frontendApi: api }))

describe('首次登录与安全恢复表单', () => {
  beforeEach(async () => {
    Object.values(api).forEach((mock) => mock.mockReset())
    api.getCurrentUser.mockResolvedValue({ data: null })
    setActivePinia(createPinia())
    await router.push('/login')
    await router.isReady()
  })

  it('首次登录调用真实 API 契约并要求两次新密码一致', async () => {
    api.completeFirstLogin.mockResolvedValue({ data: { completed: true } })
    const wrapper = mount(LoginView, { global: { plugins: [router] } })
    await wrapper.findAll('button').find((button) => button.text() === '首次登录')!.trigger('click')
    await wrapper.get('[aria-label="学校编号"]').setValue('SCHOOL_SYNTHETIC')
    await wrapper.get('[aria-label="账号"]').setValue('STUDENT_SYNTHETIC')
    await wrapper.get('[aria-label="一次性凭据"]').setValue('one-time')
    await wrapper.get('[aria-label="新密码"]').setValue('new-password')
    await wrapper.get('[aria-label="确认新密码"]').setValue('different-password')
    await wrapper.get('form').trigger('submit')
    expect(api.completeFirstLogin).not.toHaveBeenCalled()
    await wrapper.get('[aria-label="确认新密码"]').setValue('new-password')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(api.completeFirstLogin).toHaveBeenCalledWith({ school_ref: 'SCHOOL_SYNTHETIC', username: 'STUDENT_SYNTHETIC', credential: 'one-time', new_password: 'new-password', confirm_password: 'new-password' })
    expect(wrapper.text()).toContain('密码已更新，请返回登录')
    wrapper.unmount()
  })

  it('安全恢复表单提交学生信息和填写的原因代码', async () => {
    api.createRecoveryRequest.mockResolvedValue({ data: { ticket_ref: 'TICKET_SYNTHETIC' } })
    const wrapper = mount(LoginView, { global: { plugins: [router] } })
    await wrapper.findAll('button').find((button) => button.text() === '忘记密码')!.trigger('click')
    await wrapper.get('[aria-label="学校编号"]').setValue('SCHOOL_SYNTHETIC')
    await wrapper.get('[aria-label="账号"]').setValue('STUDENT_SYNTHETIC')
    await wrapper.get('[aria-label="班级编号"]').setValue('CLASS_SYNTHETIC')
    await wrapper.get('[aria-label="申请原因代码"]').setValue('SYNTHETIC_ACCESS_RECOVERY')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(api.createRecoveryRequest).toHaveBeenCalledWith({ school_ref: 'SCHOOL_SYNTHETIC', username: 'STUDENT_SYNTHETIC', class_ref: 'CLASS_SYNTHETIC', reason_code: 'SYNTHETIC_ACCESS_RECOVERY' })
    expect(wrapper.text()).toContain('申请已提交')
    wrapper.unmount()
  })

  it('教职工邀请接受只收集邀请编号和一次性凭据', async () => {
    api.acceptStaffInvitation.mockResolvedValue({ data: { accepted: true } })
    const wrapper = mount(LoginView, { global: { plugins: [router] } })
    await wrapper.findAll('button').find((button) => button.text() === '接受教职工邀请')!.trigger('click')
    expect(wrapper.find('[aria-label="学校编号"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="账号"]').exists()).toBe(false)
    await wrapper.get('[aria-label="邀请编号"]').setValue('INV_SYNTHETIC')
    await wrapper.get('[aria-label="一次性凭据"]').setValue('one-time')
    await wrapper.get('[aria-label="新密码"]').setValue('new-password')
    await wrapper.get('[aria-label="确认新密码"]').setValue('new-password')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(api.acceptStaffInvitation).toHaveBeenCalledWith({ invitation_ref: 'INV_SYNTHETIC', credential: 'one-time', new_password: 'new-password', confirm_password: 'new-password' })
    wrapper.unmount()
  })
})
