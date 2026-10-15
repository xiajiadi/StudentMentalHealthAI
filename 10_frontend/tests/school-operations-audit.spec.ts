/* global AbortSignal */

import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

const auditApi = vi.hoisted(() => ({ list: vi.fn() }))
vi.mock('@/services/mock-api', () => ({
  frontendApi: { listSchoolOperationsAudit: auditApi.list },
}))

import AdminOperationsAudit from '@/components/school/AdminOperationsAudit.vue'

const page = (action: 'school_directory.rename_class' | 'school_tasks.task.published', hasMore = false) => ({
  data: {
    items: [{
      event_ref: action === 'school_directory.rename_class'
        ? '2d6e0c0f-233b-4d62-8f20-d7d0a2f187a3'
        : 'b77e9a73-afbc-4481-adf0-ea33df53e883',
      created_at: '2026-10-16T00:00:00Z',
      action,
      result: 'SUCCESS' as const,
      resource_category: action === 'school_directory.rename_class' ? 'class' as const : 'task' as const,
      record_count: null,
    }],
    offset: 0,
    limit: 25,
    has_more: hasMore,
  },
})

describe('AdminOperationsAudit', () => {
  it('paginates and filters through the read-only API', async () => {
    auditApi.list
      .mockResolvedValueOnce(page('school_directory.rename_class', true))
      .mockResolvedValueOnce({ data: { items: [], offset: 25, limit: 25, has_more: false } })
      .mockResolvedValueOnce(page('school_tasks.task.published'))
    const wrapper = mount(AdminOperationsAudit, { props: { scopeKey: 'school-a' } })
    await flushPromises()

    expect(wrapper.text()).toContain('调整班级名称')
    await wrapper.findAll('button').find((button) => button.text().includes('下一页'))!.trigger('click')
    await flushPromises()
    expect(auditApi.list).toHaveBeenNthCalledWith(2, {
      offset: 25, limit: 25, category: null, signal: expect.any(AbortSignal),
    })
    await wrapper.find('select').setValue('task')
    await flushPromises()
    expect(auditApi.list).toHaveBeenNthCalledWith(3, {
      offset: 0, limit: 25, category: 'task', signal: expect.any(AbortSignal),
    })
    expect(wrapper.text()).toContain('发布测评任务')
    wrapper.unmount()
  })

  it('clears prior-scope rows and reloads when school identity changes', async () => {
    let resolveNext: ((value: ReturnType<typeof page>) => void) | undefined
    auditApi.list
      .mockResolvedValueOnce(page('school_directory.rename_class'))
      .mockReturnValueOnce(new Promise((resolve) => { resolveNext = resolve }))
    const wrapper = mount(AdminOperationsAudit, { props: { scopeKey: 'school-a|admin-a' } })
    await flushPromises()
    expect(wrapper.text()).toContain('调整班级名称')

    await wrapper.setProps({ scopeKey: 'school-b|admin-b' })
    expect(wrapper.text()).not.toContain('调整班级名称')
    expect(wrapper.text()).toContain('正在读取本校运营记录')
    resolveNext?.(page('school_tasks.task.published'))
    await flushPromises()
    expect(wrapper.text()).toContain('发布测评任务')
    wrapper.unmount()
  })
})
