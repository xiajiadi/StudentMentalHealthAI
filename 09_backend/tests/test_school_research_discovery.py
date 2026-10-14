from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from database_layer import enums as db_enums
from database_layer import models as db_models
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.mysql import MEDIUMBLOB
from sqlalchemy.orm import Session

from smhai_backend.adapters.database import MySqlBackendAdapter
from smhai_backend.adapters.school_research_discovery import (
    SchoolResearchDiscoveryPersistenceAdapter,
)
from smhai_backend.core.errors import (
    BackendError,
    ErrorCode,
    backend_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from smhai_backend.core.request_context import make_context
from smhai_backend.domains.auth.dependencies import current_actor
from smhai_backend.domains.models import BackendRole
from smhai_backend.domains.school_research.study_use import (
    ResearchStudyProfilePin,
    ResearchStudyUsePolicy,
)
from smhai_backend.domains.school_research_discovery.router import router
from smhai_backend.domains.school_research_discovery.schemas import (
    ResearchDiscoverySessionPage,
    ResearchDiscoveryTaskPage,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_school_research_live_scope as live_scope_helpers

NOW = datetime(2026, 10, 14, 9, 30)
PROFILE_SHA = "a" * 64
MANIFEST_SHA = "b" * 64
CROSSWALK_SHA = "c" * 64
CONFIG_SHA = "d" * 64


class _AsyncSessionFacade:
    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement):
        return self._session.execute(statement)

    async def scalar(self, statement):
        return self._session.scalar(statement)


class _UnitOfWork:
    def __init__(self, session: Session) -> None:
        self.session = _AsyncSessionFacade(session)
        self._sync_session = session

    async def __aenter__(self):
        if not self._sync_session.in_transaction():
            self._sync_session.begin()
        return self

    async def __aexit__(self, exc_type, _exc, _traceback):
        if exc_type is None:
            self._sync_session.commit()
        else:
            self._sync_session.rollback()


def _policy() -> ResearchStudyUsePolicy:
    return ResearchStudyUsePolicy(
        study_ref="synthetic-replay-study",
        school_id=101,
        institution="Synthetic School A",
        use_scope="ISOLATED_HISTORICAL_REPLAY",
        noncommercial=True,
        historical_replay_only=True,
        english_unchanged=True,
        starts_at=(NOW - timedelta(days=2)).replace(tzinfo=UTC),
        ends_at=(NOW + timedelta(days=3)).replace(tzinfo=UTC),
        profiles=(
            ResearchStudyProfilePin(
                profile_ref="profile-demo",
                profile_sha256=PROFILE_SHA,
                manifest_sha256=MANIFEST_SHA,
                published_crosswalk_sha256=CROSSWALK_SHA,
            ),
        ),
        rights_basis="Synthetic fixture for repository testing",
        rights_source_urls=("https://example.invalid/rights",),
        recorded_by="synthetic-test-operator",
        recorded_at=(NOW - timedelta(days=1)).replace(tzinfo=UTC),
        operator_declaration="Synthetic fixture only",
        source_rights_verified=True,
    )


@pytest.fixture
def discovery_scope(monkeypatch):
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
        "school_research_profile_versions",
        "school_research_task_bindings",
        "school_research_sessions",
    }
    tables = [table for table in db_models.Base.metadata.sorted_tables if table.name in table_names]
    db_models.Base.metadata.create_all(engine, tables=tables)
    session = Session(engine, expire_on_commit=False)
    live_scope_helpers._seed_school_scope(session)
    _seed_research_profile_and_binding(session)

    owner = object.__new__(MySqlBackendAdapter)
    owner.identity_profile = "school_tenant"
    owner._db_models = db_models
    owner._db_enums = db_enums
    owner._select = select
    owner._uow = lambda: _UnitOfWork(session)
    owner._school_actor_role = MySqlBackendAdapter._school_actor_role.__get__(owner)
    adapter = SchoolResearchDiscoveryPersistenceAdapter(owner, study_use_policy=_policy())
    yield SimpleNamespace(
        engine=engine,
        session=session,
        statements=statements,
        owner=owner,
        adapter=adapter,
        actor=live_scope_helpers._actor(),
    )
    session.close()
    engine.dispose()


def _seed_research_profile_and_binding(session: Session) -> None:
    session.get(db_models.MeasurementTask, 401).instrument_id = "PROMIS_ANXIETY"
    session.get(db_models.MeasurementTask, 401).instrument_version = "research-v1"
    session.get(db_models.MeasurementTask, 401).config_version = "config-v1"
    session.add_all(
        [
            db_models.SchoolResearchProfileVersion(
                id=700,
                public_id="profile-version-public-a",
                school_id=101,
                profile_ref="profile-demo",
                version_number=1,
                instrument_id="PROMIS_ANXIETY",
                dimension="ANXIETY",
                source_population_scope="US_8_17",
                profile_sha256=PROFILE_SHA,
                manifest_sha256=MANIFEST_SHA,
                fit_sha256=None,
                calibration_sha256=None,
                parameter_origin="PUBLISHED_ROUNDED_REFERENCE",
                published_parameter_crosswalk_sha256=CROSSWALK_SHA,
                rights_status="VERIFIED",
                execution_status="SIMULATION_ENABLED",
                research_only=True,
                human_curated=False,
                psychological_interpretation_allowed=False,
                publication_status=("not_approved_for_publication_or_operational_use"),
                purpose="RESEARCH_SIMULATION",
                payload_ciphertext=b"synthetic encrypted metadata fixture",
                cipher_format_version="test-v1",
                key_version="test-key",
                payload_schema_version="test-schema",
                created_by_membership_role_id=302,
                status_changed_by_membership_role_id=302,
                simulation_enabled_at=NOW - timedelta(days=1),
            ),
            db_models.SchoolResearchTaskBinding(
                id=701,
                public_id="binding-public-a",
                school_id=101,
                task_id=401,
                class_id=401,
                profile_version_id=700,
                profile_ref="profile-demo",
                profile_version_number=1,
                profile_sha256=PROFILE_SHA,
                response_origin="PUBLIC_OBSERVED",
                status="ACTIVE",
                purpose="RESEARCH_SIMULATION",
                research_only=True,
                config_version="config-v1",
                config_sha256=CONFIG_SHA,
                config_ciphertext=b"synthetic encrypted config fixture",
                cipher_format_version="test-v1",
                key_version="test-key",
                payload_schema_version="test-schema",
                created_by_membership_role_id=302,
            ),
        ]
    )
    session.commit()


def _seed_completed_session(session: Session, *, session_ref: str = "own-session-1") -> None:
    session.add(
        db_models.SchoolResearchSession(
            id=1001,
            public_id="research-session-public-a",
            session_ref=session_ref,
            school_id=101,
            task_id=401,
            class_id=401,
            task_enrollment_id=601,
            subject_id=501,
            task_binding_id=701,
            profile_version_id=700,
            profile_ref="profile-demo",
            profile_version_number=1,
            profile_sha256=PROFILE_SHA,
            response_origin="PUBLIC_OBSERVED",
            config_version="config-v1",
            config_sha256=CONFIG_SHA,
            purpose="RESEARCH_SIMULATION",
            research_only=True,
            status="COMPLETED",
            state_version=2,
            items_answered=4,
            stop_reason="max_items_reached",
            snapshot_ciphertext=b"synthetic encrypted session state fixture",
            snapshot_sha256="e" * 64,
            cipher_format_version="test-v1",
            key_version="test-key",
            payload_schema_version="test-schema",
            started_at=NOW - timedelta(hours=1),
            completed_at=NOW - timedelta(minutes=1),
        )
    )
    session.commit()


class _ApiService:
    def __init__(self):
        self.calls = []

    async def list_tasks(self, actor, *, limit, offset):
        self.calls.append((actor, limit, offset))
        return ResearchDiscoveryTaskPage(
            items=[], total=0, limit=limit, offset=offset, has_more=False, next_offset=None
        )

    async def list_sessions(self, actor, *, limit, offset):
        self.calls.append((actor, limit, offset))
        return ResearchDiscoverySessionPage(
            items=[], total=0, limit=limit, offset=offset, has_more=False, next_offset=None
        )


def _api_app(actor, service):
    app = FastAPI()
    app.state.container = SimpleNamespace(
        school_research_discovery=service,
        settings=SimpleNamespace(
            cookie_name="smhai_dev_session",
            auth=SimpleNamespace(csrf_header_name="X-CSRF-Token"),
            allowed_origins=[],
        ),
    )
    app.add_exception_handler(BackendError, backend_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(router, prefix="/api/v1")

    @app.middleware("http")
    async def request_context(request, call_next):
        request.state.request_context = make_context(request)
        return await call_next(request)

    async def provide_actor(request: Request):
        request.state.session = SimpleNamespace(csrf_token="synthetic-csrf")
        return actor

    app.dependency_overrides[current_actor] = provide_actor
    return app


async def _api_request(app, path):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path, headers={"X-CSRF-Token": "synthetic-csrf"})


@pytest.mark.asyncio
async def test_lists_only_current_public_observed_scope_and_closed_lifecycle_dtos(discovery_scope):
    _seed_completed_session(discovery_scope.session)

    tasks = await discovery_scope.adapter.list_tasks(
        discovery_scope.actor, limit=30, offset=0, at=NOW
    )
    sessions = await discovery_scope.adapter.list_sessions(
        discovery_scope.actor, limit=30, offset=0, at=NOW
    )

    assert type(tasks) is ResearchDiscoveryTaskPage
    assert tasks.total == 1 and len(tasks.items) == 1
    task = tasks.items[0].model_dump(mode="json")
    assert task == {
        "task_ref": "task-demo-1",
        "class_ref": "class-demo-a",
        "profile_ref": "profile-demo",
        "source_population_scope": "US_8_17",
        "instrument_id": "PROMIS_ANXIETY",
        "instrument_version": "research-v1",
        "publication_status": "not_approved_for_publication_or_operational_use",
        "research_only": True,
        "opens_at": "2026-10-13T09:30:00Z",
        "due_at": "2026-10-15T09:30:00Z",
        "status": "PUBLISHED",
        "completion_count": 1,
        "session_ref": "own-session-1",
        "session_status": "COMPLETED",
        "items_answered": 4,
    }
    assert type(sessions) is ResearchDiscoverySessionPage
    assert sessions.total == 1 and len(sessions.items) == 1
    assert sessions.items[0].model_dump(mode="json") == {
        "session_ref": "own-session-1",
        "task_ref": "task-demo-1",
        "status": "COMPLETED",
        "items_answered": 4,
        "completed_at": "2026-10-14T09:29:00Z",
        "research_only": True,
    }
    all_output = repr(tasks) + repr(sessions) + str(task)
    for sensitive in (PROFILE_SHA, MANIFEST_SHA, CROSSWALK_SHA, CONFIG_SHA, "snapshot_ciphertext"):
        assert sensitive not in all_output
    assert not any(
        query.lstrip().startswith("select")
        and ("payload_ciphertext" in query or "config_ciphertext" in query)
        for query in discovery_scope.statements
    ), [
        query[:600]
        for query in discovery_scope.statements
        if query.lstrip().startswith("select")
        and ("payload_ciphertext" in query or "config_ciphertext" in query)
    ]


@pytest.mark.asyncio
async def test_revocation_wrong_origin_or_crosswalk_mismatch_hides_task_and_history(
    discovery_scope,
):
    _seed_completed_session(discovery_scope.session)
    binding = discovery_scope.session.get(db_models.SchoolResearchTaskBinding, 701)
    binding.response_origin = "MODEL_GENERATED"
    discovery_scope.session.commit()
    tasks = await discovery_scope.adapter.list_tasks(
        discovery_scope.actor, limit=30, offset=0, at=NOW
    )
    history = await discovery_scope.adapter.list_sessions(
        discovery_scope.actor, limit=30, offset=0, at=NOW
    )
    assert tasks.total == history.total == 0

    binding.response_origin = "PUBLIC_OBSERVED"
    profile = discovery_scope.session.get(db_models.SchoolResearchProfileVersion, 700)
    profile.published_parameter_crosswalk_sha256 = "f" * 64
    discovery_scope.session.commit()
    tasks = await discovery_scope.adapter.list_tasks(
        discovery_scope.actor, limit=30, offset=0, at=NOW
    )
    assert tasks.total == 0

    profile.published_parameter_crosswalk_sha256 = CROSSWALK_SHA
    roster = discovery_scope.session.get(db_models.SchoolClassStudent, 501)
    roster.status = "REVOKED"
    roster.revoked_at = NOW - timedelta(minutes=1)
    discovery_scope.session.commit()
    history = await discovery_scope.adapter.list_sessions(
        discovery_scope.actor, limit=30, offset=0, at=NOW
    )
    assert history.total == 0


@pytest.mark.asyncio
async def test_duplicate_active_self_grants_do_not_create_ambiguous_discovery_scope(
    discovery_scope,
):
    discovery_scope.session.add(
        db_models.SubjectAccessGrant(
            id=503,
            public_id="grant-a-duplicate",
            principal_account_id=201,
            subject_id=501,
            school_id=101,
            relationship_type="SELF",
            status="ACTIVE",
            valid_from=NOW - timedelta(days=30),
        )
    )
    discovery_scope.session.commit()
    page = await discovery_scope.adapter.list_tasks(
        discovery_scope.actor, limit=30, offset=0, at=NOW
    )
    assert page.items == [] and page.total == 0


@pytest.mark.asyncio
async def test_task_projection_does_not_attach_cross_subject_session_metadata(discovery_scope):
    _seed_completed_session(discovery_scope.session)
    session_row = discovery_scope.session.get(db_models.SchoolResearchSession, 1001)
    session_row.subject_id = 999
    discovery_scope.session.commit()

    task_page = await discovery_scope.adapter.list_tasks(
        discovery_scope.actor, limit=30, offset=0, at=NOW
    )
    assert task_page.total == 1 and len(task_page.items) == 1
    task = task_page.items[0]
    assert task.session_ref is None
    assert task.session_status is None
    assert task.items_answered == 0
    assert task.completion_count == 0


@pytest.mark.asyncio
async def test_pages_are_server_bounded_and_stably_ordered(discovery_scope):
    # A second task in the same active student scope exercises server-side
    # offset pagination while retaining unique enrollment and SELF predicates.
    session = discovery_scope.session
    session.add(
        db_models.MeasurementTask(
            id=402,
            public_id="task-public-a-2",
            school_id=101,
            class_id=401,
            task_ref="task-demo-2",
            created_by_membership_role_id=302,
            instrument_id="PROMIS_ANXIETY",
            instrument_version="research-v1",
            item_bank_version=None,
            config_version="config-v1",
            opens_at=NOW - timedelta(days=2),
            due_at=NOW + timedelta(days=1),
            published_at=NOW - timedelta(hours=1),
            status="PUBLISHED",
            cat_binding_mode="RESEARCH_PROFILE",
        )
    )
    session.flush()
    session.add_all(
        [
            db_models.TaskEnrollment(
                id=602,
                public_id="enrollment-public-a-2",
                school_id=101,
                task_id=402,
                class_id=401,
                class_student_id=501,
                subject_id=501,
                status="ACTIVE",
            ),
            db_models.SchoolResearchTaskBinding(
                id=702,
                public_id="binding-public-a-2",
                school_id=101,
                task_id=402,
                class_id=401,
                profile_version_id=700,
                profile_ref="profile-demo",
                profile_version_number=1,
                profile_sha256=PROFILE_SHA,
                response_origin="PUBLIC_OBSERVED",
                status="ACTIVE",
                purpose="RESEARCH_SIMULATION",
                research_only=True,
                config_version="config-v1",
                config_sha256=CONFIG_SHA,
                config_ciphertext=b"synthetic encrypted config fixture",
                cipher_format_version="test-v1",
                key_version="test-key",
                payload_schema_version="test-schema",
                created_by_membership_role_id=302,
            ),
        ]
    )
    session.commit()

    first = await discovery_scope.adapter.list_tasks(
        discovery_scope.actor, limit=1, offset=0, at=NOW
    )
    second = await discovery_scope.adapter.list_tasks(
        discovery_scope.actor, limit=1, offset=1, at=NOW
    )
    assert first.total == second.total == 2
    assert first.has_more is True and first.next_offset == 1
    assert second.has_more is False and second.next_offset is None
    assert first.items[0].task_ref == "task-demo-2"
    assert second.items[0].task_ref == "task-demo-1"
    assert first.items[0].session_ref is None
    assert first.items[0].session_status is None
    assert first.items[0].items_answered == 0
    assert first.items[0].completion_count == 0
    with pytest.raises(BackendError) as raised:
        await discovery_scope.adapter.list_tasks(discovery_scope.actor, limit=31, offset=0, at=NOW)
    assert raised.value.code is ErrorCode.VALIDATION_FAILED
    with pytest.raises(BackendError) as raised:
        await discovery_scope.adapter.list_tasks(
            discovery_scope.actor, limit=1, offset=10_001, at=NOW
        )
    assert raised.value.code is ErrorCode.VALIDATION_FAILED


@pytest.mark.asyncio
async def test_missing_policy_is_503_after_identity_check_and_nonstudent_is_denied(discovery_scope):
    discovery_scope.adapter._study_use_policy = None
    discovery_scope.statements.clear()
    with pytest.raises(BackendError) as unavailable:
        await discovery_scope.adapter.list_tasks(discovery_scope.actor, limit=30, offset=0, at=NOW)
    assert unavailable.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert not any("measurement_tasks" in query for query in discovery_scope.statements)

    from dataclasses import replace

    with pytest.raises(BackendError) as forbidden:
        await discovery_scope.adapter.list_tasks(
            replace(discovery_scope.actor, role=BackendRole.TEACHER),
            limit=30,
            offset=0,
            at=NOW,
        )
    assert forbidden.value.code is ErrorCode.FORBIDDEN


@pytest.mark.asyncio
async def test_router_limits_student_scope_and_does_not_call_service_for_other_roles():
    actor = live_scope_helpers._actor()
    service = _ApiService()
    app = _api_app(actor, service)
    response = await _api_request(app, "/api/v1/school/research-discovery/tasks?limit=1&offset=2")
    assert response.status_code == 200
    assert response.json()["data"] == {
        "items": [],
        "total": 0,
        "limit": 1,
        "offset": 2,
        "has_more": False,
        "next_offset": None,
    }
    assert service.calls == [(actor, 1, 2)]

    invalid = await _api_request(app, "/api/v1/school/research-discovery/sessions?limit=31")
    assert invalid.status_code == 422
    assert len(service.calls) == 1

    from dataclasses import replace

    service = _ApiService()
    app = _api_app(replace(actor, role=BackendRole.TEACHER), service)
    forbidden = await _api_request(app, "/api/v1/school/research-discovery/tasks")
    assert forbidden.status_code == 403
    assert service.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    "unknown=ignored",
    "limit=1&limit=2",
    "offset=0&offset=1",
    "profile_sha256=" + "a" * 64,
])
@pytest.mark.parametrize("resource", ["tasks", "sessions"])
async def test_discovery_query_is_closed_and_duplicate_free(query, resource):
    service = _ApiService()
    app = _api_app(live_scope_helpers._actor(), service)
    response = await _api_request(
        app, f"/api/v1/school/research-discovery/{resource}?{query}"
    )
    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.asyncio
async def test_authenticated_student_read_needs_no_mutation_csrf_header():
    service = _ApiService()
    app = _api_app(live_scope_helpers._actor(), service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/v1/school/research-discovery/tasks")
    assert response.status_code == 200
    assert len(service.calls) == 1
