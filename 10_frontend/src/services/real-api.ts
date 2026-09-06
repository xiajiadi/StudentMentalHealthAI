import {
  createAssessment,
  createSupportApiV1SupportRequestsPost,
  completeAssessment,
  getAssessment,
  getAssessmentState,
  getReport,
  getReviewApiV1ReviewsReviewIdGet,
  listReviewsApiV1ReviewsGet,
  loginApiV1AuthLoginPost,
  meApiV1AuthMeGet,
  recordAssessmentResponse,
  reviewReport,
} from '@/api/generated/sdk.gen'
import { createClient, createConfig } from '@/api/generated/client'
import type { ApiEnvelope, Assessment, Citation, GenerationResult } from '@/types/contracts'
import type {
  CatQuestion,
  ReviewCase,
  ReviewDetailViewModel,
  ReviewQueueViewModel,
  StudentHomeViewModel,
  StudentReportViewModel,
  TeacherOverviewViewModel,
} from '@/types/view-models'
import type {
  AssessmentState,
  FrontendApi,
  LoginInput,
  LoginResult,
  ReviewSubmission,
  SupportResult,
} from '@/api/client'

type UnknownRecord = Record<string, unknown>

const SYNTHETIC_FIXTURE_LABEL = '真实接口 · 合成数据 · 仅用于工程验证'
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || '/'
const apiClient = createClient(createConfig({
  baseUrl: apiBaseUrl,
  credentials: 'include',
}))

export class RealApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly retryable = false,
  ) {
    super(message)
    this.name = 'RealApiError'
  }
}

const isRecord = (value: unknown): value is UnknownRecord => Boolean(value) && typeof value === 'object'

const requestError = (value: unknown): RealApiError => {
  if (isRecord(value)) {
    const detail = value.detail
    if (typeof detail === 'string') return new RealApiError(String(value.code || 'API_ERROR'), detail)
    if (Array.isArray(detail)) return new RealApiError(String(value.code || 'API_VALIDATION_ERROR'), '请求参数没有通过校验。')
    const message = typeof value.message === 'string' ? value.message : '接口请求没有完成。'
    return new RealApiError(String(value.code || 'API_ERROR'), message, Boolean(value.retryable))
  }
  return new RealApiError('API_ERROR', '接口请求没有完成。', true)
}

const unwrap = async <T>(operation: () => Promise<unknown>): Promise<ApiEnvelope<T>> => {
  let raw: unknown
  try {
    raw = await operation()
  } catch (error) {
    if (error instanceof RealApiError) throw error
    throw new RealApiError('NETWORK_UNAVAILABLE', '当前无法连接到本地接口，请确认 Backend 正在运行。', true)
  }

  if (!isRecord(raw)) throw new RealApiError('API_INVALID_RESPONSE', '接口返回了无法识别的响应。')
  if (raw.error) throw requestError(raw.error)
  if (typeof raw.request_id === 'string' && 'data' in raw) return raw as unknown as ApiEnvelope<T>
  if (isRecord(raw.data) && typeof raw.data.request_id === 'string' && 'data' in raw.data) {
    return raw.data as unknown as ApiEnvelope<T>
  }
  throw new RealApiError('API_INVALID_RESPONSE', '接口响应缺少统一信封字段。')
}

const nowToken = (prefix: string) => {
  const suffix = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}-${suffix}`
}

const valueAsString = (value: unknown, fallback = '') => typeof value === 'string' ? value : fallback

const mapQuestion = (value: unknown): CatQuestion | null => {
  if (!isRecord(value) || typeof value.item_id !== 'string' || typeof value.prompt !== 'string') return null
  const options = Array.isArray(value.options)
    ? value.options.filter(isRecord).map((option) => ({
      value: valueAsString(option.value),
      label: valueAsString(option.label, valueAsString(option.value)),
    })).filter((option) => option.value)
    : []
  return { item_id: value.item_id, prompt: value.prompt, options }
}

const mapAssessmentState = (value: unknown): AssessmentState => {
  const source = isRecord(value) ? value : {}
  const status = valueAsString(source.status, 'created')
  return {
    assessment_id: valueAsString(source.assessment_id),
    subject_id: valueAsString(source.subject_id),
    status: status === 'completed' ? 'completed' : status === 'in_progress' ? 'in_progress' : 'created',
    current_index: typeof source.current_index === 'number' ? source.current_index : 0,
    answered_count: typeof source.answered_count === 'number' ? source.answered_count : 0,
    can_complete: Boolean(source.can_complete),
    max_items: typeof source.max_items === 'number' ? source.max_items : 0,
    question: mapQuestion(source.current_item),
  }
}

const mutationHeaders = (csrfToken: string, key: string) => ({
  'X-CSRF-Token': csrfToken,
  'Idempotency-Key': key,
})

const mapRole = (value: unknown, fallback: LoginInput['role']): LoginInput['role'] => {
  const role = valueAsString(value).toLowerCase()
  return role === 'teacher' || role === 'reviewer' || role === 'student' ? role : fallback
}

const mapAssessment = (value: unknown, assessmentId: string, subjectId: string): Assessment => {
  const source = isRecord(value) ? value : {}
  const rawDimensions = isRecord(source.dimensions) ? source.dimensions : {}
  const dimensions: Assessment['dimensions'] = {}
  for (const [key, rawValue] of Object.entries(rawDimensions)) {
    const dimension = isRecord(rawValue) ? rawValue : {}
    const theta = typeof dimension.theta === 'number' ? dimension.theta : 0
    const score = typeof dimension.score === 'number' ? dimension.score : null
    const band = dimension.band === 'attention' || dimension.band === 'normal' ? dimension.band : 'unknown'
    dimensions[key] = {
      theta,
      se: typeof dimension.se === 'number' ? dimension.se : 0,
      score,
      band,
      interpretation_status: dimension.interpretation_status === 'estimated' || dimension.interpretation_status === 'insufficient_data'
        ? dimension.interpretation_status
        : 'not_scored',
      items_answered: typeof dimension.items_answered === 'number' ? dimension.items_answered : 0,
    }
  }
  const riskSource = isRecord(source.risk) ? source.risk : {}
  const level = riskSource.level === 'crisis' || riskSource.level === 'high' || riskSource.level === 'attention'
    ? riskSource.level
    : 'normal'
  const timestamps = isRecord(source.timestamps) ? source.timestamps : {}
  const instrument = isRecord(source.instrument) ? source.instrument : {}
  const provenance = isRecord(source.provenance) ? source.provenance : {}
  const summary = isRecord(source.response_summary) ? source.response_summary : {}
  return {
    schema_version: 'assessment.v1',
    assessment_id: valueAsString(source.assessment_id, assessmentId),
    subject_id: valueAsString(source.subject_id, subjectId),
    instrument: {
      instrument_id: valueAsString(instrument.instrument_id, 'instrument_demo_cat_v0_1'),
      version: valueAsString(instrument.version, 'demo.v1'),
    },
    population_scope: valueAsString(source.population_scope, 'K12学生 · 合成范围'),
    status: valueAsString(source.status, 'completed') as Assessment['status'],
    dimensions,
    risk: {
      level,
      need_human_review: Boolean(riskSource.need_human_review),
      reason_codes: Array.isArray(riskSource.reason_codes) ? riskSource.reason_codes.filter((item): item is string => typeof item === 'string') : [],
      ruleset_id: valueAsString(riskSource.ruleset_id, 'RULESET_not_exposed'),
    },
    response_summary: {
      items_answered: typeof summary.items_answered === 'number' ? summary.items_answered : 0,
      duration_seconds: typeof summary.duration_seconds === 'number' ? summary.duration_seconds : null,
    },
    provenance: {
      source_adapter: valueAsString(provenance.source_adapter, 'cat_http_adapter'),
      adapter_version: valueAsString(provenance.adapter_version, 'unknown'),
      cat_engine_version: valueAsString(provenance.cat_engine_version, 'adaptivetesting-1.2.1'),
      item_bank_version: valueAsString(provenance.item_bank_version, 'demo.v1'),
    },
    timestamps: {
      started_at: valueAsString(timestamps.started_at, new Date().toISOString()),
      completed_at: typeof timestamps.completed_at === 'string' ? timestamps.completed_at : null,
    },
  }
}

const allowedGenerationStatuses = new Set<GenerationResult['status']>([
  'requested', 'safety_blocked', 'generating', 'generated', 'needs_review', 'approved', 'rejected',
])

const mapGeneration = (value: unknown, report: UnknownRecord, assessmentId: string): GenerationResult => {
  const source = isRecord(value) ? value : {}
  const statusValue = valueAsString(source.status, valueAsString(report.status, 'safety_blocked'))
  const status = allowedGenerationStatuses.has(statusValue as GenerationResult['status'])
    ? statusValue as GenerationResult['status']
    : statusValue === 'closed' ? 'approved' : 'safety_blocked'
  const rawContent = isRecord(source.content) ? source.content : null
  const content = rawContent
    ? {
      summary: valueAsString(rawContent.summary, '这份合成支持参考已准备好。'),
      observations: Array.isArray(rawContent.observations) ? rawContent.observations.filter((item): item is string => typeof item === 'string') : [],
      suggestions: Array.isArray(rawContent.suggestions)
        ? rawContent.suggestions.filter(isRecord).map((item) => ({
          text: valueAsString(item.text),
          source_chunk_ids: Array.isArray(item.source_chunk_ids)
            ? item.source_chunk_ids.filter((chunk): chunk is string => typeof chunk === 'string')
            : [],
        })).filter((item) => item.text && item.source_chunk_ids.length)
        : [],
      disclaimer: valueAsString(rawContent.disclaimer, '此内容用于教育支持，不构成诊断或治疗建议。合成案例不代表真实学生结果。'),
    }
    : null
  const safety = isRecord(source.safety) ? source.safety : {}
  const provenance = isRecord(source.provenance) ? source.provenance : {}
  const review = isRecord(source.review) ? source.review : {}
  const reviewStatus = valueAsString(review.status, valueAsString(report.review_status, 'not_required'))
  return {
    schema_version: 'generation.v1',
    generation_id: valueAsString(source.generation_id, valueAsString(report.generation_id, 'GEN_not_exposed')),
    status,
    target_role: source.target_role === 'teacher' || source.target_role === 'parent' || source.target_role === 'admin' ? source.target_role : 'student',
    content,
    safety: {
      precheck: safety.precheck === 'passed' || safety.precheck === 'warn' || safety.precheck === 'needs_review' ? safety.precheck : 'blocked',
      postcheck: safety.postcheck === 'passed' || safety.postcheck === 'warn' || safety.postcheck === 'needs_review' ? safety.postcheck : 'blocked',
      reason_codes: Array.isArray(safety.reason_codes) ? safety.reason_codes.filter((item): item is string => typeof item === 'string') : [],
      human_review_required: Boolean(safety.human_review_required),
    },
    provenance: {
      assessment_id: valueAsString(provenance.assessment_id, assessmentId),
      retrieval_id: valueAsString(provenance.retrieval_id, 'RETR_not_run'),
      prompt_id: valueAsString(provenance.prompt_id, 'PROMPT_backend_support_v1'),
      prompt_version: valueAsString(provenance.prompt_version, '1.0'),
      model_id: valueAsString(provenance.model_id, 'MODEL_not_used'),
      model_version: valueAsString(provenance.model_version, 'not_used'),
      runtime_version: valueAsString(provenance.runtime_version, 'not_used'),
    },
    review: {
      status: reviewStatus === 'approved' || reviewStatus === 'rejected' || reviewStatus === 'pending' ? reviewStatus : 'not_required',
      reviewer_id: typeof review.reviewer_id === 'string' ? review.reviewer_id : null,
      reviewed_at: typeof review.reviewed_at === 'string' ? review.reviewed_at : null,
    },
    created_at: valueAsString(source.created_at, new Date().toISOString()),
  }
}

const citationsFromGeneration = (generation: GenerationResult): Citation[] => {
  const ids = new Set<string>()
  for (const suggestion of generation.content?.suggestions || []) {
    for (const chunkId of suggestion.source_chunk_ids) ids.add(chunkId)
  }
  return [...ids].map((chunkId, index) => ({
    citation_id: `CITE_${index + 1}_${chunkId}`,
    chunk_id: chunkId,
    title: '已审核资料片段',
    organization: '合成教育资料库',
    locator: `knowledge.v1 · ${chunkId}`,
  }))
}

const mapReport = (rawReport: unknown, rawAssessment: unknown): StudentReportViewModel => {
  const report = isRecord(rawReport) ? rawReport : {}
  const assessmentId = valueAsString(report.assessment_id)
  const assessment = mapAssessment(rawAssessment, assessmentId, 'SUBJ_REDACTED')
  const generation = mapGeneration(report.generation, report, assessmentId)
  const actions = generation.content?.suggestions.map((suggestion, index) => ({
    number: String(index + 1).padStart(2, '0'),
    title: `从一个小步骤开始 ${index + 1}`,
    body: suggestion.text,
  })) || []
  const dimensions = Object.entries(assessment.dimensions).map(([key, dimension], index) => ({
    key,
    label: `维度 ${String.fromCharCode(65 + index)} · 合成占位`,
    value: dimension.score ?? Math.max(0, Math.min(100, Math.round(50 + dimension.theta * 12))),
    helper: '结构估计 · 非诊断',
  }))
  return {
    fixtureLabel: SYNTHETIC_FIXTURE_LABEL,
    report: {
      reportId: valueAsString(report.report_id),
      assessmentId,
      generation,
      assessment,
    },
    meaning: {
      title: '把这份结构当作下一步的参考',
      body: '这份页面只承载合成测评与支持流程的结构，不把结果解释成疾病、诊断或确定性标签。',
      note: '真实部署时，展示范围由后端授权与安全披露策略共同决定。',
    },
    data: {
      title: '本次测评的结构',
      body: '维度名称与数值只用于展示接口如何承载结构化结果，不代表经过确认的心理学维度。',
      dimensions,
    },
    actions,
    evidence: citationsFromGeneration(generation),
  }
}

const mapReviewStatus = (value: unknown): ReviewCase['status'] => {
  const status = valueAsString(value, 'pending').toUpperCase()
  return status === 'IN_REVIEW' || status === 'APPROVED' || status === 'REJECTED' ? status : 'PENDING'
}

const mapReviewCase = (value: unknown): ReviewCase => {
  const source = isRecord(value) ? value : {}
  const reviewId = valueAsString(source.review_id, 'REVIEW_REDACTED')
  const action = valueAsString(source.safety_action, 'REVIEW_REQUIRED')
  const highPriority = action === 'CRISIS_ROUTE'
  const timestamp = new Date().toISOString()
  return {
    review_case_id: valueAsString(source.safety_review_case_id, reviewId),
    review_id: reviewId,
    case_id: null,
    decision_id: 'DECISION_REDACTED',
    trace_id: 'TRACE_REDACTED',
    status: mapReviewStatus(source.status),
    reason_codes: Array.isArray(source.reason_codes) ? source.reason_codes.filter((item): item is string => typeof item === 'string') : ['HUMAN_REVIEW_REQUIRED'],
    priority: highPriority ? 'CRITICAL' : 'HIGH',
    assigned_role: 'REVIEWER',
    disclosure_policy: 'REDACTED',
    subject_id: 'SUBJ_REDACTED',
    report_id: valueAsString(source.report_id, 'REPORT_REDACTED'),
    created_at: timestamp,
    updated_at: timestamp,
    generationStatus: 'needs_review',
    summary: `安全流程 ${action}，普通个性化生成已暂停，等待人工确认。`,
    safeContext: '仅展示后端授权的最小摘要。原始回答、身份信息和完整模型上下文不在此页面。',
  }
}

export class RealApiProvider implements FrontendApi {
  private csrfToken = ''
  private readonly reviewCases = new Map<string, ReviewCase>()

  async login(input: LoginInput): Promise<ApiEnvelope<LoginResult>> {
    const response = await unwrap<UnknownRecord>(() => loginApiV1AuthLoginPost({
      client: apiClient,
      body: { username: input.account, password: input.password },
    }))
    const actor = isRecord(response.data.actor) ? response.data.actor : {}
    this.csrfToken = valueAsString(response.data.csrf_token)
    return {
      ...response,
      data: {
        userId: valueAsString(actor.user_id),
        role: mapRole(actor.role, input.role),
        displayName: valueAsString(actor.username, input.account),
        initials: valueAsString(actor.username, input.account).slice(0, 1).toUpperCase(),
      },
    }
  }

  async getStudentHome(): Promise<ApiEnvelope<StudentHomeViewModel | null>> {
    const response = await unwrap<UnknownRecord>(() => meApiV1AuthMeGet({ client: apiClient }))
    return { ...response, data: null }
  }

  async startAssessment(): Promise<ApiEnvelope<AssessmentState>> {
    const created = await unwrap<unknown>(() => createAssessment({
      client: apiClient,
      body: {
        subject_id: 'SUBJ_demo_a',
        instrument_id: 'instrument_demo_cat_v0_1',
        instrument_version: 'demo.v1',
      },
      headers: mutationHeaders(this.csrfToken, nowToken('frontend-assessment-create')),
    }))
    const createdAssessment = isRecord(created.data) ? created.data : {}
    const assessmentId = valueAsString(createdAssessment.assessment_id)
    if (!assessmentId) throw new RealApiError('API_INVALID_RESPONSE', '接口没有返回测评会话标识。')
    const state = await unwrap<unknown>(() => getAssessmentState({
      client: apiClient,
      path: { assessment_id: assessmentId },
    }))
    return { ...state, data: mapAssessmentState(state.data) }
  }

  async submitAssessmentResponse(assessmentId: string, itemId: string, response: string): Promise<ApiEnvelope<AssessmentState>> {
    const result = await unwrap<unknown>(() => recordAssessmentResponse({
      client: apiClient,
      path: { assessment_id: assessmentId },
      body: { item_id: itemId, response },
      headers: mutationHeaders(this.csrfToken, nowToken(`frontend-assessment-response-${assessmentId}`)),
    }))
    return { ...result, data: mapAssessmentState(result.data) }
  }

  async completeAssessment(assessmentId: string): Promise<ApiEnvelope<Assessment>> {
    const response = await unwrap<unknown>(() => completeAssessment({
      client: apiClient,
      path: { assessment_id: assessmentId },
      body: {},
      headers: mutationHeaders(this.csrfToken, nowToken(`frontend-assessment-complete-${assessmentId}`)),
    }))
    return { ...response, data: mapAssessment(response.data, assessmentId, 'SUBJ_demo_a') }
  }

  async createSupport(assessmentId: string, message: string): Promise<ApiEnvelope<SupportResult>> {
    return unwrap<SupportResult>(() => createSupportApiV1SupportRequestsPost({
      client: apiClient,
      body: {
        assessment_id: assessmentId,
        target_role: 'student',
        message,
        language: 'zh-CN',
        purpose: 'education_support',
      },
      headers: mutationHeaders(this.csrfToken, nowToken(`frontend-support-${assessmentId}`)),
    }))
  }

  async getStudentReport(reportId: string): Promise<ApiEnvelope<StudentReportViewModel>> {
    const reportResponse = await unwrap<unknown>(() => getReport({
      client: apiClient,
      path: { report_id: reportId },
    }))
    const rawReport = isRecord(reportResponse.data) ? reportResponse.data : {}
    const assessmentId = valueAsString(rawReport.assessment_id)
    const assessmentResponse = await unwrap<unknown>(() => getAssessment({
      client: apiClient,
      path: { assessment_id: assessmentId },
    }))
    return { ...reportResponse, data: mapReport(rawReport, assessmentResponse.data) }
  }

  async getTeacherOverview(): Promise<ApiEnvelope<TeacherOverviewViewModel>> {
    const response = await unwrap<UnknownRecord>(() => meApiV1AuthMeGet({ client: apiClient }))
    return {
      ...response,
      data: { fixtureLabel: SYNTHETIC_FIXTURE_LABEL, summary: [], trend: [], attentionCases: [] },
    }
  }

  async getReviewQueue(): Promise<ApiEnvelope<ReviewQueueViewModel>> {
    const response = await unwrap<unknown>(() => listReviewsApiV1ReviewsGet({ client: apiClient }))
    const rawCases = Array.isArray(response.data) ? response.data : []
    const cases = rawCases.map(mapReviewCase)
    for (const item of cases) this.reviewCases.set(item.report_id, item)
    return {
      ...response,
      data: { fixtureLabel: SYNTHETIC_FIXTURE_LABEL, cases },
    }
  }

  async getReviewDetail(reviewCaseId: string): Promise<ApiEnvelope<ReviewDetailViewModel>> {
    const response = await unwrap<unknown>(() => getReviewApiV1ReviewsReviewIdGet({
      client: apiClient,
      path: { review_id: reviewCaseId },
    }))
    const caseData = mapReviewCase(response.data)
    this.reviewCases.set(caseData.report_id, caseData)
    const now = new Date().toISOString()
    return {
      ...response,
      data: {
        fixtureLabel: SYNTHETIC_FIXTURE_LABEL,
        case: caseData,
        timeline: [
          { label: '安全检查', detail: '普通个性化生成已暂停', time: now, tone: 'done' },
          { label: '进入人工复核', detail: '等待复核员确认下一步', time: now, tone: 'current' },
          { label: '审核结果', detail: '完成后记录在此处', time: '待处理', tone: 'muted' },
        ],
        evidence: [],
        safeAssessment: {
          assessmentId: valueAsString((response.data as UnknownRecord).assessment_id, 'ASSESS_REDACTED'),
          completion: '已完成 · 仅摘要',
          dataBoundary: '只展示授权摘要，不含原始回答或身份信息。',
          dimensionNote: '维度名称与数值为合成结构，占位展示，不作心理学解释。',
        },
        allowedActions: caseData.status === 'APPROVED' || caseData.status === 'REJECTED' ? [] : ['approved', 'rejected'],
      },
    }
  }

  async submitReview(reportId: string, input: ReviewSubmission): Promise<ApiEnvelope<ReviewCase>> {
    const response = await unwrap<UnknownRecord>(() => reviewReport({
      client: apiClient,
      path: { report_id: reportId },
      body: { decision: input.decision, note_code: input.note.trim().slice(0, 160) || undefined },
      headers: mutationHeaders(this.csrfToken, nowToken(`frontend-review-${reportId}`)),
    }))
    const prior = this.reviewCases.get(reportId)
    const status = valueAsString(response.data.review_status, input.decision)
    const caseData: ReviewCase = {
      ...(prior || mapReviewCase({ report_id: reportId, review_id: response.data.review_id, status })),
      status: status === 'approved' ? 'APPROVED' : 'REJECTED',
      updated_at: new Date().toISOString(),
      summary: input.decision === 'approved' ? '复核已完成。结果可以进入后续授权流程。' : '复核已完成。该结果不会进入后续发布流程。',
    }
    this.reviewCases.set(reportId, caseData)
    return { ...response, data: caseData }
  }
}
