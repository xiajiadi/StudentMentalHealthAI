import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import AppSelect from '@/components/app/AppSelect.vue'
import router from '@/router'
import LoginView from '@/views/auth/LoginView.vue'
import { frontendApi } from '@/services/mock-api'
import { useSessionStore } from '@/stores/session'
import type { LoginResult } from '@/api/client'

const contexts = [
  { role: 'student' as const, schoolRef: 'SYNTHETIC_ALPHA' },
  { role: 'teacher' as const, schoolRef: 'SYNTHETIC_BETA' },
]
const pending: LoginResult = { userId: 'USER_context', role: 'student', subjectId: null, displayName: '合成账号', initials: 'S', availableContexts: contexts, activeContext: null }
const response = (data: LoginResult) => ({ request_id: 'REQ_context', trace_id: 'TRACE_context', data })
const originalSwitch = frontendApi.switchActiveContext

beforeEach(async () => {
  setActivePinia(createPinia())
  await router.push('/login')
})
afterEach(() => {
  vi.restoreAllMocks()
  if (originalSwitch) frontendApi.switchActiveContext = originalSwitch
  else delete frontendApi.switchActiveContext
})

it('offers only server-authorized contexts after authentication, then enters the confirmed role', async () => {
  vi.spyOn(frontendApi, 'login').mockResolvedValue(response(pending))
  const choose = vi.fn().mockResolvedValue(response({ ...pending, role: 'teacher', activeContext: contexts[1]! }))
  frontendApi.switchActiveContext = choose
  const wrapper = mount(LoginView, { global: { plugins: [router] } })
  try {
    expect(wrapper.find('#school-context').exists()).toBe(false)
    await wrapper.get('#account').setValue('synthetic')
    await wrapper.get('#password').setValue('synthetic-only')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('#password').exists()).toBe(false)
    const select = wrapper.getComponent(AppSelect)
    expect(select.props('options')).toEqual([
      expect.objectContaining({ value: '0', label: expect.stringContaining('SYNTHETIC_ALPHA') }),
      expect.objectContaining({ value: '1', label: expect.stringContaining('SYNTHETIC_BETA') }),
    ])
    expect(useSessionStore().isAuthenticated).toBe(false)
    select.vm.$emit('update:modelValue', '1')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(choose).toHaveBeenCalledWith(contexts[1])
    expect(useSessionStore().role).toBe('teacher')
    await vi.waitFor(() => expect(router.currentRoute.value.path).toBe('/teacher/workspace'))
  } finally { wrapper.unmount() }
})

it('keeps selection pending when the returned active context is not the selected one', async () => {
  vi.spyOn(frontendApi, 'login').mockResolvedValue(response(pending))
  frontendApi.switchActiveContext = vi.fn().mockResolvedValue(response(pending))
  const wrapper = mount(LoginView, { global: { plugins: [router] } })
  try {
    await wrapper.get('#account').setValue('synthetic')
    await wrapper.get('#password').setValue('synthetic-only')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    wrapper.getComponent(AppSelect).vm.$emit('update:modelValue', '0')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(useSessionStore().isAuthenticated).toBe(false)
    expect(wrapper.get('[role="alert"]').text()).toContain('not been confirmed')
    expect(wrapper.find('#school-context').exists()).toBe(true)
  } finally { wrapper.unmount() }
})
