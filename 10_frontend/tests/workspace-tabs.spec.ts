import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import WorkspaceDetailSheet from '@/components/workspace/WorkspaceDetailSheet.vue'
import WorkspaceTabs from '@/components/workspace/WorkspaceTabs.vue'

const options = [
  { value: 'review', label: '专业复核' },
  { value: 'education', label: '教育内容' },
  { value: 'safety', label: '安全事项' },
]

describe('WorkspaceTabs', () => {
  it('exposes one selected tab and emits changes on activation', async () => {
    const wrapper = mount(WorkspaceTabs, {
      props: { id: 'workspace-test', label: '专业工作类型', modelValue: 'review', tabs: options },
      slots: { panel: '当前工作内容' },
    })
    await flushPromises()

    const tabs = wrapper.findAll('[role="tab"]')
    expect(tabs).toHaveLength(3)
    expect(tabs[0]?.attributes('aria-selected')).toBe('true')
    expect(tabs[0]?.attributes('aria-controls')).toBeTruthy()
    const panel = wrapper.get('[role="tabpanel"]')
    expect(panel.text()).toContain('当前工作内容')
    expect(panel.attributes('aria-labelledby')).toBe(tabs[0]?.attributes('id'))

    await tabs[1]?.trigger('mousedown', { button: 0, ctrlKey: false })
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['education'])
    await wrapper.setProps({ modelValue: 'education' })
    expect(wrapper.findAll('[aria-selected="true"]')).toHaveLength(1)
    expect(wrapper.findAll('[aria-selected="true"]')[0]?.text()).toBe('教育内容')
    wrapper.unmount()
  })

  it('exposes disabled tabs and preserves a single selected tab', async () => {
    const wrapper = mount(WorkspaceTabs, {
      props: {
        id: 'workspace-keys',
        label: '专业工作类型',
        modelValue: 'review',
        tabs: [options[0]!, { ...options[1]!, disabled: true }, options[2]!],
      },
    })

    const tabs = wrapper.findAll('[role="tab"]')
    expect(tabs[1]?.attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('[aria-selected="true"]')).toHaveLength(1)
    wrapper.unmount()
  })
})

describe('WorkspaceDetailSheet', () => {
  it('renders a labelled dialog and emits a close update from its accessible close button', async () => {
    const host = document.createElement('div')
    document.body.append(host)
    const wrapper = mount(WorkspaceDetailSheet, {
      attachTo: host,
      props: { open: true, title: '任务详情', description: '查看服务端返回的任务状态。' },
      slots: { default: '只读任务信息' },
    })

    try {
      await flushPromises()
      const dialog = document.body.querySelector('[role="dialog"]')
      expect(dialog?.textContent).toContain('任务详情')
      expect(dialog?.textContent).toContain('只读任务信息')
      const close = document.body.querySelector('[aria-label="关闭详情"]')
      expect(close).not.toBeNull()
      close?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await flushPromises()
      expect(wrapper.emitted('update:open')?.at(-1)).toEqual([false])
    } finally {
      wrapper.unmount()
      host.remove()
    }
  })
})
