/* global AbortSignal */

import {
  createAssessment,
  createSupport,
  completeAssessment,
  getAssessment,
  getAssessmentState,
  getReport,
  getReview,
  listReviews,
  authLogin,
  authLogout,
  authMe,
  authCsrf,
  recordAssessmentResponse,
  reviewReport,
} from '@/api/generated/sdk.gen'
import { createClient, createConfig } from '@/api/generated/client'
import type { ApiEnvelope, Assessment, Citation, GenerationResult, Role, SchoolRoleContext } from '@/types/contracts'
import type {
  CatQuestion,
  ReviewCase,
  ReviewDetailViewModel,
  ReviewQueueViewModel,
  StudentHomeViewModel,
  StudentReportViewModel,
} from '@/types/view-models'
import type {
  AssessmentState,
  AssessmentListEntry,
  AssessmentListParams,
  ResearchProfileCandidate,
  ResearchProfileVersion,
  ResearchProfileVersionPage,
  ResearchProfileSimulationReceipt,
  ResearchSourceCatalogPage,
  ResearchSourceDetail,
  ResearchSourceReview,
  ResearchSourceSummary,
  ResearchTaskBindingOption,
  ResearchTaskPublishInput,
  ResearchTaskPublicationReceipt,
  ResearchAnswerInput,
  ResearchCompletion,
  ResearchDiscoveryPage,
  ResearchL1Session,
  ResearchQuestion,
  ResearchResponseOption,
  ResearchSessionDiscoveryEntry,
  ResearchTaskDiscoveryEntry,
  FrontendApi,
  LoginInput,
  LoginResult,
  ReportSummary,
  SchoolClass,
  SchoolMember,
  SchoolMemberRole,
  SchoolTask,
  SchoolTaskEnrollment,
  SchoolTaskStart,
  StudentSchoolTask,
  StudentSchoolTaskHistory,
  ReviewSubmission,
  TeacherTaskProgress,
  SupportResult,
  SchoolDirectory,
  SchoolOperationsAuditCategory,
  SchoolOperationsAuditEvent,
  SchoolOperationsAuditPage,
  SchoolAccountImportRow,
  SchoolAccountPreview,
  SchoolAccountBatch,
} from '@/api/client'

type UnknownRecord = Record<string, unknown>

const SYNTHETIC_FIXTURE_LABEL = '真实接口 · 合成数据 · 仅用于工程验证'
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || '/'
const apiClient = createClient(createConfig({
  baseUrl: apiBaseUrl,
  credentials: 'include',
}))

export class RealApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly retryable = false,
    public readonly schoolAccountPreview: SchoolAccountPreview | null = null,
  ) {
    super(message)
    this.name = 'RealApiError'
  }
}

const isRecord = (value: unknown): value is UnknownRecord => Boolean(value) && typeof value === 'object'

const requestError = (value: unknown): RealApiError => {
  if (isRecord(value)) {
     const code = typeof value.code === 'string' ? value.code : 'API_ERROR'
     const detail = typeof value.detail === 'string' ? value.detail : '接口请求没有完成。'
     const message = Array.isArray(value.errors) ? '请求参数没有通过校验。' : detail
     return new RealApiError(code, message, Boolean(value.retryable))
  }
  return new RealApiError('API_ERROR', '接口请求没有完成。', true)
}

const unwrap = async <T>(operation: () => Promise<unknown>): Promise<ApiEnvelope<T>> => {
  let raw: unknown
  try {
    raw = await operation()
  } catch (error) {
    if (error instanceof RealApiError) throw error
    throw new RealApiError('NETWORK_UNAVAILABLE', '当前无法连接到本地接口，请确认 Backend 正在运行。', true)
  }

  if (!isRecord(raw)) throw new RealApiError('API_INVALID_RESPONSE', '接口返回了无法识别的响应。')
  if (raw.error) throw requestError(raw.error)
  if (typeof raw.request_id === 'string' && 'data' in raw) return raw as unknown as ApiEnvelope<T>
  if (isRecord(raw.data) && typeof raw.data.request_id === 'string' && 'data' in raw.data) {
    return raw.data as unknown as ApiEnvelope<T>
  }
  throw new RealApiError('API_INVALID_RESPONSE', '接口响应缺少统一信封字段。')
}

const nowToken = (prefix: string) => {
  const suffix = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}-${suffix}`
}

const valueAsString = (value: unknown, fallback = '') => typeof value === 'string' ? value : fallback
const nullableString = (value: unknown): string | null => typeof value === 'string' ? value : null
const requiredString = (source: UnknownRecord, key: string): string => {
  const value = source[key]
  if (typeof value !== 'string' || !value.trim()) {
    throw new RealApiError('API_INVALID_RESPONSE', '学校任务响应格式无法识别。')
  }
  return value
}
const requiredCount = (source: UnknownRecord, key: string): number => {
  const value = source[key]
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    throw new RealApiError('API_INVALID_RESPONSE', '学校任务统计格式无法识别。')
  }
  return value
}
const requiredPositiveCount = (source: UnknownRecord, key: string): number => {
  const value = source[key]
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 1) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究会话响应格式无法识别。')
  }
  return value
}
const requireExactKeys = (value: UnknownRecord, keys: readonly string[], message: string) => {
  if (Object.keys(value).length !== keys.length || keys.some((key) => !Object.hasOwn(value, key))) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
}
const researchStatus = (value: unknown): value is ResearchSessionDiscoveryEntry['status'] =>
  value === 'IN_PROGRESS' || value === 'COMPLETED' || value === 'FAILED' || value === 'ABANDONED'

const mapResearchTaskDiscovery = (value: unknown): ResearchTaskDiscoveryEntry => {
  const keys = [
    'task_ref', 'class_ref', 'profile_ref', 'source_population_scope', 'instrument_id', 'instrument_version',
    'publication_status', 'research_only', 'opens_at', 'due_at', 'status', 'completion_count',
    'session_ref', 'session_status', 'items_answered',
  ] as const
  if (!isRecord(value) || Array.isArray(value)) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究任务列表格式无法识别。')
  }
  requireExactKeys(value, keys, '研究任务列表包含不支持的信息。')
  const sessionRef = value.session_ref
  const sessionStatus = value.session_status
  if ((sessionRef !== null && typeof sessionRef !== 'string')
    || (sessionStatus !== null && !researchStatus(sessionStatus))
    || (value.publication_status !== 'not_approved_for_publication_or_operational_use')
    || value.research_only !== true || value.status !== 'PUBLISHED'
    || (sessionRef === null) !== (sessionStatus === null)) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究任务状态格式无法识别。')
  }
  const completionCount = requiredCount(value, 'completion_count')
  const itemsAnswered = requiredCount(value, 'items_answered')
  if (completionCount > 1 || (sessionRef === null && (itemsAnswered !== 0 || completionCount !== 0))
    || (sessionRef !== null && completionCount !== (sessionStatus === 'COMPLETED' ? 1 : 0))) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究任务进度格式无法识别。')
  }
  return {
    task_ref: requiredString(value, 'task_ref'),
    class_ref: requiredString(value, 'class_ref'),
    profile_ref: requiredString(value, 'profile_ref'),
    source_population_scope: requiredString(value, 'source_population_scope'),
    instrument_id: requiredString(value, 'instrument_id'),
    instrument_version: requiredString(value, 'instrument_version'),
    publication_status: value.publication_status,
    research_only: true,
    opens_at: requiredTimestamp(value, 'opens_at')!,
    due_at: requiredTimestamp(value, 'due_at', true),
    status: 'PUBLISHED',
    completion_count: completionCount,
    session_ref: sessionRef as string | null,
    session_status: sessionStatus as ResearchTaskDiscoveryEntry['session_status'],
    items_answered: itemsAnswered,
  }
}

const mapResearchSessionDiscovery = (value: unknown): ResearchSessionDiscoveryEntry => {
  const keys = ['session_ref', 'task_ref', 'status', 'items_answered', 'completed_at', 'research_only'] as const
  if (!isRecord(value) || Array.isArray(value)) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究会话记录格式无法识别。')
  }
  requireExactKeys(value, keys, '研究会话记录包含不支持的信息。')
  if (!researchStatus(value.status) || value.research_only !== true) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究会话记录状态格式无法识别。')
  }
  return {
    session_ref: requiredString(value, 'session_ref'),
    task_ref: requiredString(value, 'task_ref'),
    status: value.status,
    items_answered: requiredCount(value, 'items_answered'),
    completed_at: requiredTimestamp(value, 'completed_at', true),
    research_only: true,
  }
}

const mapResearchProfileCandidate = (value: unknown): ResearchProfileCandidate => {
  const keys = [
    'profile_ref', 'version_number', 'source_population_scope', 'instrument_id',
    'research_only', 'publication_status', 'rights_status', 'execution_status',
    'created_at', 'catalog_state',
  ] as const
  if (!isRecord(value) || Array.isArray(value)) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究资料候选格式无法识别。')
  }
  requireExactKeys(value, keys, '研究资料目录包含不支持的信息。')
  const version = value.version_number
  const population = value.source_population_scope
  const created = value.created_at
  if ((version !== null && (typeof version !== 'number' || !Number.isSafeInteger(version) || version < 1))
    || (population !== null && typeof population !== 'string')
    || (created !== null && typeof created !== 'string')
    || value.research_only !== true
    || value.publication_status !== 'not_approved_for_publication_or_operational_use'
    || !['VERIFIED', 'PENDING', 'REVOKED'].includes(String(value.rights_status))
    || !['CANDIDATE_RESEARCH_ONLY', 'SIMULATION_ENABLED', 'DISABLED'].includes(String(value.execution_status))
    || !['REGISTRY_CANDIDATE', 'IMPORTED_CANDIDATE', 'EXISTING_CANDIDATE', 'IDEMPOTENT_REPLAY'].includes(String(value.catalog_state))) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究资料候选状态格式无法识别。')
  }
  return {
    profile_ref: requiredString(value, 'profile_ref'),
    version_number: version as number | null,
    source_population_scope: population as string | null,
    instrument_id: requiredString(value, 'instrument_id'),
    research_only: true,
    publication_status: 'not_approved_for_publication_or_operational_use',
    rights_status: value.rights_status as string,
    execution_status: value.execution_status as string,
    created_at: created === null ? null : requiredTimestamp(value, 'created_at', true),
    catalog_state: value.catalog_state as ResearchProfileCandidate['catalog_state'],
  }
}

const mapResearchSourceReview = (value: unknown): ResearchSourceReview => {
  const keys = [
    'package_status', 'reviewer_kind', 'review_status', 'professional_approval', 'ethics_approval',
    'clinical_approval', 'psychometric_approval', 'publication_eligible', 'production_use',
  ] as const
  if (!isRecord(value) || Array.isArray(value)) {
    throw new RealApiError('API_INVALID_RESPONSE', '资料审核边界格式无法识别。')
  }
  requireExactKeys(value, keys, '资料审核边界包含不支持的信息。')
  if (value.package_status !== 'ENGINEERING_REVIEWED_RESEARCH_ONLY'
    || value.reviewer_kind !== 'AI_ENGINEERING' || value.review_status !== 'pending'
    || keys.slice(3).some((key) => value[key] !== false)) {
    throw new RealApiError('API_INVALID_RESPONSE', '资料审核状态或批准范围无法识别。')
  }
  return {
    package_status: 'ENGINEERING_REVIEWED_RESEARCH_ONLY',
    reviewer_kind: 'AI_ENGINEERING',
    review_status: 'pending',
    professional_approval: false,
    ethics_approval: false,
    clinical_approval: false,
    psychometric_approval: false,
    publication_eligible: false,
    production_use: false,
  }
}

const validHttpsUrl = (value: unknown): value is string => {
  if (typeof value !== 'string' || !value.trim()) return false
  try {
    const url = new globalThis.URL(value)
    return url.protocol === 'https:' && Boolean(url.hostname) && !url.username && !url.password
  } catch {
    return false
  }
}

const mapResearchSourceSummary = (value: unknown): ResearchSourceSummary => {
  const keys = [
    'source_ref', 'title', 'organization', 'publication_date', 'canonical_url',
    'source_population_scope', 'source_language', 'layers', 'rights_status', 'retrieval_eligible',
  ] as const
  if (!isRecord(value) || Array.isArray(value)) {
    throw new RealApiError('API_INVALID_RESPONSE', '来源目录条目格式无法识别。')
  }
  requireExactKeys(value, keys, '来源目录条目包含不支持的信息。')
  const layers = value.layers
  if (!Array.isArray(layers) || layers.length > 3
    || layers.some((layer) => typeof layer !== 'string' || !['policy', 'theory', 'intervention'].includes(layer))
    || new Set(layers).size !== layers.length
    || value.source_language !== 'English'
    || typeof value.rights_status !== 'string'
    || !['VERIFIED_WITH_CONDITIONS', 'PENDING'].includes(value.rights_status)
    || typeof value.retrieval_eligible !== 'boolean'
    || (value.retrieval_eligible && value.rights_status !== 'VERIFIED_WITH_CONDITIONS')
    || !validHttpsUrl(value.canonical_url)) {
    throw new RealApiError('API_INVALID_RESPONSE', '来源目录状态格式无法识别。')
  }
  return {
    source_ref: requiredString(value, 'source_ref'),
    title: requiredString(value, 'title'),
    organization: requiredString(value, 'organization'),
    publication_date: requiredString(value, 'publication_date'),
    canonical_url: value.canonical_url,
    source_population_scope: requiredString(value, 'source_population_scope'),
    source_language: 'English',
    layers: layers as ResearchSourceSummary['layers'],
    rights_status: value.rights_status as ResearchSourceSummary['rights_status'],
    retrieval_eligible: value.retrieval_eligible,
  }
}

const mapResearchSourcePage = (value: unknown): ResearchSourceCatalogPage => {
  const keys = [
    'schema_version', 'source_package_ref', 'manifest_sha256', 'study_ref',
    'consumer_age_min', 'consumer_age_max', 'review', 'items', 'total', 'limit', 'offset', 'has_more',
  ] as const
  if (!isRecord(value) || Array.isArray(value)) {
    throw new RealApiError('API_INVALID_RESPONSE', '来源目录分页格式无法识别。')
  }
  requireExactKeys(value, keys, '来源目录包含不支持的信息。')
  if (value.schema_version !== 'school.research-source-catalog.v1'
    || typeof value.manifest_sha256 !== 'string'
    || !/^[0-9a-f]{64}$/.test(value.manifest_sha256)
    || value.consumer_age_min !== 14 || value.consumer_age_max !== 17
    || typeof value.has_more !== 'boolean' || !Array.isArray(value.items)) {
    throw new RealApiError('API_INVALID_RESPONSE', '来源目录分页状态无法识别。')
  }
  const total = requiredCount(value, 'total')
  const limit = requiredPositiveCount(value, 'limit')
  const offset = requiredCount(value, 'offset')
  if (limit > 50 || offset > 10_000 || value.items.length > limit
    || offset + value.items.length > total || value.has_more !== (offset + value.items.length < total)) {
    throw new RealApiError('API_INVALID_RESPONSE', '来源目录分页范围无法识别。')
  }
  const items = value.items.map(mapResearchSourceSummary)
  if (new Set(items.map((item) => item.source_ref)).size !== items.length) {
    throw new RealApiError('API_INVALID_RESPONSE', '来源目录包含重复条目。')
  }
  return {
    schema_version: 'school.research-source-catalog.v1',
    source_package_ref: requiredString(value, 'source_package_ref'),
    manifest_sha256: value.manifest_sha256 as string,
    study_ref: requiredString(value, 'study_ref'),
    consumer_age_min: 14,
    consumer_age_max: 17,
    review: mapResearchSourceReview(value.review),
    items,
    total,
    limit,
    offset,
    has_more: value.has_more,
  }
}

const mapResearchSourceDetail = (value: unknown): ResearchSourceDetail => {
  if (!isRecord(value) || Array.isArray(value)) {
    throw new RealApiError('API_INVALID_RESPONSE', '来源详情格式无法识别。')
  }
  const summary = mapResearchSourceSummary(Object.fromEntries(
    Object.entries(value).filter(([key]) => [
      'source_ref', 'title', 'organization', 'publication_date', 'canonical_url',
      'source_population_scope', 'source_language', 'layers', 'rights_status', 'retrieval_eligible',
    ].includes(key)),
  ))
  const keys = [
    'source_ref', 'title', 'organization', 'publication_date', 'canonical_url',
    'source_population_scope', 'source_language', 'layers', 'rights_status', 'retrieval_eligible',
    'license', 'license_url', 'attribution', 'rights_evidence_url', 'rights_evidence_sha256',
    'rights_scope_note', 'source_capture_sha256', 'review',
  ] as const
  requireExactKeys(value, keys, '来源详情包含不支持的信息。')
  if (!validHttpsUrl(value.license_url) || !validHttpsUrl(value.rights_evidence_url)
    || (value.source_capture_sha256 !== null
      && (typeof value.source_capture_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(value.source_capture_sha256)))
    || typeof value.rights_evidence_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(value.rights_evidence_sha256)) {
    throw new RealApiError('API_INVALID_RESPONSE', '来源权利证据格式无法识别。')
  }
  return {
    ...summary,
    license: requiredString(value, 'license'),
    license_url: value.license_url,
    attribution: requiredString(value, 'attribution'),
    rights_evidence_url: value.rights_evidence_url,
    rights_evidence_sha256: value.rights_evidence_sha256,
    rights_scope_note: requiredString(value, 'rights_scope_note'),
    source_capture_sha256: value.source_capture_sha256 as string | null,
    review: mapResearchSourceReview(value.review),
  }
}

const mapResearchProfileVersion = (value: unknown): ResearchProfileVersion => {
  const keys = [
    'profile_ref', 'version_number', 'source_population_scope', 'instrument_id',
    'research_only', 'publication_status', 'rights_status', 'execution_status',
    'created_at', 'use_eligibility',
  ] as const
  if (!isRecord(value) || Array.isArray(value)) {
    throw new RealApiError('API_INVALID_RESPONSE', '已登记资料版本格式无法识别。')
  }
  requireExactKeys(value, keys, '已登记资料版本包含不支持的信息。')
  if (value.research_only !== true
    || value.publication_status !== 'not_approved_for_publication_or_operational_use'
    || !['PENDING', 'VERIFIED', 'REVOKED'].includes(String(value.rights_status))
    || !['CANDIDATE_RESEARCH_ONLY', 'SIMULATION_ENABLED', 'DISABLED'].includes(String(value.execution_status))
    || value.use_eligibility !== 'RECHECK_REQUIRED') {
    throw new RealApiError('API_INVALID_RESPONSE', '已登记资料版本状态格式无法识别。')
  }
  return {
    profile_ref: requiredString(value, 'profile_ref'),
    version_number: requiredPositiveCount(value, 'version_number'),
    source_population_scope: requiredString(value, 'source_population_scope'),
    instrument_id: requiredString(value, 'instrument_id'),
    research_only: true,
    publication_status: 'not_approved_for_publication_or_operational_use',
    rights_status: value.rights_status as ResearchProfileVersion['rights_status'],
    execution_status: value.execution_status as ResearchProfileVersion['execution_status'],
    created_at: requiredTimestamp(value, 'created_at')!,
    use_eligibility: 'RECHECK_REQUIRED',
  }
}

const mapResearchProfileVersionPage = (value: unknown): ResearchProfileVersionPage => {
  const keys = ['items', 'total', 'limit', 'offset', 'has_more', 'next_offset'] as const
  if (!isRecord(value) || Array.isArray(value) || !Array.isArray(value.items)) {
    throw new RealApiError('API_INVALID_RESPONSE', '资料版本列表格式无法识别。')
  }
  requireExactKeys(value, keys, '资料版本列表包含不支持的信息。')
  const total = requiredCount(value, 'total')
  const limit = requiredPositiveCount(value, 'limit')
  const offset = requiredCount(value, 'offset')
  const nextOffset = value.next_offset
  if (limit > 30 || offset > 10_000 || value.items.length > limit
    || typeof value.has_more !== 'boolean'
    || (nextOffset !== null && (typeof nextOffset !== 'number' || !Number.isSafeInteger(nextOffset) || nextOffset < 0))
    || value.has_more !== (nextOffset !== null)
    || (value.items.length > 0 && total < offset + value.items.length)
    || value.has_more !== (offset + value.items.length < total)
    || (value.has_more && (value.items.length === 0 || nextOffset !== offset + value.items.length))) {
    throw new RealApiError('API_INVALID_RESPONSE', '资料版本分页信息无法识别。')
  }
  return {
    items: value.items.map(mapResearchProfileVersion),
    total,
    limit,
    offset,
    has_more: value.has_more,
    next_offset: nextOffset as number | null,
  }
}

const mapResearchProfileSimulationReceipt = (value: unknown): ResearchProfileSimulationReceipt => {
  const keys = [
    'profile_ref', 'version_number', 'research_only', 'human_curated',
    'publication_status', 'rights_status', 'execution_status', 'simulation_only',
    'clinical_approval', 'ethics_approval', 'psychometric_approval', 'study_ref',
    'policy_expires_at', 'catalog_state',
  ] as const
  if (!isRecord(value) || Array.isArray(value)) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究资格回执格式无法识别。')
  }
  requireExactKeys(value, keys, '研究资格回执包含不支持的信息。')
  if (value.research_only !== true || value.human_curated !== false
    || value.publication_status !== 'not_approved_for_publication_or_operational_use'
    || value.rights_status !== 'VERIFIED' || value.execution_status !== 'SIMULATION_ENABLED'
    || value.simulation_only !== true || value.clinical_approval !== false
    || value.ethics_approval !== false || value.psychometric_approval !== false
    || !['SIMULATION_ENABLED', 'IDEMPOTENT_REPLAY'].includes(String(value.catalog_state))) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究资格状态格式无法识别。')
  }
  const version = requiredPositiveCount(value, 'version_number')
  const expiry = requiredTimestamp(value, 'policy_expires_at')
  return {
    profile_ref: requiredString(value, 'profile_ref'),
    version_number: version,
    research_only: true,
    human_curated: false,
    publication_status: 'not_approved_for_publication_or_operational_use',
    rights_status: 'VERIFIED',
    execution_status: 'SIMULATION_ENABLED',
    simulation_only: true,
    clinical_approval: false,
    ethics_approval: false,
    psychometric_approval: false,
    study_ref: requiredString(value, 'study_ref'),
    policy_expires_at: expiry!,
    catalog_state: value.catalog_state as ResearchProfileSimulationReceipt['catalog_state'],
  }
}

const mapResearchTaskBindingOption = (value: unknown): ResearchTaskBindingOption => {
  const keys = [
    'binding_ref', 'profile_ref', 'profile_version_number', 'source_population_scope',
    'instrument_id', 'instrument_version', 'research_only', 'publication_status',
  ] as const
  if (!isRecord(value) || Array.isArray(value)) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究任务候选格式无法识别。')
  }
  requireExactKeys(value, keys, '研究任务候选包含不支持的信息。')
  if (value.research_only !== true
    || value.publication_status !== 'not_approved_for_publication_or_operational_use') {
    throw new RealApiError('API_INVALID_RESPONSE', '研究任务候选状态格式无法识别。')
  }
  return {
    binding_ref: requiredString(value, 'binding_ref'),
    profile_ref: requiredString(value, 'profile_ref'),
    profile_version_number: requiredPositiveCount(value, 'profile_version_number'),
    source_population_scope: requiredString(value, 'source_population_scope'),
    instrument_id: requiredString(value, 'instrument_id'),
    instrument_version: requiredString(value, 'instrument_version'),
    research_only: true,
    publication_status: 'not_approved_for_publication_or_operational_use',
  }
}

const mapResearchTaskPublication = (value: unknown): ResearchTaskPublicationReceipt => {
  const keys = [
    'task_ref', 'class_ref', 'binding_ref', 'profile_ref', 'profile_version_number',
    'source_population_scope', 'instrument_id', 'instrument_version', 'status',
    'opens_at', 'due_at', 'published_at', 'published_enrollment_count',
    'response_origin', 'research_only', 'publication_status',
  ] as const
  if (!isRecord(value) || Array.isArray(value)) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究任务发布回执格式无法识别。')
  }
  requireExactKeys(value, keys, '研究任务发布回执包含不支持的信息。')
  if (value.status !== 'PUBLISHED' || value.response_origin !== 'PUBLIC_OBSERVED'
    || value.research_only !== true
    || value.publication_status !== 'not_approved_for_publication_or_operational_use') {
    throw new RealApiError('API_INVALID_RESPONSE', '研究任务发布状态格式无法识别。')
  }
  return {
    task_ref: requiredString(value, 'task_ref'),
    class_ref: requiredString(value, 'class_ref'),
    binding_ref: requiredString(value, 'binding_ref'),
    profile_ref: requiredString(value, 'profile_ref'),
    profile_version_number: requiredPositiveCount(value, 'profile_version_number'),
    source_population_scope: requiredString(value, 'source_population_scope'),
    instrument_id: requiredString(value, 'instrument_id'),
    instrument_version: requiredString(value, 'instrument_version'),
    status: 'PUBLISHED',
    opens_at: requiredTimestamp(value, 'opens_at')!,
    due_at: requiredTimestamp(value, 'due_at')!,
    published_at: requiredTimestamp(value, 'published_at')!,
    published_enrollment_count: requiredCount(value, 'published_enrollment_count'),
    response_origin: 'PUBLIC_OBSERVED',
    research_only: true,
    publication_status: 'not_approved_for_publication_or_operational_use',
  }
}

const mapResearchPage = <T>(value: unknown, mapItem: (item: unknown) => T): ResearchDiscoveryPage<T> => {
  const keys = ['items', 'total', 'limit', 'offset', 'has_more', 'next_offset'] as const
  if (!isRecord(value) || Array.isArray(value) || !Array.isArray(value.items)) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究任务分页格式无法识别。')
  }
  requireExactKeys(value, keys, '研究任务分页包含不支持的信息。')
  const total = requiredCount(value, 'total')
  const limit = requiredPositiveCount(value, 'limit')
  const offset = requiredCount(value, 'offset')
  const hasMore = value.has_more
  const nextOffset = value.next_offset
  if (typeof hasMore !== 'boolean'
    || (nextOffset !== null && (typeof nextOffset !== 'number' || !Number.isInteger(nextOffset) || nextOffset < 0))
    || hasMore !== (nextOffset !== null)
    || value.items.length > limit) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究任务分页状态格式无法识别。')
  }
  return {
    items: value.items.map(mapItem), total, limit, offset, has_more: hasMore,
    next_offset: nextOffset as number | null,
  }
}

const mapResearchOption = (value: unknown): ResearchResponseOption => {
  const keys = ['value', 'label'] as const
  if (!isRecord(value) || Array.isArray(value)) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究题目选项格式无法识别。')
  }
  requireExactKeys(value, keys, '研究题目选项包含不支持的信息。')
  if (typeof value.value !== 'number' || !Number.isSafeInteger(value.value)
    || (value.label !== null && typeof value.label !== 'string')) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究题目选项格式无法识别。')
  }
  return { value: value.value, label: value.label as string | null }
}

const mapResearchQuestion = (value: unknown): ResearchQuestion => {
  const keys = ['item_id', 'stem', 'step', 'response_options'] as const
  if (!isRecord(value) || Array.isArray(value) || !Array.isArray(value.response_options)) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究题目格式无法识别。')
  }
  requireExactKeys(value, keys, '研究题目包含不支持的信息。')
  const responseOptions = value.response_options.map(mapResearchOption)
  if (!responseOptions.length || new Set(responseOptions.map((item) => item.value)).size !== responseOptions.length) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究题目选项格式无法识别。')
  }
  return {
    item_id: requiredString(value, 'item_id'),
    stem: requiredString(value, 'stem'),
    step: requiredCount(value, 'step'),
    response_options: responseOptions,
  }
}

const mapResearchCompletion = (value: unknown): ResearchCompletion => {
  const keys = ['status', 'items_answered', 'stop_reason'] as const
  const stopReasons = ['se_threshold_reached', 'max_items_reached', 'item_bank_exhausted', 'item_bank_exhausted_before_minimum']
  if (!isRecord(value) || Array.isArray(value)) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究完成记录格式无法识别。')
  }
  requireExactKeys(value, keys, '研究完成记录包含不支持的信息。')
  if (value.status !== 'COMPLETED' || !stopReasons.includes(String(value.stop_reason))) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究完成记录格式无法识别。')
  }
  return { status: 'COMPLETED', items_answered: requiredCount(value, 'items_answered'), stop_reason: value.stop_reason as ResearchCompletion['stop_reason'] }
}

const mapResearchL1Session = (value: unknown): ResearchL1Session => {
  const keys = ['session_ref', 'status', 'state_version', 'items_answered', 'research_only', 'resume_required', 'stop_reason', 'question', 'completion'] as const
  const stopReasons = ['se_threshold_reached', 'max_items_reached', 'item_bank_exhausted', 'item_bank_exhausted_before_minimum']
  if (!isRecord(value) || Array.isArray(value)) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究会话响应格式无法识别。')
  }
  requireExactKeys(value, keys, '研究会话响应包含不支持的信息。')
  if (!researchStatus(value.status) || value.research_only !== true || typeof value.resume_required !== 'boolean'
    || (value.stop_reason !== null && !stopReasons.includes(String(value.stop_reason)))
    || (value.question !== null && value.status !== 'IN_PROGRESS')
    || (value.completion !== null && value.status !== 'COMPLETED')) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究会话状态格式无法识别。')
  }
  const question = value.question === null ? null : mapResearchQuestion(value.question)
  const completion = value.completion === null ? null : mapResearchCompletion(value.completion)
  if ((value.status === 'COMPLETED') !== (completion !== null)
    || (completion && (completion.items_answered !== requiredCount(value, 'items_answered')
      || completion.stop_reason !== value.stop_reason))
    || (value.status === 'IN_PROGRESS' && question === null && value.resume_required !== true)) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究会话完成状态无法识别。')
  }
  return {
    session_ref: requiredString(value, 'session_ref'),
    status: value.status,
    state_version: requiredPositiveCount(value, 'state_version'),
    items_answered: requiredCount(value, 'items_answered'),
    research_only: true,
    resume_required: value.resume_required,
    stop_reason: value.stop_reason as ResearchL1Session['stop_reason'],
    question,
    completion,
  }
}
const requiredTimestamp = (source: UnknownRecord, key: string, nullable = false): string | null => {
  const value = source[key]
  if (nullable && (value === null || value === undefined)) return null
  if (typeof value !== 'string' || Number.isNaN(Date.parse(value))) {
    throw new RealApiError('API_INVALID_RESPONSE', '学校任务时间格式无法识别。')
  }
  return value
}
const isAssessmentStatus = (value: unknown): value is Assessment['status'] =>
  value === 'created' || value === 'in_progress' || value === 'completed' || value === 'abandoned' || value === 'invalid'

const nullableDisplayName = (value: unknown): string | null => {
  if (value !== null && (typeof value !== 'string' || value.length > 120)) {
    throw new RealApiError('API_INVALID_RESPONSE', '学校目录名称格式无法识别。')
  }
  return value as string | null
}

const mapSchoolClass = (value: unknown): SchoolClass => {
  if (!isRecord(value)) throw new RealApiError('API_INVALID_RESPONSE', '班级列表格式无法识别。')
  if (value.display_name !== undefined && value.display_name !== null && typeof value.display_name !== 'string') {
    throw new RealApiError('API_INVALID_RESPONSE', '班级列表格式无法识别。')
  }
  return {
    class_ref: requiredString(value, 'class_ref'),
    status: requiredString(value, 'status'),
    active_student_count: requiredCount(value, 'active_student_count'),
    active_teacher_count: requiredCount(value, 'active_teacher_count'),
    ...(value.display_name !== undefined ? { display_name: value.display_name as string | null } : {}),
  }
}

const mapSchoolMember = (value: unknown): SchoolMember => {
  if (!isRecord(value) || (value.role !== 'student' && value.role !== 'teacher')) {
    throw new RealApiError('API_INVALID_RESPONSE', '人员列表格式无法识别。')
  }
  if (value.subject_id !== undefined && value.subject_id !== null && typeof value.subject_id !== 'string') {
    throw new RealApiError('API_INVALID_RESPONSE', '人员列表格式无法识别。')
  }
  return {
    user_id: requiredString(value, 'user_id'),
    role: value.role,
    subject_id: nullableString(value.subject_id),
    ...(value.display_name === undefined ? {} : { display_name: nullableDisplayName(value.display_name) }),
    ...(value.account_status === undefined ? {} : { account_status: requiredString(value, 'account_status') }),
    ...(value.provisioning_status === undefined ? {} : { provisioning_status: nullableDisplayName(value.provisioning_status) }),
  }
}

const mapSchoolDirectory = (value: unknown): SchoolDirectory => {
  const rootKeys = new Set(['school', 'classes', 'members'])
  if (!isRecord(value) || Object.keys(value).some((key) => !rootKeys.has(key))
    || !isRecord(value.school) || Object.keys(value.school).some((key) => !['school_ref', 'display_name'].includes(key))
    || !Array.isArray(value.classes) || !Array.isArray(value.members)) {
    throw new RealApiError('API_INVALID_RESPONSE', '学校目录格式无法识别。')
  }
  const school = {
    school_ref: requiredString(value.school, 'school_ref'),
    display_name: nullableDisplayName(value.school.display_name),
  }
  const classRefs = new Set<string>()
  const classes = value.classes.map((item) => {
    const allowed = new Set(['class_ref', 'status', 'active_student_count', 'active_teacher_count', 'display_name'])
    if (!isRecord(item) || Object.keys(item).some((key) => !allowed.has(key))) {
      throw new RealApiError('API_INVALID_RESPONSE', '学校目录班级包含不支持的信息。')
    }
    if (!Object.hasOwn(item, 'display_name')) throw new RealApiError('API_INVALID_RESPONSE', '学校目录班级名称缺失。')
    const mapped = mapSchoolClass(item)
    if (classRefs.has(mapped.class_ref)) {
      throw new RealApiError('API_INVALID_RESPONSE', '学校目录包含重复班级。')
    }
    classRefs.add(mapped.class_ref)
    return mapped
  })
  const memberKeys = new Set<string>()
  const members = value.members.map((item) => {
    const allowed = new Set(['user_id', 'display_name', 'role', 'account_status', 'provisioning_status'])
    if (!isRecord(item) || Object.keys(item).some((key) => !allowed.has(key))
      || (item.role !== 'student' && item.role !== 'teacher')) {
      throw new RealApiError('API_INVALID_RESPONSE', '学校目录人员包含不支持的信息。')
    }
    const userId = requiredString(item, 'user_id')
    const memberKey = JSON.stringify([userId, item.role])
    if (memberKeys.has(memberKey)) throw new RealApiError('API_INVALID_RESPONSE', '学校目录包含重复账号角色。')
    memberKeys.add(memberKey)
    if (!['ACTIVE', 'SUSPENDED', 'DISABLED'].includes(String(item.account_status))) {
      throw new RealApiError('API_INVALID_RESPONSE', '学校目录账号状态无法识别。')
    }
    if (item.provisioning_status !== null && item.provisioning_status !== 'PENDING_ACTIVATION' && item.provisioning_status !== 'ACTIVE') {
      throw new RealApiError('API_INVALID_RESPONSE', '学校目录账号状态无法识别。')
    }
    return {
      user_id: userId,
      display_name: nullableDisplayName(item.display_name),
      role: item.role,
      account_status: requiredString(item, 'account_status'),
      provisioning_status: nullableDisplayName(item.provisioning_status),
    }
  })
  return { school, classes, members }
}

const auditCategoryByAction: Record<SchoolOperationsAuditEvent['action'], SchoolOperationsAuditCategory> = {
  'school_directory.rename_school': 'organization',
  'school_directory.rename_class': 'class',
  'school_directory.rename_member': 'member',
  'school_directory.import_accounts': 'account_batch',
  'school_directory.activate_account': 'account',
  'school_tasks.task.published': 'task',
}

const mapSchoolOperationsAudit = (value: unknown): SchoolOperationsAuditPage => {
  const pageKeys = ['items', 'offset', 'limit', 'has_more'] as const
  const eventKeys = ['event_ref', 'created_at', 'action', 'result', 'resource_category', 'record_count'] as const
  if (!isRecord(value) || !Array.isArray(value.items)) {
    throw new RealApiError('API_INVALID_RESPONSE', '运营记录列表格式无法识别。')
  }
  requireExactKeys(value, pageKeys, '运营记录列表包含不支持的信息。')
  if (!Number.isSafeInteger(value.offset) || (value.offset as number) < 0 || (value.offset as number) > 10_000
    || !Number.isSafeInteger(value.limit) || (value.limit as number) < 1 || (value.limit as number) > 50
    || typeof value.has_more !== 'boolean' || value.items.length > (value.limit as number)) {
    throw new RealApiError('API_INVALID_RESPONSE', '运营记录分页信息无效。')
  }
  const items = value.items.map((entry): SchoolOperationsAuditEvent => {
    if (!isRecord(entry)) throw new RealApiError('API_INVALID_RESPONSE', '运营记录格式无法识别。')
    requireExactKeys(entry, eventKeys, '运营记录包含不支持的信息。')
    const action = entry.action
    if (typeof action !== 'string' || !Object.hasOwn(auditCategoryByAction, action)) {
      throw new RealApiError('API_INVALID_RESPONSE', '运营记录操作类型无法识别。')
    }
    const category = auditCategoryByAction[action as SchoolOperationsAuditEvent['action']]
    if (entry.resource_category !== category
      || (entry.result !== 'SUCCESS' && entry.result !== 'FAILURE' && entry.result !== 'DENIED')
      || typeof entry.event_ref !== 'string'
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(entry.event_ref)
      || typeof entry.created_at !== 'string' || Number.isNaN(Date.parse(entry.created_at))) {
      throw new RealApiError('API_INVALID_RESPONSE', '运营记录字段无法识别。')
    }
    const count = entry.record_count
    if (count !== null && (!Number.isSafeInteger(count) || (count as number) < 1 || (count as number) > 100)) {
      throw new RealApiError('API_INVALID_RESPONSE', '运营记录数量信息无效。')
    }
    return {
      event_ref: entry.event_ref,
      created_at: entry.created_at,
      action: action as SchoolOperationsAuditEvent['action'],
      result: entry.result,
      resource_category: category,
      record_count: count as number | null,
    }
  })
  return {
    items,
    offset: value.offset as number,
    limit: value.limit as number,
    has_more: value.has_more,
  }
}

const mapSchoolAccountPreview = (value: unknown): SchoolAccountPreview => {
  if (!isRecord(value) || Object.keys(value).some((key) => !['valid', 'row_count', 'errors'].includes(key))
    || typeof value.valid !== 'boolean' || !Array.isArray(value.errors)) {
    throw new RealApiError('API_INVALID_RESPONSE', '账号预览格式无法识别。')
  }
  const rowCount = requiredCount(value, 'row_count')
  if (rowCount > 100) throw new RealApiError('API_INVALID_RESPONSE', '账号预览格式无法识别。')
  const errorKeys = new Set<string>()
  const errors = value.errors.map((item) => {
    const allowed = new Set(['row_no', 'code'])
    if (!isRecord(item) || Object.keys(item).some((key) => !allowed.has(key))
      || !Number.isInteger(item.row_no) || (item.row_no as number) < 1
      || typeof item.code !== 'string' || !/^[A-Z0-9_]{1,64}$/.test(item.code)) {
      throw new RealApiError('API_INVALID_RESPONSE', '账号预览包含不支持的信息。')
    }
    const errorKey = JSON.stringify([item.row_no, item.code])
    if (errorKeys.has(errorKey)) {
      throw new RealApiError('API_INVALID_RESPONSE', '账号预览包含不支持的信息。')
    }
    errorKeys.add(errorKey)
    return { row_no: item.row_no as number, code: item.code }
  })
  if (value.valid !== (errors.length === 0)) {
    throw new RealApiError('API_INVALID_RESPONSE', '账号预览状态无法识别。')
  }
  return { valid: value.valid, row_count: rowCount, errors }
}

const mapSchoolAccountBatch = (value: unknown): SchoolAccountBatch => {
  const allowed = new Set(['batch_ref', 'created_count', 'accounts'])
  if (!isRecord(value) || Object.keys(value).some((key) => !allowed.has(key)) || !Array.isArray(value.accounts)) {
    throw new RealApiError('API_INVALID_RESPONSE', '账号批次格式无法识别。')
  }
  const rowNumbers = new Set<number>()
  const accounts = value.accounts.map((item) => {
    const accountKeys = new Set(['row_no', 'user_id', 'display_name', 'role', 'status'])
    if (!isRecord(item) || Object.keys(item).some((key) => !accountKeys.has(key))
      || !Number.isInteger(item.row_no) || (item.row_no as number) < 1
      || (item.role !== 'student' && item.role !== 'teacher')
      || (item.status !== 'PENDING_ACTIVATION' && item.status !== 'ACTIVE')) {
      throw new RealApiError('API_INVALID_RESPONSE', '账号批次包含不支持的信息。')
    }
    if (rowNumbers.has(item.row_no as number) || typeof item.display_name !== 'string' || !item.display_name.trim() || item.display_name.length > 120) {
      throw new RealApiError('API_INVALID_RESPONSE', '账号批次包含不支持的信息。')
    }
    rowNumbers.add(item.row_no as number)
    return {
      row_no: item.row_no as number,
      user_id: requiredString(item, 'user_id'),
      display_name: requiredString(item, 'display_name'),
      role: item.role,
      status: item.status,
    }
  })
  const createdCount = requiredCount(value, 'created_count')
  if (createdCount !== accounts.length || createdCount > 100) {
    throw new RealApiError('API_INVALID_RESPONSE', '账号批次数量无法识别。')
  }
  return { batch_ref: requiredString(value, 'batch_ref'), created_count: createdCount, accounts }
}

const mapSchoolTask = (value: unknown): SchoolTask => {
  if (!isRecord(value)) throw new RealApiError('API_INVALID_RESPONSE', '任务列表格式无法识别。')
  const activationRef = value.activation_ref
  const planName = value.plan_name
  const planVersionNumber = value.plan_version_number
  if ((activationRef !== undefined && activationRef !== null
      && (typeof activationRef !== 'string' || !/^CACT_[A-Za-z0-9-]{36}$/.test(activationRef)))
    || (planName !== undefined && planName !== null && typeof planName !== 'string')
    || (planVersionNumber !== undefined && planVersionNumber !== null
      && (typeof planVersionNumber !== 'number' || !Number.isSafeInteger(planVersionNumber) || planVersionNumber < 1))) {
    throw new RealApiError('API_INVALID_RESPONSE', '任务版本信息格式无法识别。')
  }
  return {
    task_ref: requiredString(value, 'task_ref'),
    class_ref: requiredString(value, 'class_ref'),
    status: requiredString(value, 'status'),
    opens_at: requiredTimestamp(value, 'opens_at')!,
    due_at: requiredTimestamp(value, 'due_at', true),
    published_at: requiredTimestamp(value, 'published_at')!,
    published_enrollment_count: requiredCount(value, 'published_enrollment_count'),
    active_enrollment_count: requiredCount(value, 'active_enrollment_count'),
    revoked_enrollment_count: requiredCount(value, 'revoked_enrollment_count'),
    instrument_id: requiredString(value, 'instrument_id'),
    instrument_version: requiredString(value, 'instrument_version'),
    activation_ref: typeof activationRef === 'string' ? activationRef : null,
    plan_name: typeof planName === 'string' ? planName : null,
    plan_version_number: typeof planVersionNumber === 'number' ? planVersionNumber : null,
  }
}

const mapStudentSchoolTask = (value: unknown): StudentSchoolTask => {
  if (!isRecord(value)) throw new RealApiError('API_INVALID_RESPONSE', '学校任务列表格式无法识别。')
  const assessmentStatus = value.assessment_status
  if (assessmentStatus !== null && assessmentStatus !== undefined && !isAssessmentStatus(assessmentStatus)) {
    throw new RealApiError('API_INVALID_RESPONSE', '测评进度格式无法识别。')
  }
  if (value.assessment_id !== null && value.assessment_id !== undefined && typeof value.assessment_id !== 'string') {
    throw new RealApiError('API_INVALID_RESPONSE', '测评会话格式无法识别。')
  }
  return {
    task_ref: requiredString(value, 'task_ref'),
    class_ref: requiredString(value, 'class_ref'),
    status: requiredString(value, 'status'),
    opens_at: requiredTimestamp(value, 'opens_at')!,
    due_at: requiredTimestamp(value, 'due_at', true),
    assessment_id: nullableString(value.assessment_id),
    assessment_status: assessmentStatus ?? null,
  }
}

const mapStudentSchoolTaskHistory = (value: unknown): StudentSchoolTaskHistory => {
  const allowed = new Set([
    'task_ref', 'class_ref', 'task_status', 'enrollment_status',
    'assessment_status', 'started_at', 'completed_at',
  ])
  if (!isRecord(value) || Object.keys(value).some((key) => !allowed.has(key))) {
    throw new RealApiError('API_INVALID_RESPONSE', '任务历史包含不支持的信息，已停止展示。')
  }
  const assessmentStatus = value.assessment_status
  if (assessmentStatus !== null && assessmentStatus !== undefined && !isAssessmentStatus(assessmentStatus)) {
    throw new RealApiError('API_INVALID_RESPONSE', '任务历史状态格式无法识别。')
  }
  return {
    task_ref: requiredString(value, 'task_ref'),
    class_ref: requiredString(value, 'class_ref'),
    task_status: requiredString(value, 'task_status'),
    enrollment_status: requiredString(value, 'enrollment_status'),
    assessment_status: assessmentStatus ?? null,
    started_at: requiredTimestamp(value, 'started_at', true),
    completed_at: requiredTimestamp(value, 'completed_at', true),
  }
}

const mapTeacherTaskProgress = (value: unknown): TeacherTaskProgress => {
  const allowed = new Set([
    'class_ref', 'task_ref', 'task_status', 'opens_at', 'due_at',
    'published_enrollment_count', 'active_enrollment_count', 'revoked_enrollment_count',
    'not_started_count', 'created_count', 'in_progress_count', 'completed_count',
    'abandoned_count', 'invalid_count',
  ])
  if (!isRecord(value) || Object.keys(value).some((key) => !allowed.has(key))) {
    throw new RealApiError('API_INVALID_RESPONSE', '任务汇总包含不支持的信息，已停止展示。')
  }
  return {
    class_ref: requiredString(value, 'class_ref'),
    task_ref: requiredString(value, 'task_ref'),
    task_status: requiredString(value, 'task_status'),
    opens_at: requiredTimestamp(value, 'opens_at')!,
    due_at: requiredTimestamp(value, 'due_at', true),
    published_enrollment_count: requiredCount(value, 'published_enrollment_count'),
    active_enrollment_count: requiredCount(value, 'active_enrollment_count'),
    revoked_enrollment_count: requiredCount(value, 'revoked_enrollment_count'),
    not_started_count: requiredCount(value, 'not_started_count'),
    created_count: requiredCount(value, 'created_count'),
    in_progress_count: requiredCount(value, 'in_progress_count'),
    completed_count: requiredCount(value, 'completed_count'),
    abandoned_count: requiredCount(value, 'abandoned_count'),
    invalid_count: requiredCount(value, 'invalid_count'),
  }
}

const mapSchoolTaskEnrollment = (value: unknown): SchoolTaskEnrollment => {
  if (!isRecord(value)) throw new RealApiError('API_INVALID_RESPONSE', '报名记录格式无法识别。')
  return {
    enrollment_ref: requiredString(value, 'enrollment_ref'),
    status: requiredString(value, 'status'),
  }
}

const mapQuestion = (value: unknown): CatQuestion | null => {
  if (!isRecord(value) || typeof value.item_id !== 'string' || typeof value.prompt !== 'string') return null
  const options = Array.isArray(value.options)
    ? value.options.filter(isRecord).map((option) => ({
      value: valueAsString(option.value),
      label: valueAsString(option.label, valueAsString(option.value)),
    })).filter((option) => option.value)
    : []
  return { item_id: value.item_id, prompt: value.prompt, options }
}

const mapAssessmentState = (value: unknown): AssessmentState => {
  const source = isRecord(value) ? value : {}
  const status = valueAsString(source.status, 'created')
  return {
    assessment_id: valueAsString(source.assessment_id),
    subject_id: valueAsString(source.subject_id),
    status: status === 'completed' ? 'completed' : status === 'in_progress' ? 'in_progress' : 'created',
    current_index: typeof source.current_index === 'number' ? source.current_index : 0,
    answered_count: typeof source.answered_count === 'number' ? source.answered_count : 0,
    can_complete: Boolean(source.can_complete),
    max_items: typeof source.max_items === 'number' ? source.max_items : 0,
    question: mapQuestion(source.current_item),
  }
}

const mutationHeaders = (csrfToken: string, key: string) => ({
  'X-CSRF-Token': csrfToken,
  'Idempotency-Key': key,
})

const mapRole = (value: unknown): Role => {
  const role = valueAsString(value).toUpperCase()
  if (role === 'STUDENT') return 'student'
  if (role === 'TEACHER') return 'teacher'
  if (role === 'PSYCHOLOGICAL_SPECIALIST') return 'psychological_specialist'
  if (role === 'ADMIN') return 'school_admin'
  if (role === 'REVIEWER') return 'reviewer'
  throw new RealApiError('AUTH_ROLE_UNSUPPORTED', '服务端返回了当前界面不支持的账号角色。')
}

const mapAuthorizedRoles = (value: unknown): Role[] | undefined => {
  if (!Array.isArray(value)) return undefined
  const roles = value.flatMap((item) => {
    try { return [mapRole(item)] } catch { return [] }
  })
  return [...new Set(roles)]
}

const mapSchoolContext = (value: unknown): SchoolRoleContext => {
  if (!isRecord(value) || !valueAsString(value.school_ref)) {
    throw new RealApiError('API_INVALID_RESPONSE', '学校身份信息不完整。')
  }
  const role = mapRole(value.role)
  if (role === 'reviewer') throw new RealApiError('API_INVALID_RESPONSE', '该身份不属于学校工作区。')
  return { role, schoolRef: valueAsString(value.school_ref) }
}

const mapSchoolContexts = (value: unknown): SchoolRoleContext[] => {
  if (value === undefined) return []
  if (!Array.isArray(value)) throw new RealApiError('API_INVALID_RESPONSE', '学校身份列表格式错误。')
  return value.map(mapSchoolContext)
}

const mapAssessment = (value: unknown, assessmentId: string): Assessment => {
  const source = isRecord(value) ? value : {}
  const subjectId = valueAsString(source.subject_id)
  if (!subjectId) {
    throw new RealApiError('API_INVALID_RESPONSE', '测评响应缺少主体标识，已停止展示该记录。')
  }
  const rawDimensions = isRecord(source.dimensions) ? source.dimensions : {}
  const dimensions: Assessment['dimensions'] = {}
  for (const [key, rawValue] of Object.entries(rawDimensions)) {
    const dimension = isRecord(rawValue) ? rawValue : {}
    const theta = typeof dimension.theta === 'number' ? dimension.theta : 0
    const score = typeof dimension.score === 'number' ? dimension.score : null
    const band = dimension.band === 'attention' || dimension.band === 'normal' ? dimension.band : 'unknown'
    dimensions[key] = {
      theta,
      se: typeof dimension.se === 'number' ? dimension.se : 0,
      score,
      band,
      interpretation_status: dimension.interpretation_status === 'estimated' || dimension.interpretation_status === 'insufficient_data'
        ? dimension.interpretation_status
        : 'not_scored',
      items_answered: typeof dimension.items_answered === 'number' ? dimension.items_answered : 0,
    }
  }
  if (!isRecord(source.risk)) {
    throw new RealApiError('API_INVALID_RESPONSE', '测评响应缺少有效风险信息，已停止展示该记录。')
  }
  const riskSource = source.risk
  const allowedRiskLevels = new Set(['normal', 'attention', 'high', 'crisis'])
  if (typeof riskSource.level !== 'string' || !allowedRiskLevels.has(riskSource.level)) {
    throw new RealApiError('API_INVALID_RESPONSE', '测评响应包含无效风险等级，已停止展示该记录。')
  }
  if (typeof riskSource.need_human_review !== 'boolean') {
    throw new RealApiError('API_INVALID_RESPONSE', '测评响应缺少有效人工复核状态，已停止展示该记录。')
  }
  const timestamps = isRecord(source.timestamps) ? source.timestamps : {}
  const instrument = isRecord(source.instrument) ? source.instrument : {}
  const provenance = isRecord(source.provenance) ? source.provenance : {}
  const summary = isRecord(source.response_summary) ? source.response_summary : {}
  return {
    schema_version: 'assessment.v1',
    assessment_id: valueAsString(source.assessment_id, assessmentId),
    subject_id: subjectId,
    instrument: {
      instrument_id: valueAsString(instrument.instrument_id, 'CURRENT_SYNTHETIC_GRM'),
      version: valueAsString(instrument.version, 'synthetic_item_bank.v1 / demo.v1'),
    },
    population_scope: valueAsString(source.population_scope, '大学新生合成演示范围'),
    status: valueAsString(source.status, 'completed') as Assessment['status'],
    dimensions,
    risk: {
      level: riskSource.level as Assessment['risk']['level'],
      need_human_review: riskSource.need_human_review,
      reason_codes: Array.isArray(riskSource.reason_codes) ? riskSource.reason_codes.filter((item): item is string => typeof item === 'string') : [],
      ruleset_id: valueAsString(riskSource.ruleset_id, 'RULESET_not_exposed'),
    },
    response_summary: {
      items_answered: typeof summary.items_answered === 'number' ? summary.items_answered : 0,
      duration_seconds: typeof summary.duration_seconds === 'number' ? summary.duration_seconds : null,
    },
    provenance: {
      source_adapter: valueAsString(provenance.source_adapter, 'cat_http_adapter'),
      adapter_version: valueAsString(provenance.adapter_version, 'unknown'),
      cat_engine_version: valueAsString(provenance.cat_engine_version, 'not_exposed'),
      item_bank_version: valueAsString(provenance.item_bank_version, 'demo.v1'),
    },
    timestamps: {
      started_at: valueAsString(timestamps.started_at, new Date().toISOString()),
      completed_at: typeof timestamps.completed_at === 'string' ? timestamps.completed_at : null,
    },
  }
}

const mapAssessmentListEntry = (value: unknown): AssessmentListEntry => {
  const allowed = new Set(['assessment_id', 'status', 'items_answered', 'started_at', 'completed_at'])
  if (!isRecord(value) || Object.keys(value).some((key) => !allowed.has(key))) {
    throw new RealApiError('API_INVALID_RESPONSE', '测评列表包含不支持的信息，已停止展示。')
  }
  const startedAt = value.started_at
  const completedAt = value.completed_at
  const isTimestamp = (timestamp: unknown): timestamp is string | null =>
    timestamp === null || (typeof timestamp === 'string'
      && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(timestamp)
      && !Number.isNaN(Date.parse(timestamp)))
  if (!isAssessmentStatus(value.status)
    || !Number.isInteger(value.items_answered) || (value.items_answered as number) < 0
    || !isTimestamp(startedAt) || !isTimestamp(completedAt)) {
    throw new RealApiError('API_INVALID_RESPONSE', '测评进度格式无法识别。')
  }
  return {
    assessment_id: requiredString(value, 'assessment_id'),
    status: value.status,
    items_answered: value.items_answered as number,
    started_at: startedAt,
    completed_at: completedAt,
  }
}

const allowedGenerationStatuses = new Set<GenerationResult['status']>([
  'requested', 'safety_blocked', 'generating', 'generated', 'needs_review', 'approved', 'rejected',
])

const mapGeneration = (value: unknown, report: UnknownRecord, assessmentId: string): GenerationResult => {
  const source = isRecord(value) ? value : {}
  const statusValue = valueAsString(source.status, valueAsString(report.status, 'safety_blocked'))
  const status = allowedGenerationStatuses.has(statusValue as GenerationResult['status'])
    ? statusValue as GenerationResult['status']
    : statusValue === 'closed' ? 'approved' : 'safety_blocked'
  const rawContent = isRecord(source.content) ? source.content : null
  const content = rawContent
    ? {
      summary: valueAsString(rawContent.summary, '这份合成支持参考已准备好。'),
      observations: Array.isArray(rawContent.observations) ? rawContent.observations.filter((item): item is string => typeof item === 'string') : [],
      suggestions: Array.isArray(rawContent.suggestions)
        ? rawContent.suggestions.filter(isRecord).map((item) => ({
          text: valueAsString(item.text),
          source_chunk_ids: Array.isArray(item.source_chunk_ids)
            ? item.source_chunk_ids.filter((chunk): chunk is string => typeof chunk === 'string')
            : [],
        })).filter((item) => item.text && item.source_chunk_ids.length)
        : [],
      disclaimer: valueAsString(rawContent.disclaimer, '此内容用于教育支持，不构成诊断或治疗建议。合成案例不代表真实学生结果。'),
    }
    : null
  const safety = isRecord(source.safety) ? source.safety : {}
  const provenance = isRecord(source.provenance) ? source.provenance : {}
  const review = isRecord(source.review) ? source.review : {}
  const reviewStatus = valueAsString(review.status, valueAsString(report.review_status, 'not_required'))
  const generationStatus = provenance.generation_status === 'NOT_RUN'
    || (!rawContent && status !== 'generated') ? 'NOT_RUN' : 'EXECUTED'
  const candidateSource = provenance.candidate_source === 'CONTROLLED_SYNTHETIC'
    ? 'CONTROLLED_SYNTHETIC'
    : generationStatus === 'NOT_RUN' ? 'NOT_RUN' : 'MODEL_EXECUTED'
  return {
    schema_version: 'generation.v1',
    generation_id: valueAsString(source.generation_id, valueAsString(report.generation_id, 'GEN_not_exposed')),
    status,
    target_role: source.target_role === 'teacher' || source.target_role === 'parent' || source.target_role === 'admin' ? source.target_role : 'student',
    content,
    safety: {
      precheck: safety.precheck === 'passed' || safety.precheck === 'warn' || safety.precheck === 'needs_review' ? safety.precheck : 'blocked',
      postcheck: safety.postcheck === 'passed' || safety.postcheck === 'warn' || safety.postcheck === 'needs_review' ? safety.postcheck : 'blocked',
      reason_codes: Array.isArray(safety.reason_codes) ? safety.reason_codes.filter((item): item is string => typeof item === 'string') : [],
      human_review_required: Boolean(safety.human_review_required),
    },
    provenance: {
      assessment_id: valueAsString(provenance.assessment_id, assessmentId),
      retrieval_id: valueAsString(provenance.retrieval_id, 'RETR_not_run'),
      prompt_id: valueAsString(provenance.prompt_id, 'PROMPT_backend_support_v1'),
      prompt_version: valueAsString(provenance.prompt_version, '1.0'),
      model_id: generationStatus === 'NOT_RUN' ? null : nullableString(provenance.model_id),
      model_version: generationStatus === 'NOT_RUN' ? null : nullableString(provenance.model_version),
      runtime_version: generationStatus === 'NOT_RUN' ? null : nullableString(provenance.runtime_version),
      generation_status: generationStatus,
      candidate_source: candidateSource,
    },
    review: {
      status: reviewStatus === 'approved' || reviewStatus === 'rejected' || reviewStatus === 'pending' ? reviewStatus : 'not_required',
      reviewer_id: typeof review.reviewer_id === 'string' ? review.reviewer_id : null,
      reviewed_at: typeof review.reviewed_at === 'string' ? review.reviewed_at : null,
    },
    created_at: valueAsString(source.created_at, new Date().toISOString()),
  }
}

const citationsFromApi = (value: unknown): Citation[] => {
  if (!Array.isArray(value)) return []
  return value.filter(isRecord).map((item, index) => ({
    citation_id: valueAsString(item.citation_id, `CITE_unavailable_${index + 1}`),
    chunk_id: nullableString(item.chunk_id),
    document_id: nullableString(item.document_id),
    title: nullableString(item.title),
    organization: nullableString(item.organization),
    locator: nullableString(item.locator),
    excerpt: nullableString(item.excerpt),
  }))
}

const mapReport = (rawReport: unknown, rawAssessment: unknown): StudentReportViewModel => {
  const report = isRecord(rawReport) ? rawReport : {}
  const assessmentId = valueAsString(report.assessment_id)
  const assessment = mapAssessment(rawAssessment, assessmentId)
  const generation = mapGeneration(report.generation, report, assessmentId)
  const actions = generation.content?.suggestions.map((suggestion, index) => ({
    number: String(index + 1).padStart(2, '0'),
    title: `从一个小步骤开始 ${index + 1}`,
    body: suggestion.text,
  })) || []
  const dimensions = Object.entries(assessment.dimensions).map(([key, dimension], index) => ({
    key,
    label: `维度 ${String.fromCharCode(65 + index)} · 合成占位`,
    value: dimension.score ?? Math.max(0, Math.min(100, Math.round(50 + dimension.theta * 12))),
    helper: '结构估计 · 非诊断',
  }))
  return {
    fixtureLabel: SYNTHETIC_FIXTURE_LABEL,
    report: {
      reportId: valueAsString(report.report_id),
      assessmentId,
      generation,
      assessment,
    },
    meaning: {
      title: '把这份结构当作下一步的参考',
      body: '这份页面只承载合成测评与支持流程的结构，不把结果解释成疾病、诊断或确定性标签。',
      note: '真实部署时，展示范围由后端授权与安全披露策略共同决定。',
    },
    data: {
      title: '本次测评的结构',
      body: '维度名称与数值只用于展示接口如何承载结构化结果，不代表经过确认的心理学维度。',
      dimensions,
    },
    actions,
    evidence: citationsFromApi(report.citations),
  }
}

const mapReviewStatus = (value: unknown): ReviewCase['status'] => {
  const status = valueAsString(value, 'pending').toUpperCase()
  return status === 'IN_REVIEW' || status === 'APPROVED' || status === 'REJECTED' ? status : 'PENDING'
}

const mapReviewCase = (value: unknown): ReviewCase => {
  const source = isRecord(value) ? value : {}
  const reviewId = valueAsString(source.review_id, 'REVIEW_REDACTED')
  const action = valueAsString(source.safety_action, 'REVIEW_REQUIRED')
  const highPriority = action === 'CRISIS_ROUTE'
  const timestamp = new Date().toISOString()
  return {
    review_case_id: valueAsString(source.safety_review_case_id, reviewId),
    review_id: reviewId,
    case_id: null,
    decision_id: 'DECISION_REDACTED',
    trace_id: 'TRACE_REDACTED',
    status: mapReviewStatus(source.status),
    reason_codes: Array.isArray(source.reason_codes) ? source.reason_codes.filter((item): item is string => typeof item === 'string') : ['HUMAN_REVIEW_REQUIRED'],
    priority: highPriority ? 'CRITICAL' : 'HIGH',
    assigned_role: 'REVIEWER',
    disclosure_policy: 'REDACTED',
    subject_id: 'SUBJ_REDACTED',
    report_id: valueAsString(source.report_id, 'REPORT_REDACTED'),
    created_at: timestamp,
    updated_at: timestamp,
    generationStatus: 'needs_review',
    summary: `安全流程 ${action}，普通个性化生成已暂停，等待人工确认。`,
    safeContext: '仅展示后端授权的最小摘要。原始回答、身份信息和完整模型上下文不在此页面。',
  }
}

export interface IndependentConversationRequest {
  method: 'GET' | 'POST'
  path: string
  query?: { offset?: number; limit?: number }
  body?: Record<string, unknown>
  idempotencyKey?: string
}

export interface IndependentEducationReviewRequest {
  method: 'GET' | 'POST'
  path: string
  query?: { offset?: number; limit?: number }
  body?: Record<string, unknown>
  idempotencyKey?: string
}

export class RealApiProvider implements FrontendApi {
  private csrfToken = ''
  private actorSubjectId: string | null = null
  private activeSchoolContext: SchoolRoleContext | null = null
  private readonly reviewCases = new Map<string, ReviewCase>()

  async requestSchoolCatSavedSimulation<T>(input: {
    path: string; body: Record<string, unknown>
  }): Promise<ApiEnvelope<T>> {
    if (!/^\/api\/v1\/school\/cat-assets\/plan-versions\/CPVER_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}\/simulations$/.test(input.path)) {
      throw new RealApiError('API_INVALID_REQUEST', '保存方案的模拟请求地址无效。')
    }
    await this.ensureCsrfToken()
    return unwrap<T>(() => apiClient.request({
      method: 'POST', url: input.path, body: input.body,
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': this.csrfToken! },
    }))
  }

  async requestSchoolCatAssets<T>(input: {
    method: 'GET' | 'POST' | 'PATCH'; path: string; body?: Record<string, unknown>
    query?: Record<string, unknown>; idempotencyKey?: string
  }): Promise<ApiEnvelope<T>> {
    const base = '/api/v1/school/cat-assets'
    const resource = `${base}/(?:banks/CBANK_|plans/CPLAN_)[A-Za-z0-9][A-Za-z0-9_.-]{0,122}`
    const collection = input.path === `${base}/banks` || input.path === `${base}/plans`
    const detail = new RegExp(`^${resource}$`).test(input.path)
    const version = new RegExp(`^${base}/(?:bank-versions/CBVER_|plan-versions/CPVER_)[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$`).test(input.path)
    const activationCollection = input.path === `${base}/activations`
    const activationDetail = new RegExp(`^${base}/activations/CACT_[A-Za-z0-9-]{36}$`).test(input.path)
    const createActivation = new RegExp(`^${base}/plan-versions/CPVER_[A-Za-z0-9-]{36}/activations$`).test(input.path)
    const allowed = input.method === 'GET'
      ? collection || detail || version || activationCollection || input.path === `${base}/template`
      : input.method === 'POST'
        ? collection || new RegExp(`^${resource}/versions$`).test(input.path) || createActivation
        : input.method === 'PATCH' && (detail || activationDetail)
    if (!allowed) throw new RealApiError('API_INVALID_REQUEST', '题库与方案请求地址无效。')
    if (input.method !== 'GET' && !input.idempotencyKey?.trim()) {
      throw new RealApiError('API_INVALID_REQUEST', '题库与方案请求缺少操作标识。')
    }
    if (input.method !== 'GET') await this.ensureCsrfToken()
    return unwrap<T>(() => apiClient.request({
      method: input.method, url: input.path,
      ...(input.body ? { body: input.body } : {}),
      ...(input.query ? { query: input.query } : {}),
      headers: input.method !== 'GET'
        ? { 'Content-Type': 'application/json', ...mutationHeaders(this.csrfToken, input.idempotencyKey!) }
        : {},
    }))
  }

  async requestSchoolCatManagement<T>(input: {
    method: 'GET' | 'POST'; path: string; body?: Record<string, unknown>
  }): Promise<ApiEnvelope<T>> {
    const base = '/api/v1/school/cat-management'
    if (!((input.method === 'GET' && input.path === `${base}/catalog`)
      || (input.method === 'POST' && input.path === `${base}/simulations`))) {
      throw new RealApiError('API_INVALID_REQUEST', '测评方案请求地址无效。')
    }
    if (input.method === 'POST') await this.ensureCsrfToken()
    return unwrap<T>(() => apiClient.request({
      method: input.method, url: input.path,
      ...(input.body ? { body: input.body } : {}),
      headers: input.method === 'POST'
        ? { 'Content-Type': 'application/json', 'X-CSRF-Token': this.csrfToken! }
        : {},
    }))
  }

  async requestProfessionalReview<T>(input: IndependentConversationRequest): Promise<ApiEnvelope<T>> {
    const base = '/api/v1/school/professional-reviews'
    const task = `${base}/tasks/TASK_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}`
    const casePath = `${task}/cases/PCR_[A-Za-z0-9][A-Za-z0-9_.-]{0,123}`
    const allowed = input.method === 'GET'
      ? input.path === `${base}/tasks` || input.path === `${base}/assignments` || input.path === `${base}/specialists`
        || new RegExp(`^${task}/(?:cases|eligible-enrollments)$`).test(input.path)
        || new RegExp(`^${casePath}$`).test(input.path)
      : new RegExp(`^${task}/(?:cases|assignments)$`).test(input.path)
        || new RegExp(`^${casePath}/(?:open|decision)$`).test(input.path)
        || new RegExp(`^${task}/assignments/ASSIGN_[A-Za-z0-9][A-Za-z0-9_.-]{0,120}/revoke$`).test(input.path)
    if (!allowed || !['GET', 'POST'].includes(input.method)) {
      throw new RealApiError('API_INVALID_REQUEST', '专业工作请求地址无效。')
    }
    if (input.method === 'POST' && !input.idempotencyKey?.trim()) {
      throw new RealApiError('API_INVALID_REQUEST', '专业工作请求缺少操作标识。')
    }
    if (input.method === 'POST') await this.ensureCsrfToken()
    return unwrap<T>(() => apiClient.request({
      method: input.method, url: input.path,
      ...(input.query ? { query: input.query } : {}),
      ...(input.body ? { body: input.body } : {}),
      headers: input.method === 'POST'
        ? { 'Content-Type': 'application/json', ...mutationHeaders(this.csrfToken, input.idempotencyKey!) }
        : {},
    }))
  }

  async requestIndependentConversation<T>(input: IndependentConversationRequest): Promise<ApiEnvelope<T>> {
    const match = /^\/api\/v1\/student\/(conversations|research-conversations)(?:\/(CONV_[A-Za-z0-9][A-Za-z0-9_.-]{0,122})(\/messages)?|\/capability)?$/.exec(input.path)
    const isCapability = input.path === '/api/v1/student/research-conversations/capability'
    const isCollection = Boolean(match && !match[2] && !input.path.endsWith('/capability'))
    const isDetail = Boolean(match?.[2] && !match[3])
    const isMessages = Boolean(match?.[2] && match[3])
    if (!(input.method === 'GET' ? isCollection || isDetail || isCapability : isCollection || isMessages)) {
      throw new RealApiError('API_INVALID_REQUEST', '教育支持请求地址无效。')
    }
    if (input.method === 'POST' && !input.idempotencyKey?.trim()) {
      throw new RealApiError('API_INVALID_REQUEST', '教育支持请求缺少操作标识。')
    }
    if (input.method === 'POST') await this.ensureCsrfToken()
    return unwrap<T>(() => apiClient.request({
      method: input.method,
      url: input.path,
      ...(input.query ? { query: input.query } : {}),
      ...(input.body ? { body: input.body } : {}),
      headers: input.method === 'POST'
        ? { 'Content-Type': 'application/json', ...mutationHeaders(this.csrfToken, input.idempotencyKey!) }
        : {},
    }))
  }

  async requestIndependentEducationReview<T>(input: IndependentEducationReviewRequest): Promise<ApiEnvelope<T>> {
    const conversationRef = 'CONV_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}'
    const reviewRef = 'EDUREV_[0-9a-f]{32}'
    const studentBase = new RegExp(`^/api/v1/student/research-conversations/${conversationRef}/education-reviews$`)
    const studentReviewAction = new RegExp(`^/api/v1/student/research-conversations/${conversationRef}/education-reviews/${reviewRef}/(?:share|withdraw)$`)
    const studentReviewers = new RegExp(`^/api/v1/student/research-conversations/${conversationRef}/education-reviewers$`)
    const specialistPath = new RegExp(`^/api/v1/school/independent-education-reviews(?:/${reviewRef}(?:/(?:draft|publish|revoke))?)?$`)
    const isStudentList = studentBase.test(input.path)
    const isStudentReviewers = studentReviewers.test(input.path)
    const isStudentMutation = studentReviewAction.test(input.path)
    const isSpecialistPath = specialistPath.test(input.path)
    const isSpecialistRead = isSpecialistPath
      && !new RegExp(`^/api/v1/school/independent-education-reviews/${reviewRef}/(?:draft|publish|revoke)$`).test(input.path)
    const isSpecialistMutation = new RegExp(`^/api/v1/school/independent-education-reviews/${reviewRef}/(?:draft|publish|revoke)$`).test(input.path)
    const allowed = input.method === 'GET'
      ? isStudentList || isStudentReviewers || isSpecialistRead
      : isStudentMutation || isSpecialistMutation
    if (!allowed) {
      throw new RealApiError('API_INVALID_REQUEST', '独立研究教育复核请求地址无效。')
    }
    if (input.method === 'POST' && !input.idempotencyKey?.trim()) {
      throw new RealApiError('API_INVALID_REQUEST', '独立研究教育复核请求缺少操作标识。')
    }
    if (input.method === 'POST') await this.ensureCsrfToken()
    return unwrap<T>(() => apiClient.request({
      method: input.method,
      url: input.path,
      ...(input.query ? { query: input.query } : {}),
      ...(input.body ? { body: input.body } : {}),
      headers: input.method === 'POST'
        ? { 'Content-Type': 'application/json', ...mutationHeaders(this.csrfToken, input.idempotencyKey!) }
        : {},
    }))
  }

  private projectActor(actor: UnknownRecord, fallbackName = '工作区用户'): LoginResult {
    const contexts = mapSchoolContexts(actor.available_contexts)
    const active = actor.active_context == null ? null : mapSchoolContext(actor.active_context)
    const role = mapRole(actor.role)
    if (active && (active.role !== role || !contexts.some((item) => item.role === active.role && item.schoolRef === active.schoolRef))) {
      throw new RealApiError('API_INVALID_RESPONSE', '当前学校身份与授权列表不一致。')
    }
    const subjectId = nullableString(actor.subject_id)
    const name = valueAsString(actor.username, fallbackName)
    return {
      userId: valueAsString(actor.user_id), role,
      authorizedRoles: mapAuthorizedRoles(actor.authorized_roles),
      subjectId, displayName: name,
      initials: name.slice(0, 1).toUpperCase(),
      ...(contexts.length ? { availableContexts: contexts, activeContext: active } : {}),
    }
  }

  async switchActiveContext(context: SchoolRoleContext): Promise<ApiEnvelope<LoginResult>> {
    this.activeSchoolContext = null
    await this.ensureCsrfToken()
    const response = await unwrap<UnknownRecord>(() => apiClient.request({
      method: 'POST', url: '/api/v1/auth/active-context',
      body: { role: context.role === 'school_admin' ? 'ADMIN' : context.role.toUpperCase(), school_ref: context.schoolRef },
      headers: { 'Content-Type': 'application/json', ...mutationHeaders(this.csrfToken, nowToken('frontend-auth-context')) },
    }))
    const data = this.projectActor(response.data)
    if (data.activeContext?.role !== context.role || data.activeContext.schoolRef !== context.schoolRef) {
      throw new RealApiError('API_INVALID_RESPONSE', '学校身份尚未激活，请重试。')
    }
    this.actorSubjectId = data.subjectId
    this.activeSchoolContext = data.activeContext ?? null
    this.reviewCases.clear()
    return { ...response, data }
  }

  private async ensureCsrfToken(): Promise<string> {
    if (this.csrfToken) return this.csrfToken
    const response = await unwrap<{ csrf_token: string }>(() => authCsrf({ client: apiClient }))
    this.csrfToken = response.data.csrf_token
    return this.csrfToken
  }

  async login(input: LoginInput): Promise<ApiEnvelope<LoginResult>> {
    this.actorSubjectId = null
    this.activeSchoolContext = null
    const response = await unwrap<UnknownRecord>(() => authLogin({
      client: apiClient,
      body: { username: input.account, password: input.password },
    }))
    const actor = isRecord(response.data.actor) ? response.data.actor : {}
    this.csrfToken = valueAsString(response.data.csrf_token)
    this.reviewCases.clear()
    const data = this.projectActor(actor, input.account)
    this.actorSubjectId = data.subjectId
    this.activeSchoolContext = data.activeContext ?? null
    if (data.availableContexts?.length === 1 && !data.activeContext) return this.switchActiveContext(data.availableContexts[0]!)
    return { ...response, data }
  }

  async logout(): Promise<ApiEnvelope<{ logged_out: boolean }>> {
    await this.ensureCsrfToken()
    const response = await unwrap<{ logged_out: boolean }>(() => authLogout({
      client: apiClient,
      headers: mutationHeaders(this.csrfToken, nowToken('frontend-auth-logout')),
    }))
    this.csrfToken = ''
    this.actorSubjectId = null
    this.activeSchoolContext = null
    this.reviewCases.clear()
    return response
  }

  async getCurrentUser(): Promise<ApiEnvelope<LoginResult | null>> {
    this.actorSubjectId = null
    this.activeSchoolContext = null
    const response = await unwrap<UnknownRecord>(() => authMe({ client: apiClient }))
    const actor = isRecord(response.data.actor) ? response.data.actor : response.data
    const userId = valueAsString(actor.user_id)
    if (!userId) {
      this.actorSubjectId = null
      this.activeSchoolContext = null
      this.reviewCases.clear()
      return { ...response, data: null }
    }
    const data = this.projectActor(actor)
    this.actorSubjectId = data.subjectId
    this.activeSchoolContext = data.activeContext ?? null
    if (data.availableContexts?.length === 1 && !data.activeContext) return this.switchActiveContext(data.availableContexts[0]!)
    return { ...response, data }
  }

  async getStudentHome(): Promise<ApiEnvelope<StudentHomeViewModel | null>> {
    const response = await unwrap<UnknownRecord>(() => authMe({ client: apiClient }))
    return { ...response, data: null }
  }

  async listAssessments(params?: AssessmentListParams): Promise<ApiEnvelope<Assessment[]>> {
    const query = new URLSearchParams()
    if (params?.limit !== undefined) query.set('limit', String(params.limit))
    if (params?.skip !== undefined) query.set('skip', String(params.skip))
    if (params?.status !== undefined) query.set('status', params.status)
    const queryString = query.toString()
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET',
      url: `/api/v1/assessments${queryString ? `?${queryString}` : ''}`,
      parseAs: 'json',
    }))
    const rows = Array.isArray(response.data) ? response.data : []
    return { ...response, data: rows.map((row) => {
      const source = isRecord(row) ? row : {}
      return mapAssessment(source, valueAsString(source.assessment_id))
    }) }
  }

  async listAssessmentEntries(params?: AssessmentListParams): Promise<ApiEnvelope<AssessmentListEntry[]>> {
    if (this.activeSchoolContext?.role === 'student') {
      const query = new URLSearchParams()
      if (params?.limit !== undefined) query.set('limit', String(params.limit))
      if (params?.skip !== undefined) query.set('skip', String(params.skip))
      if (params?.status !== undefined) query.set('status', params.status)
      const queryString = query.toString()
      const response = await unwrap<unknown>(() => apiClient.request({
        method: 'GET',
        url: `/api/v1/school/assessments${queryString ? `?${queryString}` : ''}`,
        parseAs: 'json',
      }))
      if (!Array.isArray(response.data)) throw new RealApiError('API_INVALID_RESPONSE', '测评列表格式无法识别。')
      return { ...response, data: response.data.map(mapAssessmentListEntry) }
    }

    const response = await this.listAssessments(params)
    return {
      ...response,
      data: response.data.map((assessment) => ({
        assessment_id: assessment.assessment_id,
        status: assessment.status,
        items_answered: assessment.response_summary.items_answered,
        started_at: assessment.timestamps.started_at,
        completed_at: assessment.timestamps.completed_at,
      })),
    }
  }

  async getAssessmentState(assessmentId: string): Promise<ApiEnvelope<AssessmentState>> {
    const response = await unwrap<unknown>(() => getAssessmentState({
      client: apiClient,
      path: { assessment_id: assessmentId },
    }))
    return { ...response, data: mapAssessmentState(response.data) }
  }

  async getAssessmentResult(assessmentId: string): Promise<ApiEnvelope<Assessment>> {
    const response = await unwrap<unknown>(() => getAssessment({ client: apiClient, path: { assessment_id: assessmentId } }))
    const source = isRecord(response.data) ? response.data : {}
    return {
      ...response,
      data: mapAssessment(source, assessmentId),
    }
  }

  async listReports(assessmentId?: string): Promise<ApiEnvelope<{ items: ReportSummary[]; next_cursor: string | null }>> {
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET',
      url: '/api/v1/reports',
      query: { assessment_id: assessmentId, limit: 100 },
      parseAs: 'json',
    }))
    const data = isRecord(response.data) ? response.data : {}
    const items = Array.isArray(data.items) ? data.items.filter(isRecord).map((item) => ({
      report_id: valueAsString(item.report_id),
      assessment_id: valueAsString(item.assessment_id),
      status: valueAsString(item.status, 'unknown'),
      safety_action: nullableString(item.safety_action),
      created_at: valueAsString(item.created_at),
      citation_count: typeof item.citation_count === 'number' ? item.citation_count : 0,
    })) : []
    return { ...response, data: { items, next_cursor: nullableString(data.next_cursor) } }
  }

  async startAssessment(assessmentId?: string): Promise<ApiEnvelope<AssessmentState>> {
    if (assessmentId) return this.getAssessmentState(assessmentId)
    if (this.activeSchoolContext) {
      throw new RealApiError('SCHOOL_TASK_REQUIRED', '请选择当前开放的学校测评任务。')
    }
    if (!this.actorSubjectId) {
      throw new RealApiError('AUTH_SUBJECT_MISSING', '当前登录账号缺少授权的合成主体标识，无法创建测评。')
    }
    await this.ensureCsrfToken()
    const created = await unwrap<unknown>(() => createAssessment({
      client: apiClient,
      body: {
        subject_id: this.actorSubjectId,
        instrument_id: 'CURRENT_SYNTHETIC_GRM',
        instrument_version: 'synthetic_item_bank.v1 / demo.v1',
      },
      headers: mutationHeaders(this.csrfToken, nowToken('frontend-assessment-create')),
    }))
    const createdAssessment = isRecord(created.data) ? created.data : {}
    const createdAssessmentId = valueAsString(createdAssessment.assessment_id)
    if (!createdAssessmentId) throw new RealApiError('API_INVALID_RESPONSE', '接口没有返回测评会话标识。')
    const state = await unwrap<unknown>(() => getAssessmentState({
      client: apiClient,
      path: { assessment_id: createdAssessmentId },
    }))
    return { ...state, data: mapAssessmentState(state.data) }
  }

  async submitAssessmentResponse(assessmentId: string, itemId: string, response: string): Promise<ApiEnvelope<AssessmentState>> {
    await this.ensureCsrfToken()
    const result = await unwrap<unknown>(() => recordAssessmentResponse({
      client: apiClient,
      path: { assessment_id: assessmentId },
      body: { item_id: itemId, response },
      headers: mutationHeaders(this.csrfToken, nowToken(`frontend-assessment-response-${assessmentId}`)),
    }))
    return { ...result, data: mapAssessmentState(result.data) }
  }

  async completeAssessment(assessmentId: string): Promise<ApiEnvelope<Assessment>> {
    await this.ensureCsrfToken()
    const response = await unwrap<unknown>(() => completeAssessment({
      client: apiClient,
      path: { assessment_id: assessmentId },
      body: {},
      headers: mutationHeaders(this.csrfToken, nowToken(`frontend-assessment-complete-${assessmentId}`)),
    }))
    return { ...response, data: mapAssessment(response.data, assessmentId) }
  }

  private async schoolWrite(
    path: string,
    body: unknown,
    operation: string,
    idempotencyKey = nowToken(`frontend-school-${operation}`),
  ): Promise<ApiEnvelope<unknown>> {
    await this.ensureCsrfToken()
    return unwrap<unknown>(() => apiClient.request({
      method: 'POST',
      url: path,
      body,
      parseAs: 'json',
      headers: {
        'Content-Type': 'application/json',
        ...mutationHeaders(this.csrfToken, idempotencyKey),
      },
    }))
  }

  async getSchoolAdminDirectory(): Promise<ApiEnvelope<SchoolDirectory>> {
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET', url: '/api/v1/school/admin/directory', parseAs: 'json',
    }))
    return { ...response, data: mapSchoolDirectory(response.data) }
  }

  async listSchoolOperationsAudit(params: {
    offset: number
    limit: number
    category?: SchoolOperationsAuditCategory | null
    signal?: AbortSignal
  }): Promise<ApiEnvelope<SchoolOperationsAuditPage>> {
    const { offset, limit, category = null, signal } = params
    const validCategories: SchoolOperationsAuditCategory[] = [
      'organization', 'class', 'member', 'account_batch', 'account', 'task',
    ]
    if (!Number.isSafeInteger(offset) || offset < 0 || offset > 10_000
      || !Number.isSafeInteger(limit) || limit < 1 || limit > 50
      || (category !== null && !validCategories.includes(category))) {
      throw new RealApiError('API_INVALID_REQUEST', '运营记录查询范围无效。')
    }
    const query = new URLSearchParams({ offset: String(offset), limit: String(limit) })
    if (category) query.set('category', category)
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET',
      url: `/api/v1/school/operations-audit?${query.toString()}`,
      signal,
      parseAs: 'json',
    }))
    const data = mapSchoolOperationsAudit(response.data)
    if (data.offset !== offset || data.limit !== limit
      || (category !== null && data.items.some((item) => item.resource_category !== category))) {
      throw new RealApiError('API_INVALID_RESPONSE', '运营记录与当前查询不匹配。')
    }
    return { ...response, data }
  }

  async updateSchoolDisplayName(displayName: string): Promise<ApiEnvelope<unknown>> {
    return this.schoolWrite('/api/v1/school/admin/school/name', { display_name: displayName }, 'school-name')
  }

  async updateSchoolClassDisplayName(classRef: string, displayName: string): Promise<ApiEnvelope<unknown>> {
    return this.schoolWrite(
      `/api/v1/school/admin/classes/${encodeURIComponent(classRef)}/name`,
      { display_name: displayName }, 'class-name',
    )
  }

  async updateSchoolMemberDisplayName(userId: string, displayName: string): Promise<ApiEnvelope<unknown>> {
    return this.schoolWrite(
      `/api/v1/school/admin/members/${encodeURIComponent(userId)}/name`,
      { display_name: displayName }, 'member-name',
    )
  }

  async previewSchoolAccountImport(
    classRef: string | null,
    rows: SchoolAccountImportRow[],
  ): Promise<ApiEnvelope<SchoolAccountPreview>> {
    await this.ensureCsrfToken()
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'POST',
      url: '/api/v1/school/admin/accounts/preview',
      body: { class_ref: classRef, rows },
      parseAs: 'json',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': this.csrfToken },
    }))
    return { ...response, data: mapSchoolAccountPreview(response.data) }
  }

  async importSchoolAccounts(
    classRef: string | null,
    rows: SchoolAccountImportRow[],
    idempotencyKey: string,
  ): Promise<ApiEnvelope<SchoolAccountBatch>> {
    await this.ensureCsrfToken()
    const raw = await apiClient.request({
      method: 'POST',
      url: '/api/v1/school/admin/accounts/import',
      body: { class_ref: classRef, rows },
      parseAs: 'json',
      headers: {
        'Content-Type': 'application/json',
        ...mutationHeaders(this.csrfToken, idempotencyKey),
      },
    })
    if (isRecord(raw) && isRecord(raw.response) && raw.response.status === 409) {
      const body = raw.error
      const envelope = isRecord(body) && typeof body.request_id === 'string' && isRecord(body.data)
        ? body
        : isRecord(body) && isRecord(body.data) && typeof body.data.request_id === 'string' && isRecord(body.data.data)
          ? body.data
          : null
      if (envelope) {
        try {
          const preview = mapSchoolAccountPreview(envelope.data)
          if (!preview.valid && preview.errors.length > 0) {
            throw new RealApiError(
              'SCHOOL_ACCOUNT_IMPORT_REJECTED',
              '导入前服务端发现数据已变化，请重新预览。',
              false,
              preview,
            )
          }
        } catch (error) {
          if (error instanceof RealApiError && error.code === 'SCHOOL_ACCOUNT_IMPORT_REJECTED') throw error
        }
      }
    }
    const response = await unwrap<unknown>(async () => raw)
    return { ...response, data: mapSchoolAccountBatch(response.data) }
  }

  async getSchoolAccountBatch(batchRef: string): Promise<ApiEnvelope<SchoolAccountBatch>> {
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET',
      url: `/api/v1/school/admin/accounts/batches/${encodeURIComponent(batchRef)}`,
      parseAs: 'json',
    }))
    return { ...response, data: mapSchoolAccountBatch(response.data) }
  }

  async activateSchoolAccount(userId: string, newPassword: string): Promise<ApiEnvelope<unknown>> {
    await this.ensureCsrfToken()
    return unwrap<unknown>(() => apiClient.request({
      method: 'POST',
      url: `/api/v1/school/admin/accounts/${encodeURIComponent(userId)}/activate`,
      body: { new_password: newPassword },
      parseAs: 'json',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': this.csrfToken },
    }))
  }

  async listSchoolClasses(params: { signal?: AbortSignal } = {}): Promise<ApiEnvelope<SchoolClass[]>> {
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET', url: '/api/v1/school/classes', signal: params.signal, parseAs: 'json',
    }))
    if (!Array.isArray(response.data)) throw new RealApiError('API_INVALID_RESPONSE', '班级列表格式无法识别。')
    return { ...response, data: response.data.map(mapSchoolClass) }
  }

  async listSchoolMembers(role: SchoolMemberRole): Promise<ApiEnvelope<SchoolMember[]>> {
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET',
      url: '/api/v1/school/members',
      query: { role },
      parseAs: 'json',
    }))
    if (!Array.isArray(response.data)) throw new RealApiError('API_INVALID_RESPONSE', '人员列表格式无法识别。')
    return { ...response, data: response.data.map(mapSchoolMember) }
  }

  async createSchoolClass(classRef: string): Promise<ApiEnvelope<SchoolClass>> {
    const response = await this.schoolWrite('/api/v1/school/classes', { class_ref: classRef }, 'class-create')
    return { ...response, data: mapSchoolClass(response.data) }
  }

  async assignSchoolStudent(classRef: string, studentUserId: string): Promise<ApiEnvelope<unknown>> {
    return this.schoolWrite(
      `/api/v1/school/classes/${encodeURIComponent(classRef)}/students`,
      { student_user_id: studentUserId },
      `class-${classRef}-student`,
    )
  }

  async assignSchoolTeacher(classRef: string, teacherUserId: string): Promise<ApiEnvelope<unknown>> {
    return this.schoolWrite(
      `/api/v1/school/classes/${encodeURIComponent(classRef)}/teachers`,
      { teacher_user_id: teacherUserId },
      `class-${classRef}-teacher`,
    )
  }

  async listSchoolTasks(classRef: string): Promise<ApiEnvelope<SchoolTask[]>> {
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET',
      url: `/api/v1/school/classes/${encodeURIComponent(classRef)}/tasks`,
      parseAs: 'json',
    }))
    if (!Array.isArray(response.data)) throw new RealApiError('API_INVALID_RESPONSE', '任务列表格式无法识别。')
    return { ...response, data: response.data.map(mapSchoolTask) }
  }

  async publishSchoolTask(
    classRef: string,
    opensAt: string,
    dueAt: string | null,
    activationRef?: string | null,
  ): Promise<ApiEnvelope<SchoolTask>> {
    if (activationRef !== undefined && activationRef !== null
      && !/^CACT_[A-Za-z0-9-]{36}$/.test(activationRef)) {
      throw new RealApiError('API_INVALID_REQUEST', '启用记录编号无效。')
    }
    const response = await this.schoolWrite(
      `/api/v1/school/classes/${encodeURIComponent(classRef)}/tasks`,
      { opens_at: opensAt, due_at: dueAt, ...(activationRef ? { activation_ref: activationRef } : {}) },
      `class-${classRef}-task-publish`,
    )
    return { ...response, data: mapSchoolTask(response.data) }
  }

  async listStudentSchoolTasks(): Promise<ApiEnvelope<StudentSchoolTask[]>> {
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET', url: '/api/v1/school/tasks/student', parseAs: 'json',
    }))
    if (!Array.isArray(response.data)) throw new RealApiError('API_INVALID_RESPONSE', '学校任务列表格式无法识别。')
    return { ...response, data: response.data.map(mapStudentSchoolTask) }
  }

  async listStudentSchoolTaskHistory(): Promise<ApiEnvelope<StudentSchoolTaskHistory[]>> {
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET', url: '/api/v1/school/tasks/student/history', parseAs: 'json',
    }))
    if (!Array.isArray(response.data)) throw new RealApiError('API_INVALID_RESPONSE', '任务历史格式无法识别。')
    return { ...response, data: response.data.map(mapStudentSchoolTaskHistory) }
  }

  async startStudentSchoolTask(taskRef: string): Promise<ApiEnvelope<SchoolTaskStart>> {
    const response = await this.schoolWrite(
      `/api/v1/school/tasks/${encodeURIComponent(taskRef)}/start`,
      {},
      `task-${taskRef}-start`,
    )
    if (!isRecord(response.data)) throw new RealApiError('API_INVALID_RESPONSE', '测评会话格式无法识别。')
    const source = response.data
    if (!isAssessmentStatus(source.status)) throw new RealApiError('API_INVALID_RESPONSE', '测评进度格式无法识别。')
    const currentItem = source.current_item === null ? null : mapQuestion(source.current_item)
    if (source.current_item !== null && !currentItem) throw new RealApiError('API_INVALID_RESPONSE', '当前题目格式无法识别。')
    if (typeof source.can_complete !== 'boolean') throw new RealApiError('API_INVALID_RESPONSE', '测评进度格式无法识别。')
    const maxItems = source.max_items === null ? null : requiredCount(source, 'max_items')
    if (source.selected_item_id !== null && source.selected_item_id !== undefined && typeof source.selected_item_id !== 'string') {
      throw new RealApiError('API_INVALID_RESPONSE', '当前题目格式无法识别。')
    }
    return {
      ...response,
      data: {
        task_ref: requiredString(source, 'task_ref'),
        assessment_id: requiredString(source, 'assessment_id'),
        subject_id: requiredString(source, 'subject_id'),
        status: source.status,
        selected_item_id: nullableString(source.selected_item_id),
        current_item: currentItem,
        answered_count: requiredCount(source, 'answered_count'),
        administered_count: requiredCount(source, 'administered_count'),
        can_complete: source.can_complete,
        max_items: maxItems,
      },
    }
  }

  async listTeacherSchoolTaskProgress(): Promise<ApiEnvelope<TeacherTaskProgress[]>> {
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET', url: '/api/v1/school/teacher/task-progress', parseAs: 'json',
    }))
    if (!Array.isArray(response.data)) throw new RealApiError('API_INVALID_RESPONSE', '任务汇总格式无法识别。')
    return { ...response, data: response.data.map(mapTeacherTaskProgress) }
  }

  async listSchoolTaskEnrollments(taskRef: string): Promise<ApiEnvelope<SchoolTaskEnrollment[]>> {
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET',
      url: `/api/v1/school/tasks/${encodeURIComponent(taskRef)}/enrollments`,
      parseAs: 'json',
    }))
    if (!Array.isArray(response.data)) throw new RealApiError('API_INVALID_RESPONSE', '报名列表格式无法识别。')
    return { ...response, data: response.data.map(mapSchoolTaskEnrollment) }
  }

  async revokeSchoolTaskEnrollment(taskRef: string, enrollmentRef: string): Promise<ApiEnvelope<SchoolTaskEnrollment>> {
    const response = await this.schoolWrite(
      `/api/v1/school/tasks/${encodeURIComponent(taskRef)}/enrollments/${encodeURIComponent(enrollmentRef)}/revoke`,
      {},
      `task-${taskRef}-revoke`,
    )
    return { ...response, data: mapSchoolTaskEnrollment(response.data) }
  }

  async listResearchProfileCatalog(params: { signal?: AbortSignal } = {}): Promise<ApiEnvelope<ResearchProfileCandidate[]>> {
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET', url: '/api/v1/school/research-profiles/catalog', signal: params.signal, parseAs: 'json',
    }))
    if (!Array.isArray(response.data)) throw new RealApiError('API_INVALID_RESPONSE', '研究资料目录格式无法识别。')
    return { ...response, data: response.data.map(mapResearchProfileCandidate) }
  }

  async listResearchSourceCatalog(
    params: { limit?: number; offset?: number; signal?: AbortSignal } = {},
  ): Promise<ApiEnvelope<ResearchSourceCatalogPage>> {
    const limit = params.limit ?? 20
    const offset = params.offset ?? 0
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 50
      || !Number.isSafeInteger(offset) || offset < 0 || offset > 10_000) {
      throw new RealApiError('API_INVALID_REQUEST', '资料目录分页范围无效。')
    }
    const query = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET',
      url: `/api/v1/school/research-sources/catalog?${query.toString()}`,
      signal: params.signal,
      parseAs: 'json',
    }))
    const data = mapResearchSourcePage(response.data)
    if (data.limit !== limit || data.offset !== offset) {
      throw new RealApiError('API_INVALID_RESPONSE', '资料目录分页与当前查询不匹配。')
    }
    return { ...response, data }
  }

  async getResearchSource(
    sourceRef: string,
    params: { signal?: AbortSignal } = {},
  ): Promise<ApiEnvelope<ResearchSourceDetail>> {
    if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(sourceRef)) {
      throw new RealApiError('API_INVALID_REQUEST', '来源编号无效。')
    }
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET',
      url: `/api/v1/school/research-sources/${encodeURIComponent(sourceRef)}`,
      signal: params.signal,
      parseAs: 'json',
    }))
    const data = mapResearchSourceDetail(response.data)
    if (data.source_ref !== sourceRef) {
      throw new RealApiError('API_INVALID_RESPONSE', '来源详情与当前选择不匹配。')
    }
    return { ...response, data }
  }

  async listResearchProfileVersions(
    profileRef: string,
    params: { limit?: number; offset?: number; signal?: AbortSignal } = {},
  ): Promise<ApiEnvelope<ResearchProfileVersionPage>> {
    const limit = params.limit ?? 30
    const offset = params.offset ?? 0
    if (!profileRef.trim() || !Number.isSafeInteger(limit) || limit < 1 || limit > 30
      || !Number.isSafeInteger(offset) || offset < 0 || offset > 10_000) {
      throw new RealApiError('API_INVALID_REQUEST', '资料版本查询范围无效。')
    }
    const query = new URLSearchParams({ profile_ref: profileRef, limit: String(limit), offset: String(offset) })
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET',
      url: `/api/v1/school/research-profiles/versions?${query.toString()}`,
      signal: params.signal,
      parseAs: 'json',
    }))
    const data = mapResearchProfileVersionPage(response.data)
    if (data.items.some((item) => item.profile_ref !== profileRef)
      || new Set(data.items.map((item) => item.version_number)).size !== data.items.length
      || data.offset !== offset || data.limit !== limit) {
      throw new RealApiError('API_INVALID_RESPONSE', '资料版本列表与当前查询不匹配。')
    }
    return { ...response, data }
  }

  async importResearchProfile(
    profileRef: string,
    versionNumber: number,
    idempotencyKey: string,
  ): Promise<ApiEnvelope<ResearchProfileCandidate>> {
    if (!Number.isSafeInteger(versionNumber) || versionNumber < 1 || !profileRef.trim()) {
      throw new RealApiError('API_INVALID_REQUEST', '研究资料版本信息无效。')
    }
    const response = await this.schoolWrite(
      '/api/v1/school/research-profiles/import',
      { profile_ref: profileRef, version_number: versionNumber },
      'research-profile-import',
      idempotencyKey,
    )
    return { ...response, data: mapResearchProfileCandidate(response.data) }
  }

  async enableResearchProfileSimulation(
    profileRef: string,
    versionNumber: number,
    idempotencyKey: string,
  ): Promise<ApiEnvelope<ResearchProfileSimulationReceipt>> {
    if (!Number.isSafeInteger(versionNumber) || versionNumber < 1 || !profileRef.trim()) {
      throw new RealApiError('API_INVALID_REQUEST', '研究资料版本信息无效。')
    }
    const response = await this.schoolWrite(
      '/api/v1/school/research-profiles/enable-simulation',
      { profile_ref: profileRef, version_number: versionNumber },
      'research-profile-enable-simulation',
      idempotencyKey,
    )
    return { ...response, data: mapResearchProfileSimulationReceipt(response.data) }
  }

  async listResearchTaskCatalog(params: { signal?: AbortSignal } = {}): Promise<ApiEnvelope<ResearchTaskBindingOption[]>> {
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET', url: '/api/v1/school/research-tasks/catalog', signal: params.signal, parseAs: 'json',
    }))
    if (!Array.isArray(response.data)) throw new RealApiError('API_INVALID_RESPONSE', '研究任务目录格式无法识别。')
    return { ...response, data: response.data.map(mapResearchTaskBindingOption) }
  }

  async publishResearchTask(
    input: ResearchTaskPublishInput,
    idempotencyKey: string,
  ): Promise<ApiEnvelope<ResearchTaskPublicationReceipt>> {
    const opensAt = Date.parse(input.opens_at)
    const dueAt = Date.parse(input.due_at)
    if (!input.class_ref.trim() || !input.task_ref.trim() || !input.binding_ref.trim()
      || !Number.isSafeInteger(input.profile_version_number) || input.profile_version_number < 1
      || !Number.isFinite(opensAt) || !Number.isFinite(dueAt) || dueAt <= opensAt) {
      throw new RealApiError('API_INVALID_REQUEST', '研究任务发布信息无效。')
    }
    const response = await this.schoolWrite(
      '/api/v1/school/research-tasks/publish',
      {
        class_ref: input.class_ref,
        task_ref: input.task_ref,
        binding_ref: input.binding_ref,
        profile_version_number: input.profile_version_number,
        opens_at: input.opens_at,
        due_at: input.due_at,
      },
      `research-task-${input.task_ref}-publish`,
      idempotencyKey,
    )
    return { ...response, data: mapResearchTaskPublication(response.data) }
  }

  async listStudentResearchTasks(params: { limit?: number; offset?: number; signal?: AbortSignal } = {}): Promise<ApiEnvelope<ResearchDiscoveryPage<ResearchTaskDiscoveryEntry>>> {
    const query = new URLSearchParams({
      limit: String(params.limit ?? 30),
      offset: String(params.offset ?? 0),
    })
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET',
      url: `/api/v1/school/research-discovery/tasks?${query.toString()}`,
      signal: params.signal,
      parseAs: 'json',
    }))
    return { ...response, data: mapResearchPage(response.data, mapResearchTaskDiscovery) }
  }

  async listStudentResearchSessions(params: { limit?: number; offset?: number; signal?: AbortSignal } = {}): Promise<ApiEnvelope<ResearchDiscoveryPage<ResearchSessionDiscoveryEntry>>> {
    const query = new URLSearchParams({
      limit: String(params.limit ?? 30),
      offset: String(params.offset ?? 0),
    })
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET',
      url: `/api/v1/school/research-discovery/sessions?${query.toString()}`,
      signal: params.signal,
      parseAs: 'json',
    }))
    return { ...response, data: mapResearchPage(response.data, mapResearchSessionDiscovery) }
  }

  async startStudentResearchTask(taskRef: string, idempotencyKey: string): Promise<ApiEnvelope<ResearchL1Session>> {
    const response = await this.schoolWrite(
      `/api/v1/school/research/tasks/${encodeURIComponent(taskRef)}/start`,
      {},
      `research-task-${taskRef}-start`,
      idempotencyKey,
    )
    return { ...response, data: mapResearchL1Session(response.data) }
  }

  async resumeStudentResearchSession(sessionRef: string): Promise<ApiEnvelope<ResearchL1Session>> {
    const response = await this.schoolWrite(
      `/api/v1/school/research/sessions/${encodeURIComponent(sessionRef)}/resume`,
      {},
      `research-session-${sessionRef}-resume`,
    )
    return { ...response, data: mapResearchL1Session(response.data) }
  }

  async answerStudentResearchSession(
    sessionRef: string,
    input: ResearchAnswerInput,
    idempotencyKey: string,
  ): Promise<ApiEnvelope<ResearchL1Session>> {
    if (!Number.isSafeInteger(input.raw_value) || !Number.isSafeInteger(input.expected_state_version)
      || input.expected_state_version < 1 || !input.item_id.trim()) {
      throw new RealApiError('API_INVALID_REQUEST', '研究题目回答信息无效。')
    }
    const response = await this.schoolWrite(
      `/api/v1/school/research/sessions/${encodeURIComponent(sessionRef)}/answers`,
      input,
      `research-session-${sessionRef}-answer-${input.expected_state_version}`,
      idempotencyKey,
    )
    return { ...response, data: mapResearchL1Session(response.data) }
  }

  async createSupport(assessmentId: string, message: string): Promise<ApiEnvelope<SupportResult>> {
    await this.ensureCsrfToken()
    return unwrap<SupportResult>(() => createSupport({
      client: apiClient,
      body: {
        assessment_id: assessmentId,
        target_role: 'student',
        message,
        language: 'zh-CN',
        purpose: 'education_support',
      },
      headers: mutationHeaders(this.csrfToken, nowToken(`frontend-support-${assessmentId}`)),
    }))
  }

  async getStudentReport(reportId: string): Promise<ApiEnvelope<StudentReportViewModel>> {
    const reportResponse = await unwrap<unknown>(() => getReport({
      client: apiClient,
      path: { report_id: reportId },
    }))
    const rawReport = isRecord(reportResponse.data) ? reportResponse.data : {}
    const assessmentId = valueAsString(rawReport.assessment_id)
    const assessmentResponse = await unwrap<unknown>(() => getAssessment({
      client: apiClient,
      path: { assessment_id: assessmentId },
    }))
    return { ...reportResponse, data: mapReport(rawReport, assessmentResponse.data) }
  }

  async getTeacherOverview(): Promise<ApiEnvelope<unknown>> {
    return unwrap<unknown>(() => apiClient.request({
      method: 'GET',
      url: '/api/v1/teacher/overview',
      parseAs: 'json',
    }))
  }

  async getTeacherStudent(subjectId: string): Promise<ApiEnvelope<unknown>> {
    return unwrap<unknown>(() => apiClient.request({
      method: 'GET',
      url: `/api/v1/teacher/students/${encodeURIComponent(subjectId)}`,
      parseAs: 'json',
    }))
  }

  async getReviewQueue(): Promise<ApiEnvelope<ReviewQueueViewModel>> {
    const response = await unwrap<unknown>(() => listReviews({ client: apiClient }))
    const rawCases = Array.isArray(response.data) ? response.data : []
    const cases = rawCases.map(mapReviewCase)
    for (const item of cases) this.reviewCases.set(item.report_id, item)
    return {
      ...response,
      data: { fixtureLabel: SYNTHETIC_FIXTURE_LABEL, cases },
    }
  }

  async getReviewDetail(reviewCaseId: string): Promise<ApiEnvelope<ReviewDetailViewModel>> {
    const response = await unwrap<unknown>(() => getReview({
      client: apiClient,
      path: { review_id: reviewCaseId },
    }))
    const caseData = mapReviewCase(response.data)
    this.reviewCases.set(caseData.report_id, caseData)
    const now = new Date().toISOString()
    return {
      ...response,
      data: {
        fixtureLabel: SYNTHETIC_FIXTURE_LABEL,
        case: caseData,
        timeline: [
          { label: '安全检查', detail: '普通个性化生成已暂停', time: now, tone: 'done' },
          { label: '进入人工复核', detail: '等待复核员确认下一步', time: now, tone: 'current' },
          { label: '审核结果', detail: '完成后记录在此处', time: '待处理', tone: 'muted' },
        ],
        evidence: [],
        safeAssessment: {
          assessmentId: valueAsString((response.data as UnknownRecord).assessment_id, 'ASSESS_REDACTED'),
          completion: '已完成 · 仅摘要',
          dataBoundary: '只展示授权摘要，不含原始回答或身份信息。',
          dimensionNote: '维度名称与数值为合成结构，占位展示，不作心理学解释。',
        },
        allowedActions: caseData.status === 'APPROVED' || caseData.status === 'REJECTED' ? [] : ['approved', 'rejected'],
      },
    }
  }

  async submitReview(reportId: string, input: ReviewSubmission): Promise<ApiEnvelope<ReviewCase>> {
    await this.ensureCsrfToken()
    const response = await unwrap<UnknownRecord>(() => reviewReport({
      client: apiClient,
      path: { report_id: reportId },
      body: { decision: input.decision, note_code: input.note.trim().slice(0, 160) || undefined },
      headers: mutationHeaders(this.csrfToken, nowToken(`frontend-review-${reportId}`)),
    }))
    const prior = this.reviewCases.get(reportId)
    const status = valueAsString(response.data.review_status, input.decision)
    const caseData: ReviewCase = {
      ...(prior || mapReviewCase({ report_id: reportId, review_id: response.data.review_id, status })),
      status: status === 'approved' ? 'APPROVED' : 'REJECTED',
      updated_at: new Date().toISOString(),
      summary: input.decision === 'approved' ? '复核已完成。结果可以进入后续授权流程。' : '复核已完成。该结果不会进入后续发布流程。',
    }
    this.reviewCases.set(reportId, caseData)
    return { ...response, data: caseData }
  }
}

export const realApiProvider = new RealApiProvider()

export const requestIndependentConversation = <T>(input: IndependentConversationRequest): Promise<ApiEnvelope<T>> =>
  realApiProvider.requestIndependentConversation<T>(input)

export const requestIndependentEducationReview = <T>(input: IndependentEducationReviewRequest): Promise<ApiEnvelope<T>> =>
  realApiProvider.requestIndependentEducationReview<T>(input)

export const requestProfessionalReview = <T>(input: IndependentConversationRequest): Promise<ApiEnvelope<T>> =>
  realApiProvider.requestProfessionalReview<T>(input)

export const requestSchoolCatManagement = <T>(input: {
  method: 'GET' | 'POST'; path: string; body?: Record<string, unknown>
}): Promise<ApiEnvelope<T>> => realApiProvider.requestSchoolCatManagement<T>(input)

export const requestSchoolCatAssets = <T>(input: {
  method: 'GET' | 'POST' | 'PATCH'; path: string; body?: Record<string, unknown>
  query?: Record<string, unknown>; idempotencyKey?: string
}): Promise<ApiEnvelope<T>> => realApiProvider.requestSchoolCatAssets<T>(input)

export const requestSchoolCatSavedSimulation = <T>(input: {
  path: string; body: Record<string, unknown>
}): Promise<ApiEnvelope<T>> => realApiProvider.requestSchoolCatSavedSimulation<T>(input)
