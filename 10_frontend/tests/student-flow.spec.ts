import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { Assessment, ApiEnvelope } from '@/types/contracts'
import type { ReportSummary, SupportResult } from '@/api/client'
import AssessmentResultView from '@/views/student/AssessmentResultView.vue'
import SupportChatView from '@/views/student/SupportChatView.vue'

const api = vi.hoisted(() => ({
  getAssessmentResult: vi.fn(),
  listReports: vi.fn(),
  createSupport: vi.fn(),
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

const makeRouter = async (path: string) => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/student/assessment/:id/result', component: AssessmentResultView },
      { path: '/student/support', component: SupportChatView },
      { path: '/student/home', component: { template: '<main>学生空间</main>' } },
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
    api.listReports.mockResolvedValue(envelope({ items: [], next_cursor: null }))
    api.createSupport.mockResolvedValue(envelope(support()))
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
