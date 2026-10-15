from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from database_layer.enums import AuditResult
from database_layer.school_research_education_jobs import (
    GENERAL_EDUCATION_POLICY_VERSION,
    ResearchEducationJobClaim,
    ResearchEducationJobErrorCode,
)

from smhai_backend.adapters.school_research_education_candidates import (
    SchoolResearchEducationCandidatePersistenceAdapter,
)
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.models import BackendRole
from smhai_backend.domains.research_general_education.prompt import (
    PROMPT_ID,
    PROMPT_SHA256,
    PROMPT_VERSION,
)
from smhai_backend.domains.research_general_education.schemas import (
    ResearchGeneralEducationInputReviewReceipt,
)
from smhai_backend.domains.research_general_education.service import (
    SAFETY_POLICY_VERSION,
    ResearchGeneralEducationPolicyPins,
    canonical_input_context_sha256,
)

from .test_school_research_education_candidates_service import (
    actor,
    candidate_payload,
)

_POLICY_HASH = "1" * 64
_SOURCE_MANIFEST = "2" * 64


def adapter(**changes):
    values = {
        "enabled": True,
        "school_id": 17,
        "school_study_ref": "SCHOOL_STUDY_SYNTHETIC",
        "policy_hash": _POLICY_HASH,
        "source_manifest_sha256": _SOURCE_MANIFEST,
        "source_package_ref": "R3_PACKAGE_SYNTHETIC",
        "source_study_ref": "R3_STUDY_SYNTHETIC",
        "study_use_policy": None,
    }
    values.update(changes)
    return SchoolResearchEducationCandidatePersistenceAdapter(None, **values)


def _row(payload, **changes):
    provenance = payload.provenance
    adapter_for_hash = adapter()
    values = dict(
        study_ref="SCHOOL_STUDY_SYNTHETIC",
        policy_version="RESEARCH_GENERAL_EDUCATION_DRAFT_V1",
        policy_hash=provenance.policy_hash,
        source_manifest_sha256=provenance.source_manifest_sha256,
        purpose="RESEARCH_SIMULATION",
        research_only=True,
        psychological_interpretation_allowed=False,
        publication_status="not_approved_for_publication_or_operational_use",
        safety_policy_version=SAFETY_POLICY_VERSION,
        content_revision=1,
        status="HELD",
        state_version=1,
        content_sha256=adapter_for_hash._payload_sha256(payload),
        scope=SimpleNamespace(response_origin="PUBLIC_OBSERVED"),
        payload_schema_version="school-research-general-education-candidate.v1",
        cipher_format_version="enc.v1",
        key_version="key-v1",
        payload_ciphertext=b"ciphertext",
        retrieval_id=provenance.retrieval_id,
        retrieval_bundle_sha256=provenance.retrieval_bundle_sha256,
        prompt_ref=provenance.prompt_id,
        prompt_version=provenance.prompt_version,
        prompt_sha256=provenance.prompt_sha256,
        model_ref=provenance.model_id,
        model_digest_sha256=provenance.model_digest_sha256,
        runtime_version=provenance.runtime_version,
        input_safety_action=provenance.input_safety_action,
        retrieval_safety_action=provenance.retrieval_safety_action,
        output_safety_action=provenance.output_safety_action,
    )
    values.update(changes)
    return SimpleNamespace(**values)


def _education_job_claim(**changes):
    now = datetime(2026, 10, 15, 11, 30, tzinfo=UTC)
    values = {
        "id": 91,
        "job_ref": "REJ_education_review_001",
        "school_id": 17,
        "research_session_id": 11,
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
        "policy_version": GENERAL_EDUCATION_POLICY_VERSION,
        "policy_hash": _POLICY_HASH,
        "purpose": "RESEARCH_SIMULATION",
        "research_only": True,
        "publication_status": "not_approved_for_publication_or_operational_use",
        "status": "LEASED",
        "attempt_count": 1,
        "next_attempt_at": None,
        "lease_expires_at": now + timedelta(minutes=5),
        "last_error_code": None,
        "created_at": now,
        "updated_at": now,
        "lease_owner": "worker-synthetic",
        "lease_token": "lease-token-synthetic",
    }
    values.update(changes)
    return ResearchEducationJobClaim(**values)


def _input_review_receipt(claim, *, configured=None, **changes):
    configured = configured or adapter()
    pins = ResearchGeneralEducationPolicyPins(
        policy_hash=configured.policy_hash,
        source_package_ref=configured.source_package_ref,
        source_study_ref=configured.source_study_ref,
        source_manifest_sha256=configured.source_manifest_sha256,
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
        "decision_id": "DEC_adapter_fixture_001",
        "review_ref": "REVIEW_adapter_fixture_001",
        "trace_id": f"TRACE_{token}",
        "canonical_input_sha256": canonical_input_context_sha256(policy_pins=pins),
        "policy_version": GENERAL_EDUCATION_POLICY_VERSION,
        "policy_hash": configured.policy_hash,
        "safety_policy_version": SAFETY_POLICY_VERSION,
        "source_package_ref": configured.source_package_ref,
        "source_study_ref": configured.source_study_ref,
        "source_manifest_sha256": configured.source_manifest_sha256,
        "source_age_scope": "14-17",
        "prompt_id": PROMPT_ID,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": PROMPT_SHA256,
    }
    values.update(changes)
    return ResearchGeneralEducationInputReviewReceipt(**values)


def test_input_review_expiry_is_bounded_by_remaining_retention():
    configured = adapter()
    receipt = _input_review_receipt(_education_job_claim(), configured=configured)
    now = datetime(2026, 10, 15, tzinfo=UTC)
    retention = now + timedelta(hours=2)
    evidence = configured._input_review_evidence(
        receipt, now=now, retention_due_at=retention
    )
    assert evidence.expires_at == retention
    with pytest.raises(BackendError):
        configured._input_review_evidence(receipt, now=now, retention_due_at=now)


def _finalize_harness(configured, claim, *, revoked=False):
    from database_layer.school_research_education_input_reviews import (
        ResearchEducationInputReviewScope,
    )

    now = datetime(2026, 10, 15, 11, 30, tzinfo=UTC)
    scope = ResearchEducationInputReviewScope(
        research_session_id=claim.research_session_id,
        school_id=claim.school_id,
        task_id=claim.task_id,
        class_id=claim.class_id,
        task_enrollment_id=claim.task_enrollment_id,
        subject_id=claim.subject_id,
        task_binding_id=claim.task_binding_id,
        profile_version_id=claim.profile_version_id,
        profile_ref=claim.profile_ref,
        profile_version_number=claim.profile_version_number,
        profile_sha256=claim.profile_sha256,
        response_origin=claim.response_origin,
    )
    events = []

    class InputReviewRepository:
        async def create_pending(self, **kwargs):
            events.append(("create_pending", kwargs, active_uow[0]))
            return SimpleNamespace(input_review_ref="REIR_synthetic")

    class JobRepository:
        async def require_active_claim(self, **kwargs):
            assert kwargs["job_id"] == claim.id
            return claim

        async def finish(self, **kwargs):
            events.append(("finish", kwargs, active_uow[0]))
            return kwargs["status"]

    class AuditRepository:
        async def append(self, **kwargs):
            events.append(("audit", kwargs, active_uow[0]))

    active_uow = []

    class UnitOfWork:
        research_education_jobs = JobRepository()
        research_education_input_reviews = InputReviewRepository()
        audit = AuditRepository()

        async def __aenter__(self):
            active_uow.append(self)
            return self

        async def __aexit__(self, *_args):
            return False

    async def live_claim_scope(_uow, _claim, *, now):
        assert now == now_fixed
        if revoked:
            raise BackendError(ErrorCode.FORBIDDEN)
        return claim, object(), object(), "RSESS_synthetic", scope, None

    now_fixed = now
    configured._require_enabled = lambda: None
    configured._now = lambda: (now, now)
    configured._uow = UnitOfWork
    configured._live_claim_scope = live_claim_scope
    return events


def test_disabled_or_unpinned_candidate_policy_fails_closed():
    with pytest.raises(BackendError) as raised:
        adapter(enabled=False)._require_enabled()
    assert raised.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE

    with pytest.raises(BackendError) as raised:
        adapter(policy_hash=None)._require_enabled()
    assert raised.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE


async def test_wrong_school_is_hidden_before_scope_resolution():
    configured = adapter()
    with pytest.raises(BackendError) as raised:
        await configured._active_task(
            object(),
            replace(actor(BackendRole.PSYCHOLOGICAL_SPECIALIST), school_id=18),
            "TASK_demo",
            at=datetime.now(UTC),
        )
    assert raised.value.code is ErrorCode.RESOURCE_NOT_FOUND


@pytest.mark.parametrize("response_origin", ["PUBLIC_OBSERVED", "MODEL_GENERATED"])
async def test_active_task_rechecks_current_assigned_specialist_and_observed_binding(
    response_origin,
):
    configured = adapter()
    task = SimpleNamespace(id=23, class_id=5)
    binding = SimpleNamespace(response_origin=response_origin)
    assignment = SimpleNamespace(specialist_membership_role_id=7)

    async def require_actor(_uow, _actor, _role, _at):
        return 101, 7

    async def get_task(_uow, _actor, _task_ref, *, lock):
        assert lock is True
        return task

    async def active_assignment(_uow, _actor, _task, *, at, lock):
        assert lock is True
        return assignment

    async def task_scope(_uow, _actor, _task, _at):
        return binding, object()

    configured._require_actor = require_actor
    configured._task = get_task
    configured._active_assignment = active_assignment
    configured._require_task_study_scope = task_scope

    if response_origin == "MODEL_GENERATED":
        with pytest.raises(BackendError) as raised:
            await configured._active_task(
                object(),
                actor(BackendRole.PSYCHOLOGICAL_SPECIALIST),
                "TASK_demo",
                at=datetime.now(UTC),
            )
        assert raised.value.code is ErrorCode.RESOURCE_NOT_FOUND
    else:
        result = await configured._active_task(
            object(), actor(BackendRole.PSYCHOLOGICAL_SPECIALIST), "TASK_demo", at=datetime.now(UTC)
        )
        assert result == (task, binding, 7)


async def test_revoked_specialist_assignment_fails_closed():
    configured = adapter()
    task = SimpleNamespace(id=23, class_id=5)

    async def require_actor(_uow, _actor, _role, _at):
        return 101, 7

    async def get_task(_uow, _actor, _task_ref, *, lock):
        return task

    async def revoked_assignment(_uow, _actor, _task, *, at, lock):
        raise BackendError(ErrorCode.RESOURCE_NOT_FOUND)

    configured._require_actor = require_actor
    configured._task = get_task
    configured._active_assignment = revoked_assignment

    with pytest.raises(BackendError) as raised:
        await configured._active_task(
            object(), actor(BackendRole.PSYCHOLOGICAL_SPECIALIST), "TASK_demo", at=datetime.now(UTC)
        )
    assert raised.value.code is ErrorCode.RESOURCE_NOT_FOUND


async def test_generation_job_list_is_current_task_scoped_and_content_free(monkeypatch):
    from database_layer import models
    from sqlalchemy import select

    configured = adapter()
    monkeypatch.setattr(configured, "_require_enabled", lambda: None)
    configured._db_models = models
    monkeypatch.setattr(configured, "_select", select, raising=False)
    now = datetime(2026, 10, 15, tzinfo=UTC)
    monkeypatch.setattr(configured, "_now", lambda: (now, now))
    task = SimpleNamespace(id=23, class_id=31)
    binding = SimpleNamespace(
        binding_id=61,
        profile_version_id=71,
        profile_ref="PROMIS_SYNTHETIC",
        profile_version_number=3,
        profile_sha256="4" * 64,
    )

    async def active_task(_uow, _actor, _task_ref, *, at):
        assert at == now
        return task, binding, 7

    monkeypatch.setattr(configured, "_active_task", active_task)

    class Rows:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class Session:
        def __init__(self):
            self.statements = []

        async def scalar(self, statement):
            self.statements.append(statement)
            return 1

        async def execute(self, statement):
            self.statements.append(statement)
            if len(self.statements) == 2:
                return Rows([
                    SimpleNamespace(
                        _mapping={
                            "job_ref": "REJ_" + "a" * 64,
                            "status": "HELD",
                            "attempt_count": 1,
                            "last_error_code": None,
                            "created_at": now,
                            "updated_at": now,
                            "generation_round": 0,
                            "input_review_ref": None,
                        }
                    )
                ])
            return Rows([("HELD", 1)])

    class UnitOfWork:
        def __init__(self):
            self.session = Session()
            self.entered = self.exited = 0

        async def __aenter__(self):
            self.entered += 1
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            self.exited += 1
            return False

    uow = UnitOfWork()
    monkeypatch.setattr(configured, "_uow", lambda: uow, raising=False)

    result = await configured.school_research_education_candidate_generation_job_list(
        actor(BackendRole.PSYCHOLOGICAL_SPECIALIST), "TASK_demo", offset=0, limit=20
    )

    assert result["total"] == 1
    assert result["status_counts"]["HELD"] == 1
    assert result["items"] == [
        {
            "job_ref": "REJ_" + "a" * 64,
            "status": "HELD",
            "attempt_count": 1,
            "last_error_code": None,
            "created_at": now,
            "updated_at": now,
            "generation_round": 0,
            "input_review_ref": None,
        }
    ]
    assert uow.entered == uow.exited == 1
    assert len(uow.session.statements) == 3
    parameters = [
        set(statement.compile().params.values()) for statement in uow.session.statements
    ]
    assert all(_POLICY_HASH in values for values in parameters)
    assert all("RESEARCH_GENERAL_EDUCATION_DRAFT_V1" in values for values in parameters)
    assert all(task.id in values for values in parameters)
    assert all(binding.binding_id in values for values in parameters)
    selected = " ".join(str(column) for column in uow.session.statements[1].selected_columns)
    assert all(name in selected for name in ("job_ref", "status", "attempt_count", "created_at"))
    assert all(
        name not in selected
        for name in ("subject_id", "lease_owner", "lease_token", "payload")
    )


def test_new_payload_must_match_server_policy_source_and_model_pins():
    configured = adapter()
    payload = candidate_payload()
    assert configured._validate_new_payload(payload) is payload

    unpinned = payload.model_dump(mode="json")
    unpinned["provenance"]["source_manifest_sha256"] = "9" * 64
    with pytest.raises(BackendError) as raised:
        configured._validate_new_payload(unpinned)
    assert raised.value.code is ErrorCode.FORBIDDEN

    altered_excerpt = payload.model_dump(mode="json")
    altered_excerpt["source_cards"][0]["excerpt_text"] += " modified"
    with pytest.raises(BackendError) as raised:
        configured._validate_new_payload(altered_excerpt)
    assert raised.value.code is ErrorCode.FORBIDDEN


async def test_input_review_finalize_persists_exact_receipt_before_finishing_in_one_uow():
    claim = _education_job_claim()
    configured = adapter()
    receipt = _input_review_receipt(claim, configured=configured)
    events = _finalize_harness(configured, claim)

    disposition = await configured.finalize_education_job(
        claim,
        status="REVIEW_REQUIRED",
        error_code=ResearchEducationJobErrorCode.SAFETY_BLOCKED,
        input_review=receipt,
    )

    assert disposition == "REVIEW_REQUIRED"
    assert [event[0] for event in events] == ["create_pending", "finish"]
    assert events[0][2] is events[1][2]
    evidence = events[0][1]["evidence"]
    assert evidence.decision_id == receipt.decision_id
    assert evidence.safety_review_ref == receipt.review_ref
    assert evidence.safety_trace_id == receipt.trace_id
    assert evidence.safety_operation == "INPUT"
    assert evidence.safety_action == "REVIEW_REQUIRED"
    assert evidence.reason_codes == ("CONTENT_CONTROVERSIAL",)
    assert evidence.requires_human is True
    assert evidence.canonical_input_sha256 == receipt.canonical_input_sha256
    assert evidence.policy_hash == configured.policy_hash
    assert evidence.source_manifest_sha256 == configured.source_manifest_sha256
    assert evidence.prompt_id == PROMPT_ID
    assert evidence.expires_at == datetime(2026, 10, 16, 11, 30, tzinfo=UTC)
    assert events[1][1]["status"] == "REVIEW_REQUIRED"
    assert events[1][1]["error_code"] is ResearchEducationJobErrorCode.SAFETY_BLOCKED


@pytest.mark.parametrize(
    ("reason_code", "expected_audit_reason"),
    [
        ("RESEARCH_RUNTIME_FAILED", "RESEARCH_RUNTIME_FAILED"),
        ("UNTRUSTED_BUT_WELL_FORMED", "UNCLASSIFIED_OUTCOME"),
        ("raw reason text", None),
        (123, None),
    ],
)
async def test_terminal_reason_audit_is_safe_and_same_uow(
    reason_code, expected_audit_reason
):
    claim = _education_job_claim()
    configured = adapter()
    events = _finalize_harness(configured, claim)

    disposition = await configured.finalize_education_job(
        claim,
        status="FAILED",
        error_code=ResearchEducationJobErrorCode.GENERATION_FAILED,
        reason_code=reason_code,
    )

    assert disposition == "FAILED"
    assert events[0][0] == "finish"
    assert events[0][1]["status"] == "FAILED"
    assert events[0][1]["error_code"] is ResearchEducationJobErrorCode.GENERATION_FAILED
    if expected_audit_reason is None:
        assert [event[0] for event in events] == ["finish"]
        return
    assert [event[0] for event in events] == ["finish", "audit"]
    audit = events[1][1]
    assert events[0][2] is events[1][2]
    assert audit["action"] == "school_research_education_job.terminal"
    assert audit["resource_type"] == "school_research_education_job"
    assert audit["resource_public_id"] == claim.job_ref
    assert audit["result"] is AuditResult.FAILURE
    token = hashlib.sha256(
        f"{claim.job_ref}:{claim.attempt_count}".encode("ascii")
    ).hexdigest()[:32]
    assert audit["trace_id"] == f"TRACE_{token}"
    assert audit["safe_metadata"] == {
        "source": GENERAL_EDUCATION_POLICY_VERSION,
        "state": "FAILED",
        "reason_code": expected_audit_reason,
    }


@pytest.mark.parametrize(
    "invalid_receipt", ["wrong_trace", "wrong_pin", "wrong_digest", "wrong_type"]
)
async def test_invalid_receipt_cannot_create_pending_review_or_finish_job(invalid_receipt):
    claim = _education_job_claim()
    configured = adapter()
    receipt = _input_review_receipt(claim, configured=configured)
    if invalid_receipt == "wrong_trace":
        receipt = _input_review_receipt(
            claim, configured=configured, trace_id="TRACE_wrong_binding"
        )
    elif invalid_receipt == "wrong_pin":
        receipt = _input_review_receipt(
            claim, configured=configured, source_manifest_sha256="9" * 64
        )
    elif invalid_receipt == "wrong_digest":
        receipt = _input_review_receipt(
            claim, configured=configured, canonical_input_sha256="9" * 64
        )
    else:
        receipt = SimpleNamespace(trace_id=receipt.trace_id)
    events = _finalize_harness(configured, claim)

    with pytest.raises(BackendError) as raised:
        await configured.finalize_education_job(
            claim,
            status="REVIEW_REQUIRED",
            error_code=ResearchEducationJobErrorCode.SAFETY_BLOCKED,
            input_review=receipt,
        )

    assert raised.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert events == []


async def test_nonreview_status_cannot_persist_input_review_receipt():
    claim = _education_job_claim()
    configured = adapter()
    receipt = _input_review_receipt(claim, configured=configured)
    events = _finalize_harness(configured, claim)

    with pytest.raises(BackendError) as raised:
        await configured.finalize_education_job(
            claim,
            status="FAILED",
            error_code=ResearchEducationJobErrorCode.GENERATION_FAILED,
            input_review=receipt,
        )

    assert raised.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert events == []


async def test_revoked_scope_cancels_job_without_persisting_input_review():
    claim = _education_job_claim()
    configured = adapter()
    receipt = _input_review_receipt(claim, configured=configured)
    events = _finalize_harness(configured, claim, revoked=True)

    disposition = await configured.finalize_education_job(
        claim,
        status="REVIEW_REQUIRED",
        error_code=ResearchEducationJobErrorCode.SAFETY_BLOCKED,
        input_review=receipt,
    )

    assert disposition == "CANCELLED"
    assert [event[0] for event in events] == ["finish", "audit"]
    assert events[0][1]["status"] == "CANCELLED"
    assert events[0][1]["error_code"] is None
    assert events[0][2] is events[1][2]
    assert events[1][1]["result"] is AuditResult.DENIED
    assert events[1][1]["safe_metadata"] == {
        "source": GENERAL_EDUCATION_POLICY_VERSION,
        "state": "CANCELLED",
        "reason_code": "SCOPE_REVOKED",
    }


def test_candidate_readback_checks_row_payload_provenance_and_content_hash():
    configured = adapter()
    payload = candidate_payload()
    configured.protection = SimpleNamespace(
        decrypt_json=lambda _encrypted: payload.model_dump(mode="python")
    )

    result = configured._payload_from_row(_row(payload))
    assert result.provenance.model_digest_sha256 == payload.provenance.model_digest_sha256
    assert result.source_cards[0].excerpt_text == payload.source_cards[0].excerpt_text

    tampered = _row(payload, model_ref="other-model")
    with pytest.raises(BackendError) as raised:
        configured._payload_from_row(tampered)
    assert raised.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE

    with pytest.raises(BackendError) as raised:
        configured._payload_from_row(_row(payload, content_sha256="0" * 64))
    assert raised.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE


async def test_worker_live_claim_locks_task_scope_before_job_lease():
    from database_layer import models
    from database_layer.school_research_education_jobs import ResearchEducationJobClaim
    from sqlalchemy import select

    claim = ResearchEducationJobClaim(
        id=91,
        job_ref="REDJOB_synthetic",
        school_id=17,
        research_session_id=11,
        task_id=23,
        class_id=31,
        task_enrollment_id=41,
        subject_id=51,
        task_binding_id=61,
        profile_version_id=71,
        profile_ref="PROMIS_SYNTHETIC",
        profile_version_number=3,
        profile_sha256="1" * 64,
        response_origin="PUBLIC_OBSERVED",
        policy_version="RESEARCH_GENERAL_EDUCATION_DRAFT_V1",
        policy_hash=_POLICY_HASH,
        purpose="RESEARCH_SIMULATION",
        research_only=True,
        publication_status="not_approved_for_publication_or_operational_use",
        status="LEASED",
        attempt_count=1,
        next_attempt_at=None,
        lease_expires_at=datetime(2026, 10, 15, 12, tzinfo=UTC),
        last_error_code=None,
        created_at=datetime(2026, 10, 15, 11, tzinfo=UTC),
        updated_at=datetime(2026, 10, 15, 11, tzinfo=UTC),
        lease_owner="worker-synthetic",
        lease_token="token-synthetic",
    )
    scope = SimpleNamespace(
        research_session_id=11,
        school_id=17,
        task_id=23,
        class_id=31,
        task_enrollment_id=41,
        subject_id=51,
        task_binding_id=61,
        profile_version_id=71,
        profile_ref="PROMIS_SYNTHETIC",
        profile_version_number=3,
        profile_sha256="1" * 64,
        response_origin="PUBLIC_OBSERVED",
    )
    events = []

    class Session:
        def __init__(self):
            self.scalar_calls = 0

        async def scalar(self, _statement):
            self.scalar_calls += 1
            if self.scalar_calls == 1:
                events.append("task_lock")
                return SimpleNamespace(id=23, class_id=31)
            return "SCHOOL_synthetic"

    class JobRepository:
        async def require_active_claim(self, **kwargs):
            assert kwargs["job_id"] == claim.id
            events.append("job_lease_lock")
            return claim

    configured = adapter()
    configured._db_models = models
    configured._db_enums = SimpleNamespace(
        DataOrigin=SimpleNamespace(SYNTHETIC=SimpleNamespace(value="SYNTHETIC"))
    )
    configured._select = select

    async def require_assignment(_uow, _task, *, at):
        events.append("assignment_lock")

    async def require_profile_scope(_uow, _actor, _task, _now):
        events.append("profile_scope")
        return (
            SimpleNamespace(
                binding_id=61,
                response_origin="PUBLIC_OBSERVED",
                profile_version_id=71,
                profile_ref="PROMIS_SYNTHETIC",
                profile_version_number=3,
                profile_sha256="1" * 64,
            ),
            None,
        )

    async def session_ref(_uow, _actor, _task, session_id):
        assert session_id == claim.research_session_id
        events.append("session_ref")
        return "RSESS_synthetic"

    async def current_scope(_uow, _actor, _task, **kwargs):
        assert kwargs["lock"] is True
        events.append("session_scope_lock")
        return scope, None, None, None, None

    configured._require_active_specialist_assignment = require_assignment
    configured._require_task_study_scope = require_profile_scope
    configured._session_ref = session_ref
    configured._current_scope = current_scope
    uow = SimpleNamespace(
        session=Session(),
        research_education_jobs=JobRepository(),
    )

    result = await configured._live_claim_scope(
        uow, claim, now=datetime(2026, 10, 15, 11, 30, tzinfo=UTC)
    )

    assert result[0] is claim
    assert events == [
        "task_lock",
        "assignment_lock",
        "profile_scope",
        "session_ref",
        "session_scope_lock",
        "job_lease_lock",
    ]


async def test_claim_with_wrong_policy_hash_is_denied_and_only_cancelled():
    from database_layer.school_research_education_jobs import ResearchEducationJobClaim

    claim = ResearchEducationJobClaim(
        id=91,
        job_ref="REDJOB_synthetic",
        school_id=17,
        research_session_id=11,
        task_id=23,
        class_id=31,
        task_enrollment_id=41,
        subject_id=51,
        task_binding_id=61,
        profile_version_id=71,
        profile_ref="PROMIS_SYNTHETIC",
        profile_version_number=3,
        profile_sha256="1" * 64,
        response_origin="PUBLIC_OBSERVED",
        policy_version="RESEARCH_GENERAL_EDUCATION_DRAFT_V1",
        policy_hash="9" * 64,
        purpose="RESEARCH_SIMULATION",
        research_only=True,
        publication_status="not_approved_for_publication_or_operational_use",
        status="LEASED",
        attempt_count=1,
        next_attempt_at=None,
        lease_expires_at=datetime(2026, 10, 15, 12, tzinfo=UTC),
        last_error_code=None,
        created_at=datetime(2026, 10, 15, 11, tzinfo=UTC),
        updated_at=datetime(2026, 10, 15, 11, tzinfo=UTC),
        lease_owner="worker-synthetic",
        lease_token="token-synthetic",
    )
    finished = []
    audit_events = []

    class JobRepository:
        async def require_active_claim(self, **kwargs):
            assert kwargs["job_id"] == claim.id
            return claim

        async def finish(self, **kwargs):
            finished.append(kwargs)

    class AuditRepository:
        async def append(self, **kwargs):
            audit_events.append(kwargs)

    class UnitOfWork:
        research_education_jobs = JobRepository()
        audit = AuditRepository()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    configured = adapter()
    configured._require_enabled = lambda: None
    configured._utc_now = lambda: datetime(2026, 10, 15, 11, 30, tzinfo=UTC)
    configured._uow = UnitOfWork
    disposition = await configured.finalize_education_job(
        claim, status="REVIEW_REQUIRED"
    )

    assert disposition == "CANCELLED"
    assert len(finished) == 1
    assert finished[0]["status"] == "CANCELLED"
    assert finished[0]["error_code"] is None
    assert len(audit_events) == 1
    assert audit_events[0]["result"] is AuditResult.DENIED
    assert audit_events[0]["safe_metadata"] == {
        "source": GENERAL_EDUCATION_POLICY_VERSION,
        "state": "CANCELLED",
        "reason_code": "SCOPE_REVOKED",
    }
