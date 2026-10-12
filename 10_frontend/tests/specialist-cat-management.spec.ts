import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SpecialistCatManagement from '@/components/school/SpecialistCatManagement.vue'
import { useSessionStore } from '@/stores/session'

const catApi = vi.hoisted(() => ({ getCatalog: vi.fn(), runSimulation: vi.fn() }))
vi.mock('@/services/school-cat-management', () => ({ schoolCatManagement: catApi }))

import router from '@/router'
import { workspaceConfig } from '@/components/shell/navigation'

const catalog = {
  schema_version: 'synthetic_cat_management.v1' as const,
  engineering_only: true as const,
  psychological_interpretation_allowed: false as const,
  item_bank: {
    item_bank_id: 'BANK_SYNTHETIC_1', version: 'v0.1', instrument_id: 'instrument_demo',
    item_count: 18, dimension_count: 3, status: 'published' as const, validation: 'STRUCTURE_VALID' as const,
  },
  config: {
    config_version: 'config-demo-v1', model: 'GRM', estimator: 'EAP', selection_method: 'MAX_INFORMATION',
    min_items: 4, max_items: 12, se_threshold: 0.35, seed: 41,
  },
  simulation: { available: true as const, sample_sizes: [100, 1000] as (100 | 1000)[], fixed_seed: 41 },
}
const result = {
  schema_version: 'synthetic_cat_management.v1' as const,
  engineering_only: true as const,
  psychological_interpretation_allowed: false as const,
  item_bank_id: 'BANK_SYNTHETIC_1', item_bank_version: 'v0.1', config_version: 'config-demo-v1',
  n_examinees: 100 as 100 | 1000, seed: 41,
  metrics: { bias: 0.01, rmse: 0.24, mae: 0.19, mean_test_length: 8.2, median_test_length: 8, mean_se: 0.31 },
  stopping_reason_distribution: { SE_THRESHOLD_REACHED: 76, MAX_ITEMS_REACHED: 24 },
}

function prepare(role: 'teacher' | 'psychological_specialist' = 'psychological_specialist') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const session = useSessionStore()
  session.signIn({
    userId: 'USER_SYNTHETIC_SPECIALIST', role, subjectId: null,
    displayName: '合成账号', initials: '合', activeContext: { role, schoolRef: 'SCHOOL_SYNTHETIC_A' },
  })
  catApi.getCatalog.mockResolvedValue(catalog)
  catApi.runSimulation.mockResolvedValue(result)
  const wrapper = mount(SpecialistCatManagement, { global: { plugins: [pinia] } })
  return { wrapper, session }
}

beforeEach(() => vi.clearAllMocks())
afterEach(() => vi.restoreAllMocks())

describe('specialist CAT management workspace', () => {
  it('routes only the specialist navigation to the new CAT section', () => {
    const match = router.resolve('/specialist/cat')
    expect(match.name).toBe('specialist-workspace')
    expect(match.meta.roles).toEqual(['psychological_specialist'])
    expect(workspaceConfig.psychological_specialist?.items.map(({ to }) => to)).toContain('/specialist/cat')
    expect(workspaceConfig.student?.items.map(({ to }) => to)).not.toContain('/specialist/cat')
    expect(router.resolve('/specialist/not-a-section').matched).toHaveLength(1)
  })

  it('does not request CAT data for an ordinary teacher role', async () => {
    const { wrapper } = prepare('teacher')
    await flushPromises()
    expect(catApi.getCatalog).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('无法查看CAT配置')
    wrapper.unmount()
  })

  it('shows unavailable without fabricated data and reloads only after an explicit action', async () => {
    catApi.getCatalog.mockRejectedValueOnce(Object.assign(new Error('private backend detail'), { code: 'CAT_MANAGEMENT_UNAVAILABLE' }))
    const { wrapper } = prepare()
    await flushPromises()
    expect(catApi.getCatalog).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('题库信息暂不可用')
    expect(wrapper.text()).not.toContain('private backend detail')
    expect(wrapper.find('.cat-workbench').exists()).toBe(false)
    await wrapper.get('.cat-button--quiet').trigger('click')
    await flushPromises()
    expect(catApi.getCatalog).toHaveBeenCalledTimes(2)
    expect(wrapper.find('.cat-workbench').exists()).toBe(true)
    wrapper.unmount()
  })

  it('shows current read-only metadata and sends one explicit selected-size simulation', async () => {
    const { wrapper } = prepare()
    await flushPromises()
    expect(catApi.getCatalog).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('题库版本')
    expect(wrapper.text()).toContain('v0.1')
    expect(wrapper.text()).toContain('18 道')
    expect(wrapper.text()).toContain('心理学解释已关闭')
    expect(wrapper.text()).not.toContain('BANK_SYNTHETIC_1')

    await wrapper.get('input[value="1000"]').setValue()
    expect(wrapper.find('.cat-results').exists()).toBe(false)
    catApi.runSimulation.mockResolvedValueOnce({ ...result, n_examinees: 1000 })
    await wrapper.get('.cat-button--primary').trigger('click')
    await flushPromises()
    expect(catApi.runSimulation).toHaveBeenCalledOnce()
    expect(catApi.runSimulation).toHaveBeenCalledWith(catalog, 1000)
    expect(wrapper.text()).toContain('1,000')
    expect(wrapper.text()).toContain('均方根误差 RMSE')
    expect(wrapper.text()).toContain('停止原因汇总')
    expect(wrapper.text()).not.toContain('subject_id')
    expect(wrapper.text()).not.toContain('BANK_SYNTHETIC_1')
    wrapper.unmount()
  })

  it('compares only a user-requested repeat and never presents a cached result as a new run', async () => {
    const { wrapper } = prepare()
    await flushPromises()
    await wrapper.get('.cat-button--primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('偏差 Bias')
    expect(catApi.runSimulation).toHaveBeenCalledTimes(1)

    expect(wrapper.get('.cat-button--primary').text()).toContain('再次运行并对照')
    await wrapper.get('.cat-button--primary').trigger('click')
    await flushPromises()
    expect(catApi.runSimulation).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('本次与上一轮同样本量运行的聚合结果一致。')
    wrapper.unmount()
  })

  it('clears prior results when a permission error arrives and reports no successful output', async () => {
    const { wrapper } = prepare()
    await flushPromises()
    await wrapper.get('.cat-button--primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('偏差 Bias')

    catApi.runSimulation.mockRejectedValueOnce(Object.assign(new Error('private backend detail'), { code: 'FORBIDDEN' }))
    await wrapper.get('.cat-button--primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('无法查看CAT配置')
    expect(wrapper.text()).not.toContain('偏差 Bias')
    expect(wrapper.text()).not.toContain('private backend detail')
    wrapper.unmount()
  })

  it('clears data on school-context change and ignores a late simulation response', async () => {
    const { wrapper, session } = prepare()
    await flushPromises()
    let resolveRun!: (value: typeof result) => void
    catApi.runSimulation.mockReturnValueOnce(new Promise((resolve) => { resolveRun = resolve }))
    await wrapper.get('.cat-button--primary').trigger('click')
    expect(wrapper.text()).toContain('运行中，较大批次可能需要数分钟。')

    catApi.getCatalog.mockResolvedValueOnce({
      ...catalog,
      item_bank: { ...catalog.item_bank, version: 'v0.2' },
    })
    session.signIn({
      userId: 'USER_SYNTHETIC_SPECIALIST', role: 'psychological_specialist', subjectId: null,
      displayName: '合成账号', initials: '合', activeContext: { role: 'psychological_specialist', schoolRef: 'SCHOOL_SYNTHETIC_B' },
    })
    await flushPromises()
    expect(catApi.getCatalog).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('v0.2')
    expect(wrapper.find('.cat-results').exists()).toBe(false)

    resolveRun(result)
    await flushPromises()
    expect(wrapper.text()).not.toContain('偏差 Bias')
    wrapper.unmount()
  })

  it('clears successful metrics when an explicit repeat is rejected as busy without retrying', async () => {
    const { wrapper } = prepare()
    await flushPromises()
    await wrapper.get('.cat-button--primary').trigger('click')
    await flushPromises()
    catApi.runSimulation.mockRejectedValueOnce(Object.assign(new Error('busy'), { code: 'workflow_conflict' }))
    await wrapper.get('.cat-button--primary').trigger('click')
    await flushPromises()
    expect(catApi.runSimulation).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('模拟服务正忙')
    expect(wrapper.text()).not.toContain('偏差 Bias')
    wrapper.unmount()
  })
})
