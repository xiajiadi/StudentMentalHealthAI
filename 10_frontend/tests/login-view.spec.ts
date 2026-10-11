import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import router from '@/router'
import LoginView from '@/views/auth/LoginView.vue'

describe('登录页认证边界', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    await router.push('/login')
  })

  it('不预填账号密码，也不允许登录前选择角色', async () => {
    await router.isReady()
    const wrapper = mount(LoginView, { global: { plugins: [router] } })

    try {
      expect((wrapper.get('#account').element as unknown as { value: string }).value).toBe('')
      expect((wrapper.get('#password').element as unknown as { value: string }).value).toBe('')
      expect(wrapper.find('.role-picker').exists()).toBe(false)
      expect(wrapper.get('h1').text()).toBe('Enter your workspace')
      expect(wrapper.get('button[type="submit"]').text()).toBe('Continue')
    } finally {
      wrapper.unmount()
    }
  })
})
