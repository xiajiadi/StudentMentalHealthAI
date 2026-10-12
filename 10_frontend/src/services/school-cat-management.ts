import { RealApiError, requestSchoolCatManagement } from '@/services/real-api'

type UnknownRecord = Record<string, unknown>

export const CAT_SIMULATION_SAMPLE_SIZES = [100, 1000] as const
export type CatSimulationSampleSize = typeof CAT_SIMULATION_SAMPLE_SIZES[number]

export interface SchoolCatCatalog {
  schema_version: 'synthetic_cat_management.v1'
  engineering_only: true
  psychological_interpretation_allowed: false
  item_bank: {
    item_bank_id: string
    version: string
    instrument_id: string
    item_count: number
    dimension_count: number
    status: 'draft' | 'calibrating' | 'validated' | 'published' | 'deprecated'
    validation: 'STRUCTURE_VALID'
  }
  config: {
    config_version: string
    model: string
    estimator: string
    selection_method: string
    min_items: number
    max_items: number
    se_threshold: number
    seed: number
  }
  simulation: {
    available: true
    sample_sizes: CatSimulationSampleSize[]
    fixed_seed: number
  }
}

export interface SchoolCatSimulation {
  schema_version: 'synthetic_cat_management.v1'
  engineering_only: true
  psychological_interpretation_allowed: false
  item_bank_id: string
  item_bank_version: string
  config_version: string
  n_examinees: CatSimulationSampleSize
  seed: number
  metrics: {
    bias: number
    rmse: number
    mae: number
    mean_test_length: number
    median_test_length: number
    mean_se: number
  }
  stopping_reason_distribution: Partial<Record<CatStopReason, number>>
}

export type CatStopReason =
  | 'SE_THRESHOLD_REACHED'
  | 'MAX_ITEMS_REACHED'
  | 'ITEM_BANK_EXHAUSTED'
  | 'MANUAL_TERMINATION'
  | 'ERROR'
  | 'NOT_STOPPED'

const METRIC_KEYS = ['bias', 'rmse', 'mae', 'mean_test_length', 'median_test_length', 'mean_se'] as const
const STOP_REASONS: readonly CatStopReason[] = [
  'SE_THRESHOLD_REACHED', 'MAX_ITEMS_REACHED', 'ITEM_BANK_EXHAUSTED',
  'MANUAL_TERMINATION', 'ERROR', 'NOT_STOPPED',
]
const INVALID_RESPONSE = 'CAT 管理接口返回的数据格式无法识别。'

const record = (value: unknown): UnknownRecord => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new RealApiError('API_INVALID_RESPONSE', INVALID_RESPONSE)
  }
  return value as UnknownRecord
}

const text = (source: UnknownRecord, key: string): string => {
  const value = source[key]
  if (typeof value !== 'string' || !value.trim()) {
    throw new RealApiError('API_INVALID_RESPONSE', INVALID_RESPONSE)
  }
  return value
}

const integer = (source: UnknownRecord, key: string, minimum = 0): number => {
  const value = source[key]
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < minimum) {
    throw new RealApiError('API_INVALID_RESPONSE', INVALID_RESPONSE)
  }
  return value
}

const finite = (source: UnknownRecord, key: string): number => {
  const value = source[key]
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new RealApiError('API_INVALID_RESPONSE', INVALID_RESPONSE)
  }
  return value
}

const requireFlags = (source: UnknownRecord) => {
  if (source.schema_version !== 'synthetic_cat_management.v1'
    || source.engineering_only !== true
    || source.psychological_interpretation_allowed !== false) {
    throw new RealApiError('CAT_MANAGEMENT_UNAVAILABLE', '当前题库不满足合成工程模拟的使用条件。')
  }
}

const unwrap = async <T>(request: Parameters<typeof requestSchoolCatManagement>[0]): Promise<T> =>
  (await requestSchoolCatManagement<unknown>(request)).data as T

const mapCatalog = (value: unknown): SchoolCatCatalog => {
  const source = record(value)
  requireFlags(source)
  const bank = record(source.item_bank)
  const config = record(source.config)
  const simulation = record(source.simulation)
  const status = bank.status
  const sampleSizes = simulation.sample_sizes
  const seed = integer(config, 'seed')
  if (!['draft', 'calibrating', 'validated', 'published', 'deprecated'].includes(String(status))
    || bank.validation !== 'STRUCTURE_VALID'
    || simulation.available !== true
    || !Array.isArray(sampleSizes)
    || sampleSizes.length !== CAT_SIMULATION_SAMPLE_SIZES.length
    || sampleSizes[0] !== CAT_SIMULATION_SAMPLE_SIZES[0]
    || sampleSizes[1] !== CAT_SIMULATION_SAMPLE_SIZES[1]
    || integer(simulation, 'fixed_seed') !== seed
    || integer(bank, 'item_count', 1) < 1
    || integer(bank, 'dimension_count', 1) < 1) {
    throw new RealApiError('CAT_MANAGEMENT_UNAVAILABLE', '当前题库或配置暂不可用于工程模拟。')
  }
  const minItems = integer(config, 'min_items', 1)
  const maxItems = integer(config, 'max_items', 1)
  if (maxItems < minItems || maxItems > integer(bank, 'item_count', 1)) {
    throw new RealApiError('API_INVALID_RESPONSE', INVALID_RESPONSE)
  }
  return {
    schema_version: 'synthetic_cat_management.v1',
    engineering_only: true,
    psychological_interpretation_allowed: false,
    item_bank: {
      item_bank_id: text(bank, 'item_bank_id'),
      version: text(bank, 'version'),
      instrument_id: text(bank, 'instrument_id'),
      item_count: integer(bank, 'item_count', 1),
      dimension_count: integer(bank, 'dimension_count', 1),
      status: status as SchoolCatCatalog['item_bank']['status'],
      validation: 'STRUCTURE_VALID',
    },
    config: {
      config_version: text(config, 'config_version'),
      model: text(config, 'model'),
      estimator: text(config, 'estimator'),
      selection_method: text(config, 'selection_method'),
      min_items: minItems,
      max_items: maxItems,
      se_threshold: finite(config, 'se_threshold'),
      seed,
    },
    simulation: {
      available: true,
      sample_sizes: [...CAT_SIMULATION_SAMPLE_SIZES],
      fixed_seed: seed,
    },
  }
}

const mapSimulation = (
  value: unknown,
  catalog: SchoolCatCatalog,
  sampleSize: CatSimulationSampleSize,
): SchoolCatSimulation => {
  const source = record(value)
  requireFlags(source)
  const metricSource = record(source.metrics)
  const actualMetricKeys = Object.keys(metricSource).sort()
  if (actualMetricKeys.length !== METRIC_KEYS.length
    || actualMetricKeys.some((key, index) => key !== [...METRIC_KEYS].sort()[index])) {
    throw new RealApiError('API_INVALID_RESPONSE', INVALID_RESPONSE)
  }
  const metrics = Object.fromEntries(METRIC_KEYS.map((key) => {
    const value = finite(metricSource, key)
    if ((key !== 'bias' && value < 0)
      || ((key === 'mean_test_length' || key === 'median_test_length') && value === 0)) {
      throw new RealApiError('API_INVALID_RESPONSE', INVALID_RESPONSE)
    }
    return [key, value]
  })) as SchoolCatSimulation['metrics']
  const nExaminees = source.n_examinees
  const seed = integer(source, 'seed')
  const stoppingSource = record(source.stopping_reason_distribution)
  const stopping: Partial<Record<CatStopReason, number>> = {}
  for (const [reason, count] of Object.entries(stoppingSource)) {
    if (!STOP_REASONS.includes(reason as CatStopReason)
      || typeof count !== 'number' || !Number.isSafeInteger(count) || count < 0) {
      throw new RealApiError('API_INVALID_RESPONSE', INVALID_RESPONSE)
    }
    stopping[reason as CatStopReason] = count
  }
  if ((nExaminees !== 100 && nExaminees !== 1000)
    || nExaminees !== sampleSize
    || text(source, 'item_bank_id') !== catalog.item_bank.item_bank_id
    || text(source, 'item_bank_version') !== catalog.item_bank.version
    || text(source, 'config_version') !== catalog.config.config_version
    || seed !== catalog.config.seed
    || Object.keys(stopping).length === 0
    || Object.values(stopping).reduce((total, count) => total + (count ?? 0), 0) !== sampleSize) {
    throw new RealApiError('API_INVALID_RESPONSE', INVALID_RESPONSE)
  }
  return {
    schema_version: 'synthetic_cat_management.v1',
    engineering_only: true,
    psychological_interpretation_allowed: false,
    item_bank_id: catalog.item_bank.item_bank_id,
    item_bank_version: catalog.item_bank.version,
    config_version: catalog.config.config_version,
    n_examinees: sampleSize,
    seed,
    metrics,
    stopping_reason_distribution: stopping,
  }
}

export class SchoolCatManagementService {
  async getCatalog(): Promise<SchoolCatCatalog> {
    const value = await unwrap<unknown>({
      method: 'GET', path: '/api/v1/school/cat-management/catalog',
    })
    return mapCatalog(value)
  }

  async runSimulation(catalog: SchoolCatCatalog, sampleSize: CatSimulationSampleSize): Promise<SchoolCatSimulation> {
    if (!CAT_SIMULATION_SAMPLE_SIZES.includes(sampleSize)) {
      throw new RealApiError('VALIDATION_FAILED', '请选择支持的模拟样本量。')
    }
    const value = await unwrap<unknown>({
      method: 'POST', path: '/api/v1/school/cat-management/simulations',
      body: { n_examinees: sampleSize },
    })
    return mapSimulation(value, catalog, sampleSize)
  }
}

export const schoolCatManagement = new SchoolCatManagementService()
