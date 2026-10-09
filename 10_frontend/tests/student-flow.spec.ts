import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { Assessment, ApiEnvelope } from '@/types/contracts'
import type { AssessmentState, ReportSummary, SupportResult } from '@/api/client'
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

const support = (overrides: Partial<SupportResult> = {}): SupportResult => ({
  status: 'needs_review',
  safety_action: 'CRISIS_ROUTE',
  normal_generation: false,
  generation: {},
  report_id: report.report_id,
  content: null,
  citations: [],
  review_reference: 'REVIEW_SYNTHETIC_001',
  crisis_response: null,
  trace_id: 'TRACE_support',
  synthetic_fixture_only: true,
  integration_labels: { SAFETY: 'REAL_HTTP' },
  ...overrides,
})

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
    api.createSupport.mockResolvedValue(envelope(support()))
    api.getStudentReport.mockRejectedValue(new Error('synthetic report unavailable'))
  })

  it('学生空间从服务端记录中提供继续入口并分开展示测评历史和报告历史', async () => {
    api.listAssessments.mockResolvedValue(envelope([{ ...assessment, status: 'in_progress' }]))
    api.listReports.mockResolvedValue(envelope({ items: [report], next_cursor: null }))
    const router = await makeRouter('/student/home')
    const wrapper = mount(StudentHomeView, { global: { plugins: [router, createPinia()] } })
    await flushPromises()

    expect(wrapper.text()).toContain('有一项测评尚未完成')
    expect(wrapper.text()).toContain('继续测评')
    expect(wrapper.text()).toContain('测评记录')
    expect(wrapper.text()).toContain('对话与报告')
    expect(wrapper.text()).toContain(report.report_id)
  })

  it('学生空间明确显示演示数据重置受阻且不会删除已有记录', async () => {
    const router = await makeRouter('/student/home')
    const wrapper = mount(StudentHomeView, { global: { plugins: [router, createPinia()] } })
    await flushPromises()

    const resetStatus = wrapper.get('.student-reset__status')
    expect(resetStatus.attributes('role')).toBe('status')
    expect(resetStatus.text()).toContain('BLOCKED · 暂不可用')
    expect(resetStatus.text()).toContain('返回退出码 2')
    expect(resetStatus.text()).toContain('不会停止服务、连接数据库或删除数据')
    expect(resetStatus.text()).toContain('旧演示工作区和记录会保留')
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
  })

  it('危机路由显示阻断状态，不显示普通生成内容', async () => {
    api.listReports.mockResolvedValue(envelope({ items: [report], next_cursor: null }))
    const router = await makeRouter(`/student/support?assessment=${assessment.assessment_id}`)
    const wrapper = mount(SupportChatView, { global: { plugins: [router] } })
    await flushPromises()
    await wrapper.get('textarea').setValue('演示请求')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('已进入安全流程')
    expect(wrapper.text()).toContain('CRISIS_ROUTE')
    expect(wrapper.text()).not.toContain('模型回答')
    expect(wrapper.text()).toContain(report.report_id)
  })

  it('支持历史失败显示不可用和重试，支持请求失败保留草稿', async () => {
    api.listReports.mockRejectedValueOnce(new Error('synthetic history unavailable'))
    api.createSupport.mockRejectedValue(new Error('synthetic support unavailable'))
    const router = await makeRouter(`/student/support?assessment=${assessment.assessment_id}`)
    const wrapper = mount(SupportChatView, { global: { plugins: [router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('历史记录暂时无法加载')
    expect(wrapper.text()).toContain('synthetic history unavailable')
    expect(wrapper.text()).not.toContain('还没有已保存的支持报告')

    await wrapper.get('textarea').setValue('这是要保留以便重试的演示问题')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('支持请求未完成')
    expect(wrapper.text()).toContain('synthetic support unavailable')
    expect((wrapper.get('textarea').element as { value: string }).value).toBe('这是要保留以便重试的演示问题')
  })

  it('来源标签只说明演示资料，不声称经过人工审核', async () => {
    api.createSupport.mockResolvedValue(envelope(support({
      status: 'generated',
      safety_action: 'PROCEED_WITH_BOUNDARY',
      normal_generation: true,
      content: { summary: '演示回答', observations: [], suggestions: [], disclaimer: '合成演示内容。' },
      citations: [{}],
    })))
    const router = await makeRouter(`/student/support?assessment=${assessment.assessment_id}`)
    const wrapper = mount(SupportChatView, { global: { plugins: [router] } })
    await flushPromises()
    await wrapper.get('textarea').setValue('演示请求')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('演示资料来源')
    expect(wrapper.text()).not.toContain('已审核来源')
  })
})
