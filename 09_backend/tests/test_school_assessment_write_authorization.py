from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pytest

from smhai_backend.adapters.database import MySqlBackendAdapter
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.core.idempotency import fingerprint, remember_result_async
from smhai_backend.domains.assessment.binding import D3_IDENTITY
from smhai_backend.domains.assessment.schemas import ResponseEvent
from smhai_backend.domains.assessment.service import AssessmentService
from smhai_backend.domains.auth.dependencies import csrf_protected
from smhai_backend.domains.models import (
    Actor,
    AssessmentRecord,
    BackendRole,
    SchoolRoleContext,
)


def _actor() -> Actor:
    role_context = SchoolRoleContext(
        context_id="ROLE_synthetic_student",
        role=BackendRole.STUDENT,
        school_id=7,
        school_ref="SCHOOL_synthetic",
    )
    return Actor(
        user_id="USER_synthetic_student",
        username="synthetic-student",
        role=BackendRole.STUDENT,
        subject_id="SUBJECT_synthetic",
        scope_profile="school_tenant",
        school_id=7,
        school_ref="SCHOOL_synthetic",
        school_contexts=(role_context,),
    )


def _record(status: str = "in_progress") -> AssessmentRecord:
    return AssessmentRecord(
        assessment_id="ASSESS_synthetic_task",
        subject_id="SUBJECT_synthetic",
        assessment={
            "schema_version": "assessment.v1",
            "assessment_id": "ASSESS_synthetic_task",
            "subject_id": "SUBJECT_synthetic",
            "instrument": {
                "instrument_id": D3_IDENTITY.instrument_id,
                "version": D3_IDENTITY.instrument_version,
            },
            "population_scope": "SYNTHETIC_STUDENT_DEMO",
            "status": status,
            "dimensions": {},
            "risk": {},
            "response_summary": {"items_answered": 0, "duration_seconds": None},
            "provenance": {},
            "timestamps": {"started_at": "2026-10-13T00:00:00Z", "completed_at": None},
        },
        task_enrollment_id=90,
        cat_binding_mode="FIXTURE",
        current_item={"item_id": "ITEM_synthetic_1"},
        can_complete=True,
    )


class _Cat:
    label = "REAL_HTTP"

    async def state(self, session, **_kwargs):
        return session

    async def submit_response(self, *_args, **_kwargs):
        return {}

    async def complete(self, session, **_kwargs):
        return {
            "schema_version": "assessment.v1",
            "assessment_id": session.assessment_id,
            "subject_id": session.subject_id,
            "status": "completed",
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["submit", "complete"])
async def test_school_write_reauthorization_failure_persists_nothing_and_emits_no_audit(operation):
    stored = []
    audit_events = []
    source = _record()

    class Repository:
        async def school_save_assessment_for_actor(self, _actor, _record, **_kwargs):
            # Models an enrollment/window revocation that committed after the
            # service's post-CAT authorized read and before its write UOW.
            raise BackendError(ErrorCode.RESOURCE_NOT_FOUND, detail="assessment unavailable")

        async def save(self, value):
            stored.append(value)

    class Audit:
        async def record(self, **event):
            audit_events.append(event)

    service = AssessmentService.__new__(AssessmentService)
    service.repository = Repository()
    service.cat = _Cat()
    service.audit = Audit()
    service._sessions = {}

    async def authorized_read(_actor, _assessment_id, *_args, **_kwargs):
        return deepcopy(source)

    service._get_for_actor = authorized_read
    with pytest.raises(BackendError) as denied:
        if operation == "submit":
            await service.submit(
                _actor(),
                source.assessment_id,
                ResponseEvent(item_id="ITEM_synthetic_1", response=1),
                request_id="REQ_write_guard",
                trace_id="TRACE_write_guard",
            )
        else:
            await service.complete(
                _actor(),
                source.assessment_id,
                request_id="REQ_write_guard",
                trace_id="TRACE_write_guard",
            )

    assert denied.value.code is ErrorCode.RESOURCE_NOT_FOUND
    assert stored == []
    assert audit_events == []


@pytest.mark.asyncio
async def test_school_assessment_start_is_denied_before_cat_start():
    class Cat:
        calls = 0

        async def start(self, **_kwargs):
            self.calls += 1
            raise AssertionError("school must start from an assigned task")

    cat = Cat()
    service = AssessmentService.__new__(AssessmentService)
    service.cat = cat

    with pytest.raises(BackendError) as denied:
        await service.create(
            _actor(),
            SimpleNamespace(
                subject_id="SUBJECT_synthetic",
                instrument_id="x",
                instrument_version="v1",
            ),
            request_id="REQ_generic_school_start",
            trace_id="TRACE_generic_school_start",
        )

    assert denied.value.code is ErrorCode.FORBIDDEN
    assert cat.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "body", "scope", "expected_action"),
    [
        (
            "/api/v1/assessments/ASSESS_synthetic_task/responses",
            {"item_id": "ITEM_synthetic_1", "response": 1},
            "response",
            "assessment:write",
        ),
        (
            "/api/v1/assessments/ASSESS_synthetic_task/complete",
            {},
            "complete",
            "assessment:complete",
        ),
    ],
)
async def test_cached_school_response_replay_rechecks_current_authorization(
    app, client, path, body, scope, expected_action
):
    actor = _actor()
    assessment_id = "ASSESS_synthetic_task"
    key = f"cached-{scope}"
    fingerprint_payload = {"assessment_id": assessment_id}
    if scope == "response":
        fingerprint_payload.update(body)
    cache_scope = f"{actor.user_id}:assessment:{scope}:{assessment_id}"
    await remember_result_async(
        app.state.container.idempotency,
        scope=cache_scope,
        key=key,
        request_fingerprint=fingerprint(fingerprint_payload),
        status_code=200,
        body={"request_id": "cached", "trace_id": "cached", "data": {"cached": True}},
    )

    class Assessments:
        calls = []

        async def get_for_actor(self, _actor, requested_id, *, action, **_kwargs):
            self.calls.append((requested_id, action))
            raise BackendError(ErrorCode.RESOURCE_NOT_FOUND, detail="assessment unavailable")

        async def submit(self, *_args, **_kwargs):
            raise AssertionError("cached response replay must not reapply CAT mutation")

        async def complete(self, *_args, **_kwargs):
            raise AssertionError("cached completion replay must not rerun CAT")

    assessments = Assessments()
    app.state.container.assessments = assessments

    async def current_school_actor():
        return actor

    app.dependency_overrides[csrf_protected] = current_school_actor
    try:
        response = await client.post(path, json=body, headers={"Idempotency-Key": key})
    finally:
        app.dependency_overrides.pop(csrf_protected, None)

    assert response.status_code == 404
    assert response.json().get("data") != {"cached": True}
    assert assessments.calls == [(assessment_id, expected_action)]


@pytest.mark.asyncio
async def test_successful_school_completion_replay_does_not_enqueue_twice(app, client):
    actor = _actor()
    assessment_id = "ASSESS_synthetic_task"
    completion = _record("completed")
    completion.assessment.update(
        {
            "schema_version": "assessment.v1",
            "assessment_id": assessment_id,
            "subject_id": "SUBJECT_synthetic",
            "population_scope": "SYNTHETIC_STUDENT_DEMO",
            "dimensions": {},
            "risk": {
                "level": "normal",
                "need_human_review": False,
                "reason_codes": [],
                "ruleset_id": "synthetic-test",
            },
            "response_summary": {"items_answered": 0, "duration_seconds": None},
            "provenance": {
                "source_adapter": "synthetic",
                "adapter_version": "test",
                "cat_engine_version": "synthetic-cat",
                "item_bank_version": "synthetic-bank-v1",
            },
        }
    )
    completion.assessment["timestamps"]["completed_at"] = "2026-10-14T00:00:00Z"

    class Assessments:
        def __init__(self):
            self.authorized_reads = []
            self.completion_calls = 0
            self.job_enqueues = []

        async def get_for_actor(self, _actor, requested_id, *, action, **_kwargs):
            self.authorized_reads.append((requested_id, action))
            return deepcopy(completion)

        async def complete(self, _actor, requested_id, **_kwargs):
            assert requested_id == assessment_id
            self.completion_calls += 1
            self.job_enqueues.append(requested_id)
            return deepcopy(completion)

    assessments = Assessments()
    app.state.container.assessments = assessments

    async def current_school_actor():
        return actor

    app.dependency_overrides[csrf_protected] = current_school_actor
    headers = {"Idempotency-Key": "school-complete-replay"}
    try:
        first = await client.post(
            f"/api/v1/assessments/{assessment_id}/complete", json={}, headers=headers
        )
        replay = await client.post(
            f"/api/v1/assessments/{assessment_id}/complete", json={}, headers=headers
        )
    finally:
        app.dependency_overrides.pop(csrf_protected, None)

    assert first.status_code == replay.status_code == 200
    assert replay.json() == first.json()
    assert assessments.completion_calls == 1
    assert assessments.job_enqueues == [assessment_id]
    assert assessments.authorized_reads == [(assessment_id, "assessment:complete")]


@pytest.mark.asyncio
async def test_cached_school_generic_create_is_denied_before_idempotency_replay(app, client):
    actor = _actor()
    payload = {
        "subject_id": "SUBJ_synthetic",
        "instrument_id": "instrument.synthetic",
        "instrument_version": "1.0",
    }
    await remember_result_async(
        app.state.container.idempotency,
        scope=f"{actor.user_id}:assessment:create",
        key="preexisting-school-create",
        request_fingerprint=fingerprint(payload),
        status_code=201,
        body={"request_id": "cached", "trace_id": "cached", "data": {"cached": True}},
    )
    class Assessments:
        async def create(self, *_args, **_kwargs):
            raise AssertionError("school task route owns assessment starts")

    app.state.container.assessments = Assessments()

    async def current_school_actor():
        return actor

    app.dependency_overrides[csrf_protected] = current_school_actor
    try:
        response = await client.post(
            "/api/v1/assessments",
            json=payload,
            headers={"Idempotency-Key": "preexisting-school-create"},
        )
    finally:
        app.dependency_overrides.pop(csrf_protected, None)

    assert response.status_code == 403


class _Column:
    def __eq__(self, _other):
        return self

    def is_(self, _other):
        return self


class _Query:
    def __init__(self, model):
        self.model = model

    def where(self, *_args):
        return self

    def with_for_update(self):
        return self


class _TaskBinding:
    school_id = _Column()
    task_id = _Column()


class _SessionBinding:
    school_id = _Column()
    assessment_session_id = _Column()


class _AssessmentSession:
    id = _Column()
    assessment_ref = _Column()
    subject_id = _Column()
    task_enrollment_id = _Column()


@pytest.mark.asyncio
async def test_missing_saved_binding_is_denied_before_assessment_response_append():
    db_record = SimpleNamespace(
        id=80,
        assessment_ref="ASSESS_synthetic_task",
        subject_id=100,
        task_enrollment_id=90,
        status="IN_PROGRESS",
        cat_binding_mode="SAVED_VERSION",
    )
    enrollment = SimpleNamespace(id=90, school_id=7, subject_id=100, class_id=20, task_id=30)
    task = SimpleNamespace(
        id=30,
        cat_binding_mode="SAVED_VERSION",
        instrument_id="SYNTHETIC_CAT",
        instrument_version="synthetic_item_bank.v1 / demo.v1",
        item_bank_version="demo.v1",
        config_version="config.v1",
    )
    subject = SimpleNamespace(subject_ref="SUBJECT_synthetic")

    class Session:
        async def scalar(self, query):
            if query.model is _AssessmentSession:
                return db_record
            if query.model in {_TaskBinding, _SessionBinding}:
                return None
            raise AssertionError("unexpected database read")

    class Uow:
        def __init__(self):
            self.session = Session()
            self.assessments = SimpleNamespace(get_session=lambda _ref: _session())
            self.school_operations = SimpleNamespace(
                active_enrollment_for_assessment=lambda **_kwargs: _enrollment()
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    async def _session():
        return db_record

    async def _enrollment():
        return enrollment

    appended = []
    adapter = MySqlBackendAdapter.__new__(MySqlBackendAdapter)
    adapter.identity_profile = "school_tenant"
    adapter._db_models = SimpleNamespace(
        AssessmentSession=_AssessmentSession,
        SchoolCatTaskBinding=_TaskBinding,
        SchoolCatSessionBinding=_SessionBinding,
    )
    adapter._select = _Query
    adapter._uow = Uow

    async def role(_uow, _actor, role_code, _at, *, lock=False):
        assert role_code == "student" and lock is True
        return 1, 2

    async def lock_scope(_uow, _actor, _account_id, active_enrollment, *, at):
        return active_enrollment, task, subject

    async def save_in_uow(*_args, **_kwargs):
        appended.append("save")

    adapter._school_actor_role = role
    adapter._lock_school_assessment_write_scope = lock_scope
    adapter._save_assessment_in_uow = save_in_uow
    adapter._db_not_found = LookupError

    with pytest.raises(BackendError) as denied:
        await adapter.school_save_assessment_for_actor(
            _actor(),
            _record(),
            at=datetime(2026, 10, 13),
            trace_id="TRACE_missing_binding",
        )

    assert denied.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert appended == []


@pytest.mark.asyncio
async def test_revoked_enrollment_is_rechecked_inside_write_uow_before_save():
    writes = []

    class Uow:
        def __init__(self):
            self.school_operations = SimpleNamespace(
                active_enrollment_for_assessment=lambda **_kwargs: _no_active_enrollment()
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    async def _no_active_enrollment():
        return None

    adapter = MySqlBackendAdapter.__new__(MySqlBackendAdapter)
    adapter.identity_profile = "school_tenant"
    adapter._db_models = SimpleNamespace()
    adapter._uow = Uow

    async def role(_uow, _actor, role_code, _at, *, lock=False):
        assert role_code == "student" and lock is True
        return 1, 2

    async def should_not_lock_or_save(*_args, **_kwargs):
        writes.append("scope")

    async def should_not_persist(*_args, **_kwargs):
        writes.append("save")

    adapter._school_actor_role = role
    adapter._lock_school_assessment_write_scope = should_not_lock_or_save
    adapter._save_assessment_in_uow = should_not_persist
    with pytest.raises(BackendError) as denied:
        await adapter.school_save_assessment_for_actor(
            _actor(),
            _record(),
            at=datetime(2026, 10, 13),
            trace_id="TRACE_revoked_enrollment",
        )

    assert denied.value.code is ErrorCode.RESOURCE_NOT_FOUND
    assert writes == []
