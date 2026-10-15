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
    _canonical_mapping_sha256,
)
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.core.request_context import RequestContext
from smhai_backend.domains.models import BackendRole
from smhai_backend.domains.research_general_education.prompt import (
    PROMPT_ID,
    PROMPT_SHA256,
    PROMPT_VERSION,
    get_prompt_definition,
)
from smhai_backend.domains.research_general_education.schemas import (
    ResearchGeneralEducationBoundaryDiagnostic,
    ResearchGeneralEducationInputReviewReceipt,
    ResearchGeneralEducationOutputSafetyDiagnostic,
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
        generation_round=0,
        input_review_id=None,
        input_review_state=None,
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


def _authorized_input_review_dto(
    configured,
    *,
    prompt_version=PROMPT_VERSION,
    prompt_sha256=PROMPT_SHA256,
):
    from database_layer.school_research_education_input_reviews import (
        ResearchEducationInputReviewDTO,
        ResearchEducationInputReviewScope,
    )

    from smhai_backend.domains.research_general_education.input_review_policy import (
        INPUT_REVIEW_CONTINUATION_POLICY_VERSION,
        continuation_policy_sha256_for_prompt,
    )
    from smhai_backend.domains.research_general_education.prompt import PROMPT_ID

    claim = _education_job_claim(job_ref="REJ_" + "e" * 64)
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
    pins = ResearchGeneralEducationPolicyPins(
        policy_hash=configured.policy_hash,
        source_package_ref=configured.source_package_ref,
        source_study_ref=configured.source_study_ref,
        source_manifest_sha256=configured.source_manifest_sha256,
    )
    trace = "TRACE_" + hashlib.sha256(f"{claim.job_ref}:1".encode("ascii")).hexdigest()[:32]
    return ResearchEducationInputReviewDTO(
        id=301,
        input_review_ref="REIR_" + "f" * 32,
        job_id=claim.id,
        job_ref=claim.job_ref,
        scope=scope,
        decision_id="DEC_synthetic_authorized_input",
        safety_review_ref="REVIEW_synthetic_authorized_input",
        safety_trace_id=trace,
        safety_operation="INPUT",
        safety_action="REVIEW_REQUIRED",
        safety_reason_code="CONTENT_CONTROVERSIAL",
        safety_requires_human=True,
        canonical_input_sha256=canonical_input_context_sha256(
            policy_pins=pins,
            prompt_id=PROMPT_ID,
            prompt_version=prompt_version,
            prompt_sha256=prompt_sha256,
        ),
        policy_version=GENERAL_EDUCATION_POLICY_VERSION,
        policy_hash=configured.policy_hash,
        source_package_ref=configured.source_package_ref,
        source_study_ref=configured.source_study_ref,
        source_manifest_sha256=configured.source_manifest_sha256,
        prompt_id=PROMPT_ID,
        prompt_version=prompt_version,
        prompt_sha256=prompt_sha256,
        status="CONTINUATION_AUTHORIZED",
        state_version=2,
        expires_at=now + timedelta(hours=12),
        resolved_by_membership_role_id=None,
        resolved_at=None,
        trace_id=trace,
        retention_due_at=None,
        created_at=now - timedelta(minutes=30),
        updated_at=now,
        original_job_generation_round=0,
        grant_policy_version=INPUT_REVIEW_CONTINUATION_POLICY_VERSION,
        grant_policy_hash=continuation_policy_sha256_for_prompt(
            PROMPT_ID, prompt_version, prompt_sha256
        ),
        authorized_by_membership_role_id=73,
        authorized_at=now - timedelta(minutes=20),
        consumed_at=None,
    )


@pytest.mark.asyncio
async def test_output_review_round_one_requires_current_input_grant_and_prompt():
    from database_layer.models import SchoolResearchEducationInputReview
    from sqlalchemy import select

    from smhai_backend.domains.research_general_education.prompt import PROMPT_REGISTRY

    configured = adapter()
    current_review = _authorized_input_review_dto(configured)
    output_review = SimpleNamespace(
        generation_round=1,
        input_review_id=current_review.id,
        scope=current_review.scope,
        policy_version=current_review.policy_version,
        policy_hash=current_review.policy_hash,
        source_package_ref=current_review.source_package_ref,
        source_study_ref=current_review.source_study_ref,
        source_manifest_sha256=current_review.source_manifest_sha256,
        prompt_id=current_review.prompt_id,
        prompt_version=current_review.prompt_version,
        prompt_sha256=current_review.prompt_sha256,
        canonical_input_sha256=current_review.canonical_input_sha256,
    )

    class Session:
        async def scalar(self, _statement):
            return current_review.input_review_ref

    class InputReviews:
        async def get_for_task(self, **_kwargs):
            return current_review

    uow = SimpleNamespace(
        session=Session(),
        research_education_input_reviews=InputReviews(),
    )
    configured._db_models = SimpleNamespace(
        SchoolResearchEducationInputReview=SchoolResearchEducationInputReview
    )
    configured._select = select

    async def role_is_current(*_args, **_kwargs):
        return None

    async def original_review_is_current(*_args, **_kwargs):
        return None

    configured._require_active_specialist_assignment = role_is_current
    configured._current_input_review = original_review_is_current
    await configured._require_current_output_review_input_grant(
        uow,
        SimpleNamespace(id=current_review.scope.task_id),
        output_review,
        at=datetime(2026, 10, 15, 11, 30, tzinfo=UTC),
    )

    legacy_prompt = next(
        definition for key, definition in PROMPT_REGISTRY.items() if key[1] == "1.0.0"
    )
    legacy_review = _authorized_input_review_dto(
        configured,
        prompt_version=legacy_prompt.version,
        prompt_sha256=legacy_prompt.sha256,
    )
    legacy_output = SimpleNamespace(
        **{
            **output_review.__dict__,
            "input_review_id": legacy_review.id,
            "scope": legacy_review.scope,
            "prompt_version": legacy_review.prompt_version,
            "prompt_sha256": legacy_review.prompt_sha256,
            "canonical_input_sha256": legacy_review.canonical_input_sha256,
        }
    )
    current_review = legacy_review
    with pytest.raises(BackendError) as rejected:
        await configured._require_current_output_review_input_grant(
            uow,
            SimpleNamespace(id=legacy_review.scope.task_id),
            legacy_output,
            at=datetime(2026, 10, 15, 11, 30, tzinfo=UTC),
        )
    assert rejected.value.code is ErrorCode.WORKFLOW_CONFLICT


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
    class EventLog(list):
        output_review_status = None
        output_review_consume_calls = 0
        output_review_create_failure = False

    events = EventLog()

    class InputReviewRepository:
        async def create_pending(self, **kwargs):
            events.append(("create_pending", kwargs, active_uow[0]))
            return SimpleNamespace(input_review_ref="REIR_synthetic")

    class OutputReviewRepository:
        async def create_pending(self, **kwargs):
            events.append(("output_review_create_pending", kwargs, active_uow[0]))
            if events.output_review_create_failure:
                raise RuntimeError("synthetic persistence failure")
            events.output_review_status = "PENDING"
            return SimpleNamespace(output_review_ref="REOR_synthetic")

        async def consume_for_candidate(self, **kwargs):
            events.output_review_consume_calls += 1
            events.output_review_status = "CONSUMED"
            return kwargs

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
        research_education_output_reviews = OutputReviewRepository()
        audit = AuditRepository()

        class Session:
            class Nested:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args):
                    return False

            def begin_nested(self):
                return self.Nested()

        session = Session()

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


async def _generate_output_review_payload(claim, content):
    from tests.test_research_general_education import (
        _OutputReviewSafety,
        _Runtime,
        _service,
    )

    token = hashlib.sha256(
        f"{claim.job_ref}:{claim.attempt_count}".encode("ascii")
    ).hexdigest()[:32]
    context = RequestContext(request_id=f"REQ_{token}", trace_id=f"TRACE_{token}")
    runtime = _Runtime(content=content)
    service, _retriever = _service(runtime=runtime, safety=_OutputReviewSafety())
    result = await service.generate(
        caller_role="PSYCHOLOGICAL_SPECIALIST", request_context=context
    )
    assert result.status == "REVIEW_REQUIRED"
    assert result.reason_code == "OUTPUT_SAFETY_STOP"
    assert result.output_review_payload is not None
    return service, result.output_review_payload


def test_disabled_or_unpinned_candidate_policy_fails_closed():
    with pytest.raises(BackendError) as raised:
        adapter(enabled=False)._require_enabled()
    assert raised.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE

    with pytest.raises(BackendError) as raised:
        adapter(policy_hash=None)._require_enabled()
    assert raised.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE

    with pytest.raises(BackendError) as expired_source:
        adapter(source_valid_through=datetime.now(UTC) - timedelta(seconds=1))._require_enabled()
    assert expired_source.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE


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


def test_review_required_candidate_is_allowed_only_with_consumed_output_review_sidecar():
    payload = candidate_payload()
    provenance = payload.provenance.model_copy(
        update={
            "output_safety_action": "REVIEW_REQUIRED",
            "output_safety_reason_codes": ["CONTENT_CONTROVERSIAL"],
        }
    )
    reviewed_payload = payload.model_copy(update={"provenance": provenance})
    configured = adapter()

    with pytest.raises(BackendError) as missing_sidecar:
        configured._require_row_pins(_row(reviewed_payload))
    assert missing_sidecar.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE

    configured._require_row_pins(
        _row(
            reviewed_payload,
            output_review_id=91,
            output_review_state="CONSUMED",
        )
    )
    with pytest.raises(BackendError) as wrong_sidecar:
        configured._require_row_pins(
            _row(
                reviewed_payload,
                output_review_id=91,
                output_review_state="PENDING",
            )
        )
    assert wrong_sidecar.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE


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


async def test_boundary_diagnostic_audit_is_content_free_and_same_uow():
    claim = _education_job_claim()
    configured = adapter()
    events = _finalize_harness(configured, claim)
    diagnostic = ResearchGeneralEducationBoundaryDiagnostic(
        field_kind="OBSERVATION",
        field_index=2,
        category="CLINICAL",
        match_count=3,
    )

    disposition = await configured.finalize_education_job(
        claim,
        status="ABSTAINED",
        error_code=ResearchEducationJobErrorCode.GENERATION_FAILED,
        reason_code="RESEARCH_CLAIM_BOUNDARY_REJECTED",
        boundary_diagnostic=diagnostic,
    )

    assert disposition == "ABSTAINED"
    assert [event[0] for event in events] == ["finish", "audit", "audit"]
    assert events[0][2] is events[1][2] is events[2][2]
    terminal_audit = events[1][1]
    assert terminal_audit["action"] == "school_research_education_job.terminal"
    assert terminal_audit["safe_metadata"] == {
        "source": GENERAL_EDUCATION_POLICY_VERSION,
        "state": "ABSTAINED",
        "reason_code": "RESEARCH_CLAIM_BOUNDARY_REJECTED",
    }
    diagnostic_audit = events[2][1]
    assert diagnostic_audit["action"] == "school_research_education_job.claim_boundary"
    assert diagnostic_audit["resource_type"] == "school_research_education_job"
    assert diagnostic_audit["resource_public_id"] == claim.job_ref
    assert diagnostic_audit["result"] is AuditResult.FAILURE
    assert diagnostic_audit["trace_id"] == terminal_audit["trace_id"]
    assert diagnostic_audit["safe_metadata"] == {
        "source": GENERAL_EDUCATION_POLICY_VERSION,
        "state": "OBSERVATION",
        "reason_code": "CLINICAL",
        "count": 3,
    }


async def test_output_safety_diagnostic_audit_is_closed_content_free_and_trace_bound():
    claim = _education_job_claim()
    configured = adapter()
    events = _finalize_harness(configured, claim)
    diagnostic = ResearchGeneralEducationOutputSafetyDiagnostic(
        action="REVIEW_REQUIRED",
        reason_codes=("CONTENT_UNSAFE", "PROMPT_INJECTION"),
        requires_human=True,
    )

    disposition = await configured.finalize_education_job(
        claim,
        status="REVIEW_REQUIRED",
        error_code=ResearchEducationJobErrorCode.SAFETY_BLOCKED,
        reason_code="OUTPUT_SAFETY_STOP",
        output_safety_diagnostic=diagnostic,
    )

    assert disposition == "REVIEW_REQUIRED"
    assert [event[0] for event in events] == ["finish", "audit", "audit", "audit"]
    assert all(event[2] is events[0][2] for event in events)
    token = hashlib.sha256(f"{claim.job_ref}:{claim.attempt_count}".encode("ascii")).hexdigest()[
        :32
    ]
    assert events[1][1]["action"] == "school_research_education_job.terminal"
    assert events[1][1]["safe_metadata"]["reason_code"] == "OUTPUT_SAFETY_STOP"
    for event, code in zip(events[2:], diagnostic.reason_codes, strict=True):
        audit = event[1]
        assert audit["action"] == "school_research_education_job.output_safety"
        assert audit["resource_type"] == "school_research_education_job"
        assert audit["resource_public_id"] == claim.job_ref
        assert audit["result"] is AuditResult.FAILURE
        assert audit["trace_id"] == f"TRACE_{token}"
        assert audit["safe_metadata"] == {
            "schema_version": "research-output-safety-diagnostic.v1",
            "source": GENERAL_EDUCATION_POLICY_VERSION,
            "state": "REVIEW_REQUIRED",
            "reason_code": code,
            "count": 1,
        }
        assert set(audit["safe_metadata"]) == {
            "schema_version", "source", "state", "reason_code", "count"
        }


@pytest.mark.parametrize("failure_kind", ["payload_unavailable", "oversize", "persistence"])
async def test_optional_output_review_capture_failure_is_closed_and_keeps_safety_terminal(
    failure_kind,
):
    claim = _education_job_claim(job_ref="REJ_" + "b" * 64)
    configured = adapter()
    configured.study_use_policy = SimpleNamespace(
        ends_at=datetime(2026, 10, 16, 11, 30, tzinfo=UTC)
    )
    events = _finalize_harness(configured, claim)
    payload = None
    if failure_kind != "payload_unavailable":
        service, payload = await _generate_output_review_payload(
            claim,
            {
                "summary": "一般教育资料概述。",
                "observations": ["来源分别描述一般教育信息。"],
                "suggestions": [
                    {"text": "可以查看来源。", "source_chunk_ids": ["CHUNK_UNKNOWN"]}
                ],
                "disclaimer": "仅为一般资料。",
            },
        )
        configured.policy_hash = service.policy_pins.policy_hash
        configured.source_package_ref = service.policy_pins.source_package_ref
        configured.source_study_ref = service.policy_pins.source_study_ref
        configured.source_manifest_sha256 = service.policy_pins.source_manifest_sha256
        configured.source_cards = service.source_cards
        configured.protection = SimpleNamespace(
            encrypt_json=lambda *_args, **_kwargs: SimpleNamespace(
                ciphertext=(b"x" * 1_000_001 if failure_kind == "oversize" else b"cipher"),
                cipher_format_version="enc.v1",
                key_version="test-key",
                payload_schema_version="school-research-general-education-output-review.v1",
            )
        )
        if failure_kind == "persistence":
            events.output_review_create_failure = True

    diagnostic = ResearchGeneralEducationOutputSafetyDiagnostic(
        action="REVIEW_REQUIRED",
        reason_codes=("CONTENT_CONTROVERSIAL",),
        requires_human=True,
    )
    disposition = await configured.finalize_education_job(
        claim,
        status="REVIEW_REQUIRED",
        error_code=ResearchEducationJobErrorCode.SAFETY_BLOCKED,
        reason_code="OUTPUT_SAFETY_STOP",
        output_safety_diagnostic=diagnostic,
        output_review_payload=payload,
    )

    assert disposition == "REVIEW_REQUIRED"
    assert any(event[0] == "finish" for event in events)
    capture = next(
        event[1]
        for event in events
        if event[0] == "audit"
        and event[1]["action"] == "school_research_education_job.output_review_capture"
    )
    expected_code = {
        "payload_unavailable": "PAYLOAD_UNAVAILABLE",
        "oversize": "PAYLOAD_TOO_LARGE",
        "persistence": "PERSISTENCE_FAILED",
    }[failure_kind]
    assert capture["result"] is AuditResult.FAILURE
    assert capture["safe_metadata"] == {
        "schema_version": "research-output-review-capture.v1",
        "source": GENERAL_EDUCATION_POLICY_VERSION,
        "state": "NOT_SAVED",
        "reason_code": expected_code,
    }
    assert events.output_review_status is None
    assert events.output_review_consume_calls == 0
    assert "content" not in capture["safe_metadata"]


@pytest.mark.asyncio
async def test_output_review_savepoint_failure_allows_terminal_job_commit():
    from sqlalchemy import Column, Integer, MetaData, Table, create_engine, insert, select
    from sqlalchemy.orm import Session

    claim = _education_job_claim(job_ref="REJ_" + "d" * 64)
    service, payload = await _generate_output_review_payload(
        claim,
        {
            "summary": "一般教育资料概述。",
            "observations": ["来源分别描述一般教育信息。"],
            "suggestions": [
                {"text": "可以查看来源。", "source_chunk_ids": ["CHUNK_UNKNOWN"]}
            ],
            "disclaimer": "仅为一般资料。",
        },
    )
    configured = adapter(
        policy_hash=service.policy_pins.policy_hash,
        source_package_ref=service.policy_pins.source_package_ref,
        source_study_ref=service.policy_pins.source_study_ref,
        source_manifest_sha256=service.policy_pins.source_manifest_sha256,
        source_cards=service.source_cards,
    )
    configured.study_use_policy = SimpleNamespace(
        ends_at=datetime(2026, 10, 16, 11, 30, tzinfo=UTC)
    )
    configured.protection = SimpleNamespace(
        encrypt_json=lambda *_args, **_kwargs: SimpleNamespace(
            ciphertext=b"encrypted-review",
            cipher_format_version="enc.v1",
            key_version="test-key",
            payload_schema_version="school-research-general-education-output-review.v1",
        )
    )
    _finalize_harness(configured, claim)

    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    rows = Table("savepoint_probe", metadata, Column("id", Integer, primary_key=True))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(rows).values(id=1))

    completed = []
    audit_events = []

    class Jobs:
        async def require_active_claim(self, **_kwargs):
            return claim

        async def finish(self, **kwargs):
            await uow.session.execute(insert(rows).values(id=2))
            completed.append(kwargs["status"])
            return kwargs["status"]

    class OutputReviews:
        async def create_pending(self, **_kwargs):
            # The duplicate key raises IntegrityError inside the adapter's savepoint.
            await uow.session.execute(insert(rows).values(id=1))

    class Audit:
        async def append(self, **kwargs):
            audit_events.append(kwargs)

    class UnitOfWork:
        def __init__(self):
            self.session = AsyncSessionFacade(engine)
            self.research_education_jobs = Jobs()
            self.research_education_output_reviews = OutputReviews()
            self.research_education_input_reviews = SimpleNamespace()
            self.audit = Audit()

        async def __aenter__(self):
            await self.session.begin()
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            try:
                if exc_type is None:
                    await self.session.commit()
                else:
                    await self.session.rollback()
            finally:
                await self.session.close()
            return False

    uow = None

    class AsyncSessionFacade:
        def __init__(self, database_engine):
            self.sync_session = Session(database_engine)

        async def begin(self):
            self.sync_session.begin()

        async def execute(self, statement):
            return self.sync_session.execute(statement)

        def begin_nested(self):
            transaction = self.sync_session.begin_nested()

            class NestedContext:
                async def __aenter__(self):
                    return transaction.__enter__()

                async def __aexit__(self, exc_type, exc, traceback):
                    return transaction.__exit__(exc_type, exc, traceback)

            return NestedContext()

        async def commit(self):
            self.sync_session.commit()

        async def rollback(self):
            self.sync_session.rollback()

        async def close(self):
            self.sync_session.close()

    def new_uow():
        nonlocal uow
        uow = UnitOfWork()
        return uow

    configured._uow = new_uow
    diagnostic = ResearchGeneralEducationOutputSafetyDiagnostic(
        action="REVIEW_REQUIRED",
        reason_codes=("CONTENT_CONTROVERSIAL",),
        requires_human=True,
    )
    try:
        disposition = await configured.finalize_education_job(
            claim,
            status="REVIEW_REQUIRED",
            error_code=ResearchEducationJobErrorCode.SAFETY_BLOCKED,
            reason_code="OUTPUT_SAFETY_STOP",
            output_safety_diagnostic=diagnostic,
            output_review_payload=payload,
        )
        assert disposition == "REVIEW_REQUIRED"
        assert completed == ["REVIEW_REQUIRED"]
        assert any(
            event["action"] == "school_research_education_job.output_review_capture"
            and event["safe_metadata"]["reason_code"] == "PERSISTENCE_FAILED"
            for event in audit_events
        )
        with Session(engine) as check_session:
            committed_ids = list(check_session.scalars(select(rows.c.id)).all())
        assert committed_ids == [1, 2]
    finally:
        engine.dispose()


@pytest.mark.parametrize("invalid_kind", ["unknown_source_chunk", "business_invalid_content"])
async def test_output_review_keeps_structural_payload_until_candidate_validation(invalid_kind):
    from database_layer.school_research_education_output_reviews import (
        OUTPUT_REVIEW_PAYLOAD_SCHEMA_VERSION,
    )

    claim = _education_job_claim(job_ref="REJ_" + "c" * 64)
    if invalid_kind == "unknown_source_chunk":
        content = {
            "summary": "一般教育资料概述。",
            "observations": ["来源分别描述一般教育信息。"],
            "suggestions": [
                {"text": "可以查看来源。", "source_chunk_ids": ["CHUNK_UNKNOWN"]}
            ],
            "disclaimer": "仅为一般资料。",
        }
    else:
        content = {
            "summary": " ",
            "observations": ["来源分别描述一般教育信息。"],
            "suggestions": [
                {
                    "text": "可以查看来源。",
                    "source_chunk_ids": [
                        "CHUNK_SCHOOL_RESEARCH_policy-1",
                        "CHUNK_SCHOOL_RESEARCH_theory-1",
                        "CHUNK_SCHOOL_RESEARCH_intervention-1",
                    ],
                }
            ],
            "disclaimer": "仅为一般资料。",
        }
    service, payload = await _generate_output_review_payload(claim, content)
    configured = adapter(
        policy_hash=service.policy_pins.policy_hash,
        source_package_ref=service.policy_pins.source_package_ref,
        source_study_ref=service.policy_pins.source_study_ref,
        source_manifest_sha256=service.policy_pins.source_manifest_sha256,
        source_cards=service.source_cards,
    )
    configured.study_use_policy = SimpleNamespace(
        ends_at=datetime(2026, 10, 15, 13, 30, tzinfo=UTC)
    )
    review_dump = payload.model_dump(mode="json")
    configured.protection = SimpleNamespace(
        encrypt_json=lambda *_args, **_kwargs: SimpleNamespace(
            ciphertext=b"encrypted-review",
            cipher_format_version="enc.v1",
            key_version="test-key",
            payload_schema_version=OUTPUT_REVIEW_PAYLOAD_SCHEMA_VERSION,
        ),
        decrypt_json=lambda _encrypted: review_dump,
    )
    events = _finalize_harness(configured, claim)
    diagnostic = ResearchGeneralEducationOutputSafetyDiagnostic(
        action="REVIEW_REQUIRED",
        reason_codes=("CONTENT_CONTROVERSIAL",),
        requires_human=True,
    )

    disposition = await configured.finalize_education_job(
        claim,
        status="REVIEW_REQUIRED",
        error_code=ResearchEducationJobErrorCode.SAFETY_BLOCKED,
        reason_code="OUTPUT_SAFETY_STOP",
        output_safety_diagnostic=diagnostic,
        output_review_payload=payload,
    )

    assert disposition == "REVIEW_REQUIRED"
    assert [event[0] for event in events if event[0] in {
        "output_review_create_pending", "finish"
    }] == ["output_review_create_pending", "finish"]
    assert events.output_review_status == "PENDING"
    save_event = next(
        event[1]
        for event in events
        if event[0] == "audit"
        and event[1]["action"] == "school_research_education_job.output_review_capture"
    )
    assert save_event["safe_metadata"]["state"] == "SAVED"
    assert save_event["safe_metadata"]["reason_code"] == "OUTPUT_REVIEW_SAVED"
    create_event = next(event[1] for event in events if event[0] == "output_review_create_pending")
    assert create_event["payload_ciphertext"] == b"encrypted-review"
    assert create_event["evidence"].expires_at == datetime(
        2026, 10, 15, 13, 30, tzinfo=UTC
    )
    assert "content" not in create_event

    row = SimpleNamespace(
        payload_schema_version=OUTPUT_REVIEW_PAYLOAD_SCHEMA_VERSION,
        cipher_format_version="enc.v1",
        key_version="test-key",
        payload_ciphertext=b"encrypted-review",
        job_ref=claim.job_ref,
        generation_round=0,
        policy_hash=payload.provenance.policy_hash,
        source_manifest_sha256=payload.provenance.source_manifest_sha256,
        retrieval_id=payload.provenance.retrieval_id,
        retrieval_bundle_sha256=payload.provenance.retrieval_bundle_sha256,
        prompt_id=payload.provenance.prompt_id,
        prompt_version=payload.provenance.prompt_version,
        prompt_sha256=payload.provenance.prompt_sha256,
        model_ref=payload.provenance.model_id,
        model_digest_sha256=payload.provenance.model_digest_sha256,
        runtime_version=payload.provenance.runtime_version,
        input_safety_action=payload.provenance.input_safety_action,
        retrieval_safety_action=payload.provenance.retrieval_safety_action,
        safety_decision_id=payload.safety_decision_id,
        safety_review_ref=payload.safety_review_ref,
        safety_trace_id=payload.safety_trace_id,
        content_sha256=_canonical_mapping_sha256(review_dump),
    )
    readback = configured._output_review_payload_from_row(row)
    assert readback.content == payload.content
    with pytest.raises(BackendError) as rejected:
        configured._candidate_payload_from_output_review(readback)
    assert rejected.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert events.output_review_status == "PENDING"
    assert events.output_review_consume_calls == 0


async def test_real_audit_repository_accepts_schema_version_metadata_without_db_write():
    from database_layer.repositories import AuditRepository

    class NoWriteSession:
        def __init__(self):
            self.added = []

        def add(self, record):
            self.added.append(record)

        async def flush(self):
            return None

    session = NoWriteSession()
    repository = AuditRepository(session)
    metadata = {
        "schema_version": "research-output-safety-diagnostic.v1",
        "source": GENERAL_EDUCATION_POLICY_VERSION,
        "state": "REVIEW_REQUIRED",
        "reason_code": "CONTENT_UNSAFE",
        "count": 1,
    }

    await repository.append(
        action="school_research_education_job.output_safety",
        resource_type="school_research_education_job",
        resource_public_id="REJ_synthetic_audit_fixture",
        result=AuditResult.FAILURE,
        trace_id="TRACE_synthetic_audit_fixture",
        safe_metadata=metadata,
    )

    assert len(session.added) == 1
    assert session.added[0].safe_metadata == metadata
    with pytest.raises(ValueError, match="non-whitelisted field"):
        await repository.append(
            action="school_research_education_job.output_safety",
            resource_type="school_research_education_job",
            resource_public_id="REJ_synthetic_audit_fixture",
            result=AuditResult.FAILURE,
            trace_id="TRACE_synthetic_audit_fixture",
            safe_metadata={**metadata, "unapproved": "value"},
        )
    assert len(session.added) == 1


@pytest.mark.parametrize(
    ("diagnostic", "status", "reason_code", "error_code", "revoked"),
    [
        (
            ResearchGeneralEducationOutputSafetyDiagnostic(
                action="REVIEW_REQUIRED",
                reason_codes=("CONTENT_UNSAFE",),
                requires_human=True,
            ),
            "REVIEW_REQUIRED",
            "RESEARCH_RUNTIME_FAILED",
            ResearchEducationJobErrorCode.SAFETY_BLOCKED,
            False,
        ),
        (
            ResearchGeneralEducationOutputSafetyDiagnostic(
                action="BLOCK", reason_codes=("CONTENT_UNSAFE",), requires_human=False
            ),
            "REVIEW_REQUIRED",
            "OUTPUT_SAFETY_STOP",
            ResearchEducationJobErrorCode.SAFETY_BLOCKED,
            False,
        ),
        (
            SimpleNamespace(
                action="REVIEW_REQUIRED",
                reason_codes=("CONTENT_UNSAFE",),
                requires_human=True,
            ),
            "REVIEW_REQUIRED",
            "OUTPUT_SAFETY_STOP",
            ResearchEducationJobErrorCode.SAFETY_BLOCKED,
            False,
        ),
        (
            ResearchGeneralEducationOutputSafetyDiagnostic.model_construct(
                action="REVIEW_REQUIRED",
                reason_codes=("UNSAFE_FREEFORM",),
                requires_human=True,
            ),
            "REVIEW_REQUIRED",
            "OUTPUT_SAFETY_STOP",
            ResearchEducationJobErrorCode.SAFETY_BLOCKED,
            False,
        ),
        (
            None,
            "REVIEW_REQUIRED",
            "OUTPUT_SAFETY_STOP",
            ResearchEducationJobErrorCode.SAFETY_BLOCKED,
            False,
        ),
        (
            ResearchGeneralEducationOutputSafetyDiagnostic(
                action="REVIEW_REQUIRED",
                reason_codes=("CONTENT_UNSAFE",),
                requires_human=True,
            ),
            "REVIEW_REQUIRED",
            "OUTPUT_SAFETY_STOP",
            ResearchEducationJobErrorCode.SAFETY_BLOCKED,
            True,
        ),
    ],
)
async def test_invalid_or_stale_output_diagnostic_does_not_change_terminal_outcome(
    diagnostic, status, reason_code, error_code, revoked
):
    claim = _education_job_claim()
    configured = adapter()
    events = _finalize_harness(configured, claim, revoked=revoked)

    disposition = await configured.finalize_education_job(
        claim,
        status=status,
        error_code=error_code,
        reason_code=reason_code,
        output_safety_diagnostic=diagnostic,
    )

    assert disposition == ("CANCELLED" if revoked else status)
    assert not any(
        event[1].get("action") == "school_research_education_job.output_safety"
        for event in events
        if event[0] == "audit"
    )


@pytest.mark.parametrize(
    "diagnostic",
    [
        SimpleNamespace(
            field_kind="SUMMARY", field_index=0, category="DIAGNOSIS", match_count=1
        ),
        ResearchGeneralEducationBoundaryDiagnostic.model_construct(
            field_kind="SUMMARY", field_index=-1, category="DIAGNOSIS", match_count=0
        ),
    ],
)
async def test_invalid_boundary_diagnostic_adds_no_claim_audit(diagnostic):
    claim = _education_job_claim()
    configured = adapter()
    events = _finalize_harness(configured, claim)

    disposition = await configured.finalize_education_job(
        claim,
        status="ABSTAINED",
        error_code=ResearchEducationJobErrorCode.GENERATION_FAILED,
        reason_code="RESEARCH_CLAIM_BOUNDARY_REJECTED",
        boundary_diagnostic=diagnostic,
    )

    assert disposition == "ABSTAINED"
    assert [event[0] for event in events] == ["finish", "audit"]
    assert events[1][1]["action"] == "school_research_education_job.terminal"
    assert events[1][1]["safe_metadata"]["reason_code"] == (
        "RESEARCH_CLAIM_BOUNDARY_REJECTED"
    )


async def test_valid_diagnostic_is_ignored_for_nonboundary_outcome():
    claim = _education_job_claim()
    configured = adapter()
    events = _finalize_harness(configured, claim)
    diagnostic = ResearchGeneralEducationBoundaryDiagnostic(
        field_kind="SUMMARY",
        field_index=0,
        category="DIAGNOSIS",
        match_count=1,
    )

    disposition = await configured.finalize_education_job(
        claim,
        status="FAILED",
        error_code=ResearchEducationJobErrorCode.GENERATION_FAILED,
        reason_code="RESEARCH_RUNTIME_FAILED",
        boundary_diagnostic=diagnostic,
    )

    assert disposition == "FAILED"
    assert [event[0] for event in events] == ["finish", "audit"]
    assert events[1][1]["action"] == "school_research_education_job.terminal"


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


def test_candidate_readback_accepts_only_registered_historical_prompt_tuple():
    configured = adapter()
    payload = candidate_payload()
    old_sha = "f7b8f8ed70cfdf932d7e774101dfb4d2dae17e45f6aaf968e09fda146c0686ea"
    legacy_prompt = get_prompt_definition(PROMPT_ID, "1.0.0", old_sha)
    assert legacy_prompt is not None
    legacy_payload = payload.model_copy(update={
        "provenance": payload.provenance.model_copy(update={
            "prompt_id": legacy_prompt.prompt_id,
            "prompt_version": legacy_prompt.version,
            "prompt_sha256": legacy_prompt.sha256,
        })
    })
    configured.protection = SimpleNamespace(
        decrypt_json=lambda _encrypted: legacy_payload.model_dump(mode="python")
    )

    result = configured._payload_from_row(_row(legacy_payload))
    assert result.provenance.prompt_version == "1.0.0"
    assert result.provenance.prompt_sha256 == old_sha
    with pytest.raises(BackendError):
        configured._validate_new_payload(legacy_payload)

    with pytest.raises(BackendError) as raised:
        configured._payload_from_row(
            _row(legacy_payload, prompt_sha256="0" * 64)
        )
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


@pytest.mark.parametrize(
    "mismatch",
    [
        None,
        "output_scope",
        "input_scope",
        "output_ref",
        "input_ref",
        "missing_output",
        "missing_input",
    ],
)
async def test_candidate_review_lineage_is_projected_only_after_exact_db_verification(mismatch):
    from database_layer.models import (
        SchoolResearchEducationInputReview,
        SchoolResearchEducationJob,
        SchoolResearchEducationOutputReview,
    )
    from database_layer.school_research_education_output_reviews import (
        ResearchEducationOutputReviewScope,
    )
    from sqlalchemy import select

    from smhai_backend.domains.research_general_education.service import (
        EXPECTED_MODEL_DIGEST_SHA256,
        EXPECTED_MODEL_ID,
    )

    configured = adapter()
    now = datetime(2026, 10, 15, 11, 30, tzinfo=UTC)
    consumed_input = replace(
        _authorized_input_review_dto(configured),
        status="CONSUMED",
        state_version=3,
        consumed_at=now,
        updated_at=now,
    )
    input_review_ref = consumed_input.input_review_ref
    input_scope = consumed_input.scope
    if mismatch == "input_scope":
        consumed_input = replace(
            consumed_input,
            scope=replace(input_scope, task_id=input_scope.task_id + 1),
        )
    elif mismatch == "input_ref":
        consumed_input = replace(
            consumed_input,
            input_review_ref="REIR_" + "c" * 32,
        )
    job_ref = "REJ_" + "a" * 64
    expected_trace = "TRACE_" + hashlib.sha256(f"{job_ref}:1".encode("ascii")).hexdigest()[:32]
    output_ref = "REOR_" + "b" * 32
    output_scope = ResearchEducationOutputReviewScope(
        **{
            name: getattr(input_scope, name)
            for name in ResearchEducationOutputReviewScope.__dataclass_fields__
        }
    )
    if mismatch == "output_scope":
        output_scope = replace(output_scope, task_id=output_scope.task_id + 1)

    row = _row(
        candidate_payload(),
        job_id=97,
        generation_round=1,
        input_review_id=consumed_input.id,
        input_review_state="CONSUMED",
        output_review_id=98,
        output_review_state="CONSUMED",
        scope=input_scope,
        status="HELD",
        state_version=1,
        input_safety_action="REVIEW_REQUIRED",
        output_safety_action="REVIEW_REQUIRED",
        created_at=now,
        trace_id=expected_trace,
    )
    job = SimpleNamespace(
        id=row.job_id,
        job_ref=job_ref,
        school_id=row.scope.school_id,
        research_session_id=row.scope.research_session_id,
        generation_round=1,
        input_review_id=consumed_input.id,
        status="REVIEW_REQUIRED",
        attempt_count=1,
        policy_hash=row.policy_hash,
        policy_version=row.policy_version,
        last_error_code="SAFETY_BLOCKED",
        lease_owner=None,
        lease_token=None,
        **{
            name: getattr(row.scope, name)
            for name in ResearchEducationOutputReviewScope.__dataclass_fields__
            if name not in {"school_id", "research_session_id"}
        },
    )
    source_job = SimpleNamespace(
        id=consumed_input.job_id,
        job_ref=consumed_input.job_ref,
        school_id=row.scope.school_id,
        research_session_id=row.scope.research_session_id,
        generation_round=0,
        input_review_id=None,
        status="REVIEW_REQUIRED",
        attempt_count=1,
        last_error_code="SAFETY_BLOCKED",
        policy_hash=consumed_input.policy_hash,
        **{
            name: getattr(row.scope, name)
            for name in ResearchEducationOutputReviewScope.__dataclass_fields__
            if name not in {"school_id", "research_session_id"}
        },
    )
    output_review = SimpleNamespace(
        id=row.output_review_id,
        output_review_ref=output_ref,
        job_id=job.id,
        job_ref=job.job_ref,
        generation_round=1,
        input_review_id=consumed_input.id,
        scope=output_scope,
        safety_operation="OUTPUT",
        safety_action="REVIEW_REQUIRED",
        safety_reason_code="CONTENT_CONTROVERSIAL",
        safety_requires_human=True,
        input_safety_action="PROCEED",
        retrieval_safety_action="PROCEED",
        canonical_input_sha256=consumed_input.canonical_input_sha256,
        policy_version=GENERAL_EDUCATION_POLICY_VERSION,
        policy_hash=configured.policy_hash,
        source_package_ref=configured.source_package_ref,
        source_study_ref=configured.source_study_ref,
        source_manifest_sha256=configured.source_manifest_sha256,
        retrieval_id="RETR_synthetic_output_review",
        retrieval_bundle_sha256="3" * 64,
        prompt_id=PROMPT_ID,
        prompt_version=PROMPT_VERSION,
        prompt_sha256=PROMPT_SHA256,
        model_ref=EXPECTED_MODEL_ID,
        model_digest_sha256=EXPECTED_MODEL_DIGEST_SHA256,
        runtime_version="runtime-synthetic",
        safety_policy_version=SAFETY_POLICY_VERSION,
        content_sha256="4" * 64,
        candidate_content_sha256=row.content_sha256,
        candidate_payload_schema_version="school-research-general-education-candidate.v1",
        status="CONSUMED",
        state_version=2,
        consumed_at=now,
        trace_id=expected_trace,
        safety_trace_id=expected_trace,
    )
    if mismatch == "output_ref":
        output_review.output_review_ref = "REOR_" + "c" * 32

    class Session:
        def __init__(self):
            self.results = iter((job, output_ref, input_review_ref, source_job))

        async def scalar(self, _statement):
            return next(self.results)

    class OutputReviews:
        async def get_for_task(self, *, scope, output_review_ref):
            assert output_review_ref == output_ref
            assert scope == ResearchEducationOutputReviewScope(
                **{
                    name: getattr(row.scope, name)
                    for name in ResearchEducationOutputReviewScope.__dataclass_fields__
                }
            )
            return None if mismatch == "missing_output" else output_review

    class InputReviews:
        async def get_for_task(self, *, school_id, task_id, input_review_ref):
            assert (school_id, task_id, input_review_ref) == (
                row.scope.school_id,
                row.scope.task_id,
                input_review_ref,
            )
            return None if mismatch == "missing_input" else consumed_input

    configured._db_models = SimpleNamespace(
        SchoolResearchEducationJob=SchoolResearchEducationJob,
        SchoolResearchEducationInputReview=SchoolResearchEducationInputReview,
        SchoolResearchEducationOutputReview=SchoolResearchEducationOutputReview,
    )
    configured._select = select
    uow = SimpleNamespace(
        session=Session(),
        research_education_output_reviews=OutputReviews(),
        research_education_input_reviews=InputReviews(),
    )

    if mismatch is not None:
        with pytest.raises(BackendError) as rejected:
            await configured.verify_candidate_input_lineage_in_uow(uow, row)
        assert rejected.value.code is ErrorCode.WORKFLOW_CONFLICT
        return

    lineage = await configured.verify_candidate_input_lineage_in_uow(uow, row)
    assert lineage == {
        "generation_round": 1,
        "input_review": {
            "input_review_ref": consumed_input.input_review_ref,
            "status": "CONSUMED",
            "state_version": 3,
        },
        "output_review": {
            "output_review_ref": output_ref,
            "status": "CONSUMED",
            "state_version": 2,
            "reason_code": "CONTENT_CONTROVERSIAL",
        },
    }
    assert row.output_safety_action == "REVIEW_REQUIRED"
    assert candidate_payload().provenance.output_safety_action == "PROCEED"
