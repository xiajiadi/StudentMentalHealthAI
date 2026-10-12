import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SpecialistCatAssets from '@/components/school/SpecialistCatAssets.vue'
import { useSessionStore } from '@/stores/session'

const api = vi.hoisted(() => ({
  getTemplate: vi.fn(), listBanks: vi.fn(), listPlans: vi.fn(), getBank: vi.fn(), getBankVersion: vi.fn(),
  createBank: vi.fn(), createBankVersion: vi.fn(), updateBank: vi.fn(), getPlan: vi.fn(), getPlanVersion: vi.fn(),
  createPlan: vi.fn(), createPlanVersion: vi.fn(), updatePlan: vi.fn(),
}))
vi.mock('@/services/school-cat-assets', () => ({
  schoolCatAssets: api,
  newCatAssetIdempotencyKey: vi.fn(() => 'cat-asset-stable-test-key'),
}))

const bankDoc = () => ({
  item_bank_id: 'ITEMBANK_synthetic', version: 'demo.v1', instrument_id: 'CURRENT_SYNTHETIC_GRM',
  target_population: 'SYNTHETIC_STUDENT_DEMO', measurement_model: 'GRM', dimensions: ['demo_trait'],
  items: [{
    item_id: 'ITEM_synthetic_1', dimension: 'demo_trait', stem: '合成题目', response_type: 'likert',
    response_options: ['从不', '有时'], scoring: { 从不: 0, 有时: 1 }, model: 'GRM',
    parameters: { a: 1, thresholds: [0] }, source: 'synthetic_fixture', status: 'published',
  }], status: 'published',
  metadata: { synthetic: true, intended_use: 'engineering_test_only', psychological_interpretation_allowed: false },
})
const config = () => ({
  config_version: 'demo.v1', model: 'GRM', estimator: 'EAP', selection_method: 'MFI', min_items: 1, max_items: 1,
  se_threshold: 0.5, initial_theta: 0, prior_mean: 0, prior_sd: 1, optimization_interval: [-4, 4], seed: 7,
  exposure_control: 'none', content_balancing: 'none',
})
const flags = { engineering_only: true, psychological_interpretation_allowed: false }
const bankMeta = { bank_ref: 'CBANK_synthetic', display_name: '合成题库', status: 'ACTIVE', revision: 1, created_at: '2026-10-12T00:00:00Z', updated_at: '2026-10-12T00:00:00Z' }
const versionMeta = { version_ref: 'CBVER_synthetic', version_number: 1, created_at: '2026-10-12T00:00:00Z', item_count: 1, dimension_count: 1 }
const detail = () => ({ ...flags, ...bankMeta, versions: [versionMeta] })
const version = () => ({ ...flags, ...versionMeta, bank_document: bankDoc() })

function setup(role: 'teacher' | 'psychological_specialist' = 'psychological_specialist') {
  const pinia = createPinia()
  setActivePinia(pinia)
  const session = useSessionStore()
  session.signIn({ userId: 'USER_SYNTHETIC_SPECIALIST', role, subjectId: null, displayName: '合成账号', initials: '专', activeContext: { role, schoolRef: 'SCHOOL_SYNTHETIC_A' } })
  api.getTemplate.mockResolvedValue({ ...flags, bank_document: bankDoc(), config_document: config() })
  api.listBanks.mockResolvedValue({ ...flags, items: [], has_more: false })
  api.listPlans.mockResolvedValue({ ...flags, items: [], has_more: false })
  const wrapper = mount(SpecialistCatAssets, { props: { active: true }, global: { plugins: [pinia] } })
  return { wrapper, session }
}

function mountAssets(props?: { active?: boolean }) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const session = useSessionStore()
  session.signIn({ userId: 'USER_SYNTHETIC_SPECIALIST', role: 'psychological_specialist', subjectId: null, displayName: '合成账号', initials: '专', activeContext: { role: 'psychological_specialist', schoolRef: 'SCHOOL_SYNTHETIC_A' } })
  api.getTemplate.mockResolvedValue({ ...flags, bank_document: bankDoc(), config_document: config() })
  api.listBanks.mockResolvedValue({ ...flags, items: [], has_more: false })
  api.listPlans.mockResolvedValue({ ...flags, items: [], has_more: false })
  const wrapper = mount(SpecialistCatAssets, { ...(props ? { props } : {}), global: { plugins: [pinia] } })
  return { wrapper, session }
}

beforeEach(() => vi.clearAllMocks())
afterEach(() => vi.restoreAllMocks())

describe('specialist CAT asset editor', () => {
  it('loads the three asset resources on a default parent mount without explicit props', async () => {
    const { wrapper } = mountAssets()
    await flushPromises()
    expect(api.getTemplate).toHaveBeenCalledOnce()
    expect(api.listBanks).toHaveBeenCalledOnce()
    expect(api.listPlans).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('还没有题库')
    wrapper.unmount()
  })

  it('does not load when the parent explicitly disables the panel', async () => {
    const { wrapper } = mountAssets({ active: false })
    await flushPromises()
    expect(api.getTemplate).not.toHaveBeenCalled()
    expect(api.listBanks).not.toHaveBeenCalled()
    expect(api.listPlans).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('does not load content for a non-specialist role', async () => {
    const { wrapper } = setup('teacher')
    await flushPromises()
    expect(wrapper.text()).toContain('无法读取资产')
    expect(api.getTemplate).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('合成题目')
    wrapper.unmount()
  })

  it('starts from the real synthetic template and retries an uncertain create with the exact same key and body', async () => {
    const { wrapper } = setup()
    await flushPromises()
    await wrapper.get('.asset-list .asset-button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('题干')
    expect(wrapper.text()).toContain('GRM 区分参数 a')
    await wrapper.get('.asset-editor textarea').setValue('更新后的合成题干')
    api.createBank.mockRejectedValueOnce(new Error('private network response detail'))
      .mockResolvedValueOnce({ ...detail(), version_ref: 'CBVER_synthetic' })
    await wrapper.get('.asset-button--primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('保存结果尚未确认')
    expect(wrapper.text()).not.toContain('private network response detail')
    await wrapper.get('.asset-feedback--error button').trigger('click')
    api.listBanks.mockResolvedValue({ ...flags, items: [bankMeta], has_more: false })
    api.getBank.mockResolvedValue(detail())
    api.getBankVersion.mockResolvedValue(version())
    await flushPromises()
    expect(api.createBank).toHaveBeenCalledTimes(2)
    expect(api.createBank.mock.calls[0]).toEqual(api.createBank.mock.calls[1])
    expect(api.createBank.mock.calls[0]?.[2]).toBe('cat-asset-stable-test-key')
    expect(api.createBank.mock.calls[0]?.[1].items[0].stem).toBe('更新后的合成题干')
    wrapper.unmount()
  })

  it('clears cached asset content when active role changes', async () => {
    const { wrapper, session } = setup()
    await flushPromises()
    expect(wrapper.text()).toContain('还没有题库')
    session.signOut()
    await flushPromises()
    expect(wrapper.text()).not.toContain('合成题目')
    expect(wrapper.text()).toContain('无法读取资产')
    wrapper.unmount()
  })
})
