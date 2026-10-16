import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const services = vi.hoisted(() => ({
  studentList: vi.fn(),
  studentReviewers: vi.fn(),
  studentShare: vi.fn(),
  studentWithdraw: vi.fn(),
  specialistList: vi.fn(),
  specialistGet: vi.fn(),
  specialistDraft: vi.fn(),
  specialistPublish: vi.fn(),
  specialistRevoke: vi.fn(),
  key: vi.fn(() => 'synthetic-independent-review-key'),
}))

vi.mock('@/services/independent-education-reviews', () => ({
  newIndependentEducationReviewIdempotencyKey: services.key,
  studentIndependentEducationReviews: {
    list: services.studentList,
    listReviewers: services.studentReviewers,
    share: services.studentShare,
    withdraw: services.studentWithdraw,
  },
  specialistIndependentEducationReviews: {
    list: services.specialistList,
    get: services.specialistGet,
    saveDraft: services.specialistDraft,
    publish: services.specialistPublish,
    revoke: services.specialistRevoke,
  },
}))

import StudentIndependentEducationReviews from '@/components/school/StudentIndependentEducationReviews.vue'
import SpecialistIndependentEducationReviews from '@/components/school/SpecialistIndependentEducationReviews.vue'
import { useSessionStore } from '@/stores/session'

const reviewRef = 'EDUREV_0123456789abcdef0123456789abcdef'
const conversationId = 'CONV_synthetic_1'
const studentHeld = {
  review_ref: reviewRef, status: 'HELD', state_version: 1,
  created_at: '2026-10-16T08:00:00Z', updated_at: '2026-10-16T08:00:00Z',
  reviewer_ref: null, published_content: null,
}
const specialistSummary = {
  review_ref: reviewRef, status: 'SHARED', state_version: 2,
  created_at: '2026-10-16T08:00:00Z', updated_at: '2026-10-16T09:00:00Z',
}
const specialistDetail = {
  ...specialistSummary,
  shared_at: '2026-10-16T09:00:00Z',
  candidate: {
    schema_version: 'independent-research-education-candidate.v1',
    content: {
      summary: '仅心理老师可见的合成原始候选摘要',
      observations: [], suggestions: [], disclaimer: '仅供隔离研究演示。',
    },
    citations: [], source_cards: [],
    provenance: {
      purpose: 'RESEARCH_SIMULATION', research_only: true,
      source_study_ref: 'STUDY_synthetic', source_package_ref: 'PACKAGE_synthetic',
      source_manifest_sha256: 'a'.repeat(64), retrieval_id: 'RETR_synthetic',
      retrieval_bundle_sha256: 'b'.repeat(64), prompt_id: 'PROMPT_synthetic',
      prompt_version: '1.0.0', prompt_sha256: null, model_id: 'MODEL_synthetic',
      logical_model_id: 'LOGICAL_synthetic', model_version: '1.0', model_digest_sha256: 'c'.repeat(64),
      runtime_version: 'runtime-synthetic', trace_id: 'TRACE_synthetic',
      input_safety_action: 'PROCEED', input_safety_reason_codes: [],
      retrieval_safety_action: 'PROCEED', retrieval_safety_reason_codes: [],
      output_safety_action: 'PROCEED', output_safety_reason_codes: [],
      claim_boundary_status: 'ACCEPTED', citation_binding_status: 'BOUND',
    },
  },
  reviewed_draft: null,
}

function signIn(role: 'student' | 'psychological_specialist') {
  const pinia = createPinia()
  setActivePinia(pinia)
  useSessionStore(pinia).signIn({
    userId: `USER_synthetic_${role}`, role,
    subjectId: role === 'student' ? 'SUBJECT_synthetic_1' : null,
    displayName: 'Synthetic User', initials: 'S',
    activeContext: { role, schoolRef: 'SCHOOL_synthetic_1' },
  })
  return pinia
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

describe('independent education review components', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    services.studentList.mockResolvedValue({ items: [studentHeld], total: 1, offset: 0, limit: 20, has_more: false })
    services.studentReviewers.mockResolvedValue({
      items: [{ reviewer_ref: 'MEMROLE_synthetic_1', display_name: '合成心理老师' }],
      total: 1, offset: 0, limit: 20, has_more: false,
    })
    services.studentShare.mockResolvedValue({ ...studentHeld, status: 'SHARED', state_version: 2, reviewer_ref: 'MEMROLE_synthetic_1' })
    services.specialistList.mockResolvedValue({ items: [specialistSummary], total: 1, offset: 0, limit: 20, has_more: false })
    services.specialistGet.mockResolvedValue(specialistDetail)
  })

  it('keeps held content hidden from the student and requires explicit share consent', async () => {
    const pinia = signIn('student')
    const wrapper = mount(StudentIndependentEducationReviews, {
      props: { conversationId, refreshToken: 0 }, global: { plugins: [pinia] },
    })
    await flushPromises()

    expect(services.studentList).toHaveBeenCalledWith(conversationId, 0, 20)
    expect(wrapper.text()).toContain('待分享')
    expect(wrapper.text()).not.toContain('仅心理老师可见的合成原始候选摘要')
    expect(services.studentReviewers).toHaveBeenCalledWith(conversationId, 0, 20)
    const shareButton = wrapper.findAll('button').find((button) => button.text().includes('分享给所选心理老师'))!
    expect(shareButton.attributes('disabled')).toBeDefined()

    await wrapper.get('select').setValue('MEMROLE_synthetic_1')
    await wrapper.get('input[type="checkbox"]').setValue(true)
    await flushPromises()
    expect(shareButton.attributes('disabled')).toBeUndefined()
    await shareButton.trigger('click')
    await flushPromises()
    expect(services.studentShare).toHaveBeenCalledWith(conversationId, studentHeld, 'MEMROLE_synthetic_1', 'synthetic-independent-review-key')
    useSessionStore(pinia).signIn({
      userId: 'USER_synthetic_teacher', role: 'teacher', subjectId: null,
      displayName: 'Synthetic Teacher', initials: 'T',
      activeContext: { role: 'teacher', schoolRef: 'SCHOOL_synthetic_1' },
    })
    await flushPromises()
    expect(wrapper.text()).not.toContain('待分享')
    wrapper.unmount()
  })

  it('refreshes the same conversation metadata when a new terminal turn advances the token', async () => {
    services.studentList
      .mockResolvedValueOnce({ items: [], total: 0, offset: 0, limit: 20, has_more: false })
      .mockResolvedValueOnce({ items: [studentHeld], total: 1, offset: 0, limit: 20, has_more: false })
    const pinia = signIn('student')
    const wrapper = mount(StudentIndependentEducationReviews, {
      props: { conversationId, refreshToken: 0 }, global: { plugins: [pinia] },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('当前会话没有可显示的复核记录')

    await wrapper.setProps({ refreshToken: 1 })
    await flushPromises()
    expect(services.studentList).toHaveBeenCalledTimes(2)
    expect(services.studentList).toHaveBeenLastCalledWith(conversationId, 0, 20)
    expect(wrapper.text()).toContain('待分享')
    wrapper.unmount()
  })

  it('allows the student to withdraw a revoked publication into the terminal withdrawn state', async () => {
    const revoked = { ...studentHeld, status: 'REVOKED', state_version: 3, reviewer_ref: 'MEMROLE_synthetic_1' }
    const withdrawn = { ...revoked, status: 'WITHDRAWN', state_version: 4 }
    services.studentList
      .mockResolvedValueOnce({ items: [revoked], total: 1, offset: 0, limit: 20, has_more: false })
      .mockResolvedValueOnce({ items: [withdrawn], total: 1, offset: 0, limit: 20, has_more: false })
    services.studentWithdraw.mockResolvedValue(withdrawn)
    const pinia = signIn('student')
    const wrapper = mount(StudentIndependentEducationReviews, {
      props: { conversationId }, global: { plugins: [pinia] },
    })
    await flushPromises()
    const withdrawButton = wrapper.findAll('button').find((button) => button.text().includes('撤回分享'))!
    expect(withdrawButton.exists()).toBe(true)
    await withdrawButton.trigger('click')
    await flushPromises()

    expect(services.studentWithdraw).toHaveBeenCalledWith(conversationId, revoked, 'synthetic-independent-review-key')
    expect(wrapper.text()).toContain('已撤回分享')
    expect(wrapper.findAll('button').some((button) => button.text().includes('撤回分享'))).toBe(false)
    wrapper.unmount()
  })

  it('does not show a retry for an old share after the student context changes', async () => {
    const pendingShare = deferred<unknown>()
    services.studentShare.mockReturnValue(pendingShare.promise)
    const pinia = signIn('student')
    const session = useSessionStore(pinia)
    const wrapper = mount(StudentIndependentEducationReviews, {
      props: { conversationId }, global: { plugins: [pinia] },
    })
    await flushPromises()
    await wrapper.get('select').setValue('MEMROLE_synthetic_1')
    await wrapper.get('input[type="checkbox"]').setValue(true)
    await wrapper.findAll('button').find((button) => button.text().includes('分享给所选心理老师'))!.trigger('click')
    expect(services.studentShare).toHaveBeenCalledOnce()

    session.signIn({
      userId: 'USER_synthetic_teacher', role: 'teacher', subjectId: null,
      displayName: 'Synthetic Teacher', initials: 'T',
      activeContext: { role: 'teacher', schoolRef: 'SCHOOL_synthetic_1' },
    })
    pendingShare.reject(Object.assign(new Error('synthetic timeout'), { retryable: true }))
    await flushPromises()
    expect(wrapper.text()).not.toContain('使用同一请求重试')
    expect(wrapper.text()).not.toContain('待分享')
    wrapper.unmount()
  })

  it('shows assigned candidate detail without conversation-history controls', async () => {
    const pinia = signIn('psychological_specialist')
    const wrapper = mount(SpecialistIndependentEducationReviews, {
      global: { plugins: [pinia] },
    })
    await flushPromises()
    expect(services.specialistList).toHaveBeenCalledWith(0, 20)
    const row = wrapper.findAll('button').find((button) => button.text().includes('待核对'))!
    await row.trigger('click')
    await flushPromises()

    expect(services.specialistGet).toHaveBeenCalledWith(reviewRef)
    expect(wrapper.text()).toContain('仅心理老师可见的合成原始候选摘要')
    expect(wrapper.text()).toContain('工程追溯信息')
    expect(wrapper.text()).not.toContain('打开对话')
    expect(wrapper.text()).not.toContain('查看历史消息')
    useSessionStore(pinia).signIn({
      userId: 'USER_synthetic_student', role: 'student', subjectId: 'SUBJECT_synthetic_1',
      displayName: 'Synthetic Student', initials: 'S',
      activeContext: { role: 'student', schoolRef: 'SCHOOL_synthetic_1' },
    })
    await flushPromises()
    expect(wrapper.text()).not.toContain('仅心理老师可见的合成原始候选摘要')
    wrapper.unmount()
  })

  it('clears withdrawn detail and does not request the revoked review again', async () => {
    const publishedSummary = { ...specialistSummary, status: 'PUBLISHED', state_version: 4 }
    const publishedDetail = {
      ...specialistDetail,
      ...publishedSummary,
      reviewed_draft: {
        title: '合成已发布标题', body: '合成已发布正文', content_revision: 1,
        citations: [], source_cards: [], updated_at: '2026-10-16T10:00:00Z',
      },
    }
    services.specialistList
      .mockResolvedValueOnce({ items: [publishedSummary], total: 1, offset: 0, limit: 20, has_more: false })
      .mockResolvedValueOnce({ items: [], total: 0, offset: 0, limit: 20, has_more: false })
    services.specialistGet.mockResolvedValue(publishedDetail)
    services.specialistRevoke.mockResolvedValue(undefined)
    const pinia = signIn('psychological_specialist')
    const wrapper = mount(SpecialistIndependentEducationReviews, {
      global: { plugins: [pinia] },
    })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('已发布'))!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('合成已发布正文')

    await wrapper.get('.independent-education-review-workspace__confirm input').setValue(true)
    await wrapper.findAll('button').find((button) => button.text().trim() === '撤回发布')!.trigger('click')
    await flushPromises()

    expect(services.specialistRevoke).toHaveBeenCalledOnce()
    expect(services.specialistGet).toHaveBeenCalledTimes(1)
    expect(services.specialistList).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).not.toContain('合成已发布正文')
    expect(wrapper.text()).not.toContain('原始内容保留不变')
    expect(wrapper.text()).toContain('发布已撤回，学生将无法继续查看。')
    wrapper.unmount()
  })
})
