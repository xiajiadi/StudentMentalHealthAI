import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { Assessment, ApiEnvelope } from '@/types/contracts'
import type { AssessmentState, ReportSummary } from '@/api/client'
import AssessmentResultView from '@/views/student/AssessmentResultView.vue'
import AssessmentView from '@/views/student/AssessmentView.vue'
import StudentAssessmentsView from '@/views/student/StudentAssessmentsView.vue'
import StudentFeedbackView from '@/views/student/StudentFeedbackView.vue'
import StudentHomeView from '@/views/student/StudentHomeView.vue'
import StudentResultView from '@/views/student/StudentResultView.vue'
import SupportChatView from '@/views/student/SupportChatView.vue'
import { useSessionStore } from '@/stores/session'

const api = vi.hoisted(() => ({
  getAssessmentResult: vi.fn(),
  listAssessments: vi.fn(),
  listAssessmentEntries: undefined as undefined | ReturnType<typeof vi.fn>,
  listReports: vi.fn(),
  startAssessment: vi.fn(),
  submitAssessmentResponse: vi.fn(),
  completeAssessment: vi.fn(),
  createSupport: vi.fn(),
  getStudentReport: vi.fn(),
}))
const conversations = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  detail: vi.fn(),
  send: vi.fn(),
}))

vi.mock('@/services/mock-api', () => ({ frontendApi: api }))
vi.mock('@/services/independent-conversations', () => ({
  independentConversations: conversations,
  newConversationIdempotencyKey: vi.fn(() => 'synthetic-independent-key'),
}))

const envelope = <T>(data: T): ApiEnvelope<T> => ({ request_id: 'REQ_test', trace_id: 'TRACE_test', data })

const assessment: Assessment = {
  schema_version: 'assessment.v1',
  assessment_id: 'ASSESS_SYNTHETIC_001',
  subject_id: 'SYNTHETIC_STUDENT_DEMO',
  instrument: { instrument_id: 'CURRENT_SYNTHETIC_GRM', version: 'demo.v1' },
  population_scope: 'synthetic_demo',
  status: 'completed',
  dimensions: {},
  risk: { level: 'normal', need_human_review: false, reason_codes: [], ruleset_id: 'demo' },
  response_summary: { items_answered: 4, duration_seconds: null },
  provenance: { source_adapter: 'demo', adapter_version: '0.1.0', cat_engine_version: 'demo', item_bank_version: 'demo.v1' },
  timestamps: { started_at: '2026-10-07T00:00:00Z', completed_at: '2026-10-07T00:01:00Z' },
}

const report: ReportSummary = {
  report_id: 'REPORT_SYNTHETIC_001',
  assessment_id: assessment.assessment_id,
  status: 'needs_review',
  safety_action: 'CRISIS_ROUTE',
  created_at: '2026-10-07T00:02:00Z',
  citation_count: 0,
}

const conversationProjection = (conversationId: string) => ({
  conversationId,
  status: 'open' as const,
  createdAt: '2026-10-07T00:00:00Z',
  updatedAt: '2026-10-07T00:01:00Z',
})

const conversationMessage = (index: number, status: 'completed' | 'requested', text: string) => {
  const turnId = `TURN_SYNTHETIC_${String(index).padStart(3, '0')}`
  return {
    messageId: `MSG_SYNTHETIC_${String(index).padStart(3, '0')}`,
    sequence: index,
    createdAt: `2026-10-07T00:${String(Math.floor(index / 60)).padStart(2, '0')}:${String(index % 60).padStart(2, '0')}Z`,
    turnId,
    role: 'student' as const,
    text,
    content: null,
    turn: {
      turnId,
      status,
      action: status === 'requested' ? null : 'ALLOW',
      createdAt: '2026-10-07T00:00:00Z',
      completedAt: status === 'requested' ? null : '2026-10-07T00:01:00Z',
      citations: [],
    },
  }
}

const conversationDetail = (conversationId: string, messages: ReturnType<typeof conversationMessage>[], offset: number, totalTurns: number) => ({
  conversation: conversationProjection(conversationId),
  messages,
  offset,
  limit: 20,
  totalTurns,
  hasMore: offset + 20 < totalTurns,
})

const deferred = <T,>() => {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

const question = { item_id: 'ITEM_demo_002', prompt: '你最近是否容易开始一项学习任务？', options: [{ value: '1', label: '不太容易' }, { value: '2', label: '比较容易' }] }
const assessmentState = (overrides: Partial<AssessmentState> = {}): AssessmentState => ({
  assessment_id: assessment.assessment_id,
  subject_id: assessment.subject_id,
  status: 'in_progress',
  current_index: 1,
  answered_count: 1,
  can_complete: false,
  max_items: 4,
  question,
  ...overrides,
})

const makeRouter = async (path: string) => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/student/assessment/:id/result', component: AssessmentResultView },
      { path: '/student/assessment/:id', component: AssessmentView },
      { path: '/student/assessment', component: AssessmentView },
      { path: '/student/assessments', component: StudentAssessmentsView },
      { path: '/student/home', component: StudentHomeView },
      { path: '/student/history', component: StudentHomeView },
      { path: '/student/reports', component: StudentResultView },
      { path: '/student/reports/:id', component: StudentResultView },
      { path: '/student/feedback', component: StudentFeedbackView },
      { path: '/student/support', component: SupportChatView },
    ],
  })
  await router.push(path)
  await router.isReady()
  return router
}

describe('学生演示闭环页面', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listAssessmentEntries = undefined
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      writable: true,
      value: vi.fn((media: string) => ({
        matches: false,
        media,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    })
    api.getAssessmentResult.mockResolvedValue(envelope(assessment))
    api.listAssessments.mockResolvedValue(envelope([]))
    api.listReports.mockResolvedValue(envelope({ items: [], next_cursor: null }))
    api.startAssessment.mockResolvedValue(envelope(assessmentState({ current_index: 0, answered_count: 0, question: { ...question, item_id: 'ITEM_demo_001' } })))
    api.submitAssessmentResponse.mockResolvedValue(envelope(assessmentState({ can_complete: true, answered_count: 2, question: { ...question, item_id: 'ITEM_demo_003' } })))
    api.completeAssessment.mockResolvedValue(envelope(assessment))
    api.getStudentReport.mockRejectedValue(new Error('synthetic report unavailable'))
    conversations.list.mockResolvedValue({ items: [], total: 0, hasMore: false })
    conversations.create.mockResolvedValue({
      conversationId: 'CONV_SYNTHETIC_001', status: 'open',
      createdAt: '2026-10-07T00:00:00Z', updatedAt: '2026-10-07T00:00:00Z',
    })
    conversations.detail.mockResolvedValue({
      conversation: {
        conversationId: 'CONV_SYNTHETIC_001', status: 'open',
        createdAt: '2026-10-07T00:00:00Z', updatedAt: '2026-10-07T00:00:00Z',
      }, messages: [], offset: 0, limit: 20, totalTurns: 0, hasMore: false,
    })
    conversations.send.mockResolvedValue({
      turnId: 'TURN_SYNTHETIC_001', status: 'requested', replayed: false,
      action: null, completedAt: null, content: null, citations: [],
    })
  })

  it('自主测评使用进度列表恢复会话，不读取完整测评列表', async () => {
    api.listAssessmentEntries = vi.fn().mockResolvedValue(envelope([{
      assessment_id: assessment.assessment_id, status: 'in_progress', items_answered: 1,
      started_at: '2026-10-07T00:00:00Z', completed_at: null,
    }]))
    const router = await makeRouter('/student/assessment')
    const wrapper = mount(AssessmentView, { global: { plugins: [router, createPinia()] } })
    await flushPromises()
    expect(api.listAssessmentEntries).toHaveBeenCalledWith({ status: 'in_progress', limit: 1 })
    expect(api.listAssessments).not.toHaveBeenCalled()
    expect(api.startAssessment).toHaveBeenCalledWith(assessment.assessment_id)
    wrapper.unmount()
  })

  it('首页根据登录名称问候，并展示不可点击的四卡片功能介绍', async () => {
    api.listAssessments.mockResolvedValue(envelope([{ ...assessment, status: 'in_progress' }]))
    api.listReports.mockResolvedValue(envelope({ items: [report], next_cursor: null }))
    const router = await makeRouter('/student/home')
    const pinia = createPinia()
    useSessionStore(pinia).signIn({ userId: 'student_01', role: 'student', subjectId: 'SYNTHETIC_STUDENT_DEMO', displayName: 'Jack', initials: 'J' })
    const wrapper = mount(StudentHomeView, { global: { plugins: [router, pinia] } })
    await flushPromises()

    expect(wrapper.text()).toContain('Welcome back Jack')
    expect(wrapper.get('.student-feature__title').text()).toBe('Build a better understanding of yourself with AI.')
    expect(wrapper.findAll('.student-feature-card')).toHaveLength(4)
    expect(wrapper.findAll('.student-carousel__dots button')).toHaveLength(5)
    expect(wrapper.text()).toContain('从一次测评开始')
    expect(wrapper.text()).not.toContain('了解当前支持功能')
    expect(wrapper.text()).not.toContain('关于演示数据')
    expect(wrapper.find('.student-feature-card button').exists()).toBe(false)
    expect(wrapper.find('.student-feature-card a').exists()).toBe(false)
    await wrapper.get('.student-feature__action').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/student/assessments')
    wrapper.unmount()

    const historyRouter = await makeRouter('/student/history')
    const history = mount(StudentHomeView, { global: { plugins: [historyRouter, createPinia()] } })
    await flushPromises()
    expect(history.text()).toContain('测评与支持记录')
    expect(history.text()).toContain('安全流程记录')
    expect(history.find('.history-section:last-child .app-button').exists()).toBe(false)
    expect(historyRouter.currentRoute.value.fullPath).toBe('/student/history')
  })

  it.each(['SYNTHETIC_STUDENT_DEMO', 'USER_demo_student'])('技术账号标识 %s 不进入首页问候', async (identifier) => {
    const router = await makeRouter('/student/home')
    const pinia = createPinia()
    useSessionStore(pinia).signIn({
      userId: identifier, role: 'student', subjectId: 'SYNTHETIC_STUDENT_DEMO',
      displayName: identifier, initials: 'S',
    })
    const wrapper = mount(StudentHomeView, { global: { plugins: [router, pinia] } })
    await flushPromises()

    const welcomeTitle = wrapper.get('#student-home-title')
    expect(welcomeTitle.text()).toBe('Welcome back 同学')
    expect(wrapper.text()).not.toContain(identifier)
    wrapper.unmount()
  })

  it('保留较长的人类显示名称，并将欢迎标题限制在可换行的两行内', async () => {
    const longDisplayName = 'AlexandriaVeryLongHumanReadableStudentDisplayNameThatNeedsWrapping'
    const router = await makeRouter('/student/home')
    const pinia = createPinia()
    useSessionStore(pinia).signIn({
      userId: 'student_01', role: 'student', subjectId: 'SYNTHETIC_STUDENT_DEMO',
      displayName: longDisplayName, initials: 'A',
    })
    const wrapper = mount(StudentHomeView, { global: { plugins: [router, pinia] } })
    await flushPromises()

    const welcomeTitle = wrapper.get('#student-home-title')
    expect(welcomeTitle.text()).toBe(`Welcome back ${longDisplayName}`)
    expect(welcomeTitle.classes()).toContain('student-carousel__welcome-title')
    wrapper.unmount()
  })

  it('首页不请求测评列表，历史页以metadata显示待开始和UTC记录', async () => {
    api.listAssessmentEntries = vi.fn().mockResolvedValue(envelope([
      {
        assessment_id: 'ASSESS_CREATED_METADATA', status: 'created', items_answered: 0,
        started_at: null, completed_at: null,
      },
      {
        assessment_id: 'ASSESS_PROGRESS_METADATA', status: 'in_progress', items_answered: 2,
        started_at: '2026-10-07T00:00:00Z', completed_at: null,
      },
    ]))
    api.listAssessments.mockResolvedValue(envelope([{ ...assessment, status: 'completed' }]))

    const homeRouter = await makeRouter('/student/home')
    const home = mount(StudentHomeView, { global: { plugins: [homeRouter, createPinia()] } })
    await flushPromises()
    expect(api.listAssessmentEntries).not.toHaveBeenCalled()
    expect(api.listAssessments).not.toHaveBeenCalled()
    home.unmount()

    const historyRouter = await makeRouter('/student/history')
    const history = mount(StudentHomeView, { global: { plugins: [historyRouter, createPinia()] } })
    await flushPromises()
    expect(api.listAssessmentEntries).toHaveBeenCalledWith({ limit: 30, skip: 0 })
    expect(api.listAssessments).not.toHaveBeenCalled()
    const rows = history.findAll('.history-row')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.text()).toContain('待开始')
    expect(rows[0]!.text()).toContain('0 项已记录')
    expect(rows[0]!.text()).toContain('尚未开始')
    expect(rows[0]!.text()).not.toContain('进行中')
    expect(rows[1]!.text()).toContain('进行中')
    expect(rows[1]!.text()).toContain('2 项已记录')
    expect(rows[1]!.text()).toContain('2026年10月')
    history.unmount()
  })

  it('历史metadata按30分页、失败保留旧行并去重追加', async () => {
    const firstPage = Array.from({ length: 30 }, (_, index) => ({
      assessment_id: `ASSESS_HISTORY_${index}`,
      status: 'completed' as const,
      items_answered: index,
      started_at: null,
      completed_at: '2026-10-07T00:00:00Z',
    }))
    const duplicate = firstPage[29]!
    const finalPage = [duplicate, {
      assessment_id: 'ASSESS_HISTORY_30', status: 'created' as const, items_answered: 0,
      started_at: null, completed_at: null,
    }]
    let pageCalls = 0
    api.listAssessmentEntries = vi.fn().mockImplementation(({ skip }: { skip: number }) => {
      if (skip === 0) return Promise.resolve(envelope(firstPage))
      pageCalls += 1
      if (pageCalls === 1) return Promise.reject(new Error('synthetic metadata page outage'))
      return Promise.resolve(envelope(finalPage))
    })
    const router = await makeRouter('/student/history')
    const wrapper = mount(StudentHomeView, { global: { plugins: [router, createPinia()] } })
    await flushPromises()
    expect(wrapper.findAll('.history-row')).toHaveLength(30)
    expect(wrapper.text()).toContain('已显示 30 条')
    await wrapper.get('.history-load-more .app-button').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.history-row')).toHaveLength(30)
    expect(wrapper.get('[role="alert"]').text()).toContain('暂时无法加载更多测评记录')
    expect(wrapper.get('[role="alert"]').text()).not.toContain('synthetic metadata page outage')
    await wrapper.get('.history-load-more .app-button').trigger('click')
    await flushPromises()
    expect(api.listAssessmentEntries).toHaveBeenNthCalledWith(2, { limit: 30, skip: 30 })
    expect(api.listAssessmentEntries).toHaveBeenNthCalledWith(3, { limit: 30, skip: 30 })
    expect(wrapper.findAll('.history-row')).toHaveLength(31)
    expect(wrapper.findAll('.history-row').filter((row) => row.text().includes('尚未开始的合成测评'))).toHaveLength(1)
    expect(wrapper.text()).toContain('待开始')
    expect(api.listAssessments).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('反馈只取completed metadata并支持更多页，metadata失败不回退旧测评接口', async () => {
    const firstPage = Array.from({ length: 30 }, (_, index) => ({
      assessment_id: `ASSESS_FEEDBACK_${index}`, status: 'completed' as const,
      items_answered: 4, started_at: null, completed_at: '2026-10-07T00:01:00Z',
    }))
    api.listAssessmentEntries = vi.fn()
      .mockResolvedValueOnce(envelope(firstPage))
      .mockResolvedValueOnce(envelope([{
        assessment_id: 'ASSESS_FEEDBACK_30', status: 'completed', items_answered: 3,
        started_at: null, completed_at: null,
      }]))
    const router = await makeRouter('/student/feedback')
    const wrapper = mount(StudentFeedbackView, { global: { plugins: [router, createPinia()] } })
    await flushPromises()
    expect(api.listAssessmentEntries).toHaveBeenCalledWith({ limit: 30, skip: 0, status: 'completed' })
    expect(wrapper.findAll('.feedback-section--completed .feedback-row')).toHaveLength(30)
    await wrapper.get('.assessment-load-more .app-button').trigger('click')
    await flushPromises()
    expect(api.listAssessmentEntries).toHaveBeenNthCalledWith(2, { limit: 30, skip: 30, status: 'completed' })
    expect(wrapper.findAll('.feedback-section--completed .feedback-row')).toHaveLength(31)
    expect(api.listAssessments).not.toHaveBeenCalled()
    wrapper.unmount()

    api.listAssessmentEntries = vi.fn().mockRejectedValue(new Error('synthetic metadata outage'))
    const failedRouter = await makeRouter('/student/feedback')
    const failed = mount(StudentFeedbackView, { global: { plugins: [failedRouter, createPinia()] } })
    await flushPromises()
    expect(api.listAssessmentEntries).toHaveBeenCalledTimes(1)
    expect(api.listAssessments).not.toHaveBeenCalled()
    expect(failed.text()).toContain('测评反馈暂时无法加载')
    expect(failed.findAll('.feedback-section--completed .feedback-row')).toHaveLength(0)
    failed.unmount()
  })

  it('我的测评以真实会话生成三列网格和列表视图，并保留继续与结果入口', async () => {
    const createdAssessment: Assessment = {
      ...assessment,
      assessment_id: 'ASSESSMENT_CREATED_001',
      status: 'created',
      response_summary: { items_answered: 0, duration_seconds: null },
      timestamps: { started_at: null, completed_at: null },
    }
    const inProgressAssessment: Assessment = { ...assessment, assessment_id: 'ASSESSMENT_PROGRESS_001', status: 'in_progress' }
    api.listAssessments.mockResolvedValue(envelope([createdAssessment, inProgressAssessment, assessment]))
    const router = await makeRouter('/student/assessments')
    const wrapper = mount(StudentAssessmentsView, { global: { plugins: [router, createPinia()] } })
    await flushPromises()

    expect(wrapper.findAll('.assessment-card')).toHaveLength(3)
    expect(wrapper.find('.assessment-card__brand').exists()).toBe(false)
    expect(wrapper.find('.assessment-card__poster-title').exists()).toBe(false)
    expect(wrapper.get('.assessment-card__art').attributes('src')).toBe('/assets/psynova/original-covers/flow-01.svg')
    expect(wrapper.get('.assessment-cards').classes()).toContain('assessment-cards--grid')
    await wrapper.get('[aria-label="列表显示"]').trigger('click')
    expect(wrapper.get('.assessment-cards').classes()).toContain('assessment-cards--list')
    await wrapper.get('[role="group"][aria-label="按状态筛选测评"] button:nth-child(3)').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.assessment-card')).toHaveLength(1)
    await wrapper.get('.assessment-card .app-button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/student/assessment/ASSESSMENT_PROGRESS_001')
    wrapper.unmount()

    api.listAssessments.mockResolvedValue(envelope([assessment]))
    const completedRouter = await makeRouter('/student/assessments')
    const completedWrapper = mount(StudentAssessmentsView, { global: { plugins: [completedRouter, createPinia()] } })
    await flushPromises()
    await completedWrapper.get('.assessment-card .app-button').trigger('click')
    await flushPromises()
    expect(completedRouter.currentRoute.value.fullPath).toBe(`/student/assessment/${assessment.assessment_id}/result`)
    completedWrapper.unmount()
  })

  it('我的测评直接呈现学校metadata，并把空开始时间显示为尚未开始', async () => {
    api.listAssessmentEntries = vi.fn().mockResolvedValue(envelope([{
      assessment_id: 'ASSESS_CREATED_METADATA', status: 'created', items_answered: 0,
      started_at: null, completed_at: null,
    }]))
    const router = await makeRouter('/student/assessments')
    const wrapper = mount(StudentAssessmentsView, { global: { plugins: [router, createPinia()] } })
    await flushPromises()

    expect(api.listAssessmentEntries).toHaveBeenCalledWith({ limit: 30, skip: 0, status: undefined })
    expect(wrapper.text()).toContain('尚未开始')
    expect(wrapper.text()).toContain('0 项已记录')
    expect(wrapper.get('.assessment-card .app-button').text()).toContain('开始测评')
    expect(router.currentRoute.value.fullPath).toBe('/student/assessments')
    wrapper.unmount()
  })

  it('学校metadata接口失败时显示列表错误，不回退到完整测评列表', async () => {
    api.listAssessmentEntries = vi.fn().mockRejectedValue(new Error('synthetic metadata outage'))
    const router = await makeRouter('/student/assessments')
    const wrapper = mount(StudentAssessmentsView, { global: { plugins: [router, createPinia()] } })
    await flushPromises()

    expect(api.listAssessmentEntries).toHaveBeenCalledTimes(1)
    expect(api.listAssessments).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('测评列表暂时无法加载')
    expect(wrapper.findAll('.assessment-card')).toHaveLength(0)
    wrapper.unmount()
  })

  it('我的测评横幅按钮进入现有测评流程', async () => {
    const router = await makeRouter('/student/assessments')
    const wrapper = mount(StudentAssessmentsView, { global: { plugins: [router, createPinia()] } })
    await flushPromises()
    await wrapper.get('.assessment-hero .app-button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/student/assessment')
  })

  it('历史页面为进行中和已完成记录提供真实的继续或结果导航', async () => {
    api.listAssessments.mockResolvedValue(envelope([{ ...assessment, status: 'in_progress' }]))
    const router = await makeRouter('/student/history')
    const wrapper = mount(StudentHomeView, { global: { plugins: [router, createPinia()] } })
    await flushPromises()

    await wrapper.get('.history-row .app-button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe(`/student/assessment/${assessment.assessment_id}`)
  })

  it('继续已保存测评，保存回答后同时提供继续和完成选项', async () => {
    api.listAssessments.mockResolvedValue(envelope([{ ...assessment, status: 'in_progress' }]))
    const router = await makeRouter('/student/assessment')
    const wrapper = mount(AssessmentView, { global: { plugins: [router, createPinia()] } })
    await flushPromises()

    expect(api.startAssessment).toHaveBeenCalledWith(assessment.assessment_id)
    await wrapper.get('[role="radio"]').trigger('click')
    await wrapper.get('button.app-button--primary').trigger('click')
    await flushPromises()

    expect(api.submitAssessmentResponse).toHaveBeenCalledWith(assessment.assessment_id, 'ITEM_demo_001', '1')
    expect(wrapper.text()).toContain('下一题')
    expect(wrapper.get('[aria-label="完成测评"]').text()).toBe('完成')
    await wrapper.get('[aria-label="完成测评"]').trigger('click')
    await flushPromises()
    expect(api.completeAssessment).toHaveBeenCalledWith(assessment.assessment_id)
    expect(router.currentRoute.value.fullPath).toBe(`/student/assessment/${assessment.assessment_id}/result`)
  })

  it('没有下一题但可完成时仍显示明确的完成操作', async () => {
    api.startAssessment.mockResolvedValue(envelope(assessmentState({ can_complete: true, question: null })))
    const router = await makeRouter(`/student/assessment/${assessment.assessment_id}`)
    const wrapper = mount(AssessmentView, { global: { plugins: [router, createPinia()] } })
    await flushPromises()

    expect(wrapper.get('#assessment-complete-title').text()).toBe('测评可结束')
    await wrapper.get('button.app-button--primary').trigger('click')
    await flushPromises()
    expect(api.completeAssessment).toHaveBeenCalledWith(assessment.assessment_id)
  })

  it('完成前保存失败时不结束测评或跳转结果页', async () => {
    api.startAssessment.mockResolvedValue(envelope(assessmentState({ can_complete: true })))
    api.submitAssessmentResponse.mockRejectedValueOnce(new Error('保存失败'))
    const router = await makeRouter(`/student/assessment/${assessment.assessment_id}`)
    const wrapper = mount(AssessmentView, { global: { plugins: [router, createPinia()] } })
    await flushPromises()
    await wrapper.get('[role="radio"]').trigger('click')
    await wrapper.get('[aria-label="完成测评"]').trigger('click')
    await flushPromises()
    expect(api.submitAssessmentResponse).toHaveBeenCalledWith(assessment.assessment_id, question.item_id, '1')
    expect(api.completeAssessment).not.toHaveBeenCalled()
    expect(router.currentRoute.value.fullPath).toBe(`/student/assessment/${assessment.assessment_id}`)
    expect(wrapper.text()).toContain('保存失败')
    wrapper.unmount()
  })

  it('保存后服务端取消可完成状态时不调用结束接口', async () => {
    api.startAssessment.mockResolvedValue(envelope(assessmentState({ can_complete: true })))
    api.submitAssessmentResponse.mockResolvedValueOnce(envelope(assessmentState({ can_complete: false, answered_count: 2 })))
    const router = await makeRouter(`/student/assessment/${assessment.assessment_id}`)
    const wrapper = mount(AssessmentView, { global: { plugins: [router, createPinia()] } })
    await flushPromises()
    await wrapper.get('[role="radio"]').trigger('click')
    await wrapper.get('[aria-label="完成测评"]').trigger('click')
    await flushPromises()
    expect(api.submitAssessmentResponse).toHaveBeenCalled()
    expect(api.completeAssessment).not.toHaveBeenCalled()
    expect(wrapper.find('[aria-label="完成测评"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('报告详情不会伪造缺失的 ID，并会显示服务端错误说明', async () => {
    const router = await makeRouter('/student/reports')
    const wrapper = mount(StudentResultView, { global: { plugins: [router, createPinia()] } })
    await flushPromises()
    expect(wrapper.text()).toContain('报告标识不可用')
    wrapper.unmount()

    const reportRouter = await makeRouter('/student/reports/REPORT_SYNTHETIC_404')
    const reportWrapper = mount(StudentResultView, { global: { plugins: [reportRouter, createPinia()] } })
    await flushPromises()
    expect(api.getStudentReport).toHaveBeenCalledWith('REPORT_SYNTHETIC_404')
    expect(reportWrapper.text()).toContain('synthetic report unavailable')
  })

  it('结果页明确显示合成、教育用途和非诊断边界', async () => {
    const router = await makeRouter(`/student/assessment/${assessment.assessment_id}/result`)
    const wrapper = mount(AssessmentResultView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('SYNTHETIC')
    expect(wrapper.text()).toContain('非诊断')
    expect(wrapper.text()).toContain('已记录 4 项回答')
    expect(wrapper.text()).not.toContain('theta')
    expect(wrapper.text()).toContain('CLAIM_BOUNDARY')
    await wrapper.get('.assessment-result__actions .app-button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/student/support')
  })

  it('教育支持可独立新建会话并保留教育用途与隐私边界', async () => {
    api.listReports.mockResolvedValue(envelope({ items: [report], next_cursor: null }))
    const router = await makeRouter(`/student/support?assessment=${assessment.assessment_id}`)
    const wrapper = mount(SupportChatView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('这是一般教育支持')
    expect(wrapper.text()).toContain('对话不会读取测评答案')
    expect(wrapper.find('textarea').exists()).toBe(false)
    await wrapper.get('button[aria-label="新建会话"]').trigger('click')
    await flushPromises()
    expect(conversations.create).toHaveBeenCalledWith('synthetic-independent-key')
    expect(wrapper.find('textarea').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('CLAIM_BOUNDARY')
    conversations.send.mockRejectedValueOnce(new Error('synthetic network timeout'))
    await wrapper.get('textarea').setValue('如何安排复习？')
    await wrapper.get('.conversation-composer').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('synthetic network timeout')
    expect(wrapper.text()).toContain('本次重试会沿用相同消息请求')
    const firstRequest = conversations.send.mock.calls[0]
    expect(firstRequest).toEqual(['CONV_SYNTHETIC_001', '如何安排复习？', 'synthetic-independent-key'])
    await wrapper.get('.conversation-composer').trigger('submit')
    await flushPromises()
    expect(conversations.send).toHaveBeenCalledTimes(2)
    expect(conversations.send.mock.calls[1]).toEqual(firstRequest)
    expect(wrapper.text()).toContain('消息已收到，回复仍在处理中')
    expect(wrapper.text()).not.toContain('synthetic network timeout')
    expect(api.createSupport).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('安全流程记录')
    expect(api.listReports).toHaveBeenCalledWith()
    await wrapper.get('.support-record-row .app-button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe(`/student/reports/${report.report_id}`)
  })

  it('快速切换会话时丢弃较早详情请求的迟到结果与错误', async () => {
    const conversationA = conversationProjection('CONV_SYNTHETIC_A')
    const conversationB = conversationProjection('CONV_SYNTHETIC_B')
    const detailARequests = [deferred<ReturnType<typeof conversationDetail>>(), deferred<ReturnType<typeof conversationDetail>>() ]
    const detailBRequests = [deferred<ReturnType<typeof conversationDetail>>(), deferred<ReturnType<typeof conversationDetail>>() ]
    const requestIndexes = new Map<string, number>()
    conversations.list.mockResolvedValue({ items: [conversationA, conversationB], total: 2, hasMore: false })
    conversations.detail.mockImplementation((conversationId: string) => {
      const requests = conversationId === conversationA.conversationId ? detailARequests : detailBRequests
      const index = requestIndexes.get(conversationId) ?? 0
      requestIndexes.set(conversationId, index + 1)
      return requests[index]!.promise
    })
    const router = await makeRouter('/student/support')
    const wrapper = mount(SupportChatView, { global: { plugins: [router] } })
    await flushPromises()

    const conversationButtons = wrapper.findAll('.conversation-list__item')
    await conversationButtons[0]!.trigger('click')
    await conversationButtons[1]!.trigger('click')
    detailBRequests[0]!.resolve(conversationDetail(conversationB.conversationId, [conversationMessage(2, 'completed', 'B 会话正文')], 0, 1))
    await flushPromises()
    detailARequests[0]!.resolve(conversationDetail(conversationA.conversationId, [conversationMessage(1, 'completed', '过期 A 会话正文')], 0, 1))
    await flushPromises()

    await conversationButtons[0]!.trigger('click')
    await conversationButtons[1]!.trigger('click')
    detailARequests[1]!.reject(new Error('stale conversation A error'))
    detailBRequests[1]!.resolve(conversationDetail(conversationB.conversationId, [conversationMessage(2, 'completed', 'B 会话正文')], 0, 1))
    await flushPromises()

    expect(wrapper.text()).toContain('B 会话正文')
    expect(wrapper.text()).not.toContain('过期 A 会话正文')
    expect(wrapper.text()).not.toContain('stale conversation A error')
    expect(wrapper.get('.conversation-list__item--selected').text()).toContain('会话 2')
    wrapper.unmount()
  })

  it('REQUESTED 轮次只允许手动读取状态，不能发送下一条消息', async () => {
    const conversationId = 'CONV_SYNTHETIC_PENDING'
    const pendingDetail = conversationDetail(conversationId, [conversationMessage(1, 'requested', '处理中消息')], 0, 1)
    conversations.list.mockResolvedValue({ items: [pendingDetail.conversation], total: 1, hasMore: false })
    conversations.detail.mockResolvedValue(pendingDetail)
    const router = await makeRouter('/student/support')
    const wrapper = mount(SupportChatView, { global: { plugins: [router] } })
    await flushPromises()
    await wrapper.get('.conversation-list__item').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('上一条消息仍在处理中')
    expect(wrapper.text()).toContain('刷新只读取已保存状态，不会重新发送消息')
    expect(wrapper.get('.conversation-composer button').attributes('disabled')).toBeDefined()
    await wrapper.get('button[aria-label="刷新会话"]').trigger('click')
    await flushPromises()
    await wrapper.get('.conversation-composer').trigger('submit')
    expect(conversations.detail).toHaveBeenCalledTimes(2)
    expect(conversations.send).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('超过一页后发送会打开最新页，并可向前加载较早对话', async () => {
    const conversationId = 'CONV_SYNTHETIC_LONG'
    const item = conversationProjection(conversationId)
    const firstTwenty = Array.from({ length: 20 }, (_, index) => conversationMessage(index + 1, 'completed', `第 ${index + 1} 轮`))
    const firstPage = conversationDetail(conversationId, firstTwenty, 0, 20)
    const latestPage = conversationDetail(conversationId, [conversationMessage(21, 'requested', '最新第 21 轮')], 20, 21)
    conversations.list.mockResolvedValue({ items: [item], total: 1, hasMore: false })
    conversations.detail
      .mockResolvedValueOnce(firstPage)
      .mockResolvedValueOnce(latestPage)
      .mockResolvedValueOnce(firstPage)
    const router = await makeRouter('/student/support')
    const wrapper = mount(SupportChatView, { global: { plugins: [router] } })
    await flushPromises()
    await wrapper.get('.conversation-list__item').trigger('click')
    await flushPromises()
    await wrapper.get('textarea').setValue('继续安排复习')
    await wrapper.get('.conversation-composer').trigger('submit')
    await flushPromises()

    expect(conversations.detail.mock.calls.map(([id, offset]) => [id, offset])).toEqual([
      [conversationId, 0], [conversationId, 20],
    ])
    expect(wrapper.text()).toContain('最新第 21 轮')
    expect(wrapper.text()).toContain('加载更早的对话')
    await wrapper.get('.conversation-thread button').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.conversation-message')).toHaveLength(21)
    expect(wrapper.text()).toContain('第 20 轮')
    expect(conversations.send).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('测评关联历史失败显示不可用和重试', async () => {
    api.listReports.mockRejectedValueOnce(new Error('synthetic history unavailable'))
    const router = await makeRouter(`/student/support?assessment=${assessment.assessment_id}`)
    const wrapper = mount(SupportChatView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('既有记录暂时无法加载')
    expect(wrapper.text()).toContain('synthetic history unavailable')
    expect(api.createSupport).not.toHaveBeenCalled()
  })
})
