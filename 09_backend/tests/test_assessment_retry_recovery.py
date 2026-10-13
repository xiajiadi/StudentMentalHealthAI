from __future__ import annotations

from copy import deepcopy

import pytest

from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.assessment.service import (
    AssessmentService,
    _is_commit_outcome_uncertain,
    _same_json_value,
)
from smhai_backend.domains.authorization import NativeAuthorizationProvider
from smhai_backend.domains.models import Actor, AssessmentRecord, BackendRole
from smhai_backend.integrations.cat import CatStart

_ASSESSMENT_ID = "ASSESS_retry_synthetic"
_SUBJECT_ID = "SUBJ_retry_synthetic"
_STARTED_AT = "2026-10-13T00:00:00Z"
_SAVED_BINDING = {
    "binding_ref": "CSBIND_" + "a" * 36,
    "activation_ref": "CACT_" + "b" * 36,
    "plan_version_ref": "CPVER_" + "c" * 36,
    "bank_version_ref": "CBVER_" + "d" * 36,
}
_BANK_DOCUMENT = {
    "instrument_id": "CURRENT_SYNTHETIC_GRM",
    "version": "demo.v1",
    "metadata": {"instrument_version": "synthetic_item_bank.v1 / demo.v1"},
}
_CONFIG_DOCUMENT = {"config_version": "demo.cat.v1"}


def _record(*, responses=None, mode="FIXTURE"):
    return AssessmentRecord(
        assessment_id=_ASSESSMENT_ID,
        subject_id=_SUBJECT_ID,
        assessment={
            "status": "in_progress",
            "instrument": {
                "instrument_id": "CURRENT_SYNTHETIC_GRM",
                "version": "synthetic_item_bank.v1 / demo.v1",
            },
            "timestamps": {"started_at": _STARTED_AT},
            "response_summary": {"items_answered": len(responses or {})},
            "dimensions": {"wellbeing": {"items_answered": len(responses or {})}},
        },
        responses=dict(responses or {}),
        task_enrollment_id=81,
        cat_binding_mode=mode,
        saved_binding=dict(_SAVED_BINDING) if mode == "SAVED_VERSION" else None,
        saved_bank_document=deepcopy(_BANK_DOCUMENT) if mode == "SAVED_VERSION" else None,
        saved_config_document=deepcopy(_CONFIG_DOCUMENT) if mode == "SAVED_VERSION" else None,
        cat_item_bank_version="demo.v1" if mode == "SAVED_VERSION" else None,
        cat_config_version="demo.cat.v1" if mode == "SAVED_VERSION" else None,
    )


def _actor(*, subject_id=_SUBJECT_ID):
    return Actor(
        user_id="USER_retry_synthetic",
        username="student_retry_synthetic",
        role=BackendRole.STUDENT,
        subject_id=subject_id,
        accessible_subject_ids=frozenset({subject_id}),
        scope_profile="school_tenant",
        school_id=7,
        school_ref="SCHOOL_retry_synthetic",
    )


class _AuthoritativeRepository:
    def __init__(self, record, *, fail_save=None, deny_read_at=None):
        self.record = deepcopy(record)
        self.fail_save = fail_save
        self.deny_read_at = deny_read_at
        self.reads = 0
        self.saves = 0

    async def school_get_assessment_for_actor(self, actor, assessment_id, *, at):
        self.reads += 1
        assert actor.role is BackendRole.STUDENT
        assert assessment_id == self.record.assessment_id
        if actor.subject_id != self.record.subject_id:
            return None
        if self.deny_read_at == self.reads:
            return None
        return deepcopy(self.record)

    async def school_save_assessment_for_actor(self, actor, record, *, at, trace_id):
        self.saves += 1
        if self.fail_save == "before_commit":
            raise BackendError(
                ErrorCode.DEPENDENCY_UNAVAILABLE, detail="synthetic persistence failure"
            )
        if self.fail_save == "program_error":
            raise RuntimeError("synthetic programming failure")
        self.record = deepcopy(record)
        if self.fail_save == "after_commit":
            raise BackendError(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                detail="synthetic commit acknowledgement failure",
            )


class _IdempotentCat:
    label = "REAL_HTTP"

    def __init__(self, *, mode="FIXTURE", responses=(), unavailable=False):
        self.mode = mode
        self.binding = dict(_SAVED_BINDING) if mode == "SAVED_VERSION" else None
        self.available = not unavailable
        self.session = self._session(
            administered_count=len(responses),
            current_item={"item_id": f"ITEM_{len(responses) + 1}"},
        )
        self.accepted = list(responses)
        self.posts = []
        self.starts = 0

    def _session(self, *, administered_count, current_item):
        return CatStart(
            assessment_id=_ASSESSMENT_ID,
            subject_id=_SUBJECT_ID,
            instrument_id="CURRENT_SYNTHETIC_GRM",
            instrument_version="synthetic_item_bank.v1 / demo.v1",
            started_at=_STARTED_AT,
            current_item=current_item,
            current_index=administered_count,
            answered_count=administered_count,
            administered_count=administered_count,
            item_bank_version="demo.v1",
            config_version="demo.cat.v1",
            provider_version="synthetic-cat.v1",
            cat_binding_mode=self.mode,
            saved_binding=self.binding,
        )

    async def state(self, session, **_kwargs):
        if not self.available:
            raise BackendError(ErrorCode.RESOURCE_NOT_FOUND, detail="synthetic CAT missing")
        return self.session

    async def start(self, **_kwargs):
        self.starts += 1
        self.available = True
        self.accepted = []
        self.session = self._session(
            administered_count=0, current_item={"item_id": "ITEM_1"}
        )
        return self.session

    async def start_saved_session(self, **_kwargs):
        return await self.start()

    async def submit_response(self, session, *, item_id, response, **_kwargs):
        self.posts.append((item_id, deepcopy(response)))
        if item_id == (self.session.current_item or {}).get("item_id"):
            self.accepted.append((item_id, deepcopy(response)))
            self.session = self._session(
                administered_count=self.session.administered_count + 1,
                current_item={"item_id": f"ITEM_{self.session.administered_count + 2}"},
            )
            return {}
        if self.accepted and self.accepted[-1] == (item_id, response):
            return {}
        raise BackendError(ErrorCode.WORKFLOW_CONFLICT, detail="synthetic CAT item mismatch")


class _Audit:
    def __init__(self):
        self.events = []

    async def record(self, **kwargs):
        self.events.append(kwargs["event"])
        return None


def _service(repository, cat):
    return AssessmentService(
        repository=repository,
        cat=cat,
        authorization=NativeAuthorizationProvider(),
        audit=_Audit(),
    )


async def _submit(service, actor, *, item_id="ITEM_1", response=2):
    from smhai_backend.domains.assessment.schemas import ResponseEvent

    return await service.submit(
        actor,
        _ASSESSMENT_ID,
        ResponseEvent(item_id=item_id, response=response),
        request_id="REQ_retry_synthetic",
        trace_id="TRACE_retry_synthetic",
    )


@pytest.mark.asyncio
async def test_retry_after_uncommitted_write_uses_db_history_and_cat_exact_duplicate():
    repository = _AuthoritativeRepository(_record(), fail_save="before_commit")
    cat = _IdempotentCat()
    service = _service(repository, cat)

    with pytest.raises(BackendError) as caught:
        await _submit(service, _actor())
    assert caught.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert repository.record.responses == {}
    assert cat.accepted == [("ITEM_1", 2)]

    repository.fail_save = None
    result = await _submit(service, _actor())

    assert repository.record.responses == {"ITEM_1": 2}
    assert repository.saves == 2
    assert cat.posts == [("ITEM_1", 2), ("ITEM_1", 2)]
    assert cat.accepted == [("ITEM_1", 2)]
    assert result.current_item == {"item_id": "ITEM_2"}


@pytest.mark.asyncio
async def test_commit_with_lost_ack_is_confirmed_by_one_actor_scoped_reread():
    repository = _AuthoritativeRepository(_record(), fail_save="after_commit")
    cat = _IdempotentCat()
    service = _service(repository, cat)
    result = await _submit(service, _actor())

    assert repository.record.responses == {"ITEM_1": 2}
    assert repository.saves == 1
    assert repository.reads == 3  # initial read, pre-write refresh, and commit check
    assert cat.posts == [("ITEM_1", 2)]
    assert result.responses == {"ITEM_1": 2}
    assert service.audit.events == ["ASSESSMENT_RESPONSE_ACCEPTED"]


@pytest.mark.asyncio
async def test_persisted_exact_retry_skips_cat_post_and_type_mismatch_conflicts():
    repository = _AuthoritativeRepository(_record(responses={"ITEM_1": True}))
    cat = _IdempotentCat(responses=(("ITEM_1", True),))
    service = _service(repository, cat)

    result = await _submit(service, _actor(), response=True)
    assert result.responses == {"ITEM_1": True}
    assert cat.posts == []
    assert repository.saves == 0
    assert service.audit.events == []

    with pytest.raises(BackendError) as caught:
        await _submit(service, _actor(), response=1)
    assert caught.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert cat.posts == []
    assert repository.saves == 0


@pytest.mark.asyncio
async def test_commit_reread_denial_preserves_write_error_without_cat_repost():
    repository = _AuthoritativeRepository(
        _record(), fail_save="before_commit", deny_read_at=3
    )
    cat = _IdempotentCat()
    service = _service(repository, cat)

    with pytest.raises(BackendError) as caught:
        await _submit(service, _actor())
    assert caught.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE

    assert repository.reads == 3
    assert repository.saves == 1
    assert cat.posts == [("ITEM_1", 2)]
    assert repository.record.responses == {}


@pytest.mark.asyncio
async def test_unclassified_program_error_is_not_hidden_by_commit_probe():
    repository = _AuthoritativeRepository(_record(), fail_save="program_error")
    cat = _IdempotentCat()

    with pytest.raises(RuntimeError, match="synthetic programming failure"):
        await _submit(_service(repository, cat), _actor())

    assert repository.reads == 2  # initial authorized read and pre-write refresh only
    assert repository.saves == 1
    assert cat.posts == [("ITEM_1", 2)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("subject_id", "deny_read_at"),
    [("SUBJ_other_synthetic", None), (_SUBJECT_ID, 1)],
    ids=["other-subject", "revoked-enrollment"],
)
async def test_actor_scoped_missing_or_other_subject_fails_before_cat_or_save(
    subject_id, deny_read_at
):
    repository = _AuthoritativeRepository(_record(), deny_read_at=deny_read_at)
    cat = _IdempotentCat()

    with pytest.raises(BackendError) as caught:
        await _submit(_service(repository, cat), _actor(subject_id=subject_id))

    assert caught.value.code is ErrorCode.RESOURCE_NOT_FOUND
    assert cat.posts == []
    assert repository.saves == 0


@pytest.mark.asyncio
async def test_persisted_old_item_retry_returns_current_cat_state_without_reposting():
    repository = _AuthoritativeRepository(
        _record(responses={"ITEM_1": "A", "ITEM_2": "B"})
    )
    cat = _IdempotentCat(
        responses=(("ITEM_1", "A"), ("ITEM_2", "B")),
    )

    result = await _submit(_service(repository, cat), _actor(), response="A")

    assert result.responses == {"ITEM_1": "A", "ITEM_2": "B"}
    assert result.current_item == {"item_id": "ITEM_3"}
    assert cat.posts == []
    assert repository.saves == 0


@pytest.mark.asyncio
async def test_cat_404_recovery_replays_only_persisted_history_before_duplicate_return():
    repository = _AuthoritativeRepository(_record(responses={"ITEM_1": "A"}))
    cat = _IdempotentCat(responses=(("ITEM_1", "A"),), unavailable=True)
    result = await _submit(_service(repository, cat), _actor(), response="A")

    assert cat.starts == 1
    assert cat.posts == [("ITEM_1", "A")]
    assert cat.accepted == [("ITEM_1", "A")]
    assert result.responses == {"ITEM_1": "A"}
    assert result.current_item == {"item_id": "ITEM_2"}
    assert repository.saves == 0


@pytest.mark.asyncio
async def test_saved_version_duplicate_keeps_exact_binding_and_skips_cat_post():
    repository = _AuthoritativeRepository(
        _record(responses={"ITEM_1": "A"}, mode="SAVED_VERSION")
    )
    cat = _IdempotentCat(mode="SAVED_VERSION", responses=(("ITEM_1", "A"),))
    result = await _submit(_service(repository, cat), _actor(), response="A")

    assert result.cat_binding_mode == "SAVED_VERSION"
    assert result.saved_binding == _SAVED_BINDING
    assert result.cat_item_bank_version == "demo.v1"
    assert result.cat_config_version == "demo.cat.v1"
    assert cat.posts == []
    assert repository.saves == 0


@pytest.mark.asyncio
async def test_completed_assessment_rejects_response_retry_without_cat_or_save():
    completed = _record(responses={"ITEM_1": "A"})
    completed.assessment["status"] = "completed"
    repository = _AuthoritativeRepository(completed)
    cat = _IdempotentCat(responses=(("ITEM_1", "A"),))

    with pytest.raises(BackendError) as caught:
        await _submit(_service(repository, cat), _actor(), response="A")

    assert caught.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert cat.posts == []
    assert repository.saves == 0


def test_json_equality_is_recursive_order_independent_and_rejects_non_json_values():
    assert _same_json_value({"a": [True], "b": 2}, {"b": 2, "a": [True]})
    assert not _same_json_value({"a": [True]}, {"a": [1]})
    assert not _same_json_value({"a": (1, 2)}, {"a": [1, 2]})


def test_commit_probe_recognizes_storage_errors_but_not_programming_errors():
    sqlalchemy_error = type(
        "SQLAlchemyError", (Exception,), {"__module__": "sqlalchemy.exc"}
    )
    db_error = type("OperationalError", (sqlalchemy_error,), {"__module__": "sqlalchemy.exc"})

    assert _is_commit_outcome_uncertain(db_error("synthetic"))
    assert _is_commit_outcome_uncertain(
        BackendError(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="synthetic")
    )
    assert not _is_commit_outcome_uncertain(RuntimeError("synthetic"))



@pytest.mark.asyncio
async def test_readonly_retry_rejects_concurrent_completion_on_fresh_read():
    class CompletedOnRefresh(_AuthoritativeRepository):
        async def school_get_assessment_for_actor(self, actor, assessment_id, *, at):
            if self.reads == 1:
                self.record.assessment["status"] = "completed"
            return await super().school_get_assessment_for_actor(actor, assessment_id, at=at)

    repository = CompletedOnRefresh(_record(responses={"ITEM_1": 2}))
    cat = _IdempotentCat(responses=(("ITEM_1", 2),))
    service = _service(repository, cat)
    with pytest.raises(BackendError) as caught:
        await _submit(service, _actor())
    assert caught.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert repository.saves == 0
    assert cat.posts == []
    assert service.audit.events == []


@pytest.mark.asyncio
async def test_commit_probe_rejects_concurrent_completed_record():
    class CompletedAfterCommit(_AuthoritativeRepository):
        async def school_save_assessment_for_actor(self, actor, record, *, at, trace_id):
            try:
                await super().school_save_assessment_for_actor(
                    actor, record, at=at, trace_id=trace_id
                )
            except BackendError:
                self.record.assessment["status"] = "completed"
                raise

    repository = CompletedAfterCommit(_record(), fail_save="after_commit")
    cat = _IdempotentCat()
    service = _service(repository, cat)
    with pytest.raises(BackendError) as caught:
        await _submit(service, _actor())
    assert caught.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert repository.record.assessment["status"] == "completed"
    assert repository.record.responses == {"ITEM_1": 2}
    assert cat.posts == [("ITEM_1", 2)]
    assert service.audit.events == []
