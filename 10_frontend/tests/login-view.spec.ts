import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import router from '@/router'
import LoginView from '@/views/auth/LoginView.vue'

describe('M0 demo login hint', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    await router.push('/login')
  })

  it('directs the demo user to retain the prefilled synthetic account information', async () => {
    await router.isReady()
    const wrapper = mount(LoginView, { global: { plugins: [router] } })

    try {
      expect(wrapper.get('#password-hint').text()).toBe(
        '这是本地合成演示；保留预填账号信息即可登录。',
      )
    } finally {
      wrapper.unmount()
    }
  })
})
