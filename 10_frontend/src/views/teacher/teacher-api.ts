import { frontendApi as sharedFrontendApi } from '@/services/mock-api'

export interface TeacherStudentSummary {
  subject_id: string
  assessment_count: number
  completed_count: number
  in_progress_count: number
  last_activity_at: string | null
}

export interface TeacherOverview {
  subjects_count: number
  assessments_count: number
  completed_count: number
  in_progress_count: number
  reports_count: number
  report_status_counts: Record<string, number>
  review_status_counts: Record<string, number>
  students: TeacherStudentSummary[]
}

export interface TeacherAssessmentHistoryItem {
  assessment_id: string
  status: string
  items_answered: number | null
  started_at: string | null
  completed_at: string | null
}

export interface TeacherStudentHistory {
  subject_id: string
  assessment_count: number
  completed_count: number
  in_progress_count: number
  assessments: TeacherAssessmentHistoryItem[]
}

interface TeacherApi {
  getTeacherOverview(): Promise<{ data: TeacherOverview }>
  getTeacherStudent(subjectId: string): Promise<{ data: TeacherStudentHistory }>
}

type SharedTeacherApi = {
  getTeacherOverview(): Promise<{ data: unknown }>
  getTeacherStudent?: (subjectId: string) => Promise<{ data: unknown }>
}

// The shared client/provider wiring is owned by the Lead. This narrow adapter
// fails closed until its provider returns the source-backed response shape.
const sharedTeacherApi = sharedFrontendApi as unknown as SharedTeacherApi
export const teacherApi: TeacherApi = {
  async getTeacherOverview() {
    const response = await sharedTeacherApi.getTeacherOverview()
    if (!isTeacherOverview(response.data)) throw contractError()
    return { ...response, data: response.data }
  },
  async getTeacherStudent(subjectId) {
    if (!sharedTeacherApi.getTeacherStudent) throw contractError()
    const response = await sharedTeacherApi.getTeacherStudent(subjectId)
    if (!isTeacherStudentHistory(response.data)) throw contractError()
    return { ...response, data: response.data }
  },
}

export function isTeacherForbidden(error: unknown): boolean {
  return error !== null
    && typeof error === 'object'
    && 'code' in error
    && typeof error.code === 'string'
    && error.code.toLowerCase() === 'forbidden'
}

function contractError() {
  return Object.assign(new Error('教师数据响应不符合当前接口约定。'), { code: 'API_INVALID_RESPONSE' })
}

function isTeacherOverview(value: unknown): value is TeacherOverview {
  if (!isRecord(value)) return false
  return isNonNegativeInteger(value.subjects_count)
    && isNonNegativeInteger(value.assessments_count)
    && isNonNegativeInteger(value.completed_count)
    && isNonNegativeInteger(value.in_progress_count)
    && isNonNegativeInteger(value.reports_count)
    && isCountMap(value.report_status_counts)
    && isCountMap(value.review_status_counts)
    && Array.isArray(value.students)
    && value.students.every(isTeacherStudentSummary)
}

function isTeacherStudentHistory(value: unknown): value is TeacherStudentHistory {
  if (!isRecord(value)) return false
  return typeof value.subject_id === 'string'
    && isNonNegativeInteger(value.assessment_count)
    && isNonNegativeInteger(value.completed_count)
    && isNonNegativeInteger(value.in_progress_count)
    && Array.isArray(value.assessments)
    && value.assessments.every(isTeacherAssessmentHistoryItem)
}

function isTeacherStudentSummary(value: unknown): value is TeacherStudentSummary {
  if (!isRecord(value)) return false
  return typeof value.subject_id === 'string'
    && isNonNegativeInteger(value.assessment_count)
    && isNonNegativeInteger(value.completed_count)
    && isNonNegativeInteger(value.in_progress_count)
    && (typeof value.last_activity_at === 'string' || value.last_activity_at === null)
}

function isTeacherAssessmentHistoryItem(value: unknown): value is TeacherAssessmentHistoryItem {
  if (!isRecord(value)) return false
  return typeof value.assessment_id === 'string'
    && typeof value.status === 'string'
    && (isNonNegativeInteger(value.items_answered) || value.items_answered === null)
    && (typeof value.started_at === 'string' || value.started_at === null)
    && (typeof value.completed_at === 'string' || value.completed_at === null)
}

function isCountMap(value: unknown): value is Record<string, number> {
  return isRecord(value) && Object.values(value).every(isNonNegativeInteger)
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
