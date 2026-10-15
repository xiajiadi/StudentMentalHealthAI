from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from database_layer.school_research_education_jobs import (
    GENERAL_EDUCATION_POLICY_VERSION,
    ResearchEducationJobClaim,
    ResearchEducationJobErrorCode,
)

from smhai_backend.domains.research_general_education.input_review_policy import (
    INPUT_REVIEW_CONTINUATION_POLICY_SHA256,
    INPUT_REVIEW_CONTINUATION_POLICY_VERSION,
)
from smhai_backend.domains.research_general_education.schemas import (
    ResearchGeneralEducationBoundaryDiagnostic,
    ResearchGeneralEducationCandidatePayload,
    ResearchGeneralEducationInputReviewReceipt,
    ResearchGeneralEducationOutcome,
    ResearchGeneralEducationOutputSafetyDiagnostic,
    ResearchGeneralEducationReviewedInputAuthorization,
)
from smhai_backend.domains.research_general_education.service import (
    EXPECTED_MODEL_DIGEST_SHA256,
    EXPECTED_MODEL_ID,
    EXPECTED_MODEL_VERSION,
    PROMPT_ID,
    PROMPT_SHA256,
    PROMPT_VERSION,
    SAFETY_POLICY_VERSION,
    ResearchGeneralEducationPolicyPins,
    canonical_input_context_sha256,
)
from smhai_backend.domains.school_research_general_education_generation.worker import (
    ResearchGeneralEducationWorker,
    ResearchGeneralEducationWorkerResult,
)
from smhai_backend.domains.support.schemas import GenerationContent, Suggestion, SupportCitation

_NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
_POLICY_HASH = "a" * 64
_MANIFEST_HASH = "b" * 64


def _claim(**changes):
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
        "profile_ref": "synthetic-profile",
        "profile_version_number": 3,
        "profile_sha256": "c" * 64,
        "response_origin": "PUBLIC_OBSERVED",
        "policy_version": GENERAL_EDUCATION_POLICY_VERSION,
        "policy_hash": _POLICY_HASH,
        "purpose": "RESEARCH_SIMULATION",
        "research_only": True,
        "publication_status": "not_approved_for_publication_or_operational_use",
        "status": "LEASED",
        "attempt_count": 1,
        "next_attempt_at": None,
        "lease_expires_at": _NOW + timedelta(minutes=5),
        "last_error_code": None,
        "created_at": _NOW,
        "updated_at": _NOW,
        "lease_owner": "general-education-2",
        "lease_token": "synthetic-lease-token",
    }
    values.update(changes)
    return ResearchEducationJobClaim(**values)


def _payload():
    excerpt = "公开来源保留的人群范围和局限。"
    from hashlib import sha256

    excerpt_hash = sha256(excerpt.encode("utf-8")).hexdigest()
    chunk_id = "CHUNK_R3_A"
    source_card = {
        "chunk_id": chunk_id,
        "record_id": "RECORD_R3_A",
        "source_id": "SOURCE_R3_A",
        "title": "Public source",
        "organization": "Public organization",
        "canonical_url": "https://example.org/source",
        "record_locator": "section-1",
        "source_population_scope": "secondary school students",
        "source_language": "zh",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": "Public organization",
        "excerpt_sha256": excerpt_hash,
        "excerpt_text": excerpt,
        "consumer_age_min": 14,
        "consumer_age_max": 17,
    }
    suffix = (
        "; source population: secondary school students; source: https://example.org/source; "
        "license: CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/); "
        "attribution: Public organization"
    )
    return ResearchGeneralEducationCandidatePayload(
        schema_version="school-research-general-education-candidate.v1",
        content=GenerationContent(
            summary="一般教育信息",
            observations=["公开资料中的一般观察"],
            suggestions=[Suggestion(text="查看来源资料", source_chunk_ids=[chunk_id])],
            disclaimer="供研究任务中的专业人员复核。",
        ),
        citations=[
            SupportCitation(
                citation_id="C1",
                chunk_id=chunk_id,
                document_id="DOC_R3_A",
                title="Public source",
                organization="Public organization",
                locator=f"section-1{suffix}",
                rank=1,
                source_version="R3-v1",
                source_hash=f"sha256:{excerpt_hash}",
            )
        ],
        source_cards=[source_card],
        provenance={
            "policy_version": GENERAL_EDUCATION_POLICY_VERSION,
            "policy_hash": _POLICY_HASH,
            "safety_policy_version": SAFETY_POLICY_VERSION,
            "source_package_ref": "R3_PACKAGE_SYNTHETIC",
            "source_study_ref": "R3_STUDY_SYNTHETIC",
            "source_manifest_sha256": _MANIFEST_HASH,
            "source_age_scope": "14-17",
            "retrieval_id": "RETR_education_1",
            "retrieval_bundle_sha256": "d" * 64,
            "cited_chunk_ids": [chunk_id],
            "generation_id": "GEN_education_1",
            "prompt_id": PROMPT_ID,
            "prompt_version": PROMPT_VERSION,
            "prompt_sha256": PROMPT_SHA256,
            "model_id": EXPECTED_MODEL_ID,
            "model_version": EXPECTED_MODEL_VERSION,
            "model_digest_sha256": EXPECTED_MODEL_DIGEST_SHA256,
            "runtime_version": "runtime-pinned-v1",
            "runtime_attempt_count": 1,
            "runtime_retry_count": 0,
            "runtime_fallback_count": 0,
            "runtime_fallback_attempted": False,
            "runtime_local_only": True,
            "input_safety_action": "PROCEED",
            "input_safety_reason_codes": ["CLEAR"],
            "retrieval_safety_action": "PROCEED",
            "retrieval_safety_reason_codes": ["CLEAR"],
            "output_safety_action": "PROCEED",
            "output_safety_reason_codes": ["CLEAR"],
        },
    )


class _Repository:
    def __init__(self, claims=None, *, error=None):
        self.claims = list(claims or [])
        self.error = error
        self.calls = []

    async def claim_next(
        self,
        *,
        school_id,
        lease_owner,
        limit,
        lease_seconds,
        max_attempts,
        policy_version,
        generation_round,
        now,
    ):
        kwargs = {
            "school_id": school_id,
            "lease_owner": lease_owner,
            "limit": limit,
            "lease_seconds": lease_seconds,
            "max_attempts": max_attempts,
            "policy_version": policy_version,
            "generation_round": generation_round,
            "now": now,
        }
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return [
            claim
            for claim in self.claims
            if getattr(claim, "generation_round", 0) == generation_round
        ][:limit]


class _Uow:
    def __init__(self, repository):
        self.research_education_jobs = repository

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class _Persistence:
    def __init__(self, repository):
        self.repository = repository
        self.uow_count = 0

    def _uow(self):
        self.uow_count += 1
        return _Uow(self.repository)


class _Adapter:
    def __init__(self, *, authorized=True, input_review_continuation_enabled=False):
        self.authorized = authorized
        self.input_review_continuation_enabled = input_review_continuation_enabled
        self.authorized_claims = []
        self.finalized = []
        self.finalize_kwargs = []
        self.stored = []
        self.review_authorization = None

    async def authorize_education_claim(self, claim):
        self.authorized_claims.append(claim)
        return self.authorized

    async def finalize_education_job(self, claim, *, status, error_code=None, **kwargs):
        self.finalized.append((claim, status, error_code))
        self.finalize_kwargs.append(kwargs)
        return status

    async def load_input_review_authorization(self, claim):
        return self.review_authorization

    async def store_generated_candidate(self, claim, payload, *, trace_id, input_review=None):
        self.stored.append((claim, payload, trace_id, input_review))
        return {
            "candidate_ref": "REEDUC_synthetic_candidate",
            "status": "HELD",
            "state_version": 1,
            "purpose": "RESEARCH_SIMULATION",
            "research_only": True,
            "psychological_interpretation_allowed": False,
            "publication_status": "not_approved_for_publication_or_operational_use",
            "student_feedback_eligible": False,
        }


class _Generation:
    def __init__(self, outcome=None, *, error=None):
        self.outcome = outcome
        self.error = error
        self.calls = []
        self.reviewed_calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.outcome

    async def generate_reviewed_input(self, **kwargs):
        self.reviewed_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.outcome


def _worker(
    *,
    claim=None,
    adapter=None,
    generation=None,
    repository=None,
    lock=None,
    persistence=None,
    continuation_enabled=False,
):
    claim_repo = repository or _Repository([claim or _claim()])
    active_persistence = persistence or _Persistence(claim_repo)
    return ResearchGeneralEducationWorker(
        school_id=2,
        policy_hash=_POLICY_HASH,
        persistence=active_persistence,
        persistence_adapter=adapter or _Adapter(),
        generation_service=generation
        or _Generation(
            ResearchGeneralEducationOutcome(
                status="ABSTAINED", reason_code="ZERO_EVIDENCE"
            )
        ),
        concurrency_lock=lock or asyncio.Lock(),
        worker_id="general-education-2",
        input_review_continuation_enabled=continuation_enabled,
        clock=lambda: _NOW,
    )


@pytest.mark.asyncio
async def test_held_candidate_is_authorized_then_stored_once_with_system_context():
    claim = _claim()
    adapter = _Adapter()
    payload = _payload()
    generation = _Generation(
        ResearchGeneralEducationOutcome(
            status="HELD",
            reason_code="AWAITING_SOURCE_LIMIT_AND_CONTENT_REVIEW",
            candidate=payload,
        )
    )
    worker = _worker(claim=claim, adapter=adapter, generation=generation)

    result = await worker.run_once()

    assert result is ResearchGeneralEducationWorkerResult.HELD
    assert adapter.authorized_claims == [claim]
    assert len(generation.calls) == 1
    assert set(generation.calls[0]) == {"caller_role", "request_context"}
    assert generation.calls[0]["caller_role"] == "SYSTEM"
    context = generation.calls[0]["request_context"]
    assert context.request_id == context.trace_id.replace("TRACE_", "REQ_")
    assert claim.job_ref not in {context.request_id, context.trace_id}
    assert len(adapter.stored) == 1
    assert adapter.stored[0][:2] == (claim, payload)
    assert adapter.stored[0][2] == context.trace_id
    assert adapter.finalized == []


@pytest.mark.asyncio
async def test_claim_uses_policy_attempt_one_and_db_error_never_calls_model():
    repository = _Repository(error=RuntimeError("database detail must not escape"))
    generation = _Generation(
        ResearchGeneralEducationOutcome(status="ABSTAINED", reason_code="ZERO_EVIDENCE")
    )
    worker = _worker(repository=repository, generation=generation)

    result = await worker.run_once()

    assert result is ResearchGeneralEducationWorkerResult.RETRY
    assert repository.calls == [
        {
            "school_id": 2,
            "lease_owner": "general-education-2",
            "limit": 1,
            "lease_seconds": 300,
            "max_attempts": 1,
            "policy_version": GENERAL_EDUCATION_POLICY_VERSION,
            "generation_round": 0,
            "now": _NOW,
        }
    ]
    assert generation.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claim",
    [
        _claim(policy_hash="f" * 64),
        _claim(response_origin="MODEL_GENERATED"),
        _claim(policy_version="NO_RESEARCH_PERSONALIZED_POLICY_V1", policy_hash=None),
    ],
)
async def test_mismatched_claim_is_cancelled_without_generation(claim):
    adapter = _Adapter()
    generation = _Generation()
    repository = _Repository([claim])
    persistence = _Persistence(repository)
    worker = _worker(
        claim=claim,
        adapter=adapter,
        generation=generation,
        repository=repository,
        persistence=persistence,
    )

    result = await worker.run_once()

    assert result is ResearchGeneralEducationWorkerResult.CANCELLED
    assert adapter.finalized == [(claim, "CANCELLED", None)]
    assert generation.calls == []
    assert adapter.stored == []


@pytest.mark.asyncio
async def test_unauthorized_claim_and_outcome_dispositions_never_store_candidate():
    claim = _claim()
    adapter = _Adapter(authorized=False)
    generation = _Generation()
    worker = _worker(claim=claim, adapter=adapter, generation=generation)

    result = await worker.run_once()

    assert result is ResearchGeneralEducationWorkerResult.CANCELLED
    assert adapter.finalized == [(claim, "CANCELLED", None)]
    assert generation.calls == []

    dispositions = (
        (
            "ABSTAINED",
            "ZERO_EVIDENCE",
            "ABSTAINED",
            ResearchEducationJobErrorCode.SOURCE_UNQUALIFIED,
        ),
        (
            "REVIEW_REQUIRED",
            "OUTPUT_SAFETY_STOP",
            "REVIEW_REQUIRED",
            ResearchEducationJobErrorCode.SAFETY_BLOCKED,
        ),
        (
            "CRISIS_ROUTED",
            "CRISIS_ROUTE",
            "CRISIS_ROUTED",
            ResearchEducationJobErrorCode.SAFETY_BLOCKED,
        ),
        (
            "FAILED",
            "RESEARCH_RUNTIME_FAILED",
            "FAILED",
            ResearchEducationJobErrorCode.GENERATION_FAILED,
        ),
    )
    for status, reason, expected, code in dispositions:
        adapter = _Adapter()
        generation = _Generation(ResearchGeneralEducationOutcome(status=status, reason_code=reason))
        worker = _worker(adapter=adapter, generation=generation)
        result = await worker.run_once()
        assert result.value == expected
        assert len(adapter.finalized) == 1
        assert adapter.finalized[0][1:] == (expected, code)
        assert adapter.finalize_kwargs == [{"reason_code": reason}]
        assert adapter.stored == []


@pytest.mark.asyncio
async def test_boundary_diagnostic_is_forwarded_without_candidate_text():
    diagnostic = ResearchGeneralEducationBoundaryDiagnostic(
        field_kind="OBSERVATION",
        field_index=2,
        category="CLINICAL",
        match_count=3,
    )
    adapter = _Adapter()
    generation = _Generation(
        ResearchGeneralEducationOutcome(
            status="ABSTAINED",
            reason_code="RESEARCH_CLAIM_BOUNDARY_REJECTED",
            boundary_diagnostic=diagnostic,
        )
    )
    worker = _worker(adapter=adapter, generation=generation)

    result = await worker.run_once()

    assert result is ResearchGeneralEducationWorkerResult.ABSTAINED
    assert adapter.finalize_kwargs == [
        {
            "reason_code": "RESEARCH_CLAIM_BOUNDARY_REJECTED",
            "boundary_diagnostic": diagnostic,
        }
    ]
    assert adapter.stored == []


@pytest.mark.asyncio
async def test_generation_exception_is_terminal_and_cancellation_leaves_single_attempt_lease():
    claim = _claim()
    adapter = _Adapter()
    generation = _Generation(error=TimeoutError("sensitive model detail"))
    worker = _worker(claim=claim, adapter=adapter, generation=generation)

    result = await worker.run_once()

    assert result is ResearchGeneralEducationWorkerResult.FAILED
    assert generation.calls[0]["caller_role"] == "SYSTEM"
    assert adapter.finalized == [
        (claim, "FAILED", ResearchEducationJobErrorCode.UPSTREAM_TIMEOUT)
    ]
    assert adapter.stored == []

    class _CancelledGeneration:
        calls = 0

        async def generate(self, **_kwargs):
            self.calls += 1
            raise asyncio.CancelledError

    cancelled_generation = _CancelledGeneration()
    cancelled_adapter = _Adapter()
    worker = _worker(
        claim=claim,
        adapter=cancelled_adapter,
        generation=cancelled_generation,
    )
    with pytest.raises(asyncio.CancelledError):
        await worker.run_once()
    assert cancelled_generation.calls == 1
    assert cancelled_adapter.finalized == []
    assert cancelled_adapter.stored == []


def _input_review_receipt(claim, **changes):
    pins = ResearchGeneralEducationPolicyPins(
        policy_hash=_POLICY_HASH,
        source_package_ref="R3_PACKAGE_SYNTHETIC",
        source_study_ref="R3_STUDY_SYNTHETIC",
        source_manifest_sha256=_MANIFEST_HASH,
    )
    token = hashlib.sha256(
        f"{claim.job_ref}:{claim.attempt_count}".encode("ascii")
    ).hexdigest()[:32]
    values = {
        "schema_version": "school-research-general-education-input-review.v1",
        "operation": "INPUT",
        "action": "REVIEW_REQUIRED",
        "reason_codes": ("CONTENT_CONTROVERSIAL",),
        "requires_human": True,
        "decision_id": "DEC_worker_fixture_001",
        "review_ref": "REVIEW_worker_fixture_001",
        "trace_id": f"TRACE_{token}",
        "canonical_input_sha256": canonical_input_context_sha256(policy_pins=pins),
        "policy_version": GENERAL_EDUCATION_POLICY_VERSION,
        "policy_hash": _POLICY_HASH,
        "safety_policy_version": SAFETY_POLICY_VERSION,
        "source_package_ref": pins.source_package_ref,
        "source_study_ref": pins.source_study_ref,
        "source_manifest_sha256": pins.source_manifest_sha256,
        "source_age_scope": "14-17",
        "prompt_id": PROMPT_ID,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": PROMPT_SHA256,
    }
    values.update(changes)
    return ResearchGeneralEducationInputReviewReceipt(**values)


@pytest.mark.asyncio
async def test_round_one_uses_only_typed_reviewed_path_and_binds_candidate_storage():
    claim = _claim(generation_round=1, input_review_id=52)
    receipt = _input_review_receipt(claim).model_copy(
        update={"trace_id": "TRACE_original_input_job"}
    )
    worker = _worker(claim=claim)
    context = worker._context(claim)
    authorization = ResearchGeneralEducationReviewedInputAuthorization(
        input_review_ref="REIR_" + "e" * 32,
        authorized_state_version=2,
        receipt=receipt,
        continuation_job_ref=claim.job_ref,
        continuation_trace_id=context.trace_id,
        continuation_policy_version=INPUT_REVIEW_CONTINUATION_POLICY_VERSION,
        continuation_policy_hash=INPUT_REVIEW_CONTINUATION_POLICY_SHA256,
        expires_at=_NOW + timedelta(hours=1),
    )
    adapter = _Adapter(input_review_continuation_enabled=True)
    adapter.review_authorization = authorization
    generation = _Generation(
        ResearchGeneralEducationOutcome(
            status="HELD",
            reason_code="AWAITING_SOURCE_LIMIT_AND_CONTENT_REVIEW",
            candidate=_payload(),
        )
    )
    repository = _Repository([claim])
    persistence = _Persistence(repository)
    worker = _worker(
        claim=claim,
        adapter=adapter,
        generation=generation,
        repository=repository,
        persistence=persistence,
        continuation_enabled=True,
    )

    result = await worker.run_once()

    assert result is ResearchGeneralEducationWorkerResult.HELD
    assert generation.calls == []
    assert len(generation.reviewed_calls) == 1
    assert generation.reviewed_calls[0] == {
        "caller_role": "SYSTEM",
        "request_context": worker._context(claim),
        "authorization": authorization,
    }
    assert adapter.stored[0][3] is authorization
    assert repository.calls[0]["generation_round"] == 1
    assert len(repository.calls) == 1
    assert persistence.uow_count == 1


@pytest.mark.asyncio
async def test_round_one_missing_grant_is_cancelled_without_generation_fallback():
    claim = _claim(generation_round=1, input_review_id=52)
    adapter = _Adapter(input_review_continuation_enabled=True)
    generation = _Generation()
    repository = _Repository([claim])
    worker = _worker(
        claim=claim,
        adapter=adapter,
        generation=generation,
        repository=repository,
        continuation_enabled=True,
    )

    result = await worker.run_once()

    assert result is ResearchGeneralEducationWorkerResult.CANCELLED
    assert adapter.finalized[0][1] == "CANCELLED"
    assert generation.calls == []
    assert generation.reviewed_calls == []
    assert adapter.stored == []


@pytest.mark.asyncio
async def test_enabled_claim_checks_reviewed_round_first_then_round_zero_in_one_uow():
    ordinary_claim = _claim()
    repository = _Repository([ordinary_claim])
    persistence = _Persistence(repository)
    adapter = _Adapter(input_review_continuation_enabled=True)
    generation = _Generation(
        ResearchGeneralEducationOutcome(status="ABSTAINED", reason_code="ZERO_EVIDENCE")
    )
    worker = _worker(
        claim=ordinary_claim,
        adapter=adapter,
        generation=generation,
        repository=repository,
        persistence=persistence,
        continuation_enabled=True,
    )

    result = await worker.run_once()

    assert result is ResearchGeneralEducationWorkerResult.ABSTAINED
    assert [call["generation_round"] for call in repository.calls] == [1, 0]
    assert all(call["max_attempts"] == 1 for call in repository.calls)
    assert persistence.uow_count == 1
    assert len(generation.calls) == 1


@pytest.mark.asyncio
async def test_disabled_worker_queries_only_round_zero_even_if_round_one_exists():
    continuation_claim = _claim(generation_round=1, input_review_id=52)
    repository = _Repository([continuation_claim])
    adapter = _Adapter(input_review_continuation_enabled=True)
    generation = _Generation()
    worker = _worker(
        claim=continuation_claim,
        adapter=adapter,
        generation=generation,
        repository=repository,
    )

    result = await worker.run_once()

    assert result is ResearchGeneralEducationWorkerResult.IDLE
    assert [call["generation_round"] for call in repository.calls] == [0]
    assert adapter.authorized_claims == []
    assert generation.calls == []


@pytest.mark.asyncio
async def test_worker_passes_only_valid_input_review_receipt_and_legacy_outcome_omits_kwarg():
    claim = _claim()
    adapter = _Adapter()
    receipt = _input_review_receipt(claim)
    generation = _Generation(
        ResearchGeneralEducationOutcome(
            status="REVIEW_REQUIRED",
            reason_code="INPUT_SAFETY_STOP",
            input_review=receipt,
        )
    )
    worker = _worker(claim=claim, adapter=adapter, generation=generation)

    result = await worker.run_once()

    assert result is ResearchGeneralEducationWorkerResult.REVIEW_REQUIRED
    assert adapter.finalized == [
        (claim, "REVIEW_REQUIRED", ResearchEducationJobErrorCode.SAFETY_BLOCKED)
    ]
    assert adapter.finalize_kwargs == [
        {"input_review": receipt, "reason_code": "INPUT_SAFETY_STOP"}
    ]
    assert adapter.stored == []

    legacy_adapter = _Adapter()
    legacy_worker = _worker(
        claim=claim,
        adapter=legacy_adapter,
        generation=_Generation(
            ResearchGeneralEducationOutcome(
                status="REVIEW_REQUIRED", reason_code="OUTPUT_SAFETY_STOP"
            )
        ),
    )
    legacy_result = await legacy_worker.run_once()

    assert legacy_result is ResearchGeneralEducationWorkerResult.REVIEW_REQUIRED
    assert legacy_adapter.finalized == [
        (claim, "REVIEW_REQUIRED", ResearchEducationJobErrorCode.SAFETY_BLOCKED)
    ]
    assert legacy_adapter.finalize_kwargs == [
        {"reason_code": "OUTPUT_SAFETY_STOP"}
    ]


@pytest.mark.asyncio
async def test_worker_forwards_only_typed_output_safety_diagnostic():
    claim = _claim()
    adapter = _Adapter()
    diagnostic = ResearchGeneralEducationOutputSafetyDiagnostic(
        action="REVIEW_REQUIRED",
        reason_codes=("CONTENT_UNSAFE",),
        requires_human=True,
    )
    worker = _worker(
        claim=claim,
        adapter=adapter,
        generation=_Generation(
            ResearchGeneralEducationOutcome(
                status="REVIEW_REQUIRED",
                reason_code="OUTPUT_SAFETY_STOP",
                output_safety_diagnostic=diagnostic,
            )
        ),
    )

    result = await worker.run_once()

    assert result is ResearchGeneralEducationWorkerResult.REVIEW_REQUIRED
    assert adapter.finalized == [
        (claim, "REVIEW_REQUIRED", ResearchEducationJobErrorCode.SAFETY_BLOCKED)
    ]
    assert adapter.finalize_kwargs == [
        {
            "reason_code": "OUTPUT_SAFETY_STOP",
            "output_safety_diagnostic": diagnostic,
        }
    ]
    assert adapter.stored == []


@pytest.mark.parametrize(
    ("action", "requires_human", "status", "result"),
    [
        (
            "BLOCK",
            False,
            "ABSTAINED",
            ResearchGeneralEducationWorkerResult.ABSTAINED,
        ),
        (
            "PROCEED",
            True,
            "REVIEW_REQUIRED",
            ResearchGeneralEducationWorkerResult.REVIEW_REQUIRED,
        ),
        (
            "CRISIS_ROUTE",
            True,
            "CRISIS_ROUTED",
            ResearchGeneralEducationWorkerResult.CRISIS_ROUTED,
        ),
    ],
)
def test_output_safety_diagnostic_maps_to_existing_safety_blocked_error(
    action, requires_human, status, result
):
    outcome = ResearchGeneralEducationOutcome(
        status=status,
        reason_code="OUTPUT_SAFETY_STOP",
        output_safety_diagnostic=ResearchGeneralEducationOutputSafetyDiagnostic(
            action=action,
            reason_codes=("CONTENT_UNSAFE",),
            requires_human=requires_human,
        ),
    )

    actual_status, error_code, worker_result = ResearchGeneralEducationWorker._disposition(
        outcome
    )

    assert actual_status == status
    assert error_code is ResearchEducationJobErrorCode.SAFETY_BLOCKED
    assert worker_result is result


@pytest.mark.asyncio
async def test_shared_lock_serializes_workers_and_start_stop_are_idempotent():
    shared_lock = asyncio.Lock()
    entered = asyncio.Event()
    release = asyncio.Event()

    class _BlockingGeneration:
        active = 0
        max_active = 0

        async def generate(self, **_kwargs):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            entered.set()
            await release.wait()
            self.active -= 1
            return ResearchGeneralEducationOutcome(status="ABSTAINED", reason_code="ZERO_EVIDENCE")

    first_claim = _claim()
    second_claim = replace(first_claim, id=18, job_ref="REJ_1123456789abcdef")
    first_repo = _Repository([first_claim])
    second_repo = _Repository([second_claim])
    generation = _BlockingGeneration()
    first = _worker(repository=first_repo, generation=generation, lock=shared_lock)
    second = _worker(repository=second_repo, generation=generation, lock=shared_lock)

    first_run = asyncio.create_task(first.run_once())
    await entered.wait()
    second_run = asyncio.create_task(second.run_once())
    await asyncio.sleep(0)
    assert second_repo.calls == []
    release.set()
    await asyncio.gather(first_run, second_run)
    assert generation.max_active == 1
    assert len(second_repo.calls) == 1

    idle_repo = _Repository([])
    poller = _worker(repository=idle_repo)
    started = poller.start()
    assert poller.start() is started
    await asyncio.sleep(0)
    await poller.stop(drain=True)
    assert started.done()
    assert idle_repo.calls
