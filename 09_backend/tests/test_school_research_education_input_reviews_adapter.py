from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from database_layer import models
from database_layer.school_research_education_input_reviews import (
    ResearchEducationInputReviewDTO,
    ResearchEducationInputReviewError,
    ResearchEducationInputReviewScope,
)
from pydantic import ValidationError
from sqlalchemy import select

from smhai_backend.adapters.school_research_education_input_reviews import (
    ResearchEducationInputReviewPersistenceMixin,
    _input_review_repo_call,
)
from smhai_backend.core.errors import BackendError, ErrorCode, error
from smhai_backend.core.request_context import RequestContext
from smhai_backend.domains.research_general_education.input_review_policy import (
    INPUT_REVIEW_CONTINUATION_POLICY_SHA256,
    INPUT_REVIEW_CONTINUATION_POLICY_VERSION,
    continuation_policy_sha256_for_prompt,
)
from smhai_backend.domains.research_general_education.prompt import (
    PROMPT_ID,
    PROMPT_SHA256,
    PROMPT_VERSION,
)
from smhai_backend.domains.research_general_education.service import (
    ResearchGeneralEducationPolicyPins,
    _valid_reviewed_input_authorization,
    canonical_input_context_sha256,
)

NOW = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)
POLICY_HASH = "a" * 64
MANIFEST_HASH = "b" * 64
INPUT_REVIEW_REF = "REIR_" + "c" * 32
JOB_REF = "REJ_" + "d" * 64


def trace_for_job(job_ref):
    import hashlib

    token = hashlib.sha256(f"{job_ref}:1".encode("ascii")).hexdigest()[:32]
    return f"TRACE_{token}"


def scope(**changes):
    values = {
        "research_session_id": 701,
        "school_id": 17,
        "task_id": 31,
        "class_id": 37,
        "task_enrollment_id": 41,
        "subject_id": 43,
        "task_binding_id": 47,
        "profile_version_id": 53,
        "profile_ref": "PROFILE_SYNTHETIC",
        "profile_version_number": 2,
        "profile_sha256": "e" * 64,
        "response_origin": "PUBLIC_OBSERVED",
    }
    values.update(changes)
    return ResearchEducationInputReviewScope(**values)


def row(*, status="PENDING", state_version=1, **changes):
    pins = ResearchGeneralEducationPolicyPins(
        policy_hash=POLICY_HASH,
        source_package_ref="PKG_R3",
        source_study_ref="STUDY_R3",
        source_manifest_sha256=MANIFEST_HASH,
    )
    values = {
        "id": 101,
        "input_review_ref": INPUT_REVIEW_REF,
        "job_id": 97,
        "job_ref": JOB_REF,
        "scope": scope(),
        "decision_id": "decision_synthetic_1",
        "safety_review_ref": "review_synthetic_1",
        "safety_trace_id": trace_for_job(JOB_REF),
        "safety_operation": "INPUT",
        "safety_action": "REVIEW_REQUIRED",
        "safety_reason_code": "CONTENT_CONTROVERSIAL",
        "safety_requires_human": True,
        "canonical_input_sha256": canonical_input_context_sha256(policy_pins=pins),
        "policy_version": "RESEARCH_GENERAL_EDUCATION_DRAFT_V1",
        "policy_hash": POLICY_HASH,
        "source_package_ref": "PKG_R3",
        "source_study_ref": "STUDY_R3",
        "source_manifest_sha256": MANIFEST_HASH,
        "prompt_id": PROMPT_ID,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": PROMPT_SHA256,
        "status": status,
        "state_version": state_version,
        "expires_at": NOW + timedelta(hours=6),
        "resolved_by_membership_role_id": 222 if state_version == 2 else None,
        "resolved_at": NOW if state_version == 2 else None,
        "trace_id": trace_for_job(JOB_REF),
        "retention_due_at": None,
        "created_at": NOW - timedelta(minutes=5),
        "updated_at": NOW if state_version == 2 else NOW - timedelta(minutes=5),
    }
    values.update(changes)
    if "job_ref" in changes and "safety_trace_id" not in changes:
        values["safety_trace_id"] = trace_for_job(values["job_ref"])
    if "job_ref" in changes and "trace_id" not in changes:
        values["trace_id"] = trace_for_job(values["job_ref"])
    return ResearchEducationInputReviewDTO(**values)


class Result:
    def __init__(self, first):
        self.value = first

    def first(self):
        return self.value


class FakeSession:
    def __init__(self, adapter):
        self.adapter = adapter
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        if isinstance(self.adapter.job_facts, list):
            return Result(self.adapter.job_facts.pop(0))
        return Result(self.adapter.job_facts)


class FakeRepository:
    def __init__(self, initial):
        self.current = initial
        self.calls = []

    async def list_for_task(self, **kwargs):
        self.calls.append(("list", kwargs))
        return self.rows if hasattr(self, "rows") else [self.current]

    async def get_for_task(self, **kwargs):
        self.calls.append(("get", kwargs))
        return self.current

    async def reject(self, **kwargs):
        self.calls.append(("reject", kwargs))
        self.current = replace(
            self.current,
            status="REJECTED",
            state_version=2,
            resolved_by_membership_role_id=kwargs["actor_membership_role_id"],
            resolved_at=NOW,
            updated_at=NOW,
        )
        return self.current

    async def revoke(self, **kwargs):
        self.calls.append(("revoke", kwargs))
        self.current = replace(
            self.current,
            status="REVOKED",
            state_version=2,
            resolved_by_membership_role_id=kwargs["actor_membership_role_id"],
            resolved_at=NOW,
            updated_at=NOW,
        )
        return self.current


class FakeAudit:
    def __init__(self):
        self.calls = []

    async def append(self, **kwargs):
        self.calls.append(kwargs)


class FakeAdapter(ResearchEducationInputReviewPersistenceMixin):
    def __init__(self, initial=None):
        self.enabled = True
        self.input_review_continuation_enabled = False
        self.school_id = 17
        self.school_study_ref = "STUDY_R3"
        self.policy_hash = POLICY_HASH
        self.source_manifest_sha256 = MANIFEST_HASH
        self.source_package_ref = "PKG_R3"
        self.source_study_ref = "STUDY_R3"
        self.study_use_policy = SimpleNamespace(source_rights_verified=True)
        self._db_models = models
        self._select = select
        self._db_enums = SimpleNamespace()
        self.task = SimpleNamespace(id=31)
        self.role_id = 222
        self.actor_account_id = 333
        self.current_scope = scope()
        self.review = initial or row()
        self.repo = FakeRepository(self.review)
        self.audit = FakeAudit()
        self.session = FakeSession(self)
        self.uow = SimpleNamespace(
            session=self.session,
            research_education_input_reviews=self.repo,
            audit=self.audit,
        )
        self.job_facts = self._expected_job_facts(self.review)
        self.events = []
        self.idempotency_replayed = False
        self.idempotency_receipt_ref = self.review.input_review_ref

    @staticmethod
    def _expected_job_facts(review):
        return (
            review.job_ref,
            review.scope.research_session_id,
            review.scope.school_id,
            review.scope.task_id,
            1,
            review.scope.class_id,
            review.scope.task_enrollment_id,
            review.scope.subject_id,
            review.scope.task_binding_id,
            review.scope.profile_version_id,
            review.scope.profile_ref,
            review.scope.profile_version_number,
            review.scope.profile_sha256,
            review.scope.response_origin,
            "REVIEW_REQUIRED",
            "SAFETY_BLOCKED",
            "RESEARCH_GENERAL_EDUCATION_DRAFT_V1",
            POLICY_HASH,
            "RESEARCH_SIMULATION",
            True,
            "not_approved_for_publication_or_operational_use",
            0,
            None,
        )

    def _require_enabled(self):
        if not self.enabled:
            raise error(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="disabled")

    def _now(self):
        return NOW, NOW.replace(tzinfo=None)

    @asynccontextmanager
    async def _uow(self):
        yield self.uow

    async def _active_task(self, _uow, _actor, task_ref, *, at):
        self.events.append(("active_task", task_ref))
        if task_ref != "TASK_synthetic_1":
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="not found")
        return self.task, SimpleNamespace(), self.role_id

    async def _require_actor(self, _uow, _actor, role_code, _at):
        self.events.append(("require_actor", role_code))
        if role_code != "psychological_specialist":
            raise error(ErrorCode.FORBIDDEN, detail="denied")
        return self.actor_account_id, self.role_id

    async def _session_ref(self, _uow, _actor, _task, session_id):
        assert session_id == self.review.scope.research_session_id
        return "RSESSION_synthetic_1"

    async def _current_scope(
        self, _uow, _actor, _task, *, session_ref, at, lock=False
    ):
        assert session_ref == "RSESSION_synthetic_1"
        return self.current_scope, {}, None, None, None

    @staticmethod
    def _same_scope(left, right):
        fields = tuple(ResearchEducationInputReviewScope.__dataclass_fields__)
        return all(getattr(left, field) == getattr(right, field) for field in fields)

    async def _school_idempotency_begin(self, _uow, idempotency):
        self.events.append(("idempotency_begin", idempotency))
        return SimpleNamespace(
            replayed=self.idempotency_replayed,
            record=SimpleNamespace(result_resource_type="school_research_education_input_review"),
        )

    async def _receipt_resource(self, claim, expected_type):
        assert claim.record.result_resource_type == expected_type
        return self.idempotency_receipt_ref

    async def _school_idempotency_complete(
        self, _uow, _claim, *, resource_type, result_ref
    ):
        self.events.append(("idempotency_complete", resource_type, result_ref))

    async def _audit_research(self, _uow, **kwargs):
        self.events.append(("audit", kwargs))


def specialist():
    return SimpleNamespace(school_id=17, role="psychological_specialist")


def authorized_row(**changes):
    values = dict(
        status="CONTINUATION_AUTHORIZED", state_version=2,
        decision_id="DEC_synthetic_1", safety_review_ref="REVIEW_synthetic_1",
        grant_policy_version=INPUT_REVIEW_CONTINUATION_POLICY_VERSION,
        grant_policy_hash=INPUT_REVIEW_CONTINUATION_POLICY_SHA256,
        authorized_by_membership_role_id=222, authorized_at=NOW,
        resolved_by_membership_role_id=None, resolved_at=None, updated_at=NOW,
    )
    values.update(changes)
    return row(**values)


@pytest.mark.parametrize("changes", [
    {"grant_policy_hash": "9" * 64},
    {"grant_policy_version": "OTHER"},
    {"authorized_by_membership_role_id": None},
    {"authorized_at": NOW + timedelta(days=1)},
    {"status": "CONSUMED", "state_version": 2, "consumed_at": NOW},
    {"status": "CONSUMED", "state_version": 3, "consumed_at": None},
])
def test_review_grant_pins_and_consumption_state_fail_closed(changes):
    adapter = FakeAdapter()
    adapter._input_review_pins(authorized_row())
    with pytest.raises(BackendError):
        adapter._input_review_pins(authorized_row(**changes))


def test_historical_prompt_review_and_grant_remain_readable_but_not_authorizable():
    adapter = FakeAdapter()
    adapter.input_review_continuation_enabled = True
    old_sha = "f7b8f8ed70cfdf932d7e774101dfb4d2dae17e45f6aaf968e09fda146c0686ea"
    old_policy_hash = continuation_policy_sha256_for_prompt(PROMPT_ID, "1.0.0", old_sha)
    pins = ResearchGeneralEducationPolicyPins(
        policy_hash=POLICY_HASH,
        source_package_ref="PKG_R3",
        source_study_ref="STUDY_R3",
        source_manifest_sha256=MANIFEST_HASH,
    )
    old_digest = canonical_input_context_sha256(
        policy_pins=pins,
        prompt_id=PROMPT_ID,
        prompt_version="1.0.0",
        prompt_sha256=old_sha,
    )
    pending_old = row(
        prompt_version="1.0.0",
        prompt_sha256=old_sha,
        canonical_input_sha256=old_digest,
    )
    adapter._input_review_pins(pending_old)
    assert adapter._input_review_summary(
        pending_old, task_ref="TASK_synthetic_1", session_ref="RSESSION_synthetic_1"
    )["continuation_enabled"] is False

    authorized_old = authorized_row(
        prompt_version="1.0.0",
        prompt_sha256=old_sha,
        canonical_input_sha256=old_digest,
        grant_policy_hash=old_policy_hash,
    )
    adapter._input_review_pins(authorized_old)
    consumed_old = authorized_row(
        status="CONSUMED",
        state_version=3,
        prompt_version="1.0.0",
        prompt_sha256=old_sha,
        canonical_input_sha256=old_digest,
        grant_policy_hash=old_policy_hash,
        consumed_at=NOW + timedelta(minutes=1),
    )
    adapter._input_review_pins(consumed_old)
    with pytest.raises(BackendError):
        adapter._input_review_pins(authorized_row(
            prompt_version="1.0.0",
            prompt_sha256=old_sha,
            canonical_input_sha256=old_digest,
            grant_policy_hash=INPUT_REVIEW_CONTINUATION_POLICY_SHA256,
        ))


@pytest.mark.asyncio
async def test_historical_pending_review_cannot_be_authorized_for_current_generation():
    adapter = FakeAdapter()
    adapter.input_review_continuation_enabled = True
    old_sha = "f7b8f8ed70cfdf932d7e774101dfb4d2dae17e45f6aaf968e09fda146c0686ea"
    pins = ResearchGeneralEducationPolicyPins(
        policy_hash=POLICY_HASH,
        source_package_ref="PKG_R3",
        source_study_ref="STUDY_R3",
        source_manifest_sha256=MANIFEST_HASH,
    )
    old_digest = canonical_input_context_sha256(
        policy_pins=pins,
        prompt_id=PROMPT_ID,
        prompt_version="1.0.0",
        prompt_sha256=old_sha,
    )
    adapter.review = row(
        prompt_version="1.0.0",
        prompt_sha256=old_sha,
        canonical_input_sha256=old_digest,
    )
    adapter.repo.current = adapter.review
    with pytest.raises(BackendError) as raised:
        await adapter.school_research_education_input_review_resolve(
            specialist(), "TASK_synthetic_1", INPUT_REVIEW_REF,
            expected_state_version=1, target="CONTINUATION_AUTHORIZED",
            idempotency=("idem", "body", "scope"), trace_id="TRACE_synthetic_1",
        )
    assert raised.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert not any(call[0] == "idempotency_begin" for call in adapter.events)
    assert not any(call[0] == "authorize" for call in adapter.repo.calls)


@pytest.mark.asyncio
async def test_historical_authorization_cannot_load_generation_capability():
    adapter = FakeAdapter()
    adapter.input_review_continuation_enabled = True
    old_sha = "f7b8f8ed70cfdf932d7e774101dfb4d2dae17e45f6aaf968e09fda146c0686ea"
    old_policy_hash = continuation_policy_sha256_for_prompt(PROMPT_ID, "1.0.0", old_sha)
    pins = ResearchGeneralEducationPolicyPins(
        policy_hash=POLICY_HASH,
        source_package_ref="PKG_R3",
        source_study_ref="STUDY_R3",
        source_manifest_sha256=MANIFEST_HASH,
    )
    old_digest = canonical_input_context_sha256(
        policy_pins=pins,
        prompt_id=PROMPT_ID,
        prompt_version="1.0.0",
        prompt_sha256=old_sha,
    )
    review = authorized_row(
        prompt_version="1.0.0",
        prompt_sha256=old_sha,
        canonical_input_sha256=old_digest,
        grant_policy_hash=old_policy_hash,
    )
    adapter.review = review
    adapter.repo.current = review

    async def scalar(_statement):
        return review.input_review_ref

    adapter.session.scalar = scalar
    claim = SimpleNamespace(
        **{
            name: getattr(review.scope, name)
            for name in review.scope.__dataclass_fields__
        },
        generation_round=1,
        input_review_id=review.id,
        attempt_count=1,
        job_ref="REJ_" + "f" * 64,
    )
    with pytest.raises(BackendError) as raised:
        await adapter._continuation_authorization(
            adapter.uow, claim, adapter.task, now=NOW
        )
    assert raised.value.code is ErrorCode.WORKFLOW_CONFLICT


@pytest.mark.asyncio
async def test_historical_authorized_review_can_be_revoked_without_reauthorizing():
    adapter = FakeAdapter()
    old_sha = "f7b8f8ed70cfdf932d7e774101dfb4d2dae17e45f6aaf968e09fda146c0686ea"
    old_policy_hash = continuation_policy_sha256_for_prompt(PROMPT_ID, "1.0.0", old_sha)
    pins = ResearchGeneralEducationPolicyPins(
        policy_hash=POLICY_HASH,
        source_package_ref="PKG_R3",
        source_study_ref="STUDY_R3",
        source_manifest_sha256=MANIFEST_HASH,
    )
    old_digest = canonical_input_context_sha256(
        policy_pins=pins,
        prompt_id=PROMPT_ID,
        prompt_version="1.0.0",
        prompt_sha256=old_sha,
    )
    review = authorized_row(
        prompt_version="1.0.0",
        prompt_sha256=old_sha,
        canonical_input_sha256=old_digest,
        grant_policy_hash=old_policy_hash,
    )
    adapter.review = review
    adapter.repo.current = review

    async def revoke(**kwargs):
        adapter.repo.calls.append(("revoke", kwargs))
        adapter.repo.current = replace(
            review,
            status="REVOKED",
            state_version=3,
            resolved_by_membership_role_id=kwargs["actor_membership_role_id"],
            resolved_at=NOW,
            updated_at=NOW,
        )
        return adapter.repo.current

    adapter.repo.revoke = revoke
    result = await adapter.school_research_education_input_review_resolve(
        specialist(),
        "TASK_synthetic_1",
        INPUT_REVIEW_REF,
        expected_state_version=2,
        target="REVOKED",
        idempotency=("idem", "body", "scope"),
        trace_id="TRACE_synthetic_1",
    )
    assert result["status"] == "REVOKED"
    assert result["state_version"] == 3
    assert [call[0] for call in adapter.repo.calls] == ["get", "revoke"]


@pytest.mark.asyncio
async def test_continuation_disabled_cannot_enqueue_or_begin_idempotency():
    adapter = FakeAdapter()
    with pytest.raises(BackendError) as raised:
        await adapter.school_research_education_input_review_resolve(
            specialist(), "TASK_synthetic_1", INPUT_REVIEW_REF,
            expected_state_version=1, target="CONTINUATION_AUTHORIZED",
            idempotency=("idem", "body", "scope"), trace_id="TRACE_synthetic_1",
        )
    assert raised.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert not adapter.repo.calls
    assert not adapter.events


@pytest.mark.asyncio
async def test_continuation_capability_rechecks_exact_authorizer_and_original_job(monkeypatch):
    from smhai_backend.domains.research_general_education import service as processor

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is not None else NOW.replace(tzinfo=None)

    monkeypatch.setattr(processor, "datetime", FixedClock)
    review = authorized_row()
    adapter = FakeAdapter(review)
    adapter.input_review_continuation_enabled = True
    claim = SimpleNamespace(
        **{name: getattr(review.scope, name) for name in review.scope.__dataclass_fields__},
        generation_round=1, input_review_id=review.id, attempt_count=1,
        job_ref="REJ_" + "f" * 64,
    )
    async def scalar(_statement):
        return review.input_review_ref
    async def require_assignment(_uow, _task, *, at, membership_role_id):
        assert at == NOW
        assert membership_role_id == review.authorized_by_membership_role_id
        adapter.events.append(("exact_authorizer", membership_role_id))
    adapter.session.scalar = scalar
    adapter._require_active_specialist_assignment = require_assignment
    grant, actual = await adapter._continuation_authorization(
        adapter.uow, claim, adapter.task, now=NOW,
    )
    assert actual is review
    assert grant.receipt.action == "REVIEW_REQUIRED"
    assert grant.input_review_ref == INPUT_REVIEW_REF
    assert grant.input_review_ref != grant.receipt.review_ref
    assert grant.receipt.trace_id == trace_for_job(JOB_REF)
    assert grant.continuation_trace_id == trace_for_job(claim.job_ref)
    assert grant.continuation_job_ref != grant.receipt.trace_id
    assert ("exact_authorizer", 222) in adapter.events

    # The real persistence adapter produces two independent identifiers; the
    # processor validator must accept the Backend REIR ref beside Safety REVIEW ref.
    assert _valid_reviewed_input_authorization(
        grant,
        request_context=RequestContext(
            request_id="REQ_continuation", trace_id=grant.continuation_trace_id
        ),
        policy_pins=ResearchGeneralEducationPolicyPins(
            policy_hash=POLICY_HASH,
            source_package_ref="PKG_R3",
            source_study_ref="STUDY_R3",
            source_manifest_sha256=MANIFEST_HASH,
        ),
    )
    malformed = grant.model_dump()
    malformed["input_review_ref"] = grant.receipt.review_ref
    with pytest.raises(ValidationError):
        type(grant).model_validate(malformed)

    adapter.repo.current = replace(review, expires_at=NOW)
    with pytest.raises(BackendError):
        await adapter._continuation_authorization(adapter.uow, claim, adapter.task, now=NOW)


@pytest.mark.asyncio
async def test_input_review_list_and_detail_project_only_fixed_pins_and_disposition():
    adapter = FakeAdapter()
    actor = specialist()

    page = await adapter.school_research_education_input_review_list(
        actor, "TASK_synthetic_1", offset=0, limit=20
    )
    detail = await adapter.school_research_education_input_review_get(
        actor, "TASK_synthetic_1", INPUT_REVIEW_REF
    )

    assert page["items"][0]["reason_codes"] == ["CONTENT_CONTROVERSIAL"]
    assert page["items"][0]["continuation_enabled"] is False
    assert page["has_more"] is False
    assert detail["input_review_ref"] == INPUT_REVIEW_REF
    assert detail["fixed_request"]
    assert detail["policy_hash"] == POLICY_HASH
    assert not ({"subject_id", "decision_id", "safety_trace_id", "response_text"}
                & set(detail))
    assert len(adapter.session.statements) == 2


@pytest.mark.asyncio
async def test_input_review_list_uses_one_row_lookahead_and_caps_page_at_twenty():
    adapter = FakeAdapter()
    rows = [
        row(
            input_review_ref=f"REIR_{index:032x}",
            job_id=100 + index,
            job_ref=f"REJ_{index:064x}",
        )
        for index in range(21)
    ]
    adapter.repo.rows = rows
    adapter.job_facts = [adapter._expected_job_facts(item) for item in rows]

    page = await adapter.school_research_education_input_review_list(
        specialist(), "TASK_synthetic_1", offset=20, limit=20
    )

    assert len(page["items"]) == 20
    assert page["has_more"] is True
    assert page["offset"] == 20 and page["limit"] == 20
    assert adapter.repo.calls[0][1]["limit"] == 21


@pytest.mark.asyncio
async def test_input_review_list_fails_closed_on_any_stale_row_or_original_job():
    first = row()
    stale = replace(first, input_review_ref="REIR_" + "f" * 32, policy_hash="9" * 64)
    adapter = FakeAdapter(first)
    adapter.repo.rows = [first, stale]

    with pytest.raises(BackendError) as raised:
        await adapter.school_research_education_input_review_list(
            specialist(), "TASK_synthetic_1", offset=0, limit=20
        )
    assert raised.value.code.value == "workflow_conflict"

    adapter = FakeAdapter(first)
    adapter.job_facts = (*adapter.job_facts[:15], "GENERATION_FAILED", *adapter.job_facts[16:])
    with pytest.raises(BackendError) as raised:
        await adapter.school_research_education_input_review_get(
            specialist(), "TASK_synthetic_1", INPUT_REVIEW_REF
        )
    assert raised.value.code.value == "workflow_conflict"

    adapter = FakeAdapter(first)
    adapter.job_facts = (*adapter.job_facts[:4], 0, *adapter.job_facts[5:])
    with pytest.raises(BackendError) as raised:
        await adapter.school_research_education_input_review_get(
            specialist(), "TASK_synthetic_1", INPUT_REVIEW_REF
        )
    assert raised.value.code.value == "workflow_conflict"


@pytest.mark.asyncio
async def test_input_review_requires_current_scope_and_contentless_digest_binding():
    adapter = FakeAdapter()
    adapter.current_scope = scope(profile_sha256="9" * 64)
    with pytest.raises(BackendError) as raised:
        await adapter.school_research_education_input_review_get(
            specialist(), "TASK_synthetic_1", INPUT_REVIEW_REF
        )
    assert raised.value.code.value == "workflow_conflict"

    wrong_trace = trace_for_job(JOB_REF)[:-1] + "0"
    adapter = FakeAdapter(row(safety_trace_id=wrong_trace, trace_id=wrong_trace))
    with pytest.raises(BackendError) as raised:
        await adapter.school_research_education_input_review_get(
            specialist(), "TASK_synthetic_1", INPUT_REVIEW_REF
        )
    assert raised.value.code.value == "dependency_invalid_response"

    adapter = FakeAdapter(row(canonical_input_sha256="9" * 64))
    with pytest.raises(BackendError) as raised:
        await adapter.school_research_education_input_review_get(
            specialist(), "TASK_synthetic_1", INPUT_REVIEW_REF
        )
    assert raised.value.code.value == "workflow_conflict"


@pytest.mark.asyncio
async def test_expired_review_remains_readable_but_cannot_be_resolved():
    expired = row(expires_at=NOW - timedelta(minutes=1))
    adapter = FakeAdapter(expired)
    detail = await adapter.school_research_education_input_review_get(
        specialist(), "TASK_synthetic_1", INPUT_REVIEW_REF
    )
    assert detail["status"] == "PENDING"

    with pytest.raises(BackendError) as raised:
        await adapter.school_research_education_input_review_resolve(
            specialist(),
            "TASK_synthetic_1",
            INPUT_REVIEW_REF,
            expected_state_version=1,
            target="REJECTED",
            idempotency=("idem", "body", "scope"),
            trace_id="TRACE_synthetic_1",
        )
    assert raised.value.code.value == "workflow_conflict"
    assert not any(event[0] == "idempotency_begin" for event in adapter.events)

    too_long = row(expires_at=NOW + timedelta(days=2))
    adapter = FakeAdapter(too_long)
    with pytest.raises(BackendError) as raised:
        await adapter.school_research_education_input_review_get(
            specialist(), "TASK_synthetic_1", INPUT_REVIEW_REF
        )
    assert raised.value.code.value == "dependency_invalid_response"


@pytest.mark.asyncio
async def test_input_review_resolution_uses_only_reject_revoke_and_audits_once():
    adapter = FakeAdapter()
    result = await adapter.school_research_education_input_review_resolve(
        specialist(),
        "TASK_synthetic_1",
        INPUT_REVIEW_REF,
        expected_state_version=1,
        target="REVOKED",
        idempotency=("idem", "body", "scope"),
        trace_id="TRACE_synthetic_1",
    )
    assert result["status"] == "REVOKED"
    assert result["state_version"] == 2
    assert [call[0] for call in adapter.repo.calls] == ["get", "revoke"]
    assert any(event[0] == "audit" for event in adapter.events)
    assert any(event[0] == "idempotency_complete" for event in adapter.events)

    adapter = FakeAdapter()
    with pytest.raises(BackendError) as raised:
        await adapter.school_research_education_input_review_resolve(
            specialist(),
            "TASK_synthetic_1",
            INPUT_REVIEW_REF,
            expected_state_version=1,
            target="APPROVED",
            idempotency=("idem", "body", "scope"),
            trace_id="TRACE_synthetic_1",
        )
    assert raised.value.code.value == "validation_failed"
    assert not any(event[0] == "idempotency_begin" for event in adapter.events)


@pytest.mark.asyncio
async def test_input_review_replay_revalidates_role_scope_expiry_and_same_disposition():
    resolved = row(status="REJECTED", state_version=2)
    adapter = FakeAdapter(resolved)
    adapter.idempotency_replayed = True
    result = await adapter.school_research_education_input_review_resolve(
        specialist(),
        "TASK_synthetic_1",
        INPUT_REVIEW_REF,
        expected_state_version=1,
        target="REJECTED",
        idempotency=("idem", "body", "scope"),
        trace_id="TRACE_synthetic_1",
    )
    assert result["status"] == "REJECTED"
    assert not any(event[0] == "audit" for event in adapter.events)
    assert not any(event[0] == "idempotency_complete" for event in adapter.events)

    adapter = FakeAdapter(resolved)
    adapter.idempotency_replayed = True
    adapter.idempotency_receipt_ref = "REIR_" + "8" * 32
    with pytest.raises(BackendError) as raised:
        await adapter.school_research_education_input_review_resolve(
            specialist(),
            "TASK_synthetic_1",
            INPUT_REVIEW_REF,
            expected_state_version=1,
            target="REJECTED",
            idempotency=("idem", "body", "scope"),
            trace_id="TRACE_synthetic_1",
        )
    assert raised.value.code.value == "workflow_conflict"


@pytest.mark.asyncio
async def test_input_review_repository_errors_are_mapped_to_closed_backend_codes():
    async def raise_repo_error(exc):
        raise exc

    with pytest.raises(BackendError) as raised:
        await _input_review_repo_call(
            raise_repo_error(ResearchEducationInputReviewError("INVALID_PAGINATION"))
        )
    assert raised.value.code.value == "validation_failed"

    with pytest.raises(BackendError) as raised:
        await _input_review_repo_call(
            raise_repo_error(ResearchEducationInputReviewError("EXPIRY_EXCEEDS_RETENTION"))
        )
    assert raised.value.code.value == "workflow_conflict"
