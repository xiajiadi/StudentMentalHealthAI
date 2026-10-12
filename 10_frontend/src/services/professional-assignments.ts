import { RealApiError, requestProfessionalReview } from '@/services/real-api'

type UnknownRecord = Record<string, unknown>
type ReviewRequest = Parameters<typeof requestProfessionalReview>[0]

export type ProfessionalReviewSpecialist = {
  user_id: string
  display_name: string | null
}

export type ProfessionalReviewAssignment = {
  assignment_ref: string
  task_ref: string
  specialist_user_id: string
  status: 'ACTIVE' | 'REVOKED'
  assigned_at: string
  revoked_at: string | null
}

const record = (value: unknown): UnknownRecord => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new RealApiError('API_INVALID_RESPONSE', '任务分配信息格式无法识别。')
  }
  return value as UnknownRecord
}

const text = (source: UnknownRecord, key: string): string => {
  const value = source[key]
  if (typeof value !== 'string' || !value.trim()) {
    throw new RealApiError('API_INVALID_RESPONSE', '任务分配信息格式无法识别。')
  }
  return value
}

const timestamp = (source: UnknownRecord, key: string): string => {
  const value = text(source, key)
  if (Number.isNaN(Date.parse(value))) {
    throw new RealApiError('API_INVALID_RESPONSE', '任务分配时间格式无法识别。')
  }
  return value
}

const mapSpecialist = (value: unknown): ProfessionalReviewSpecialist => {
  const source = record(value)
  const displayName = source.display_name
  if (displayName !== null && (typeof displayName !== 'string' || !displayName.trim())) {
    throw new RealApiError('API_INVALID_RESPONSE', '专员信息格式无法识别。')
  }
  return { user_id: text(source, 'user_id'), display_name: displayName as string | null }
}

const mapAssignment = (value: unknown): ProfessionalReviewAssignment => {
  const source = record(value)
  const status = source.status
  if (status !== 'ACTIVE' && status !== 'REVOKED') {
    throw new RealApiError('API_INVALID_RESPONSE', '任务分配状态无法识别。')
  }
  const revokedAt = source.revoked_at
  if (revokedAt !== null && (typeof revokedAt !== 'string' || Number.isNaN(Date.parse(revokedAt)))) {
    throw new RealApiError('API_INVALID_RESPONSE', '任务分配时间格式无法识别。')
  }
  return {
    assignment_ref: text(source, 'assignment_ref'),
    task_ref: text(source, 'task_ref'),
    specialist_user_id: text(source, 'specialist_user_id'),
    status,
    assigned_at: timestamp(source, 'assigned_at'),
    revoked_at: revokedAt as string | null,
  }
}

const unwrap = async <T>(request: ReviewRequest): Promise<T> => (await requestProfessionalReview<T>(request)).data
const taskPath = (taskRef: string) => `/api/v1/school/professional-reviews/tasks/${encodeURIComponent(taskRef)}`

export class ProfessionalAssignmentsService {
  async listSpecialists(): Promise<ProfessionalReviewSpecialist[]> {
    const value = await unwrap<unknown>({ method: 'GET', path: '/api/v1/school/professional-reviews/specialists' })
    if (!Array.isArray(value)) throw new RealApiError('API_INVALID_RESPONSE', '专员列表格式无法识别。')
    return value.map(mapSpecialist)
  }

  async listAssignments(): Promise<ProfessionalReviewAssignment[]> {
    const value = await unwrap<unknown>({ method: 'GET', path: '/api/v1/school/professional-reviews/assignments' })
    if (!Array.isArray(value)) throw new RealApiError('API_INVALID_RESPONSE', '任务分配列表格式无法识别。')
    return value.map(mapAssignment)
  }

  async assign(taskRef: string, specialistUserId: string, idempotencyKey: string): Promise<ProfessionalReviewAssignment> {
    return mapAssignment(await unwrap<unknown>({
      method: 'POST', path: `${taskPath(taskRef)}/assignments`,
      body: { specialist_user_id: specialistUserId }, idempotencyKey,
    }))
  }

  async revoke(taskRef: string, assignmentRef: string, idempotencyKey: string): Promise<ProfessionalReviewAssignment> {
    return mapAssignment(await unwrap<unknown>({
      method: 'POST', path: `${taskPath(taskRef)}/assignments/${encodeURIComponent(assignmentRef)}/revoke`,
      body: {}, idempotencyKey,
    }))
  }
}

export const professionalAssignments = new ProfessionalAssignmentsService()

export const newProfessionalAssignmentIdempotencyKey = (): string => {
  if (typeof crypto === 'undefined' || typeof crypto.randomUUID !== 'function') {
    throw new RealApiError('SECURE_RANDOM_UNAVAILABLE', '当前浏览器无法安全建立请求标识。')
  }
  return `professional-assignment-${crypto.randomUUID()}`
}
