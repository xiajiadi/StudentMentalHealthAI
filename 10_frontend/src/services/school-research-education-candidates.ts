import { RealApiError } from '@/services/real-api'
import {
  mapResearchEducationSourceCard,
  newResearchFeedbackIdempotencyKey,
  requestSchoolResearchFeedbackApi,
  type FeedbackSourceCard,
  type ResearchFeedbackCitation,
  type ResearchReviewTask,
} from '@/services/school-research-feedback'

type RecordValue = Record<string, unknown>
export type EducationSourceCard = FeedbackSourceCard
export type ResearchEducationCandidateStatus = 'HELD' | 'ADOPTED' | 'DISCARDED'
export type ResearchEducationCandidateTarget = 'ADOPTED' | 'DISCARDED'
export type ResearchEducationGenerationStatus =
  | 'QUEUED'
  | 'LEASED'
  | 'RETRY'
  | 'HELD'
  | 'ABSTAINED'
  | 'REVIEW_REQUIRED'
  | 'CRISIS_ROUTED'
  | 'FAILED'
  | 'CANCELLED'
export type ResearchEducationGenerationJobErrorCode = typeof generationJobErrorCodes[number]

export type ResearchEducationGenerationJob = {
  job_ref: string
  generation_round: 0 | 1
  input_review_ref: string | null
  status: ResearchEducationGenerationStatus
  attempt_count: number
  last_error_code: ResearchEducationGenerationJobErrorCode | null
  created_at: string
  updated_at: string
}

export type ResearchEducationGenerationStatusCounts = Record<ResearchEducationGenerationStatus, number>

export type ResearchEducationGenerationJobPage = {
  items: ResearchEducationGenerationJob[]
  offset: number
  limit: number
  total: number
  has_more: boolean
  status_counts: ResearchEducationGenerationStatusCounts
  policy_version: 'RESEARCH_GENERAL_EDUCATION_DRAFT_V1'
  purpose: 'RESEARCH_SIMULATION'
  research_only: true
  publication_status: 'not_approved_for_publication_or_operational_use'
  student_feedback_eligible: false
}

export type ResearchEducationCandidateSummary = {
  candidate_ref: string
  task_ref: string
  session_ref: string
  status: ResearchEducationCandidateStatus
  state_version: number
  purpose: 'RESEARCH_SIMULATION'
  research_only: true
  psychological_interpretation_allowed: false
  publication_status: 'not_approved_for_publication_or_operational_use'
  student_feedback_eligible: false
  created_at: string
  updated_at: string
}

export type ResearchGeneralEducationContent = {
  summary: string
  observations: string[]
  suggestions: Array<{ text: string; source_chunk_ids: string[] }>
  disclaimer: string
}

export type ResearchGeneralEducationProvenance = {
  policy_version: 'RESEARCH_GENERAL_EDUCATION_DRAFT_V1'
  policy_hash: string
  safety_policy_version: 'safety-port-unversioned.v1'
  source_package_ref: string
  source_study_ref: string
  source_manifest_sha256: string
  source_age_scope: '14-17'
  retrieval_id: string
  retrieval_bundle_sha256: string
  cited_chunk_ids: string[]
  generation_id: string
  prompt_id: string
  prompt_version: string
  prompt_sha256: string
  model_id: string
  model_version: string
  model_digest_sha256: string
  runtime_version: string
  runtime_attempt_count: 1
  runtime_retry_count: 0
  runtime_fallback_count: 0
  runtime_fallback_attempted: false
  runtime_local_only: true
  input_safety_action: 'PROCEED' | 'PROCEED_WITH_BOUNDARY'
  input_safety_reason_codes: string[]
  retrieval_safety_action: 'PROCEED' | 'PROCEED_WITH_BOUNDARY'
  retrieval_safety_reason_codes: string[]
  output_safety_action: 'PROCEED' | 'PROCEED_WITH_BOUNDARY'
  output_safety_reason_codes: string[]
}

export type ResearchGeneralEducationCandidatePayload = {
  schema_version: 'school-research-general-education-candidate.v1'
  content: ResearchGeneralEducationContent
  citations: ResearchFeedbackCitation[]
  source_cards: EducationSourceCard[]
  provenance: ResearchGeneralEducationProvenance
}

export type ResearchEducationCandidateDetail = ResearchEducationCandidateSummary & {
  candidate_payload: ResearchGeneralEducationCandidatePayload
}

export type ResearchEducationCandidatePage = {
  items: ResearchEducationCandidateSummary[]
  offset: number
  limit: number
  has_more: boolean
}

export type ResearchEducationCandidateBatchReceipt = {
  batch_ref: string
  job_refs: string[]
  job_count: number
  offset: number
  limit: number
  next_offset: number | null
  policy_version: 'RESEARCH_GENERAL_EDUCATION_DRAFT_V1'
  purpose: 'RESEARCH_SIMULATION'
  research_only: true
  publication_status: 'not_approved_for_publication_or_operational_use'
  student_feedback_eligible: false
}

export type ResearchEducationCandidateTask = ResearchReviewTask

const publicationStatus = 'not_approved_for_publication_or_operational_use' as const
const sha256Pattern = /^[0-9a-f]{64}$/
const chunkIdPattern = /^CHUNK_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$/
const candidateRefPattern = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/
const jobRefPattern = /^REJ_[0-9a-f]{64}$/
const inputReviewRefPattern = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/
const batchRefPattern = /^REGENBATCH_[0-9a-f]{64}$/
const provenanceFields = [
  'policy_version', 'policy_hash', 'safety_policy_version', 'source_package_ref',
  'source_study_ref', 'source_manifest_sha256', 'source_age_scope', 'retrieval_id',
  'retrieval_bundle_sha256', 'cited_chunk_ids', 'generation_id', 'prompt_id',
  'prompt_version', 'prompt_sha256', 'model_id', 'model_version', 'model_digest_sha256',
  'runtime_version', 'runtime_attempt_count', 'runtime_retry_count', 'runtime_fallback_count',
  'runtime_fallback_attempted', 'runtime_local_only', 'input_safety_action',
  'input_safety_reason_codes', 'retrieval_safety_action', 'retrieval_safety_reason_codes',
  'output_safety_action', 'output_safety_reason_codes',
].sort()
const contentFields = ['summary', 'observations', 'suggestions', 'disclaimer'].sort()
const suggestionFields = ['text', 'source_chunk_ids'].sort()
const candidatePayloadFields = ['schema_version', 'content', 'citations', 'source_cards', 'provenance'].sort()
const candidateSummaryFields = [
  'candidate_ref', 'task_ref', 'session_ref', 'status', 'state_version', 'purpose',
  'research_only', 'psychological_interpretation_allowed', 'publication_status',
  'student_feedback_eligible', 'created_at', 'updated_at',
].sort()
const candidatePageFields = ['items', 'offset', 'limit', 'has_more'].sort()
const generationStatuses: ResearchEducationGenerationStatus[] = [
  'QUEUED', 'LEASED', 'RETRY', 'HELD', 'ABSTAINED', 'REVIEW_REQUIRED', 'CRISIS_ROUTED', 'FAILED', 'CANCELLED',
]
const generationStatusCountFields = [...generationStatuses].sort()
const generationJobFields = [
  'job_ref', 'generation_round', 'input_review_ref', 'status', 'attempt_count',
  'last_error_code', 'created_at', 'updated_at',
].sort()
const generationJobPageFields = [
  'items', 'offset', 'limit', 'total', 'has_more', 'status_counts', 'policy_version',
  'purpose', 'research_only', 'publication_status', 'student_feedback_eligible',
].sort()
const generationJobErrorCodes = [
  'POLICY_UNAVAILABLE', 'SOURCE_UNQUALIFIED', 'SAFETY_BLOCKED', 'UPSTREAM_TRANSIENT',
  'UPSTREAM_RATE_LIMITED', 'UPSTREAM_TIMEOUT', 'DEPENDENCY_INVALID_RESPONSE', 'GENERATION_FAILED',
  'INTERNAL_FAILURE', 'INTERNAL_FAILURE_AUTHORIZATION', 'INTERNAL_FAILURE_GENERATION',
  'INTERNAL_FAILURE_OUTCOME_VALIDATION', 'INTERNAL_FAILURE_CANDIDATE_PROJECTION',
  'INTERNAL_FAILURE_CANDIDATE_STORE', 'INTERNAL_FAILURE_DISPOSITION',
  'INTERNAL_FAILURE_FINALIZATION', 'LEASE_EXPIRED_MAX_ATTEMPTS', 'MAX_ATTEMPTS_EXHAUSTED',
] as const
const generationJobErrorCodeSet = new Set<string>(generationJobErrorCodes)
const candidateBatchFields = [
  'batch_ref', 'job_refs', 'job_count', 'offset', 'limit', 'next_offset', 'policy_version',
  'purpose', 'research_only', 'publication_status', 'student_feedback_eligible',
].sort()
const citationFields = [
  'citation_id', 'chunk_id', 'document_id', 'title', 'organization', 'locator', 'rank',
  'source_version', 'source_hash',
].sort()

function record(value: unknown, message: string): RecordValue {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return value as RecordValue
}

function exact(source: RecordValue, fields: string[], message: string) {
  if (Object.keys(source).sort().join('|') !== fields.join('|')) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
}

function text(source: RecordValue, key: string, max: number, message: string): string {
  const value = source[key]
  if (typeof value !== 'string' || !value.trim() || value.length > max) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return value
}

function optionalText(source: RecordValue, key: string, max: number, message: string): string | null {
  const value = source[key]
  if (value === null) return null
  if (typeof value !== 'string' || value.length > max) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return value
}

function timestamp(source: RecordValue, key: string, message: string): string {
  const value = source[key]
  if (typeof value !== 'string' || !value.trim() || Number.isNaN(Date.parse(value))) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return value
}

function boundedInt(source: RecordValue, key: string, minimum: number, maximum: number, message: string): number {
  const value = source[key]
  if (!Number.isSafeInteger(value) || (value as number) < minimum || (value as number) > maximum) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return value as number
}

function reference(value: string, message = '候选编号无效。') {
  if (typeof value !== 'string' || !candidateRefPattern.test(value)) {
    throw new RealApiError('API_INVALID_REQUEST', message)
  }
}

function idempotencyKey(value: string) {
  if (typeof value !== 'string' || !value.trim() || value.length > 255) {
    throw new RealApiError('API_INVALID_REQUEST', '候选操作缺少请求标识。')
  }
}

function pageArguments(offset: number, limit: number, maxLimit = 50) {
  if (!Number.isSafeInteger(offset) || offset < 0 || offset > 100_000
    || !Number.isSafeInteger(limit) || limit < 1 || limit > maxLimit) {
    throw new RealApiError('VALIDATION_FAILED', '候选列表分页参数无效。')
  }
  return { offset, limit }
}

function mapTask(value: unknown): ResearchEducationCandidateTask {
  const message = '候选任务列表格式无法识别。'
  const source = record(value, message)
  exact(source, ['task_ref', 'class_ref', 'class_display_name', 'published_at'].sort(), message)
  return {
    task_ref: text(source, 'task_ref', 128, message),
    class_ref: text(source, 'class_ref', 128, message),
    class_display_name: optionalText(source, 'class_display_name', 160, message),
    published_at: timestamp(source, 'published_at', message),
  }
}

function mapSummary(value: unknown): ResearchEducationCandidateSummary {
  const message = '候选列表格式无法识别。'
  const source = record(value, message)
  exact(source, candidateSummaryFields, message)
  if (!['HELD', 'ADOPTED', 'DISCARDED'].includes(String(source.status))
    || source.purpose !== 'RESEARCH_SIMULATION' || source.research_only !== true
    || source.psychological_interpretation_allowed !== false || source.publication_status !== publicationStatus
    || source.student_feedback_eligible !== false) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  const status = source.status as ResearchEducationCandidateStatus
  const stateVersion = boundedInt(source, 'state_version', 1, 2, message)
  if ((status === 'HELD') !== (stateVersion === 1)) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  const candidateRef = text(source, 'candidate_ref', 128, message)
  if (!candidateRefPattern.test(candidateRef)) throw new RealApiError('API_INVALID_RESPONSE', message)
  return {
    candidate_ref: candidateRef,
    task_ref: text(source, 'task_ref', 128, message),
    session_ref: text(source, 'session_ref', 128, message),
    status,
    state_version: stateVersion,
    purpose: 'RESEARCH_SIMULATION',
    research_only: true,
    psychological_interpretation_allowed: false,
    publication_status: publicationStatus,
    student_feedback_eligible: false,
    created_at: timestamp(source, 'created_at', message),
    updated_at: timestamp(source, 'updated_at', message),
  }
}

function mapCitation(value: unknown): ResearchFeedbackCitation {
  const message = '候选引用格式无法识别。'
  const source = record(value, message)
  exact(source, citationFields, message)
  const rank = source.rank
  if (rank !== null && (!Number.isSafeInteger(rank) || (rank as number) < 1)) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return {
    citation_id: text(source, 'citation_id', 128, message),
    chunk_id: optionalText(source, 'chunk_id', 192, message),
    document_id: optionalText(source, 'document_id', 128, message),
    title: optionalText(source, 'title', 500, message),
    organization: optionalText(source, 'organization', 300, message),
    locator: optionalText(source, 'locator', 2048, message),
    rank: rank as number | null,
    source_version: optionalText(source, 'source_version', 128, message),
    source_hash: optionalText(source, 'source_hash', 128, message),
  }
}

function mapProvenance(value: unknown): ResearchGeneralEducationProvenance {
  const message = '候选来源追溯格式无法识别。'
  const source = record(value, message)
  exact(source, provenanceFields, message)
  const hash = (key: string) => {
    const result = text(source, key, 64, message)
    if (!sha256Pattern.test(result)) throw new RealApiError('API_INVALID_RESPONSE', message)
    return result
  }
  const reasons = (key: string): string[] => {
    const values = source[key]
    if (!Array.isArray(values) || values.length < 1 || values.length > 16
      || values.some((item) => typeof item !== 'string' || !/^[A-Z][A-Z0-9_]{0,63}$/.test(item))) {
      throw new RealApiError('API_INVALID_RESPONSE', message)
    }
    return [...values] as string[]
  }
  const action = (key: string): 'PROCEED' | 'PROCEED_WITH_BOUNDARY' => {
    const value = source[key]
    if (value !== 'PROCEED' && value !== 'PROCEED_WITH_BOUNDARY') {
      throw new RealApiError('API_INVALID_RESPONSE', message)
    }
    return value
  }
  const chunkIds = source.cited_chunk_ids
  if (!Array.isArray(chunkIds) || chunkIds.length < 1 || chunkIds.length > 8
    || chunkIds.some((item) => typeof item !== 'string' || !chunkIdPattern.test(item))
    || new Set(chunkIds).size !== chunkIds.length) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  if (source.policy_version !== 'RESEARCH_GENERAL_EDUCATION_DRAFT_V1'
    || source.safety_policy_version !== 'safety-port-unversioned.v1'
    || source.source_age_scope !== '14-17'
    || source.runtime_attempt_count !== 1 || source.runtime_retry_count !== 0
    || source.runtime_fallback_count !== 0 || source.runtime_fallback_attempted !== false
    || source.runtime_local_only !== true) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return {
    policy_version: 'RESEARCH_GENERAL_EDUCATION_DRAFT_V1',
    policy_hash: hash('policy_hash'),
    safety_policy_version: 'safety-port-unversioned.v1',
    source_package_ref: text(source, 'source_package_ref', 128, message),
    source_study_ref: text(source, 'source_study_ref', 128, message),
    source_manifest_sha256: hash('source_manifest_sha256'),
    source_age_scope: '14-17',
    retrieval_id: text(source, 'retrieval_id', 164, message),
    retrieval_bundle_sha256: hash('retrieval_bundle_sha256'),
    cited_chunk_ids: [...chunkIds] as string[],
    generation_id: text(source, 'generation_id', 164, message),
    prompt_id: text(source, 'prompt_id', 164, message),
    prompt_version: text(source, 'prompt_version', 64, message),
    prompt_sha256: hash('prompt_sha256'),
    model_id: text(source, 'model_id', 128, message),
    model_version: text(source, 'model_version', 128, message),
    model_digest_sha256: hash('model_digest_sha256'),
    runtime_version: text(source, 'runtime_version', 64, message),
    runtime_attempt_count: 1,
    runtime_retry_count: 0,
    runtime_fallback_count: 0,
    runtime_fallback_attempted: false,
    runtime_local_only: true,
    input_safety_action: action('input_safety_action'),
    input_safety_reason_codes: reasons('input_safety_reason_codes'),
    retrieval_safety_action: action('retrieval_safety_action'),
    retrieval_safety_reason_codes: reasons('retrieval_safety_reason_codes'),
    output_safety_action: action('output_safety_action'),
    output_safety_reason_codes: reasons('output_safety_reason_codes'),
  }
}

function mapPayload(value: unknown): ResearchGeneralEducationCandidatePayload {
  const message = '候选原始内容格式无法识别。'
  const source = record(value, message)
  exact(source, candidatePayloadFields, message)
  if (source.schema_version !== 'school-research-general-education-candidate.v1') {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  const rawContent = record(source.content, message)
  exact(rawContent, contentFields, message)
  if (!Array.isArray(rawContent.observations) || !Array.isArray(rawContent.suggestions)) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  const content: ResearchGeneralEducationContent = {
    summary: text(rawContent, 'summary', 100_000, message),
    observations: rawContent.observations.map((item) => {
      if (typeof item !== 'string') throw new RealApiError('API_INVALID_RESPONSE', message)
      return item
    }),
    suggestions: rawContent.suggestions.map((item) => {
      const suggestion = record(item, message)
      exact(suggestion, suggestionFields, message)
      const chunks = suggestion.source_chunk_ids
      if (!Array.isArray(chunks) || chunks.length < 1 || chunks.length > 8
        || chunks.some((chunk) => typeof chunk !== 'string' || !chunkIdPattern.test(chunk))) {
        throw new RealApiError('API_INVALID_RESPONSE', message)
      }
      return {
        text: text(suggestion, 'text', 100_000, message),
        source_chunk_ids: [...chunks] as string[],
      }
    }),
    disclaimer: text(rawContent, 'disclaimer', 100_000, message),
  }
  if (!Array.isArray(source.citations) || source.citations.length < 1 || source.citations.length > 8
    || !Array.isArray(source.source_cards) || source.source_cards.length < 1 || source.source_cards.length > 8) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  const citations = source.citations.map(mapCitation)
  const sourceCards = source.source_cards.map(mapResearchEducationSourceCard)
  const provenance = mapProvenance(source.provenance)
  const chunks = sourceCards.map((card) => card.chunk_id)
  if (new Set(chunks).size !== chunks.length || citations.length !== sourceCards.length
    || new Set(citations.map((citation) => citation.citation_id)).size !== citations.length
    || new Set(citations.map((citation) => citation.chunk_id)).size !== citations.length
    || provenance.cited_chunk_ids.length !== chunks.length
    || provenance.cited_chunk_ids.some((chunk) => !chunks.includes(chunk))
    || content.suggestions.some((item) => item.source_chunk_ids.some((chunk) => !chunks.includes(chunk)))
    || citations.some((citation, index) => {
      const card = sourceCards[index]
      const locatorSuffix = `; source population: ${card.source_population_scope}; source: ${card.canonical_url}; license: ${card.license} (${card.license_url}); attribution: ${card.attribution}`
      return citation.chunk_id !== card.chunk_id || citation.title !== card.title
        || citation.organization !== card.organization
        || citation.source_hash !== `sha256:${card.excerpt_sha256}`
        || (citation.locator !== `${card.record_locator}${locatorSuffix}`
          && citation.locator !== `record: ${card.record_id}${locatorSuffix}`)
    })) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return Object.freeze({
    schema_version: 'school-research-general-education-candidate.v1',
    content: Object.freeze({
      ...content,
      observations: Object.freeze(content.observations) as unknown as string[],
      suggestions: Object.freeze(content.suggestions.map((item) => Object.freeze({
        ...item,
        source_chunk_ids: Object.freeze(item.source_chunk_ids) as unknown as string[],
      }))) as unknown as ResearchGeneralEducationContent['suggestions'],
    }),
    citations: Object.freeze(citations.map((item) => Object.freeze(item))) as unknown as ResearchFeedbackCitation[],
    source_cards: Object.freeze(sourceCards.map((item) => Object.freeze(item))) as unknown as EducationSourceCard[],
    provenance: Object.freeze({
      ...provenance,
      cited_chunk_ids: Object.freeze(provenance.cited_chunk_ids) as unknown as string[],
      input_safety_reason_codes: Object.freeze(provenance.input_safety_reason_codes) as unknown as string[],
      retrieval_safety_reason_codes: Object.freeze(provenance.retrieval_safety_reason_codes) as unknown as string[],
      output_safety_reason_codes: Object.freeze(provenance.output_safety_reason_codes) as unknown as string[],
    }),
  })
}

function mapDetail(value: unknown): ResearchEducationCandidateDetail {
  const message = '候选原始内容格式无法识别。'
  const source = record(value, message)
  exact(source, [...candidateSummaryFields, 'candidate_payload'].sort(), message)
  return Object.freeze({
    ...mapSummary(Object.fromEntries(Object.entries(source).filter(([key]) => candidateSummaryFields.includes(key)))),
    candidate_payload: mapPayload(source.candidate_payload),
  })
}

function mapPage(value: unknown, expectedOffset: number, expectedLimit: number): ResearchEducationCandidatePage {
  const message = '候选列表格式无法识别。'
  const source = record(value, message)
  exact(source, candidatePageFields, message)
  if (source.offset !== expectedOffset || source.limit !== expectedLimit || typeof source.has_more !== 'boolean'
    || !Array.isArray(source.items) || source.items.length > expectedLimit) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  const items = source.items.map(mapSummary)
  if (new Set(items.map((item) => item.candidate_ref)).size !== items.length
    || (source.has_more === true && items.length !== expectedLimit)) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return { items, offset: expectedOffset, limit: expectedLimit, has_more: source.has_more }
}

function mapGenerationJobPage(
  value: unknown,
  expectedOffset: number,
  expectedLimit: number,
): ResearchEducationGenerationJobPage {
  const message = '研究生成任务状态格式无法识别。'
  const source = record(value, message)
  exact(source, generationJobPageFields, message)
  if (source.offset !== expectedOffset || source.limit !== expectedLimit
    || !Number.isSafeInteger(source.total) || (source.total as number) < 0
    || typeof source.has_more !== 'boolean'
    || source.policy_version !== 'RESEARCH_GENERAL_EDUCATION_DRAFT_V1'
    || source.purpose !== 'RESEARCH_SIMULATION' || source.research_only !== true
    || source.publication_status !== publicationStatus || source.student_feedback_eligible !== false) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  if (!Array.isArray(source.items) || source.items.length > expectedLimit) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  const rawCounts = record(source.status_counts, message)
  exact(rawCounts, generationStatusCountFields, message)
  const statusCounts = {} as ResearchEducationGenerationStatusCounts
  for (const status of generationStatuses) {
    const count = rawCounts[status]
    if (!Number.isSafeInteger(count) || (count as number) < 0) {
      throw new RealApiError('API_INVALID_RESPONSE', message)
    }
    statusCounts[status] = count as number
  }
  const total = source.total as number
  if (Object.values(statusCounts).reduce((sum, count) => sum + count, 0) !== total) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  const items = source.items.map((value): ResearchEducationGenerationJob => {
    const item = record(value, message)
    exact(item, generationJobFields, message)
    if (!generationStatuses.includes(item.status as ResearchEducationGenerationStatus)
      || !Number.isSafeInteger(item.attempt_count) || (item.attempt_count as number) < 0
      || (item.attempt_count as number) > 1
      || (item.last_error_code !== null && (typeof item.last_error_code !== 'string'
        || !generationJobErrorCodeSet.has(item.last_error_code)))
      || typeof item.created_at !== 'string' || Number.isNaN(Date.parse(item.created_at))
      || typeof item.updated_at !== 'string' || Number.isNaN(Date.parse(item.updated_at))) {
      throw new RealApiError('API_INVALID_RESPONSE', message)
    }
    const jobRef = text(item, 'job_ref', 68, message)
    const generationRound = item.generation_round
    const inputReviewRef = item.input_review_ref
    if (!jobRefPattern.test(jobRef)
      || (generationRound !== 0 && generationRound !== 1)
      || (generationRound === 0 && inputReviewRef !== null)
      || (generationRound === 1 && (typeof inputReviewRef !== 'string' || !inputReviewRefPattern.test(inputReviewRef)))) {
      throw new RealApiError('API_INVALID_RESPONSE', message)
    }
    return {
      job_ref: jobRef,
      generation_round: generationRound,
      input_review_ref: inputReviewRef as string | null,
      status: item.status as ResearchEducationGenerationStatus,
      attempt_count: item.attempt_count as number,
      last_error_code: item.last_error_code as ResearchEducationGenerationJobErrorCode | null,
      created_at: item.created_at,
      updated_at: item.updated_at,
    }
  })
  if (new Set(items.map((item) => item.job_ref)).size !== items.length
    || source.has_more !== (expectedOffset + items.length < total)) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return {
    items,
    offset: expectedOffset,
    limit: expectedLimit,
    total,
    has_more: source.has_more,
    status_counts: statusCounts,
    policy_version: 'RESEARCH_GENERAL_EDUCATION_DRAFT_V1',
    purpose: 'RESEARCH_SIMULATION',
    research_only: true,
    publication_status: publicationStatus,
    student_feedback_eligible: false,
  }
}

function mapBatch(value: unknown, expectedOffset: number, expectedLimit: number): ResearchEducationCandidateBatchReceipt {
  const message = '候选入队回执格式无法识别。'
  const source = record(value, message)
  exact(source, candidateBatchFields, message)
  if (source.policy_version !== 'RESEARCH_GENERAL_EDUCATION_DRAFT_V1'
    || source.purpose !== 'RESEARCH_SIMULATION' || source.research_only !== true
    || source.publication_status !== publicationStatus || source.student_feedback_eligible !== false
    || source.offset !== expectedOffset || source.limit !== expectedLimit
    || !Array.isArray(source.job_refs) || source.job_refs.length > expectedLimit
    || source.job_count !== source.job_refs.length) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  const batchRef = text(source, 'batch_ref', 75, message)
  const jobRefs = source.job_refs.map((jobRef) => text({ value: jobRef }, 'value', 68, message))
  const nextOffset = source.next_offset
  if (!batchRefPattern.test(batchRef) || jobRefs.some((jobRef) => !jobRefPattern.test(jobRef))
    || new Set(jobRefs).size !== jobRefs.length
    || (nextOffset !== null && (!Number.isSafeInteger(nextOffset)
      || source.job_count !== expectedLimit
      || (nextOffset as number) !== expectedOffset + source.job_count))) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return {
    batch_ref: batchRef,
    job_refs: jobRefs,
    job_count: source.job_count as number,
    offset: expectedOffset,
    limit: expectedLimit,
    next_offset: nextOffset as number | null,
    policy_version: 'RESEARCH_GENERAL_EDUCATION_DRAFT_V1',
    purpose: 'RESEARCH_SIMULATION',
    research_only: true,
    publication_status: publicationStatus,
    student_feedback_eligible: false,
  }
}

function ensureKey(key: string) {
  idempotencyKey(key)
}

export class SchoolResearchEducationCandidateService {
  async listTasks(): Promise<ResearchEducationCandidateTask[]> {
    const message = '候选任务列表格式无法识别。'
    const source = record(await requestSchoolResearchFeedbackApi({
      method: 'GET', path: '/api/v1/school/research-education-candidates/tasks',
    }), message)
    exact(source, ['items'], message)
    if (!Array.isArray(source.items)) throw new RealApiError('API_INVALID_RESPONSE', message)
    const items = source.items.map(mapTask)
    if (new Set(items.map((item) => item.task_ref)).size !== items.length) {
      throw new RealApiError('API_INVALID_RESPONSE', message)
    }
    return items
  }

  async list(
    taskRef: string,
    status: ResearchEducationCandidateStatus = 'HELD',
    offset = 0,
    limit = 20,
  ): Promise<ResearchEducationCandidatePage> {
    reference(taskRef, '研究任务编号无效。')
    if (!['HELD', 'ADOPTED', 'DISCARDED'].includes(status)) {
      throw new RealApiError('VALIDATION_FAILED', '候选状态无效。')
    }
    const paging = pageArguments(offset, limit)
    const page = mapPage(await requestSchoolResearchFeedbackApi({
      method: 'GET',
      path: `/api/v1/school/research-education-candidates/tasks/${encodeURIComponent(taskRef)}/candidates`,
      query: { status, ...paging },
    }), offset, limit)
    if (page.items.some((item) => item.task_ref !== taskRef || item.status !== status)) {
      throw new RealApiError('API_INVALID_RESPONSE', '候选列表范围与请求不一致。')
    }
    return page
  }

  async listJobs(
    taskRef: string,
    offset = 0,
    limit = 20,
  ): Promise<ResearchEducationGenerationJobPage> {
    reference(taskRef, '研究任务编号无效。')
    const paging = pageArguments(offset, limit)
    return mapGenerationJobPage(await requestSchoolResearchFeedbackApi({
      method: 'GET',
      path: `/api/v1/school/research-education-candidates/tasks/${encodeURIComponent(taskRef)}/generation-jobs`,
      query: paging,
    }), offset, limit)
  }

  async get(taskRef: string, candidateRef: string): Promise<ResearchEducationCandidateDetail> {
    reference(taskRef, '研究任务编号无效。')
    reference(candidateRef)
    const detail = mapDetail(await requestSchoolResearchFeedbackApi({
      method: 'GET',
      path: `/api/v1/school/research-education-candidates/tasks/${encodeURIComponent(taskRef)}/candidates/${encodeURIComponent(candidateRef)}`,
    }))
    if (detail.task_ref !== taskRef || detail.candidate_ref !== candidateRef) {
      throw new RealApiError('API_INVALID_RESPONSE', '候选详情范围与请求不一致。')
    }
    return detail
  }

  async resolve(
    taskRef: string,
    candidate: ResearchEducationCandidateSummary,
    target: ResearchEducationCandidateTarget,
    key: string,
  ): Promise<ResearchEducationCandidateSummary> {
    reference(taskRef, '研究任务编号无效。')
    reference(candidate.candidate_ref)
    ensureKey(key)
    if (candidate.task_ref !== taskRef || candidate.status !== 'HELD'
      || !['ADOPTED', 'DISCARDED'].includes(target)
      || !Number.isSafeInteger(candidate.state_version)
      || candidate.state_version !== 1) {
      throw new RealApiError('VALIDATION_FAILED', '候选状态已变化或当前不可复核。')
    }
    const updated = mapSummary(await requestSchoolResearchFeedbackApi({
      method: 'POST',
      path: `/api/v1/school/research-education-candidates/tasks/${encodeURIComponent(taskRef)}/candidates/${encodeURIComponent(candidate.candidate_ref)}/resolve`,
      body: { expected_state_version: candidate.state_version, target },
      idempotencyKey: key,
    }))
    if (updated.candidate_ref !== candidate.candidate_ref || updated.task_ref !== taskRef
      || updated.status !== target || updated.state_version !== 2) {
      throw new RealApiError('API_INVALID_RESPONSE', '候选复核结果与请求不一致。')
    }
    return updated
  }

  async enqueue(
    taskRef: string,
    limit: number,
    offset: number,
    key: string,
  ): Promise<ResearchEducationCandidateBatchReceipt> {
    reference(taskRef, '研究任务编号无效。')
    ensureKey(key)
    const page = pageArguments(offset, limit, 100)
    return mapBatch(await requestSchoolResearchFeedbackApi({
      method: 'POST',
      path: `/api/v1/school/research-education-candidates/tasks/${encodeURIComponent(taskRef)}/enqueue`,
      body: page,
      idempotencyKey: key,
    }), offset, limit)
  }
}

export const schoolResearchEducationCandidates = new SchoolResearchEducationCandidateService()
export const newResearchEducationCandidateIdempotencyKey = newResearchFeedbackIdempotencyKey
