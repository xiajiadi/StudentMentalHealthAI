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

export interface FrontendApi {
  login(input: LoginInput): Promise<ApiEnvelope<LoginResult>>
  switchActiveContext?(context: SchoolRoleContext): Promise<ApiEnvelope<LoginResult>>
  logout(): Promise<ApiEnvelope<{ logged_out: boolean }>>
  getCurrentUser(): Promise<ApiEnvelope<LoginResult | null>>
  getStudentHome(): Promise<ApiEnvelope<StudentHomeViewModel | null>>
  listAssessments(params?: AssessmentListParams): Promise<ApiEnvelope<Assessment[]>>
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
}
