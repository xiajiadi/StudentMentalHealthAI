from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from smhai_backend.adapters.database import MySqlBackendAdapter, SchoolIdempotencyClaim
from smhai_backend.domains.assessment.binding import D3_IDENTITY


class _Expression:
    def __and__(self, _other):
        return self


class _Column:
    def __eq__(self, _other):
        return _Expression()


class _ModelMeta(type):
    def __getattr__(cls, _name):
        return _Column()


class _Model(metaclass=_ModelMeta):
    pass


class _SchoolClass(_Model):
    pass


class _TaskEnrollment(_Model):
    pass


class _SchoolClassStudent(_Model):
    pass


class _SubjectAccessGrant(_Model):
    pass


class _MeasurementTask(_Model):
    pass


class _AssessmentSession(_Model):
    pass


class _SchoolCatSessionBinding(_Model):
    pass


class _Subject(_Model):
    pass


@dataclass
class _Counts:
    published_enrollment_count: int
    active_enrollment_count: int
    revoked_enrollment_count: int


class _Query:
    def __init__(self, model):
        self.model = model

    def where(self, *_args):
        return self

    def join(self, *_args):
        return self

    def with_for_update(self):
        return self


class _Session:
    def __init__(self, *, existing_session=None, audit_failure=False):
        self.existing_session = existing_session
        self.audit_failure = audit_failure
        self.added = []
        self.flush_count = 0
        self.pending_writes = []
        self.school_class = SimpleNamespace(id=51)
        self.enrollment = SimpleNamespace(id=61, task_id=71, subject_id=81)
        self.task = SimpleNamespace(
            id=71,
            task_ref="TASK_SYNTHETIC_AUDIT",
            public_id="task-public-ref",
            school_id=7,
            cat_binding_mode="FIXTURE",
            instrument_id=D3_IDENTITY.instrument_id,
            instrument_version=D3_IDENTITY.instrument_version,
            status="PUBLISHED",
            opens_at=datetime(2026, 10, 13, 1, tzinfo=UTC),
            due_at=None,
            published_at=datetime(2026, 10, 13, 1, tzinfo=UTC),
        )
        self.session_record = existing_session or SimpleNamespace(
            id=91,
            assessment_ref="ASSESS_SYNTHETIC_AUDIT",
            subject_id=81,
            instrument_id=D3_IDENTITY.instrument_id,
            instrument_version=D3_IDENTITY.instrument_version,
            item_bank_version="fixture-bank-v1",
            config_version="fixture-config-v1",
            started_at=datetime(2026, 10, 13, 1, tzinfo=UTC),
            status="CREATED",
            trace_id="TRACE_new-session",
        )

    async def scalar(self, statement):
        if statement.model is _SchoolClass:
            return self.school_class
        if statement.model is _TaskEnrollment:
            return self.enrollment
        if statement.model is _AssessmentSession:
            return self.existing_session
        if statement.model is _SchoolCatSessionBinding:
            return None
        if statement.model is _MeasurementTask:
            return self.task
        raise AssertionError(f"unexpected scalar model: {statement.model!r}")

    async def get(self, model, _record_id):
        if model is _MeasurementTask:
            return self.task
        if model is _Subject:
            return SimpleNamespace(subject_ref="SUBJ_SYNTHETIC_AUDIT")
        raise AssertionError(f"unexpected get model: {model!r}")

    def add(self, value):
        self.added.append(value)
        self.pending_writes.append(value)

    async def flush(self):
        self.flush_count += 1


class _Audit:
    def __init__(self, session, fail=False):
        self.session = session
        self.fail = fail
        self.calls = []

    async def append(self, **event):
        self.calls.append(event)
        if self.fail:
            raise RuntimeError("synthetic audit failure")
        self.session.pending_writes.append(event)


class _SchoolOperations:
    def __init__(self, session):
        self.session = session
        self.publish_calls = []
        self.prepare_calls = []

    async def publish_task_with_snapshot(self, **values):
        self.publish_calls.append(values)
        self.session.pending_writes.append("measurement-task-and-enrollments")
        task = self.session.task
        task.task_ref = values["task_ref"]
        task.instrument_id = values["instrument_id"]
        task.instrument_version = values["instrument_version"]
        task.status = "PUBLISHED"
        task.opens_at = values["opens_at"]
        task.due_at = values["due_at"]
        task.published_at = values["published_at"]
        return SimpleNamespace(task=task, enrollment_count=1)

    async def task_progress_counts(self, **_kwargs):
        return _Counts(
            published_enrollment_count=1,
            active_enrollment_count=1,
            revoked_enrollment_count=0,
        )

    async def create_task_assessment_session(self, **values):
        self.prepare_calls.append(values)
        if self.session.existing_session is None:
            self.session.pending_writes.append("assessment-session")
            self.session.session_record.trace_id = values["trace_id"]
        return self.session.session_record


class _Uow:
    def __init__(self, *, existing_session=None, audit_failure=False):
        self.session = _Session(existing_session=existing_session, audit_failure=audit_failure)
        self.school_operations = _SchoolOperations(self.session)
        self.audit = _Audit(self.session, fail=audit_failure)
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, _exc, _traceback):
        if exc_type is None:
            self.committed = True
        else:
            self.rolled_back = True
            self.session.pending_writes.clear()
        return False


def _adapter(uow, *, replayed=False, receipt_type="assessment_session"):
    adapter = MySqlBackendAdapter.__new__(MySqlBackendAdapter)
    adapter.identity_profile = "school_tenant"
    adapter._db_models = SimpleNamespace(
        SchoolClass=_SchoolClass,
        TaskEnrollment=_TaskEnrollment,
        SchoolClassStudent=_SchoolClassStudent,
        SubjectAccessGrant=_SubjectAccessGrant,
        MeasurementTask=_MeasurementTask,
        AssessmentSession=_AssessmentSession,
        SchoolCatSessionBinding=_SchoolCatSessionBinding,
        SchoolCatTaskBinding=object,
        Subject=_Subject,
    )
    adapter._db_enums = SimpleNamespace(
        AuditResult=SimpleNamespace(SUCCESS="SUCCESS")
    )
    adapter._select = _Query
    adapter._uow = lambda: uow

    async def school_role(_uow, _actor, role, _at, *, lock=False):
        assert role in {"admin", "student"}
        if role == "student":
            assert lock is True
        return 12, 13

    async def begin_idempotency(_uow, _claim):
        return SchoolIdempotencyClaim(
            record=SimpleNamespace(
                result_resource_type=receipt_type if replayed else None,
                result_public_id=(
                    "task-public-ref"
                    if replayed and receipt_type == "measurement_task"
                    else "ASSESS_SYNTHETIC_AUDIT" if replayed else None
                ),
            ),
            replayed=replayed,
        )

    async def complete_idempotency(_uow, _claim, *, resource_type, result_ref):
        uow.session.pending_writes.append(("idempotency", resource_type, result_ref))

    async def binding_fields(_uow, _actor, task):
        return {"activation_ref": None, "plan_name": None, "plan_version_number": None}

    async def assessment_binding(_uow, _actor, _task, _enrollment, _session, *, at):
        return {"cat_binding_mode": "FIXTURE"}

    adapter._school_actor_role = school_role
    adapter._school_idempotency_begin = begin_idempotency
    adapter._school_idempotency_complete = complete_idempotency
    adapter._task_cat_binding_fields = binding_fields
    adapter._school_task_assessment_binding = assessment_binding

    async def locked_scope(_uow, _actor, _account_id, enrollment, *, at):
        return enrollment, uow.session.task, SimpleNamespace(subject_ref="SUBJ_SYNTHETIC_AUDIT")

    adapter._lock_school_assessment_write_scope = locked_scope
    return adapter


def _actor():
    return SimpleNamespace(school_id=7)


@pytest.mark.asyncio
async def test_task_publish_appends_safe_actor_bound_audit_inside_creation_uow(monkeypatch):
    import smhai_backend.core.request_context as request_context

    uow = _Uow()
    adapter = _adapter(uow)
    trace_id = "TRACE_task_publish"
    monkeypatch.setattr(
        request_context,
        "get_request_context",
        lambda: SimpleNamespace(trace_id=trace_id),
    )
    at = datetime(2026, 10, 13, 1, tzinfo=UTC)

    result = await adapter.school_publish_task(
        _actor(),
        "CLASS_SYNTHETIC_AUDIT",
        "TASK_SYNTHETIC_AUDIT",
        opens_at=at,
        due_at=None,
        at=at,
        idempotency=("key", "f" * 64, "scope"),
    )

    assert result["task_ref"] == "TASK_SYNTHETIC_AUDIT"
    assert uow.committed and not uow.rolled_back
    assert uow.audit.calls == [
        {
            "action": "school_tasks.task.published",
            "resource_type": "measurement_task",
            "resource_public_id": "TASK_SYNTHETIC_AUDIT",
            "result": "SUCCESS",
            "trace_id": trace_id,
            "actor_account_id": 12,
            "safe_metadata": {"source": "backend", "state": "PUBLISHED"},
        }
    ]
    assert uow.session.pending_writes[-1] == uow.audit.calls[0]


@pytest.mark.asyncio
async def test_task_publish_audit_failure_rolls_back_creation_binding_and_receipt(monkeypatch):
    import smhai_backend.core.request_context as request_context

    uow = _Uow(audit_failure=True)
    adapter = _adapter(uow)
    monkeypatch.setattr(
        request_context,
        "get_request_context",
        lambda: SimpleNamespace(trace_id="TRACE_task_publish_rollback"),
    )
    at = datetime(2026, 10, 13, 1, tzinfo=UTC)

    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        await adapter.school_publish_task(
            _actor(),
            "CLASS_SYNTHETIC_AUDIT",
            "TASK_SYNTHETIC_AUDIT",
            opens_at=at,
            due_at=None,
            at=at,
            idempotency=("key", "f" * 64, "scope"),
        )

    assert uow.rolled_back and not uow.committed
    assert uow.session.pending_writes == []


@pytest.mark.asyncio
async def test_new_task_session_appends_trace_bound_audit_and_audit_failure_rolls_back():
    trace_id = "TRACE_task_session"
    uow = _Uow()
    uow.session.session_record.trace_id = trace_id
    adapter = _adapter(uow)
    at = datetime(2026, 10, 13, 2, tzinfo=UTC)

    result = await adapter.school_prepare_task_session(
        _actor(),
        "TASK_SYNTHETIC_AUDIT",
        "ASSESS_SYNTHETIC_AUDIT",
        at=at,
        trace_id=trace_id,
        idempotency=("start-key", "e" * 64, "scope"),
    )
    assert result["assessment_id"] == "ASSESS_SYNTHETIC_AUDIT"
    assert uow.committed and not uow.rolled_back
    assert uow.audit.calls == [
        {
            "action": "school_tasks.assessment_session.prepared",
            "resource_type": "assessment_session",
            "resource_public_id": "ASSESS_SYNTHETIC_AUDIT",
            "result": "SUCCESS",
            "trace_id": trace_id,
            "actor_account_id": 12,
            "safe_metadata": {"source": "backend", "state": "CREATED"},
        }
    ]

    failed_uow = _Uow(audit_failure=True)
    failed_uow.session.session_record.trace_id = trace_id
    failed_adapter = _adapter(failed_uow)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        await failed_adapter.school_prepare_task_session(
            _actor(),
            "TASK_SYNTHETIC_AUDIT",
            "ASSESS_SYNTHETIC_AUDIT",
            at=at,
            trace_id=trace_id,
            idempotency=("start-key", "e" * 64, "scope"),
        )
    assert failed_uow.rolled_back and not failed_uow.committed
    assert failed_uow.session.pending_writes == []


@pytest.mark.asyncio
async def test_reused_or_replayed_task_session_does_not_duplicate_audit():
    existing = SimpleNamespace(
        id=91,
        assessment_ref="ASSESS_SYNTHETIC_AUDIT",
        subject_id=81,
        instrument_id=D3_IDENTITY.instrument_id,
        instrument_version=D3_IDENTITY.instrument_version,
        item_bank_version="fixture-bank-v1",
        config_version="fixture-config-v1",
        started_at=datetime(2026, 10, 13, 1, tzinfo=UTC),
        status="IN_PROGRESS",
        trace_id="TRACE_original_session",
        cat_binding_mode="FIXTURE",
    )
    uow = _Uow(existing_session=existing)
    adapter = _adapter(uow)
    await adapter.school_prepare_task_session(
        _actor(),
        "TASK_SYNTHETIC_AUDIT",
        "ASSESS_unused_new_ref",
        at=datetime(2026, 10, 13, 2, tzinfo=UTC),
        trace_id="TRACE_reuse_session",
        idempotency=("new-reuse-key", "a" * 64, "scope"),
    )
    assert uow.committed and uow.audit.calls == []

    replay_uow = _Uow(existing_session=existing)
    replay_adapter = _adapter(replay_uow, replayed=True)
    await replay_adapter.school_prepare_task_session(
        _actor(),
        "TASK_SYNTHETIC_AUDIT",
        "ASSESS_unused_new_ref",
        at=datetime(2026, 10, 13, 2, tzinfo=UTC),
        trace_id="TRACE_replay_session",
        idempotency=("replay-key", "b" * 64, "scope"),
    )
    assert replay_uow.committed and replay_uow.audit.calls == []


@pytest.mark.asyncio
async def test_replayed_task_publication_does_not_duplicate_audit():
    uow = _Uow()
    adapter = _adapter(uow, replayed=True, receipt_type="measurement_task")
    result = await adapter.school_publish_task(
        _actor(),
        "CLASS_SYNTHETIC_AUDIT",
        "TASK_SYNTHETIC_AUDIT",
        opens_at=datetime(2026, 10, 13, 1, tzinfo=UTC),
        due_at=None,
        at=datetime(2026, 10, 13, 1, tzinfo=UTC),
        idempotency=("publish-replay", "c" * 64, "scope"),
    )
    assert result["task_ref"] == "TASK_SYNTHETIC_AUDIT"
    assert uow.committed and uow.audit.calls == []
