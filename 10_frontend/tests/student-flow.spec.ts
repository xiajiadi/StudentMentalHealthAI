import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { Assessment, ApiEnvelope } from '@/types/contracts'
import type { AssessmentState, ReportSummary } from '@/api/client'
import AssessmentResultView from '@/views/student/AssessmentResultView.vue'
import AssessmentView from '@/views/student/AssessmentView.vue'
import StudentAssessmentsView from '@/views/student/StudentAssessmentsView.vue'
import StudentHomeView from '@/views/student/StudentHomeView.vue'
import StudentResultView from '@/views/student/StudentResultView.vue'
import SupportChatView from '@/views/student/SupportChatView.vue'
import { useSessionStore } from '@/stores/session'

const api = vi.hoisted(() => ({
  getAssessmentResult: vi.fn(),
  listAssessments: vi.fn(),
  listReports: vi.fn(),
  startAssessment: vi.fn(),
  submitAssessmentResponse: vi.fn(),
  completeAssessment: vi.fn(),
  createSupport: vi.fn(),
  getStudentReport: vi.fn(),
}))

vi.mock('@/services/mock-api', () => ({ frontendApi: api }))

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

  it('教育支持页面说明 CLAIM_BOUNDARY 阻断且不提交消息或显示占位回答', async () => {
    api.listReports.mockResolvedValue(envelope({ items: [report], next_cursor: null }))
    const router = await makeRouter(`/student/support?assessment=${assessment.assessment_id}`)
    const wrapper = mount(SupportChatView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('独立支持生成暂不可用')
    expect(wrapper.text()).toContain('CLAIM_BOUNDARY')
    expect(wrapper.find('textarea').exists()).toBe(false)
    expect(api.createSupport).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('安全流程记录')
    expect(api.listReports).toHaveBeenCalledWith()
    await wrapper.get('.support-record-row .app-button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe(`/student/reports/${report.report_id}`)
  })

  it('支持历史失败显示不可用和重试', async () => {
    api.listReports.mockRejectedValueOnce(new Error('synthetic history unavailable'))
    const router = await makeRouter(`/student/support?assessment=${assessment.assessment_id}`)
    const wrapper = mount(SupportChatView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('支持记录暂时无法加载')
    expect(wrapper.text()).toContain('synthetic history unavailable')
    expect(api.createSupport).not.toHaveBeenCalled()
  })
})
