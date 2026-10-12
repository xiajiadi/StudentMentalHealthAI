from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from smhai_backend.adapters.database import MySqlBackendAdapter, SchoolIdempotencyClaim
from smhai_backend.core.errors import BackendError, ErrorCode


class _Expression:
    def __and__(self, _other):
        return self


class _Column:
    def __eq__(self, _other):
        return _Expression()

    def is_(self, _other):
        return _Expression()


class _Query:
    def join(self, *_args):
        return self

    def where(self, *_args):
        return self


class _Session:
    async def scalar(self, _query):
        return SimpleNamespace(id=51, task_id=61)

    async def get(self, model, _record_id):
        if model is _Subject:
            return SimpleNamespace(subject_ref="SUBJECT_SYNTHETIC")
        if model is _MeasurementTask:
            return SimpleNamespace(task_ref="TASK_SYNTHETIC")
        raise AssertionError("unexpected model read")


class _Subject:
    pass


class _MeasurementTask:
    id = _Column()
    school_id = _Column()
    class_id = _Column()
    task_ref = _Column()


class _TaskEnrollment:
    school_id = _Column()
    status = _Column()
    task_id = _Column()
    class_id = _Column()
    id = _Column()


class _UnitOfWork:
    def __init__(self, school_operations):
        self.session = _Session()
        self.school_operations = school_operations

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback):
        return False


class _SchoolOperations:
    def __init__(self, *, failure=None):
        self.failure = failure
        self.calls = []

    async def create_task_assessment_session(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure is not None:
            raise self.failure
        return SimpleNamespace(
            assessment_ref=kwargs["assessment_ref"],
            subject_id=71,
            instrument_id="D3_IDENTITY",
            instrument_version="v1",
            item_bank_version="bank-v1",
            config_version="config-v1",
            started_at=kwargs["at"],
            status="IN_PROGRESS",
        )


def _replay_adapter(*, failure=None):
    operations = _SchoolOperations(failure=failure)
    uow = _UnitOfWork(operations)
    adapter = MySqlBackendAdapter.__new__(MySqlBackendAdapter)
    adapter.identity_profile = "school_tenant"
    adapter._db_models = SimpleNamespace(
        TaskEnrollment=_TaskEnrollment,
        MeasurementTask=_MeasurementTask,
        Subject=_Subject,
    )
    adapter._select = lambda _model: _Query()
    adapter._uow = lambda: uow

    async def resolve_actor(_uow, _actor, role_code, _at):
        assert role_code == "student"
        return 12, 34

    async def claim_receipt(_uow, _idempotency):
        record = SimpleNamespace(
            result_resource_type="assessment_session",
            result_public_id="ASSESS_SYNTHETIC",
        )
        return SchoolIdempotencyClaim(record=record, replayed=True)

    async def unexpected_completion(*_args, **_kwargs):
        raise AssertionError("a replay must not complete the old receipt")

    adapter._school_actor_role = resolve_actor
    adapter._school_idempotency_begin = claim_receipt
    adapter._school_idempotency_complete = unexpected_completion
    return adapter, operations


@pytest.mark.asyncio
async def test_replayed_task_start_returns_existing_guarded_session_without_recompleting_receipt():
    adapter, operations = _replay_adapter()
    at = datetime(2026, 10, 11, 12, tzinfo=UTC)
    actor = SimpleNamespace(school_id=8)

    result = await adapter.school_prepare_task_session(
        actor,
        "TASK_SYNTHETIC",
        "ASSESS_UNUSED",
        at=at,
        trace_id="trace-synthetic",
        idempotency=("key", "f" * 64, "scope"),
    )

    assert result == {
        "assessment_id": "ASSESS_SYNTHETIC",
        "subject_id": "SUBJECT_SYNTHETIC",
        "instrument_id": "D3_IDENTITY",
        "instrument_version": "v1",
        "item_bank_version": "bank-v1",
        "config_version": "config-v1",
        "started_at": at,
        "task_ref": "TASK_SYNTHETIC",
        "session_status": "IN_PROGRESS",
    }
    assert operations.calls == [
        {
            "enrollment_id": 51,
            "assessment_ref": "ASSESS_SYNTHETIC",
            "school_id": 8,
            "student_account_id": 12,
            "at": at,
            "trace_id": "trace-synthetic",
        }
    ]


@pytest.mark.asyncio
async def test_replayed_task_start_still_propagates_current_enrollment_or_window_denial():
    denial = BackendError(ErrorCode.RESOURCE_NOT_FOUND, detail="open task unavailable")
    adapter, operations = _replay_adapter(failure=denial)

    with pytest.raises(BackendError) as caught:
        await adapter.school_prepare_task_session(
            SimpleNamespace(school_id=8),
            "TASK_SYNTHETIC",
            "ASSESS_UNUSED",
            at=datetime(2026, 10, 11, 12, tzinfo=UTC),
            trace_id="trace-synthetic",
            idempotency=("key", "f" * 64, "scope"),
        )

    assert caught.value.code is ErrorCode.RESOURCE_NOT_FOUND
    assert len(operations.calls) == 1
