from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

import smhai_backend.adapters.school_post_assessment as adapter_module
from smhai_backend.adapters.school_post_assessment import (
    SchoolPostAssessmentAuthorization,
    SchoolPostAssessmentPersistenceAdapter,
    SchoolPostAssessmentWorkerManager,
)
from smhai_backend.core.config import PostAssessmentWorkerSettings
from smhai_backend.domains.post_assessment.service import (
    PersistenceStage,
    PostAssessmentAuthorizationFailure,
    PostAssessmentAuthorizationScope,
    PostAssessmentPersistenceFailure,
)

NOW = datetime(2026, 10, 14, 9, 0)
SCOPE = PostAssessmentAuthorizationScope(
    school_id=101,
    task_id=201,
    class_id=301,
    class_student_id=401,
    task_enrollment_id=501,
    subject_id=601,
    assessment_session_id=701,
)


@dataclass(frozen=True)
class _Predicate:
    text: str

    def __and__(self, other):
        return _Predicate(f"({self.text} AND {other.text})")

    def __or__(self, other):
        return _Predicate(f"({self.text} OR {other.text})")

    def __str__(self):
        return self.text


class _Column:
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return _Predicate(f"{self.name}={other!r}")

    def __le__(self, other):
        return _Predicate(f"{self.name}<={other!r}")

    def __ge__(self, other):
        return _Predicate(f"{self.name}>={other!r}")

    def is_(self, other):
        return _Predicate(f"{self.name} IS {other!r}")

    def is_not(self, other):
        return _Predicate(f"{self.name} IS NOT {other!r}")

    def __repr__(self):
        return self.name


class _Model:
    def __init__(self, name, *columns):
        self.__name__ = name
        for column in ("id", *columns):
            setattr(self, column, _Column(f"{name}.{column}"))


class _Query:
    def __init__(self, columns):
        self.columns = columns
        self.joins = []
        self.predicates = []
        self.limit_value = None
        self.distinct_value = False

    def select_from(self, model):
        self.source = model.__name__
        return self

    def join(self, model, condition=None):
        self.joins.append((model.__name__, condition))
        return self

    def where(self, *conditions):
        self.predicates.extend(conditions)
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def distinct(self):
        self.distinct_value = True
        return self

    def order_by(self, *_values):
        return self

    def predicate_text(self):
        return " ".join(str(item) for item in self.predicates)


class _Result:
    def __init__(self, values):
        self.values = values

    def all(self):
        return list(self.values)


class _Session:
    def __init__(self, *, assessment_ref: str | None = "ASMT_701", principal_ids=(801,)):
        self.assessment_ref = assessment_ref
        self.principal_ids = list(principal_ids)
        self.statements = []
        self.models: Any = None

    async def scalar(self, statement):
        self.statements.append(statement)
        if statement.columns == (self.models.AssessmentSession.assessment_ref,):
            return self.assessment_ref
        return None

    async def scalars(self, statement):
        self.statements.append(statement)
        if statement.columns == (self.models.SubjectAccessGrant.principal_account_id,):
            return _Result(self.principal_ids)
        return _Result([101])


class _Uow:
    def __init__(self, session, enrollment):
        self.session = session
        self.school_operations = SimpleNamespace(
            completed_enrollment_for_post_assessment=self._active_enrollment
        )
        self.enrollment = enrollment
        self.lookups = []

    async def _active_enrollment(self, **values):
        self.lookups.append(values)
        return self.enrollment

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class _Persistence:
    def __init__(self, session, enrollment=None):
        self.identity_profile = "school_tenant"
        self._started = True
        self._db_models = SimpleNamespace(
            School=_Model("schools", "status", "data_origin"),
            AssessmentSession=_Model(
                "assessment_sessions",
                "assessment_ref",
                "status",
                "completed_at",
                "task_enrollment_id",
                "subject_id",
            ),
            TaskEnrollment=_Model(
                "task_enrollments",
                "school_id",
                "task_id",
                "class_id",
                "class_student_id",
                "subject_id",
                "status",
                "revoked_at",
            ),
            SubjectAccessGrant=_Model(
                "subject_access_grants",
                "principal_account_id",
                "school_id",
                "subject_id",
                "relationship_type",
                "status",
                "revoked_at",
                "valid_from",
                "valid_until",
            ),
            AssessmentResponse=_Model("assessment_responses", "payload_ciphertext"),
            AssessmentResult=_Model("assessment_results", "payload_ciphertext"),
        )
        session.models = self._db_models
        self._db_enums = SimpleNamespace(
            DataOrigin=SimpleNamespace(SYNTHETIC=SimpleNamespace(value="SYNTHETIC"))
        )
        self._utc_now = lambda: NOW
        self._select = lambda *columns: _Query(columns)
        self._session = session
        self._enrollment = enrollment
        self.uow = _Uow(session, enrollment)
        self._started = True

    def _uow(self):
        return self.uow


@pytest.mark.asyncio
async def test_authorization_uses_exact_completed_scope_and_reuses_active_enrollment_predicate():
    enrollment = SimpleNamespace(
        id=SCOPE.task_enrollment_id,
        school_id=SCOPE.school_id,
        task_id=SCOPE.task_id,
        class_id=SCOPE.class_id,
        class_student_id=SCOPE.class_student_id,
        subject_id=SCOPE.subject_id,
    )
    session = _Session()
    persistence = _Persistence(session, enrollment)
    authorization = SchoolPostAssessmentAuthorization(persistence, school_id=SCOPE.school_id)

    assert await authorization.is_authorized(SCOPE) is True
    assessment_query, grant_query = session.statements
    assert assessment_query.columns == (persistence._db_models.AssessmentSession.assessment_ref,)
    assert {name for name, _condition in assessment_query.joins} == {"task_enrollments"}
    assessment_conditions = assessment_query.predicate_text()
    for expected in (
        "assessment_sessions.id=701",
        "assessment_sessions.status='COMPLETED'",
        "assessment_sessions.completed_at IS NOT None",
        "task_enrollments.school_id=101",
        "task_enrollments.task_id=201",
        "task_enrollments.class_id=301",
        "task_enrollments.class_student_id=401",
        "task_enrollments.subject_id=601",
        "task_enrollments.status='ACTIVE'",
    ):
        assert expected in assessment_conditions
    grant_conditions = grant_query.predicate_text()
    assert "subject_access_grants.relationship_type='SELF'" in grant_conditions
    assert "subject_access_grants.status='ACTIVE'" in grant_conditions
    assert persistence.uow.lookups == [
        {"assessment_ref": "ASMT_701", "student_account_id": 801, "at": NOW}
    ]
    assert "assessment_responses" not in repr(session.statements)
    assert "assessment_results" not in repr(session.statements)


@pytest.mark.asyncio
async def test_authorization_fails_closed_for_wrong_school_missing_session_or_ambiguous_grant():
    enrollment = SimpleNamespace(
        id=SCOPE.task_enrollment_id,
        school_id=SCOPE.school_id,
        task_id=SCOPE.task_id,
        class_id=SCOPE.class_id,
        class_student_id=SCOPE.class_student_id,
        subject_id=SCOPE.subject_id,
    )
    wrong_scope = PostAssessmentAuthorizationScope(
        school_id=999,
        task_id=SCOPE.task_id,
        class_id=SCOPE.class_id,
        class_student_id=SCOPE.class_student_id,
        task_enrollment_id=SCOPE.task_enrollment_id,
        subject_id=SCOPE.subject_id,
        assessment_session_id=SCOPE.assessment_session_id,
    )
    session = _Session(assessment_ref=None)
    persistence = _Persistence(session, enrollment)
    authorization = SchoolPostAssessmentAuthorization(persistence, school_id=SCOPE.school_id)

    assert await authorization.is_authorized(wrong_scope) is False
    assert await authorization.is_authorized(SCOPE) is False
    assert persistence.uow.lookups == []

    ambiguous_session = _Session(principal_ids=(801, 802))
    ambiguous_persistence = _Persistence(ambiguous_session, enrollment)
    ambiguous_auth = SchoolPostAssessmentAuthorization(
        ambiguous_persistence, school_id=SCOPE.school_id
    )
    assert await ambiguous_auth.is_authorized(SCOPE) is False
    assert ambiguous_persistence.uow.lookups == []


@pytest.mark.asyncio
async def test_active_school_inventory_is_metadata_only_and_synthetic_scoped():
    session = _Session()
    persistence = _Persistence(session)

    async def scalars(statement):
        session.statements.append(statement)
        return _Result([101, 202])

    session.scalars = scalars
    adapter = SchoolPostAssessmentPersistenceAdapter(persistence)
    assert await adapter.active_school_ids() == [101, 202]
    query = session.statements[-1]
    assert query.columns == (persistence._db_models.School.id,)
    assert "schools.status='ACTIVE'" in query.predicate_text()
    assert "schools.data_origin='SYNTHETIC'" in query.predicate_text()

class _FakeAuthorization:
    async def is_authorized(self, _scope):
        return False


class _FakeAdapter:
    def __init__(self, persistence, school_ids):
        self.persistence = persistence
        self.school_ids = school_ids

    async def active_school_ids(self):
        return list(self.school_ids)

    def authorization_for_school(self, school_id: int):
        del school_id
        return _FakeAuthorization()


class _FakeWorker:
    instances = []

    def __init__(self, **values):
        self.values = values
        self.stop_event = asyncio.Event()
        self._run_task = None
        self.__class__.instances.append(self)

    async def _run(self):
        await self.stop_event.wait()

    def start(self):
        self._run_task = asyncio.create_task(self._run())
        return self._run_task

    async def stop(self, *, drain=True):
        del drain
        self.stop_event.set()
        if self._run_task is not None:
            await self._run_task


@pytest.mark.asyncio
async def test_manager_starts_per_school_with_shared_lock_and_safe_health(monkeypatch):
    class _ReadyPersistence:
        identity_profile = "school_tenant"
        _started = True
        _utc_now = staticmethod(lambda: NOW)

        def _uow(self):
            return None

    _FakeWorker.instances.clear()
    monkeypatch.setattr(adapter_module, "PostAssessmentWorker", _FakeWorker)
    monkeypatch.setattr(
        adapter_module,
        "database_persistence_error_mapper",
        lambda: object(),
    )
    persistence = _ReadyPersistence()
    manager = SchoolPostAssessmentWorkerManager(
        _FakeAdapter(persistence, [101, 202]),
        PostAssessmentWorkerSettings(),
    )

    await manager.start()
    assert set(manager.workers) == {101, 202}
    assert len(_FakeWorker.instances) == 2
    assert _FakeWorker.instances[0].values["concurrency_lock"] is manager._global_lock
    assert _FakeWorker.instances[1].values["concurrency_lock"] is manager._global_lock
    assert manager.dependency_status()["status"] == "READY"
    await manager.close()
    assert all(worker._run_task.done() for worker in _FakeWorker.instances)
    with pytest.raises(RuntimeError, match="cannot be restarted"):
        await manager.start()


@pytest.mark.asyncio
async def test_manager_fails_startup_when_database_error_mapper_is_unavailable(monkeypatch):
    class _ReadyPersistence:
        identity_profile = "school_tenant"
        _started = True

        def _uow(self):
            return None

    def missing_mapper():
        raise RuntimeError("database persistence error mapping is unavailable")

    monkeypatch.setattr(adapter_module, "database_persistence_error_mapper", missing_mapper)
    manager = SchoolPostAssessmentWorkerManager(
        _FakeAdapter(_ReadyPersistence(), [101]), PostAssessmentWorkerSettings()
    )

    with pytest.raises(RuntimeError, match="mapping is unavailable"):
        await manager.start()
    assert manager.workers == {}
    assert manager._started is False


@pytest.mark.asyncio
async def test_worker_failure_is_visible_without_logging_exception_text(monkeypatch, caplog):
    class _FailedWorker(_FakeWorker):
        async def _run(self):
            raise PostAssessmentPersistenceFailure(PersistenceStage.RETRY)

    class _ReadyPersistence:
        identity_profile = "school_tenant"
        _started = True
        _utc_now = staticmethod(lambda: NOW)

        def _uow(self):
            return None

    _FailedWorker.instances.clear()
    monkeypatch.setattr(adapter_module, "PostAssessmentWorker", _FailedWorker)
    monkeypatch.setattr(adapter_module, "database_persistence_error_mapper", lambda: object())
    manager = SchoolPostAssessmentWorkerManager(
        _FakeAdapter(_ReadyPersistence(), [101]), PostAssessmentWorkerSettings()
    )
    await manager.start()
    for _ in range(3):
        if manager.health[101].status == "UNAVAILABLE":
            break
        await asyncio.sleep(0)

    assert manager.health[101].status == "UNAVAILABLE"
    assert manager.health[101].failure_code == "PERSISTENCE_RETRY"
    assert manager.dependency_status()["status"] == "UNAVAILABLE"
    assert "persistence failed during retry" not in caplog.text
    await manager.close()


@pytest.mark.asyncio
async def test_unexpected_worker_cancellation_marks_manager_unavailable(monkeypatch, caplog):
    class _ReadyPersistence:
        identity_profile = "school_tenant"
        _started = True
        _utc_now = staticmethod(lambda: NOW)

        def _uow(self):
            return None

    _FakeWorker.instances.clear()
    monkeypatch.setattr(adapter_module, "PostAssessmentWorker", _FakeWorker)
    monkeypatch.setattr(adapter_module, "database_persistence_error_mapper", lambda: object())
    manager = SchoolPostAssessmentWorkerManager(
        _FakeAdapter(_ReadyPersistence(), [101]), PostAssessmentWorkerSettings()
    )

    await manager.start()
    worker = manager.workers[101]
    task = worker._run_task
    assert task is not None
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)

    assert manager.health[101].status == "UNAVAILABLE"
    assert manager.health[101].failure_code == "UNEXPECTED_WORKER_STOP"
    assert manager.dependency_status()["status"] == "UNAVAILABLE"
    assert caplog.records[-1].failure_code == "UNEXPECTED_WORKER_STOP"
    await manager.close()


@pytest.mark.asyncio
async def test_authorization_failure_marks_health_unavailable_with_fixed_code(
    monkeypatch, caplog
):
    class _FailedWorker(_FakeWorker):
        async def _run(self):
            raise PostAssessmentAuthorizationFailure()

    class _ReadyPersistence:
        identity_profile = "school_tenant"
        _started = True
        _utc_now = staticmethod(lambda: NOW)

        def _uow(self):
            return None

    _FailedWorker.instances.clear()
    monkeypatch.setattr(adapter_module, "PostAssessmentWorker", _FailedWorker)
    monkeypatch.setattr(adapter_module, "database_persistence_error_mapper", lambda: object())
    manager = SchoolPostAssessmentWorkerManager(
        _FakeAdapter(_ReadyPersistence(), [101]), PostAssessmentWorkerSettings()
    )

    await manager.start()
    for _ in range(3):
        if manager.health[101].status == "UNAVAILABLE":
            break
        await asyncio.sleep(0)

    assert manager.health[101].status == "UNAVAILABLE"
    assert manager.health[101].failure_code == "AUTHORIZATION_FAILURE"
    assert manager.dependency_status()["status"] == "UNAVAILABLE"
    assert caplog.records[-1].failure_code == "AUTHORIZATION_FAILURE"
    await manager.close()
