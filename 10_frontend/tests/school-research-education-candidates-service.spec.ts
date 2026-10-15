import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SchoolResearchEducationCandidateService } from '@/services/school-research-education-candidates'

const envelope = (data: unknown) => ({ request_id: 'REQ_synthetic', trace_id: 'TRACE_synthetic', data })
const response = (data: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => data,
}) as Response

const chunkId = 'CHUNK_synthetic_1'
const excerptHash = '1'.repeat(64)

const sourceCard = () => ({
  chunk_id: chunkId,
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
  excerpt_sha256: excerptHash,
  excerpt_text: 'Synthetic source excerpt.',
  consumer_age_min: 14,
  consumer_age_max: 17,
})

const provenance = (changes: Record<string, unknown> = {}) => ({
  policy_version: 'RESEARCH_GENERAL_EDUCATION_DRAFT_V1',
  policy_hash: '2'.repeat(64),
  safety_policy_version: 'safety-port-unversioned.v1',
  source_package_ref: 'PKG_R3',
  source_study_ref: 'STUDY_R3',
  source_manifest_sha256: '3'.repeat(64),
  source_age_scope: '14-17',
  retrieval_id: 'RETR_synthetic_1',
  retrieval_bundle_sha256: '4'.repeat(64),
  cited_chunk_ids: [chunkId],
  generation_id: 'GEN_synthetic_1',
  prompt_id: 'PROMPT_school_research_general_education_candidate_v1',
  prompt_version: '1.1.0',
  prompt_sha256: '5'.repeat(64),
  model_id: 'qwen2.5-7b-instruct-school-demo',
  model_version: 'qwen2.5:7b-instruct-q4_K_M',
  model_digest_sha256: '6'.repeat(64),
  runtime_version: 'runtime-synthetic',
  runtime_attempt_count: 1,
  runtime_retry_count: 0,
  runtime_fallback_count: 0,
  runtime_fallback_attempted: false,
  runtime_local_only: true,
  input_safety_action: 'PROCEED',
  input_safety_reason_codes: ['NO_RISK_SIGNAL'],
  retrieval_safety_action: 'PROCEED',
  retrieval_safety_reason_codes: ['RETRIEVAL_CLEAR'],
  output_safety_action: 'PROCEED',
  output_safety_reason_codes: ['OUTPUT_CLEAR'],
  ...changes,
})

const candidateDetail = (
  changes: Record<string, unknown> = {},
  provenanceChanges: Record<string, unknown> = {},
) => {
  const card = sourceCard()
  const locatorSuffix = `; source population: ${card.source_population_scope}; source: ${card.canonical_url}; license: ${card.license} (${card.license_url}); attribution: ${card.attribution}`
  return {
    candidate_ref: `REEDUC_${'a'.repeat(32)}`,
    task_ref: 'TASK_synthetic_1',
    session_ref: 'RSESSION_synthetic_1',
    status: 'HELD',
    state_version: 1,
    purpose: 'RESEARCH_SIMULATION',
    research_only: true,
    psychological_interpretation_allowed: false,
    publication_status: 'not_approved_for_publication_or_operational_use',
    student_feedback_eligible: false,
    created_at: '2026-10-16T08:00:00Z',
    updated_at: '2026-10-16T08:00:00Z',
    review_lineage: { generation_round: 0, input_review: null, output_review: null },
    candidate_payload: {
      schema_version: 'school-research-general-education-candidate.v1',
      content: {
        summary: 'Synthetic educational summary.',
        observations: ['Synthetic observation.'],
        suggestions: [{ text: 'Synthetic suggestion.', source_chunk_ids: [chunkId] }],
        disclaimer: 'Synthetic educational information only.',
      },
      citations: [{
        citation_id: 'CITATION_synthetic_1',
        chunk_id: chunkId,
        document_id: 'RECORD_synthetic_1',
        title: card.title,
        organization: card.organization,
        locator: `${card.record_locator}${locatorSuffix}`,
        rank: 1,
        source_version: 'v1',
        source_hash: `sha256:${excerptHash}`,
      }],
      source_cards: [card],
      provenance: provenance(provenanceChanges),
    },
    ...changes,
  }
}

describe('research education candidate review lineage projection', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => vi.unstubAllGlobals())

  it('keeps round-zero candidates on safe input/output actions with null review lineage', async () => {
    fetchMock.mockResolvedValueOnce(response(envelope(candidateDetail())))
    const service = new SchoolResearchEducationCandidateService()

    const detail = await service.get('TASK_synthetic_1', `REEDUC_${'a'.repeat(32)}`)
    expect(detail.review_lineage).toEqual({ generation_round: 0, input_review: null, output_review: null })
    expect(detail.candidate_payload.provenance.input_safety_action).toBe('PROCEED')
    expect(detail.candidate_payload.provenance.output_safety_action).toBe('PROCEED')
  })

  it('preserves reviewed input as historical REVIEW_REQUIRED only with matching consumed round-one lineage', async () => {
    fetchMock.mockResolvedValueOnce(response(envelope(candidateDetail({
      review_lineage: {
        generation_round: 1,
        input_review: { input_review_ref: `REIR_${'b'.repeat(32)}`, status: 'CONSUMED', state_version: 3 },
        output_review: null,
      },
    }, { input_safety_action: 'REVIEW_REQUIRED' }))))
    const service = new SchoolResearchEducationCandidateService()

    const detail = await service.get('TASK_synthetic_1', `REEDUC_${'a'.repeat(32)}`)
    expect(detail.review_lineage.generation_round).toBe(1)
    expect(detail.review_lineage.input_review).toMatchObject({ status: 'CONSUMED', state_version: 3 })
    expect(detail.candidate_payload.provenance.input_safety_action).toBe('REVIEW_REQUIRED')
  })

  it('rejects reviewed actions without the exact consumed sidecar and state version', async () => {
    const missingSidecar = candidateDetail({}, { input_safety_action: 'REVIEW_REQUIRED' })
    const roundOneMissingInput = candidateDetail({ review_lineage: {
      generation_round: 1,
      input_review: null,
      output_review: null,
    } }, { input_safety_action: 'REVIEW_REQUIRED' })
    const wrongVersion = candidateDetail({ review_lineage: {
      generation_round: 1,
      input_review: { input_review_ref: `REIR_${'b'.repeat(32)}`, status: 'CONSUMED', state_version: 2 },
      output_review: null,
    } }, { input_safety_action: 'REVIEW_REQUIRED' })
    const roundZeroWithInputReview = candidateDetail({ review_lineage: {
      generation_round: 0,
      input_review: { input_review_ref: `REIR_${'b'.repeat(32)}`, status: 'CONSUMED', state_version: 3 },
      output_review: null,
    } })
    fetchMock
      .mockResolvedValueOnce(response(envelope(missingSidecar)))
      .mockResolvedValueOnce(response(envelope(roundOneMissingInput)))
      .mockResolvedValueOnce(response(envelope(wrongVersion)))
      .mockResolvedValueOnce(response(envelope(roundZeroWithInputReview)))
    const service = new SchoolResearchEducationCandidateService()

    await expect(service.get('TASK_synthetic_1', `REEDUC_${'a'.repeat(32)}`))
      .rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
    await expect(service.get('TASK_synthetic_1', `REEDUC_${'a'.repeat(32)}`))
      .rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
    await expect(service.get('TASK_synthetic_1', `REEDUC_${'a'.repeat(32)}`))
      .rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
    await expect(service.get('TASK_synthetic_1', `REEDUC_${'a'.repeat(32)}`))
      .rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })

  it('allows output REVIEW_REQUIRED only with consumed controversy lineage and rejects altered sidecar shape', async () => {
    const accepted = candidateDetail({ review_lineage: {
      generation_round: 0,
      input_review: null,
      output_review: {
        output_review_ref: `REOR_${'c'.repeat(32)}`,
        status: 'CONSUMED',
        state_version: 2,
        reason_code: 'CONTENT_CONTROVERSIAL',
      },
    } }, { output_safety_action: 'REVIEW_REQUIRED' })
    const wrongReason = candidateDetail({ review_lineage: {
      generation_round: 0,
      input_review: null,
      output_review: {
        output_review_ref: `REOR_${'c'.repeat(32)}`,
        status: 'CONSUMED',
        state_version: 2,
        reason_code: 'OTHER_REASON',
      },
    } }, { output_safety_action: 'REVIEW_REQUIRED' })
    fetchMock
      .mockResolvedValueOnce(response(envelope(accepted)))
      .mockResolvedValueOnce(response(envelope(wrongReason)))
    const service = new SchoolResearchEducationCandidateService()

    const detail = await service.get('TASK_synthetic_1', `REEDUC_${'a'.repeat(32)}`)
    expect(detail.review_lineage.output_review).toMatchObject({ status: 'CONSUMED', reason_code: 'CONTENT_CONTROVERSIAL' })
    expect(detail.candidate_payload.provenance.output_safety_action).toBe('REVIEW_REQUIRED')
    await expect(service.get('TASK_synthetic_1', `REEDUC_${'a'.repeat(32)}`))
      .rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })

    fetchMock.mockResolvedValueOnce(response(envelope(
      candidateDetail({}, { output_safety_action: 'REVIEW_REQUIRED' }),
    )))
    await expect(service.get('TASK_synthetic_1', `REEDUC_${'a'.repeat(32)}`))
      .rejects.toMatchObject({ code: 'API_INVALID_RESPONSE' })
  })
})
