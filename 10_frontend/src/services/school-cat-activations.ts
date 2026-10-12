import { RealApiError, requestSchoolCatAssets } from '@/services/real-api'

const PLAN_VERSION_REF = /^CPVER_[A-Za-z0-9-]{36}$/
const ACTIVATION_REF = /^CACT_[A-Za-z0-9-]{36}$/
const BANK_VERSION_REF = /^CBVER_[A-Za-z0-9-]{36}$/
const INVALID_RESPONSE = '启用版本接口返回的数据格式无法识别。'

type RecordValue = Record<string, unknown>

export interface CatActivationMetadata {
  activation_ref: string
  plan_version_ref: string
  bank_version_ref: string
  plan_name: string
  plan_version_number: number
  bank_name: string
  bank_version_number: number
  status: 'ACTIVE' | 'REVOKED'
  revision: number
  created_at: string
  revoked_at: string | null
}

export interface CatActivationPage {
  engineering_only: true
  psychological_interpretation_allowed: false
  items: CatActivationMetadata[]
  has_more: boolean
}

export interface CatActivationResponse {
  engineering_only: true
  psychological_interpretation_allowed: false
  activation: CatActivationMetadata
}

const record = (value: unknown): RecordValue => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) invalid()
  return value as RecordValue
}

const invalid = (): never => { throw new RealApiError('API_INVALID_RESPONSE', INVALID_RESPONSE) }

const exactKeys = (value: RecordValue, keys: readonly string[]) =>
  Object.keys(value).sort().join('|') === [...keys].sort().join('|')

const flags = (value: RecordValue) => {
  if (value.engineering_only !== true || value.psychological_interpretation_allowed !== false) invalid()
}

const positiveInteger = (value: unknown): number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 1 ? value : invalid()

const timestamp = (value: unknown): string =>
  typeof value === 'string' && Number.isFinite(Date.parse(value)) ? value : invalid()

const mapMetadata = (value: unknown): CatActivationMetadata => {
  const source = record(value)
  const keys = [
    'activation_ref', 'plan_version_ref', 'bank_version_ref', 'plan_name',
    'plan_version_number', 'bank_name', 'bank_version_number', 'status', 'revision',
    'created_at', 'revoked_at',
  ]
  if (!exactKeys(source, keys)
    || typeof source.activation_ref !== 'string' || !ACTIVATION_REF.test(source.activation_ref)
    || typeof source.plan_version_ref !== 'string' || !PLAN_VERSION_REF.test(source.plan_version_ref)
    || typeof source.bank_version_ref !== 'string' || !BANK_VERSION_REF.test(source.bank_version_ref)
    || typeof source.plan_name !== 'string' || !source.plan_name.trim() || source.plan_name.length > 120
    || typeof source.bank_name !== 'string' || !source.bank_name.trim() || source.bank_name.length > 120
    || (source.status !== 'ACTIVE' && source.status !== 'REVOKED')
    || (source.revoked_at !== null && (typeof source.revoked_at !== 'string' || !Number.isFinite(Date.parse(source.revoked_at))))) {
    return invalid()
  }
  return {
    activation_ref: source.activation_ref,
    plan_version_ref: source.plan_version_ref,
    bank_version_ref: source.bank_version_ref,
    plan_name: source.plan_name,
    plan_version_number: positiveInteger(source.plan_version_number),
    bank_name: source.bank_name,
    bank_version_number: positiveInteger(source.bank_version_number),
    status: source.status,
    revision: positiveInteger(source.revision),
    created_at: timestamp(source.created_at),
    revoked_at: source.revoked_at,
  }
}

const mapPage = (value: unknown): CatActivationPage => {
  const source = record(value)
  if (!exactKeys(source, ['engineering_only', 'psychological_interpretation_allowed', 'items', 'has_more'])) invalid()
  flags(source)
  if (!Array.isArray(source.items) || typeof source.has_more !== 'boolean') invalid()
  return {
    engineering_only: true,
    psychological_interpretation_allowed: false,
    items: source.items.map(mapMetadata),
    has_more: source.has_more,
  }
}

const mapResponse = (value: unknown): CatActivationResponse => {
  const source = record(value)
  if (!exactKeys(source, ['engineering_only', 'psychological_interpretation_allowed', 'activation'])) invalid()
  flags(source)
  return {
    engineering_only: true,
    psychological_interpretation_allowed: false,
    activation: mapMetadata(source.activation),
  }
}

const requestKey = (value: string): string => {
  if (typeof value !== 'string' || !value.trim() || value.length > 200) {
    throw new RealApiError('API_INVALID_REQUEST', '启用状态变更缺少请求标识。')
  }
  return value
}

const unwrap = async (request: Parameters<typeof requestSchoolCatAssets>[0]): Promise<unknown> =>
  (await requestSchoolCatAssets<unknown>(request)).data

export class SchoolCatActivationsService {
  async list(options: { skip?: number; limit?: number; planVersionRef?: string } = {}): Promise<CatActivationPage> {
    const skip = options.skip ?? 0
    const limit = options.limit ?? 30
    if (!Number.isSafeInteger(skip) || skip < 0 || !Number.isSafeInteger(limit) || limit < 1 || limit > 100) {
      throw new RealApiError('VALIDATION_FAILED', '启用版本列表分页参数无效。')
    }
    if (options.planVersionRef !== undefined && !PLAN_VERSION_REF.test(options.planVersionRef)) {
      throw new RealApiError('VALIDATION_FAILED', '方案版本编号无效。')
    }
    const page = mapPage(await unwrap({
      method: 'GET', path: '/api/v1/school/cat-assets/activations',
      query: {
        limit, skip,
        ...(options.planVersionRef ? { plan_version_ref: options.planVersionRef } : {}),
      },
    }))
    if (page.items.length > limit
      || (options.planVersionRef && page.items.some((item) => item.plan_version_ref !== options.planVersionRef))) invalid()
    return page
  }

  async create(planVersionRef: string, idempotencyKey: string): Promise<CatActivationMetadata> {
    if (!PLAN_VERSION_REF.test(planVersionRef)) {
      throw new RealApiError('VALIDATION_FAILED', '方案版本编号无效。')
    }
    const response = mapResponse(await unwrap({
      method: 'POST',
      path: `/api/v1/school/cat-assets/plan-versions/${encodeURIComponent(planVersionRef)}/activations`,
      body: {},
      idempotencyKey: requestKey(idempotencyKey),
    }))
    if (response.activation.plan_version_ref !== planVersionRef) invalid()
    return response.activation
  }

  async revoke(
    activationRef: string,
    expectedRevision: number,
    idempotencyKey: string,
  ): Promise<CatActivationMetadata> {
    if (!ACTIVATION_REF.test(activationRef)) {
      throw new RealApiError('VALIDATION_FAILED', '启用记录编号无效。')
    }
    if (!Number.isSafeInteger(expectedRevision) || expectedRevision < 1) {
      throw new RealApiError('VALIDATION_FAILED', '启用记录版本已变化，请刷新后重试。')
    }
    const response = mapResponse(await unwrap({
      method: 'PATCH',
      path: `/api/v1/school/cat-assets/activations/${encodeURIComponent(activationRef)}`,
      body: { expected_revision: expectedRevision, status: 'REVOKED' },
      idempotencyKey: requestKey(idempotencyKey),
    }))
    if (response.activation.activation_ref !== activationRef || response.activation.status !== 'REVOKED'
      || response.activation.revision !== expectedRevision + 1) invalid()
    return response.activation
  }
}

export const schoolCatActivations = new SchoolCatActivationsService()

export const newCatActivationIdempotencyKey = (): string => {
  if (typeof crypto === 'undefined' || typeof crypto.randomUUID !== 'function') {
    throw new RealApiError('SECURE_RANDOM_UNAVAILABLE', '当前浏览器无法安全建立变更请求。')
  }
  return `cat-activation-${crypto.randomUUID()}`
}

export const catActivationReferencePatterns = { activation: ACTIVATION_REF, planVersion: PLAN_VERSION_REF } as const
