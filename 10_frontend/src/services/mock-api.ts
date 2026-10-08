import {
  catQuestions,
  reviewCaseFixture,
  reviewEvidence,
  studentHomeFixture,
  studentReportFixture,
  syntheticAssessment,
  SYNTHETIC_FIXTURE_LABEL,
} from '@/mocks/fixtures'
import type { ApiEnvelope, Assessment, Report } from '@/types/contracts'
import type {
  ReviewCase,
  ReviewDetailViewModel,
  ReviewQueueViewModel,
  StudentHomeViewModel,
  StudentReportViewModel,
} from '@/types/view-models'
import type {
  AssessmentState,
  FrontendApi,
  LoginInput,
  LoginResult,
  ReportSummary,
  ReviewSubmission,
  SupportResult,
} from '@/api/client'
import { RealApiProvider } from '@/services/real-api'

export class MockApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly retryable = false,
  ) {
    super(message)
    this.name = 'MockApiError'
  }
}

const clone = <T>(value: T): T => structuredClone(value)

const sleep = (duration = 280) => new Promise<void>((resolve) => window.setTimeout(resolve, duration))

const requestIds = (key: string): ApiEnvelope<unknown> => ({
  request_id: `REQ_demo_${key}`,
  trace_id: `TRACE_demo_${key}`,
  data: {},
})

const currentDemoState = () => {
  if (typeof window === 'undefined') return null
  return new URLSearchParams(window.location.search).get('state')
}

let assessmentIndex = 0
let answeredCount = 0
let mockAssessmentId = 'ASSESS_demo_session_001'
let reviewCaseState: ReviewCase = clone(reviewCaseFixture)

export class MockApiProvider implements FrontendApi {
  async login(input: LoginInput): Promise<ApiEnvelope<LoginResult>> {
    await sleep(480)

    if (!input.account.trim() || !input.password.trim()) {
      throw new MockApiError('AUTH_INVALID_INPUT', '请输入演示账号和密码。')
    }
    if (input.password.toLowerCase() === 'network') {
      throw new MockApiError('NETWORK_UNAVAILABLE', '当前无法连接到演示服务，请稍后重试。', true)
    }
    if (input.password.toLowerCase() === 'wrong') {
      throw new MockApiError('AUTH_UNAUTHORIZED', '账号或密码不正确，请检查后再试。')
    }

    const result: LoginResult = {
      userId: `USER_demo_${input.role}`,
      role: input.role,
      subjectId: input.role === 'student' ? 'SUBJ_demo_student_001' : null,
      displayName: input.role === 'student' ? '演示同学' : input.role === 'teacher' ? '演示教师' : '演示复核员',
      initials: input.role === 'student' ? '学' : input.role === 'teacher' ? '师' : '复',
    }
    return { ...requestIds(`login_${input.role}`), data: result } as ApiEnvelope<LoginResult>
  }

  async logout(): Promise<ApiEnvelope<{ logged_out: boolean }>> {
    await sleep(80)
    return { ...requestIds('logout'), data: { logged_out: true } } as ApiEnvelope<{ logged_out: boolean }>
  }

  async getCurrentUser(): Promise<ApiEnvelope<LoginResult | null>> {
    await sleep(80)
    return { ...requestIds('current_user'), data: null } as ApiEnvelope<LoginResult | null>
  }

  async getStudentHome(): Promise<ApiEnvelope<StudentHomeViewModel | null>> {
    await sleep()
    const state = currentDemoState()
    if (state === 'error') throw new MockApiError('INTERNAL_ERROR', '演示服务暂时不可用，请重试。', true)
    return {
      ...requestIds('student_home'),
      data: state === 'empty' ? null : clone(studentHomeFixture),
    } as ApiEnvelope<StudentHomeViewModel | null>
  }

  async listAssessments(): Promise<ApiEnvelope<Assessment[]>> {
    await sleep()
    const rows = answeredCount > 0
      ? [{ ...clone(syntheticAssessment), assessment_id: mockAssessmentId, status: assessmentIndex >= 3 ? 'completed' as const : 'in_progress' as const }]
      : []
    return { ...requestIds('assessment_list'), data: rows } as ApiEnvelope<Assessment[]>
  }

  async getAssessmentState(assessmentId: string): Promise<ApiEnvelope<AssessmentState>> {
    await sleep()
    if (assessmentId !== mockAssessmentId) throw new MockApiError('ASSESSMENT_NOT_FOUND', '没有找到这次测评。')
    const question = catQuestions[assessmentIndex] ? clone(catQuestions[assessmentIndex]) : null
    return { ...requestIds('assessment_state'), data: {
      assessment_id: mockAssessmentId,
      subject_id: 'SUBJ_demo_student_001',
      status: 'in_progress',
      current_index: assessmentIndex,
      answered_count: answeredCount,
      can_complete: answeredCount >= 3,
      max_items: 8,
      question,
    } } as ApiEnvelope<AssessmentState>
  }

  async getAssessmentResult(assessmentId: string): Promise<ApiEnvelope<Assessment>> {
    await sleep()
    if (assessmentId !== mockAssessmentId || answeredCount < 3) throw new MockApiError('ASSESSMENT_NOT_FOUND', '没有找到已完成的测评结果。')
    return { ...requestIds('assessment_result'), data: clone({ ...syntheticAssessment, assessment_id: assessmentId }) } as ApiEnvelope<Assessment>
  }

  async listReports(assessmentId?: string): Promise<ApiEnvelope<{ items: ReportSummary[]; next_cursor: string | null }>> {
    await sleep()
    const items = answeredCount >= 3 && (!assessmentId || assessmentId === mockAssessmentId)
      ? [{ report_id: studentReportFixture.report.reportId, assessment_id: mockAssessmentId, status: 'generated', safety_action: 'PROCEED_WITH_BOUNDARY', created_at: syntheticAssessment.timestamps.completed_at || '', citation_count: studentReportFixture.evidence.length }]
      : []
    return { ...requestIds('report_list'), data: { items, next_cursor: null } } as ApiEnvelope<{ items: ReportSummary[]; next_cursor: null }>
  }

  async startAssessment(assessmentId?: string): Promise<ApiEnvelope<AssessmentState>> {
    if (assessmentId) return this.getAssessmentState(assessmentId)
    await sleep()
    assessmentIndex = 0
    answeredCount = 0
    mockAssessmentId = `ASSESS_demo_session_${Date.now()}`
    return {
      ...requestIds('assessment_start'),
      data: {
        assessment_id: mockAssessmentId,
        subject_id: 'SUBJ_demo_student_001',
        status: 'in_progress',
        current_index: assessmentIndex,
        answered_count: answeredCount,
        can_complete: false,
        max_items: 8,
        question: clone(catQuestions[assessmentIndex]),
      },
    } as ApiEnvelope<AssessmentState>
  }

  async submitAssessmentResponse(assessmentId: string, itemId: string, response: string): Promise<ApiEnvelope<AssessmentState>> {
    await sleep(520)
    if (!assessmentId || !itemId || !response) throw new MockApiError('ASSESSMENT_SCHEMA_INVALID', '这道题还没有完成选择。')
    if (currentDemoState() === 'submit-error') {
      throw new MockApiError('ASSESSMENT_SUBMIT_FAILED', '答案暂时没有保存，请保持页面不动后重试。', true)
    }

    answeredCount += 1
    assessmentIndex += 1
    const canComplete = answeredCount >= 3
    const question = catQuestions[assessmentIndex] ? clone(catQuestions[assessmentIndex]) : null
    return {
      ...requestIds('assessment_response'),
      data: {
        assessment_id: assessmentId,
        subject_id: 'SUBJ_demo_student_001',
        status: question ? 'in_progress' : 'completed',
        current_index: assessmentIndex,
        answered_count: answeredCount,
        can_complete: canComplete,
        max_items: 8,
        question,
      },
    } as ApiEnvelope<AssessmentState>
  }

  async completeAssessment(assessmentId: string): Promise<ApiEnvelope<Assessment>> {
    await sleep(680)
    if (!assessmentId) throw new MockApiError('ASSESSMENT_NOT_FOUND', '测评会话已失效，请重新开始。')
    return {
      ...requestIds('assessment_complete'),
      data: clone({ ...syntheticAssessment, assessment_id: assessmentId }),
    } as ApiEnvelope<Assessment>
  }

  async createSupport(assessmentId: string, message: string): Promise<ApiEnvelope<SupportResult>> {
    await sleep(520)
    if (!assessmentId || !message.trim()) throw new MockApiError('SUPPORT_SCHEMA_INVALID', '支持请求还没有准备好。')
    return {
      ...requestIds('support_create'),
      data: {
        status: 'generated',
        safety_action: 'PROCEED_WITH_BOUNDARY',
        normal_generation: true,
        generation: clone(studentReportFixture.report.generation) as unknown as Record<string, unknown>,
        report_id: studentReportFixture.report.reportId,
        content: clone(studentReportFixture.report.generation.content) as unknown as Record<string, unknown>,
        citations: clone(studentReportFixture.evidence) as unknown as Array<Record<string, unknown>>,
        review_reference: null,
        crisis_response: null,
        trace_id: 'TRACE_demo_support',
        synthetic_fixture_only: true,
        integration_labels: { CAT: 'MOCK', RAG: 'MOCK', LLM_RUNTIME: 'MOCK', SAFETY: 'MOCK' },
      },
    } as ApiEnvelope<SupportResult>
  }

  async getStudentReport(reportId: string): Promise<ApiEnvelope<StudentReportViewModel>> {
    await sleep()
    if (!reportId) throw new MockApiError('REPORT_NOT_FOUND', '没有找到这份结果，请返回后重试。')
    const state = currentDemoState()
    const report = clone(studentReportFixture)
    if (state === 'evidence-unavailable') report.evidence = []
    if (state === 'partial') {
      report.meaning.body = '这次结果的部分内容已经准备好，但完整支持参考仍在整理中。'
      report.report.generation.content = null
    }
    return {
      ...requestIds('student_report'),
      data: report,
    } as ApiEnvelope<StudentReportViewModel>
  }

  async getTeacherOverview(): Promise<ApiEnvelope<unknown>> {
    throw new MockApiError('API_UNAVAILABLE', '教师汇总需要已授权的真实本地服务。')
  }

  async getTeacherStudent(_subjectId: string): Promise<ApiEnvelope<unknown>> {
    throw new MockApiError('API_UNAVAILABLE', '教师历史需要已授权的真实本地服务。')
  }

  async getReviewQueue(): Promise<ApiEnvelope<ReviewQueueViewModel>> {
    await sleep()
    const state = currentDemoState()
    if (state === 'error') throw new MockApiError('REVIEW_QUEUE_UNAVAILABLE', '复核队列暂时无法加载，请重试。', true)
    return {
      ...requestIds('review_queue'),
      data: {
        fixtureLabel: SYNTHETIC_FIXTURE_LABEL,
        cases: state === 'empty' ? [] : [clone(reviewCaseState), {
          ...clone(reviewCaseState),
          review_case_id: 'REVIEW_demo_002',
          case_id: 'CASE_demo_review_002',
          subject_id: 'SUBJ_demo_review_002',
          report_id: 'REPORT_demo_review_002',
          status: 'IN_REVIEW',
          priority: 'NORMAL',
          summary: '这份合成案例正在由复核员确认支持范围。',
          updated_at: '2026-09-04T09:10:00Z',
        }],
      },
    } as ApiEnvelope<ReviewQueueViewModel>
  }

  async getReviewDetail(reviewCaseId: string): Promise<ApiEnvelope<ReviewDetailViewModel>> {
    await sleep()
    if (reviewCaseId !== reviewCaseState.review_case_id && reviewCaseId !== 'REVIEW_demo_002') {
      throw new MockApiError('REVIEW_NOT_FOUND', '没有找到这条复核记录。')
    }
    const caseData = reviewCaseId === 'REVIEW_demo_002'
      ? { ...clone(reviewCaseState), review_case_id: 'REVIEW_demo_002', status: 'IN_REVIEW' as const, priority: 'NORMAL' as const }
      : clone(reviewCaseState)
    return {
      ...requestIds('review_detail'),
      data: {
        fixtureLabel: SYNTHETIC_FIXTURE_LABEL,
        case: caseData,
        timeline: [
          { label: '测评完成', detail: '已形成最小结构摘要', time: '今天 13:58', tone: 'done' },
          { label: '安全检查', detail: '普通个性化生成已暂停', time: '今天 14:02', tone: 'done' },
          { label: '进入人工复核', detail: '等待复核员确认下一步', time: '今天 14:20', tone: 'current' },
          { label: '审核结果', detail: '完成后记录在此处', time: '待处理', tone: 'muted' },
        ],
        evidence: clone(reviewEvidence),
        safeAssessment: {
          assessmentId: 'ASSESS_demo_review_001',
          completion: '已完成 · 仅摘要',
          dataBoundary: '只展示授权摘要，不含原始回答或身份信息。',
          dimensionNote: '维度名称与数值为合成结构，占位展示，不作心理学解释。',
        },
        allowedActions: caseData.status === 'APPROVED' || caseData.status === 'REJECTED' ? [] : ['approved', 'rejected'],
      },
    } as ApiEnvelope<ReviewDetailViewModel>
  }

  async submitReview(reportId: string, input: ReviewSubmission): Promise<ApiEnvelope<ReviewCase>> {
    await sleep(620)
    if (reportId !== reviewCaseState.report_id) throw new MockApiError('REPORT_NOT_FOUND', '这条报告已经不存在或已被移除。')
    if (reviewCaseState.status === 'APPROVED' || reviewCaseState.status === 'REJECTED') {
      throw new MockApiError('CONFLICT_IDEMPOTENCY', '这条复核记录已经处理完成。')
    }
    reviewCaseState = {
      ...reviewCaseState,
      status: input.decision === 'approved' ? 'APPROVED' : 'REJECTED',
      updated_at: '2026-09-05T07:00:00Z',
      summary: input.decision === 'approved'
        ? '复核已完成。结果可以进入后续授权流程。'
        : '复核已完成。该结果不会进入后续发布流程。',
    }
    return {
      ...requestIds('review_submit'),
      data: clone(reviewCaseState),
    } as ApiEnvelope<ReviewCase>
  }
}

export const frontendApi: FrontendApi = import.meta.env.MODE === 'test' || import.meta.env.VITE_API_MODE === 'mock'
  ? new MockApiProvider()
  : new RealApiProvider()

export type FrontendReport = Report
