/* global AbortSignal, DOMException */

import type { SchoolClass } from '@/api/client'
import { realApiProvider, requestProfessionalReview } from '@/services/real-api'

type UnknownRecord = Record<string, unknown>
type SafetyRequest = {
  method: 'GET' | 'POST' | 'PUT'
  path: string
  query?: Record<string, string | number>
  body?: Record<string, unknown>
  idempotencyKey?: string
  signal?: AbortSignal
}

export type SafetyCaseStatus =
  | 'UNASSIGNED_PENDING' | 'ASSIGNED' | 'IN_REVIEW' | 'REVIEWED'
  | 'ESCALATION_NEEDED' | 'CLOSED' | 'REVOKED'
export type SafetyTransitionStatus = 'IN_REVIEW' | 'REVIEWED' | 'ESCALATION_NEEDED' | 'CLOSED'
export type SafetyDecisionCode = 'UNRESOLVED_NEEDS_CONTEXT'

export type UnassignedSafetyCase = {
  case_ref: string
  status: 'UNASSIGNED_PENDING'
  state_version: number
  class_ref: string | null
  created_at: string
  updated_at: string
}

export type AssignedSafetyCase = {
  case_ref: string
  class_ref: string
  action: 'REVIEW_REQUIRED' | 'CRISIS_ROUTE'
  reason_codes: string[]
  status: Exclude<SafetyCaseStatus, 'UNASSIGNED_PENDING' | 'REVOKED'>
  state_version: number
  decision_code: SafetyDecisionCode | null
  created_at: string
  updated_at: string
  assigned_at: string
  reviewed_at: string | null
  closed_at: string | null
  review_note?: string | null
}

export type SafetySpecialist = { user_id: string; display_name: string | null }
export type SafetyClass = Pick<SchoolClass, 'class_ref' | 'display_name' | 'status'>
export type SafetyPage<T> = { items: T[]; total: number }
export type SafetyAssignmentReceipt = {
  case_ref: string
  status: 'ASSIGNED'
  state_version: number
  class_ref: string
  assigned_at: string
  updated_at: string
}

export class SchoolConversationSafetyError extends Error {
  constructor(
    public readonly code: string,
    public readonly retryable = false,
  ) {
    super('安全复核请求暂未完成。')
    this.name = 'SchoolConversationSafetyError'
  }
}

const basePath = '/api/v1/school/conversation-safety'
const apiBaseUrl = new window.URL(import.meta.env.VITE_API_BASE_URL || '/', window.location.origin).toString()
const safeRef = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/
const reasonCode = /^[A-Z][A-Z0-9_]{0,63}$/

const invalid = () => new SchoolConversationSafetyError('API_INVALID_RESPONSE')
const asRecord = (value: unknown): UnknownRecord => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalid()
  return value as UnknownRecord
}
const exactFields = (value: UnknownRecord, expected: readonly string[]) => {
  if (Object.keys(value).sort().join('|') !== [...expected].sort().join('|')) throw invalid()
}
const text = (value: unknown, max = 128): string => {
  if (typeof value !== 'string' || !value.trim() || value.length > max) throw invalid()
  return value
}
const ref = (value: unknown): string => {
  const result = text(value)
  if (!safeRef.test(result)) throw invalid()
  return result
}
const timestamp = (value: unknown, nullable = false): string | null => {
  if (nullable && value === null) return null
  const result = text(value, 64)
  if (!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(result) || Number.isNaN(Date.parse(result))) throw invalid()
  return result
}
const version = (value: unknown): number => {
  if (!Number.isSafeInteger(value) || (value as number) < 1 || (value as number) > 2147483647) throw invalid()
  return value as number
}

const mapUnassigned = (value: unknown): UnassignedSafetyCase => {
  const row = asRecord(value)
  exactFields(row, ['case_ref', 'status', 'state_version', 'class_ref', 'created_at', 'updated_at'])
  if (row.status !== 'UNASSIGNED_PENDING') throw invalid()
  const classRef = row.class_ref === null ? null : ref(row.class_ref)
  return {
    case_ref: ref(row.case_ref), status: 'UNASSIGNED_PENDING', state_version: version(row.state_version),
    class_ref: classRef, created_at: timestamp(row.created_at)!, updated_at: timestamp(row.updated_at)!,
  }
}

const mapAssigned = (value: unknown, withNote: boolean): AssignedSafetyCase => {
  const row = asRecord(value)
  const fields = ['case_ref', 'class_ref', 'action', 'reason_codes', 'status', 'state_version', 'decision_code', 'created_at', 'updated_at', 'assigned_at', 'reviewed_at', 'closed_at']
  exactFields(row, withNote ? [...fields, 'review_note'] : fields)
  const statuses: AssignedSafetyCase['status'][] = ['ASSIGNED', 'IN_REVIEW', 'REVIEWED', 'ESCALATION_NEEDED', 'CLOSED']
  if (!statuses.includes(row.status as AssignedSafetyCase['status'])
    || !['REVIEW_REQUIRED', 'CRISIS_ROUTE'].includes(String(row.action))
    || (row.decision_code !== null && row.decision_code !== 'UNRESOLVED_NEEDS_CONTEXT')) throw invalid()
  if (!Array.isArray(row.reason_codes) || row.reason_codes.length < 1 || row.reason_codes.length > 16
    || row.reason_codes.some((code) => typeof code !== 'string' || !reasonCode.test(code))
    || new Set(row.reason_codes).size !== row.reason_codes.length) throw invalid()
  const note = row.review_note
  if (withNote && note !== null && (typeof note !== 'string' || note.length > 4000)) throw invalid()
  const reviewedAt = timestamp(row.reviewed_at, true)
  const closedAt = timestamp(row.closed_at, true)
  if (row.status === 'IN_REVIEW' && row.decision_code !== null) throw invalid()
  if (['REVIEWED', 'ESCALATION_NEEDED', 'CLOSED'].includes(String(row.status))
    && row.decision_code !== 'UNRESOLVED_NEEDS_CONTEXT') throw invalid()
  return {
    case_ref: ref(row.case_ref), class_ref: ref(row.class_ref),
    action: row.action as AssignedSafetyCase['action'], reason_codes: [...row.reason_codes] as string[],
    status: row.status as AssignedSafetyCase['status'], state_version: version(row.state_version),
    decision_code: row.decision_code as SafetyDecisionCode | null,
    created_at: timestamp(row.created_at)!, updated_at: timestamp(row.updated_at)!,
    assigned_at: timestamp(row.assigned_at)!, reviewed_at: reviewedAt, closed_at: closedAt,
    ...(withNote ? { review_note: note as string | null } : {}),
  }
}

const mapPage = <T>(value: unknown, mapper: (item: unknown) => T, limit: number): SafetyPage<T> => {
  const page = asRecord(value)
  exactFields(page, ['items', 'total'])
  if (!Array.isArray(page.items) || !Number.isSafeInteger(page.total) || (page.total as number) < 0
    || page.items.length > limit || page.items.length > (page.total as number)) throw invalid()
  const items = page.items.map(mapper)
  const ids = items.map((item) => (item as { case_ref: string }).case_ref)
  if (new Set(ids).size !== ids.length) throw invalid()
  return { items, total: page.total as number }
}

const unwrapEnvelope = (value: unknown): unknown => {
  const envelope = asRecord(value)
  if ('error' in envelope) {
    const problem = asRecord(envelope.error)
    throw new SchoolConversationSafetyError(
      typeof problem.code === 'string' ? problem.code.toUpperCase() : 'API_ERROR',
      problem.retryable === true,
    )
  }
  exactFields(envelope, ['request_id', 'trace_id', 'data'])
  if (typeof envelope.request_id !== 'string' || !envelope.request_id
    || typeof envelope.trace_id !== 'string' || !envelope.trace_id) throw invalid()
  return envelope.data
}

const endpoint = (path: string) => new window.URL(path, apiBaseUrl).toString()

async function getCsrfToken(signal?: AbortSignal): Promise<string> {
  let response: Response
  try {
    response = await fetch(endpoint('/api/v1/auth/csrf'), {
      method: 'GET', credentials: 'include', headers: { Accept: 'application/json' }, signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new SchoolConversationSafetyError('NETWORK_UNAVAILABLE', true)
  }
  let raw: unknown
  try { raw = await response.json() } catch { throw invalid() }
  if (!response.ok) unwrapEnvelope(raw)
  const data = asRecord(unwrapEnvelope(raw))
  exactFields(data, ['csrf_token'])
  return text(data.csrf_token, 512)
}

async function request(input: SafetyRequest): Promise<unknown> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (input.method !== 'GET') {
    if (!input.idempotencyKey?.trim() || input.idempotencyKey.length > 128) {
      throw new SchoolConversationSafetyError('API_INVALID_REQUEST')
    }
    headers['Content-Type'] = 'application/json'
    headers['X-CSRF-Token'] = await getCsrfToken(input.signal)
    headers['Idempotency-Key'] = input.idempotencyKey
  }
  const url = new window.URL(input.path, apiBaseUrl)
  for (const [key, value] of Object.entries(input.query ?? {})) url.searchParams.set(key, String(value))
  let response: Response
  try {
    response = await fetch(url.toString(), {
      method: input.method, credentials: 'include', headers,
      ...(input.body ? { body: JSON.stringify(input.body) } : {}), signal: input.signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new SchoolConversationSafetyError('NETWORK_UNAVAILABLE', true)
  }
  let raw: unknown
  try { raw = await response.json() } catch { throw invalid() }
  if (!response.ok) unwrapEnvelope(raw)
  return unwrapEnvelope(raw)
}

const pageArgs = (offset: number, limit: number) => {
  if (!Number.isSafeInteger(offset) || offset < 0 || offset > 100000
    || !Number.isSafeInteger(limit) || limit < 1 || limit > 50) {
    throw new SchoolConversationSafetyError('VALIDATION_FAILED')
  }
  return { offset, limit }
}
const requireRef = (value: string) => {
  if (!safeRef.test(value)) throw new SchoolConversationSafetyError('API_INVALID_REQUEST')
}
const key = (value: string) => {
  if (!value.trim() || value.length > 128) throw new SchoolConversationSafetyError('API_INVALID_REQUEST')
}

const mapSpecialist = (value: unknown): SafetySpecialist => {
  const row = asRecord(value)
  exactFields(row, ['user_id', 'display_name'])
  const name = row.display_name
  if (name !== null && (typeof name !== 'string' || !name.trim() || name.length > 120)) throw invalid()
  return { user_id: ref(row.user_id), display_name: name as string | null }
}

export class SchoolConversationSafetyService {
  async listUnassigned(offset = 0, limit = 20, signal?: AbortSignal): Promise<SafetyPage<UnassignedSafetyCase>> {
    const data = await request({ method: 'GET', path: `${basePath}/unassigned`, query: pageArgs(offset, limit), signal })
    return mapPage(data, mapUnassigned, limit)
  }

  async listAssigned(offset = 0, limit = 20, signal?: AbortSignal): Promise<SafetyPage<AssignedSafetyCase>> {
    const data = await request({ method: 'GET', path: `${basePath}/assigned`, query: pageArgs(offset, limit), signal })
    return mapPage(data, (item) => mapAssigned(item, false), limit)
  }

  async getAssignedCase(caseRef: string, signal?: AbortSignal): Promise<AssignedSafetyCase> {
    requireRef(caseRef)
    return mapAssigned(await request({ method: 'GET', path: `${basePath}/${encodeURIComponent(caseRef)}`, signal }), true)
  }

  async assign(
    row: UnassignedSafetyCase,
    classRef: string,
    specialistUserId: string,
    idempotencyKey: string,
  ): Promise<SafetyAssignmentReceipt> {
    requireRef(row.case_ref); requireRef(classRef); requireRef(specialistUserId); key(idempotencyKey)
    const value = asRecord(await request({
      method: 'POST', path: `${basePath}/${encodeURIComponent(row.case_ref)}/assignment`,
      body: { expected_version: row.state_version, class_ref: classRef, specialist_user_id: specialistUserId },
      idempotencyKey,
    }))
    exactFields(value, ['case_ref', 'status', 'state_version', 'class_ref', 'assigned_at', 'updated_at'])
    if (value.status !== 'ASSIGNED' || ref(value.case_ref) !== row.case_ref || ref(value.class_ref) !== classRef
      || version(value.state_version) !== row.state_version + 1) throw invalid()
    return {
      case_ref: row.case_ref, status: 'ASSIGNED', state_version: value.state_version as number,
      class_ref: classRef, assigned_at: timestamp(value.assigned_at)!, updated_at: timestamp(value.updated_at)!,
    }
  }

  async saveNote(caseRef: string, expectedVersion: number, note: string, idempotencyKey: string): Promise<AssignedSafetyCase> {
    requireRef(caseRef); key(idempotencyKey)
    if (!Number.isSafeInteger(expectedVersion) || expectedVersion < 1 || note.trim().length === 0 || note.length > 4000) {
      throw new SchoolConversationSafetyError('VALIDATION_FAILED')
    }
    const updated = mapAssigned(await request({
      method: 'PUT', path: `${basePath}/${encodeURIComponent(caseRef)}/note`,
      body: { expected_version: expectedVersion, note }, idempotencyKey,
    }), true)
    if (updated.case_ref !== caseRef || updated.state_version !== expectedVersion + 1 || updated.status !== 'IN_REVIEW') throw invalid()
    return updated
  }

  async transition(
    caseRef: string,
    expectedVersion: number,
    status: SafetyTransitionStatus,
    idempotencyKey: string,
  ): Promise<AssignedSafetyCase> {
    requireRef(caseRef); key(idempotencyKey)
    if (!Number.isSafeInteger(expectedVersion) || expectedVersion < 1) throw new SchoolConversationSafetyError('VALIDATION_FAILED')
    const body = {
      expected_version: expectedVersion,
      status,
      decision_code: status === 'IN_REVIEW' ? null : 'UNRESOLVED_NEEDS_CONTEXT',
    }
    const updated = mapAssigned(await request({
      method: 'POST', path: `${basePath}/${encodeURIComponent(caseRef)}/transition`, body, idempotencyKey,
    }), true)
    const expectedDecision = status === 'IN_REVIEW' ? null : 'UNRESOLVED_NEEDS_CONTEXT'
    if (updated.case_ref !== caseRef || updated.state_version !== expectedVersion + 1
      || updated.status !== status || updated.decision_code !== expectedDecision) throw invalid()
    return updated
  }

  async listSpecialists(): Promise<SafetySpecialist[]> {
    const envelope = await requestProfessionalReview<unknown>({
      method: 'GET', path: '/api/v1/school/professional-reviews/specialists',
    })
    if (!Array.isArray(envelope.data)) throw invalid()
    const rows = envelope.data.map(mapSpecialist)
    if (new Set(rows.map((item) => item.user_id)).size !== rows.length) throw invalid()
    return rows
  }

  async listActiveClasses(signal?: AbortSignal): Promise<SafetyClass[]> {
    const envelope = await realApiProvider.listSchoolClasses({ signal })
    const rows = envelope.data
      .filter((row) => row.status === 'ACTIVE' || row.status === 'active')
      .map((row) => ({ class_ref: row.class_ref, display_name: row.display_name ?? null, status: row.status }))
    if (new Set(rows.map((item) => item.class_ref)).size !== rows.length) throw invalid()
    return rows
  }
}

export const schoolConversationSafety = new SchoolConversationSafetyService()

export const newConversationSafetyIdempotencyKey = (): string => {
  if (typeof crypto === 'undefined' || typeof crypto.randomUUID !== 'function') {
    throw new SchoolConversationSafetyError('SECURE_RANDOM_UNAVAILABLE')
  }
  return `conversation-safety-${crypto.randomUUID()}`
}

