import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { Assessment, ApiEnvelope } from '@/types/contracts'
import type { AssessmentState, ReportSummary } from '@/api/client'
import AssessmentResultView from '@/views/student/AssessmentResultView.vue'
import AssessmentView from '@/views/student/AssessmentView.vue'
import StudentHomeView from '@/views/student/StudentHomeView.vue'
import StudentResultView from '@/views/student/StudentResultView.vue'
import SupportChatView from '@/views/student/SupportChatView.vue'

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
    api.getAssessmentResult.mockResolvedValue(envelope(assessment))
    api.listAssessments.mockResolvedValue(envelope([]))
    api.listReports.mockResolvedValue(envelope({ items: [], next_cursor: null }))
    api.startAssessment.mockResolvedValue(envelope(assessmentState({ current_index: 0, answered_count: 0, question: { ...question, item_id: 'ITEM_demo_001' } })))
    api.submitAssessmentResponse.mockResolvedValue(envelope(assessmentState({ can_complete: true, answered_count: 2, question: { ...question, item_id: 'ITEM_demo_003' } })))
    api.completeAssessment.mockResolvedValue(envelope(assessment))
    api.getStudentReport.mockRejectedValue(new Error('synthetic report unavailable'))
  })

  it('首页使用服务端记录提供测评入口、教育支持入口和历史导航', async () => {
    api.listAssessments.mockResolvedValue(envelope([{ ...assessment, status: 'in_progress' }]))
    api.listReports.mockResolvedValue(envelope({ items: [report], next_cursor: null }))
    const router = await makeRouter('/student/home')
    const wrapper = mount(StudentHomeView, { global: { plugins: [router, createPinia()] } })
    await flushPromises()

    expect(wrapper.text()).toContain('给自己一点时间')
    expect(wrapper.text()).toContain('继续测评')
    expect(wrapper.text()).toContain('教育支持')
    await wrapper.get('.student-hero__actions .app-button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe(`/student/assessment/${assessment.assessment_id}`)
    wrapper.unmount()

    const historyRouter = await makeRouter('/student/history')
    const history = mount(StudentHomeView, { global: { plugins: [historyRouter, createPinia()] } })
    await flushPromises()
    expect(history.text()).toContain('测评与支持记录')
    expect(history.text()).toContain('安全流程记录')
    await history.get('.history-section:last-child .app-button').trigger('click')
    await flushPromises()
    expect(historyRouter.currentRoute.value.fullPath).toBe(`/student/reports/${report.report_id}`)
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
    expect(wrapper.text()).toContain('保存当前作答并继续')
    expect(wrapper.text()).toContain('保存并继续回答')
    expect(wrapper.text()).toContain('完成并查看结构')
  })

  it('没有下一题但可完成时仍显示明确的完成操作', async () => {
    api.startAssessment.mockResolvedValue(envelope(assessmentState({ can_complete: true, question: null })))
    const router = await makeRouter(`/student/assessment/${assessment.assessment_id}`)
    const wrapper = mount(AssessmentView, { global: { plugins: [router, createPinia()] } })
    await flushPromises()

    expect(wrapper.text()).toContain('本次合成测评已经可以结束')
    expect(wrapper.text()).toContain('完成并查看结构')
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
