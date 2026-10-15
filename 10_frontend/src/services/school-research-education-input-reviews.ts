import { RealApiError } from '@/services/real-api'
import {
  newResearchFeedbackIdempotencyKey,
  requestSchoolResearchFeedbackApi,
} from '@/services/school-research-feedback'

type UnknownRecord = Record<string, unknown>

export type ResearchEducationInputReviewStatus =
  | 'PENDING'
  | 'CONTINUATION_AUTHORIZED'
  | 'CONSUMED'
  | 'REJECTED'
  | 'REVOKED'
export type ResearchEducationInputReviewTarget =
  | 'CONTINUATION_AUTHORIZED'
  | 'REJECTED'
  | 'REVOKED'

export type ResearchEducationInputReviewSummary = {
  input_review_ref: string
  job_ref: string
  task_ref: string
  session_ref: string
  status: ResearchEducationInputReviewStatus
  state_version: number
  expires_at: string
  created_at: string
  updated_at: string
  reason_codes: ['CONTENT_CONTROVERSIAL']
  purpose: 'RESEARCH_SIMULATION'
  research_only: true
  continuation_enabled: boolean
}

export type ResearchEducationInputReviewDetail = ResearchEducationInputReviewSummary & {
  fixed_request: string
  canonical_input_sha256: string
  policy_version: 'RESEARCH_GENERAL_EDUCATION_DRAFT_V1'
  policy_hash: string
  source_package_ref: string
  source_study_ref: string
  source_manifest_sha256: string
  prompt_id: string
  prompt_version: string
  prompt_sha256: string
}

export type ResearchEducationInputReviewPage = {
  items: ResearchEducationInputReviewSummary[]
  offset: number
  limit: number
  has_more: boolean
}

const summaryFields = [
  'input_review_ref', 'job_ref', 'task_ref', 'session_ref', 'status', 'state_version',
  'expires_at', 'created_at', 'updated_at', 'reason_codes', 'purpose', 'research_only',
  'continuation_enabled',
].sort()
const detailFields = [
  ...summaryFields,
  'fixed_request', 'canonical_input_sha256', 'policy_version', 'policy_hash',
  'source_package_ref', 'source_study_ref', 'source_manifest_sha256',
  'prompt_id', 'prompt_version', 'prompt_sha256',
].sort()
const pageFields = ['items', 'offset', 'limit', 'has_more'].sort()
const tokenPattern = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/
const jobRefPattern = /^REJ_[0-9a-f]{64}$/
const sha256Pattern = /^[0-9a-f]{64}$/
const promptRefPattern = /^PROMPT_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$/
const apiPrefix = '/api/v1/school/research-education-candidates'
const fixedPolicyVersion = 'RESEARCH_GENERAL_EDUCATION_DRAFT_V1' as const

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

function boundedText(source: UnknownRecord, key: string, max: number, message: string): string {
  const value = source[key]
  if (typeof value !== 'string' || !value.trim() || value.length > max) return invalid(message)
  return value
}

function token(source: UnknownRecord, key: string, message: string): string {
  const value = boundedText(source, key, 128, message)
  if (!tokenPattern.test(value)) return invalid(message)
  return value
}

function timestamp(source: UnknownRecord, key: string, message: string): string {
  const value = boundedText(source, key, 64, message)
  if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) || Number.isNaN(Date.parse(value))) return invalid(message)
  return value
}

function digest(source: UnknownRecord, key: string, message: string): string {
  const value = boundedText(source, key, 64, message)
  if (!sha256Pattern.test(value)) return invalid(message)
  return value
}

function taskArgument(value: string): string {
  if (typeof value !== 'string' || !tokenPattern.test(value)) {
    throw new RealApiError('VALIDATION_FAILED', '研究任务编号无效。')
  }
  return value
}

function pageArguments(offset: number, limit: number): { offset: number; limit: number } {
  if (!Number.isSafeInteger(offset) || offset < 0 || offset > 100_000
    || !Number.isSafeInteger(limit) || limit < 1 || limit > 20) {
    throw new RealApiError('VALIDATION_FAILED', '输入复核分页参数无效。')
  }
  return { offset, limit }
}

function idempotencyArgument(value: string): void {
  if (typeof value !== 'string' || !value.trim() || value.length > 255) {
    throw new RealApiError('API_INVALID_REQUEST', '输入复核操作缺少请求标识。')
  }
}

function mapSummary(value: unknown, expectedTaskRef: string): ResearchEducationInputReviewSummary {
  const message = '输入复核记录格式无法识别。'
  const source = record(value, message)
  exactFields(source, summaryFields, message)
  const inputReviewRef = token(source, 'input_review_ref', message)
  const taskRef = token(source, 'task_ref', message)
  const sessionRef = token(source, 'session_ref', message)
  const jobRef = boundedText(source, 'job_ref', 68, message)
  const status = source.status
  const stateVersion = source.state_version
  const reasons = source.reason_codes
  const versions: Record<string, number[]> = {
    PENDING: [1],
    CONTINUATION_AUTHORIZED: [2],
    CONSUMED: [3],
    REJECTED: [2],
    REVOKED: [2, 3],
  }
  if (taskRef !== expectedTaskRef || !jobRefPattern.test(jobRef)
    || typeof status !== 'string' || !(status in versions)
    || !Number.isSafeInteger(stateVersion) || !versions[status]?.includes(stateVersion as number)
    || !Array.isArray(reasons) || reasons.length !== 1 || reasons[0] !== 'CONTENT_CONTROVERSIAL'
    || source.purpose !== 'RESEARCH_SIMULATION' || source.research_only !== true
    || typeof source.continuation_enabled !== 'boolean') {
    return invalid(message)
  }
  const expiresAt = timestamp(source, 'expires_at', message)
  const createdAt = timestamp(source, 'created_at', message)
  const updatedAt = timestamp(source, 'updated_at', message)
  if (Date.parse(expiresAt) <= Date.parse(createdAt) || Date.parse(updatedAt) < Date.parse(createdAt)) {
    return invalid(message)
  }
  return Object.freeze({
    input_review_ref: inputReviewRef,
    job_ref: jobRef,
    task_ref: taskRef,
    session_ref: sessionRef,
    status,
    state_version: stateVersion as number,
    expires_at: expiresAt,
    created_at: createdAt,
    updated_at: updatedAt,
    reason_codes: ['CONTENT_CONTROVERSIAL'],
    purpose: 'RESEARCH_SIMULATION',
    research_only: true,
    continuation_enabled: source.continuation_enabled,
  })
}

function mapDetail(value: unknown, expectedTaskRef: string, expectedReviewRef: string): ResearchEducationInputReviewDetail {
  const message = '输入复核详情格式无法识别。'
  const source = record(value, message)
  exactFields(source, detailFields, message)
  const summary = mapSummary(
    Object.fromEntries(Object.entries(source).filter(([key]) => summaryFields.includes(key))),
    expectedTaskRef,
  )
  if (summary.input_review_ref !== expectedReviewRef
    || source.policy_version !== fixedPolicyVersion) return invalid(message)
  const fixedRequest = boundedText(source, 'fixed_request', 2_000, message)
  const sourcePackageRef = token(source, 'source_package_ref', message)
  const sourceStudyRef = token(source, 'source_study_ref', message)
  const promptId = boundedText(source, 'prompt_id', 164, message)
  if (!promptRefPattern.test(promptId)) return invalid(message)
  return Object.freeze({
    ...summary,
    fixed_request: fixedRequest,
    canonical_input_sha256: digest(source, 'canonical_input_sha256', message),
    policy_version: fixedPolicyVersion,
    policy_hash: digest(source, 'policy_hash', message),
    source_package_ref: sourcePackageRef,
    source_study_ref: sourceStudyRef,
    source_manifest_sha256: digest(source, 'source_manifest_sha256', message),
    prompt_id: promptId,
    prompt_version: boundedText(source, 'prompt_version', 64, message),
    prompt_sha256: digest(source, 'prompt_sha256', message),
  })
}

function mapPage(value: unknown, taskRef: string, offset: number, limit: number): ResearchEducationInputReviewPage {
  const message = '输入复核列表格式无法识别。'
  const source = record(value, message)
  exactFields(source, pageFields, message)
  if (source.offset !== offset || source.limit !== limit || typeof source.has_more !== 'boolean'
    || !Array.isArray(source.items) || source.items.length > limit
    || (source.has_more === true && source.items.length !== limit)) {
    return invalid(message)
  }
  const items = source.items.map((item) => mapSummary(item, taskRef))
  if (new Set(items.map((item) => item.input_review_ref)).size !== items.length) return invalid(message)
  return { items, offset, limit, has_more: source.has_more }
}

export class SchoolResearchEducationInputReviewService {
  async list(taskRef: string, offset = 0, limit = 20): Promise<ResearchEducationInputReviewPage> {
    taskArgument(taskRef)
    const page = pageArguments(offset, limit)
    const data = await requestSchoolResearchFeedbackApi({
      method: 'GET',
      path: `${apiPrefix}/tasks/${encodeURIComponent(taskRef)}/input-reviews`,
      query: page,
    })
    return mapPage(data, taskRef, offset, limit)
  }

  async get(taskRef: string, inputReviewRef: string): Promise<ResearchEducationInputReviewDetail> {
    taskArgument(taskRef)
    if (!tokenPattern.test(inputReviewRef)) {
      throw new RealApiError('VALIDATION_FAILED', '输入复核编号无效。')
    }
    const data = await requestSchoolResearchFeedbackApi({
      method: 'GET',
      path: `${apiPrefix}/tasks/${encodeURIComponent(taskRef)}/input-reviews/${encodeURIComponent(inputReviewRef)}`,
    })
    return mapDetail(data, taskRef, inputReviewRef)
  }

  async resolve(
    taskRef: string,
    review: ResearchEducationInputReviewSummary,
    target: ResearchEducationInputReviewTarget,
    key: string,
  ): Promise<ResearchEducationInputReviewSummary> {
    taskArgument(taskRef)
    idempotencyArgument(key)
    const pending = review.status === 'PENDING' && review.state_version === 1
    const authorized = review.status === 'CONTINUATION_AUTHORIZED' && review.state_version === 2
    const validTarget = target === 'CONTINUATION_AUTHORIZED'
      ? pending && review.continuation_enabled
      : target === 'REJECTED'
        ? pending
        : target === 'REVOKED' && (pending || authorized)
    if (review.task_ref !== taskRef || !validTarget || Date.parse(review.expires_at) <= Date.now()) {
      throw new RealApiError('WORKFLOW_CONFLICT', '这条输入复核已过期或状态已变化。')
    }
    const updated = mapSummary(await requestSchoolResearchFeedbackApi({
      method: 'POST',
      path: `${apiPrefix}/tasks/${encodeURIComponent(taskRef)}/input-reviews/${encodeURIComponent(review.input_review_ref)}/resolve`,
      body: { expected_state_version: review.state_version, target },
      idempotencyKey: key,
    }), taskRef)
    const expectedStatus = target
    if (updated.input_review_ref !== review.input_review_ref || updated.status !== expectedStatus
      || updated.state_version !== review.state_version + 1) {
      return invalid('输入复核结果与请求不一致。')
    }
    return updated
  }
}

export const schoolResearchEducationInputReviews = new SchoolResearchEducationInputReviewService()
export const newResearchEducationInputReviewIdempotencyKey = newResearchFeedbackIdempotencyKey
