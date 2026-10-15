from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from database_layer import models
from database_layer.school_research_education_candidates import (
    ResearchEducationCandidateScope,
)
from database_layer.school_research_education_input_reviews import (
    ResearchEducationInputReviewScope,
)
from sqlalchemy import select

from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.research_general_education.input_review_policy import (
    INPUT_REVIEW_CONTINUATION_POLICY_SHA256,
    INPUT_REVIEW_CONTINUATION_POLICY_VERSION,
)
from smhai_backend.domains.research_general_education.schemas import (
    ResearchGeneralEducationCandidatePayload,
    ResearchGeneralEducationInputReviewReceipt,
    ResearchGeneralEducationReviewedInputAuthorization,
)
from smhai_backend.domains.research_general_education.service import (
    ResearchGeneralEducationPolicyPins,
    canonical_input_context_sha256,
)

from .test_school_research_education_candidates_adapter import (
    _education_job_claim,
    adapter,
)
from .test_school_research_education_candidates_adapter import (
    _row as candidate_row,
)
from .test_school_research_education_candidates_service import candidate_payload
from .test_school_research_education_input_reviews_adapter import (
    NOW as _REVIEW_NOW,
)
from .test_school_research_education_input_reviews_adapter import (
    authorized_row,
)
from .test_school_research_education_input_reviews_adapter import (
    trace_for_job as _trace_for_review_job,
)

NOW = datetime(2026, 10, 15, 11, 30, tzinfo=UTC)
_SCOPE_VALUES = {
    "research_session_id": 11,
    "school_id": 17,
    "task_id": 23,
    "class_id": 31,
    "task_enrollment_id": 41,
    "subject_id": 51,
    "task_binding_id": 61,
    "profile_version_id": 71,
    "profile_ref": "PROMIS_SYNTHETIC",
    "profile_version_number": 3,
    "profile_sha256": "1" * 64,
    "response_origin": "PUBLIC_OBSERVED",
}


def _scope():
    return ResearchEducationCandidateScope(**_SCOPE_VALUES)


def _review_scope():
    return ResearchEducationInputReviewScope(**_SCOPE_VALUES)


def _continuation_claim():
    return replace(
        _education_job_claim(),
        id=141,
        job_ref="REJ_" + "e" * 64,
        generation_round=1,
        input_review_id=101,
    )


def _authorized_review(*, status="CONTINUATION_AUTHORIZED", state_version=2, **changes):
    pins = ResearchGeneralEducationPolicyPins(
        policy_hash="1" * 64,
        source_package_ref="R3_PACKAGE_SYNTHETIC",
        source_study_ref="R3_STUDY_SYNTHETIC",
        source_manifest_sha256="2" * 64,
    )
    values = {
        "scope": _review_scope(),
        "policy_hash": "1" * 64,
        "source_package_ref": "R3_PACKAGE_SYNTHETIC",
        "source_study_ref": "R3_STUDY_SYNTHETIC",
        "source_manifest_sha256": "2" * 64,
        "canonical_input_sha256": canonical_input_context_sha256(policy_pins=pins),
        "created_at": _REVIEW_NOW - timedelta(minutes=5),
        "authorized_at": NOW - timedelta(minutes=5),
        "expires_at": NOW + timedelta(hours=4),
        "status": status,
        "state_version": state_version,
        "updated_at": NOW,
    }
    values.update(changes)
    base = authorized_row(**values)
    return base


def _reviewed_payload() -> ResearchGeneralEducationCandidatePayload:
    value = candidate_payload().model_dump(mode="python")
    value["provenance"]["input_safety_action"] = "REVIEW_REQUIRED"
    value["provenance"]["input_safety_reason_codes"] = ["CONTENT_CONTROVERSIAL"]
    return ResearchGeneralEducationCandidatePayload.model_validate(value, strict=True)


def _authorization(claim, review):
    receipt = ResearchGeneralEducationInputReviewReceipt(
        schema_version="school-research-general-education-input-review.v1",
        operation=review.safety_operation,
        action=review.safety_action,
        reason_codes=(review.safety_reason_code,),
        requires_human=review.safety_requires_human,
        decision_id=review.decision_id,
        review_ref=review.safety_review_ref,
        trace_id=review.safety_trace_id,
        canonical_input_sha256=review.canonical_input_sha256,
        policy_version=review.policy_version,
        policy_hash=review.policy_hash,
        safety_policy_version="safety-port-unversioned.v1",
        source_package_ref=review.source_package_ref,
        source_study_ref=review.source_study_ref,
        source_manifest_sha256=review.source_manifest_sha256,
        source_age_scope="14-17",
        prompt_id=review.prompt_id,
        prompt_version=review.prompt_version,
        prompt_sha256=review.prompt_sha256,
    )
    continuation_trace = _trace_for_review_job(claim.job_ref)
    return ResearchGeneralEducationReviewedInputAuthorization(
        input_review_ref=review.input_review_ref,
        authorized_state_version=2,
        receipt=receipt,
        continuation_job_ref=claim.job_ref,
        continuation_trace_id=continuation_trace,
        continuation_policy_version=INPUT_REVIEW_CONTINUATION_POLICY_VERSION,
        continuation_policy_hash=INPUT_REVIEW_CONTINUATION_POLICY_SHA256,
        expires_at=review.expires_at,
    )


class _Audit:
    def __init__(self, events, uow):
        self.events = events
        self.uow = uow

    async def append(self, **_kwargs):
        self.events.append(("audit", self.uow))


class _UnitOfWork:
    def __init__(self, events, input_reviews, candidates, jobs):
        self.events = events
        self.research_education_input_reviews = input_reviews
        self.research_education_candidates = candidates
        self.research_education_jobs = jobs
        self.session = SimpleNamespace()
        self.audit = _Audit(events, self)

    async def __aenter__(self):
        self.events.append(("enter", self))
        return self

    async def __aexit__(self, exc_type, _exc, _tb):
        self.events.append(("exit", self, exc_type))
        return False


def _persisted_candidate(scope, review, now):
    return SimpleNamespace(
        id=211,
        candidate_ref="REEDUC_synthetic_continuation",
        scope=scope,
        status="HELD",
        purpose="RESEARCH_SIMULATION",
        research_only=True,
        psychological_interpretation_allowed=False,
        publication_status="not_approved_for_publication_or_operational_use",
        student_feedback_eligible=False,
        state_version=1,
        content_revision=1,
        generation_round=1,
        input_review_id=review.id,
        input_review_state="CONSUMED",
        input_safety_action="REVIEW_REQUIRED",
        retrieval_safety_action="PROCEED",
        output_safety_action="PROCEED",
        created_at=now,
        updated_at=now,
        policy_hash="1" * 64,
    )


def _storage_harness(*, review_status="CONSUMED"):
    claim = _continuation_claim()
    consumed_at = NOW
    authorized = _authorized_review()
    consumed_review = replace(
        authorized,
        status="CONSUMED",
        state_version=3,
        consumed_at=consumed_at,
        updated_at=consumed_at,
    )
    revoked_review = replace(
        authorized,
        status="REVOKED",
        state_version=3,
        resolved_by_membership_role_id=222,
        resolved_at=consumed_at,
        updated_at=consumed_at,
    )
    current_review = revoked_review if review_status == "REVOKED" else authorized
    review = revoked_review if review_status == "REVOKED" else consumed_review
    authorization = _authorization(claim, authorized)
    events = []
    scope = _scope()
    task = SimpleNamespace(id=scope.task_id)
    persisted_candidate = _persisted_candidate(scope, review, consumed_at)

    class InputReviewRepository:
        async def consume_for_candidate(self, **kwargs):
            assert kwargs["claim"] == claim
            assert kwargs["scope"] == review.scope
            assert kwargs["grant_policy_version"] == INPUT_REVIEW_CONTINUATION_POLICY_VERSION
            assert kwargs["grant_policy_hash"] == INPUT_REVIEW_CONTINUATION_POLICY_SHA256
            assert kwargs["trace_id"] == authorization.continuation_trace_id
            events.append(("consume", uow))
            return consumed_review

        async def get_for_task(self, **_kwargs):
            return current_review

    class CandidateRepository:
        async def create_held(self, **kwargs):
            assert kwargs["claim"] == claim
            assert kwargs["input_review"] is review
            events.append(("create", uow))
            return persisted_candidate

    class JobRepository:
        async def finish(self, **kwargs):
            assert kwargs["job_id"] == claim.id
            assert kwargs["status"] == "HELD"
            events.append(("finish", uow))
            return SimpleNamespace(
                status="HELD",
                research_session_id=claim.research_session_id,
                policy_hash=claim.policy_hash,
            )

    uow = _UnitOfWork(events, InputReviewRepository(), CandidateRepository(), JobRepository())
    async def review_ref_lookup(_statement):
        return current_review.input_review_ref

    uow.session.scalar = review_ref_lookup
    configured = adapter()
    configured._require_enabled = lambda: None
    configured._db_enums = SimpleNamespace(
        AuditResult=SimpleNamespace(SUCCESS="SUCCESS")
    )
    configured.input_review_continuation_enabled = True
    configured._db_models = models
    configured._select = select
    configured.protection = SimpleNamespace(
        encrypt_json=lambda _body, *, payload_schema_version: SimpleNamespace(
            ciphertext=b"synthetic-ciphertext",
            cipher_format_version="enc.v1",
            key_version="key-v1",
            payload_schema_version=payload_schema_version,
        )
    )
    configured._now = lambda: (NOW, NOW.replace(tzinfo=None))
    configured._uow = lambda: uow

    async def live_scope(_uow, supplied_claim, *, now):
        assert supplied_claim == claim
        assert now == NOW
        return claim, task, SimpleNamespace(school_id=17), "RSESS_synthetic", scope, None

    async def active_authorizer(_uow, _task, *, at, membership_role_id):
        assert at == NOW
        assert membership_role_id == authorized.authorized_by_membership_role_id

    async def original_scope(_uow, _actor, _task, _row, *, at, lock):
        assert at == NOW and lock is True
        return scope, "RSESS_synthetic"

    configured._live_claim_scope = live_scope
    configured._require_active_specialist_assignment = active_authorizer
    configured._current_input_review = original_scope
    return configured, claim, authorization, review, events, uow


@pytest.mark.asyncio
async def test_continuation_store_consumes_review_creates_held_candidate_and_finishes_in_one_uow():
    configured, claim, authorization, review, events, uow = _storage_harness()

    result = await configured.store_generated_candidate(
        claim,
        _reviewed_payload(),
        trace_id=authorization.continuation_trace_id,
        input_review=authorization,
    )

    assert result["status"] == "HELD"
    assert [event[0] for event in events] == [
        "enter", "consume", "create", "finish", "audit", "exit"
    ]
    assert all(event[1] is uow for event in events)
    assert review.status == "CONSUMED"


@pytest.mark.asyncio
async def test_revoked_continuation_grant_cannot_consume_or_persist_a_candidate():
    configured, claim, authorization, _review, events, _uow = _storage_harness(
        review_status="REVOKED"
    )

    with pytest.raises(BackendError) as raised:
        await configured.store_generated_candidate(
            claim,
            _reviewed_payload(),
            trace_id=authorization.continuation_trace_id,
            input_review=authorization,
        )

    assert raised.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert [event[0] for event in events] == ["enter", "exit"]


@pytest.mark.asyncio
async def test_forged_worker_capability_cannot_consume_or_persist_a_candidate():
    configured, claim, authorization, _review, events, _uow = _storage_harness()
    forged = authorization.model_copy(
        update={"continuation_job_ref": "REJ_" + "0" * 64}
    )

    with pytest.raises(BackendError) as raised:
        await configured.store_generated_candidate(
            claim,
            _reviewed_payload(),
            trace_id=authorization.continuation_trace_id,
            input_review=forged,
        )

    assert raised.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert [event[0] for event in events] == ["enter", "exit"]


class _LineageSession:
    def __init__(self, values):
        self.values = list(values)

    async def scalar(self, _statement):
        return self.values.pop(0)


class _LineageReviewRepository:
    def __init__(self, review):
        self.review = review

    async def get_for_task(self, **_kwargs):
        return self.review


def _lineage_fixture(*, candidate_trace_id=None):
    configured = adapter()
    configured._db_models = models
    configured._select = select
    scope = _scope()
    claim = _continuation_claim()
    review = _authorized_review(
        status="CONSUMED",
        state_version=3,
        consumed_at=NOW,
        updated_at=NOW,
    )
    job = SimpleNamespace(
        id=claim.id,
        job_ref=claim.job_ref,
        **_SCOPE_VALUES,
        policy_version=claim.policy_version,
        policy_hash=claim.policy_hash,
        status="HELD",
        attempt_count=1,
        generation_round=1,
        input_review_id=review.id,
    )
    original = SimpleNamespace(
        id=review.job_id,
        job_ref=review.job_ref,
        **_SCOPE_VALUES,
        policy_version=review.policy_version,
        policy_hash=review.policy_hash,
        generation_round=0,
        input_review_id=None,
        status="REVIEW_REQUIRED",
        attempt_count=1,
        last_error_code="SAFETY_BLOCKED",
    )
    continuation_trace = _trace_for_review_job(claim.job_ref)
    row = candidate_row(
        candidate_payload(),
        job_id=claim.id,
        scope=scope,
        generation_round=1,
        input_review_id=review.id,
        input_review_state="CONSUMED",
        input_safety_action="REVIEW_REQUIRED",
        retrieval_safety_action="PROCEED",
        output_safety_action="PROCEED",
        created_at=NOW,
        trace_id=candidate_trace_id or continuation_trace,
    )
    uow = SimpleNamespace(
        session=_LineageSession([job, review.input_review_ref, original]),
        research_education_input_reviews=_LineageReviewRepository(review),
    )
    return configured, uow, row


@pytest.mark.asyncio
async def test_continuation_candidate_read_rejects_trace_not_bound_to_round_one_job():
    configured, uow, row = _lineage_fixture(candidate_trace_id="TRACE_unbound")

    with pytest.raises(BackendError) as raised:
        await configured.verify_candidate_input_lineage_in_uow(uow, row)

    assert raised.value.code is ErrorCode.WORKFLOW_CONFLICT


@pytest.mark.asyncio
async def test_continuation_candidate_read_accepts_exact_consumed_sidecar_job_and_trace():
    configured, uow, row = _lineage_fixture()

    await configured.verify_candidate_input_lineage_in_uow(uow, row)

    assert uow.session.values == []
