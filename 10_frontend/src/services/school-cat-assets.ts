import { RealApiError, requestSchoolCatAssets } from '@/services/real-api'

type UnknownRecord = Record<string, unknown>
type JsonRecord = { [key: string]: unknown }
type AssetStatus = 'ACTIVE' | 'ARCHIVED'

export interface CatAssetItemDocument extends JsonRecord {
  item_id: string
  dimension: string
  stem: string
  response_type: string
  response_options: string[]
  scoring: Record<string, number>
  model: 'GRM'
  parameters: { a: number; thresholds: number[] }
  source: string
  status: 'published' | 'demo' | 'synthetic'
}

export interface CatBankDocument extends JsonRecord {
  item_bank_id: string
  version: string
  instrument_id: string
  target_population: string
  measurement_model: 'GRM'
  dimensions: [string]
  items: CatAssetItemDocument[]
  status: 'draft' | 'published'
  metadata: JsonRecord
}

export interface CatConfigDocument extends JsonRecord {
  config_version: string
  model: 'GRM'
  estimator: 'EAP' | 'BM'
  selection_method: 'MFI'
  min_items: number
  max_items: number
  se_threshold: number | null
  initial_theta: number
  prior_mean: number
  prior_sd: number
  optimization_interval: [number, number]
  seed: number
  exposure_control: 'none'
  content_balancing: 'none'
}

export interface CatAssetTemplate {
  engineering_only: true
  psychological_interpretation_allowed: false
  bank_document: CatBankDocument
  config_document: CatConfigDocument
}

export interface CatBankVersionMetadata {
  version_ref: string
  version_number: number
  created_at: string
  item_count: number
  dimension_count: number
}

export interface CatPlanVersionMetadata {
  version_ref: string
  version_number: number
  created_at: string
  bank_version_ref?: string
}

export interface CatBankMetadata {
  bank_ref: string
  display_name: string
  status: AssetStatus
  revision: number
  created_at: string
  updated_at: string
}

export interface CatPlanMetadata {
  plan_ref: string
  display_name: string
  status: AssetStatus
  revision: number
  created_at: string
  updated_at: string
}

export interface CatBankDetail extends CatBankMetadata {
  versions: CatBankVersionMetadata[]
}

export interface CatPlanDetail extends CatPlanMetadata {
  versions: CatPlanVersionMetadata[]
}

export interface CatBankVersion extends CatBankVersionMetadata {
  bank_document: CatBankDocument
}

export interface CatPlanVersion extends CatPlanVersionMetadata {
  config_document: CatConfigDocument
}

export type CatAssetVersionSummary = CatBankVersionMetadata | CatPlanVersionMetadata

export function latestCatAssetVersion<T extends CatAssetVersionSummary>(versions: readonly T[]): T | undefined {
  return versions.reduce<T | undefined>((latest, version) =>
    !latest || version.version_number > latest.version_number ? version : latest, undefined)
}

export interface CatAssetPage<T> {
  engineering_only: true
  psychological_interpretation_allowed: false
  items: T[]
  has_more: boolean
}

export interface CatBankMutation extends CatBankDetail {
  version_ref?: string
}

export interface CatPlanMutation extends CatPlanDetail {
  version_ref?: string
}

const INVALID_RESPONSE = '题库或方案接口返回的数据格式无法识别。'
const BANK_REF = /^CBANK_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$/
const BANK_VERSION_REF = /^CBVER_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$/
const PLAN_REF = /^CPLAN_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$/
const PLAN_VERSION_REF = /^CPVER_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$/
const ITEM_REF = /^ITEM_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$/
const MAX_DOCUMENT_BYTES = 256 * 1024
const MAX_ITEM_COUNT = 100
const exactKeys = (value: UnknownRecord, expected: string[]) =>
  Object.keys(value).sort().join('|') === [...expected].sort().join('|')

const invalid = (): never => { throw new RealApiError('API_INVALID_RESPONSE', INVALID_RESPONSE) }
const record = (value: unknown): UnknownRecord => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid()
  return value as UnknownRecord
}
const text = (source: UnknownRecord, key: string, maximum = 5000): string => {
  const value = source[key]
  if (typeof value !== 'string' || !value.trim() || value.length > maximum) return invalid()
  return value
}
const integer = (source: UnknownRecord, key: string, minimum = 0, maximum = Number.MAX_SAFE_INTEGER): number => {
  const value = source[key]
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < minimum || value > maximum) return invalid()
  return value
}
const finite = (source: UnknownRecord, key: string, minimum = -Infinity, maximum = Infinity): number => {
  const value = source[key]
  if (typeof value !== 'number' || !Number.isFinite(value) || value < minimum || value > maximum) return invalid()
  return value
}
const timestamp = (source: UnknownRecord, key: string): string => {
  const value = text(source, key, 64)
  if (Number.isNaN(Date.parse(value))) return invalid()
  return value
}
const requireFlags = (source: UnknownRecord) => {
  if (source.engineering_only !== true || source.psychological_interpretation_allowed !== false) {
    throw new RealApiError('CAT_ASSET_UNAVAILABLE', '当前资产不满足合成工程内容的使用条件。')
  }
}
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const utf8Size = (value: unknown): number => encodeURIComponent(JSON.stringify(value)).replace(/%[\da-f]{2}/gi, 'x').length

function mapBankDocument(value: unknown): CatBankDocument {
  const bank = record(value)
  if (!exactKeys(bank, [
    'item_bank_id', 'version', 'instrument_id', 'target_population', 'measurement_model',
    'dimensions', 'items', 'status', 'metadata',
  ])) return invalid()
  const metadata = record(bank.metadata)
  const dimensions = bank.dimensions
  const rawItems = bank.items
  if (bank.measurement_model !== 'GRM'
    || !Array.isArray(dimensions) || dimensions.length !== 1
    || !Array.isArray(rawItems) || rawItems.length < 1 || rawItems.length > MAX_ITEM_COUNT
    || !['draft', 'published'].includes(String(bank.status))
    || metadata.synthetic !== true
    || metadata.intended_use !== 'engineering_test_only'
    || metadata.psychological_interpretation_allowed !== false) {
    throw new RealApiError('CAT_ASSET_UNAVAILABLE', '当前题库不是可编辑的合成工程题库。')
  }
  const dimension = dimensions[0]
  if (typeof dimension !== 'string' || !dimension.trim() || dimension.length > 120) return invalid()
  const seen = new Set<string>()
  const items = rawItems.map((raw): CatAssetItemDocument => {
    const item = record(raw)
    if (!exactKeys(item, [
      'item_id', 'dimension', 'stem', 'response_type', 'response_options', 'scoring',
      'model', 'parameters', 'source', 'status',
    ])) return invalid()
    const itemId = text(item, 'item_id', 128)
    const responseOptions = item.response_options
    const scoringSource = record(item.scoring)
    if (!ITEM_REF.test(itemId) || seen.has(itemId)
      || item.dimension !== dimension
      || item.model !== 'GRM'
      || !['published', 'demo', 'synthetic'].includes(String(item.status))
      || !Array.isArray(responseOptions) || responseOptions.length < 2 || responseOptions.length > 10) return invalid()
    seen.add(itemId)
    const options = responseOptions.map((option) => {
      if (typeof option !== 'string' || !option.trim() || option.length > 120) return invalid()
      return option
    })
    if (new Set(options).size !== options.length
      || Object.keys(scoringSource).length !== options.length
      || options.some((option) => !Object.hasOwn(scoringSource, option))) return invalid()
    const scores = options.map((option) => scoringSource[option])
    if (scores.some((score) => typeof score !== 'number' || !Number.isSafeInteger(score) || score < 0 || score >= options.length)
      || new Set(scores).size !== options.length
      || scores.slice().sort((a, b) => a - b).some((score, index) => score !== index)) return invalid()
    const parameters = record(item.parameters)
    if (!exactKeys(parameters, ['a', 'thresholds'])) return invalid()
    const a = finite(parameters, 'a', Number.MIN_VALUE, 10)
    const rawThresholds = parameters.thresholds
    if (!Array.isArray(rawThresholds) || rawThresholds.length !== options.length - 1) return invalid()
    const thresholds = rawThresholds.map((threshold) => {
      if (typeof threshold !== 'number' || !Number.isFinite(threshold)) return invalid()
      return threshold
    })
    if (thresholds.some((threshold, index) => index > 0 && threshold <= thresholds[index - 1])) return invalid()
    return {
      item_id: itemId,
      dimension,
      stem: text(item, 'stem', 2000),
      response_type: item.response_type === 'likert' ? 'likert' : invalid(),
      response_options: options,
      scoring: Object.fromEntries(options.map((option, index) => [option, scores[index] as number])),
      model: 'GRM',
      parameters: { a, thresholds },
      source: text(item, 'source', 240),
      status: item.status as CatAssetItemDocument['status'],
    }
  })
  const result: CatBankDocument = {
    item_bank_id: text(bank, 'item_bank_id', 128),
    version: text(bank, 'version', 120),
    instrument_id: text(bank, 'instrument_id', 120),
    target_population: text(bank, 'target_population', 120),
    measurement_model: 'GRM',
    dimensions: [dimension],
    items,
    status: bank.status as CatBankDocument['status'],
    metadata: clone(metadata) as JsonRecord,
  }
  if (utf8Size(result) > MAX_DOCUMENT_BYTES) return invalid()
  return result
}

function mapConfigDocument(value: unknown, bank?: CatBankDocument): CatConfigDocument {
  const config = record(value)
  if (!exactKeys(config, [
    'config_version', 'model', 'estimator', 'selection_method', 'min_items', 'max_items',
    'se_threshold', 'initial_theta', 'prior_mean', 'prior_sd', 'optimization_interval',
    'seed', 'exposure_control', 'content_balancing',
  ])) return invalid()
  if (config.model !== 'GRM' || !['EAP', 'BM'].includes(String(config.estimator))
    || config.selection_method !== 'MFI'
    || config.exposure_control !== 'none' || config.content_balancing !== 'none') return invalid()
  const minItems = integer(config, 'min_items', 1, MAX_ITEM_COUNT)
  const maxItems = integer(config, 'max_items', minItems, MAX_ITEM_COUNT)
  const seThreshold = config.se_threshold === null ? null : finite(config, 'se_threshold', Number.MIN_VALUE, 10)
  const interval = config.optimization_interval
  if (!Array.isArray(interval) || interval.length !== 2) return invalid()
  const low = typeof interval[0] === 'number' && Number.isFinite(interval[0]) ? interval[0] : invalid()
  const high = typeof interval[1] === 'number' && Number.isFinite(interval[1]) ? interval[1] : invalid()
  if (low >= high) return invalid()
  const result: CatConfigDocument = {
    config_version: text(config, 'config_version', 120),
    model: 'GRM',
    estimator: config.estimator as CatConfigDocument['estimator'],
    selection_method: 'MFI',
    min_items: minItems,
    max_items: maxItems,
    se_threshold: seThreshold,
    initial_theta: finite(config, 'initial_theta'),
    prior_mean: finite(config, 'prior_mean'),
    prior_sd: finite(config, 'prior_sd', Number.MIN_VALUE, 10),
    optimization_interval: [low, high],
    seed: integer(config, 'seed', 0, 4294967295),
    exposure_control: 'none',
    content_balancing: 'none',
  }
  if (bank && (result.max_items > bank.items.length || bank.measurement_model !== result.model)) return invalid()
  if (utf8Size(result) > MAX_DOCUMENT_BYTES) return invalid()
  return result
}

function mapTemplate(value: unknown): CatAssetTemplate {
  const source = record(value)
  requireFlags(source)
  const bank = mapBankDocument(source.bank_document)
  const config = mapConfigDocument(source.config_document, bank)
  return {
    engineering_only: true,
    psychological_interpretation_allowed: false,
    bank_document: bank,
    config_document: config,
  }
}

function mapList<T>(value: unknown, mapper: (item: unknown) => T): CatAssetPage<T> {
  const source = record(value)
  requireFlags(source)
  if (!Array.isArray(source.items) || typeof source.has_more !== 'boolean') return invalid()
  return {
    engineering_only: true,
    psychological_interpretation_allowed: false,
    items: source.items.map(mapper),
    has_more: source.has_more,
  }
}

function mapBankMetadata(value: unknown): CatBankMetadata {
  const source = record(value)
  const bankRef = text(source, 'bank_ref', 128)
  const status = source.status
  if (!BANK_REF.test(bankRef) || !['ACTIVE', 'ARCHIVED'].includes(String(status))) return invalid()
  return {
    bank_ref: bankRef,
    display_name: text(source, 'display_name', 120),
    status: status as AssetStatus,
    revision: integer(source, 'revision', 1),
    created_at: timestamp(source, 'created_at'),
    updated_at: timestamp(source, 'updated_at'),
  }
}

function mapPlanMetadata(value: unknown): CatPlanMetadata {
  const source = record(value)
  const planRef = text(source, 'plan_ref', 128)
  const status = source.status
  if (!PLAN_REF.test(planRef) || !['ACTIVE', 'ARCHIVED'].includes(String(status))) return invalid()
  return {
    plan_ref: planRef,
    display_name: text(source, 'display_name', 120),
    status: status as AssetStatus,
    revision: integer(source, 'revision', 1),
    created_at: timestamp(source, 'created_at'),
    updated_at: timestamp(source, 'updated_at'),
  }
}

function mapBankVersionMetadata(value: unknown): CatBankVersionMetadata {
  const source = record(value)
  const versionRef = text(source, 'version_ref', 128)
  if (!BANK_VERSION_REF.test(versionRef)) return invalid()
  return {
    version_ref: versionRef,
    version_number: integer(source, 'version_number', 1),
    created_at: timestamp(source, 'created_at'),
    item_count: integer(source, 'item_count', 1, MAX_ITEM_COUNT),
    dimension_count: integer(source, 'dimension_count', 1, 1),
  }
}

function mapPlanVersionMetadata(value: unknown): CatPlanVersionMetadata {
  const source = record(value)
  const versionRef = text(source, 'version_ref', 128)
  const bankVersionRef = source.bank_version_ref
  if (!PLAN_VERSION_REF.test(versionRef)
    || (bankVersionRef !== undefined && (typeof bankVersionRef !== 'string' || !BANK_VERSION_REF.test(bankVersionRef)))) return invalid()
  return {
    version_ref: versionRef,
    version_number: integer(source, 'version_number', 1),
    created_at: timestamp(source, 'created_at'),
    ...(typeof bankVersionRef === 'string' ? { bank_version_ref: bankVersionRef } : {}),
  }
}

function mapBankDetail(value: unknown): CatBankDetail {
  const source = record(value)
  requireFlags(source)
  const bank = record(source.bank)
  const metadata = mapBankMetadata(bank)
  if (!Array.isArray(bank.versions)) return invalid()
  return { ...metadata, versions: bank.versions.map(mapBankVersionMetadata) }
}

function mapPlanDetail(value: unknown): CatPlanDetail {
  const source = record(value)
  requireFlags(source)
  const plan = record(source.plan)
  const metadata = mapPlanMetadata(plan)
  if (!Array.isArray(plan.versions)) return invalid()
  return { ...metadata, versions: plan.versions.map(mapPlanVersionMetadata) }
}

function mapBankMutation(value: unknown): CatBankMutation {
  const detail = mapBankDetail(value)
  const source = record(value)
  const versionRef = source.version_ref
  if (versionRef !== undefined && (typeof versionRef !== 'string' || !BANK_VERSION_REF.test(versionRef))) return invalid()
  return { ...detail, ...(typeof versionRef === 'string' ? { version_ref: versionRef } : {}) }
}

function mapPlanMutation(value: unknown): CatPlanMutation {
  const detail = mapPlanDetail(value)
  const source = record(value)
  const versionRef = source.version_ref
  if (versionRef !== undefined && (typeof versionRef !== 'string' || !PLAN_VERSION_REF.test(versionRef))) return invalid()
  return { ...detail, ...(typeof versionRef === 'string' ? { version_ref: versionRef } : {}) }
}

function mapBankVersion(value: unknown): CatBankVersion {
  const source = record(value)
  requireFlags(source)
  const metadata = mapBankVersionMetadata(source.version)
  const bank = mapBankDocument(source.bank_document)
  if (metadata.item_count !== bank.items.length || metadata.dimension_count !== bank.dimensions.length) return invalid()
  return { ...metadata, bank_document: bank }
}

function mapPlanVersion(value: unknown): CatPlanVersion {
  const source = record(value)
  requireFlags(source)
  const metadata = mapPlanVersionMetadata({ ...record(source.version), bank_version_ref: source.bank_version_ref })
  return { ...metadata, config_document: mapConfigDocument(source.config_document) }
}

type CatAssetRequest = Parameters<typeof requestSchoolCatAssets>[0]

const unwrap = async (request: CatAssetRequest): Promise<unknown> =>
  (await requestSchoolCatAssets<unknown>(request)).data

const pathRef = (reference: string, pattern: RegExp): string => {
  if (!pattern.test(reference)) throw new RealApiError('VALIDATION_FAILED', '题库或方案编号无效。')
  return encodeURIComponent(reference)
}

const idempotency = (key: string): string => {
  if (typeof key !== 'string' || !key.trim() || key.length > 200) {
    throw new RealApiError('API_INVALID_REQUEST', '保存操作缺少请求标识。')
  }
  return key
}

const displayName = (value: string): string => {
  const name = value.trim()
  if (!name || name.length > 120) throw new RealApiError('VALIDATION_FAILED', '名称需填写且不超过120个字符。')
  return name
}

export class SchoolCatAssetsService {
  async getTemplate(): Promise<CatAssetTemplate> {
    return mapTemplate(await unwrap({ method: 'GET', path: '/api/v1/school/cat-assets/template' }))
  }

  async listBanks(skip = 0, limit = 30): Promise<CatAssetPage<CatBankMetadata>> {
    if (!Number.isSafeInteger(skip) || skip < 0 || !Number.isSafeInteger(limit) || limit < 1 || limit > 30) {
      throw new RealApiError('VALIDATION_FAILED', '题库列表分页参数无效。')
    }
    return mapList(await unwrap({
      method: 'GET', path: '/api/v1/school/cat-assets/banks', query: { limit, skip },
    }), mapBankMetadata)
  }

  async getBank(bankRef: string): Promise<CatBankDetail> {
    return mapBankDetail(await unwrap({ method: 'GET', path: `/api/v1/school/cat-assets/banks/${pathRef(bankRef, BANK_REF)}` }))
  }

  async createBank(name: string, document: CatBankDocument, idempotencyKey: string): Promise<CatBankMutation> {
    return mapBankMutation(await unwrap({
      method: 'POST', path: '/api/v1/school/cat-assets/banks',
      body: { display_name: displayName(name), bank_document: mapBankDocument(document) },
      idempotencyKey: idempotency(idempotencyKey),
    }))
  }

  async updateBank(
    bankRef: string,
    expectedRevision: number,
    changes: { display_name?: string; status?: AssetStatus },
    idempotencyKey: string,
  ): Promise<CatBankMetadata> {
    if (!Number.isSafeInteger(expectedRevision) || expectedRevision < 1 || Object.keys(changes).length === 0) {
      throw new RealApiError('VALIDATION_FAILED', '题库版本状态已变化，请刷新后再试。')
    }
    const value = await unwrap({
      method: 'PATCH', path: `/api/v1/school/cat-assets/banks/${pathRef(bankRef, BANK_REF)}`,
      body: {
        expected_revision: expectedRevision,
        ...(changes.display_name !== undefined ? { display_name: displayName(changes.display_name) } : {}),
        ...(changes.status !== undefined ? { status: changes.status } : {}),
      },
      idempotencyKey: idempotency(idempotencyKey),
    })
    return mapBankDetail(value)
  }

  async createBankVersion(
    bankRef: string,
    expectedRevision: number,
    document: CatBankDocument,
    idempotencyKey: string,
  ): Promise<CatBankMutation> {
    if (!Number.isSafeInteger(expectedRevision) || expectedRevision < 1) {
      throw new RealApiError('VALIDATION_FAILED', '题库版本状态已变化，请刷新后再试。')
    }
    return mapBankMutation(await unwrap({
      method: 'POST', path: `/api/v1/school/cat-assets/banks/${pathRef(bankRef, BANK_REF)}/versions`,
      body: { expected_revision: expectedRevision, bank_document: mapBankDocument(document) },
      idempotencyKey: idempotency(idempotencyKey),
    }))
  }

  async getBankVersion(versionRef: string): Promise<CatBankVersion> {
    return mapBankVersion(await unwrap({
      method: 'GET', path: `/api/v1/school/cat-assets/bank-versions/${pathRef(versionRef, BANK_VERSION_REF)}`,
    }))
  }

  async listPlans(skip = 0, limit = 30): Promise<CatAssetPage<CatPlanMetadata>> {
    if (!Number.isSafeInteger(skip) || skip < 0 || !Number.isSafeInteger(limit) || limit < 1 || limit > 30) {
      throw new RealApiError('VALIDATION_FAILED', '方案列表分页参数无效。')
    }
    return mapList(await unwrap({
      method: 'GET', path: '/api/v1/school/cat-assets/plans', query: { limit, skip },
    }), mapPlanMetadata)
  }

  async getPlan(planRef: string): Promise<CatPlanDetail> {
    return mapPlanDetail(await unwrap({ method: 'GET', path: `/api/v1/school/cat-assets/plans/${pathRef(planRef, PLAN_REF)}` }))
  }

  async createPlan(
    name: string,
    bankVersionRef: string,
    bankDocument: CatBankDocument,
    config: CatConfigDocument,
    idempotencyKey: string,
  ): Promise<CatPlanMutation> {
    const validatedBank = mapBankDocument(bankDocument)
    return mapPlanMutation(await unwrap({
      method: 'POST', path: '/api/v1/school/cat-assets/plans',
      body: {
        display_name: displayName(name),
        bank_version_ref: pathRef(bankVersionRef, BANK_VERSION_REF),
        config_document: mapConfigDocument(config, validatedBank),
      },
      idempotencyKey: idempotency(idempotencyKey),
    }))
  }

  async updatePlan(
    planRef: string,
    expectedRevision: number,
    changes: { display_name?: string; status?: AssetStatus },
    idempotencyKey: string,
  ): Promise<CatPlanMetadata> {
    if (!Number.isSafeInteger(expectedRevision) || expectedRevision < 1 || Object.keys(changes).length === 0) {
      throw new RealApiError('VALIDATION_FAILED', '方案版本状态已变化，请刷新后再试。')
    }
    const value = await unwrap({
      method: 'PATCH', path: `/api/v1/school/cat-assets/plans/${pathRef(planRef, PLAN_REF)}`,
      body: {
        expected_revision: expectedRevision,
        ...(changes.display_name !== undefined ? { display_name: displayName(changes.display_name) } : {}),
        ...(changes.status !== undefined ? { status: changes.status } : {}),
      },
      idempotencyKey: idempotency(idempotencyKey),
    })
    return mapPlanDetail(value)
  }

  async createPlanVersion(
    planRef: string,
    expectedRevision: number,
    bankVersionRef: string,
    bankDocument: CatBankDocument,
    config: CatConfigDocument,
    idempotencyKey: string,
  ): Promise<CatPlanMutation> {
    if (!Number.isSafeInteger(expectedRevision) || expectedRevision < 1) {
      throw new RealApiError('VALIDATION_FAILED', '方案版本状态已变化，请刷新后再试。')
    }
    const validatedBank = mapBankDocument(bankDocument)
    return mapPlanMutation(await unwrap({
      method: 'POST', path: `/api/v1/school/cat-assets/plans/${pathRef(planRef, PLAN_REF)}/versions`,
      body: {
        expected_revision: expectedRevision,
        bank_version_ref: pathRef(bankVersionRef, BANK_VERSION_REF),
        config_document: mapConfigDocument(config, validatedBank),
      },
      idempotencyKey: idempotency(idempotencyKey),
    }))
  }

  async getPlanVersion(versionRef: string): Promise<CatPlanVersion> {
    return mapPlanVersion(await unwrap({
      method: 'GET', path: `/api/v1/school/cat-assets/plan-versions/${pathRef(versionRef, PLAN_VERSION_REF)}`,
    }))
  }
}

export const schoolCatAssets = new SchoolCatAssetsService()
export const newCatAssetIdempotencyKey = (): string => {
  if (typeof crypto === 'undefined' || typeof crypto.randomUUID !== 'function') {
    throw new RealApiError('SECURE_RANDOM_UNAVAILABLE', '当前浏览器无法安全建立保存请求。')
  }
  return `cat-asset-${crypto.randomUUID()}`
}

export const catAssetReferencePatterns = {
  bank: BANK_REF,
  bankVersion: BANK_VERSION_REF,
  plan: PLAN_REF,
  planVersion: PLAN_VERSION_REF,
} as const
