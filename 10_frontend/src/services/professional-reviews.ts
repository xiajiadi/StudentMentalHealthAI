import { RealApiError, requestProfessionalReview } from '@/services/real-api'

type UnknownRecord = Record<string, unknown>
type ReviewRequest = Parameters<typeof requestProfessionalReview>[0]

export type ProfessionalReviewTask = {
  task_ref: string
  class_ref: string
  class_display_name: string | null
  published_at: string
}

export type EligibleEnrollment = {
  enrollment_ref: string
  assessment_ref: string
  completed_at: string
  case_ref: string | null
}

export type ProfessionalReviewCase = {
  case_ref: string
  task_ref: string
  enrollment_ref: string
  assessment_ref: string
  status: 'OPEN' | 'IN_REVIEW' | 'APPROVED' | 'REJECTED'
  publication_status: 'NOT_PUBLISHED'
  version: number
  created_at: string
  updated_at: string
  decision: 'APPROVED' | 'REJECTED' | null
  review_note: string | null
}

export type PagedResult<T> = { items: T[]; total: number }

const record = (value: unknown, message: string): UnknownRecord => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return value as UnknownRecord
}

const text = (source: UnknownRecord, key: string, message: string, allowEmpty = false): string => {
  const value = source[key]
  if (typeof value !== 'string' || (!allowEmpty && !value.trim())) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return value
}

const timestamp = (source: UnknownRecord, key: string, message: string): string => {
  const value = text(source, key, message)
  if (Number.isNaN(Date.parse(value))) throw new RealApiError('API_INVALID_RESPONSE', message)
  return value
}

const mapTask = (value: unknown): ProfessionalReviewTask => {
  const source = record(value, '工作事项格式无法识别。')
  const displayName = source.class_display_name
  if (displayName !== null && (typeof displayName !== 'string' || !displayName.trim())) {
    throw new RealApiError('API_INVALID_RESPONSE', '工作事项格式无法识别。')
  }
  return {
    task_ref: text(source, 'task_ref', '工作事项格式无法识别。'),
    class_ref: text(source, 'class_ref', '工作事项格式无法识别。'),
    class_display_name: displayName as string | null,
    published_at: timestamp(source, 'published_at', '工作事项时间格式无法识别。'),
  }
}

const mapEnrollment = (value: unknown): EligibleEnrollment => {
  const source = record(value, '完成记录格式无法识别。')
  const caseRef = source.case_ref
  if (caseRef !== null && (typeof caseRef !== 'string' || !caseRef.trim())) {
    throw new RealApiError('API_INVALID_RESPONSE', '完成记录格式无法识别。')
  }
  return {
    enrollment_ref: text(source, 'enrollment_ref', '完成记录格式无法识别。'),
    assessment_ref: text(source, 'assessment_ref', '完成记录格式无法识别。'),
    completed_at: timestamp(source, 'completed_at', '完成记录时间格式无法识别。'),
    case_ref: caseRef as string | null,
  }
}

const mapCase = (value: unknown): ProfessionalReviewCase => {
  const source = record(value, '复核记录格式无法识别。')
  const status = source.status
  const decision = source.decision
  const publicationStatus = source.publication_status
  const version = source.version
  const note = source.review_note
  if (!['OPEN', 'IN_REVIEW', 'APPROVED', 'REJECTED'].includes(String(status))
    || (decision !== null && decision !== 'APPROVED' && decision !== 'REJECTED')
    || publicationStatus !== 'NOT_PUBLISHED'
    || !Number.isInteger(version) || (version as number) < 1
    || (note !== null && typeof note !== 'string')) {
    throw new RealApiError('API_INVALID_RESPONSE', '复核记录格式无法识别。')
  }
  return {
    case_ref: text(source, 'case_ref', '复核记录格式无法识别。'),
    task_ref: text(source, 'task_ref', '复核记录格式无法识别。'),
    enrollment_ref: text(source, 'enrollment_ref', '复核记录格式无法识别。'),
    assessment_ref: text(source, 'assessment_ref', '复核记录格式无法识别。'),
    status: status as ProfessionalReviewCase['status'],
    publication_status: 'NOT_PUBLISHED',
    version: version as number,
    created_at: timestamp(source, 'created_at', '复核记录时间格式无法识别。'),
    updated_at: timestamp(source, 'updated_at', '复核记录时间格式无法识别。'),
    decision: decision as ProfessionalReviewCase['decision'],
    review_note: note as string | null,
  }
}

const mapPage = <T>(value: unknown, mapper: (item: unknown) => T, message: string): PagedResult<T> => {
  const source = record(value, message)
  if (!Array.isArray(source.items) || !Number.isInteger(source.total) || (source.total as number) < 0) {
    throw new RealApiError('API_INVALID_RESPONSE', message)
  }
  return { items: source.items.map(mapper), total: source.total as number }
}

const unwrap = async <T>(request: ReviewRequest): Promise<T> => (await requestProfessionalReview<T>(request)).data

const pageArgs = (offset: number, limit: number) => {
  if (!Number.isInteger(offset) || offset < 0 || offset > 100000
    || !Number.isInteger(limit) || limit < 1 || limit > 50) {
    throw new RealApiError('VALIDATION_FAILED', '分页参数无效。')
  }
  return { offset, limit }
}

const taskPath = (taskRef: string) => `/api/v1/school/professional-reviews/tasks/${encodeURIComponent(taskRef)}`
const casePath = (taskRef: string, caseRef: string) => `${taskPath(taskRef)}/cases/${encodeURIComponent(caseRef)}`

export class ProfessionalReviewsService {
  async listTasks(): Promise<ProfessionalReviewTask[]> {
    const value = await unwrap<unknown>({ method: 'GET', path: '/api/v1/school/professional-reviews/tasks' })
    if (!Array.isArray(value)) throw new RealApiError('API_INVALID_RESPONSE', '工作事项格式无法识别。')
    return value.map(mapTask)
  }

  async listEligibleEnrollments(taskRef: string, offset = 0, limit = 20): Promise<PagedResult<EligibleEnrollment>> {
    const page = await unwrap<unknown>({
      method: 'GET', path: `${taskPath(taskRef)}/eligible-enrollments`, query: pageArgs(offset, limit),
    })
    return mapPage(page, mapEnrollment, '完成记录列表格式无法识别。')
  }

  async listCases(taskRef: string, offset = 0, limit = 20): Promise<PagedResult<ProfessionalReviewCase>> {
    const page = await unwrap<unknown>({ method: 'GET', path: `${taskPath(taskRef)}/cases`, query: pageArgs(offset, limit) })
    return mapPage(page, mapCase, '复核记录列表格式无法识别。')
  }

  async getCase(taskRef: string, caseRef: string): Promise<ProfessionalReviewCase> {
    return mapCase(await unwrap<unknown>({ method: 'GET', path: casePath(taskRef, caseRef) }))
  }

  async createCase(taskRef: string, enrollmentRef: string, idempotencyKey: string): Promise<ProfessionalReviewCase> {
    return mapCase(await unwrap<unknown>({
      method: 'POST', path: `${taskPath(taskRef)}/cases`, body: { enrollment_ref: enrollmentRef }, idempotencyKey,
    }))
  }

  async openCase(taskRef: string, caseRef: string, expectedVersion: number, idempotencyKey: string): Promise<ProfessionalReviewCase> {
    return mapCase(await unwrap<unknown>({
      method: 'POST', path: `${casePath(taskRef, caseRef)}/open`, body: { expected_version: expectedVersion }, idempotencyKey,
    }))
  }

  async decideCase(
    taskRef: string,
    caseRef: string,
    expectedVersion: number,
    decision: 'APPROVED' | 'REJECTED',
    note: string,
    idempotencyKey: string,
  ): Promise<ProfessionalReviewCase> {
    return mapCase(await unwrap<unknown>({
      method: 'POST', path: `${casePath(taskRef, caseRef)}/decision`,
      body: { expected_version: expectedVersion, decision, note }, idempotencyKey,
    }))
  }
}

export const professionalReviews = new ProfessionalReviewsService()

export const newProfessionalReviewIdempotencyKey = (): string => {
  if (typeof crypto === 'undefined' || typeof crypto.randomUUID !== 'function') {
    throw new RealApiError('SECURE_RANDOM_UNAVAILABLE', '当前浏览器无法安全建立请求标识。')
  }
  return `professional-review-${crypto.randomUUID()}`
}
