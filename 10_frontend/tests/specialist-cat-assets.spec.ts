import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SpecialistCatAssets from '@/components/school/SpecialistCatAssets.vue'
import { useSessionStore } from '@/stores/session'

const api = vi.hoisted(() => ({
  getTemplate: vi.fn(), listBanks: vi.fn(), listPlans: vi.fn(), getBank: vi.fn(), getBankVersion: vi.fn(),
  createBank: vi.fn(), createBankVersion: vi.fn(), updateBank: vi.fn(), getPlan: vi.fn(), getPlanVersion: vi.fn(),
  createPlan: vi.fn(), createPlanVersion: vi.fn(), updatePlan: vi.fn(),
  simulateSavedPlanVersion: vi.fn(),
  listActivations: vi.fn(), createActivation: vi.fn(), revokeActivation: vi.fn(),
}))
vi.mock('@/services/school-cat-assets', () => ({
  schoolCatAssets: api,
  latestCatAssetVersion: (versions: Array<{ version_number: number }>) => versions.reduce((latest, version) => version.version_number > latest.version_number ? version : latest),
  newCatAssetIdempotencyKey: vi.fn(() => 'cat-asset-stable-test-key'),
}))
vi.mock('@/services/school-cat-activations', () => ({
  schoolCatActivations: {
    list: api.listActivations,
    create: api.createActivation,
    revoke: api.revokeActivation,
  },
  newCatActivationIdempotencyKey: vi.fn(() => 'stable-activation-test-key'),
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
const planVersion = (number = 1) => ({
  ...flags,
  version_ref: `CPVER_synthetic_${number}`, version_number: number, created_at: `2026-10-12T00:0${number}:00Z`,
  bank_version_ref: 'CBVER_synthetic', config_document: config(),
})
const planMeta = { plan_ref: 'CPLAN_synthetic', display_name: '合成方案', status: 'ACTIVE', revision: 2, created_at: '2026-10-12T00:00:00Z', updated_at: '2026-10-12T00:02:00Z' }
const activationMeta = (overrides: Record<string, unknown> = {}) => ({
  activation_ref: 'CACT_12345678-1234-1234-1234-123456789012',
  plan_version_ref: 'CPVER_synthetic_1', bank_version_ref: 'CBVER_synthetic',
  plan_name: '合成方案', plan_version_number: 1, bank_name: '合成题库', bank_version_number: 1,
  status: 'ACTIVE' as const, revision: 1, created_at: '2026-10-12T00:00:00Z', revoked_at: null,
  ...overrides,
})
const activationPage = (items: ReturnType<typeof activationMeta>[] = [], has_more = false) => ({
  engineering_only: true as const, psychological_interpretation_allowed: false as const, items, has_more,
})
const planDetail = () => ({ ...flags, ...planMeta, versions: [1, 2].map((number) => ({ version_ref: `CPVER_synthetic_${number}`, version_number: number, created_at: `2026-10-12T00:0${number}:00Z`, bank_version_ref: 'CBVER_synthetic' })) })
const simulation = (number = 1, batch: 100 | 1000 = 100, bias = 0.1) => ({
  engineering_only: true, psychological_interpretation_allowed: false,
  plan_version_ref: `CPVER_synthetic_${number}`, bank_version_ref: 'CBVER_synthetic',
  item_bank_id: bankDoc().item_bank_id, item_bank_version: bankDoc().version,
  config_version: config().config_version, n_examinees: batch, seed: config().seed,
  metrics: { bias, rmse: 0.2, mae: 0.15, mean_test_length: 1, median_test_length: 1, mean_se: 0.3 },
  stopping_reason_distribution: { MAX_ITEMS_REACHED: batch },
})

function setup(role: 'teacher' | 'psychological_specialist' = 'psychological_specialist', withPlanAssets = false) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const session = useSessionStore()
  session.signIn({ userId: 'USER_SYNTHETIC_SPECIALIST', role, subjectId: null, displayName: '合成账号', initials: '专', activeContext: { role, schoolRef: 'SCHOOL_SYNTHETIC_A' } })
  api.getTemplate.mockResolvedValue({ ...flags, bank_document: bankDoc(), config_document: config() })
  api.listBanks.mockResolvedValue({ ...flags, items: [], has_more: false })
  api.listPlans.mockResolvedValue({ ...flags, items: [], has_more: false })
  api.listActivations.mockResolvedValue(activationPage())
  if (withPlanAssets) configurePlanAssets()
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
  api.listActivations.mockResolvedValue(activationPage())
  const wrapper = mount(SpecialistCatAssets, { ...(props ? { props } : {}), global: { plugins: [pinia] } })
  return { wrapper, session }
}

async function openPlanEditor(wrapper: ReturnType<typeof mountAssets>['wrapper']) {
  await wrapper.findAll('.asset-tabs button')[1]!.trigger('click')
  await flushPromises()
  await wrapper.find('.asset-list__items .asset-row').trigger('click')
  await flushPromises()
}

function configurePlanAssets() {
  api.listBanks.mockResolvedValue({ ...flags, items: [bankMeta], has_more: false })
  api.listPlans.mockResolvedValue({ ...flags, items: [planMeta], has_more: false })
  api.getBank.mockResolvedValue(detail())
  api.getBankVersion.mockResolvedValue(version())
  api.getPlan.mockResolvedValue(planDetail())
  api.getPlanVersion.mockImplementation((reference: string) => Promise.resolve(planVersion(Number(reference.slice(-1)))))
}

beforeEach(() => { vi.clearAllMocks(); api.simulateSavedPlanVersion.mockReset() })
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

  it('keeps asset tabs locked until the initial bank-version reads finish', async () => {
    let resolveBank!: (value: ReturnType<typeof detail>) => void
    const delayedBank = new Promise<ReturnType<typeof detail>>((resolve) => { resolveBank = resolve })
    api.getTemplate.mockResolvedValue({ ...flags, bank_document: bankDoc(), config_document: config() })
    api.listBanks.mockResolvedValue({ ...flags, items: [bankMeta], has_more: false })
    api.listPlans.mockResolvedValue({ ...flags, items: [planMeta], has_more: false })
    api.getBank.mockReturnValue(delayedBank)

    const pinia = createPinia()
    setActivePinia(pinia)
    const session = useSessionStore()
    session.signIn({ userId: 'USER_SYNTHETIC_SPECIALIST', role: 'psychological_specialist', subjectId: null, displayName: '合成账号', initials: '专', activeContext: { role: 'psychological_specialist', schoolRef: 'SCHOOL_SYNTHETIC_A' } })
    const wrapper = mount(SpecialistCatAssets, { props: { active: true }, global: { plugins: [pinia] } })

    try {
      await flushPromises()
      expect(wrapper.find('.asset-state').text()).toContain('正在读取本校资产')
      const plansTab = wrapper.findAll('.asset-tabs button')[1]!
      expect(plansTab.attributes('disabled')).toBeDefined()
      await plansTab.trigger('click')
      expect(plansTab.attributes('aria-pressed')).toBe('false')
      expect(api.getTemplate).toHaveBeenCalledOnce()
      expect(api.listBanks).toHaveBeenCalledOnce()
      expect(api.listPlans).toHaveBeenCalledOnce()

      resolveBank(detail())
      await flushPromises()
      expect(wrapper.find('.asset-state').exists()).toBe(false)
      expect(plansTab.attributes('disabled')).toBeUndefined()
      await plansTab.trigger('click')
      await flushPromises()
      expect(plansTab.attributes('aria-pressed')).toBe('true')
      expect(wrapper.find('.asset-list h2').text()).toBe('CAT 方案')
      expect(wrapper.find('.asset-list__items').text()).toContain(planMeta.display_name)
      expect(api.getBank).toHaveBeenCalledOnce()
    } finally {
      resolveBank(detail())
      wrapper.unmount()
    }
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

  it('does not treat the automatically loaded editor version as an explicit simulation selection', async () => {
    const { wrapper } = setup('psychological_specialist', true)
    await flushPromises()
    await openPlanEditor(wrapper)
    expect(wrapper.text()).toContain('请先选择方案历史版本')
    expect(wrapper.find('.asset-simulation .asset-button--primary').exists()).toBe(false)
    expect(api.simulateSavedPlanVersion).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('runs and compares only the explicitly selected saved version, not edited draft values', async () => {
    api.simulateSavedPlanVersion
      .mockResolvedValueOnce(simulation(2))
      .mockResolvedValueOnce(simulation(2))
    const { wrapper } = setup('psychological_specialist', true)
    await flushPromises()
    await openPlanEditor(wrapper)
    const history = wrapper.findAll('.asset-history__row')
    await history[1]!.trigger('click')
    await flushPromises()
    await wrapper.findAll('.asset-config-grid input')[1]!.setValue('9')
    expect(wrapper.text()).toContain('未保存的当前表单配置不会用于模拟')
    await wrapper.get('.asset-simulation .asset-button--primary').trigger('click')
    await flushPromises()
    expect(api.simulateSavedPlanVersion).toHaveBeenCalledWith(
      'CPVER_synthetic_2', 'CBVER_synthetic', bankDoc(), config(), 100,
    )
    expect(wrapper.text()).toContain('合成方案 v2')
    expect(wrapper.text()).toContain('本次汇总，100 个合成样本')

    await wrapper.get('.asset-simulation .asset-button--primary').trigger('click')
    await flushPromises()
    expect(api.simulateSavedPlanVersion).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('本次与上次运行的汇总结果相同')
    wrapper.unmount()
  })

  it('clears the displayed result when the batch changes and requires an explicit rerun', async () => {
    api.simulateSavedPlanVersion.mockResolvedValueOnce(simulation(1, 100))
      .mockResolvedValueOnce(simulation(1, 1000))
    const { wrapper } = setup('psychological_specialist', true)
    await flushPromises()
    await openPlanEditor(wrapper)
    await wrapper.find('.asset-history__row').trigger('click')
    await flushPromises()
    await wrapper.get('.asset-simulation .asset-button--primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('本次汇总，100 个合成样本')
    await wrapper.get('.asset-simulation__batch select').setValue('1000')
    expect(wrapper.text()).not.toContain('本次汇总，100 个合成样本')
    expect(api.simulateSavedPlanVersion).toHaveBeenCalledOnce()
    await wrapper.get('.asset-simulation .asset-button--primary').trigger('click')
    await flushPromises()
    expect(api.simulateSavedPlanVersion).toHaveBeenLastCalledWith(
      'CPVER_synthetic_1', 'CBVER_synthetic', bankDoc(), config(), 1000,
    )
    expect(wrapper.text()).not.toContain('本次与上次运行')
    wrapper.unmount()
  })

  it('keeps busy outcomes explicit and retries only after a manual click', async () => {
    api.simulateSavedPlanVersion.mockRejectedValueOnce(Object.assign(new Error('synthetic_cat_simulation_busy'), { code: 'WORKFLOW_CONFLICT' }))
      .mockResolvedValueOnce(simulation())
    const { wrapper } = setup('psychological_specialist', true)
    await flushPromises()
    await openPlanEditor(wrapper)
    await wrapper.find('.asset-history__row').trigger('click')
    await flushPromises()
    await wrapper.get('.asset-simulation .asset-button--primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('本次没有排队，请稍后手动重试')
    expect(api.simulateSavedPlanVersion).toHaveBeenCalledOnce()
    await wrapper.get('.asset-simulation .asset-button--primary').trigger('click')
    await flushPromises()
    expect(api.simulateSavedPlanVersion).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('本次汇总，100 个合成样本')
    wrapper.unmount()
  })

  it('ignores a late simulation response after a different saved version is selected', async () => {
    let finishRun!: (value: ReturnType<typeof simulation>) => void
    api.simulateSavedPlanVersion.mockImplementationOnce(() => new Promise((resolve) => { finishRun = resolve }))
    const { wrapper } = setup('psychological_specialist', true)
    await flushPromises()
    await openPlanEditor(wrapper)
    const history = wrapper.findAll('.asset-history__row')
    await history[1]!.trigger('click')
    await flushPromises()
    await wrapper.get('.asset-simulation .asset-button--primary').trigger('click')
    expect(wrapper.text()).toContain('运行中，较大批次可能需要几分钟')
    expect(wrapper.get('.asset-simulation .asset-button--primary').attributes('disabled')).toBeDefined()

    await history[0]!.trigger('click')
    await flushPromises()
    finishRun(simulation(2))
    await flushPromises()
    expect(wrapper.text()).not.toContain('本次汇总，100 个合成样本')
    expect(wrapper.text()).toContain('合成方案 v1')
    wrapper.unmount()
  })

  it('requires an explicit manual rerun after an unknown outcome', async () => {
    api.simulateSavedPlanVersion.mockRejectedValueOnce(Object.assign(new Error('network detail'), { code: 'NETWORK_UNAVAILABLE' }))
      .mockResolvedValueOnce(simulation())
    const { wrapper } = setup('psychological_specialist', true)
    await flushPromises()
    await openPlanEditor(wrapper)
    await wrapper.find('.asset-history__row').trigger('click')
    await flushPromises()
    await wrapper.get('.asset-simulation .asset-button--primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('本次结果尚未确认')
    expect(wrapper.text()).not.toContain('network detail')
    expect(api.simulateSavedPlanVersion).toHaveBeenCalledOnce()
    expect(wrapper.get('.asset-simulation .asset-button--primary').text()).toContain('手动重新运行')
    await wrapper.get('.asset-simulation .asset-button--primary').trigger('click')
    await flushPromises()
    expect(api.simulateSavedPlanVersion).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('本次汇总，100 个合成样本')
    wrapper.unmount()
  })

  it('activates only an explicitly selected saved version and retries an unknown write with the same key', async () => {
    const selected = activationMeta({ plan_version_ref: 'CPVER_synthetic_2', plan_version_number: 2 })
    api.listActivations.mockResolvedValueOnce(activationPage())
      .mockResolvedValueOnce(activationPage([selected]))
    api.createActivation.mockRejectedValueOnce(Object.assign(new Error('private network detail'), { code: 'NETWORK_UNAVAILABLE' }))
      .mockResolvedValueOnce(selected)
    const { wrapper } = setup('psychological_specialist', true)
    await flushPromises()
    await openPlanEditor(wrapper)
    await wrapper.findAll('.asset-history__row')[1]!.trigger('click')
    await flushPromises()
    expect(api.listActivations).toHaveBeenLastCalledWith({ skip: 0, limit: 30, planVersionRef: 'CPVER_synthetic_2' })
    await wrapper.get('.asset-activation').get('button.asset-button--primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('请求结果尚未确认')
    expect(wrapper.text()).not.toContain('private network detail')
    expect(api.createActivation).toHaveBeenCalledOnce()
    await wrapper.get('.asset-activation').get('button:last-child').trigger('click')
    await flushPromises()
    expect(api.createActivation).toHaveBeenCalledTimes(2)
    expect(api.createActivation.mock.calls[0]).toEqual(['CPVER_synthetic_2', 'stable-activation-test-key'])
    expect(api.createActivation.mock.calls[1]).toEqual(api.createActivation.mock.calls[0])
    expect(wrapper.text()).toContain('当前启用')
    expect(wrapper.text()).not.toContain(selected.activation_ref)
    wrapper.unmount()
  })

  it('does not blindly retry a revision conflict and requires a manual activation refresh', async () => {
    const active = activationMeta({ plan_version_ref: 'CPVER_synthetic_2', plan_version_number: 2 })
    api.listActivations.mockResolvedValueOnce(activationPage([active]))
      .mockResolvedValueOnce(activationPage([activationMeta({ ...active, revision: 2 })]))
    api.revokeActivation.mockRejectedValueOnce(Object.assign(new Error('revision conflict'), { code: 'WORKFLOW_CONFLICT' }))
    const { wrapper } = setup('psychological_specialist', true)
    await flushPromises()
    await openPlanEditor(wrapper)
    await wrapper.findAll('.asset-history__row')[1]!.trigger('click')
    await flushPromises()
    await wrapper.get('.asset-activation').get('button.asset-button--danger').trigger('click')
    await flushPromises()
    expect(api.revokeActivation).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('启用状态已变化')
    await wrapper.get('.asset-activation').get('button.asset-button--quiet').trigger('click')
    await flushPromises()
    expect(api.listActivations).toHaveBeenCalledTimes(2)
    expect(api.revokeActivation).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('drops a late activation history response after the specialist context ends', async () => {
    let finishRead!: (page: ReturnType<typeof activationPage>) => void
    api.listActivations.mockImplementationOnce(() => new Promise((resolve) => { finishRead = resolve }))
    const { wrapper, session } = setup('psychological_specialist', true)
    await flushPromises()
    await openPlanEditor(wrapper)
    await wrapper.find('.asset-history__row').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('正在读取该版本的启用记录')
    session.signOut()
    await flushPromises()
    finishRead(activationPage([activationMeta()]))
    await flushPromises()
    expect(wrapper.text()).toContain('无法读取资产')
    expect(wrapper.text()).not.toContain('当前启用')
    expect(wrapper.text()).not.toContain('合成方案 v1，合成题库 v1')
    wrapper.unmount()
  })

  it('clears the displayed simulation result when the specialist session ends', async () => {
    api.simulateSavedPlanVersion.mockResolvedValueOnce(simulation())
    const { wrapper, session } = setup('psychological_specialist', true)
    await flushPromises()
    await openPlanEditor(wrapper)
    await wrapper.find('.asset-history__row').trigger('click')
    await flushPromises()
    await wrapper.get('.asset-simulation .asset-button--primary').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('本次汇总，100 个合成样本')
    session.signOut()
    await flushPromises()
    expect(wrapper.text()).not.toContain('本次汇总，100 个合成样本')
    expect(wrapper.text()).toContain('无法读取资产')
    wrapper.unmount()
  })
})
