from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from database_layer import enums as db_enums
from database_layer import models as db_models
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.mysql import MEDIUMBLOB
from sqlalchemy.orm import Session

from smhai_backend.adapters.database import MySqlBackendAdapter, _hash_token
from smhai_backend.adapters.school_research import SchoolResearchPersistenceAdapter
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.models import Actor, BackendRole, SchoolRoleContext

NOW = datetime(2026, 10, 14, 9, 30)
SCHOOL_PROVENANCE = "SYNTHETIC_REF_AUTH_TENANT_FIXTURE_V1"
IDEMPOTENCY_KEY = "research-start-replay-key"
IDEMPOTENCY_FINGERPRINT = hashlib.sha256(b"start-task-body").hexdigest()
IDEMPOTENCY_SCOPE = hashlib.sha256(
    b"school_research:start:synthetic-school-a:task-demo-1:student-a"
).hexdigest()
IDEMPOTENCY = (IDEMPOTENCY_KEY, IDEMPOTENCY_FINGERPRINT, IDEMPOTENCY_SCOPE)


class _AsyncSessionFacade:
    """Async-shaped calls over a real in-memory SQLite SQLAlchemy Session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement):
        return self._session.execute(statement)

    async def scalar(self, statement):
        return self._session.scalar(statement)

    async def scalars(self, statement):
        return self._session.scalars(statement)

    async def flush(self):
        self._session.flush()

    def add(self, value):
        self._session.add(value)


class _ResearchRepositorySpy:
    def __init__(self) -> None:
        self.scope_lock_calls = 0
        self.decrypt_calls = 0
        self.metadata_calls = 0

    async def get_session_l1_metadata(self, **_kwargs):
        self.metadata_calls += 1
        return SimpleNamespace(
            session_ref="research-session-existing",
            school_id=101,
            task_id=401,
            class_id=401,
            task_enrollment_id=601,
            subject_id=501,
            task_binding_id=701,
            profile_version_id=700,
            profile_ref="profile-demo",
            profile_version_number=1,
            profile_sha256="a" * 64,
            response_origin="PUBLIC_OBSERVED",
            config_version="config-v1",
            config_sha256="b" * 64,
            status="IN_PROGRESS",
            state_version=1,
            items_answered=0,
            stop_reason=None,
            started_at=NOW,
            completed_at=None,
        )

    async def lock_student_task_scope(self, **_kwargs):
        self.scope_lock_calls += 1
        raise AssertionError("unauthorized candidate reached locked research scope")

    async def load_session_for_resume(self, **_kwargs):
        self.decrypt_calls += 1
        raise AssertionError("unauthorized candidate reached snapshot decryption")


class _UnitOfWork:
    def __init__(self, session: Session, repo: _ResearchRepositorySpy) -> None:
        self.session = _AsyncSessionFacade(session)
        self.research_cat = repo

    async def __aenter__(self):
        self._session = self.session._session
        if not self._session.in_transaction():
            self._session.begin()
        return self

    async def __aexit__(self, exc_type, _exc, _traceback):
        if exc_type is None:
            self._session.commit()
        else:
            self._session.rollback()


class _ClientFactorySpy:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, _binding):
        self.calls += 1
        raise AssertionError("unauthorized candidate reached CAT client creation")


@pytest.fixture
def live_scope(monkeypatch):
    # Keep the SQLite-only compatibility shim inside this fixture. Registering
    # a global @compiles handler at module import would alter unrelated tests.
    original_dispatch = MEDIUMBLOB._compiler_dispatch

    def local_dispatch(value, compiler, **kwargs):
        if compiler.dialect.name == "sqlite":
            return "BLOB"
        return original_dispatch(value, compiler, **kwargs)

    monkeypatch.setattr(MEDIUMBLOB, "_compiler_dispatch", local_dispatch)
    engine = create_engine("sqlite:///:memory:")
    statements: list[str] = []
    event.listen(
        engine,
        "connect",
        lambda connection, _record: connection.create_collation(
            "ascii_bin", lambda left, right: (left > right) - (left < right)
        ),
    )
    event.listen(
        engine,
        "before_cursor_execute",
        lambda _connection, _cursor, statement, _parameters, _context, _executemany: (
            statements.append(statement.lower())
        ),
    )
    table_names = {
        "accounts",
        "schools",
        "account_school_memberships",
        "membership_roles",
        "subjects",
        "subject_access_grants",
        "school_classes",
        "school_class_students",
        "measurement_tasks",
        "task_enrollments",
        "idempotency_records",
        "school_research_sessions",
    }
    tables = [table for table in db_models.Base.metadata.sorted_tables if table.name in table_names]
    db_models.Base.metadata.create_all(engine, tables=tables)
    session = Session(engine, expire_on_commit=False)
    _seed_school_scope(session)
    _seed_in_progress_session(session)

    owner = object.__new__(MySqlBackendAdapter)
    owner.identity_profile = "school_tenant"
    owner._db_models = db_models
    owner._db_enums = db_enums
    owner._select = select
    owner._utc_now = lambda: NOW
    repo = _ResearchRepositorySpy()
    owner._uow = lambda: _UnitOfWork(session, repo)
    owner._school_actor_role = MySqlBackendAdapter._school_actor_role.__get__(owner)
    factory = _ClientFactorySpy()
    persistence = SchoolResearchPersistenceAdapter(owner, client_for_binding=factory)
    _seed_completed_idempotency(session)
    yield SimpleNamespace(
        engine=engine,
        session=session,
        statements=statements,
        owner=owner,
        repo=repo,
        factory=factory,
        persistence=persistence,
    )
    session.close()
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "teacher", "admin", "disabled_account", "revoked_membership", "expired_role", "wrong_context",
])
async def test_current_identity_denials_precede_scope_and_decryption(live_scope, case):
    actor = _actor()
    if case == "teacher":
        actor = replace(actor, role=BackendRole.TEACHER)
    elif case == "admin":
        actor = replace(actor, role=BackendRole.ADMIN)
    elif case == "disabled_account":
        live_scope.session.get(db_models.Account, 201).status = "DISABLED"
    elif case == "revoked_membership":
        membership = live_scope.session.get(db_models.AccountSchoolMembership, 301)
        membership.status = "REVOKED"
        membership.revoked_at = NOW - timedelta(minutes=1)
    elif case == "expired_role":
        live_scope.session.get(db_models.MembershipRole, 302).valid_until = (
            NOW - timedelta(minutes=1)
        )
    else:
        actor = replace(actor, school_contexts=(
            replace(actor.school_contexts[0], context_id="wrong-context"),
        ))
    live_scope.session.flush()
    live_scope.statements.clear()
    with pytest.raises(BackendError) as raised:
        await live_scope.persistence.prepare_start(
            actor, "task-demo-1", at=NOW, idempotency=IDEMPOTENCY,
        )
    # The scope resolver intentionally conceals task existence for a nonstudent;
    # a revoked persisted identity is rejected by the current-role provider.
    expected_code = (
        ErrorCode.RESOURCE_NOT_FOUND if case in {"teacher", "admin"} else ErrorCode.FORBIDDEN
    )
    assert raised.value.code == expected_code
    assert not any("measurement_tasks" in query for query in live_scope.statements)
    assert live_scope.repo.scope_lock_calls == 0
    assert live_scope.repo.decrypt_calls == 0
    assert live_scope.factory.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "cross_school_task",
        "wrong_self_grant",
        "revoked_roster",
        "revoked_enrollment",
        "expired_task",
    ],
)
async def test_live_scope_denials_precede_research_lock_and_cat_http(live_scope, case):
    actor = _actor()
    task_ref = "task-demo-1"
    if case == "cross_school_task":
        _add_second_school_task(live_scope.session)
        task_ref = "task-demo-2"
    elif case == "wrong_self_grant":
        _grant(live_scope.session).relationship_type = "GUARDIAN_OF"
    elif case == "revoked_roster":
        roster = live_scope.session.get(db_models.SchoolClassStudent, 501)
        roster.status = "REVOKED"
        roster.revoked_at = NOW - timedelta(minutes=1)
    elif case == "revoked_enrollment":
        enrollment = live_scope.session.get(db_models.TaskEnrollment, 601)
        enrollment.status = "REVOKED"
        enrollment.revoked_at = NOW - timedelta(minutes=1)
    elif case == "expired_task":
        task = live_scope.session.get(db_models.MeasurementTask, 401)
        task.opens_at = NOW - timedelta(days=2)
        task.due_at = NOW - timedelta(minutes=1)
    live_scope.session.flush()

    with pytest.raises(BackendError) as raised:
        await live_scope.persistence.prepare_start(
            actor,
            task_ref,
            at=NOW,
            idempotency=IDEMPOTENCY,
        )

    assert live_scope.repo.scope_lock_calls == 0
    assert getattr(raised.value, "code", None) == ErrorCode.RESOURCE_NOT_FOUND
    assert any(
        "measurement_tasks" in statement and "subject_access_grants" in statement
        for statement in live_scope.statements
    )
    assert live_scope.repo.decrypt_calls == 0
    assert live_scope.repo.metadata_calls == 0
    assert live_scope.factory.calls == 0


@pytest.mark.asyncio
async def test_completed_idempotency_replay_is_reauthorized_before_receipt_lookup(live_scope):
    # A durable completed receipt exists for the exact operation. Revoking the
    # student roster must stop authorization before the real receipt query.
    roster = live_scope.session.get(db_models.SchoolClassStudent, 501)
    roster.status = "REVOKED"
    roster.revoked_at = NOW - timedelta(minutes=1)
    live_scope.session.commit()

    begin_calls = 0
    actual_begin = MySqlBackendAdapter._school_idempotency_begin.__get__(live_scope.owner)

    async def observe_actual_replay_lookup(uow, idempotency):
        nonlocal begin_calls
        begin_calls += 1
        return await actual_begin(uow, idempotency)

    live_scope.owner._school_idempotency_begin = observe_actual_replay_lookup

    with pytest.raises(BackendError) as raised:
        await live_scope.persistence.prepare_start(
            _actor(), "task-demo-1", at=NOW, idempotency=IDEMPOTENCY
        )

    assert getattr(raised.value, "code", None) == ErrorCode.RESOURCE_NOT_FOUND
    assert begin_calls == 0
    assert any(
        "measurement_tasks" in statement and "subject_access_grants" in statement
        for statement in live_scope.statements
    )
    receipt = live_scope.session.scalar(
        select(db_models.IdempotencyRecord).where(
            db_models.IdempotencyRecord.scope == IDEMPOTENCY_SCOPE,
            db_models.IdempotencyRecord.key_hash == _hash_token(IDEMPOTENCY_KEY),
        )
    )
    assert receipt is not None
    assert receipt.state == db_enums.IdempotencyState.COMPLETED.value
    assert live_scope.repo.scope_lock_calls == 0
    assert live_scope.repo.decrypt_calls == 0
    assert live_scope.repo.metadata_calls == 0
    assert live_scope.factory.calls == 0


@pytest.mark.asyncio
async def test_revoked_roster_rejects_resume_before_snapshot_decryption_or_cat_http(live_scope):
    roster = live_scope.session.get(db_models.SchoolClassStudent, 501)
    roster.status = "REVOKED"
    roster.revoked_at = NOW - timedelta(minutes=1)
    live_scope.session.commit()

    with pytest.raises(BackendError) as raised:
        await live_scope.persistence.prepare_resume(_actor(), "research-session-existing", at=NOW)

    assert getattr(raised.value, "code", None) == ErrorCode.RESOURCE_NOT_FOUND
    assert any(
        "school_research_sessions" in statement and "subject_access_grants" in statement
        for statement in live_scope.statements
    )
    assert live_scope.repo.metadata_calls == 1  # content-free lookup only
    assert live_scope.repo.scope_lock_calls == 0
    assert live_scope.repo.decrypt_calls == 0
    assert live_scope.factory.calls == 0


def _seed_school_scope(session: Session) -> None:
    session.add_all(
        [
            db_models.School(
                id=101,
                public_id="school-public-a",
                school_ref="synthetic-school-a",
                display_name="Synthetic School A",
                status="ACTIVE",
                data_origin="SYNTHETIC",
                provenance_ref=SCHOOL_PROVENANCE,
            ),
            db_models.Account(
                id=201,
                public_id="live-student-a",
                login_name="student-a@example.invalid",
                password_hash="synthetic-test-hash",
                status="ACTIVE",
            ),
            db_models.AccountSchoolMembership(
                id=301,
                public_id="membership-a",
                account_id=201,
                school_id=101,
                status="ACTIVE",
                valid_from=NOW - timedelta(days=30),
            ),
            db_models.MembershipRole(
                id=302,
                public_id="student-role-a",
                membership_id=301,
                school_id=101,
                role_code="student",
                status="ACTIVE",
                valid_from=NOW - timedelta(days=30),
            ),
            db_models.Subject(
                id=501,
                public_id="subject-public-a",
                subject_ref="subject-demo-a",
                school_id=101,
                status="ACTIVE",
                data_origin="SYNTHETIC",
            ),
            db_models.SubjectAccessGrant(
                id=502,
                public_id="grant-a",
                principal_account_id=201,
                subject_id=501,
                school_id=101,
                relationship_type="SELF",
                status="ACTIVE",
                valid_from=NOW - timedelta(days=30),
            ),
            db_models.SchoolClass(
                id=401,
                public_id="class-public-a",
                school_id=101,
                class_ref="class-demo-a",
                created_by_membership_role_id=302,
                status="ACTIVE",
            ),
            db_models.SchoolClassStudent(
                id=501,
                public_id="roster-public-a",
                school_id=101,
                class_id=401,
                subject_id=501,
                status="ACTIVE",
                valid_from=NOW - timedelta(days=30),
            ),
            db_models.MeasurementTask(
                id=401,
                public_id="task-public-a",
                school_id=101,
                class_id=401,
                task_ref="task-demo-1",
                created_by_membership_role_id=302,
                instrument_id="synthetic.research.demo",
                instrument_version="0.1",
                opens_at=NOW - timedelta(days=1),
                due_at=NOW + timedelta(days=1),
                published_at=NOW - timedelta(days=1),
                status="PUBLISHED",
                cat_binding_mode="RESEARCH_PROFILE",
            ),
            db_models.TaskEnrollment(
                id=601,
                public_id="enrollment-public-a",
                school_id=101,
                task_id=401,
                class_id=401,
                class_student_id=501,
                subject_id=501,
                status="ACTIVE",
            ),
        ]
    )
    session.commit()


def _seed_completed_idempotency(session: Session) -> None:
    session.add(
        db_models.IdempotencyRecord(
            id=901,
            public_id="idem-public-replay",
            scope=IDEMPOTENCY_SCOPE,
            key_hash=_hash_token(IDEMPOTENCY_KEY),
            request_hash=bytes.fromhex(IDEMPOTENCY_FINGERPRINT),
            state=db_enums.IdempotencyState.COMPLETED.value,
            result_resource_type="research_session",
            result_public_id="research-session-existing",
            expires_at=NOW + timedelta(hours=1),
        )
    )
    session.commit()


def _seed_in_progress_session(session: Session) -> None:
    session.add(
        db_models.SchoolResearchSession(
            id=1001,
            public_id="research-session-public",
            session_ref="research-session-existing",
            school_id=101,
            task_id=401,
            class_id=401,
            task_enrollment_id=601,
            subject_id=501,
            task_binding_id=701,
            profile_version_id=700,
            profile_ref="profile-demo",
            profile_version_number=1,
            profile_sha256="a" * 64,
            response_origin="PUBLIC_OBSERVED",
            config_version="config-v1",
            config_sha256="b" * 64,
            purpose="RESEARCH_SIMULATION",
            research_only=True,
            status="IN_PROGRESS",
            state_version=1,
            items_answered=0,
            snapshot_ciphertext=b"synthetic-ciphertext-placeholder",
            snapshot_sha256="c" * 64,
            cipher_format_version="test-v1",
            key_version="test-key",
            payload_schema_version="test-schema",
            started_at=NOW,
        )
    )
    session.commit()


def _add_second_school_task(session: Session) -> None:
    session.add_all(
        [
            db_models.School(
                id=102,
                public_id="school-public-b",
                school_ref="synthetic-school-b",
                display_name="Synthetic School B",
                status="ACTIVE",
                data_origin="SYNTHETIC",
                provenance_ref=SCHOOL_PROVENANCE,
            ),
            db_models.Account(
                id=202,
                public_id="live-student-b",
                login_name="student-b@example.invalid",
                password_hash="synthetic-test-hash",
                status="ACTIVE",
            ),
            db_models.AccountSchoolMembership(
                id=303,
                public_id="membership-b",
                account_id=202,
                school_id=102,
                status="ACTIVE",
                valid_from=NOW - timedelta(days=30),
            ),
            db_models.MembershipRole(
                id=304,
                public_id="student-role-b",
                membership_id=303,
                school_id=102,
                role_code="student",
                status="ACTIVE",
                valid_from=NOW - timedelta(days=30),
            ),
            db_models.Subject(
                id=503,
                public_id="subject-public-b",
                subject_ref="subject-demo-b",
                school_id=102,
                status="ACTIVE",
                data_origin="SYNTHETIC",
            ),
            db_models.SubjectAccessGrant(
                id=504,
                public_id="grant-b",
                principal_account_id=202,
                subject_id=503,
                school_id=102,
                relationship_type="SELF",
                status="ACTIVE",
                valid_from=NOW - timedelta(days=30),
            ),
            db_models.SchoolClass(
                id=402,
                public_id="class-public-b",
                school_id=102,
                class_ref="class-demo-b",
                created_by_membership_role_id=304,
                status="ACTIVE",
            ),
            db_models.SchoolClassStudent(
                id=502,
                public_id="roster-public-b",
                school_id=102,
                class_id=402,
                subject_id=503,
                status="ACTIVE",
                valid_from=NOW - timedelta(days=30),
            ),
            db_models.MeasurementTask(
                id=402,
                public_id="task-public-b",
                school_id=102,
                class_id=402,
                task_ref="task-demo-2",
                created_by_membership_role_id=304,
                instrument_id="synthetic.research.demo",
                instrument_version="0.1",
                opens_at=NOW - timedelta(days=1),
                due_at=NOW + timedelta(days=1),
                published_at=NOW - timedelta(days=1),
                status="PUBLISHED",
                cat_binding_mode="RESEARCH_PROFILE",
            ),
            db_models.TaskEnrollment(
                id=602,
                public_id="enrollment-public-b",
                school_id=102,
                task_id=402,
                class_id=402,
                class_student_id=502,
                subject_id=503,
                status="ACTIVE",
            ),
        ]
    )
    session.flush()


def _grant(session: Session):
    return session.get(db_models.SubjectAccessGrant, 502)


def _actor() -> Actor:
    return Actor(
        user_id="USER_live-student-a",
        username="student-a",
        role=BackendRole.STUDENT,
        subject_id=None,
        scope_profile="school_tenant",
        school_id=101,
        school_ref="synthetic-school-a",
        school_contexts=(
            SchoolRoleContext(
                context_id="302",
                role=BackendRole.STUDENT,
                school_id=101,
                school_ref="synthetic-school-a",
            ),
        ),
    )
