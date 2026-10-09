export type Role = 'student' | 'teacher' | 'psychological_specialist' | 'school_admin' | 'reviewer'

export type RiskLevel = 'normal' | 'attention' | 'high' | 'crisis'

export type GenerationStatus =
  | 'requested'
  | 'safety_blocked'
  | 'generating'
  | 'generated'
  | 'needs_review'
  | 'approved'
  | 'rejected'

export type ReviewStatus = 'pending' | 'approved' | 'rejected' | 'not_required'

export interface ApiEnvelope<T> {
  request_id: string
  trace_id: string
  data: T
}

export interface ApiErrorShape {
  code: string
  message: string
  details?: Record<string, unknown>
  retryable: boolean
}

export interface AssessmentDimension {
  theta: number
  se: number
  score: number | null
  band: 'unknown' | 'normal' | 'attention'
  interpretation_status: 'estimated' | 'insufficient_data' | 'not_scored'
  items_answered: number
}

export interface Assessment {
  schema_version: 'assessment.v1'
  assessment_id: string
  subject_id: string
  instrument: {
    instrument_id: string
    version: string
  }
  population_scope: string
  status: 'created' | 'in_progress' | 'completed' | 'abandoned' | 'invalid'
  dimensions: Record<string, AssessmentDimension>
  risk: {
    level: RiskLevel
    need_human_review: boolean
    reason_codes: string[]
    ruleset_id: string
  }
  response_summary: {
    items_answered: number
    duration_seconds: number | null
  }
  provenance: {
    source_adapter: string
    adapter_version: string
    cat_engine_version: string
    item_bank_version: string
  }
  timestamps: {
    started_at: string
    completed_at: string | null
  }
}

export interface Citation {
  citation_id: string
  chunk_id: string | null
  document_id?: string | null
  title?: string | null
  organization?: string | null
  locator?: string | null
  excerpt?: string
}

export interface GenerationSuggestion {
  text: string
  source_chunk_ids: string[]
}

export interface GenerationResult {
  schema_version: 'generation.v1'
  generation_id: string
  status: GenerationStatus
  target_role: 'student' | 'teacher' | 'parent' | 'admin'
  content: {
    summary: string
    observations: string[]
    suggestions: GenerationSuggestion[]
    disclaimer: string
  } | null
  safety: {
    precheck: 'passed' | 'warn' | 'blocked' | 'needs_review'
    postcheck: 'passed' | 'warn' | 'blocked' | 'needs_review'
    reason_codes: string[]
    human_review_required: boolean
  }
  provenance: {
    assessment_id: string
    retrieval_id: string
    prompt_id: string
    prompt_version: string
    model_id: string | null
    model_version: string | null
    runtime_version: string | null
    generation_status: 'EXECUTED' | 'NOT_RUN'
    candidate_source: 'MODEL_EXECUTED' | 'CONTROLLED_SYNTHETIC' | 'NOT_RUN'
  }
  review: {
    status: ReviewStatus
    reviewer_id: string | null
    reviewed_at: string | null
  }
  created_at: string
}

export interface Report {
  report_id: string
  assessment_id: string
  status: GenerationStatus
  generation_ids: string[]
}
