from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError

from smhai_backend.adapters.school_research_tasks import ResearchTaskBindingOptionView
from smhai_backend.core.errors import (
    BackendError,
    ErrorCode,
    backend_error_handler,
    error,
    unhandled_error_handler,
    validation_error_handler,
)
from smhai_backend.core.idempotency import fingerprint
from smhai_backend.core.request_context import make_context
from smhai_backend.domains.auth.dependencies import current_actor
from smhai_backend.domains.models import Actor, BackendRole, SchoolRoleContext
from smhai_backend.domains.school_research_tasks.router import router
from smhai_backend.domains.school_research_tasks.schemas import (
    ResearchTaskBindingOptionDto,
    ResearchTaskPublicationDto,
)
from smhai_backend.domains.school_research_tasks.service import SchoolResearchTasksService

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
OPEN = datetime(2026, 10, 16, 0, 0, tzinfo=UTC)
DUE = datetime(2026, 10, 22, 0, 0, tzinfo=UTC)
PROFILE_REF = "promis-pediatric-anxiety-8-item-subset-20261014-r1"
BINDING_REF = "promis-research-binding-r1"
BASE = "/api/v1/school/research-tasks"


def _actor(role: BackendRole = BackendRole.ADMIN) -> Actor:
    return Actor(
        user_id="USER_synthetic_admin",
        username="synthetic-admin",
        role=role,
        subject_id=None,
        scope_profile="school_tenant",
        school_id=71,
        school_ref="SCHOOL_synthetic",
        school_contexts=(
            SchoolRoleContext(
                context_id="ROLE_synthetic_admin",
                role=role,
                school_id=71,
                school_ref="SCHOOL_synthetic",
            ),
        ),
    )


def _publication() -> dict[str, Any]:
    return {
        "task_ref": "TASK_synthetic_replay_01",
        "class_ref": "CLASS_demo_01",
        "binding_ref": BINDING_REF,
        "profile_ref": PROFILE_REF,
        "profile_version_number": 2,
        "source_population_scope": "PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
        "instrument_id": "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
        "instrument_version": "research-v2",
        "status": "PUBLISHED",
        "opens_at": OPEN,
        "due_at": DUE,
        "published_at": NOW,
        "published_enrollment_count": 8,
        "response_origin": "PUBLIC_OBSERVED",
        "research_only": True,
        "publication_status": "not_approved_for_publication_or_operational_use",
    }


class _FakeService:
    def __init__(self):
        self.calls = []

    async def list_catalog(self, actor):
        self.calls.append(("list_catalog", actor))
        return [
            ResearchTaskBindingOptionView(
                binding_ref=BINDING_REF,
                profile_ref=PROFILE_REF,
                profile_version_number=2,
                source_population_scope="PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
                instrument_id="PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
                instrument_version="research-v2",
                research_only=True,
                publication_status="not_approved_for_publication_or_operational_use",
            )
        ]

    async def publish_task(self, actor, **kwargs):
        self.calls.append((actor, kwargs))
        return _publication()


class _Auth:
    async def actor_for_session(self, *_args, **_kwargs):
        raise error(ErrorCode.AUTH_SESSION_EXPIRED, detail="authentication is required")


def _app(actor: Actor | None = None, service: Any = ...):
    app = FastAPI()
    container = SimpleNamespace(
        settings=SimpleNamespace(
            cookie_name="smhai_dev_session",
            auth=SimpleNamespace(csrf_header_name="X-CSRF-Token"),
            allowed_origins=[],
        ),
        auth=_Auth(),
    )
    if service is not ...:
        container.school_research_tasks = service
    app.state.container = container
    app.add_exception_handler(BackendError, backend_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(router, prefix="/api/v1")

    @app.middleware("http")
    async def request_context(request, call_next):
        request.state.request_context = make_context(request)
        return await call_next(request)

    if actor is not None:

        async def provide_actor(request: Request):
            request.state.session = SimpleNamespace(csrf_token="synthetic-csrf")
            return actor

        app.dependency_overrides[current_actor] = provide_actor
    return app


async def _request(app, method, path, *, payload=None, headers=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, json=payload, headers=headers)


def _headers(**extra):
    return {"X-CSRF-Token": "synthetic-csrf", **extra}


def _payload():
    return {
        "class_ref": "CLASS_demo_01",
        "task_ref": "TASK_synthetic_replay_01",
        "binding_ref": BINDING_REF,
        "profile_version_number": 2,
        "opens_at": "2026-10-16T00:00:00Z",
        "due_at": "2026-10-22T00:00:00Z",
    }


@pytest.mark.asyncio
async def test_unauthenticated_and_non_admin_requests_are_rejected():
    unauth = await _request(
        _app(service=_FakeService()), "POST", f"{BASE}/publish", payload=_payload()
    )
    assert unauth.status_code == 401
    assert unauth.json()["code"] == "auth_session_expired"

    denied = await _request(
        _app(_actor(BackendRole.TEACHER), _FakeService()),
        "POST",
        f"{BASE}/publish",
        payload=_payload(),
        headers=_headers(**{"Idempotency-Key": "synthetic-idem"}),
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "forbidden"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    [BackendRole.TEACHER, BackendRole.STUDENT, BackendRole.PSYCHOLOGICAL_SPECIALIST],
)
async def test_catalog_is_admin_only_and_returns_closed_nonsecret_binding_options(role):
    service = _FakeService()
    response = await _request(_app(_actor(), service), "GET", f"{BASE}/catalog")
    assert response.status_code == 200
    assert response.json()["data"] == [
        {
            "binding_ref": BINDING_REF,
            "profile_ref": PROFILE_REF,
            "profile_version_number": 2,
            "source_population_scope": "PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
            "instrument_id": "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
            "instrument_version": "research-v2",
            "research_only": True,
            "publication_status": "not_approved_for_publication_or_operational_use",
        }
    ]
    assert service.calls == [("list_catalog", _actor())]
    for secretish in (
        "profile_sha256",
        "manifest_sha256",
        "config_sha256",
        "config_version",
        "cat_config",
        "parameter_values",
    ):
        assert secretish not in response.text

    denied_service = _FakeService()
    denied = await _request(
        _app(_actor(role), denied_service),
        "GET",
        f"{BASE}/catalog",
    )
    assert denied.status_code == 403
    assert denied_service.calls == []


def test_binding_option_dto_rejects_hashes_and_config_payload():
    valid = {
        "binding_ref": BINDING_REF,
        "profile_ref": PROFILE_REF,
        "profile_version_number": 2,
        "source_population_scope": "PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
        "instrument_id": "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
        "instrument_version": "research-v2",
        "research_only": True,
        "publication_status": "not_approved_for_publication_or_operational_use",
    }
    assert ResearchTaskBindingOptionDto.model_validate(valid)
    for field in ("profile_sha256", "config_sha256", "cat_config"):
        with pytest.raises(ValueError):
            ResearchTaskBindingOptionDto.model_validate({**valid, field: "forbidden"})


@pytest.mark.asyncio
async def test_csrf_and_disabled_service_checks_happen_after_admin_auth():
    app = _app(_actor())
    missing_csrf = await _request(
        app,
        "POST",
        f"{BASE}/publish",
        payload=_payload(),
        headers={"Idempotency-Key": "synthetic-idem"},
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "csrf_failed"

    unavailable = await _request(
        app,
        "POST",
        f"{BASE}/publish",
        payload=_payload(),
        headers=_headers(**{"Idempotency-Key": "synthetic-idem"}),
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "dependency_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {**_payload(), "rights_status": "VERIFIED"},
        {**_payload(), "profile_version_number": True},
        {**_payload(), "profile_version_number": "2"},
        {**_payload(), "opens_at": "2026-10-16T00:00:00"},
        {**_payload(), "due_at": "2026-10-15T00:00:00Z"},
    ],
)
async def test_request_is_closed_and_requires_strict_version_and_valid_utc_window(payload):
    service = _FakeService()
    response = await _request(
        _app(_actor(), service),
        "POST",
        f"{BASE}/publish",
        payload=payload,
        headers=_headers(**{"Idempotency-Key": "synthetic-idem"}),
    )
    assert response.status_code == 422
    assert service.calls == []
    assert "VERIFIED" not in response.text


@pytest.mark.asyncio
async def test_idempotency_key_is_required_and_response_keeps_only_safe_task_metadata():
    service = _FakeService()
    app = _app(_actor(), service)

    missing_key = await _request(
        app,
        "POST",
        f"{BASE}/publish",
        payload=_payload(),
        headers=_headers(),
    )
    assert missing_key.status_code == 422
    assert service.calls == []

    response = await _request(
        app,
        "POST",
        f"{BASE}/publish",
        payload=_payload(),
        headers=_headers(
            **{"Idempotency-Key": "synthetic-idem", "X-Trace-ID": "TRACE_task_publish"}
        ),
    )
    assert response.status_code == 201, response.text
    assert response.json()["trace_id"] == "TRACE_task_publish"
    data = response.json()["data"]
    assert data["response_origin"] == "PUBLIC_OBSERVED"
    assert data["research_only"] is True
    assert data["publication_status"] == "not_approved_for_publication_or_operational_use"
    assert data["opens_at"] == "2026-10-16T00:00:00Z"
    assert "profile_sha256" not in response.text
    assert "manifest_sha256" not in response.text
    assert "config_sha256" not in response.text
    assert "cat_config" not in response.text
    actor, kwargs = service.calls[0]
    assert actor == _actor()
    assert kwargs["binding_ref"] == BINDING_REF
    assert kwargs["idempotency"][0] == "synthetic-idem"
    assert kwargs["idempotency"][1] == fingerprint(_payload())
    assert kwargs["idempotency"][2] == fingerprint(
        {
            "actor": actor.user_id,
            "school_id": actor.school_id,
            "school_ref": actor.school_ref,
            "role": actor.role.value,
            "operation": "school_research_tasks:publish",
        }
    )


def test_publication_dto_rejects_internal_hashes_or_config_fields():
    with pytest.raises(ValueError):
        ResearchTaskPublicationDto.model_validate({**_publication(), "config_sha256": "a" * 64})


@pytest.mark.asyncio
async def test_cohort_is_only_a_server_resolved_selector_in_publish_fingerprint():
    service = _FakeService()
    payload = {**_payload(), "cohort_ref": "COHORT_R_synthetic"}
    response = await _request(
        _app(_actor(), service), "POST", f"{BASE}/publish", payload=payload,
        headers=_headers(**{"Idempotency-Key": "synthetic-cohort-task"}),
    )
    assert response.status_code == 201
    _, kwargs = service.calls[0]
    assert kwargs["cohort_ref"] == payload["cohort_ref"]
    assert kwargs["idempotency"][1] == fingerprint(payload)
    assert "case_index" not in response.text


@pytest.mark.asyncio
async def test_explicit_null_cohort_preserves_legacy_publish_fingerprint():
    service = _FakeService()
    response = await _request(
        _app(_actor(), service), "POST", f"{BASE}/publish",
        payload={**_payload(), "cohort_ref": None},
        headers=_headers(**{"Idempotency-Key": "synthetic-old-task"}),
    )
    assert response.status_code == 201
    _, kwargs = service.calls[0]
    assert "cohort_ref" not in kwargs
    assert kwargs["idempotency"][1] == fingerprint(_payload())


class _FakePersistence:
    def __init__(self):
        self.calls = []

    async def list_catalog_options(self, actor, *, at):
        self.calls.append(("list_catalog", actor, at))
        return ()

    async def publish_task(self, actor, **kwargs):
        self.calls.append((actor, kwargs))
        return _publication()


@pytest.mark.asyncio
async def test_service_requires_school_admin_and_passes_injected_clock():
    persistence = _FakePersistence()
    service = SchoolResearchTasksService(persistence=persistence, clock=lambda: NOW)
    admin = _actor()
    assert await service.list_catalog(admin) == ()
    assert persistence.calls[0] == ("list_catalog", admin, NOW)
    result = await service.publish_task(
        admin,
        class_ref="CLASS_demo_01",
        task_ref="TASK_synthetic_replay_01",
        binding_ref=BINDING_REF,
        profile_version_number=2,
        opens_at=OPEN,
        due_at=DUE,
        idempotency=("key", "a" * 64, "b" * 64),
    )
    assert result["response_origin"] == "PUBLIC_OBSERVED"
    assert persistence.calls[1][1]["at"] == NOW

    with pytest.raises(BackendError) as denied:
        await service.list_catalog(_actor(BackendRole.TEACHER))
    assert denied.value.code is ErrorCode.FORBIDDEN

    with pytest.raises(BackendError) as denied:
        await service.publish_task(
            _actor(BackendRole.TEACHER),
            class_ref="CLASS_demo_01",
            task_ref="TASK_synthetic_replay_01",
            binding_ref=BINDING_REF,
            profile_version_number=2,
            opens_at=OPEN,
            due_at=DUE,
            idempotency=("key", "a" * 64, "b" * 64),
        )
    assert denied.value.code is ErrorCode.FORBIDDEN
    assert len(persistence.calls) == 2
