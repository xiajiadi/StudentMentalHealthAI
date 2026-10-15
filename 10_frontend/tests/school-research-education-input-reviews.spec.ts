import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import SpecialistResearchEducationInputReviews from '@/components/school/SpecialistResearchEducationInputReviews.vue'
import {
  SchoolResearchEducationInputReviewService,
  type ResearchEducationInputReviewStatus,
  type ResearchEducationInputReviewSummary,
} from '@/services/school-research-education-input-reviews'
import { schoolResearchEducationCandidates } from '@/services/school-research-education-candidates'
import { useSessionStore } from '@/stores/session'

const envelope = (data: unknown) => ({ request_id: 'REQ_synthetic', trace_id: 'TRACE_synthetic', data })
const response = (data: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => data,
}) as Response

const summary = (changes: Partial<ResearchEducationInputReviewSummary> = {}) => ({
  input_review_ref: 'REIR_synthetic_1',
  job_ref: `REJ_${'a'.repeat(64)}`,
  task_ref: 'TASK_synthetic_1',
  session_ref: 'RSESSION_synthetic_1',
  status: 'PENDING',
  state_version: 1,
  expires_at: '2027-10-16T08:00:00Z',
  created_at: '2026-10-15T08:00:00Z',
  updated_at: '2026-10-15T08:00:00Z',
  reason_codes: ['CONTENT_CONTROVERSIAL'],
  purpose: 'RESEARCH_SIMULATION',
  research_only: true,
  continuation_enabled: false,
  ...changes,
})

const detail = (continuationEnabled: boolean, changes: Record<string, unknown> = {}) => ({
  ...summary({ continuation_enabled: continuationEnabled }),
  fixed_request: '请基于检索到的公开资料，撰写面向14–17岁学生的一般教育信息草稿，供研究任务中的专业人员复核。',
  canonical_input_sha256: '1'.repeat(64),
  policy_version: 'RESEARCH_GENERAL_EDUCATION_DRAFT_V1',
  policy_hash: '2'.repeat(64),
  source_package_ref: 'PKG_R3',
  source_study_ref: 'STUDY_R3',
  source_manifest_sha256: '3'.repeat(64),
  prompt_id: 'PROMPT_school_research_general_education_candidate_v1',
  prompt_version: '1.0.0',
  prompt_sha256: '4'.repeat(64),
  ...changes,
})

describe('SchoolResearchEducationInputReviewService continuation contract', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => vi.unstubAllGlobals())

  it('parses explicit capability and rejects unknown states or version combinations', async () => {
    fetchMock
      .mockResolvedValueOnce(response(envelope({
        items: [summary({ continuation_enabled: true })],
        offset: 0,
        limit: 20,
        has_more: false,
      })))
      .mockResolvedValueOnce(response(envelope({
        items: [summary({ status: 'CONTINUATION_AUTHORIZED', state_version: 1 })],
        offset: 0,
        limit: 20,
        has_more: false,
      })))
    const service = new SchoolResearchEducationInputReviewService()

    expect((await service.list('TASK_synthetic_1')).items[0]?.continuation_enabled).toBe(true)
    await expect(service.list('TASK_synthetic_1')).rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })

  it('authorizes only explicitly enabled pending records and sends versioned idempotent resolve', async () => {
    const service = new SchoolResearchEducationInputReviewService()
    const disabled = summary()
    await expect(service.resolve(
      'TASK_synthetic_1', disabled, 'CONTINUATION_AUTHORIZED', 'key-disabled',
    )).rejects.toMatchObject({ code: 'WORKFLOW_CONFLICT' })
    expect(fetchMock).not.toHaveBeenCalled()

    const enabled = summary({ continuation_enabled: true })
    fetchMock
      .mockResolvedValueOnce(response(envelope({ csrf_token: 'csrf-synthetic' })))
      .mockResolvedValueOnce(response(envelope(summary({
        status: 'CONTINUATION_AUTHORIZED',
        state_version: 2,
        continuation_enabled: true,
        updated_at: '2026-10-15T08:01:00Z',
      }))))
    const result = await service.resolve(
      'TASK_synthetic_1', enabled, 'CONTINUATION_AUTHORIZED', 'key-enabled',
    )

    expect(result.status).toBe('CONTINUATION_AUTHORIZED')
    expect(result.state_version).toBe(2)
    const [url, init] = fetchMock.mock.calls[1] as [unknown, RequestInit]
    expect(String(url)).toContain('/input-reviews/REIR_synthetic_1/resolve')
    expect(init).toMatchObject({ method: 'POST' })
    expect(init.headers).toMatchObject({
      'X-CSRF-Token': 'csrf-synthetic',
      'Idempotency-Key': 'key-enabled',
    })
    expect(JSON.parse(String(init.body))).toEqual({
      expected_state_version: 1,
      target: 'CONTINUATION_AUTHORIZED',
    })
  })
})

describe('research education generation round projection', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => vi.unstubAllGlobals())

  const generationPage = (items: unknown[]) => ({
    items,
    offset: 0,
    limit: 20,
    total: items.length,
    has_more: false,
    status_counts: {
      QUEUED: 0, LEASED: 0, RETRY: 0, HELD: items.length, ABSTAINED: 0,
      REVIEW_REQUIRED: 0, CRISIS_ROUTED: 0, FAILED: 0, CANCELLED: 0,
    },
    policy_version: 'RESEARCH_GENERAL_EDUCATION_DRAFT_V1',
    purpose: 'RESEARCH_SIMULATION',
    research_only: true,
    publication_status: 'not_approved_for_publication_or_operational_use',
    student_feedback_eligible: false,
  })

  const job = (changes: Record<string, unknown> = {}) => ({
    job_ref: `REJ_${'a'.repeat(64)}`,
    generation_round: 0,
    input_review_ref: null,
    status: 'HELD',
    attempt_count: 1,
    last_error_code: null,
    created_at: '2026-10-15T08:00:00Z',
    updated_at: '2026-10-15T08:01:00Z',
    ...changes,
  })

  it('preserves original and continuation identity and rejects a partial lineage pair', async () => {
    fetchMock.mockResolvedValueOnce(response(envelope(generationPage([
      job(),
      job({
        job_ref: `REJ_${'b'.repeat(64)}`,
        generation_round: 1,
        input_review_ref: 'REIR_synthetic_1',
      }),
    ]))))
    const page = await schoolResearchEducationCandidates.listJobs('TASK_synthetic_1')
    expect(page.items.map(({ generation_round, input_review_ref }) => [generation_round, input_review_ref]))
      .toEqual([[0, null], [1, 'REIR_synthetic_1']])

    fetchMock.mockResolvedValueOnce(response(envelope(generationPage([
      job({ generation_round: 1, input_review_ref: null }),
    ]))))
    await expect(schoolResearchEducationCandidates.listJobs('TASK_synthetic_1'))
      .rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })
})

describe('SpecialistResearchEducationInputReviews continuation affordance', () => {
  let fetchMock: ReturnType<typeof vi.fn>
  let wrapper: VueWrapper | undefined

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    setActivePinia(createPinia())
    useSessionStore().signIn({
      userId: 'user_synthetic',
      role: 'psychological_specialist',
      subjectId: null,
      displayName: '合成专员',
      initials: '合',
    })
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
    vi.unstubAllGlobals()
  })

  async function openDetail(
    enabled: boolean,
    status: ResearchEducationInputReviewStatus = 'PENDING',
    stateVersion = 1,
  ) {
    fetchMock
      .mockResolvedValueOnce(response(envelope({
        items: [summary({ continuation_enabled: enabled, status, state_version: stateVersion })],
        offset: 0,
        limit: 20,
        has_more: false,
      })))
      .mockResolvedValueOnce(response(envelope(detail(enabled, { status, state_version: stateVersion }))))
    wrapper = mount(SpecialistResearchEducationInputReviews, {
      props: { taskRef: 'TASK_synthetic_1' },
    })
    await flushPromises()
    await wrapper.get('.input-reviews__row').trigger('click')
    await flushPromises()
  }

  it('shows one-time authorization only when the trusted capability is enabled and pending', async () => {
    await openDetail(true)
    expect(wrapper?.text()).toContain('授权只允许一次研究生成')
    expect(wrapper?.find('option[value="CONTINUATION_AUTHORIZED"]').exists()).toBe(true)
    expect(wrapper?.text()).toContain('不代表专业批准')

    fetchMock
      .mockResolvedValueOnce(response(envelope({ csrf_token: 'csrf-synthetic' })))
      .mockResolvedValueOnce(response(envelope(summary({
        status: 'CONTINUATION_AUTHORIZED',
        state_version: 2,
        continuation_enabled: true,
        updated_at: '2026-10-15T08:01:00Z',
      }))))
    await wrapper?.get('select#input-review-disposition').setValue('CONTINUATION_AUTHORIZED')
    await wrapper?.get('input[type="checkbox"]').setValue(true)
    const authorize = wrapper?.findAll('button')
      .find((button) => button.text().includes('确认授权一次继续'))
    expect(authorize).toBeDefined()
    await authorize?.trigger('click')
    await flushPromises()
    expect(wrapper?.text()).toContain('生成的候选仍需人工审核；此授权不代表专业批准。')
    const [url, init] = fetchMock.mock.calls.at(-1) as [unknown, RequestInit]
    expect(String(url)).toContain('/input-reviews/REIR_synthetic_1/resolve')
    expect(JSON.parse(String(init.body))).toEqual({
      expected_state_version: 1,
      target: 'CONTINUATION_AUTHORIZED',
    })
  })

  it('does not show authorization when disabled or after the grant was consumed into a new state', async () => {
    await openDetail(false)
    expect(wrapper?.find('option[value="CONTINUATION_AUTHORIZED"]').exists()).toBe(false)
    expect(wrapper?.text()).not.toContain('授权只允许一次研究生成')
    wrapper?.unmount()
    wrapper = undefined

    await openDetail(true, 'CONTINUATION_AUTHORIZED', 2)
    expect(wrapper?.find('option[value="CONTINUATION_AUTHORIZED"]').exists()).toBe(false)
    expect(wrapper?.find('option[value="REVOKED"]').exists()).toBe(true)
  })
})
