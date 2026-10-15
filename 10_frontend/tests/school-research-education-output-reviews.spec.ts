import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import SpecialistResearchEducationOutputReviews from '@/components/school/SpecialistResearchEducationOutputReviews.vue'
import {
  SchoolResearchEducationOutputReviewService,
  type ResearchEducationOutputReviewSummary,
} from '@/services/school-research-education-output-reviews'
import { useSessionStore } from '@/stores/session'

const envelope = (data: unknown) => ({ request_id: 'REQ_synthetic', trace_id: 'TRACE_synthetic', data })
const response = (data: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => data,
}) as Response

const summary = (changes: Partial<ResearchEducationOutputReviewSummary> = {}) => ({
  output_review_ref: `REOR_${'a'.repeat(32)}`,
  job_ref: `REJ_${'a'.repeat(64)}`,
  task_ref: 'TASK_synthetic_1',
  session_ref: 'RSESSION_synthetic_1',
  generation_round: 0,
  status: 'PENDING',
  state_version: 1,
  expires_at: '2026-10-17T08:00:00Z',
  created_at: '2026-10-16T08:00:00Z',
  updated_at: '2026-10-16T08:00:00Z',
  safety_action: 'REVIEW_REQUIRED',
  reason_codes: ['CONTENT_CONTROVERSIAL'],
  requires_human: true,
  purpose: 'RESEARCH_SIMULATION',
  research_only: true,
  publication_status: 'not_approved_for_publication_or_operational_use',
  student_feedback_eligible: false,
  ...changes,
})

const sourceCard = () => ({
  chunk_id: 'CHUNK_synthetic_1',
  record_id: 'RECORD_synthetic_1',
  source_id: 'SOURCE_synthetic_1',
  title: 'Synthetic public resource',
  organization: 'Synthetic organization',
  canonical_url: 'https://example.org/resource',
  record_locator: 'section 1',
  source_population_scope: 'General adolescent education',
  source_language: 'en',
  license: 'CC BY 4.0',
  license_url: 'https://creativecommons.org/licenses/by/4.0/',
  attribution: 'Synthetic attribution',
  excerpt_sha256: '1'.repeat(64),
  excerpt_text: 'Synthetic source excerpt.',
  consumer_age_min: 14,
  consumer_age_max: 17,
})

const provenance = () => ({
  generation_id: 'GEN_synthetic_1',
  retrieval_id: 'RETR_synthetic_1',
  retrieval_bundle_sha256: '2'.repeat(64),
  policy_version: 'RESEARCH_GENERAL_EDUCATION_DRAFT_V1',
  policy_hash: '3'.repeat(64),
  safety_policy_version: 'safety-port-unversioned.v1',
  source_package_ref: 'PKG_R3',
  source_study_ref: 'STUDY_R3',
  source_manifest_sha256: '4'.repeat(64),
  source_age_scope: '14-17',
  prompt_id: 'PROMPT_school_research_general_education_candidate_v1',
  prompt_version: '1.0.0',
  prompt_sha256: '5'.repeat(64),
  model_id: 'qwen2.5-7b-instruct-school-demo',
  model_version: 'qwen2.5:7b-instruct-q4_K_M',
  model_digest_sha256: '6'.repeat(64),
  runtime_version: 'synthetic-runtime-v1',
  runtime_attempt_count: 1,
  runtime_retry_count: 0,
  runtime_fallback_count: 0,
  runtime_fallback_attempted: false,
  runtime_local_only: true,
  input_safety_action: 'PROCEED',
  input_safety_reason_codes: ['INPUT_SAFE'],
  retrieval_safety_action: 'PROCEED',
  retrieval_safety_reason_codes: ['RETRIEVAL_SAFE'],
  output_safety_action: 'REVIEW_REQUIRED',
  output_safety_reason_codes: ['CONTENT_CONTROVERSIAL'],
  output_safety_requires_human: true,
})

const reviewDetail = (changes: Record<string, unknown> = {}) => ({
  ...summary(),
  review_payload: {
    schema_version: 'school-research-general-education-output-review.v1',
    content: {
      summary: 'Synthetic educational summary.',
      observations: ['Synthetic observation.'],
      suggestions: [{ text: 'Synthetic suggestion.', source_chunk_ids: ['CHUNK_synthetic_1'] }],
      disclaimer: 'Synthetic research disclaimer.',
    },
    source_cards: [sourceCard()],
    citations: [],
    citation_binding_status: 'NOT_EVALUATED_AT_OUTPUT_STOP',
    provenance: provenance(),
  },
  ...changes,
})

const page = (items: unknown[]) => ({ items, offset: 0, limit: 20, has_more: false })

const candidateSummary = () => ({
  candidate_ref: 'REEDUC_synthetic_1',
  task_ref: 'TASK_synthetic_1',
  session_ref: 'RSESSION_synthetic_1',
  status: 'HELD',
  state_version: 1,
  purpose: 'RESEARCH_SIMULATION',
  research_only: true,
  psychological_interpretation_allowed: false,
  publication_status: 'not_approved_for_publication_or_operational_use',
  student_feedback_eligible: false,
  created_at: '2026-10-16T08:05:00Z',
  updated_at: '2026-10-16T08:05:00Z',
})

describe('SchoolResearchEducationOutputReviewService', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => vi.unstubAllGlobals())

  it('maps only assigned-task metadata and exposes source material without inventing citations', async () => {
    fetchMock
      .mockResolvedValueOnce(response(envelope(page([summary()]))))
      .mockResolvedValueOnce(response(envelope(reviewDetail())))
    const service = new SchoolResearchEducationOutputReviewService()

    const listed = await service.list('TASK_synthetic_1')
    expect(listed.items[0]?.status).toBe('PENDING')
    const detail = await service.get('TASK_synthetic_1', `REOR_${'a'.repeat(32)}`)
    expect(detail.review_payload.citations).toEqual([])
    expect(detail.review_payload.source_cards[0]?.excerpt_text).toBe('Synthetic source excerpt.')
    expect(detail.review_payload.citation_binding_status).toBe('NOT_EVALUATED_AT_OUTPUT_STOP')
    expect(detail.review_payload.provenance.output_safety_action).toBe('REVIEW_REQUIRED')
    const [url] = fetchMock.mock.calls[1] as [string]
    expect(url).toContain(`/tasks/TASK_synthetic_1/output-reviews/REOR_${'a'.repeat(32)}`)
  })

  it('rejects mismatched tasks, unexpected payload fields, or fabricated citations', async () => {
    fetchMock
      .mockResolvedValueOnce(response(envelope(page([summary({ task_ref: 'TASK_other' })]))))
      .mockResolvedValueOnce(response(envelope(reviewDetail({ private_body: 'sentinel' }))))
      .mockResolvedValueOnce(response(envelope(reviewDetail({
        review_payload: { ...reviewDetail().review_payload, citations: [{ citation_id: 'fake' }] },
      }))))
    const service = new SchoolResearchEducationOutputReviewService()

    await expect(service.list('TASK_synthetic_1')).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
    await expect(service.get('TASK_synthetic_1', `REOR_${'a'.repeat(32)}`))
      .rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
    await expect(service.get('TASK_synthetic_1', `REOR_${'a'.repeat(32)}`))
      .rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })

  it('resolves once with CSRF, state version and idempotency, then requires a HELD candidate', async () => {
    fetchMock
      .mockResolvedValueOnce(response(envelope({ csrf_token: 'csrf-synthetic' })))
      .mockResolvedValueOnce(response(envelope({
        output_review: summary({ status: 'CONSUMED', state_version: 2, updated_at: '2026-10-16T08:05:00Z' }),
        candidate: candidateSummary(),
      })))
    const result = await new SchoolResearchEducationOutputReviewService().resolve(
      'TASK_synthetic_1', summary(), 'CREATE_HELD_CANDIDATE', 'key-synthetic',
    )

    expect(result.output_review.status).toBe('CONSUMED')
    expect(result.candidate?.status).toBe('HELD')
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit]
    expect(url).toContain(`/output-reviews/REOR_${'a'.repeat(32)}/resolve`)
    expect(init).toMatchObject({ method: 'POST' })
    expect(init.headers).toMatchObject({
      'X-CSRF-Token': 'csrf-synthetic',
      'Idempotency-Key': 'key-synthetic',
    })
    expect(JSON.parse(String(init.body))).toEqual({ expected_state_version: 1, target: 'CREATE_HELD_CANDIDATE' })
  })

  it('does not send an expired or nonpending transition', async () => {
    const service = new SchoolResearchEducationOutputReviewService()
    await expect(service.resolve(
      'TASK_synthetic_1', summary({ expires_at: '2020-01-01T00:00:00Z' }), 'REJECTED', 'key-expired',
    )).rejects.toMatchObject({ code: 'WORKFLOW_CONFLICT' })
    await expect(service.resolve(
      'TASK_synthetic_1', summary({ status: 'CONSUMED', state_version: 2 }), 'REVOKED', 'key-terminal',
    )).rejects.toMatchObject({ code: 'WORKFLOW_CONFLICT' })
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('SpecialistResearchEducationOutputReviews', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  let wrapper: VueWrapper | undefined

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    setActivePinia(createPinia())
    useSessionStore().signIn({
      userId: 'user_synthetic', role: 'psychological_specialist', subjectId: null,
      displayName: '合成专员', initials: '合',
    })
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
    vi.unstubAllGlobals()
  })

  it('requires explicit acknowledgement and states held-candidate boundaries after resolve', async () => {
    fetchMock
      .mockResolvedValueOnce(response(envelope(page([summary()]))))
      .mockResolvedValueOnce(response(envelope(reviewDetail())))
    wrapper = mount(SpecialistResearchEducationOutputReviews, { props: { taskRef: 'TASK_synthetic_1' } })
    await flushPromises()
    await wrapper.get('.output-reviews__row').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('检索来源（引用关系待校验）')
    expect(wrapper.text()).toContain('不代表 Safety 允许，也不代表心理专业批准')
    expect(wrapper.text()).toContain('Synthetic educational summary.')
    expect(wrapper.text()).not.toContain('PUBLISH')
    await wrapper.get('#output-review-target').setValue('CREATE_HELD_CANDIDATE')
    const submit = wrapper.findAll('button').find((button) => button.text().includes('确认转为待审候选'))
    expect(submit?.attributes('disabled')).toBeDefined()

    fetchMock
      .mockResolvedValueOnce(response(envelope({ csrf_token: 'csrf-synthetic' })))
      .mockResolvedValueOnce(response(envelope({
        output_review: summary({ status: 'CONSUMED', state_version: 2, updated_at: '2026-10-16T08:05:00Z' }),
        candidate: candidateSummary(),
      })))
      .mockResolvedValueOnce(response(envelope(page([summary({ status: 'CONSUMED', state_version: 2 })]))))
    await wrapper.get('.output-reviews__confirm input').setValue(true)
    await flushPromises()
    const confirmed = wrapper.findAll('button').find((button) => button.text().includes('确认转为待审候选'))
    await confirmed?.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('已转为待审候选')
    expect(wrapper.text()).not.toContain('Synthetic educational summary.')
    expect(wrapper.emitted('candidateCreated')).toHaveLength(1)
    expect(fetchMock).toHaveBeenCalledTimes(5)
  })

  it('clears late private detail after switching task and hides the panel from other roles', async () => {
    let releaseDetail: ((value: Response) => void) | undefined
    fetchMock
      .mockResolvedValueOnce(response(envelope(page([summary()]))))
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { releaseDetail = resolve }))
      .mockResolvedValueOnce(response(envelope(page([]))))
    wrapper = mount(SpecialistResearchEducationOutputReviews, { props: { taskRef: 'TASK_synthetic_1' } })
    await flushPromises()
    await wrapper.get('.output-reviews__row').trigger('click')
    await wrapper.setProps({ taskRef: 'TASK_synthetic_2' })
    await flushPromises()
    releaseDetail?.(response(envelope(reviewDetail())))
    await flushPromises()
    expect(wrapper.text()).not.toContain('Synthetic educational summary.')
    expect(wrapper.text()).toContain('当前任务没有输出复核记录。')

    wrapper.unmount()
    wrapper = undefined
    useSessionStore().signIn({
      userId: 'teacher_synthetic', role: 'teacher', subjectId: null,
      displayName: '合成教师', initials: '教',
    })
    const requestCount = fetchMock.mock.calls.length
    wrapper = mount(SpecialistResearchEducationOutputReviews, { props: { taskRef: 'TASK_synthetic_1' } })
    await flushPromises()
    expect(wrapper.find('.output-reviews').exists()).toBe(false)
    expect(fetchMock).toHaveBeenCalledTimes(requestCount)
  })

  it('clears stale content and refreshes the list after a state conflict without retrying the mutation', async () => {
    fetchMock
      .mockResolvedValueOnce(response(envelope(page([summary()]))))
      .mockResolvedValueOnce(response(envelope(reviewDetail())))
    wrapper = mount(SpecialistResearchEducationOutputReviews, { props: { taskRef: 'TASK_synthetic_1' } })
    await flushPromises()
    await wrapper.get('.output-reviews__row').trigger('click')
    await flushPromises()
    await wrapper.get('#output-review-target').setValue('REJECTED')
    await wrapper.get('.output-reviews__confirm input').setValue(true)
    fetchMock
      .mockResolvedValueOnce(response(envelope({ csrf_token: 'csrf-synthetic' })))
      .mockResolvedValueOnce(response({
        error: { code: 'WORKFLOW_CONFLICT', detail: 'Synthetic stale state.' },
      }, 409))
      .mockResolvedValueOnce(response(envelope(page([]))))
    const reject = wrapper.findAll('button').find((button) => button.text().includes('确认拒绝'))
    await reject?.trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('Synthetic educational summary.')
    expect(wrapper.find('.output-reviews__row').exists()).toBe(false)
    expect(fetchMock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === 'POST'))
      .toHaveLength(1)
    expect(fetchMock).toHaveBeenCalledTimes(5)
  })
})
