import { RealApiError } from '@/services/real-api'

type UnknownRecord = Record<string, unknown>
type RequestOptions = {
  method: 'GET' | 'POST'
  path: string
  query?: Record<string, number>
  body?: Record<string, unknown>
  idempotencyKey?: string
}

export type FeedbackStatus = 'DRAFT' | 'PUBLISHED' | 'REVOKED'

export type SchoolFeedback = {
  feedback_ref: string
  case_ref: string
  assessment_ref: string
  level: 'L3'
  synthetic_only: true
  content_revision: number
  state_version: number
  case_version: number
  status: FeedbackStatus
  title: string
  body: string
  created_at: string
  published_at: string | null
  revoked_at: string | null
}

export type StudentSchoolFeedback = {
  feedback_ref: string
  assessment_ref: string
  level: 'L3'
  synthetic_only: true
  content_revision: number
  state_version: number
  status: 'PUBLISHED'
  title: string
  body: string
  created_at: string
  published_at: string
}

export type SchoolFeedbackPage<T> = { items: T[]; total: number }

const apiBaseUrl = new window.URL(import.meta.env.VITE_API_BASE_URL || '/', window.location.origin).toString()
const specialistFields = [
  'feedback_ref', 'case_ref', 'assessment_ref', 'level', 'synthetic_only',
  'content_revision', 'state_version', 'case_version', 'status', 'title', 'body',
  'created_at', 'published_at', 'revoked_at',
].sort()
const studentFields = [
  'feedback_ref', 'assessment_ref', 'level', 'synthetic_only', 'content_revision',
  'state_version', 'status', 'title', 'body', 'created_at', 'published_at',
].sort()

const record = (value: unknown, message: string): UnknownRecord => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return value as UnknownRecord
}

const exactFields = (source: UnknownRecord, fields: string[], message: string) => {
  if (Object.keys(source).sort().join('|') !== fields.join('|')) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
}

const requiredText = (source: UnknownRecord, key: string, maxLength: number, message: string) => {
  const value = source[key]
  if (typeof value !== 'string' || !value.trim() || value.length > maxLength) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return value
}

const timestamp = (source: UnknownRecord, key: string, message: string, nullable = false) => {
  const value = source[key]
  if (nullable && value === null) return null
  if (typeof value !== 'string' || !value.trim() || Number.isNaN(Date.parse(value))) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return value
}

const version = (source: UnknownRecord, key: string, message: string) => {
  const value = source[key]
  if (!Number.isSafeInteger(value) || (value as number) < 1 || (value as number) > 2147483647) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return value as number
}

const validateCommon = (source: UnknownRecord, student: boolean) => {
  const message = '反馈记录格式无法识别。'
  exactFields(source, student ? studentFields : specialistFields, message)
  const feedbackRef = requiredText(source, 'feedback_ref', 128, message)
  const assessmentRef = requiredText(source, 'assessment_ref', 128, message)
  if (!/^FEED_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$/.test(feedbackRef)
    || !/^ASSESS_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$/.test(assessmentRef)
    || source.level !== 'L3' || source.synthetic_only !== true
    || (student ? source.status !== 'PUBLISHED' : !['DRAFT', 'PUBLISHED', 'REVOKED'].includes(String(source.status)))) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  const title = requiredText(source, 'title', 120, message)
  const body = requiredText(source, 'body', 2000, message)
  const createdAt = timestamp(source, 'created_at', message)!
  const publishedAt = timestamp(source, 'published_at', message, !student)
  const revisions = {
    content_revision: version(source, 'content_revision', message),
    state_version: version(source, 'state_version', message),
  }
  if (student) {
    return {
      feedback_ref: feedbackRef,
      assessment_ref: assessmentRef,
      level: 'L3' as const,
      synthetic_only: true as const,
      ...revisions,
      status: 'PUBLISHED' as const,
      title,
      body,
      created_at: createdAt,
      published_at: publishedAt!,
    }
  }
  const caseRef = requiredText(source, 'case_ref', 128, message)
  if (!/^PCR_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$/.test(caseRef)) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return {
    feedback_ref: feedbackRef,
    case_ref: caseRef,
    assessment_ref: assessmentRef,
    level: 'L3' as const,
    synthetic_only: true as const,
    ...revisions,
    case_version: version(source, 'case_version', message),
    status: source.status as FeedbackStatus,
    title,
    body,
    created_at: createdAt,
    published_at: publishedAt,
    revoked_at: timestamp(source, 'revoked_at', message, true),
  }
}

const mapSpecialist = (value: unknown): SchoolFeedback =>
  validateCommon(record(value, '反馈记录格式无法识别。'), false) as SchoolFeedback

const mapStudent = (value: unknown): StudentSchoolFeedback =>
  validateCommon(record(value, '反馈记录格式无法识别。'), true) as StudentSchoolFeedback

const mapPage = <T>(value: unknown, mapper: (item: unknown) => T, limit: number): SchoolFeedbackPage<T> => {
  const source = record(value, '反馈列表格式无法识别。')
  exactFields(source, ['items', 'total'], '反馈列表格式无法识别。')
  if (!Array.isArray(source.items) || !Number.isSafeInteger(source.total)
    || (source.total as number) < 0 || source.items.length > (source.total as number)
    || source.items.length > limit) {
    throw new RealApiError('API_INVALID_RESPONSE', '反馈列表格式无法识别。')
  }
  const items = source.items.map(mapper)
  const ids = items.map((item) => (item as SchoolFeedback | StudentSchoolFeedback).feedback_ref)
  if (new Set(ids).size !== ids.length) {
    throw new RealApiError('API_INVALID_RESPONSE', '反馈列表包含重复记录。')
  }
  return { items, total: source.total as number }
}

const unwrap = async (value: unknown): Promise<unknown> => {
  const envelope = record(value, '反馈接口响应格式无法识别。')
  if (envelope.error) {
    const problem = record(envelope.error, '接口请求没有完成。')
    throw new RealApiError(
      typeof problem.code === 'string' ? problem.code.toUpperCase() : 'API_ERROR',
      typeof problem.detail === 'string' ? problem.detail : '接口请求没有完成。',
      problem.retryable === true,
    )
  }
  if (typeof envelope.request_id !== 'string' || typeof envelope.trace_id !== 'string' || !('data' in envelope)) {
    throw new RealApiError('API_INVALID_RESPONSE', '反馈接口响应格式无法识别。')
  }
  return envelope.data
}

const endpoint = (path: string) => new window.URL(path, apiBaseUrl).toString()

async function csrfToken(): Promise<string> {
  let response: Response
  try {
    response = await fetch(endpoint('/api/v1/auth/csrf'), {
      method: 'GET', credentials: 'include', headers: { Accept: 'application/json' },
    })
  } catch {
    throw new RealApiError('NETWORK_UNAVAILABLE', '反馈服务暂时无法连接。', true)
  }
  let raw: unknown
  try {
    raw = await response.json()
  } catch {
    throw new RealApiError('API_INVALID_RESPONSE', '安全请求校验暂不可用。')
  }
  if (!response.ok) await unwrap(raw)
  const data = record(await unwrap(raw), '安全请求校验格式无法识别。')
  return requiredText(data, 'csrf_token', 512, '安全请求校验格式无法识别。')
}

async function request(input: RequestOptions): Promise<unknown> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (input.method === 'POST') {
    if (!input.idempotencyKey?.trim()) throw new RealApiError('API_INVALID_REQUEST', '反馈操作缺少请求标识。')
    headers['Content-Type'] = 'application/json'
    headers['X-CSRF-Token'] = await csrfToken()
    headers['Idempotency-Key'] = input.idempotencyKey
  }
  const url = new window.URL(input.path, apiBaseUrl)
  for (const [key, value] of Object.entries(input.query ?? {})) url.searchParams.set(key, String(value))
  let response: Response
  try {
    response = await fetch(url.toString(), {
      method: input.method,
      credentials: 'include',
      headers,
      ...(input.body ? { body: JSON.stringify(input.body) } : {}),
    })
  } catch {
    throw new RealApiError('NETWORK_UNAVAILABLE', '反馈服务暂时无法连接。', true)
  }
  let raw: unknown
  try {
    raw = await response.json()
  } catch {
    throw new RealApiError('API_INVALID_RESPONSE', '反馈服务返回了无法识别的响应。')
  }
  if (!response.ok) await unwrap(raw)
  return unwrap(raw)
}

const requireId = (value: string, prefix: 'PCR' | 'FEED') => {
  if (!new RegExp(`^${prefix}_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$`).test(value)) {
    throw new RealApiError('API_INVALID_REQUEST', '反馈记录编号无效。')
  }
}

function pagination(offset: number, limit: number) {
  if (!Number.isSafeInteger(offset) || offset < 0 || offset > 100000
    || !Number.isSafeInteger(limit) || limit < 1 || limit > 50) {
    throw new RealApiError('VALIDATION_FAILED', '分页参数无效。')
  }
  return { offset, limit }
}

export class SchoolFeedbackService {
  async listCase(caseRef: string, offset = 0, limit = 50): Promise<SchoolFeedbackPage<SchoolFeedback>> {
    requireId(caseRef, 'PCR')
    const data = await request({ method: 'GET', path: `/api/v1/school/feedback/cases/${encodeURIComponent(caseRef)}`, query: pagination(offset, limit) })
    return mapPage(data, mapSpecialist, limit)
  }

  async createDraft(
    caseRef: string,
    expectedCaseVersion: number,
    title: string,
    body: string,
    idempotencyKey: string,
  ): Promise<SchoolFeedback> {
    requireId(caseRef, 'PCR')
    if (!Number.isSafeInteger(expectedCaseVersion) || expectedCaseVersion < 1
      || !title.trim() || title.length > 120 || !body.trim() || body.length > 2000) {
      throw new RealApiError('VALIDATION_FAILED', '标题或正文格式不符合要求。')
    }
    const data = await request({
      method: 'POST', path: `/api/v1/school/feedback/cases/${encodeURIComponent(caseRef)}`,
      body: { expected_case_version: expectedCaseVersion, title, body }, idempotencyKey,
    })
    const row = mapSpecialist(data)
    if (row.status !== 'DRAFT' || row.case_ref !== caseRef || row.case_version !== expectedCaseVersion) {
      throw new RealApiError('API_INVALID_RESPONSE', '草稿响应与当前复核记录不一致。')
    }
    return row
  }

  async publish(feedback: SchoolFeedback, idempotencyKey: string): Promise<SchoolFeedback> {
    requireId(feedback.feedback_ref, 'FEED')
    const data = await request({
      method: 'POST', path: `/api/v1/school/feedback/${encodeURIComponent(feedback.feedback_ref)}/publish`,
      body: { expected_case_version: feedback.case_version, expected_state_version: feedback.state_version },
      idempotencyKey,
    })
    const row = mapSpecialist(data)
    if (row.status !== 'PUBLISHED' || row.feedback_ref !== feedback.feedback_ref
      || row.case_ref !== feedback.case_ref || row.case_version !== feedback.case_version
      || row.state_version !== feedback.state_version + 1) {
      throw new RealApiError('API_INVALID_RESPONSE', '发布响应与当前反馈版本不一致。')
    }
    return row
  }

  async revoke(feedback: SchoolFeedback, idempotencyKey: string): Promise<SchoolFeedback> {
    requireId(feedback.feedback_ref, 'FEED')
    const data = await request({
      method: 'POST', path: `/api/v1/school/feedback/${encodeURIComponent(feedback.feedback_ref)}/revoke`,
      body: { expected_case_version: feedback.case_version, expected_state_version: feedback.state_version },
      idempotencyKey,
    })
    const row = mapSpecialist(data)
    if (row.status !== 'REVOKED' || row.feedback_ref !== feedback.feedback_ref
      || row.case_ref !== feedback.case_ref || row.case_version !== feedback.case_version
      || row.state_version !== feedback.state_version + 1) {
      throw new RealApiError('API_INVALID_RESPONSE', '撤回响应与当前反馈版本不一致。')
    }
    return row
  }

  async listStudent(offset = 0, limit = 50): Promise<SchoolFeedbackPage<StudentSchoolFeedback>> {
    const data = await request({
      method: 'GET', path: '/api/v1/school/feedback/student', query: pagination(offset, limit),
    })
    return mapPage(data, mapStudent, limit)
  }
}

export const schoolFeedback = new SchoolFeedbackService()

export const newSchoolFeedbackIdempotencyKey = (): string => {
  if (typeof crypto === 'undefined' || typeof crypto.randomUUID !== 'function') {
    throw new RealApiError('SECURE_RANDOM_UNAVAILABLE', '当前浏览器无法安全建立请求标识。')
  }
  return `school-feedback-${crypto.randomUUID()}`
}
