import { afterEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ requestSchoolCatAssets: vi.fn(), requestSchoolCatSavedSimulation: vi.fn() }))
vi.mock('@/services/real-api', () => ({
  RealApiError: class RealApiError extends Error {
    constructor(public code: string, message: string, public retryable = false) { super(message) }
  },
  requestSchoolCatAssets: transport.requestSchoolCatAssets,
  requestSchoolCatSavedSimulation: transport.requestSchoolCatSavedSimulation,
}))

import {
  SchoolCatAssetsService,
  catAssetReferencePatterns,
  latestCatAssetVersion,
  newCatAssetIdempotencyKey,
} from '@/services/school-cat-assets'

const envelope = (data: unknown) => ({ request_id: 'REQ_synthetic_assets', trace_id: 'TRACE_synthetic_assets', data })
const item = (index: number) => ({
  item_id: `ITEM_demo_${String(index).padStart(3, '0')}`,
  dimension: 'demo_trait',
  stem: `工程演示题 ${index}`,
  response_type: 'likert',
  response_options: ['never', 'rarely', 'sometimes', 'often', 'always'],
  scoring: { never: 0, rarely: 1, sometimes: 2, often: 3, always: 4 },
  model: 'GRM',
  parameters: { a: 1, thresholds: [-2, -1, 0, 1] },
  source: 'synthetic_engineering_fixture',
  status: 'published',
})
const bankDocument = () => ({
  item_bank_id: 'ITEMBANK_demo_cat', version: 'demo.v1', instrument_id: 'CURRENT_SYNTHETIC_GRM',
  target_population: 'SYNTHETIC_STUDENT_DEMO', measurement_model: 'GRM', dimensions: ['demo_trait'],
  items: Array.from({ length: 9 }, (_, index) => item(index + 1)), status: 'published',
  metadata: {
    instrument_version: 'synthetic_item_bank.v1 / demo.v1', synthetic: true,
    intended_use: 'engineering_test_only', psychological_interpretation_allowed: false,
    notice: 'NOT FOR PSYCHOLOGICAL INTERPRETATION; DEMO / ENGINEERING USE ONLY',
    psychometric_status: 'PENDING_PSYCHOMETRIC_CONFIRMATION',
  },
})
const configDocument = () => ({
  config_version: 'demo.cat.v1', model: 'GRM', estimator: 'EAP', selection_method: 'MFI',
  min_items: 3, max_items: 8, se_threshold: 0.55, initial_theta: 0, prior_mean: 0, prior_sd: 1,
  optimization_interval: [-4, 4], seed: 20260904, exposure_control: 'none', content_balancing: 'none',
})
const flags = { engineering_only: true, psychological_interpretation_allowed: false }
const bankMeta = {
  bank_ref: 'CBANK_SYNTHETIC_1', display_name: '合成题库 A', status: 'ACTIVE', revision: 2,
  created_at: '2026-10-12T00:00:00Z', updated_at: '2026-10-12T00:10:00Z',
}
const bankVersions = [
  { version_ref: 'CBVER_SYNTHETIC_1', version_number: 1, created_at: '2026-10-12T00:00:00Z', item_count: 9, dimension_count: 1 },
  { version_ref: 'CBVER_SYNTHETIC_2', version_number: 2, created_at: '2026-10-12T00:10:00Z', item_count: 9, dimension_count: 1 },
]
const bankDetail = () => ({ ...flags, bank: { ...bankMeta, versions: bankVersions } })
const bankVersion = () => ({ ...flags, version: bankVersions[1], bank_document: bankDocument() })
const planMeta = {
  plan_ref: 'CPLAN_SYNTHETIC_1', display_name: '合成方案 A', status: 'ACTIVE', revision: 1,
  created_at: '2026-10-12T00:00:00Z', updated_at: '2026-10-12T00:00:00Z',
}
const planVersions = [
  { version_ref: 'CPVER_SYNTHETIC_1', version_number: 1, created_at: '2026-10-12T00:00:00Z', bank_version_ref: 'CBVER_SYNTHETIC_2' },
]
const planDetail = () => ({ ...flags, plan: { ...planMeta, versions: planVersions.map(({ version_ref, version_number, created_at }) => ({ version_ref, version_number, created_at })) } })
const planVersion = () => ({ ...flags, version: { version_ref: planVersions[0]!.version_ref, version_number: planVersions[0]!.version_number, created_at: planVersions[0]!.created_at }, bank_version_ref: planVersions[0]!.bank_version_ref, config_document: configDocument() })
const template = () => ({ ...flags, bank_document: bankDocument(), config_document: configDocument() })
const simulation = (overrides: Record<string, unknown> = {}) => ({
  ...flags,
  plan_version_ref: 'CPVER_SYNTHETIC_1', bank_version_ref: 'CBVER_SYNTHETIC_2',
  item_bank_id: bankDocument().item_bank_id, item_bank_version: bankDocument().version,
  config_version: configDocument().config_version, n_examinees: 100, seed: configDocument().seed,
  metrics: { bias: 0.1, rmse: 0.2, mae: 0.15, mean_test_length: 6, median_test_length: 6, mean_se: 0.3 },
  stopping_reason_distribution: { MAX_ITEMS_REACHED: 100 },
  ...overrides,
})

afterEach(() => vi.clearAllMocks())

describe('school CAT assets transport adapter', () => {
  it('reads the real template and list metadata without exposing false psychology approval', async () => {
    transport.requestSchoolCatAssets
      .mockResolvedValueOnce(envelope(template()))
      .mockResolvedValueOnce(envelope({ ...flags, items: [bankMeta], has_more: true }))
      .mockResolvedValueOnce(envelope({ ...flags, items: [planMeta], has_more: false }))
    const service = new SchoolCatAssetsService()

    const currentTemplate = await service.getTemplate()
    const banks = await service.listBanks()
    const plans = await service.listPlans(30, 30)

    expect(currentTemplate.bank_document.items).toHaveLength(9)
    expect(currentTemplate.config_document.seed).toBe(20260904)
    expect(banks.items).toEqual([bankMeta])
    expect(plans.items).toEqual([planMeta])
    expect(transport.requestSchoolCatAssets.mock.calls.map(([input]) => input)).toEqual([
      { method: 'GET', path: '/api/v1/school/cat-assets/template' },
      { method: 'GET', path: '/api/v1/school/cat-assets/banks', query: { limit: 30, skip: 0 } },
      { method: 'GET', path: '/api/v1/school/cat-assets/plans', query: { limit: 30, skip: 30 } },
    ])
  })

  it.each([
    ['interpretation enabled', { ...template(), psychological_interpretation_allowed: true }, 'CAT_ASSET_UNAVAILABLE'],
    ['non-synthetic bank', { ...template(), bank_document: { ...bankDocument(), metadata: { synthetic: false } } }, 'CAT_ASSET_UNAVAILABLE'],
    ['duplicate item id', { ...template(), bank_document: { ...bankDocument(), items: [...bankDocument().items.slice(0, 8), bankDocument().items[0]] } }, 'API_INVALID_RESPONSE'],
    ['misaligned scoring', { ...template(), bank_document: { ...bankDocument(), items: [{ ...item(1), scoring: { never: 0 } }, ...bankDocument().items.slice(1)] } }, 'API_INVALID_RESPONSE'],
    ['non-increasing thresholds', { ...template(), bank_document: { ...bankDocument(), items: [{ ...item(1), parameters: { a: 1, thresholds: [-1, 0, 0, 1] } }, ...bankDocument().items.slice(1)] } }, 'API_INVALID_RESPONSE'],
    ['oversized configuration', { ...template(), config_document: { ...configDocument(), max_items: 10 } }, 'API_INVALID_RESPONSE'],
  ])('fails closed for %s template state', async (_label, data, expectedCode) => {
    transport.requestSchoolCatAssets.mockResolvedValueOnce(envelope(data))
    await expect(new SchoolCatAssetsService().getTemplate()).rejects.toMatchObject({ code: expectedCode })
  })

  it('creates and versions banks using stable caller keys and expected revisions', async () => {
    transport.requestSchoolCatAssets
      .mockResolvedValueOnce(envelope({ ...bankDetail(), revision: 1, version_ref: 'CBVER_SYNTHETIC_1' }))
      .mockResolvedValueOnce(envelope({ ...bankDetail(), version_ref: 'CBVER_SYNTHETIC_2' }))
      .mockResolvedValueOnce(envelope({ ...flags, bank: { ...bankMeta, revision: 3, versions: bankVersions } }))
    const service = new SchoolCatAssetsService()

    await service.createBank('新建合成题库', bankDocument(), 'stable-create-bank-key')
    await service.createBankVersion('CBANK_SYNTHETIC_1', 1, bankDocument(), 'stable-bank-version-key')
    await service.updateBank('CBANK_SYNTHETIC_1', 2, { display_name: '重命名题库' }, 'stable-bank-rename-key')

    expect(transport.requestSchoolCatAssets.mock.calls.map(([input]) => input)).toEqual([
      { method: 'POST', path: '/api/v1/school/cat-assets/banks', body: { display_name: '新建合成题库', bank_document: bankDocument() }, idempotencyKey: 'stable-create-bank-key' },
      { method: 'POST', path: '/api/v1/school/cat-assets/banks/CBANK_SYNTHETIC_1/versions', body: { expected_revision: 1, bank_document: bankDocument() }, idempotencyKey: 'stable-bank-version-key' },
      { method: 'PATCH', path: '/api/v1/school/cat-assets/banks/CBANK_SYNTHETIC_1', body: { expected_revision: 2, display_name: '重命名题库' }, idempotencyKey: 'stable-bank-rename-key' },
    ])
  })

  it('creates exact bank-version-linked plans and edits config in a new version', async () => {
    transport.requestSchoolCatAssets
      .mockResolvedValueOnce(envelope({ ...planDetail(), version_ref: 'CPVER_SYNTHETIC_1' }))
      .mockResolvedValueOnce(envelope({ ...planDetail(), revision: 2, version_ref: 'CPVER_SYNTHETIC_2' }))
      .mockResolvedValueOnce(envelope({ ...flags, plan: { ...planMeta, revision: 3, versions: planVersions } }))
    const service = new SchoolCatAssetsService()

    await service.createPlan('新建合成方案', 'CBVER_SYNTHETIC_2', bankDocument(), configDocument(), 'stable-plan-create-key')
    await service.createPlanVersion('CPLAN_SYNTHETIC_1', 1, 'CBVER_SYNTHETIC_2', bankDocument(), configDocument(), 'stable-plan-version-key')
    await service.updatePlan('CPLAN_SYNTHETIC_1', 2, { status: 'ARCHIVED' }, 'stable-plan-archive-key')

    expect(transport.requestSchoolCatAssets.mock.calls.map(([input]) => input)).toEqual([
      { method: 'POST', path: '/api/v1/school/cat-assets/plans', body: { display_name: '新建合成方案', bank_version_ref: 'CBVER_SYNTHETIC_2', config_document: configDocument() }, idempotencyKey: 'stable-plan-create-key' },
      { method: 'POST', path: '/api/v1/school/cat-assets/plans/CPLAN_SYNTHETIC_1/versions', body: { expected_revision: 1, bank_version_ref: 'CBVER_SYNTHETIC_2', config_document: configDocument() }, idempotencyKey: 'stable-plan-version-key' },
      { method: 'PATCH', path: '/api/v1/school/cat-assets/plans/CPLAN_SYNTHETIC_1', body: { expected_revision: 2, status: 'ARCHIVED' }, idempotencyKey: 'stable-plan-archive-key' },
    ])
  })

  it('reads immutable history and rejects unsafe refs before transport', async () => {
    transport.requestSchoolCatAssets
      .mockResolvedValueOnce(envelope(bankDetail()))
      .mockResolvedValueOnce(envelope(bankVersion()))
      .mockResolvedValueOnce(envelope(planDetail()))
      .mockResolvedValueOnce(envelope(planVersion()))
    const service = new SchoolCatAssetsService()
    await expect(service.getBank('CBANK_SYNTHETIC_1')).resolves.toMatchObject({ versions: [{ version_number: 1 }, { version_number: 2 }] })
    await expect(service.getBankVersion('CBVER_SYNTHETIC_2')).resolves.toMatchObject({ bank_document: { items: expect.arrayContaining([expect.objectContaining({ item_id: 'ITEM_demo_001' })]) } })
    await expect(service.getPlan('CPLAN_SYNTHETIC_1')).resolves.toMatchObject({ versions: [{ version_number: 1 }] })
    await expect(service.getPlanVersion('CPVER_SYNTHETIC_1')).resolves.toMatchObject({ config_document: { seed: 20260904 } })
    await expect(service.getBank('../private')).rejects.toMatchObject({ code: 'VALIDATION_FAILED' })
    expect(transport.requestSchoolCatAssets).toHaveBeenCalledTimes(4)
    expect(catAssetReferencePatterns.bank.test('CBANK_SYNTHETIC_1')).toBe(true)
  })

  it('runs only a selected immutable saved plan version with the chosen supported batch', async () => {
    transport.requestSchoolCatSavedSimulation.mockResolvedValueOnce(envelope(simulation()))
    const result = await new SchoolCatAssetsService().simulateSavedPlanVersion(
      'CPVER_SYNTHETIC_1', 'CBVER_SYNTHETIC_2', bankDocument(), configDocument(), 100,
    )
    expect(result).toMatchObject({
      engineering_only: true, psychological_interpretation_allowed: false,
      plan_version_ref: 'CPVER_SYNTHETIC_1', bank_version_ref: 'CBVER_SYNTHETIC_2',
      n_examinees: 100, seed: configDocument().seed, metrics: { rmse: 0.2 },
    })
    expect(transport.requestSchoolCatSavedSimulation).toHaveBeenCalledOnce()
    expect(transport.requestSchoolCatSavedSimulation).toHaveBeenCalledWith({
      path: '/api/v1/school/cat-assets/plan-versions/CPVER_SYNTHETIC_1/simulations',
      body: { n_examinees: 100 },
    })
  })

  it('accepts the supported 1000 synthetic sample batch when the response count matches', async () => {
    transport.requestSchoolCatSavedSimulation.mockResolvedValueOnce(envelope(simulation({
      n_examinees: 1000, stopping_reason_distribution: { MAX_ITEMS_REACHED: 1000 },
    })))
    await expect(new SchoolCatAssetsService().simulateSavedPlanVersion(
      'CPVER_SYNTHETIC_1', 'CBVER_SYNTHETIC_2', bankDocument(), configDocument(), 1000,
    )).resolves.toMatchObject({ n_examinees: 1000 })
    expect(transport.requestSchoolCatSavedSimulation).toHaveBeenCalledWith(expect.objectContaining({ body: { n_examinees: 1000 } }))
  })

  it.each([
    ['mismatched saved plan ref', { plan_version_ref: 'CPVER_SYNTHETIC_2' }],
    ['mismatched bank ref', { bank_version_ref: 'CBVER_SYNTHETIC_1' }],
    ['mismatched seed', { seed: 99 }],
    ['unknown metric', { metrics: { bias: 0, rmse: 0, mae: 0, mean_test_length: 5, median_test_length: 5, mean_se: 0, accuracy: 1 } }],
    ['non-finite metric', { metrics: { bias: 0, rmse: Number.POSITIVE_INFINITY, mae: 0, mean_test_length: 5, median_test_length: 5, mean_se: 0 } }],
    ['test length beyond the saved bank', { metrics: { bias: 0, rmse: 0, mae: 0, mean_test_length: 10, median_test_length: 5, mean_se: 0 } }],
    ['incomplete stopping counts', { stopping_reason_distribution: { MAX_ITEMS_REACHED: 99 } }],
  ])('rejects %s from saved simulation response', async (_label, changes) => {
    transport.requestSchoolCatSavedSimulation.mockResolvedValueOnce(envelope(simulation(changes)))
    await expect(new SchoolCatAssetsService().simulateSavedPlanVersion(
      'CPVER_SYNTHETIC_1', 'CBVER_SYNTHETIC_2', bankDocument(), configDocument(), 100,
    )).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })

  it('rejects unsupported batches and unsafe saved refs before transport', async () => {
    const service = new SchoolCatAssetsService()
    await expect(service.simulateSavedPlanVersion(
      'CPVER_SYNTHETIC_1', 'CBVER_SYNTHETIC_2', bankDocument(), configDocument(), 101 as 100,
    )).rejects.toMatchObject({ code: 'VALIDATION_FAILED' })
    await expect(service.simulateSavedPlanVersion(
      'CPVER_bad/ref', 'CBVER_SYNTHETIC_2', bankDocument(), configDocument(), 100,
    )).rejects.toMatchObject({ code: 'VALIDATION_FAILED' })
    expect(transport.requestSchoolCatSavedSimulation).not.toHaveBeenCalled()
  })

  it('generates a non-reused idempotency key for each user-created operation', () => {
    const first = newCatAssetIdempotencyKey()
    const second = newCatAssetIdempotencyKey()
    expect(first).toMatch(/^cat-asset-[0-9a-f-]{36}$/i)
    expect(second).not.toBe(first)
  })

  it.each([
    { order: [1, 2, 3] },
    { order: [3, 2, 1] },
  ])('selects greatest bank and plan versions independent of order %j', (orderedNumbers) => {
    const bankOrder = orderedNumbers.order.map((version_number) => ({
      version_ref: `CBVER_SYNTHETIC_${version_number}`, version_number, created_at: '2026-10-12T00:00:00Z', item_count: 9, dimension_count: 1,
    }))
    const planOrder = orderedNumbers.order.map((version_number) => ({
      version_ref: `CPVER_SYNTHETIC_${version_number}`, version_number, created_at: '2026-10-12T00:00:00Z',
    }))
    expect(latestCatAssetVersion(bankOrder)?.version_ref).toBe('CBVER_SYNTHETIC_3')
    expect(latestCatAssetVersion(planOrder)?.version_ref).toBe('CPVER_SYNTHETIC_3')
  })
})
