from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import pytest
from database_layer.school_research_education_jobs import ResearchEducationJobErrorCode

from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.research_programme_generation.schemas import (
    CLAIM_BOUNDARY_VERSION,
    STUDY_REF,
    ResearchProgrammeCandidate,
    ResearchProgrammeCitation,
    ResearchProgrammeOutcome,
    ResearchProgrammeSafetyEvidence,
)
from smhai_backend.domains.school_research_programme_generation.worker import (
    ResearchProgrammeWorker,
    ResearchProgrammeWorkerResult,
)

_POLICY_SHA = "a" * 64
_STUDY_SHA = "b" * 64


class _GenerationService:
    async def generate(self, **_kwargs):
        raise AssertionError("generation is not called in this projection test")


class _PersistenceAdapter:
    async def authorize_programme_claim(self, _claim):
        return True

    async def store_generated_candidate(self, _candidate):
        return {}


def _claim(**overrides):
    values = {
        "id": 17,
        "job_ref": "REJ_0123456789abcdef",
        "school_id": 2,
        "research_session_id": 3,
        "task_id": 4,
        "class_id": 5,
        "task_enrollment_id": 6,
        "subject_id": 7,
        "task_binding_id": 8,
        "profile_version_id": 9,
        "profile_ref": "promis-profile",
        "profile_version_number": 3,
        "profile_sha256": "c" * 64,
        "response_origin": "PUBLIC_OBSERVED",
        "policy_version": "RESEARCH_STAFF_PROGRAMME_POLICY_V1",
        "policy_hash": _POLICY_SHA,
        "attempt_count": 1,
        "lease_owner": "staff-worker-2",
        "lease_token": "opaque-lease-token",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _worker():
    return ResearchProgrammeWorker(
        school_id=2,
        persistence=None,
        persistence_adapter=_PersistenceAdapter(),
        generation_service=_GenerationService(),
        concurrency_lock=asyncio.Lock(),
        worker_id="staff-programme-2",
        processor_policy_sha256=_POLICY_SHA,
        study_policy_sha256=_STUDY_SHA,
        school_study_ref="HUNNU_PROMIS_HISTORICAL_REPLAY_2026_R1",
    )


def _held_outcome():
    citation = ResearchProgrammeCitation(
        chunk_id="CHUNK_RESEARCH_001",
        layer="theory",
        source_id="RAG-THEORY-002",
        title="Research source",
        publisher="Public source",
        year=2021,
        locator="Section 1",
        source_url="https://example.org/research",
        license="CC BY",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        attribution="Attribution retained.",
        source_extraction_sha256="d" * 64,
        excerpt_sha256="e" * 64,
        source_population="school programme research",
        certainty="source-stated",
    )
    safety = (
        ResearchProgrammeSafetyEvidence(
            stage="INPUT", action="PROCEED", reason_codes=("CLEAR",),
            trace_id="TRACE_1234567890abcdef", requires_human=False,
        ),
        ResearchProgrammeSafetyEvidence(
            stage="RETRIEVAL", action="PROCEED", reason_codes=("CLEAR",),
            trace_id="TRACE_1234567890abcdef", requires_human=False,
        ),
        ResearchProgrammeSafetyEvidence(
            stage="OUTPUT", action="PROCEED_WITH_BOUNDARY", reason_codes=("CLEAR",),
            trace_id="TRACE_1234567890abcdef", requires_human=False,
        ),
    )
    candidate = ResearchProgrammeCandidate(
        programme_ref="PROGRAMME_SCHOOL_CONNECTEDNESS_REFERENCE_V1",
        title="Staff planning reference",
        body="A planning option is to review schoolwide routines. [CHUNK_RESEARCH_001]",
        citations=(citation,),
        request_id="REQ_1234567890abcdef",
        trace_id="TRACE_1234567890abcdef",
        generation_id="GEN_1234567890abcdef",
        retrieval_id="RETR_1234567890abcdef",
        source_manifest_sha256="f" * 64,
        study_ref=STUDY_REF,
        valid_through_month="2027-06",
        prompt_id="PROMPT_staff_school_programme_research_v1",
        prompt_version="1.2.0",
        prompt_sha256="1" * 64,
        retrieval_bundle_sha256="2" * 64,
        chunk_set_sha256="3" * 64,
        source_set_sha256="4" * 64,
        safety_evidence=safety,
        model_version="qwen2.5:7b-instruct-q4_K_M",
        runtime_version="runtime-v1",
        model_digest="845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e",
    )
    return ResearchProgrammeOutcome(
        status="HELD",
        reason_code="AWAITING_INTERNAL_RESEARCH_REVIEW",
        candidate=candidate,
    )


def test_claim_mapping_is_staff_only_and_runtime_context_has_no_session_payload():
    worker = _worker()
    claim = _claim()
    generated = worker._generated_candidate(claim, _held_outcome())

    assert generated.job.policy_version == "RESEARCH_STAFF_PROGRAMME_POLICY_V1"
    assert generated.job.policy_hash == _POLICY_SHA
    assert generated.task_scope.response_origin == "PUBLIC_OBSERVED"
    assert generated.study_ref == "HUNNU_PROMIS_HISTORICAL_REPLAY_2026_R1"
    assert generated.source_study_ref == STUDY_REF
    assert generated.output_boundary == "STAFF_REFERENCE_ONLY"
    assert generated.claim_boundary_status == "ACCEPTED"
    assert generated.claim_boundary_version == CLAIM_BOUNDARY_VERSION
    assert generated.claim_boundary_version != generated.safety_policy_version
    assert generated.content.citations[0].citation_id == "S1"
    citation = generated.content.citations[0]
    assert "Section 1" in citation.source_locator
    assert "CC BY" in citation.source_locator
    assert "https://creativecommons.org/licenses/by/4.0/" in citation.source_locator
    assert "Attribution retained." in citation.source_locator
    assert "answer" not in repr(generated).casefold()
    assert "session_ref" not in repr(worker._context(claim)).casefold()
    assert type(worker._now()) is datetime


def test_worker_rejects_unpinned_rag_source_study_reference():
    worker = _worker()
    outcome = _held_outcome()
    invalid_candidate = replace(outcome.candidate, study_ref="untrusted-source-study")
    with pytest.raises(ValueError, match="source study reference"):
        worker._generated_candidate(_claim(), replace(outcome, candidate=invalid_candidate))


def test_old_no_personalized_policy_claim_is_never_sent_to_processor():
    worker = _worker()
    old_claim = _claim(
        policy_version="NO_RESEARCH_PERSONALIZED_POLICY_V1",
        policy_hash=None,
    )
    assert worker._valid_claim(old_claim) is False
    assert ResearchProgrammeWorkerResult.STALE_LEASE.value == "STALE_LEASE"


def test_no_evidence_abstains_and_crisis_action_never_generates_candidate():
    worker = _worker()
    no_evidence = SimpleNamespace(status="ABSTAINED", reason_code="RESEARCH_EVIDENCE_INCOMPLETE")
    assert worker._disposition(no_evidence) == (
        "ABSTAINED", ResearchEducationJobErrorCode.SOURCE_UNQUALIFIED
    )
    crisis = SimpleNamespace(status="HALTED", safety_action="CRISIS_ROUTE")
    assert worker._disposition(crisis) == (
        "CRISIS_ROUTED", ResearchEducationJobErrorCode.SAFETY_BLOCKED
    )


@pytest.mark.asyncio
async def test_invalid_runtime_response_finishes_for_review_without_retry_or_regeneration():
    class _InvalidResponseGeneration:
        calls = 0

        async def generate(self, **_kwargs):
            self.calls += 1
            raise BackendError(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="invalid structured research response",
            )

    class _FinalizingAdapter(_PersistenceAdapter):
        def __init__(self):
            self.finalized = []
            self.retries = []

        async def finalize_programme_job(self, claim, *, status, error_code=None):
            self.finalized.append((claim, status, error_code))
            return status

        async def retry_programme_job(self, claim, *, error_code):
            self.retries.append((claim, error_code))

    worker = _worker()
    generation = _InvalidResponseGeneration()
    persistence_adapter = _FinalizingAdapter()
    claim = _claim()

    async def claim_once():
        return [claim]

    worker._claim_one = claim_once
    worker.generation_service = generation
    worker.persistence_adapter = persistence_adapter

    result = await worker.run_once()

    assert result is ResearchProgrammeWorkerResult.REVIEW_REQUIRED
    assert generation.calls == 1
    assert len(persistence_adapter.finalized) == 1
    assert persistence_adapter.finalized[0][1:] == (
        "REVIEW_REQUIRED",
        ResearchEducationJobErrorCode.DEPENDENCY_INVALID_RESPONSE,
    )
    assert persistence_adapter.retries == []


@pytest.mark.asyncio
async def test_transient_runtime_timeout_still_uses_bounded_retry_classification():
    class _TimeoutGeneration:
        calls = 0

        async def generate(self, **_kwargs):
            self.calls += 1
            raise BackendError(ErrorCode.DEPENDENCY_TIMEOUT, detail="upstream timeout")

    class _RetryingAdapter(_PersistenceAdapter):
        def __init__(self):
            self.retries = []
            self.finalized = []

        async def retry_programme_job(self, claim, *, error_code):
            self.retries.append((claim, error_code))

        async def finalize_programme_job(self, claim, *, status, error_code=None):
            self.finalized.append((claim, status, error_code))
            return status

    worker = _worker()
    generation = _TimeoutGeneration()
    persistence_adapter = _RetryingAdapter()
    claim = _claim()

    async def claim_once():
        return [claim]

    worker._claim_one = claim_once
    worker.generation_service = generation
    worker.persistence_adapter = persistence_adapter

    result = await worker.run_once()

    assert result is ResearchProgrammeWorkerResult.RETRY
    assert generation.calls == 1
    assert persistence_adapter.retries == [
        (claim, ResearchEducationJobErrorCode.UPSTREAM_TIMEOUT)
    ]
    assert persistence_adapter.finalized == []


@pytest.mark.asyncio
async def test_unexpected_generation_failure_persists_only_fixed_stage_code():
    class _UnexpectedGeneration:
        async def generate(self, **_kwargs):
            raise RuntimeError("sensitive candidate text must not be persisted")

    class _RetryingAdapter(_PersistenceAdapter):
        def __init__(self):
            self.retries = []

        async def retry_programme_job(self, claim, *, error_code):
            self.retries.append((claim, error_code))

    worker = _worker()
    persistence_adapter = _RetryingAdapter()
    claim = _claim()

    async def claim_once():
        return [claim]

    worker._claim_one = claim_once
    worker.generation_service = _UnexpectedGeneration()
    worker.persistence_adapter = persistence_adapter

    result = await worker.run_once()

    assert result is ResearchProgrammeWorkerResult.RETRY
    assert persistence_adapter.retries == [
        (claim, ResearchEducationJobErrorCode.INTERNAL_FAILURE_GENERATION)
    ]
    assert "sensitive candidate text" not in repr(persistence_adapter.retries)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_stage", "expected_code"),
    (
        ("projection", ResearchEducationJobErrorCode.INTERNAL_FAILURE_CANDIDATE_PROJECTION),
        ("store", ResearchEducationJobErrorCode.INTERNAL_FAILURE_CANDIDATE_STORE),
    ),
)
async def test_local_candidate_contract_failure_is_reviewed_without_retry(
    failure_stage, expected_code
):
    class _HeldGeneration:
        calls = 0

        async def generate(self, **_kwargs):
            self.calls += 1
            return _held_outcome()

    class _FinalizingAdapter(_PersistenceAdapter):
        def __init__(self):
            self.finalized = []
            self.retries = []

        async def store_generated_candidate(self, _candidate):
            if failure_stage == "store":
                raise BackendError(
                    ErrorCode.VALIDATION_FAILED,
                    detail="private candidate body must not enter diagnostics",
                )
            return {}

        async def finalize_programme_job(self, claim, *, status, error_code=None):
            self.finalized.append((claim, status, error_code))
            return status

        async def retry_programme_job(self, claim, *, error_code):
            self.retries.append((claim, error_code))

    worker = _worker()
    generation = _HeldGeneration()
    persistence_adapter = _FinalizingAdapter()
    claim = _claim()

    async def claim_once():
        return [claim]

    if failure_stage == "projection":
        def invalid_projection(_claim, _outcome):
            raise TypeError("generated body must not enter diagnostics")

        worker._generated_candidate = invalid_projection

    worker._claim_one = claim_once
    worker.generation_service = generation
    worker.persistence_adapter = persistence_adapter

    result = await worker.run_once()

    assert result is ResearchProgrammeWorkerResult.REVIEW_REQUIRED
    assert generation.calls == 1
    assert persistence_adapter.finalized == [
        (
            claim,
            "REVIEW_REQUIRED",
            expected_code,
        )
    ]
    assert persistence_adapter.retries == []
    assert "generated body" not in repr(persistence_adapter.finalized)
    assert "private candidate body" not in repr(persistence_adapter.finalized)
