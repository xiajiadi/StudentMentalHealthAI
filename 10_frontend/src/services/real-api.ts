import {
  createAssessment,
  createSupport,
  completeAssessment,
  getAssessment,
  getAssessmentState,
  getReport,
  getReview,
  listReviews,
  authLogin,
  authLogout,
  authMe,
  authCsrf,
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
     const code = typeof value.code === 'string' ? value.code : 'API_ERROR'
     const detail = typeof value.detail === 'string' ? value.detail : '接口请求没有完成。'
     const message = Array.isArray(value.errors) ? '请求参数没有通过校验。' : detail
     return new RealApiError(code, message, Boolean(value.retryable))
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
const nullableString = (value: unknown): string | null => typeof value === 'string' ? value : null

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

const mapAssessment = (value: unknown, assessmentId: string): Assessment => {
  const source = isRecord(value) ? value : {}
  const subjectId = valueAsString(source.subject_id)
  if (!subjectId) {
    throw new RealApiError('API_INVALID_RESPONSE', '测评响应缺少主体标识，已停止展示该记录。')
  }
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
  if (!isRecord(source.risk)) {
    throw new RealApiError('API_INVALID_RESPONSE', '测评响应缺少有效风险信息，已停止展示该记录。')
  }
  const riskSource = source.risk
  const allowedRiskLevels = new Set(['normal', 'attention', 'high', 'crisis'])
  if (typeof riskSource.level !== 'string' || !allowedRiskLevels.has(riskSource.level)) {
    throw new RealApiError('API_INVALID_RESPONSE', '测评响应包含无效风险等级，已停止展示该记录。')
  }
  if (typeof riskSource.need_human_review !== 'boolean') {
    throw new RealApiError('API_INVALID_RESPONSE', '测评响应缺少有效人工复核状态，已停止展示该记录。')
  }
  const timestamps = isRecord(source.timestamps) ? source.timestamps : {}
  const instrument = isRecord(source.instrument) ? source.instrument : {}
  const provenance = isRecord(source.provenance) ? source.provenance : {}
  const summary = isRecord(source.response_summary) ? source.response_summary : {}
  return {
    schema_version: 'assessment.v1',
    assessment_id: valueAsString(source.assessment_id, assessmentId),
    subject_id: subjectId,
    instrument: {
      instrument_id: valueAsString(instrument.instrument_id, 'CURRENT_SYNTHETIC_GRM'),
      version: valueAsString(instrument.version, 'synthetic_item_bank.v1 / demo.v1'),
    },
    population_scope: valueAsString(source.population_scope, '大学新生合成演示范围'),
    status: valueAsString(source.status, 'completed') as Assessment['status'],
    dimensions,
    risk: {
      level: riskSource.level as Assessment['risk']['level'],
      need_human_review: riskSource.need_human_review,
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
      cat_engine_version: valueAsString(provenance.cat_engine_version, 'not_exposed'),
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
  const generationStatus = provenance.generation_status === 'NOT_RUN'
    || (!rawContent && status !== 'generated') ? 'NOT_RUN' : 'EXECUTED'
  const candidateSource = provenance.candidate_source === 'CONTROLLED_SYNTHETIC'
    ? 'CONTROLLED_SYNTHETIC'
    : generationStatus === 'NOT_RUN' ? 'NOT_RUN' : 'MODEL_EXECUTED'
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
      model_id: generationStatus === 'NOT_RUN' ? null : nullableString(provenance.model_id),
      model_version: generationStatus === 'NOT_RUN' ? null : nullableString(provenance.model_version),
      runtime_version: generationStatus === 'NOT_RUN' ? null : nullableString(provenance.runtime_version),
      generation_status: generationStatus,
      candidate_source: candidateSource,
    },
    review: {
      status: reviewStatus === 'approved' || reviewStatus === 'rejected' || reviewStatus === 'pending' ? reviewStatus : 'not_required',
      reviewer_id: typeof review.reviewer_id === 'string' ? review.reviewer_id : null,
      reviewed_at: typeof review.reviewed_at === 'string' ? review.reviewed_at : null,
    },
    created_at: valueAsString(source.created_at, new Date().toISOString()),
  }
}

const citationsFromApi = (value: unknown): Citation[] => {
  if (!Array.isArray(value)) return []
  return value.filter(isRecord).map((item, index) => ({
    citation_id: valueAsString(item.citation_id, `CITE_unavailable_${index + 1}`),
    chunk_id: nullableString(item.chunk_id),
    document_id: nullableString(item.document_id),
    title: nullableString(item.title),
    organization: nullableString(item.organization),
    locator: nullableString(item.locator),
    excerpt: nullableString(item.excerpt),
  }))
}

const mapReport = (rawReport: unknown, rawAssessment: unknown): StudentReportViewModel => {
  const report = isRecord(rawReport) ? rawReport : {}
  const assessmentId = valueAsString(report.assessment_id)
  const assessment = mapAssessment(rawAssessment, assessmentId)
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
    evidence: citationsFromApi(report.citations),
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
  private actorSubjectId: string | null = null
  private readonly reviewCases = new Map<string, ReviewCase>()

  private async ensureCsrfToken(): Promise<string> {
    if (this.csrfToken) return this.csrfToken
    const response = await unwrap<{ csrf_token: string }>(() => authCsrf({ client: apiClient }))
    this.csrfToken = response.data.csrf_token
    return this.csrfToken
  }

  async login(input: LoginInput): Promise<ApiEnvelope<LoginResult>> {
    const response = await unwrap<UnknownRecord>(() => authLogin({
      client: apiClient,
      body: { username: input.account, password: input.password },
    }))
    const actor = isRecord(response.data.actor) ? response.data.actor : {}
    this.csrfToken = valueAsString(response.data.csrf_token)
    this.actorSubjectId = nullableString(actor.subject_id)
    return {
      ...response,
      data: {
        userId: valueAsString(actor.user_id),
        role: mapRole(actor.role, input.role),
        subjectId: this.actorSubjectId,
        displayName: valueAsString(actor.username, input.account),
        initials: valueAsString(actor.username, input.account).slice(0, 1).toUpperCase(),
      },
    }
  }

  async logout(): Promise<ApiEnvelope<{ logged_out: boolean }>> {
    await this.ensureCsrfToken()
    const response = await unwrap<{ logged_out: boolean }>(() => authLogout({
      client: apiClient,
      headers: mutationHeaders(this.csrfToken, nowToken('frontend-auth-logout')),
    }))
    this.csrfToken = ''
    this.actorSubjectId = null
    return response
  }

  async getCurrentUser(): Promise<ApiEnvelope<LoginResult | null>> {
    const response = await unwrap<UnknownRecord>(() => authMe({ client: apiClient }))
    const actor = isRecord(response.data.actor) ? response.data.actor : response.data
    const userId = valueAsString(actor.user_id)
    if (!userId) return { ...response, data: null }
    const username = valueAsString(actor.username, '演示同学')
    this.actorSubjectId = nullableString(actor.subject_id)
    return {
      ...response,
      data: {
        userId,
        role: mapRole(actor.role, 'student'),
        subjectId: this.actorSubjectId,
        displayName: username,
        initials: username.slice(0, 1).toUpperCase(),
      },
    }
  }

  async getStudentHome(): Promise<ApiEnvelope<StudentHomeViewModel | null>> {
    const response = await unwrap<UnknownRecord>(() => authMe({ client: apiClient }))
    return { ...response, data: null }
  }

  async listAssessments(): Promise<ApiEnvelope<Assessment[]>> {
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET',
      url: '/api/v1/assessments',
      parseAs: 'json',
    }))
    const rows = Array.isArray(response.data) ? response.data : []
    return { ...response, data: rows.map((row) => {
      const source = isRecord(row) ? row : {}
      return mapAssessment(source, valueAsString(source.assessment_id))
    }) }
  }

  async getAssessmentState(assessmentId: string): Promise<ApiEnvelope<AssessmentState>> {
    const response = await unwrap<unknown>(() => getAssessmentState({
      client: apiClient,
      path: { assessment_id: assessmentId },
    }))
    return { ...response, data: mapAssessmentState(response.data) }
  }

  async getAssessmentResult(assessmentId: string): Promise<ApiEnvelope<Assessment>> {
    const response = await unwrap<unknown>(() => getAssessment({ client: apiClient, path: { assessment_id: assessmentId } }))
    const source = isRecord(response.data) ? response.data : {}
    return {
      ...response,
      data: mapAssessment(source, assessmentId),
    }
  }

  async listReports(assessmentId?: string): Promise<ApiEnvelope<{ items: ReportSummary[]; next_cursor: string | null }>> {
    const response = await unwrap<unknown>(() => apiClient.request({
      method: 'GET',
      url: '/api/v1/reports',
      query: { assessment_id: assessmentId, limit: 100 },
      parseAs: 'json',
    }))
    const data = isRecord(response.data) ? response.data : {}
    const items = Array.isArray(data.items) ? data.items.filter(isRecord).map((item) => ({
      report_id: valueAsString(item.report_id),
      assessment_id: valueAsString(item.assessment_id),
      status: valueAsString(item.status, 'unknown'),
      safety_action: nullableString(item.safety_action),
      created_at: valueAsString(item.created_at),
      citation_count: typeof item.citation_count === 'number' ? item.citation_count : 0,
    })) : []
    return { ...response, data: { items, next_cursor: nullableString(data.next_cursor) } }
  }

  async startAssessment(assessmentId?: string): Promise<ApiEnvelope<AssessmentState>> {
    if (assessmentId) return this.getAssessmentState(assessmentId)
    if (!this.actorSubjectId) {
      throw new RealApiError('AUTH_SUBJECT_MISSING', '当前登录账号缺少授权的合成主体标识，无法创建测评。')
    }
    await this.ensureCsrfToken()
    const created = await unwrap<unknown>(() => createAssessment({
      client: apiClient,
      body: {
        subject_id: this.actorSubjectId,
        instrument_id: 'CURRENT_SYNTHETIC_GRM',
        instrument_version: 'synthetic_item_bank.v1 / demo.v1',
      },
      headers: mutationHeaders(this.csrfToken, nowToken('frontend-assessment-create')),
    }))
    const createdAssessment = isRecord(created.data) ? created.data : {}
    const createdAssessmentId = valueAsString(createdAssessment.assessment_id)
    if (!createdAssessmentId) throw new RealApiError('API_INVALID_RESPONSE', '接口没有返回测评会话标识。')
    const state = await unwrap<unknown>(() => getAssessmentState({
      client: apiClient,
      path: { assessment_id: createdAssessmentId },
    }))
    return { ...state, data: mapAssessmentState(state.data) }
  }

  async submitAssessmentResponse(assessmentId: string, itemId: string, response: string): Promise<ApiEnvelope<AssessmentState>> {
    await this.ensureCsrfToken()
    const result = await unwrap<unknown>(() => recordAssessmentResponse({
      client: apiClient,
      path: { assessment_id: assessmentId },
      body: { item_id: itemId, response },
      headers: mutationHeaders(this.csrfToken, nowToken(`frontend-assessment-response-${assessmentId}`)),
    }))
    return { ...result, data: mapAssessmentState(result.data) }
  }

  async completeAssessment(assessmentId: string): Promise<ApiEnvelope<Assessment>> {
    await this.ensureCsrfToken()
    const response = await unwrap<unknown>(() => completeAssessment({
      client: apiClient,
      path: { assessment_id: assessmentId },
      body: {},
      headers: mutationHeaders(this.csrfToken, nowToken(`frontend-assessment-complete-${assessmentId}`)),
    }))
    return { ...response, data: mapAssessment(response.data, assessmentId) }
  }

  async createSupport(assessmentId: string, message: string): Promise<ApiEnvelope<SupportResult>> {
    await this.ensureCsrfToken()
    return unwrap<SupportResult>(() => createSupport({
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

  async getTeacherOverview(): Promise<ApiEnvelope<unknown>> {
    return unwrap<unknown>(() => apiClient.request({
      method: 'GET',
      url: '/api/v1/teacher/overview',
      parseAs: 'json',
    }))
  }

  async getTeacherStudent(subjectId: string): Promise<ApiEnvelope<unknown>> {
    return unwrap<unknown>(() => apiClient.request({
      method: 'GET',
      url: `/api/v1/teacher/students/${encodeURIComponent(subjectId)}`,
      parseAs: 'json',
    }))
  }

  async getReviewQueue(): Promise<ApiEnvelope<ReviewQueueViewModel>> {
    const response = await unwrap<unknown>(() => listReviews({ client: apiClient }))
    const rawCases = Array.isArray(response.data) ? response.data : []
    const cases = rawCases.map(mapReviewCase)
    for (const item of cases) this.reviewCases.set(item.report_id, item)
    return {
      ...response,
      data: { fixtureLabel: SYNTHETIC_FIXTURE_LABEL, cases },
    }
  }

  async getReviewDetail(reviewCaseId: string): Promise<ApiEnvelope<ReviewDetailViewModel>> {
    const response = await unwrap<unknown>(() => getReview({
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
    await this.ensureCsrfToken()
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
