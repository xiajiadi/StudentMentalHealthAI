/* global AbortSignal */

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
  display_name?: string | null
}

export type SchoolMemberRole = 'student' | 'teacher'

export interface SchoolMember {
  user_id: string
  role: SchoolMemberRole
  subject_id: string | null
  display_name?: string | null
  account_status?: string
  provisioning_status?: string | null
}

export interface SchoolDirectory {
  school: { school_ref: string; display_name: string | null }
  classes: SchoolClass[]
  members: Array<{
    user_id: string
    display_name: string | null
    role: SchoolMemberRole
    account_status: string
    provisioning_status: string | null
  }>
}

export interface SchoolAccountImportRow {
  row_no: number
  login_name: string
  display_name: string
  role: SchoolMemberRole
}

export interface SchoolAccountPreview {
  valid: boolean
  row_count: number
  errors: Array<{ row_no: number; code: string }>
}

export interface SchoolProvisionedAccount {
  row_no: number
  user_id: string
  display_name: string
  role: SchoolMemberRole
  status: 'PENDING_ACTIVATION' | 'ACTIVE'
}

export interface SchoolAccountBatch {
  batch_ref: string
  created_count: number
  accounts: SchoolProvisionedAccount[]
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
  activation_ref: string | null
  plan_name: string | null
  plan_version_number: number | null
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

/** Content-free discovery metadata for one assigned research-only CAT task. */
export interface ResearchTaskDiscoveryEntry {
  task_ref: string
  class_ref: string
  profile_ref: string
  source_population_scope: string
  instrument_id: string
  instrument_version: string
  publication_status: 'not_approved_for_publication_or_operational_use'
  research_only: true
  opens_at: string
  due_at: string | null
  status: 'PUBLISHED'
  completion_count: number
  session_ref: string | null
  session_status: 'IN_PROGRESS' | 'COMPLETED' | 'FAILED' | 'ABANDONED' | null
  items_answered: number
}

export interface ResearchSessionDiscoveryEntry {
  session_ref: string
  task_ref: string
  status: 'IN_PROGRESS' | 'COMPLETED' | 'FAILED' | 'ABANDONED'
  items_answered: number
  completed_at: string | null
  research_only: true
}

export interface ResearchDiscoveryPage<T> {
  items: T[]
  total: number
  limit: number
  offset: number
  has_more: boolean
  next_offset: number | null
}

export interface ResearchResponseOption {
  value: number
  label: string | null
}

export interface ResearchQuestion {
  item_id: string
  stem: string
  step: number
  response_options: ResearchResponseOption[]
}

export interface ResearchCompletion {
  status: 'COMPLETED'
  items_answered: number
  stop_reason: 'se_threshold_reached' | 'max_items_reached' | 'item_bank_exhausted' | 'item_bank_exhausted_before_minimum'
}

/** L1-only CAT projection. It deliberately has no score, estimate, or answer history. */
export interface ResearchL1Session {
  session_ref: string
  status: 'IN_PROGRESS' | 'COMPLETED' | 'FAILED' | 'ABANDONED'
  state_version: number
  items_answered: number
  research_only: true
  resume_required: boolean
  stop_reason: ResearchCompletion['stop_reason'] | null
  question: ResearchQuestion | null
  completion: ResearchCompletion | null
}

export interface ResearchAnswerInput {
  item_id: string
  raw_value: number
  expected_state_version: number
}

/** Server-owned candidate metadata only; no profile bytes or trust hashes. */
export interface ResearchProfileCandidate {
  profile_ref: string
  version_number: number | null
  source_population_scope: string | null
  instrument_id: string
  research_only: true
  publication_status: 'not_approved_for_publication_or_operational_use'
  rights_status: string
  execution_status: string
  created_at: string | null
  catalog_state: 'REGISTRY_CANDIDATE' | 'IMPORTED_CANDIDATE' | 'EXISTING_CANDIDATE' | 'IDEMPOTENT_REPLAY'
}

export interface ResearchSourceReview {
  package_status: 'ENGINEERING_REVIEWED_RESEARCH_ONLY'
  reviewer_kind: 'AI_ENGINEERING'
  review_status: 'pending'
  professional_approval: false
  ethics_approval: false
  clinical_approval: false
  psychometric_approval: false
  publication_eligible: false
  production_use: false
}

export interface ResearchSourceSummary {
  source_ref: string
  title: string
  organization: string
  publication_date: string
  canonical_url: string
  source_population_scope: string
  source_language: 'English'
  layers: Array<'policy' | 'theory' | 'intervention'>
  rights_status: 'VERIFIED_WITH_CONDITIONS' | 'PENDING'
  retrieval_eligible: boolean
}

export interface ResearchSourceDetail extends ResearchSourceSummary {
  license: string
  license_url: string
  attribution: string
  rights_evidence_url: string
  rights_evidence_sha256: string
  rights_scope_note: string
  source_capture_sha256: string | null
  review: ResearchSourceReview
}

export interface ResearchSourceCatalogPage {
  schema_version: 'school.research-source-catalog.v1'
  source_package_ref: string
  manifest_sha256: string
  study_ref: string
  consumer_age_min: 14
  consumer_age_max: 17
  review: ResearchSourceReview
  items: ResearchSourceSummary[]
  total: number
  limit: number
  offset: number
  has_more: boolean
}

/** Persisted version metadata only; actual use must be rechecked by the server. */
export interface ResearchProfileVersion {
  profile_ref: string
  version_number: number
  source_population_scope: string
  instrument_id: string
  research_only: true
  publication_status: 'not_approved_for_publication_or_operational_use'
  rights_status: 'PENDING' | 'VERIFIED' | 'REVOKED'
  execution_status: 'CANDIDATE_RESEARCH_ONLY' | 'SIMULATION_ENABLED' | 'DISABLED'
  created_at: string
  use_eligibility: 'RECHECK_REQUIRED'
}

export interface ResearchProfileVersionPage {
  items: ResearchProfileVersion[]
  total: number
  limit: number
  offset: number
  has_more: boolean
  next_offset: number | null
}

/** Simulation-only eligibility receipt; it does not imply professional approval. */
export interface ResearchProfileSimulationReceipt {
  profile_ref: string
  version_number: number
  research_only: true
  human_curated: false
  publication_status: 'not_approved_for_publication_or_operational_use'
  rights_status: 'VERIFIED'
  execution_status: 'SIMULATION_ENABLED'
  simulation_only: true
  clinical_approval: false
  ethics_approval: false
  psychometric_approval: false
  study_ref: string
  policy_expires_at: string
  catalog_state: 'SIMULATION_ENABLED' | 'IDEMPOTENT_REPLAY'
}

/** Safe server selector for a currently eligible public-observed binding. */
export interface ResearchTaskBindingOption {
  binding_ref: string
  profile_ref: string
  profile_version_number: number
  source_population_scope: string
  instrument_id: string
  instrument_version: string
  research_only: true
  publication_status: 'not_approved_for_publication_or_operational_use'
}

export interface ResearchTaskPublishInput {
  class_ref: string
  task_ref: string
  binding_ref: string
  profile_version_number: number
  opens_at: string
  due_at: string
}

export interface ResearchTaskPublicationReceipt extends ResearchTaskPublishInput {
  profile_ref: string
  source_population_scope: string
  instrument_id: string
  instrument_version: string
  status: 'PUBLISHED'
  published_at: string
  published_enrollment_count: number
  response_origin: 'PUBLIC_OBSERVED'
  research_only: true
  publication_status: 'not_approved_for_publication_or_operational_use'
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
  listSchoolClasses?(params?: { signal?: AbortSignal }): Promise<ApiEnvelope<SchoolClass[]>>
  listSchoolMembers?(role: SchoolMemberRole): Promise<ApiEnvelope<SchoolMember[]>>
  getSchoolAdminDirectory?(): Promise<ApiEnvelope<SchoolDirectory>>
  updateSchoolDisplayName?(displayName: string): Promise<ApiEnvelope<unknown>>
  updateSchoolClassDisplayName?(classRef: string, displayName: string): Promise<ApiEnvelope<unknown>>
  updateSchoolMemberDisplayName?(userId: string, displayName: string): Promise<ApiEnvelope<unknown>>
  previewSchoolAccountImport?(classRef: string | null, rows: SchoolAccountImportRow[]): Promise<ApiEnvelope<SchoolAccountPreview>>
  importSchoolAccounts?(classRef: string | null, rows: SchoolAccountImportRow[], idempotencyKey: string): Promise<ApiEnvelope<SchoolAccountBatch>>
  getSchoolAccountBatch?(batchRef: string): Promise<ApiEnvelope<SchoolAccountBatch>>
  activateSchoolAccount?(userId: string, newPassword: string): Promise<ApiEnvelope<unknown>>
  createSchoolClass?(classRef: string): Promise<ApiEnvelope<SchoolClass>>
  assignSchoolStudent?(classRef: string, studentUserId: string): Promise<ApiEnvelope<unknown>>
  assignSchoolTeacher?(classRef: string, teacherUserId: string): Promise<ApiEnvelope<unknown>>
  listSchoolTasks?(classRef: string): Promise<ApiEnvelope<SchoolTask[]>>
  publishSchoolTask?(classRef: string, opensAt: string, dueAt: string | null, activationRef?: string | null): Promise<ApiEnvelope<SchoolTask>>
  listStudentSchoolTasks?(): Promise<ApiEnvelope<StudentSchoolTask[]>>
  listStudentSchoolTaskHistory?(): Promise<ApiEnvelope<StudentSchoolTaskHistory[]>>
  startStudentSchoolTask?(taskRef: string): Promise<ApiEnvelope<SchoolTaskStart>>
  listStudentResearchTasks?(params?: { limit?: number; offset?: number; signal?: AbortSignal }): Promise<ApiEnvelope<ResearchDiscoveryPage<ResearchTaskDiscoveryEntry>>>
  listStudentResearchSessions?(params?: { limit?: number; offset?: number; signal?: AbortSignal }): Promise<ApiEnvelope<ResearchDiscoveryPage<ResearchSessionDiscoveryEntry>>>
  startStudentResearchTask?(taskRef: string, idempotencyKey: string): Promise<ApiEnvelope<ResearchL1Session>>
  resumeStudentResearchSession?(sessionRef: string): Promise<ApiEnvelope<ResearchL1Session>>
  answerStudentResearchSession?(sessionRef: string, input: ResearchAnswerInput, idempotencyKey: string): Promise<ApiEnvelope<ResearchL1Session>>
  listResearchProfileCatalog?(params?: { signal?: AbortSignal }): Promise<ApiEnvelope<ResearchProfileCandidate[]>>
  listResearchSourceCatalog?(params?: { limit?: number; offset?: number; signal?: AbortSignal }): Promise<ApiEnvelope<ResearchSourceCatalogPage>>
  getResearchSource?(sourceRef: string, params?: { signal?: AbortSignal }): Promise<ApiEnvelope<ResearchSourceDetail>>
  listResearchProfileVersions?(profileRef: string, params?: { limit?: number; offset?: number; signal?: AbortSignal }): Promise<ApiEnvelope<ResearchProfileVersionPage>>
  importResearchProfile?(profileRef: string, versionNumber: number, idempotencyKey: string): Promise<ApiEnvelope<ResearchProfileCandidate>>
  enableResearchProfileSimulation?(profileRef: string, versionNumber: number, idempotencyKey: string): Promise<ApiEnvelope<ResearchProfileSimulationReceipt>>
  listResearchTaskCatalog?(params?: { signal?: AbortSignal }): Promise<ApiEnvelope<ResearchTaskBindingOption[]>>
  publishResearchTask?(input: ResearchTaskPublishInput, idempotencyKey: string): Promise<ApiEnvelope<ResearchTaskPublicationReceipt>>
  listTeacherSchoolTaskProgress?(): Promise<ApiEnvelope<TeacherTaskProgress[]>>
  listSchoolTaskEnrollments?(taskRef: string): Promise<ApiEnvelope<SchoolTaskEnrollment[]>>
  revokeSchoolTaskEnrollment?(taskRef: string, enrollmentRef: string): Promise<ApiEnvelope<SchoolTaskEnrollment>>
}
