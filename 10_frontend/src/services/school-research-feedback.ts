import { RealApiError } from '@/services/real-api'

type UnknownRecord = Record<string, unknown>
type RequestInput = {
  method: 'GET' | 'POST'
  path: string
  query?: Record<string, string | number>
  body?: Record<string, unknown>
  idempotencyKey?: string
}

export type ResearchReviewTask = {
  task_ref: string
  class_ref: string
  class_display_name: string | null
  published_at: string
}

export type ResearchEligibleSession = {
  session_ref: string
  task_ref: string
  status: 'COMPLETED'
  items_answered: number
  completed_at: string
  case_ref: string | null
}

export type ResearchReviewCaseStatus = 'OPEN' | 'IN_REVIEW' | 'APPROVED' | 'REJECTED'
export type ResearchReviewCase = {
  case_ref: string
  task_ref: string
  session_ref: string
  status: ResearchReviewCaseStatus
  version: number
  created_at: string
  updated_at: string
  review_note: string | null
}

export type ResearchFeedbackStatus = 'DRAFT' | 'PUBLISHED' | 'REVOKED'
export type ResearchFeedback = {
  feedback_ref: string
  case_ref: string
  session_ref: string
  feedback_kind: 'GENERAL_EDUCATIONAL_SUPPORT'
  purpose: 'RESEARCH_SIMULATION'
  research_only: true
  psychological_interpretation_allowed: false
  publication_status: 'not_approved_for_publication_or_operational_use'
  content_revision: number
  case_version: number
  state_version: number
  status: ResearchFeedbackStatus
  title: string
  body: string
  created_at: string
  published_at: string | null
  revoked_at: string | null
}

export type StudentResearchFeedback = Omit<ResearchFeedback, 'case_ref' | 'case_version' | 'status' | 'revoked_at'> & {
  status: 'PUBLISHED'
  published_at: string
}

export type ResearchPage<T> = { items: T[]; total: number }

const apiBaseUrl = new window.URL(import.meta.env.VITE_API_BASE_URL || '/', window.location.origin).toString()
const publicationStatus = 'not_approved_for_publication_or_operational_use' as const

const taskFields = ['task_ref', 'class_ref', 'class_display_name', 'published_at'].sort()
const sessionFields = ['session_ref', 'task_ref', 'status', 'items_answered', 'completed_at', 'case_ref'].sort()
const caseFields = ['case_ref', 'task_ref', 'session_ref', 'status', 'version', 'created_at', 'updated_at', 'review_note'].sort()
const feedbackFields = [
  'feedback_ref', 'case_ref', 'session_ref', 'feedback_kind', 'purpose', 'research_only',
  'psychological_interpretation_allowed', 'publication_status', 'content_revision', 'case_version',
  'state_version', 'status', 'title', 'body', 'created_at', 'published_at', 'revoked_at',
].sort()
const studentFeedbackFields = [
  'feedback_ref', 'session_ref', 'feedback_kind', 'purpose', 'research_only',
  'psychological_interpretation_allowed', 'publication_status', 'content_revision', 'state_version',
  'status', 'title', 'body', 'created_at', 'published_at',
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

const requiredText = (source: UnknownRecord, key: string, maxLength: number, message: string): string => {
  const value = source[key]
  if (typeof value !== 'string' || !value.trim() || value.length > maxLength) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return value
}

const optionalText = (source: UnknownRecord, key: string, maxLength: number, message: string): string | null => {
  const value = source[key]
  if (value === null) return null
  if (typeof value !== 'string' || value.length > maxLength) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return value
}

const timestamp = (source: UnknownRecord, key: string, message: string, nullable = false): string | null => {
  const value = source[key]
  if (nullable && value === null) return null
  if (typeof value !== 'string' || !value.trim() || Number.isNaN(Date.parse(value))) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return value
}

const positiveInt = (source: UnknownRecord, key: string, message: string): number => {
  const value = source[key]
  if (!Number.isSafeInteger(value) || (value as number) < 1 || (value as number) > 2_147_483_647) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return value as number
}

const nonNegativeInt = (source: UnknownRecord, key: string, message: string): number => {
  const value = source[key]
  if (!Number.isSafeInteger(value) || (value as number) < 0) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return value as number
}

const requireRef = (value: string, message = '研究反馈编号无效。') => {
  if (typeof value !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(value)) {
    throw new RealApiError('API_INVALID_REQUEST', message)
  }
}

const mapTask = (value: unknown): ResearchReviewTask => {
  const message = '研究任务列表格式无法识别。'
  const source = record(value, message)
  exactFields(source, taskFields, message)
  const displayName = optionalText(source, 'class_display_name', 160, message)
  return {
    task_ref: requiredText(source, 'task_ref', 128, message),
    class_ref: requiredText(source, 'class_ref', 128, message),
    class_display_name: displayName,
    published_at: timestamp(source, 'published_at', message)!,
  }
}

const mapSession = (value: unknown): ResearchEligibleSession => {
  const message = '已完成记录格式无法识别。'
  const source = record(value, message)
  exactFields(source, sessionFields, message)
  if (source.status !== 'COMPLETED') throw new RealApiError('API_INVALID_RESPONSE', message)
  const caseRef = optionalText(source, 'case_ref', 128, message)
  return {
    session_ref: requiredText(source, 'session_ref', 128, message),
    task_ref: requiredText(source, 'task_ref', 128, message),
    status: 'COMPLETED',
    items_answered: nonNegativeInt(source, 'items_answered', message),
    completed_at: timestamp(source, 'completed_at', message)!,
    case_ref: caseRef,
  }
}

const mapCase = (value: unknown): ResearchReviewCase => {
  const message = '研究复核记录格式无法识别。'
  const source = record(value, message)
  exactFields(source, caseFields, message)
  if (!['OPEN', 'IN_REVIEW', 'APPROVED', 'REJECTED'].includes(String(source.status))) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return {
    case_ref: requiredText(source, 'case_ref', 128, message),
    task_ref: requiredText(source, 'task_ref', 128, message),
    session_ref: requiredText(source, 'session_ref', 128, message),
    status: source.status as ResearchReviewCaseStatus,
    version: positiveInt(source, 'version', message),
    created_at: timestamp(source, 'created_at', message)!,
    updated_at: timestamp(source, 'updated_at', message)!,
    review_note: optionalText(source, 'review_note', 4000, message),
  }
}

const mapFeedback = (value: unknown): ResearchFeedback => {
  const message = '研究反馈版本格式无法识别。'
  const source = record(value, message)
  exactFields(source, feedbackFields, message)
  if (source.feedback_kind !== 'GENERAL_EDUCATIONAL_SUPPORT'
    || source.purpose !== 'RESEARCH_SIMULATION' || source.research_only !== true
    || source.psychological_interpretation_allowed !== false || source.publication_status !== publicationStatus
    || !['DRAFT', 'PUBLISHED', 'REVOKED'].includes(String(source.status))) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  const status = source.status as ResearchFeedbackStatus
  const publishedAt = timestamp(source, 'published_at', message, true)
  const revokedAt = timestamp(source, 'revoked_at', message, true)
  if ((status === 'DRAFT' && (publishedAt !== null || revokedAt !== null))
    || (status === 'PUBLISHED' && (publishedAt === null || revokedAt !== null))
    || (status === 'REVOKED' && (publishedAt === null || revokedAt === null))) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return {
    feedback_ref: requiredText(source, 'feedback_ref', 128, message),
    case_ref: requiredText(source, 'case_ref', 128, message),
    session_ref: requiredText(source, 'session_ref', 128, message),
    feedback_kind: 'GENERAL_EDUCATIONAL_SUPPORT',
    purpose: 'RESEARCH_SIMULATION',
    research_only: true,
    psychological_interpretation_allowed: false,
    publication_status: publicationStatus,
    content_revision: positiveInt(source, 'content_revision', message),
    case_version: positiveInt(source, 'case_version', message),
    state_version: positiveInt(source, 'state_version', message),
    status,
    title: requiredText(source, 'title', 120, message),
    body: requiredText(source, 'body', 4000, message),
    created_at: timestamp(source, 'created_at', message)!,
    published_at: publishedAt,
    revoked_at: revokedAt,
  }
}

const mapStudentFeedback = (value: unknown): StudentResearchFeedback => {
  const message = '学生反馈记录格式无法识别。'
  const source = record(value, message)
  exactFields(source, studentFeedbackFields, message)
  if (source.feedback_kind !== 'GENERAL_EDUCATIONAL_SUPPORT'
    || source.purpose !== 'RESEARCH_SIMULATION' || source.research_only !== true
    || source.psychological_interpretation_allowed !== false || source.publication_status !== publicationStatus
    || source.status !== 'PUBLISHED') {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return {
    feedback_ref: requiredText(source, 'feedback_ref', 128, message),
    session_ref: requiredText(source, 'session_ref', 128, message),
    feedback_kind: 'GENERAL_EDUCATIONAL_SUPPORT',
    purpose: 'RESEARCH_SIMULATION',
    research_only: true,
    psychological_interpretation_allowed: false,
    publication_status: publicationStatus,
    content_revision: positiveInt(source, 'content_revision', message),
    state_version: positiveInt(source, 'state_version', message),
    status: 'PUBLISHED',
    title: requiredText(source, 'title', 120, message),
    body: requiredText(source, 'body', 4000, message),
    created_at: timestamp(source, 'created_at', message)!,
    published_at: timestamp(source, 'published_at', message)!,
  }
}

const mapPage = <T>(value: unknown, mapper: (item: unknown) => T, limit: number): ResearchPage<T> => {
  const message = '研究反馈列表格式无法识别。'
  const source = record(value, message)
  exactFields(source, ['items', 'total'], message)
  if (!Array.isArray(source.items) || !Number.isSafeInteger(source.total)
    || (source.total as number) < 0 || source.items.length > (source.total as number)
    || source.items.length > limit) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  const items = source.items.map(mapper)
  const refs = items.map((item) => (item as { case_ref?: string; feedback_ref?: string; session_ref?: string }).feedback_ref
    ?? (item as { case_ref?: string }).case_ref ?? (item as { session_ref?: string }).session_ref)
  if (new Set(refs).size !== refs.length) throw new RealApiError('API_INVALID_RESPONSE', message)
  return { items, total: source.total as number }
}

const unwrap = async (value: unknown): Promise<unknown> => {
  const envelope = record(value, '研究反馈接口响应格式无法识别。')
  if (envelope.error) {
    const problem = record(envelope.error, '接口请求没有完成。')
    throw new RealApiError(
      typeof problem.code === 'string' ? problem.code.toUpperCase() : 'API_ERROR',
      typeof problem.detail === 'string' ? problem.detail : '接口请求没有完成。',
      problem.retryable === true,
    )
  }
  if (typeof envelope.request_id !== 'string' || typeof envelope.trace_id !== 'string' || !('data' in envelope)) {
    throw new RealApiError('API_INVALID_RESPONSE', '研究反馈接口响应格式无法识别。')
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
    throw new RealApiError('NETWORK_UNAVAILABLE', '研究反馈服务暂时无法连接。', true)
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

async function request(input: RequestInput): Promise<unknown> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (input.method === 'POST') {
    if (!input.idempotencyKey?.trim()) throw new RealApiError('API_INVALID_REQUEST', '研究反馈操作缺少请求标识。')
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
    throw new RealApiError('NETWORK_UNAVAILABLE', '研究反馈服务暂时无法连接。', true)
  }
  let raw: unknown
  try {
    raw = await response.json()
  } catch {
    throw new RealApiError('API_INVALID_RESPONSE', '研究反馈服务返回了无法识别的响应。')
  }
  if (!response.ok) await unwrap(raw)
  return unwrap(raw)
}

function pagination(offset: number, limit: number) {
  if (!Number.isSafeInteger(offset) || offset < 0 || offset > 100_000
    || !Number.isSafeInteger(limit) || limit < 1 || limit > 50) {
    throw new RealApiError('VALIDATION_FAILED', '分页参数无效。')
  }
  return { offset, limit }
}

function idempotencyKey(value: string) {
  if (!value.trim() || value.length > 255) throw new RealApiError('API_INVALID_REQUEST', '研究反馈操作缺少请求标识。')
}

export class SchoolResearchFeedbackService {
  async listTasks(): Promise<ResearchReviewTask[]> {
    const data = record(await request({ method: 'GET', path: '/api/v1/school/research-feedback/tasks' }), '研究任务列表格式无法识别。')
    exactFields(data, ['items'], '研究任务列表格式无法识别。')
    if (!Array.isArray(data.items)) throw new RealApiError('API_INVALID_RESPONSE', '研究任务列表格式无法识别。')
    const rows = data.items.map(mapTask)
    if (new Set(rows.map((row) => row.task_ref)).size !== rows.length) throw new RealApiError('API_INVALID_RESPONSE', '研究任务列表包含重复项目。')
    return rows
  }

  async listEligibleSessions(taskRef: string, offset = 0, limit = 20): Promise<ResearchPage<ResearchEligibleSession>> {
    requireRef(taskRef)
    const data = await request({ method: 'GET', path: `/api/v1/school/research-feedback/tasks/${encodeURIComponent(taskRef)}/eligible-sessions`, query: pagination(offset, limit) })
    return mapPage(data, mapSession, limit)
  }

  async listCases(taskRef: string, offset = 0, limit = 20, status?: ResearchReviewCaseStatus): Promise<ResearchPage<ResearchReviewCase>> {
    requireRef(taskRef)
    const query = pagination(offset, limit)
    const data = await request({ method: 'GET', path: `/api/v1/school/research-feedback/tasks/${encodeURIComponent(taskRef)}/cases`, query: status ? { ...query, status } : query })
    return mapPage(data, mapCase, limit)
  }

  async getCase(taskRef: string, caseRef: string): Promise<ResearchReviewCase> {
    requireRef(taskRef); requireRef(caseRef)
    return mapCase(await request({ method: 'GET', path: `/api/v1/school/research-feedback/tasks/${encodeURIComponent(taskRef)}/cases/${encodeURIComponent(caseRef)}` }))
  }

  async createCase(taskRef: string, sessionRef: string, key: string): Promise<ResearchReviewCase> {
    requireRef(taskRef); requireRef(sessionRef); idempotencyKey(key)
    return mapCase(await request({ method: 'POST', path: `/api/v1/school/research-feedback/tasks/${encodeURIComponent(taskRef)}/cases`, body: { session_ref: sessionRef }, idempotencyKey: key }))
  }

  async transitionCase(taskRef: string, caseRef: string, expectedVersion: number, status: ResearchReviewCaseStatus, note: string, key: string): Promise<ResearchReviewCase> {
    requireRef(taskRef); requireRef(caseRef); idempotencyKey(key)
    if (!Number.isSafeInteger(expectedVersion) || expectedVersion < 1 || !note.trim() || note.length > 4000
      || !['OPEN', 'IN_REVIEW', 'APPROVED', 'REJECTED'].includes(status)) {
      throw new RealApiError('VALIDATION_FAILED', '复核记录或备注无效。')
    }
    return mapCase(await request({
      method: 'POST', path: `/api/v1/school/research-feedback/tasks/${encodeURIComponent(taskRef)}/cases/${encodeURIComponent(caseRef)}/decision`,
      body: { expected_version: expectedVersion, status, note }, idempotencyKey: key,
    }))
  }

  async listFeedback(caseRef: string, offset = 0, limit = 20): Promise<ResearchPage<ResearchFeedback>> {
    requireRef(caseRef)
    const data = await request({ method: 'GET', path: `/api/v1/school/research-feedback/cases/${encodeURIComponent(caseRef)}/feedback`, query: pagination(offset, limit) })
    return mapPage(data, mapFeedback, limit)
  }

  async createDraft(caseRef: string, expectedCaseVersion: number, title: string, body: string, key: string): Promise<ResearchFeedback> {
    requireRef(caseRef); idempotencyKey(key)
    if (!Number.isSafeInteger(expectedCaseVersion) || expectedCaseVersion < 1
      || !title.trim() || title.length > 120 || !body.trim() || body.length > 4000) {
      throw new RealApiError('VALIDATION_FAILED', '反馈标题或正文无效。')
    }
    return mapFeedback(await request({
      method: 'POST', path: `/api/v1/school/research-feedback/cases/${encodeURIComponent(caseRef)}/draft`,
      body: { expected_case_version: expectedCaseVersion, title, body }, idempotencyKey: key,
    }))
  }

  async publish(item: ResearchFeedback, key: string): Promise<ResearchFeedback> {
    requireRef(item.feedback_ref); idempotencyKey(key)
    return mapFeedback(await request({
      method: 'POST', path: `/api/v1/school/research-feedback/feedback/${encodeURIComponent(item.feedback_ref)}/publish`,
      body: { expected_state_version: item.state_version, expected_case_version: item.case_version }, idempotencyKey: key,
    }))
  }

  async revoke(item: ResearchFeedback, key: string): Promise<ResearchFeedback> {
    requireRef(item.feedback_ref); idempotencyKey(key)
    return mapFeedback(await request({
      method: 'POST', path: `/api/v1/school/research-feedback/feedback/${encodeURIComponent(item.feedback_ref)}/revoke`,
      body: { expected_state_version: item.state_version }, idempotencyKey: key,
    }))
  }

  async listStudent(offset = 0, limit = 20): Promise<ResearchPage<StudentResearchFeedback>> {
    const data = await request({ method: 'GET', path: '/api/v1/school/research-feedback/student', query: pagination(offset, limit) })
    return mapPage(data, mapStudentFeedback, limit)
  }
}

export const schoolResearchFeedback = new SchoolResearchFeedbackService()

export const newResearchFeedbackIdempotencyKey = (): string => {
  if (typeof crypto === 'undefined' || typeof crypto.randomUUID !== 'function') {
    throw new RealApiError('SECURE_RANDOM_UNAVAILABLE', '当前浏览器无法安全建立请求标识。')
  }
  return `research-feedback-${crypto.randomUUID()}`
}
