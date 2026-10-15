import { RealApiError } from '@/services/real-api'
import { schoolResearchFeedback, type ResearchReviewTask } from '@/services/school-research-feedback'

type RecordValue = Record<string, unknown>
export type ProgrammeCandidateStatus = 'HELD' | 'ADOPTED' | 'DISCARDED'
export type ProgrammeCandidateSummary = {
  candidate_ref: string
  programme_ref: string
  status: ProgrammeCandidateStatus
  state_version: number
  student_feedback_eligible: false
  output_boundary: 'STAFF_REFERENCE_ONLY'
  created_at: string
}
export type ProgrammeCandidateCitation = {
  citation_id: string
  source_title: string
  source_organization: string
  source_url: string
  source_locator: string | null
}
export type ProgrammeCandidateDetail = ProgrammeCandidateSummary & {
  purpose: 'RESEARCH_SIMULATION'
  research_only: true
  psychological_interpretation_allowed: false
  publication_status: 'not_approved_for_publication_or_operational_use'
  content: {
    programme_ref: string
    content_origin: 'VERIFIED_SOURCE_METADATA' | 'LEGACY_MODEL_TEXT'
    generation_mode: 'MODEL_SOURCE_SELECTION' | 'LEGACY_MODEL_AUTHORED_PASSAGES'
    title: string
    body: string
    citations: ProgrammeCandidateCitation[]
  }
}
export type ProgrammeGenerationStatus = 'QUEUED' | 'LEASED' | 'RETRY' | 'HELD' | 'ABSTAINED' | 'REVIEW_REQUIRED' | 'CRISIS_ROUTED' | 'FAILED' | 'CANCELLED'
export type ProgrammeGenerationReceipt = {
  job_ref: string
  status: ProgrammeGenerationStatus
  policy_version: 'RESEARCH_STAFF_PROGRAMME_POLICY_V1'
  purpose: 'RESEARCH_SIMULATION'
  research_only: true
  publication_status: 'not_approved_for_publication_or_operational_use'
  student_feedback_eligible: false
}
export type ProgrammeGenerationBatchReceipt = {
  batch_ref: string
  job_refs: string[]
  job_count: number
  next_cursor: string | null
  policy_version: 'RESEARCH_STAFF_PROGRAMME_POLICY_V1'
  purpose: 'RESEARCH_SIMULATION'
  research_only: true
  publication_status: 'not_approved_for_publication_or_operational_use'
  student_feedback_eligible: false
}
export type ProgrammeGenerationJob = {
  job_ref: string
  status: ProgrammeGenerationStatus
  attempt_count: number
  updated_at: string
  last_error_code: string | null
}
export type ProgrammeGenerationStatusCounts = Record<ProgrammeGenerationStatus, number>
export type ProgrammeGenerationJobPage = {
  items: ProgrammeGenerationJob[]
  offset: number
  limit: number
  total: number
  has_more: boolean
  status_counts: ProgrammeGenerationStatusCounts
  policy_version: 'RESEARCH_STAFF_PROGRAMME_POLICY_V1'
  purpose: 'RESEARCH_SIMULATION'
  research_only: true
  publication_status: 'not_approved_for_publication_or_operational_use'
  student_feedback_eligible: false
}

const apiBaseUrl = new window.URL(import.meta.env.VITE_API_BASE_URL || '/', window.location.origin).toString()
const publicationStatus = 'not_approved_for_publication_or_operational_use' as const
const summaryFields = ['candidate_ref', 'programme_ref', 'status', 'state_version', 'student_feedback_eligible', 'output_boundary', 'created_at'].sort()
const detailFields = [...summaryFields, 'purpose', 'research_only', 'psychological_interpretation_allowed', 'publication_status', 'content'].sort()
const contentFields = ['programme_ref', 'content_origin', 'generation_mode', 'title', 'body', 'citations'].sort()
const citationFields = ['citation_id', 'source_title', 'source_organization', 'source_url', 'source_locator'].sort()
const generationFields = ['job_ref', 'status', 'policy_version', 'purpose', 'research_only', 'publication_status', 'student_feedback_eligible'].sort()
const generationBatchFields = ['batch_ref', 'job_refs', 'job_count', 'next_cursor', 'policy_version', 'purpose', 'research_only', 'publication_status', 'student_feedback_eligible'].sort()
const generationJobPageFields = ['items', 'offset', 'limit', 'total', 'has_more', 'status_counts', 'policy_version', 'purpose', 'research_only', 'publication_status', 'student_feedback_eligible'].sort()
const generationJobFields = ['job_ref', 'status', 'attempt_count', 'updated_at', 'last_error_code'].sort()
const generationStatuses: ProgrammeGenerationStatus[] = ['QUEUED', 'LEASED', 'RETRY', 'HELD', 'ABSTAINED', 'REVIEW_REQUIRED', 'CRISIS_ROUTED', 'FAILED', 'CANCELLED']
const generationStatusCountFields = [...generationStatuses].sort()
const generationJobRefPattern = /^REJ_[0-9a-f]{64}$/
const generationJobErrorCodes = new Set([
  'POLICY_UNAVAILABLE', 'SOURCE_UNQUALIFIED', 'SAFETY_BLOCKED', 'UPSTREAM_TRANSIENT',
  'UPSTREAM_RATE_LIMITED', 'UPSTREAM_TIMEOUT', 'DEPENDENCY_INVALID_RESPONSE', 'GENERATION_FAILED',
  'INTERNAL_FAILURE', 'INTERNAL_FAILURE_AUTHORIZATION', 'INTERNAL_FAILURE_GENERATION',
  'INTERNAL_FAILURE_OUTCOME_VALIDATION', 'INTERNAL_FAILURE_CANDIDATE_PROJECTION',
  'INTERNAL_FAILURE_CANDIDATE_STORE', 'INTERNAL_FAILURE_DISPOSITION',
  'INTERNAL_FAILURE_FINALIZATION', 'LEASE_EXPIRED_MAX_ATTEMPTS', 'MAX_ATTEMPTS_EXHAUSTED',
])

function record(value: unknown, message: string): RecordValue {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new RealApiError('API_INVALID_RESPONSE', message)
  return value as RecordValue
}

function exact(source: RecordValue, fields: string[], message: string) {
  if (Object.keys(source).sort().join('|') !== fields.join('|')) throw new RealApiError('API_INVALID_RESPONSE', message)
}

function text(source: RecordValue, key: string, max: number, message: string): string {
  const value = source[key]
  if (typeof value !== 'string' || !value.trim() || value.length > max) throw new RealApiError('API_INVALID_RESPONSE', message)
  return value
}

function mapSummary(value: unknown): ProgrammeCandidateSummary {
  const message = '候选列表格式无法识别。'
  const source = record(value, message)
  exact(source, summaryFields, message)
  if (!['HELD', 'ADOPTED', 'DISCARDED'].includes(String(source.status))
    || source.student_feedback_eligible !== false || source.output_boundary !== 'STAFF_REFERENCE_ONLY'
    || !Number.isSafeInteger(source.state_version) || (source.state_version as number) < 1 || (source.state_version as number) > 2
    || typeof source.created_at !== 'string' || Number.isNaN(Date.parse(source.created_at))) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return {
    candidate_ref: text(source, 'candidate_ref', 128, message),
    programme_ref: text(source, 'programme_ref', 128, message),
    status: source.status as ProgrammeCandidateStatus,
    state_version: source.state_version as number,
    student_feedback_eligible: false,
    output_boundary: 'STAFF_REFERENCE_ONLY',
    created_at: source.created_at,
  }
}

function mapDetail(value: unknown): ProgrammeCandidateDetail {
  const message = '候选内容格式无法识别。'
  const source = record(value, message)
  exact(source, detailFields, message)
  if (source.purpose !== 'RESEARCH_SIMULATION' || source.research_only !== true
    || source.psychological_interpretation_allowed !== false || source.publication_status !== publicationStatus) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  const summary = mapSummary(Object.fromEntries(Object.entries(source).filter(([key]) => summaryFields.includes(key))))
  const content = record(source.content, message)
  exact(content, contentFields, message)
  const sourceMetadataPair = content.content_origin === 'VERIFIED_SOURCE_METADATA'
    && content.generation_mode === 'MODEL_SOURCE_SELECTION'
  const legacyAuthoredPair = content.content_origin === 'LEGACY_MODEL_TEXT'
    && content.generation_mode === 'LEGACY_MODEL_AUTHORED_PASSAGES'
  if (!sourceMetadataPair && !legacyAuthoredPair) throw new RealApiError('API_INVALID_RESPONSE', message)
  if (!Array.isArray(content.citations) || content.citations.length < 1 || content.citations.length > 12) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  const citations = content.citations.map((item): ProgrammeCandidateCitation => {
    const citation = record(item, message)
    exact(citation, citationFields, message)
    const citationId = text(citation, 'citation_id', 3, message)
    const sourceUrl = text(citation, 'source_url', 2048, message)
    let parsedUrl: window.URL
    try { parsedUrl = new window.URL(sourceUrl) } catch { throw new RealApiError('API_INVALID_RESPONSE', message) }
    if (!/^S(?:[1-9]|1[0-2])$/.test(citationId) || parsedUrl.protocol !== 'https:' || parsedUrl.username || parsedUrl.password) {
      throw new RealApiError('API_INVALID_RESPONSE', message)
    }
    const locator = citation.source_locator
    if (locator !== null && (typeof locator !== 'string' || locator.length > 500)) throw new RealApiError('API_INVALID_RESPONSE', message)
    return {
      citation_id: citationId,
      source_title: text(citation, 'source_title', 300, message),
      source_organization: text(citation, 'source_organization', 200, message),
      source_url: sourceUrl,
      source_locator: locator as string | null,
    }
  })
  if (new Set(citations.map((item) => item.citation_id)).size !== citations.length) throw new RealApiError('API_INVALID_RESPONSE', message)
  const title = text(content, 'title', 120, message)
  const body = text(content, 'body', 3600, message)
  const programmeRef = text(content, 'programme_ref', 128, message)
  if (programmeRef !== summary.programme_ref) throw new RealApiError('API_INVALID_RESPONSE', message)
  return {
    ...summary,
    purpose: 'RESEARCH_SIMULATION',
    research_only: true,
    psychological_interpretation_allowed: false,
    publication_status: publicationStatus,
    content: {
      programme_ref: programmeRef,
      content_origin: content.content_origin as ProgrammeCandidateDetail['content']['content_origin'],
      generation_mode: content.generation_mode as ProgrammeCandidateDetail['content']['generation_mode'],
      title,
      body,
      citations,
    },
  }
}

function mapGenerationReceipt(value: unknown): ProgrammeGenerationReceipt {
  const message = '排队回执格式无法识别。'
  const source = record(value, message)
  exact(source, generationFields, message)
  const statuses: ProgrammeGenerationStatus[] = ['QUEUED', 'LEASED', 'RETRY', 'HELD', 'ABSTAINED', 'REVIEW_REQUIRED', 'CRISIS_ROUTED', 'FAILED', 'CANCELLED']
  if (!statuses.includes(source.status as ProgrammeGenerationStatus)
    || source.policy_version !== 'RESEARCH_STAFF_PROGRAMME_POLICY_V1'
    || source.purpose !== 'RESEARCH_SIMULATION' || source.research_only !== true
    || source.publication_status !== publicationStatus || source.student_feedback_eligible !== false) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return {
    job_ref: text(source, 'job_ref', 128, message),
    status: source.status as ProgrammeGenerationStatus,
    policy_version: 'RESEARCH_STAFF_PROGRAMME_POLICY_V1',
    purpose: 'RESEARCH_SIMULATION',
    research_only: true,
    publication_status: publicationStatus,
    student_feedback_eligible: false,
  }
}

function mapGenerationBatchReceipt(value: unknown): ProgrammeGenerationBatchReceipt {
  const message = '批次排队回执格式无法识别。'
  const source = record(value, message)
  exact(source, generationBatchFields, message)
  const refs = source.job_refs
  if (!Array.isArray(refs) || refs.length > 100 || !Number.isSafeInteger(source.job_count)
    || source.job_count !== refs.length || source.policy_version !== 'RESEARCH_STAFF_PROGRAMME_POLICY_V1'
    || source.purpose !== 'RESEARCH_SIMULATION' || source.research_only !== true
    || source.publication_status !== publicationStatus || source.student_feedback_eligible !== false) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  const jobRefs = refs.map((item) => text({ ref: item }, 'ref', 68, message))
  if (jobRefs.some((item) => !generationJobRefPattern.test(item)) || new Set(jobRefs).size !== jobRefs.length) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  const nextCursor = source.next_cursor
  if (nextCursor !== null && (typeof nextCursor !== 'string' || !generationJobRefPattern.test(nextCursor)
    || jobRefs.length === 0 || nextCursor !== jobRefs[jobRefs.length - 1])) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  if (!/^REJBATCH_[0-9a-f]{64}$/.test(text(source, 'batch_ref', 73, message))) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return {
    batch_ref: source.batch_ref as string,
    job_refs: jobRefs,
    job_count: source.job_count as number,
    next_cursor: nextCursor as string | null,
    policy_version: 'RESEARCH_STAFF_PROGRAMME_POLICY_V1',
    purpose: 'RESEARCH_SIMULATION',
    research_only: true,
    publication_status: publicationStatus,
    student_feedback_eligible: false,
  }
}

function mapGenerationJobPage(value: unknown, expectedOffset: number, expectedLimit: number): ProgrammeGenerationJobPage {
  const message = '研究生成任务状态格式无法识别。'
  const source = record(value, message)
  exact(source, generationJobPageFields, message)
  if (source.offset !== expectedOffset || source.limit !== expectedLimit
    || !Number.isSafeInteger(source.total) || (source.total as number) < 0
    || typeof source.has_more !== 'boolean'
    || source.policy_version !== 'RESEARCH_STAFF_PROGRAMME_POLICY_V1'
    || source.purpose !== 'RESEARCH_SIMULATION' || source.research_only !== true
    || source.publication_status !== publicationStatus || source.student_feedback_eligible !== false) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  const rawItems = source.items
  if (!Array.isArray(rawItems) || rawItems.length > expectedLimit) throw new RealApiError('API_INVALID_RESPONSE', message)
  const rawCounts = record(source.status_counts, message)
  exact(rawCounts, generationStatusCountFields, message)
  const statusCounts = {} as ProgrammeGenerationStatusCounts
  for (const status of generationStatuses) {
    const count = rawCounts[status]
    if (!Number.isSafeInteger(count) || (count as number) < 0) throw new RealApiError('API_INVALID_RESPONSE', message)
    statusCounts[status] = count as number
  }
  if (Object.values(statusCounts).reduce((sum, count) => sum + count, 0) !== source.total) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  const items = rawItems.map((value): ProgrammeGenerationJob => {
    const item = record(value, message)
    exact(item, generationJobFields, message)
    if (!generationStatuses.includes(item.status as ProgrammeGenerationStatus)
      || !Number.isSafeInteger(item.attempt_count) || (item.attempt_count as number) < 0 || (item.attempt_count as number) > 20
      || typeof item.updated_at !== 'string' || Number.isNaN(Date.parse(item.updated_at))
      || (item.last_error_code !== null && (typeof item.last_error_code !== 'string'
        || !generationJobErrorCodes.has(item.last_error_code)))) {
      throw new RealApiError('API_INVALID_RESPONSE', message)
    }
    const jobRef = text(item, 'job_ref', 68, message)
    if (!generationJobRefPattern.test(jobRef)) throw new RealApiError('API_INVALID_RESPONSE', message)
    return {
      job_ref: jobRef,
      status: item.status as ProgrammeGenerationStatus,
      attempt_count: item.attempt_count as number,
      updated_at: item.updated_at,
      last_error_code: item.last_error_code as string | null,
    }
  })
  if (new Set(items.map((item) => item.job_ref)).size !== items.length
    || source.has_more !== (expectedOffset + items.length < (source.total as number))) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return {
    items,
    offset: expectedOffset,
    limit: expectedLimit,
    total: source.total as number,
    has_more: source.has_more,
    status_counts: statusCounts,
    policy_version: 'RESEARCH_STAFF_PROGRAMME_POLICY_V1',
    purpose: 'RESEARCH_SIMULATION',
    research_only: true,
    publication_status: publicationStatus,
    student_feedback_eligible: false,
  }
}

async function unwrap(response: Response): Promise<unknown> {
  let raw: unknown
  try { raw = await response.json() } catch { throw new RealApiError('API_INVALID_RESPONSE', '研究参考资料服务返回了无法识别的响应。') }
  const envelope = record(raw, '研究参考资料服务返回了无法识别的响应。')
  if (envelope.error) {
    const problem = record(envelope.error, '候选操作没有完成。')
    throw new RealApiError(typeof problem.code === 'string' ? problem.code.toUpperCase() : 'API_ERROR',
      typeof problem.detail === 'string' ? problem.detail : '候选操作没有完成。', problem.retryable === true)
  }
  if (typeof envelope.request_id !== 'string' || typeof envelope.trace_id !== 'string' || !('data' in envelope)) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究参考资料服务返回了无法识别的响应。')
  }
  if (!response.ok) throw new RealApiError('API_ERROR', '候选操作没有完成。')
  return envelope.data
}

async function getCsrfToken(): Promise<string> {
  let response: Response
  try {
    response = await fetch(new window.URL('/api/v1/auth/csrf', apiBaseUrl), { method: 'GET', credentials: 'include', headers: { Accept: 'application/json' } })
  } catch { throw new RealApiError('NETWORK_UNAVAILABLE', '研究参考资料服务暂时无法连接。', true) }
  const data = record(await unwrap(response), '安全请求校验格式无法识别。')
  return text(data, 'csrf_token', 512, '安全请求校验格式无法识别。')
}

async function request(path: string, init: { method?: 'GET' | 'POST'; body?: Record<string, unknown>; key?: string } = {}): Promise<unknown> {
  const method = init.method ?? 'GET'
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (method === 'POST') {
    if (!init.key) throw new RealApiError('API_INVALID_REQUEST', '候选操作缺少请求标识。')
    headers['Content-Type'] = 'application/json'
    headers['X-CSRF-Token'] = await getCsrfToken()
    headers['Idempotency-Key'] = init.key
  }
  let response: Response
  try {
    response = await fetch(new window.URL(path, apiBaseUrl), {
      method, credentials: 'include', headers,
      ...(init.body ? { body: JSON.stringify(init.body) } : {}),
    })
  } catch { throw new RealApiError('NETWORK_UNAVAILABLE', '研究参考资料服务暂时无法连接。', true) }
  return unwrap(response)
}

function ref(value: string) {
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(value)) throw new RealApiError('API_INVALID_REQUEST', '研究工作事项编号无效。')
}

export class SchoolResearchProgrammeCandidateService {
  listTasks(): Promise<ResearchReviewTask[]> { return schoolResearchFeedback.listTasks() }

  async list(taskRef: string, offset = 0, limit = 20): Promise<ProgrammeCandidateSummary[]> {
    ref(taskRef)
    if (!Number.isSafeInteger(offset) || offset < 0 || offset > 100_000 || !Number.isSafeInteger(limit) || limit < 1 || limit > 50) {
      throw new RealApiError('VALIDATION_FAILED', '分页参数无效。')
    }
    const data = record(await request(`/api/v1/school/research-programme-candidates/tasks/${encodeURIComponent(taskRef)}?offset=${offset}&limit=${limit}`), '候选列表格式无法识别。')
    exact(data, ['items'], '候选列表格式无法识别。')
    if (!Array.isArray(data.items) || data.items.length > limit) throw new RealApiError('API_INVALID_RESPONSE', '候选列表格式无法识别。')
    const items = data.items.map(mapSummary)
    if (new Set(items.map((item) => item.candidate_ref)).size !== items.length) throw new RealApiError('API_INVALID_RESPONSE', '候选列表包含重复记录。')
    return items
  }

  async get(taskRef: string, candidateRef: string): Promise<ProgrammeCandidateDetail> {
    ref(taskRef); ref(candidateRef)
    return mapDetail(await request(`/api/v1/school/research-programme-candidates/tasks/${encodeURIComponent(taskRef)}/${encodeURIComponent(candidateRef)}`))
  }

  async queueGeneration(taskRef: string, key: string): Promise<ProgrammeGenerationReceipt> {
    ref(taskRef)
    if (!key.trim() || key.length > 255) throw new RealApiError('API_INVALID_REQUEST', '候选生成请求缺少请求标识。')
    const data = await request(`/api/v1/school/research-programme-candidates/tasks/${encodeURIComponent(taskRef)}/queue-generation`, {
      method: 'POST', body: {}, key,
    })
    return mapGenerationReceipt(data)
  }

  async queueGenerationBatch(taskRef: string, key: string, limit = 25, afterJobRef: string | null = null): Promise<ProgrammeGenerationBatchReceipt> {
    ref(taskRef)
    if (!key.trim() || key.length > 255 || !Number.isSafeInteger(limit) || limit < 1 || limit > 100
      || (afterJobRef !== null && !generationJobRefPattern.test(afterJobRef))) {
      throw new RealApiError('API_INVALID_REQUEST', '批次生成请求参数无效。')
    }
    const data = await request(`/api/v1/school/research-programme-candidates/tasks/${encodeURIComponent(taskRef)}/queue-generation/batch`, {
      method: 'POST', body: { limit, after_job_ref: afterJobRef }, key,
    })
    return mapGenerationBatchReceipt(data)
  }

  async listGenerationJobs(taskRef: string, offset = 0, limit = 25): Promise<ProgrammeGenerationJobPage> {
    ref(taskRef)
    if (!Number.isSafeInteger(offset) || offset < 0 || offset > 100_000
      || !Number.isSafeInteger(limit) || limit < 1 || limit > 100) {
      throw new RealApiError('VALIDATION_FAILED', '任务状态分页参数无效。')
    }
    const data = await request(`/api/v1/school/research-programme-candidates/tasks/${encodeURIComponent(taskRef)}/generation-jobs?offset=${offset}&limit=${limit}`)
    return mapGenerationJobPage(data, offset, limit)
  }

  async transition(taskRef: string, candidate: ProgrammeCandidateSummary, action: 'adopt' | 'discard', key: string): Promise<ProgrammeCandidateSummary> {
    ref(taskRef); ref(candidate.candidate_ref)
    if (!Number.isSafeInteger(candidate.state_version) || candidate.state_version < 1 || candidate.state_version > 2 || !key.trim() || key.length > 255) {
      throw new RealApiError('API_INVALID_REQUEST', '候选操作状态无效。')
    }
    const data = await request(`/api/v1/school/research-programme-candidates/tasks/${encodeURIComponent(taskRef)}/${encodeURIComponent(candidate.candidate_ref)}/${action}`, {
      method: 'POST', body: { expected_state_version: candidate.state_version }, key,
    })
    const updated = mapSummary(data)
    const expectedStatus = action === 'adopt' ? 'ADOPTED' : 'DISCARDED'
    if (updated.status !== expectedStatus || updated.candidate_ref !== candidate.candidate_ref || updated.programme_ref !== candidate.programme_ref) {
      throw new RealApiError('API_INVALID_RESPONSE', '候选操作回执与请求不匹配。')
    }
    return updated
  }
}

export const schoolResearchProgrammeCandidates = new SchoolResearchProgrammeCandidateService()
export const newProgrammeCandidateIdempotencyKey = (): string => {
  if (typeof crypto === 'undefined' || typeof crypto.randomUUID !== 'function') throw new RealApiError('SECURE_RANDOM_UNAVAILABLE', '当前浏览器无法安全建立请求标识。')
  return `research-programme-candidate-${crypto.randomUUID()}`
}
export const newProgrammeGenerationBatchIdempotencyKey = (limit = 25): string => {
  if (typeof crypto === 'undefined' || typeof crypto.randomUUID !== 'function') throw new RealApiError('SECURE_RANDOM_UNAVAILABLE', '当前浏览器无法安全建立请求标识。')
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) throw new RealApiError('API_INVALID_REQUEST', '批次生成数量无效。')
  return `research-programme-candidate-batch-${limit}-${crypto.randomUUID()}`
}
