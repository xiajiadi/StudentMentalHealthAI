import { DOMWrapper, type VueWrapper } from '@vue/test-utils'
import { expect } from 'vitest'

export async function openAppSelect(wrapper: VueWrapper, selector: string) {
  const trigger = wrapper.get(selector)
  expect(trigger.attributes('role')).toBe('combobox')
  expect(trigger.attributes('disabled')).toBeUndefined()
  await trigger.trigger('keydown', { key: 'Enter' })
  const menuId = trigger.attributes('aria-controls')
  expect(menuId).toBeTruthy()
  const menu = document.getElementById(menuId!)
  expect(menu).not.toBeNull()
  return new DOMWrapper(menu!)
}

export async function chooseAppSelect(wrapper: VueWrapper, selector: string, label: string) {
  const menu = await openAppSelect(wrapper, selector)
  const option = menu.findAll('[role="option"]').find((item) => item.text() === label)
  expect(option, `Option ${label} is available`).toBeDefined()
  expect(option!.attributes('aria-disabled')).toBeUndefined()
  await option!.trigger('keydown', { key: 'Enter' })
}
