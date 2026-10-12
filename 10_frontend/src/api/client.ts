import type {
  ApiEnvelope,
  Assessment,
  Role,
  SchoolRoleContext,
} from '@/types/contracts'
import type {
  CatQuestion,
  ReviewCase,
  ReviewDetailViewModel,
  ReviewQueueViewModel,
  StudentHomeViewModel,
  StudentReportViewModel,
} from '@/types/view-models'

export interface LoginInput {
  account: string
  password: string
}

export interface AssessmentListParams {
  limit?: number
  skip?: number
  status?: Assessment['status']
}

/** Student-facing list metadata only; deliberately separate from frozen assessment.v1. */
export interface AssessmentListEntry {
  assessment_id: string
  status: Assessment['status']
  items_answered: number
  started_at: string | null
  completed_at: string | null
}

export interface LoginResult {
  userId: string
  role: Role
  authorizedRoles?: Role[]
  availableContexts?: SchoolRoleContext[]
  activeContext?: SchoolRoleContext | null
  subjectId: string | null
  displayName: string
  initials: string
}

export interface AssessmentState {
  assessment_id: string
  subject_id: string
  status: 'created' | 'in_progress' | 'completed'
  current_index: number
  answered_count: number
  can_complete: boolean
  max_items: number
  question: CatQuestion | null
}

export interface SupportResult {
  status: string
  safety_action: string
  normal_generation: boolean
  generation: Record<string, unknown>
  report_id: string
  content: Record<string, unknown> | null
  citations: Array<Record<string, unknown>>
  review_reference: string | null
  crisis_response: string | null
  trace_id: string
  synthetic_fixture_only: boolean
  integration_labels: Record<string, string>
}

export interface ReportSummary {
  report_id: string
  assessment_id: string
  status: string
  safety_action: string | null
  created_at: string
  citation_count: number
}

export interface ReviewSubmission {
  decision: 'approved' | 'rejected'
  note: string
}

export interface SchoolClass {
  class_ref: string
  status: string
  active_student_count: number
  active_teacher_count: number
}

export type SchoolMemberRole = 'student' | 'teacher'

export interface SchoolMember {
  user_id: string
  role: SchoolMemberRole
  subject_id: string | null
}

export interface SchoolTask {
  task_ref: string
  class_ref: string
  status: string
  opens_at: string
  due_at: string | null
  published_at: string
  published_enrollment_count: number
  active_enrollment_count: number
  revoked_enrollment_count: number
  instrument_id: string
  instrument_version: string
}

export interface StudentSchoolTask {
  task_ref: string
  class_ref: string
  status: string
  opens_at: string
  due_at: string | null
  assessment_id: string | null
  assessment_status: Assessment['status'] | null
}

export interface StudentSchoolTaskHistory {
  task_ref: string
  class_ref: string
  task_status: string
  enrollment_status: string
  assessment_status: Assessment['status'] | null
  started_at: string | null
  completed_at: string | null
}

export interface SchoolTaskStart {
  task_ref: string
  assessment_id: string
  subject_id: string
  status: Assessment['status']
  selected_item_id: string | null
  current_item: CatQuestion | null
  answered_count: number
  administered_count: number
  can_complete: boolean
  max_items: number | null
}

export interface TeacherTaskProgress {
  class_ref: string
  task_ref: string
  task_status: string
  opens_at: string
  due_at: string | null
  published_enrollment_count: number
  active_enrollment_count: number
  revoked_enrollment_count: number
  not_started_count: number
  created_count: number
  in_progress_count: number
  completed_count: number
  abandoned_count: number
  invalid_count: number
}

export interface SchoolTaskEnrollment {
  enrollment_ref: string
  status: string
}

export interface FrontendApi {
  login(input: LoginInput): Promise<ApiEnvelope<LoginResult>>
  switchActiveContext?(context: SchoolRoleContext): Promise<ApiEnvelope<LoginResult>>
  logout(): Promise<ApiEnvelope<{ logged_out: boolean }>>
  getCurrentUser(): Promise<ApiEnvelope<LoginResult | null>>
  getStudentHome(): Promise<ApiEnvelope<StudentHomeViewModel | null>>
  listAssessments(params?: AssessmentListParams): Promise<ApiEnvelope<Assessment[]>>
  listAssessmentEntries?(params?: AssessmentListParams): Promise<ApiEnvelope<AssessmentListEntry[]>>
  getAssessmentState(assessmentId: string): Promise<ApiEnvelope<AssessmentState>>
  getAssessmentResult(assessmentId: string): Promise<ApiEnvelope<Assessment>>
  listReports(assessmentId?: string): Promise<ApiEnvelope<{ items: ReportSummary[]; next_cursor: string | null }>>
  startAssessment(assessmentId?: string): Promise<ApiEnvelope<AssessmentState>>
  submitAssessmentResponse(assessmentId: string, itemId: string, response: string): Promise<ApiEnvelope<AssessmentState>>
  completeAssessment(assessmentId: string): Promise<ApiEnvelope<Assessment>>
  createSupport(assessmentId: string, message: string): Promise<ApiEnvelope<SupportResult>>
  getStudentReport(reportId: string): Promise<ApiEnvelope<StudentReportViewModel>>
  getTeacherOverview(): Promise<ApiEnvelope<unknown>>
  getTeacherStudent(subjectId: string): Promise<ApiEnvelope<unknown>>
  getReviewQueue(): Promise<ApiEnvelope<ReviewQueueViewModel>>
  getReviewDetail(reviewCaseId: string): Promise<ApiEnvelope<ReviewDetailViewModel>>
  submitReview(reportId: string, input: ReviewSubmission): Promise<ApiEnvelope<ReviewCase>>
  listSchoolClasses?(): Promise<ApiEnvelope<SchoolClass[]>>
  listSchoolMembers?(role: SchoolMemberRole): Promise<ApiEnvelope<SchoolMember[]>>
  createSchoolClass?(classRef: string): Promise<ApiEnvelope<SchoolClass>>
  assignSchoolStudent?(classRef: string, studentUserId: string): Promise<ApiEnvelope<unknown>>
  assignSchoolTeacher?(classRef: string, teacherUserId: string): Promise<ApiEnvelope<unknown>>
  listSchoolTasks?(classRef: string): Promise<ApiEnvelope<SchoolTask[]>>
  publishSchoolTask?(classRef: string, opensAt: string, dueAt: string | null): Promise<ApiEnvelope<SchoolTask>>
  listStudentSchoolTasks?(): Promise<ApiEnvelope<StudentSchoolTask[]>>
  listStudentSchoolTaskHistory?(): Promise<ApiEnvelope<StudentSchoolTaskHistory[]>>
  startStudentSchoolTask?(taskRef: string): Promise<ApiEnvelope<SchoolTaskStart>>
  listTeacherSchoolTaskProgress?(): Promise<ApiEnvelope<TeacherTaskProgress[]>>
  listSchoolTaskEnrollments?(taskRef: string): Promise<ApiEnvelope<SchoolTaskEnrollment[]>>
  revokeSchoolTaskEnrollment?(taskRef: string, enrollmentRef: string): Promise<ApiEnvelope<SchoolTaskEnrollment>>
}
