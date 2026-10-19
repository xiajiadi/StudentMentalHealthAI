import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SchoolResearchSourceCatalog from '@/components/school/SchoolResearchSourceCatalog.vue'
import { useSessionStore } from '@/stores/session'

const api = vi.hoisted(() => ({ listResearchSourceCatalog: vi.fn(), getResearchSource: vi.fn() }))
vi.mock('@/services/mock-api', () => ({ frontendApi: api }))

const review = {
  package_status: 'ENGINEERING_REVIEWED_RESEARCH_ONLY' as const,
  reviewer_kind: 'AI_ENGINEERING' as const,
  review_status: 'pending' as const,
  professional_approval: false as const,
  ethics_approval: false as const,
  clinical_approval: false as const,
  psychometric_approval: false as const,
  publication_eligible: false as const,
  production_use: false as const,
}
const source = {
  source_ref: 'SRC_POLICY',
  title: 'Public policy source',
  organization: 'Public agency',
  publication_date: '2024',
  canonical_url: 'https://example.org/source',
  source_population_scope: 'As stated in the source',
  source_language: 'English' as const,
  layers: ['policy'] as Array<'policy' | 'theory' | 'intervention'>,
  rights_status: 'VERIFIED_WITH_CONDITIONS' as const,
  retrieval_eligible: true,
}
const page = {
  schema_version: 'school.research-source-catalog.v1' as const,
  source_package_ref: 'source-package-r3',
  manifest_sha256: 'b'.repeat(64),
  study_ref: 'source-study',
  consumer_age_min: 14 as const,
  consumer_age_max: 17 as const,
  review,
  items: [source],
  total: 1,
  limit: 20,
  offset: 0,
  has_more: false,
}
const sourceDetail = {
  ...source,
  license: 'CC BY 4.0',
  license_url: 'https://creativecommons.org/licenses/by/4.0/',
  attribution: 'Public agency, CC BY 4.0',
  rights_evidence_url: 'https://example.org/rights',
  rights_evidence_sha256: 'a'.repeat(64),
  rights_scope_note: 'Attribution required',
  source_capture_sha256: null,
  review,
}

function prepare() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const session = useSessionStore()
  session.signIn({
    userId: 'USER_SPECIALIST', role: 'psychological_specialist', subjectId: null,
    displayName: '合成心理老师', initials: 'S',
    activeContext: { role: 'psychological_specialist', schoolRef: 'SCHOOL_SYNTHETIC_A' },
  })
  api.listResearchSourceCatalog.mockResolvedValue({ request_id: 'REQ', trace_id: 'TRACE', data: page })
  api.getResearchSource.mockResolvedValue({ request_id: 'REQ', trace_id: 'TRACE', data: sourceDetail })
  const wrapper = mount(SchoolResearchSourceCatalog, { global: { plugins: [pinia] } })
  return { wrapper, session }
}

beforeEach(() => vi.clearAllMocks())
afterEach(() => vi.restoreAllMocks())

describe('specialist research source catalog', () => {
  it('loads the pinned catalogue, shows source metadata and displays detail limits without source text', async () => {
    const { wrapper } = prepare()
    await flushPromises()
    expect(api.listResearchSourceCatalog).toHaveBeenCalledWith(expect.objectContaining({ limit: 20, offset: 0 }))
    expect(wrapper.text()).toContain('固定来源包')
    expect(wrapper.text()).toContain('AI_ENGINEERING，pending')
    expect(wrapper.text()).toContain('Public policy source')

    await wrapper.get('.source-row').trigger('click')
    await flushPromises()
    expect(api.getResearchSource).toHaveBeenCalledWith('SRC_POLICY', expect.objectContaining({ signal: expect.any(Object) }))
    expect(wrapper.text()).toContain('权利范围说明')
    expect(wrapper.text()).not.toContain('source text')
    expect(wrapper.get('.source-links a').attributes('target')).toBe('_blank')
    expect(wrapper.get('.source-links a').attributes('rel')).toContain('noopener')
    wrapper.unmount()
  })

  it('clears the selected source when the active role context changes', async () => {
    const { wrapper, session } = prepare()
    await flushPromises()
    await wrapper.get('.source-row').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Attribution required')

    session.signIn({
      userId: 'USER_SPECIALIST', role: 'psychological_specialist', subjectId: null,
      displayName: '合成心理老师', initials: 'S',
      activeContext: { role: 'psychological_specialist', schoolRef: 'SCHOOL_SYNTHETIC_B' },
    })
    await flushPromises()
    expect(wrapper.text()).not.toContain('Attribution required')
    expect(api.listResearchSourceCatalog).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('shows an unavailable state instead of replacing a missing backend package with fake records', async () => {
    api.listResearchSourceCatalog.mockRejectedValueOnce(new Error('hidden private detail'))
    const { wrapper } = prepare()
    await flushPromises()
    expect(wrapper.text()).toContain('无法读取经过校验的来源目录')
    expect(wrapper.text()).not.toContain('hidden private detail')
    expect(wrapper.find('.source-row').exists()).toBe(false)
    wrapper.unmount()
  })
})
