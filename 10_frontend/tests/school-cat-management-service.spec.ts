import { afterEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({ requestSchoolCatManagement: vi.fn() }))
vi.mock('@/services/real-api', () => ({
  RealApiError: class RealApiError extends Error {
    constructor(public code: string, message: string) { super(message) }
  },
  requestSchoolCatManagement: transport.requestSchoolCatManagement,
}))

import { SchoolCatManagementService } from '@/services/school-cat-management'

const envelope = (data: unknown) => ({ request_id: 'REQ_synthetic_cat', trace_id: 'TRACE_synthetic_cat', data })
const catalogDto = {
  schema_version: 'synthetic_cat_management.v1',
  engineering_only: true,
  psychological_interpretation_allowed: false,
  item_bank: {
    item_bank_id: 'BANK_SYNTHETIC_1', version: 'v0.1', instrument_id: 'instrument_demo',
    item_count: 18, dimension_count: 3, status: 'published', validation: 'STRUCTURE_VALID',
  },
  config: {
    config_version: 'config-demo-v1', model: 'GRM', estimator: 'EAP', selection_method: 'MAX_INFORMATION',
    min_items: 4, max_items: 12, se_threshold: 0.35, seed: 41,
  },
  simulation: { available: true, sample_sizes: [100, 1000], fixed_seed: 41 },
  private_path: 'must-not-be-returned',
}
const simulationDto = {
  schema_version: 'synthetic_cat_management.v1',
  engineering_only: true,
  psychological_interpretation_allowed: false,
  item_bank_id: 'BANK_SYNTHETIC_1', item_bank_version: 'v0.1', config_version: 'config-demo-v1',
  n_examinees: 100, seed: 41,
  metrics: { bias: 0.01, rmse: 0.24, mae: 0.19, mean_test_length: 8.2, median_test_length: 8, mean_se: 0.31 },
  stopping_reason_distribution: { SE_THRESHOLD_REACHED: 76, MAX_ITEMS_REACHED: 24 },
  results: [{ subject_id: 'must-not-be-returned' }],
}

afterEach(() => vi.clearAllMocks())

describe('school CAT management adapter', () => {
  it('reads the current catalog and returns only validated synthetic metadata', async () => {
    transport.requestSchoolCatManagement.mockResolvedValueOnce(envelope(catalogDto))
    const service = new SchoolCatManagementService()

    const catalog = await service.getCatalog()

    expect(transport.requestSchoolCatManagement).toHaveBeenCalledOnce()
    expect(transport.requestSchoolCatManagement).toHaveBeenCalledWith({
      method: 'GET', path: '/api/v1/school/cat-management/catalog',
    })
    expect(catalog.item_bank.version).toBe('v0.1')
    expect(catalog.config.seed).toBe(41)
    expect(catalog).not.toHaveProperty('private_path')
    expect(catalog).toMatchObject({ engineering_only: true, psychological_interpretation_allowed: false })
  })

  it.each([
    ['psychological flag enabled', { ...catalogDto, psychological_interpretation_allowed: true }],
    ['non-synthetic bank', { ...catalogDto, engineering_only: false }],
    ['missing sample size', { ...catalogDto, simulation: { ...catalogDto.simulation, sample_sizes: [100] } }],
    ['unavailable simulation', { ...catalogDto, simulation: { ...catalogDto.simulation, available: false } }],
    ['unknown status', { ...catalogDto, item_bank: { ...catalogDto.item_bank, status: 'unknown' } }],
  ])('fails closed for %s', async (_label, dto) => {
    transport.requestSchoolCatManagement.mockResolvedValueOnce(envelope(dto))
    await expect(new SchoolCatManagementService().getCatalog()).rejects.toMatchObject({
      code: 'CAT_MANAGEMENT_UNAVAILABLE',
    })
  })

  it('runs exactly one requested batch with no seed override and projects aggregate data only', async () => {
    transport.requestSchoolCatManagement.mockResolvedValueOnce(envelope(catalogDto))
      .mockResolvedValueOnce(envelope(simulationDto))
    const service = new SchoolCatManagementService()
    const catalog = await service.getCatalog()

    const simulation = await service.runSimulation(catalog, 100)

    expect(transport.requestSchoolCatManagement.mock.calls.map(([request]) => request)).toEqual([
      { method: 'GET', path: '/api/v1/school/cat-management/catalog' },
      { method: 'POST', path: '/api/v1/school/cat-management/simulations', body: { n_examinees: 100 } },
    ])
    expect(simulation).not.toHaveProperty('results')
    expect(simulation).toMatchObject({ n_examinees: 100, seed: 41, metrics: simulationDto.metrics })
    expect(transport.requestSchoolCatManagement).toHaveBeenCalledTimes(2)
  })

  it.each([
    ['infinite metric', { ...simulationDto, metrics: { ...simulationDto.metrics, rmse: Number.POSITIVE_INFINITY } }],
    ['negative error metric', { ...simulationDto, metrics: { ...simulationDto.metrics, rmse: -0.1 } }],
    ['unknown metric', { ...simulationDto, metrics: { ...simulationDto.metrics, private_metric: 1 } }],
    ['mismatched sample count', { ...simulationDto, stopping_reason_distribution: { SE_THRESHOLD_REACHED: 99 } }],
    ['unknown stopping reason', { ...simulationDto, stopping_reason_distribution: { PRIVATE_REASON: 100 } }],
    ['wrong seed', { ...simulationDto, seed: 99 }],
    ['wrong config', { ...simulationDto, config_version: 'other-config' }],
  ])('rejects %s in simulation output', async (_label, dto) => {
    transport.requestSchoolCatManagement.mockResolvedValueOnce(envelope(catalogDto))
      .mockResolvedValueOnce(envelope(dto))
    const service = new SchoolCatManagementService()
    const catalog = await service.getCatalog()
    await expect(service.runSimulation(catalog, 100)).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
    expect(transport.requestSchoolCatManagement).toHaveBeenCalledTimes(2)
  })
})
