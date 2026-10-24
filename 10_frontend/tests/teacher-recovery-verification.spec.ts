import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TeacherRecoveryVerificationView from '@/views/teacher/TeacherRecoveryVerificationView.vue'
import router from '@/router'

const api = vi.hoisted(() => ({ verifyRecoveryRequest: vi.fn() }))
vi.mock('@/services/mock-api', () => ({ frontendApi: api }))

describe('教师安全恢复核验', () => {
  beforeEach(() => api.verifyRecoveryRequest.mockReset())

  it('恢复核验路由仅授权普通教师角色', () => {
    expect(router.resolve('/teacher/recovery').meta.roles).toEqual(['teacher'])
  })

  it('仅提交学生提供的请求编号和教师填写的原因代码', async () => {
    api.verifyRecoveryRequest.mockResolvedValue({ data: { verified: true } })
    const wrapper = mount(TeacherRecoveryVerificationView)
    await wrapper.get('#recovery-ticket').setValue('TICKET_SYNTHETIC')
    await wrapper.get('#recovery-reason').setValue('SCHOOL_ID_CHECKED')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(api.verifyRecoveryRequest).toHaveBeenCalledWith('TICKET_SYNTHETIC', 'SCHOOL_ID_CHECKED')
    expect(wrapper.text()).toContain('已提交，请提醒学生等待管理员审批')
    wrapper.unmount()
  })

  it('字段缺失时保留在表单，不调用核验接口', async () => {
    const wrapper = mount(TeacherRecoveryVerificationView)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(api.verifyRecoveryRequest).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('请填写恢复请求编号和核验原因代码')
    wrapper.unmount()
  })
})
