import { RealApiError } from '@/services/real-api'
import {
  mapResearchEducationCandidateSummary,
  type ResearchEducationCandidateSummary,
  type ResearchGeneralEducationContent,
} from '@/services/school-research-education-candidates'
import {
  mapResearchEducationSourceCard,
  newResearchFeedbackIdempotencyKey,
  requestSchoolResearchFeedbackApi,
  type FeedbackSourceCard,
  type ResearchFeedbackCitation,
} from '@/services/school-research-feedback'

type UnknownRecord = Record<string, unknown>
export type ResearchEducationOutputReviewStatus = 'PENDING' | 'REJECTED' | 'REVOKED' | 'CONSUMED'
export type ResearchEducationOutputReviewTarget = 'REJECTED' | 'REVOKED' | 'CREATE_HELD_CANDIDATE'

export type ResearchEducationOutputReviewProvenance = {
  generation_id: string
  retrieval_id: string
  retrieval_bundle_sha256: string
  policy_version: 'RESEARCH_GENERAL_EDUCATION_DRAFT_V1'
  policy_hash: string
  safety_policy_version: 'safety-port-unversioned.v1'
  source_package_ref: string
  source_study_ref: string
  source_manifest_sha256: string
  source_age_scope: '14-17'
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
  input_safety_action: 'PROCEED' | 'PROCEED_WITH_BOUNDARY' | 'BLOCK' | 'REVIEW_REQUIRED' | 'CRISIS_ROUTE'
  input_safety_reason_codes: string[]
  retrieval_safety_action: 'PROCEED' | 'PROCEED_WITH_BOUNDARY' | 'BLOCK' | 'REVIEW_REQUIRED' | 'CRISIS_ROUTE'
  retrieval_safety_reason_codes: string[]
  output_safety_action: 'REVIEW_REQUIRED'
  output_safety_reason_codes: ['CONTENT_CONTROVERSIAL']
  output_safety_requires_human: true
}

export type ResearchEducationOutputReviewSummary = {
  output_review_ref: string
  job_ref: string
  task_ref: string
  session_ref: string
  generation_round: 0 | 1
  status: ResearchEducationOutputReviewStatus
  state_version: number
  expires_at: string
  created_at: string
  updated_at: string
  safety_action: 'REVIEW_REQUIRED'
  reason_codes: ['CONTENT_CONTROVERSIAL']
  requires_human: true
  purpose: 'RESEARCH_SIMULATION'
  research_only: true
  publication_status: 'not_approved_for_publication_or_operational_use'
  student_feedback_eligible: false
}

export type ResearchEducationOutputReviewDetail = ResearchEducationOutputReviewSummary & {
  review_payload: {
    schema_version: 'school-research-general-education-output-review.v1'
    content: ResearchGeneralEducationContent
    source_cards: FeedbackSourceCard[]
    citations: ResearchFeedbackCitation[]
    citation_binding_status: 'NOT_EVALUATED_AT_OUTPUT_STOP'
    provenance: ResearchEducationOutputReviewProvenance
  }
}

export type ResearchEducationOutputReviewPage = {
  items: ResearchEducationOutputReviewSummary[]
  offset: number
  limit: number
  has_more: boolean
}

export type ResearchEducationOutputReviewResolution = {
  output_review: ResearchEducationOutputReviewSummary
  candidate?: ResearchEducationCandidateSummary
}

const apiPrefix = '/api/v1/school/research-education-candidates'
const tokenPattern = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/
const jobRefPattern = /^REJ_[0-9a-f]{64}$/
const summaryFields = [
  'output_review_ref', 'job_ref', 'task_ref', 'session_ref', 'generation_round', 'status',
  'state_version', 'expires_at', 'created_at', 'updated_at', 'safety_action',
  'reason_codes', 'requires_human', 'purpose', 'research_only',
  'publication_status', 'student_feedback_eligible',
].sort()
const pageFields = ['items', 'offset', 'limit', 'has_more'].sort()
const detailFields = [...summaryFields, 'review_payload'].sort()
const payloadFields = ['schema_version', 'content', 'source_cards', 'citations', 'citation_binding_status', 'provenance'].sort()
const contentFields = ['summary', 'observations', 'suggestions', 'disclaimer'].sort()
const suggestionFields = ['text', 'source_chunk_ids'].sort()
const provenanceFields = [
  'generation_id', 'retrieval_id', 'retrieval_bundle_sha256', 'policy_version', 'policy_hash',
  'safety_policy_version', 'source_package_ref', 'source_study_ref', 'source_manifest_sha256',
  'source_age_scope', 'prompt_id', 'prompt_version', 'prompt_sha256', 'model_id', 'model_version',
  'model_digest_sha256', 'runtime_version', 'runtime_attempt_count', 'runtime_retry_count',
  'runtime_fallback_count', 'runtime_fallback_attempted', 'runtime_local_only',
  'input_safety_action', 'input_safety_reason_codes', 'retrieval_safety_action',
  'retrieval_safety_reason_codes', 'output_safety_action', 'output_safety_reason_codes',
  'output_safety_requires_human',
].sort()
const publicationStatus = 'not_approved_for_publication_or_operational_use' as const
const chunkIdPattern = /^CHUNK_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$/

const invalid = (message: string): never => {
  throw new RealApiError('API_INVALID_RESPONSE', message)
}

function record(value: unknown, message: string): UnknownRecord {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid(message)
  return value as UnknownRecord
}

function exactFields(source: UnknownRecord, fields: string[], message: string): void {
  if (Object.keys(source).sort().join('|') !== fields.join('|')) invalid(message)
}

function text(source: UnknownRecord, key: string, max: number, message: string): string {
  const value = source[key]
  if (typeof value !== 'string' || !value.trim() || value.length > max) return invalid(message)
  return value
}

function token(value: string, message: string): string {
  if (typeof value !== 'string' || !tokenPattern.test(value)) {
    throw new RealApiError('VALIDATION_FAILED', message)
  }
  return value
}

function timestamp(source: UnknownRecord, key: string, message: string): string {
  const value = text(source, key, 64, message)
  if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) || Number.isNaN(Date.parse(value))) return invalid(message)
  return value
}

function pageArguments(offset: number, limit: number): { offset: number; limit: number } {
  if (!Number.isSafeInteger(offset) || offset < 0 || offset > 100_000
    || !Number.isSafeInteger(limit) || limit < 1 || limit > 20) {
    throw new RealApiError('VALIDATION_FAILED', '输出复核分页参数无效。')
  }
  return { offset, limit }
}

function mapSummary(value: unknown, expectedTaskRef: string): ResearchEducationOutputReviewSummary {
  const message = '输出复核记录格式无法识别。'
  const source = record(value, message)
  exactFields(source, summaryFields, message)
  const outputReviewRef = text(source, 'output_review_ref', 37, message)
  const jobRef = text(source, 'job_ref', 68, message)
  const taskRef = text(source, 'task_ref', 128, message)
  const sessionRef = text(source, 'session_ref', 128, message)
  const status = source.status
  const stateVersion = source.state_version
  const generationRound = source.generation_round
  const reasons = source.reason_codes
  if (!/^REOR_[0-9a-f]{32}$/.test(outputReviewRef) || !jobRefPattern.test(jobRef)
    || !tokenPattern.test(taskRef) || taskRef !== expectedTaskRef || !tokenPattern.test(sessionRef)
    || (generationRound !== 0 && generationRound !== 1)
    || typeof status !== 'string' || !['PENDING', 'REJECTED', 'REVOKED', 'CONSUMED'].includes(status)
    || !Number.isSafeInteger(stateVersion)
    || (status === 'PENDING' ? stateVersion !== 1 : stateVersion !== 2)
    || source.safety_action !== 'REVIEW_REQUIRED'
    || !Array.isArray(reasons) || reasons.length !== 1 || reasons[0] !== 'CONTENT_CONTROVERSIAL'
    || source.requires_human !== true || source.purpose !== 'RESEARCH_SIMULATION'
    || source.research_only !== true || source.publication_status !== publicationStatus
    || source.student_feedback_eligible !== false) {
    return invalid(message)
  }
  const expiresAt = timestamp(source, 'expires_at', message)
  const createdAt = timestamp(source, 'created_at', message)
  const updatedAt = timestamp(source, 'updated_at', message)
  if (Date.parse(expiresAt) <= Date.parse(createdAt) || Date.parse(updatedAt) < Date.parse(createdAt)) {
    return invalid(message)
  }
  return Object.freeze({
    output_review_ref: outputReviewRef,
    job_ref: jobRef,
    task_ref: taskRef,
    session_ref: sessionRef,
    generation_round: generationRound,
    status: status as ResearchEducationOutputReviewStatus,
    state_version: stateVersion as number,
    expires_at: expiresAt,
    created_at: createdAt,
    updated_at: updatedAt,
    safety_action: 'REVIEW_REQUIRED',
    reason_codes: ['CONTENT_CONTROVERSIAL'],
    requires_human: true,
    purpose: 'RESEARCH_SIMULATION',
    research_only: true,
    publication_status: publicationStatus,
    student_feedback_eligible: false,
  })
}

function mapPage(value: unknown, taskRef: string, offset: number, limit: number): ResearchEducationOutputReviewPage {
  const message = '输出复核列表格式无法识别。'
  const source = record(value, message)
  exactFields(source, pageFields, message)
  if (source.offset !== offset || source.limit !== limit || typeof source.has_more !== 'boolean'
    || !Array.isArray(source.items) || source.items.length > limit) {
    return invalid(message)
  }
  const items = source.items.map((item) => mapSummary(item, taskRef))
  if (new Set(items.map((item) => item.output_review_ref)).size !== items.length
    || (source.has_more === true && items.length !== limit)) {
    return invalid(message)
  }
  return { items, offset, limit, has_more: source.has_more }
}

function mapContent(value: unknown): ResearchGeneralEducationContent {
  const message = '输出复核正文格式无法识别。'
  const source = record(value, message)
  exactFields(source, contentFields, message)
  if (!Array.isArray(source.observations) || !Array.isArray(source.suggestions)) return invalid(message)
  const observations = source.observations.map((item) => {
    if (typeof item !== 'string') return invalid(message)
    return item
  })
  const suggestions = source.suggestions.map((value) => {
    const item = record(value, message)
    exactFields(item, suggestionFields, message)
    if (!Array.isArray(item.source_chunk_ids) || item.source_chunk_ids.length < 1
      || item.source_chunk_ids.length > 8
      || item.source_chunk_ids.some((id) => typeof id !== 'string' || !chunkIdPattern.test(id))
      || new Set(item.source_chunk_ids).size !== item.source_chunk_ids.length) {
      return invalid(message)
    }
    return Object.freeze({
      text: text(item, 'text', 100_000, message),
      source_chunk_ids: Object.freeze([...item.source_chunk_ids]) as string[],
    })
  })
  return Object.freeze({
    summary: text(source, 'summary', 100_000, message),
    observations: Object.freeze(observations) as string[],
    suggestions: Object.freeze(suggestions) as ResearchGeneralEducationContent['suggestions'],
    disclaimer: text(source, 'disclaimer', 100_000, message),
  })
}

function mapProvenance(value: unknown): ResearchEducationOutputReviewProvenance {
  const message = '输出复核来源追溯格式无法识别。'
  const source = record(value, message)
  exactFields(source, provenanceFields, message)
  const hash = (key: string) => {
    const value = text(source, key, 64, message)
    if (!/^[0-9a-f]{64}$/.test(value)) return invalid(message)
    return value
  }
  const reasonCodes = (key: string) => {
    const codes = source[key]
    if (!Array.isArray(codes) || codes.length < 1 || codes.length > 16
      || codes.some((item) => typeof item !== 'string' || !item.trim() || item.length > 64)) {
      return invalid(message)
    }
    return [...codes] as string[]
  }
  const action = (key: string): ResearchEducationOutputReviewProvenance['input_safety_action'] => {
    const value = source[key]
    if (!['PROCEED', 'PROCEED_WITH_BOUNDARY', 'BLOCK', 'REVIEW_REQUIRED', 'CRISIS_ROUTE'].includes(String(value))) {
      return invalid(message)
    }
    return value as ResearchEducationOutputReviewProvenance['input_safety_action']
  }
  if (source.policy_version !== 'RESEARCH_GENERAL_EDUCATION_DRAFT_V1'
    || source.safety_policy_version !== 'safety-port-unversioned.v1'
    || source.source_age_scope !== '14-17'
    || source.runtime_attempt_count !== 1 || source.runtime_retry_count !== 0
    || source.runtime_fallback_count !== 0 || source.runtime_fallback_attempted !== false
    || source.runtime_local_only !== true || source.output_safety_action !== 'REVIEW_REQUIRED'
    || source.output_safety_requires_human !== true
    || !Array.isArray(source.output_safety_reason_codes)
    || source.output_safety_reason_codes.length !== 1
    || source.output_safety_reason_codes[0] !== 'CONTENT_CONTROVERSIAL') {
    return invalid(message)
  }
  const generationId = text(source, 'generation_id', 164, message)
  const retrievalId = text(source, 'retrieval_id', 164, message)
  const promptId = text(source, 'prompt_id', 164, message)
  if (!/^GEN_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$/.test(generationId)
    || !/^RETR_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$/.test(retrievalId)
    || !/^PROMPT_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$/.test(promptId)) {
    return invalid(message)
  }
  return Object.freeze({
    generation_id: generationId,
    retrieval_id: retrievalId,
    retrieval_bundle_sha256: hash('retrieval_bundle_sha256'),
    policy_version: 'RESEARCH_GENERAL_EDUCATION_DRAFT_V1',
    policy_hash: hash('policy_hash'),
    safety_policy_version: 'safety-port-unversioned.v1',
    source_package_ref: text(source, 'source_package_ref', 255, message),
    source_study_ref: text(source, 'source_study_ref', 255, message),
    source_manifest_sha256: hash('source_manifest_sha256'),
    source_age_scope: '14-17',
    prompt_id: promptId,
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
    input_safety_reason_codes: reasonCodes('input_safety_reason_codes'),
    retrieval_safety_action: action('retrieval_safety_action'),
    retrieval_safety_reason_codes: reasonCodes('retrieval_safety_reason_codes'),
    output_safety_action: 'REVIEW_REQUIRED',
    output_safety_reason_codes: ['CONTENT_CONTROVERSIAL'],
    output_safety_requires_human: true,
  })
}

function mapDetail(value: unknown, taskRef: string, outputReviewRef: string): ResearchEducationOutputReviewDetail {
  const message = '输出复核详情格式无法识别。'
  const source = record(value, message)
  exactFields(source, detailFields, message)
  const summary = mapSummary(
    Object.fromEntries(Object.entries(source).filter(([key]) => summaryFields.includes(key))), taskRef,
  )
  if (summary.output_review_ref !== outputReviewRef) return invalid(message)
  const payload = record(source.review_payload, message)
  exactFields(payload, payloadFields, message)
  if (payload.schema_version !== 'school-research-general-education-output-review.v1'
    || payload.citation_binding_status !== 'NOT_EVALUATED_AT_OUTPUT_STOP') {
    return invalid(message)
  }
  if (!Array.isArray(payload.source_cards) || payload.source_cards.length < 1 || payload.source_cards.length > 8
    || !Array.isArray(payload.citations) || payload.citations.length !== 0) {
    return invalid(message)
  }
  const sourceCards = payload.source_cards.map(mapResearchEducationSourceCard)
  if (new Set(sourceCards.map((card) => card.chunk_id)).size !== sourceCards.length) return invalid(message)
  return Object.freeze({
    ...summary,
    review_payload: Object.freeze({
      content: mapContent(payload.content),
      source_cards: Object.freeze(sourceCards) as FeedbackSourceCard[],
      citations: [],
      schema_version: 'school-research-general-education-output-review.v1',
      citation_binding_status: 'NOT_EVALUATED_AT_OUTPUT_STOP',
      provenance: mapProvenance(payload.provenance),
    }),
  })
}

export class SchoolResearchEducationOutputReviewService {
  async list(taskRef: string, offset = 0, limit = 20): Promise<ResearchEducationOutputReviewPage> {
    const task = token(taskRef, '研究任务编号无效。')
    const paging = pageArguments(offset, limit)
    const data = await requestSchoolResearchFeedbackApi({
      method: 'GET',
      path: `${apiPrefix}/tasks/${encodeURIComponent(task)}/output-reviews`,
      query: paging,
    })
    return mapPage(data, task, offset, limit)
  }

  async get(taskRef: string, outputReviewRef: string): Promise<ResearchEducationOutputReviewDetail> {
    const task = token(taskRef, '研究任务编号无效。')
    const review = token(outputReviewRef, '输出复核编号无效。')
    const data = await requestSchoolResearchFeedbackApi({
      method: 'GET',
      path: `${apiPrefix}/tasks/${encodeURIComponent(task)}/output-reviews/${encodeURIComponent(review)}`,
    })
    return mapDetail(data, task, review)
  }

  async resolve(
    taskRef: string,
    review: ResearchEducationOutputReviewSummary,
    target: ResearchEducationOutputReviewTarget,
    key: string,
  ): Promise<ResearchEducationOutputReviewResolution> {
    const task = token(taskRef, '研究任务编号无效。')
    if (typeof key !== 'string' || !key.trim() || key.length > 255) {
      throw new RealApiError('API_INVALID_REQUEST', '输出复核操作缺少请求标识。')
    }
    if (review.task_ref !== task || review.status !== 'PENDING' || review.state_version !== 1
      || Date.parse(review.expires_at) <= Date.now()
      || !['REJECTED', 'REVOKED', 'CREATE_HELD_CANDIDATE'].includes(target)) {
      throw new RealApiError('WORKFLOW_CONFLICT', '此输出复核已过期或状态已变化。')
    }
    const raw = record(await requestSchoolResearchFeedbackApi({
      method: 'POST',
      path: `${apiPrefix}/tasks/${encodeURIComponent(task)}/output-reviews/${encodeURIComponent(review.output_review_ref)}/resolve`,
      body: { expected_state_version: review.state_version, target },
      idempotencyKey: key,
    }), '输出复核操作响应格式无法识别。')
    const fields = Object.keys(raw).sort()
    const hasOutputReview = fields.join('|') === 'output_review'
      || fields.join('|') === 'candidate|output_review'
    if (!hasOutputReview || (target === 'CREATE_HELD_CANDIDATE' && fields.join('|') !== 'candidate|output_review')
      || (fields.includes('candidate') && raw.candidate !== null && target !== 'CREATE_HELD_CANDIDATE')) {
      return invalid('输出复核操作响应格式无法识别。')
    }
    const updated = mapSummary(raw.output_review, task)
    const expectedStatus = target === 'CREATE_HELD_CANDIDATE' ? 'CONSUMED' : target
    if (updated.output_review_ref !== review.output_review_ref
      || updated.status !== expectedStatus || updated.state_version !== review.state_version + 1) {
      return invalid('输出复核操作结果与请求不一致。')
    }
    if (target !== 'CREATE_HELD_CANDIDATE') return { output_review: updated }
    const candidate = mapResearchEducationCandidateSummary(raw.candidate)
    if (candidate.task_ref !== task || candidate.status !== 'HELD' || candidate.state_version !== 1) {
      return invalid('待审候选结果与请求不一致。')
    }
    return { output_review: updated, candidate }
  }
}

export const schoolResearchEducationOutputReviews = new SchoolResearchEducationOutputReviewService()
export const newResearchEducationOutputReviewIdempotencyKey = newResearchFeedbackIdempotencyKey
