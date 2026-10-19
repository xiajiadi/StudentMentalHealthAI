import type { Assessment, Citation, GenerationResult } from '@/types/contracts'
import type {
  CatQuestion,
  ReviewCase,
  StudentHomeViewModel,
  StudentReportViewModel,
  TeacherOverviewViewModel,
} from '@/types/view-models'

export const SYNTHETIC_FIXTURE_LABEL = '合成演示案例，仅用于工程验证'

export const syntheticAssessment: Assessment = {
  schema_version: 'assessment.v1',
  assessment_id: 'ASSESS_demo_student_001',
  subject_id: 'SUBJ_demo_student_001',
  instrument: { instrument_id: 'instrument_demo', version: '1.0.0' },
  population_scope: 'demo_population',
  status: 'completed',
  dimensions: {
    emotion: {
      theta: -0.82,
      se: 0.24,
      score: null,
      band: 'attention',
      interpretation_status: 'estimated',
      items_answered: 5,
    },
    learning: {
      theta: 0.15,
      se: 0.31,
      score: null,
      band: 'normal',
      interpretation_status: 'estimated',
      items_answered: 4,
    },
  },
  risk: {
    level: 'attention',
    need_human_review: false,
    reason_codes: ['RULESET_DEMO_ATTENTION'],
    ruleset_id: 'RULESET_demo_v1',
  },
  response_summary: { items_answered: 9, duration_seconds: 180 },
  provenance: {
    source_adapter: 'demo_adapter',
    adapter_version: '0.1.0',
    cat_engine_version: '0.1.0',
    item_bank_version: 'demo.v1',
  },
  timestamps: {
    started_at: '2026-09-05T00:00:00Z',
    completed_at: '2026-09-05T00:03:00Z',
  },
}

export const syntheticGeneration: GenerationResult = {
  schema_version: 'generation.v1',
  generation_id: 'GEN_demo_student_001',
  status: 'generated',
  target_role: 'student',
  content: {
    summary: '这次结果可以先当作一张“下一步地图”：从当前结构出发，选择一个今天能完成的小行动。',
    observations: [
      '本页面展示的是合成测评结构，不代表真实学生结果。',
      '页面不会把结构化估计转换为诊断或确定性标签。',
    ],
    suggestions: [
      {
        text: '把今天最困扰的一项学习任务拆成一个可以在短时间内完成的小步骤。',
        source_chunk_ids: ['CHUNK_67b56abe21fe9860a26d'],
      },
      {
        text: '如果愿意，可以找一位可信任的老师或家长，说明你希望怎样获得支持。',
        source_chunk_ids: ['CHUNK_8f85f2c0472e21acd2fa'],
      },
      {
        text: '约定一个回看时间，记录这个小步骤是否完成，再决定下一步。',
        source_chunk_ids: ['CHUNK_67b56abe21fe9860a26d'],
      },
    ],
    disclaimer: '此内容用于教育支持，不构成诊断或治疗建议。合成案例不代表真实学生结果。',
  },
  safety: {
    precheck: 'passed',
    postcheck: 'passed',
    reason_codes: ['OUTPUT_DEMO_APPROVED'],
    human_review_required: false,
  },
  provenance: {
    assessment_id: 'ASSESS_demo_student_001',
    retrieval_id: 'RETR_demo_student_001',
    prompt_id: 'PROMPT_student_demo_v1',
    prompt_version: '0.1.0',
    model_id: 'MODEL_local_primary',
    model_version: 'mock-0.1.0',
    runtime_version: '0.1.0',
  },
  review: { status: 'not_required', reviewer_id: null, reviewed_at: null },
  created_at: '2026-09-05T00:04:00Z',
}

export const syntheticCitations: Citation[] = [
  {
    citation_id: 'S1',
    chunk_id: 'CHUNK_67b56abe21fe9860a26d',
    title: '考试压力支持建议（合成夹具）',
    organization: '合成学校支持项目',
    locator: 'file:intervention.md; section:场景：考试压力; pages:unknown',
    excerpt: '先用开放式问题了解当前最困扰的学习或生活环节，再共同选择一个今天可以完成的小步骤。',
  },
  {
    citation_id: 'S2',
    chunk_id: 'CHUNK_8f85f2c0472e21acd2fa',
    title: '学校心理健康教育工作指引（合成夹具）',
    organization: '合成教育资料委员会',
    locator: 'file:policy.md; section:第一节 基本原则; pages:unknown',
    excerpt: '教师发现学生持续困扰时，应当先进行支持性沟通，并按照学校已经审核的转介流程寻求帮助。',
  },
  {
    citation_id: 'S3',
    chunk_id: 'CHUNK_bcbe71382652340b2249',
    title: '学生压力与应对理论摘录（合成夹具）',
    organization: '合成心理教育研究组',
    locator: 'file:theory.md; section:概念：应对; pages:unknown',
    excerpt: '应对包括重新评估问题、寻求支持和调整行动等过程。',
  },
]

export const studentHomeFixture: StudentHomeViewModel = {
  fixtureLabel: SYNTHETIC_FIXTURE_LABEL,
  greeting: '下午好，演示同学',
  stateTitle: '先看见现在，再决定下一步',
  stateBody: '最近一次合成测评已经完成。这里展示的是结构化支持参考，不是诊断结论。',
  nextAction: {
    title: '把一个大任务拆成今天的小步骤',
    body: '选择一件现在最想推进的事，先写下一个 10 分钟内能开始的动作。',
    cta: '开始一次测评',
  },
  recent: {
    label: '最近一次测评',
    status: '已完成，可查看参考',
    date: '2026 年 9 月 5 日',
    reportId: 'REPORT_demo_student_001',
  },
  supportLinks: [
    { title: '先整理，再行动', body: '用一个小问题梳理当前最想解决的事。', icon: 'compass' },
    { title: '了解支持方式', body: '看看学校支持流程和沟通建议。', icon: 'book' },
    { title: '准备一次沟通', body: '把希望获得的帮助写成一句话。', icon: 'message' },
  ],
}

export const catQuestions: CatQuestion[] = [
  {
    item_id: 'ITEM_demo_001',
    prompt: '当一项学习任务变得复杂时，你通常能否找到一个开始的步骤？',
    options: [
      { value: '1', label: '还不太能' },
      { value: '2', label: '偶尔可以' },
      { value: '3', label: '大多可以' },
      { value: '4', label: '通常可以' },
    ],
  },
  {
    item_id: 'ITEM_demo_002',
    prompt: '最近需要完成多件事情时，你能否分辨出先做哪一件？',
    options: [
      { value: '1', label: '还不太能' },
      { value: '2', label: '偶尔可以' },
      { value: '3', label: '大多可以' },
      { value: '4', label: '通常可以' },
    ],
  },
  {
    item_id: 'ITEM_demo_003',
    prompt: '遇到暂时解决不了的学习问题时，你是否知道可以向谁求助？',
    options: [
      { value: '1', label: '还不清楚' },
      { value: '2', label: '有一点方向' },
      { value: '3', label: '大致清楚' },
      { value: '4', label: '比较清楚' },
    ],
  },
  {
    item_id: 'ITEM_demo_004',
    prompt: '完成一个小步骤后，你会不会回看它是否真的帮助了自己？',
    options: [
      { value: '1', label: '很少回看' },
      { value: '2', label: '偶尔回看' },
      { value: '3', label: '有时回看' },
      { value: '4', label: '会固定回看' },
    ],
  },
  {
    item_id: 'ITEM_demo_005',
    prompt: '在需要支持时，你是否能用自己的话说出希望对方怎么帮助你？',
    options: [
      { value: '1', label: '还不太能' },
      { value: '2', label: '偶尔可以' },
      { value: '3', label: '大多可以' },
      { value: '4', label: '通常可以' },
    ],
  },
]

export const studentReportFixture: StudentReportViewModel = {
  fixtureLabel: SYNTHETIC_FIXTURE_LABEL,
  report: {
    reportId: 'REPORT_demo_student_001',
    assessmentId: syntheticAssessment.assessment_id,
    generation: syntheticGeneration,
    assessment: syntheticAssessment,
  },
  meaning: {
    title: '你可以从一个小步骤开始',
    body: '这次结构化结果更适合被当作一次自我整理：先确认当前最想推进的事情，再选择一个可以马上开始的动作。页面不会把这份结果解释成疾病、诊断或确定性标签。',
    note: '本页展示合成案例。真实使用时，展示范围由后端授权与安全披露策略共同决定。',
  },
  data: {
    title: '本次测评的结构',
    body: '下面的图表只帮助你看到页面如何承载测评结构；维度名称和数值均来自合成 fixture，不代表经过确认的心理学维度。',
    dimensions: [
      { key: 'emotion', label: '维度 A，合成占位', value: 58, helper: '结构估计，非诊断' },
      { key: 'learning', label: '维度 B，合成占位', value: 66, helper: '结构估计，非诊断' },
      { key: 'support', label: '维度 C，合成占位', value: 48, helper: '界面示例，非诊断' },
      { key: 'action', label: '维度 D，合成占位', value: 72, helper: '界面示例，非诊断' },
    ],
  },
  actions: [
    { number: '01', title: '先选一个小动作', body: '把当前最困扰的一件事写成一个短时间内可以开始的步骤。' },
    { number: '02', title: '说清楚你需要什么', body: '如果愿意，向一位可信任的老师或家长说明希望获得的支持方式。' },
    { number: '03', title: '约定一次回看', body: '给自己留一个回看时间，再根据实际体验决定下一步。' },
  ],
  evidence: syntheticCitations,
}

export const teacherOverviewFixture: TeacherOverviewViewModel = {
  fixtureLabel: SYNTHETIC_FIXTURE_LABEL,
  summary: [
    { label: '本周完成', value: '18', helper: '合成流程记录', tone: 'blue' },
    { label: '待关注流程', value: '3', helper: '需要支持性沟通', tone: 'teal' },
    { label: '等待复核', value: '1', helper: '安全流程已暂停', tone: 'amber' },
  ],
  trend: [
    { date: '周一', completed: 5, supported: 1 },
    { date: '周二', completed: 8, supported: 2 },
    { date: '周三', completed: 6, supported: 1 },
    { date: '周四', completed: 10, supported: 3 },
    { date: '周五', completed: 8, supported: 2 },
    { date: '周六', completed: 12, supported: 2 },
    { date: '周日', completed: 18, supported: 3 },
  ],
  attentionCases: [
    { caseId: 'CASE_demo_review_001', subjectId: 'SUBJ_demo_review_001', state: '等待人工复核', updatedAt: '今天 14:20', priority: 'high' },
    { caseId: 'CASE_demo_support_002', subjectId: 'SUBJ_demo_support_002', state: '建议支持性沟通', updatedAt: '昨天 16:40', priority: 'normal' },
    { caseId: 'CASE_demo_support_003', subjectId: 'SUBJ_demo_support_003', state: '已安排回看', updatedAt: '昨天 10:15', priority: 'normal' },
  ],
}

export const reviewCaseFixture: ReviewCase = {
  review_case_id: 'REVIEW_demo_001',
  review_id: 'REVIEW_EVENT_demo_001',
  case_id: 'CASE_demo_review_001',
  decision_id: 'DECISION_demo_001',
  trace_id: 'TRACE_demo_review_001',
  status: 'PENDING',
  reason_codes: ['HUMAN_REVIEW_REQUIRED'],
  priority: 'HIGH',
  assigned_role: 'REVIEWER',
  disclosure_policy: 'SUMMARY',
  subject_id: 'SUBJ_demo_review_001',
  report_id: 'REPORT_demo_review_001',
  created_at: '2026-09-05T05:20:00Z',
  updated_at: '2026-09-05T06:20:00Z',
  generationStatus: 'needs_review',
  summary: '安全流程要求对这份合成案例进行人工确认。普通个性化生成已暂停。',
  safeContext: '仅展示经过披露策略允许的摘要。原始回答、身份信息和完整模型上下文不在此页面。',
}

export const reviewEvidence = syntheticCitations.slice(0, 2)
