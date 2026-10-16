import { RealApiError, requestIndependentEducationReview } from '@/services/real-api'
import {
  mapResearchEducationSourceCard,
  mapResearchFeedbackCitation,
  newResearchFeedbackIdempotencyKey,
  type FeedbackSourceCard,
  type ResearchFeedbackCitation,
} from '@/services/school-research-feedback'

type UnknownRecord = Record<string, unknown>
export type IndependentEducationReviewStatus = 'HELD' | 'SHARED' | 'DRAFT' | 'PUBLISHED' | 'REVOKED' | 'WITHDRAWN'
export type IndependentEducationReviewPage<T> = {
  items: T[]
  offset: number
  limit: number
  total: number
  has_more: boolean
}

export type IndependentEducationPublishedContent = {
  title: string
  body: string
  citations: ResearchFeedbackCitation[]
  source_cards: FeedbackSourceCard[]
  published_at: string
}

export type IndependentEducationReviewSummary = {
  review_ref: string
  status: IndependentEducationReviewStatus
  state_version: number
  created_at: string
  updated_at: string
  reviewer_ref: string | null
  published_content: IndependentEducationPublishedContent | null
}

export type IndependentEducationReviewer = {
  reviewer_ref: string
  display_name: string
}

export type IndependentEducationSpecialistSummary = {
  review_ref: string
  status: IndependentEducationReviewStatus
  state_version: number
  created_at: string
  updated_at: string
}

export type IndependentEducationContent = {
  summary: string
  observations: string[]
  suggestions: Array<{ text: string; source_chunk_ids: string[] }>
  disclaimer: string
}

export type IndependentEducationReviewProvenance = {
  purpose: 'RESEARCH_SIMULATION'
  research_only: true
  source_study_ref: string
  source_package_ref: string
  source_manifest_sha256: string
  retrieval_id: string
  retrieval_bundle_sha256: string
  prompt_id: string
  prompt_version: string
  prompt_sha256: string | null
  model_id: string
  logical_model_id: string
  model_version: string
  model_digest_sha256: string
  runtime_version: string
  trace_id: string
  input_safety_action: string
  input_safety_reason_codes: string[]
  retrieval_safety_action: string
  retrieval_safety_reason_codes: string[]
  output_safety_action: string
  output_safety_reason_codes: string[]
  claim_boundary_status: 'ACCEPTED'
  citation_binding_status: 'BOUND'
}

export type IndependentEducationReviewCandidate = {
  schema_version: 'independent-research-education-candidate.v1'
  content: IndependentEducationContent
  citations: ResearchFeedbackCitation[]
  source_cards: FeedbackSourceCard[]
  provenance: IndependentEducationReviewProvenance
}

export type IndependentEducationReviewedDraft = {
  title: string
  body: string
  content_revision: number
  citations: ResearchFeedbackCitation[]
  source_cards: FeedbackSourceCard[]
  updated_at: string
}

export type IndependentEducationReviewDetail = IndependentEducationSpecialistSummary & {
  shared_at: string
  candidate: IndependentEducationReviewCandidate
  reviewed_draft: IndependentEducationReviewedDraft | null
}

const reviewRefPattern = /^EDUREV_[0-9a-f]{32}$/
const conversationRefPattern = /^CONV_[A-Za-z0-9][A-Za-z0-9_.-]{0,122}$/
const sha256Pattern = /^[0-9a-f]{64}$/
const statuses: IndependentEducationReviewStatus[] = ['HELD', 'SHARED', 'DRAFT', 'PUBLISHED', 'REVOKED', 'WITHDRAWN']
const summaryFields = ['review_ref', 'status', 'state_version', 'created_at', 'updated_at', 'reviewer_ref', 'published_content'].sort()
const specialistSummaryFields = ['review_ref', 'status', 'state_version', 'created_at', 'updated_at'].sort()
const reviewerFields = ['reviewer_ref', 'display_name'].sort()
const publishedContentFields = ['title', 'body', 'citations', 'source_cards', 'published_at'].sort()
const citationFields = ['citation_id', 'chunk_id', 'document_id', 'title', 'organization', 'locator', 'rank', 'source_version', 'source_hash'].sort()
const sourceCardFields = [
  'chunk_id', 'record_id', 'source_id', 'title', 'organization', 'canonical_url', 'record_locator',
  'source_population_scope', 'source_language', 'license', 'license_url', 'attribution', 'excerpt_sha256',
  'excerpt_text', 'consumer_age_min', 'consumer_age_max',
].sort()
const provenanceFields = [
  'purpose', 'research_only', 'source_study_ref', 'source_package_ref', 'source_manifest_sha256',
  'retrieval_id', 'retrieval_bundle_sha256', 'prompt_id', 'prompt_version', 'prompt_sha256', 'model_id',
  'logical_model_id', 'model_version', 'model_digest_sha256', 'runtime_version', 'trace_id',
  'input_safety_action', 'input_safety_reason_codes', 'retrieval_safety_action',
  'retrieval_safety_reason_codes', 'output_safety_action', 'output_safety_reason_codes',
  'claim_boundary_status', 'citation_binding_status',
].sort()
const contentFields = ['summary', 'observations', 'suggestions', 'disclaimer'].sort()
const suggestionFields = ['text', 'source_chunk_ids'].sort()
const draftFields = ['title', 'body', 'content_revision', 'citations', 'source_cards', 'updated_at'].sort()
const detailFields = [...specialistSummaryFields, 'shared_at', 'candidate', 'reviewed_draft'].sort()
const pageFields = ['items', 'offset', 'limit', 'total', 'has_more'].sort()

const fail = (message: string): never => { throw new RealApiError('API_INVALID_RESPONSE', message) }

function record(value: unknown, message: string): UnknownRecord {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return fail(message)
  return value as UnknownRecord
}

function exactFields(source: UnknownRecord, fields: string[], message: string) {
  if (Object.keys(source).sort().join('|') !== fields.join('|')) fail(message)
}

function boundedText(source: UnknownRecord, key: string, max: number, message: string): string {
  const value = source[key]
  if (typeof value !== 'string' || value.length > max) return fail(message)
  return value
}

function requiredText(source: UnknownRecord, key: string, max: number, message: string): string {
  const value = boundedText(source, key, max, message)
  if (!value.trim()) return fail(message)
  return value
}

function nonEmptyText(source: UnknownRecord, key: string, max: number, message: string): string {
  const value = boundedText(source, key, max, message)
  if (value.length === 0) return fail(message)
  return value
}

function nullableText(source: UnknownRecord, key: string, max: number, message: string): string | null {
  return source[key] === null ? null : requiredText(source, key, max, message)
}

function positiveInt(source: UnknownRecord, key: string, message: string): number {
  const value = source[key]
  if (!Number.isSafeInteger(value) || (value as number) < 1 || (value as number) > 2_147_483_647) return fail(message)
  return value as number
}

function timestamp(source: UnknownRecord, key: string, message: string): string {
  const value = requiredText(source, key, 64, message)
  if (Number.isNaN(Date.parse(value))) return fail(message)
  return value
}

function citations(value: unknown, message: string): ResearchFeedbackCitation[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > 8) return fail(message)
  const mapped = value.map((item) => mapResearchFeedbackCitation(item))
  if (mapped.some((item) => Object.keys(item).sort().join('|') !== citationFields.join('|'))
    || new Set(mapped.map((item) => item.citation_id)).size !== mapped.length) return fail(message)
  return mapped
}

function sourceCards(value: unknown, message: string): FeedbackSourceCard[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > 8) return fail(message)
  const mapped = value.map((item) => mapResearchEducationSourceCard(item))
  if (mapped.some((item) => Object.keys(item).sort().join('|') !== sourceCardFields.join('|'))
    || new Set(mapped.map((item) => item.chunk_id)).size !== mapped.length) return fail(message)
  return mapped
}

function validateCitationBinding(citationRows: ResearchFeedbackCitation[], cards: FeedbackSourceCard[], message: string) {
  if (citationRows.length !== cards.length || citationRows.some((citation, index) => {
    const card = cards[index]
    return citation.chunk_id !== card!.chunk_id || citation.title !== card!.title
      || citation.organization !== card!.organization || citation.source_hash !== `sha256:${card!.excerpt_sha256}`
  })) fail(message)
}

function mapPublishedContent(value: unknown): IndependentEducationPublishedContent {
  const message = '已发布研究教育内容格式无法识别。'
  const source = record(value, message)
  exactFields(source, publishedContentFields, message)
  const citationRows = citations(source.citations, message)
  const cards = sourceCards(source.source_cards, message)
  validateCitationBinding(citationRows, cards, message)
  return Object.freeze({
    title: requiredText(source, 'title', 120, message),
    body: boundedText(source, 'body', 4000, message),
    citations: Object.freeze(citationRows.map((item) => Object.freeze(item))) as unknown as ResearchFeedbackCitation[],
    source_cards: Object.freeze(cards.map((item) => Object.freeze(item))) as unknown as FeedbackSourceCard[],
    published_at: timestamp(source, 'published_at', message),
  })
}

function mapSummary(value: unknown): IndependentEducationReviewSummary {
  const message = '研究教育复核记录格式无法识别。'
  const source = record(value, message)
  exactFields(source, summaryFields, message)
  const status = source.status
  if (!statuses.includes(status as IndependentEducationReviewStatus)) return fail(message)
  const reviewRef = requiredText(source, 'review_ref', 64, message)
  if (!reviewRefPattern.test(reviewRef)) return fail(message)
  const published = source.published_content === null ? null : mapPublishedContent(source.published_content)
  if ((status === 'PUBLISHED') !== (published !== null)) return fail(message)
  return Object.freeze({
    review_ref: reviewRef,
    status: status as IndependentEducationReviewStatus,
    state_version: positiveInt(source, 'state_version', message),
    created_at: timestamp(source, 'created_at', message),
    updated_at: timestamp(source, 'updated_at', message),
    reviewer_ref: nullableText(source, 'reviewer_ref', 128, message),
    published_content: published,
  })
}

function mapSpecialistSummary(value: unknown): IndependentEducationSpecialistSummary {
  const message = '指定研究教育复核记录格式无法识别。'
  const source = record(value, message)
  exactFields(source, specialistSummaryFields, message)
  const status = source.status
  const reviewRef = requiredText(source, 'review_ref', 64, message)
  if (!statuses.includes(status as IndependentEducationReviewStatus) || !reviewRefPattern.test(reviewRef)) return fail(message)
  return Object.freeze({
    review_ref: reviewRef,
    status: status as IndependentEducationReviewStatus,
    state_version: positiveInt(source, 'state_version', message),
    created_at: timestamp(source, 'created_at', message),
    updated_at: timestamp(source, 'updated_at', message),
  })
}

function mapPage<T>(value: unknown, offset: number, limit: number, mapper: (item: unknown) => T): IndependentEducationReviewPage<T> {
  const message = '研究教育复核列表格式无法识别。'
  const source = record(value, message)
  exactFields(source, pageFields, message)
  if (!Array.isArray(source.items) || source.items.length > limit || source.offset !== offset || source.limit !== limit
    || !Number.isSafeInteger(source.total) || (source.total as number) < offset + source.items.length
    || typeof source.has_more !== 'boolean' || source.has_more !== (offset + source.items.length < (source.total as number))) return fail(message)
  const items = source.items.map(mapper)
  const refs = items.map((item) => {
    if (!item || typeof item !== 'object') return ''
    const mapped = item as { review_ref?: unknown; reviewer_ref?: unknown }
    return typeof mapped.review_ref === 'string' ? mapped.review_ref
      : typeof mapped.reviewer_ref === 'string' ? mapped.reviewer_ref : ''
  })
  if (refs.some((ref) => !ref) || new Set(refs).size !== refs.length) return fail(message)
  return { items, offset, limit, total: source.total as number, has_more: source.has_more }
}

function mapReviewer(value: unknown): IndependentEducationReviewer {
  const message = '可选心理老师列表格式无法识别。'
  const source = record(value, message)
  exactFields(source, reviewerFields, message)
  return Object.freeze({
    reviewer_ref: requiredText(source, 'reviewer_ref', 128, message),
    display_name: requiredText(source, 'display_name', 160, message),
  })
}

function mapContent(value: unknown): IndependentEducationContent {
  const message = '研究教育草稿内容格式无法识别。'
  const source = record(value, message)
  exactFields(source, contentFields, message)
  if (!Array.isArray(source.observations) || !Array.isArray(source.suggestions)) return fail(message)
  const suggestions = source.suggestions.map((item) => {
    const suggestion = record(item, message)
    exactFields(suggestion, suggestionFields, message)
    if (!Array.isArray(suggestion.source_chunk_ids) || suggestion.source_chunk_ids.length < 1 || suggestion.source_chunk_ids.length > 8
      || suggestion.source_chunk_ids.some((id) => typeof id !== 'string' || !/^CHUNK_[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$/.test(id))) return fail(message)
    return Object.freeze({
      text: nonEmptyText(suggestion, 'text', 100_000, message),
      source_chunk_ids: Object.freeze([...suggestion.source_chunk_ids]) as unknown as string[],
    })
  })
  if (source.observations.some((item) => typeof item !== 'string' || item.length > 100_000)) return fail(message)
  return Object.freeze({
    summary: nonEmptyText(source, 'summary', 100_000, message),
    observations: Object.freeze([...source.observations]) as unknown as string[],
    suggestions: Object.freeze(suggestions) as unknown as IndependentEducationContent['suggestions'],
    disclaimer: nonEmptyText(source, 'disclaimer', 100_000, message),
  })
}

function mapProvenance(value: unknown): IndependentEducationReviewProvenance {
  const message = '研究教育来源追溯格式无法识别。'
  const source = record(value, message)
  exactFields(source, provenanceFields, message)
  const hash = (key: string) => {
    const value = requiredText(source, key, 64, message)
    if (!sha256Pattern.test(value)) return fail(message)
    return value
  }
  const optionalHash = (key: string) => {
    if (source[key] === null) return null
    return hash(key)
  }
  const action = (key: string, retrieval = false) => {
    const value = source[key]
    const allowed = retrieval ? ['PROCEED', 'PROCEED_WITH_BOUNDARY'] : ['PROCEED', 'PROCEED_WITH_BOUNDARY', 'REVIEW_REQUIRED']
    if (typeof value !== 'string' || !allowed.includes(value)) return fail(message)
    return value
  }
  const reasons = (key: string): string[] => {
    const value = source[key]
    if (!Array.isArray(value) || value.length > 16 || value.some((item) => typeof item !== 'string' || !/^[A-Z][A-Z0-9_]{0,63}$/.test(item))) return fail(message)
    return [...value]
  }
  if (source.purpose !== 'RESEARCH_SIMULATION' || source.research_only !== true
    || source.claim_boundary_status !== 'ACCEPTED' || source.citation_binding_status !== 'BOUND') return fail(message)
  return Object.freeze({
    purpose: 'RESEARCH_SIMULATION',
    research_only: true,
    source_study_ref: requiredText(source, 'source_study_ref', 128, message),
    source_package_ref: requiredText(source, 'source_package_ref', 128, message),
    source_manifest_sha256: hash('source_manifest_sha256'),
    retrieval_id: requiredText(source, 'retrieval_id', 164, message),
    retrieval_bundle_sha256: hash('retrieval_bundle_sha256'),
    prompt_id: requiredText(source, 'prompt_id', 164, message),
    prompt_version: requiredText(source, 'prompt_version', 64, message),
    prompt_sha256: optionalHash('prompt_sha256'),
    model_id: requiredText(source, 'model_id', 128, message),
    logical_model_id: requiredText(source, 'logical_model_id', 128, message),
    model_version: requiredText(source, 'model_version', 128, message),
    model_digest_sha256: hash('model_digest_sha256'),
    runtime_version: requiredText(source, 'runtime_version', 64, message),
    trace_id: requiredText(source, 'trace_id', 164, message),
    input_safety_action: action('input_safety_action'),
    input_safety_reason_codes: reasons('input_safety_reason_codes'),
    retrieval_safety_action: action('retrieval_safety_action', true),
    retrieval_safety_reason_codes: reasons('retrieval_safety_reason_codes'),
    output_safety_action: action('output_safety_action'),
    output_safety_reason_codes: reasons('output_safety_reason_codes'),
    claim_boundary_status: 'ACCEPTED',
    citation_binding_status: 'BOUND',
  })
}

function mapCandidate(value: unknown): IndependentEducationReviewCandidate {
  const message = '指定研究教育草稿格式无法识别。'
  const source = record(value, message)
  const candidateFields = ['schema_version', 'content', 'citations', 'source_cards', 'provenance'].sort()
  exactFields(source, candidateFields, message)
  if (source.schema_version !== 'independent-research-education-candidate.v1') return fail(message)
  const content = mapContent(source.content)
  const citationRows = citations(source.citations, message)
  const cards = sourceCards(source.source_cards, message)
  const provenance = mapProvenance(source.provenance)
  validateCitationBinding(citationRows, cards, message)
  const chunks = new Set(cards.map((card) => card.chunk_id))
  if (provenance.citation_binding_status !== 'BOUND'
    || content.suggestions.some((suggestion) => suggestion.source_chunk_ids.some((chunk) => !chunks.has(chunk)))) return fail(message)
  return Object.freeze({
    schema_version: 'independent-research-education-candidate.v1',
    content,
    citations: Object.freeze(citationRows.map((item) => Object.freeze(item))) as unknown as ResearchFeedbackCitation[],
    source_cards: Object.freeze(cards.map((item) => Object.freeze(item))) as unknown as FeedbackSourceCard[],
    provenance,
  })
}

function mapReviewedDraft(value: unknown, candidate: IndependentEducationReviewCandidate): IndependentEducationReviewedDraft | null {
  if (value === null) return null
  const message = '研究教育复核草稿格式无法识别。'
  const source = record(value, message)
  exactFields(source, draftFields, message)
  const citationRows = citations(source.citations, message)
  const cards = sourceCards(source.source_cards, message)
  if (JSON.stringify(citationRows) !== JSON.stringify(candidate.citations)
    || JSON.stringify(cards) !== JSON.stringify(candidate.source_cards)) return fail(message)
  return Object.freeze({
    title: requiredText(source, 'title', 120, message),
    body: boundedText(source, 'body', 4000, message),
    content_revision: positiveInt(source, 'content_revision', message),
    citations: Object.freeze(citationRows.map((item) => Object.freeze(item))) as unknown as ResearchFeedbackCitation[],
    source_cards: Object.freeze(cards.map((item) => Object.freeze(item))) as unknown as FeedbackSourceCard[],
    updated_at: timestamp(source, 'updated_at', message),
  })
}

function mapSpecialistDetail(value: unknown): IndependentEducationReviewDetail {
  const message = '指定研究教育复核详情格式无法识别。'
  const source = record(value, message)
  exactFields(source, detailFields, message)
  const summary = mapSpecialistSummary(Object.fromEntries(Object.entries(source).filter(([key]) => specialistSummaryFields.includes(key))))
  const candidate = mapCandidate(source.candidate)
  return Object.freeze({
    ...summary,
    shared_at: timestamp(source, 'shared_at', message),
    candidate,
    reviewed_draft: mapReviewedDraft(source.reviewed_draft, candidate),
  })
}

function validateRef(value: string, pattern: RegExp, message: string) {
  if (typeof value !== 'string' || !pattern.test(value)) throw new RealApiError('API_INVALID_REQUEST', message)
}

function pageParams(offset: number, limit: number) {
  if (!Number.isSafeInteger(offset) || offset < 0 || offset > 100_000
    || !Number.isSafeInteger(limit) || limit < 1 || limit > 50) throw new RealApiError('VALIDATION_FAILED', '分页参数无效。')
  return { offset, limit }
}

function validateMutation(expectedVersion: number, key: string) {
  if (!Number.isSafeInteger(expectedVersion) || expectedVersion < 1 || expectedVersion > 2_147_483_647) {
    throw new RealApiError('VALIDATION_FAILED', '研究教育复核版本无效。')
  }
  if (!key.trim() || key.length > 255) throw new RealApiError('API_INVALID_REQUEST', '研究教育复核操作缺少请求标识。')
}

function unwrapEducationReview(value: unknown): IndependentEducationReviewSummary {
  const message = '研究教育复核响应格式无法识别。'
  const source = record(value, message)
  exactFields(source, ['education_review'], message)
  return mapSummary(source.education_review)
}

export class StudentIndependentEducationReviewService {
  async list(conversationId: string, offset = 0, limit = 20): Promise<IndependentEducationReviewPage<IndependentEducationReviewSummary>> {
    validateRef(conversationId, conversationRefPattern, '会话编号无效。')
    const page = pageParams(offset, limit)
    const result = await requestIndependentEducationReview<unknown>({
      method: 'GET', path: `/api/v1/student/research-conversations/${encodeURIComponent(conversationId)}/education-reviews`, query: page,
    })
    return mapPage(result.data, offset, limit, mapSummary)
  }

  async listReviewers(conversationId: string, offset = 0, limit = 20): Promise<IndependentEducationReviewPage<IndependentEducationReviewer>> {
    validateRef(conversationId, conversationRefPattern, '会话编号无效。')
    const page = pageParams(offset, limit)
    const result = await requestIndependentEducationReview<unknown>({
      method: 'GET', path: `/api/v1/student/research-conversations/${encodeURIComponent(conversationId)}/education-reviewers`, query: page,
    })
    return mapPage(result.data, offset, limit, mapReviewer)
  }

  async share(conversationId: string, item: IndependentEducationReviewSummary, reviewerRef: string, key = newResearchFeedbackIdempotencyKey()): Promise<IndependentEducationReviewSummary> {
    validateRef(conversationId, conversationRefPattern, '会话编号无效.')
    validateRef(item.review_ref, reviewRefPattern, '研究教育复核编号无效。')
    validateMutation(item.state_version, key)
    if (item.status !== 'HELD' || !reviewerRef.trim() || reviewerRef.length > 128) throw new RealApiError('VALIDATION_FAILED', '当前记录无法分享。')
    const result = await requestIndependentEducationReview<unknown>({
      method: 'POST',
      path: `/api/v1/student/research-conversations/${encodeURIComponent(conversationId)}/education-reviews/${encodeURIComponent(item.review_ref)}/share`,
      body: { expected_version: item.state_version, reviewer_ref: reviewerRef, consent: true }, idempotencyKey: key,
    })
    return unwrapEducationReview(result.data)
  }

  async withdraw(conversationId: string, item: IndependentEducationReviewSummary, key = newResearchFeedbackIdempotencyKey()): Promise<IndependentEducationReviewSummary> {
    validateRef(conversationId, conversationRefPattern, '会话编号无效。')
    validateRef(item.review_ref, reviewRefPattern, '研究教育复核编号无效。')
    validateMutation(item.state_version, key)
    if (item.status === 'WITHDRAWN') throw new RealApiError('VALIDATION_FAILED', '当前记录不能撤回。')
    const result = await requestIndependentEducationReview<unknown>({
      method: 'POST',
      path: `/api/v1/student/research-conversations/${encodeURIComponent(conversationId)}/education-reviews/${encodeURIComponent(item.review_ref)}/withdraw`,
      body: { expected_version: item.state_version }, idempotencyKey: key,
    })
    return unwrapEducationReview(result.data)
  }
}

export class SpecialistIndependentEducationReviewService {
  async list(offset = 0, limit = 20): Promise<IndependentEducationReviewPage<IndependentEducationSpecialistSummary>> {
    const page = pageParams(offset, limit)
    const result = await requestIndependentEducationReview<unknown>({
      method: 'GET', path: '/api/v1/school/independent-education-reviews', query: page,
    })
    return mapPage(result.data, offset, limit, mapSpecialistSummary)
  }

  async get(reviewRef: string): Promise<IndependentEducationReviewDetail> {
    validateRef(reviewRef, reviewRefPattern, '研究教育复核编号无效。')
    const result = await requestIndependentEducationReview<unknown>({
      method: 'GET', path: `/api/v1/school/independent-education-reviews/${encodeURIComponent(reviewRef)}`,
    })
    return mapSpecialistDetail(result.data)
  }

  async saveDraft(review: IndependentEducationSpecialistSummary, title: string, body: string, key = newResearchFeedbackIdempotencyKey()): Promise<IndependentEducationReviewSummary> {
    validateRef(review.review_ref, reviewRefPattern, '研究教育复核编号无效。')
    validateMutation(review.state_version, key)
    if ((review.status !== 'SHARED' && review.status !== 'DRAFT')
      || title.trim().length < 1 || title.length > 120 || body.trim().length < 1 || body.length > 4000) {
      throw new RealApiError('VALIDATION_FAILED', '草稿内容或复核状态无效。')
    }
    const result = await requestIndependentEducationReview<unknown>({
      method: 'POST', path: `/api/v1/school/independent-education-reviews/${encodeURIComponent(review.review_ref)}/draft`,
      body: { expected_version: review.state_version, title, body }, idempotencyKey: key,
    })
    return unwrapEducationReview(result.data)
  }

  async publish(review: IndependentEducationSpecialistSummary, key = newResearchFeedbackIdempotencyKey()): Promise<IndependentEducationReviewSummary> {
    validateRef(review.review_ref, reviewRefPattern, '研究教育复核编号无效。')
    validateMutation(review.state_version, key)
    if (review.status !== 'DRAFT') throw new RealApiError('VALIDATION_FAILED', '当前记录尚不能发布。')
    const result = await requestIndependentEducationReview<unknown>({
      method: 'POST', path: `/api/v1/school/independent-education-reviews/${encodeURIComponent(review.review_ref)}/publish`,
      body: { expected_version: review.state_version }, idempotencyKey: key,
    })
    return unwrapEducationReview(result.data)
  }

  async revoke(review: IndependentEducationSpecialistSummary, key = newResearchFeedbackIdempotencyKey()): Promise<IndependentEducationReviewSummary> {
    validateRef(review.review_ref, reviewRefPattern, '研究教育复核编号无效。')
    validateMutation(review.state_version, key)
    if (review.status !== 'PUBLISHED') throw new RealApiError('VALIDATION_FAILED', '当前记录尚未发布。')
    const result = await requestIndependentEducationReview<unknown>({
      method: 'POST', path: `/api/v1/school/independent-education-reviews/${encodeURIComponent(review.review_ref)}/revoke`,
      body: { expected_version: review.state_version }, idempotencyKey: key,
    })
    return unwrapEducationReview(result.data)
  }
}

export const studentIndependentEducationReviews = new StudentIndependentEducationReviewService()
export const specialistIndependentEducationReviews = new SpecialistIndependentEducationReviewService()
export const newIndependentEducationReviewIdempotencyKey = newResearchFeedbackIdempotencyKey
