import type {
  Assessment,
  Citation,
  GenerationResult,
  RiskLevel,
  Role,
  SchoolRoleContext,
} from './contracts'

export interface SessionUser {
  userId: string
  role: Role
  authorizedRoles?: Role[]
  availableContexts?: SchoolRoleContext[]
  activeContext?: SchoolRoleContext | null
  subjectId: string | null
  displayName: string
  initials: string
  disclosure: Role
}

export interface StudentHomeViewModel {
  fixtureLabel: string
  greeting: string
  stateTitle: string
  stateBody: string
  nextAction: {
    title: string
    body: string
    cta: string
  }
  recent: {
    label: string
    status: string
    date: string
    reportId: string
  }
  supportLinks: Array<{
    title: string
    body: string
    icon: 'book' | 'message' | 'compass'
  }>
}

export interface CatQuestion {
  item_id: string
  prompt: string
  options: Array<{ value: string; label: string }>
}

export interface CatSession {
  assessmentId: string
  subjectId: string
  currentIndex: number
  answeredCount: number
  canComplete: boolean
  maxItems: number
  state: 'loading' | 'ready' | 'submitting' | 'completed' | 'error'
  question: CatQuestion | null
  errorMessage: string | null
}

export interface StudentReportViewModel {
  fixtureLabel: string
  report: {
    reportId: string
    assessmentId: string
    generation: GenerationResult
    assessment: Assessment
  }
  meaning: {
    title: string
    body: string
    note: string
  }
  data: {
    title: string
    body: string
    dimensions: Array<{
      key: string
      label: string
      value: number
      helper: string
    }>
  }
  actions: Array<{
    number: string
    title: string
    body: string
  }>
  evidence: Citation[]
}

export interface TeacherOverviewViewModel {
  fixtureLabel: string
  summary: Array<{
    label: string
    value: string
    helper: string
    tone: 'blue' | 'teal' | 'amber'
  }>
  trend: Array<{ date: string; completed: number; supported: number }>
  attentionCases: Array<{
    caseId: string
    subjectId: string
    state: string
    updatedAt: string
    priority: 'normal' | 'high'
  }>
}

export type ReviewWorkflowStatus = 'PENDING' | 'IN_REVIEW' | 'APPROVED' | 'REJECTED'

export interface ReviewCase {
  review_case_id: string
  review_id: string | null
  case_id: string | null
  decision_id: string
  trace_id: string
  status: ReviewWorkflowStatus
  reason_codes: string[]
  priority: 'NORMAL' | 'HIGH' | 'CRITICAL'
  assigned_role: 'REVIEWER' | null
  disclosure_policy: 'SUMMARY' | 'REDACTED'
  subject_id: string
  report_id: string
  created_at: string
  updated_at: string
  generationStatus: 'safety_blocked' | 'needs_review'
  summary: string
  safeContext: string
}

export interface ReviewQueueViewModel {
  fixtureLabel: string
  cases: ReviewCase[]
}

export interface ReviewDetailViewModel {
  fixtureLabel: string
  case: ReviewCase
  timeline: Array<{
    label: string
    detail: string
    time: string
    tone: 'done' | 'current' | 'muted'
  }>
  evidence: Citation[]
  safeAssessment: {
    assessmentId: string
    completion: string
    dataBoundary: string
    dimensionNote: string
  }
  allowedActions: Array<'approved' | 'rejected'>
}

export const riskLabels: Record<RiskLevel, string> = {
  normal: '常规流程',
  attention: '需要支持',
  high: '需要人工确认',
  crisis: '安全流程',
}
