from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request

from smhai_backend.adapters.school_research_profiles import (
    SchoolResearchProfileVersionPage,
    SchoolResearchProfileVersionView,
    SchoolResearchProfileView,
)
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
from smhai_backend.domains.school_research_profiles.router import router
from smhai_backend.domains.school_research_profiles.schemas import (
    ResearchProfileCandidateDto,
)
from smhai_backend.domains.school_research_profiles.service import (
    SchoolResearchProfilesService,
)

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
PROFILE_REF = "promis-pediatric-anxiety-research"
_BASE = "/api/v1/school/research-profiles"


def _actor(role: BackendRole = BackendRole.PSYCHOLOGICAL_SPECIALIST) -> Actor:
    return Actor(
        user_id="USER_synthetic_specialist",
        username="synthetic-specialist",
        role=role,
        subject_id=None,
        scope_profile="school_tenant",
        school_id=71,
        school_ref="SCHOOL_synthetic",
        school_contexts=(
            SchoolRoleContext(
                context_id="ROLE_synthetic_specialist",
                role=role,
                school_id=71,
                school_ref="SCHOOL_synthetic",
            ),
        ),
    )


def _candidate(
    *,
    version_number: int | None = 3,
    catalog_state: str = "IMPORTED_CANDIDATE",
) -> dict[str, Any]:
    return {
        "profile_ref": PROFILE_REF,
        "version_number": version_number,
        "source_population_scope": "PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
        "instrument_id": "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
        "research_only": True,
        "publication_status": "not_approved_for_publication_or_operational_use",
        "rights_status": "PENDING",
        "execution_status": "CANDIDATE_RESEARCH_ONLY",
        "created_at": NOW if version_number is not None else None,
        "catalog_state": catalog_state,
    }


class _FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def list_profiles(self, actor):
        self.calls.append(("list", actor))
        return [_candidate(version_number=None, catalog_state="REGISTRY_CANDIDATE")]

    async def list_profile_versions(self, actor, profile_ref, *, limit, offset):
        self.calls.append(("versions", actor, profile_ref, limit, offset))
        return SchoolResearchProfileVersionPage(
            items=(
                SchoolResearchProfileVersionView(
                    profile_ref=PROFILE_REF,
                    version_number=3,
                    source_population_scope="PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
                    instrument_id="PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
                    research_only=True,
                    publication_status="not_approved_for_publication_or_operational_use",
                    rights_status="VERIFIED",
                    execution_status="SIMULATION_ENABLED",
                    created_at=NOW,
                ),
            ),
            total=1,
            limit=limit,
            offset=offset,
            has_more=False,
            next_offset=None,
        )

    async def import_profile(self, actor, profile_ref, version_number, *, idempotency):
        self.calls.append(("import", actor, profile_ref, version_number, idempotency))
        return _candidate(version_number=version_number)

    async def enable_simulation(self, actor, profile_ref, version_number, *, idempotency):
        self.calls.append(
            ("enable_simulation", actor, profile_ref, version_number, idempotency)
        )
        return {
            "profile_ref": profile_ref,
            "version_number": version_number,
            "research_only": True,
            "human_curated": False,
            "publication_status": "not_approved_for_publication_or_operational_use",
            "rights_status": "VERIFIED",
            "execution_status": "SIMULATION_ENABLED",
            "simulation_only": True,
            "clinical_approval": False,
            "ethics_approval": False,
            "psychometric_approval": False,
            "study_ref": "study:synthetic-replay",
            "policy_expires_at": NOW,
            "catalog_state": "SIMULATION_ENABLED",
        }


class _DataclassService(_FakeService):
    async def list_profiles(self, actor):
        self.calls.append(("list", actor))
        return [
            SchoolResearchProfileView(
                profile_ref=PROFILE_REF,
                version_number=3,
                source_population_scope="PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
                instrument_id="PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
                research_only=True,
                publication_status="not_approved_for_publication_or_operational_use",
                rights_status="PENDING",
                execution_status="CANDIDATE_RESEARCH_ONLY",
                created_at=datetime(2026, 10, 14, 12, 0),
                catalog_state="EXISTING_CANDIDATE",
            )
        ]

    async def import_profile(self, actor, profile_ref, version_number, *, idempotency):
        self.calls.append(("import", actor, profile_ref, version_number, idempotency))
        return SchoolResearchProfileView(
            profile_ref=PROFILE_REF,
            version_number=version_number,
            source_population_scope="PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
            instrument_id="PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
            research_only=True,
            publication_status="not_approved_for_publication_or_operational_use",
            rights_status="PENDING",
            execution_status="CANDIDATE_RESEARCH_ONLY",
            created_at=datetime(2026, 10, 14, 17, 0, tzinfo=timezone(timedelta(hours=5))),
            catalog_state="IMPORTED_CANDIDATE",
        )


class _Auth:
    async def actor_for_session(self, *_args, **_kwargs):
        raise error(ErrorCode.AUTH_SESSION_EXPIRED, detail="authentication is required")


def _mounted_app(actor: Actor | None = None, service: Any = ...):
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
        container.school_research_profiles = service
    app.state.container = container
    app.add_exception_handler(BackendError, backend_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    from fastapi.exceptions import RequestValidationError

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


async def _request(app, method: str, path: str, *, payload=None, headers=None):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, json=payload, headers=headers)


def _csrf_headers(**extra):
    return {"X-CSRF-Token": "synthetic-csrf", **extra}


@pytest.mark.asyncio
async def test_unauthenticated_catalog_and_import_are_rejected() -> None:
    app = _mounted_app(service=_FakeService())

    get_response = await _request(app, "GET", f"{_BASE}/catalog")
    post_response = await _request(
        app,
        "POST",
        f"{_BASE}/import",
        payload={"profile_ref": PROFILE_REF, "version_number": 3},
        headers=_csrf_headers(**{"Idempotency-Key": "synthetic-idem"}),
    )

    assert get_response.status_code == 401
    assert get_response.json()["code"] == "auth_session_expired"
    assert post_response.status_code == 401
    assert post_response.json()["code"] == "auth_session_expired"


@pytest.mark.asyncio
async def test_get_is_specialist_only_and_checks_role_before_disabled_service() -> None:
    app = _mounted_app(_actor(BackendRole.TEACHER))
    response = await _request(app, "GET", f"{_BASE}/catalog")

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


@pytest.mark.asyncio
async def test_get_specialist_requires_configured_service_after_authentication() -> None:
    app = _mounted_app(_actor())
    response = await _request(app, "GET", f"{_BASE}/catalog")

    assert response.status_code == 503
    assert response.json()["code"] == "dependency_unavailable"


@pytest.mark.asyncio
async def test_post_csrf_and_role_checks_precede_disabled_service() -> None:
    app = _mounted_app(_actor())
    payload = {"profile_ref": PROFILE_REF, "version_number": 3}

    missing_csrf = await _request(
        app,
        "POST",
        f"{_BASE}/import",
        payload=payload,
        headers={"Idempotency-Key": "synthetic-idem"},
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "csrf_failed"

    missing_service = await _request(
        app,
        "POST",
        f"{_BASE}/import",
        payload=payload,
        headers=_csrf_headers(**{"Idempotency-Key": "synthetic-idem"}),
    )
    assert missing_service.status_code == 503
    assert missing_service.json()["code"] == "dependency_unavailable"

    teacher_app = _mounted_app(_actor(BackendRole.TEACHER))
    denied = await _request(
        teacher_app,
        "POST",
        f"{_BASE}/import",
        payload=payload,
        headers=_csrf_headers(**{"Idempotency-Key": "synthetic-idem"}),
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "forbidden"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"profile_ref": PROFILE_REF, "version_number": 3, "profile_sha256": "a" * 64},
        {"profile_ref": PROFILE_REF, "version_number": True},
    ],
)
async def test_import_body_is_closed_and_rejects_bool_version(payload) -> None:
    service = _FakeService()
    app = _mounted_app(_actor(), service)
    response = await _request(
        app,
        "POST",
        f"{_BASE}/import",
        payload=payload,
        headers=_csrf_headers(**{"Idempotency-Key": "synthetic-idem"}),
    )

    assert response.status_code == 422
    assert service.calls == []
    assert "a" * 64 not in response.text


@pytest.mark.asyncio
async def test_import_requires_idempotency_key_after_auth_and_csrf() -> None:
    service = _FakeService()
    app = _mounted_app(_actor(), service)
    response = await _request(
        app,
        "POST",
        f"{_BASE}/import",
        payload={"profile_ref": PROFILE_REF, "version_number": 3},
        headers={"X-CSRF-Token": "synthetic-csrf"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"
    assert service.calls == []


@pytest.mark.asyncio
async def test_get_and_post_return_only_candidate_metadata_and_canonical_envelope() -> None:
    service = _FakeService()
    app = _mounted_app(_actor(), service)

    catalog = await _request(
        app,
        "GET",
        f"{_BASE}/catalog",
        headers={"X-Trace-ID": "TRACE_profiles"},
    )
    imported = await _request(
        app,
        "POST",
        f"{_BASE}/import",
        payload={"profile_ref": PROFILE_REF, "version_number": 3},
        headers=_csrf_headers(
            **{"Idempotency-Key": "synthetic-idem", "X-Trace-ID": "TRACE_import"}
        ),
    )

    assert catalog.status_code == 200
    assert catalog.json()["trace_id"] == "TRACE_profiles"
    expected_catalog = [
        _candidate(version_number=None, catalog_state="REGISTRY_CANDIDATE")
    ]
    assert catalog.json()["data"] == expected_catalog
    assert imported.status_code == 200
    assert imported.json()["trace_id"] == "TRACE_import"
    imported_expected = _candidate(version_number=3)
    imported_expected["created_at"] = "2026-10-14T12:00:00Z"
    assert imported.json()["data"] == imported_expected
    for response in (catalog, imported):
        text = response.text.casefold()
        assert "profile_sha256" not in text
        assert "manifest_sha256" not in text
        assert "raw_profile_bytes" not in text
        assert "cat_config" not in text
    call = service.calls[-1]
    assert call[:4] == ("import", _actor(), PROFILE_REF, 3)
    assert call[4][0] == "synthetic-idem"
    assert call[4][1] == fingerprint({"profile_ref": PROFILE_REF, "version_number": 3})
    assert call[4][2] == fingerprint(
        {
            "actor": _actor().user_id,
            "school_id": _actor().school_id,
            "school_ref": _actor().school_ref,
            "role": _actor().role.value,
            "operation": "school_research_profiles:import",
        }
    )


@pytest.mark.asyncio
async def test_versions_get_returns_persisted_page_without_csrf_or_private_fields() -> None:
    service = _FakeService()
    app = _mounted_app(_actor(), service)

    response = await _request(
        app,
        "GET",
        f"{_BASE}/versions?profile_ref={PROFILE_REF}&limit=1&offset=0",
    )

    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["total"] == 1
    assert result["limit"] == 1
    assert result["items"][0]["version_number"] == 3
    assert result["items"][0]["execution_status"] == "SIMULATION_ENABLED"
    assert result["items"][0]["use_eligibility"] == "RECHECK_REQUIRED"
    for forbidden in (
        "profile_sha256",
        "manifest_sha256",
        "payload_ciphertext",
        "raw_profile_bytes",
        "cat_config",
        "case_index",
        "subject_id",
        "student_id",
    ):
        assert forbidden not in response.text
    assert service.calls == [("versions", _actor(), PROFILE_REF, 1, 0)]


@pytest.mark.asyncio
async def test_versions_query_is_closed_bounded_and_specialist_only() -> None:
    service = _FakeService()
    app = _mounted_app(_actor(), service)
    invalid = await _request(
        app, "GET", f"{_BASE}/versions?profile_ref={PROFILE_REF}&limit=31"
    )
    unknown = await _request(
        app, "GET", f"{_BASE}/versions?profile_ref={PROFILE_REF}&debug=1"
    )
    duplicate = await _request(
        app,
        "GET",
        f"{_BASE}/versions?profile_ref={PROFILE_REF}&offset=0&offset=1",
    )
    teacher = await _request(
        _mounted_app(_actor(BackendRole.TEACHER), service),
        "GET",
        f"{_BASE}/versions?profile_ref={PROFILE_REF}",
    )

    assert invalid.status_code == 422
    assert unknown.status_code == 422
    assert duplicate.status_code == 422
    assert teacher.status_code == 403
    assert service.calls == []


@pytest.mark.asyncio
async def test_asgi_projects_real_frozen_adapter_dataclasses_and_normalizes_db_times() -> None:
    service = _DataclassService()
    app = _mounted_app(_actor(), service)

    catalog = await _request(app, "GET", f"{_BASE}/catalog")
    imported = await _request(
        app,
        "POST",
        f"{_BASE}/import",
        payload={"profile_ref": PROFILE_REF, "version_number": 3},
        headers=_csrf_headers(**{"Idempotency-Key": "synthetic-dataclass-idem"}),
    )

    assert catalog.status_code == 200, catalog.text
    assert catalog.json()["data"][0]["created_at"] == "2026-10-14T12:00:00Z"
    assert imported.status_code == 200, imported.text
    assert imported.json()["data"]["created_at"] == "2026-10-14T12:00:00Z"
    assert imported.json()["data"]["catalog_state"] == "IMPORTED_CANDIDATE"
    assert "profile_sha256" not in imported.text
    assert "raw_profile_bytes" not in imported.text


@pytest.mark.asyncio
async def test_activation_auth_csrf_idempotency_and_disabled_service() -> None:
    service = _FakeService()
    payload = {"profile_ref": PROFILE_REF, "version_number": 3}
    disabled = _mounted_app(_actor())

    missing_csrf = await _request(
        disabled,
        "POST",
        f"{_BASE}/enable-simulation",
        payload=payload,
        headers={"Idempotency-Key": "activation-key"},
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "csrf_failed"

    missing_idempotency = await _request(
        disabled,
        "POST",
        f"{_BASE}/enable-simulation",
        payload=payload,
        headers={"X-CSRF-Token": "synthetic-csrf"},
    )
    assert missing_idempotency.status_code == 422
    assert missing_idempotency.json()["code"] == "validation_failed"

    # The API delegates only when explicitly configured. A server without the
    # profile service cannot accidentally fall back to catalog/import behavior.
    app_unconfigured = _mounted_app(_actor())
    unavailable = await _request(
        app_unconfigured,
        "POST",
        f"{_BASE}/enable-simulation",
        payload=payload,
        headers=_csrf_headers(**{"Idempotency-Key": "activation-key"}),
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "dependency_unavailable"

    teacher = await _request(
        _mounted_app(_actor(BackendRole.TEACHER), service),
        "POST",
        f"{_BASE}/enable-simulation",
        payload=payload,
        headers=_csrf_headers(**{"Idempotency-Key": "activation-key"}),
    )
    assert teacher.status_code == 403
    assert service.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"profile_ref": PROFILE_REF, "version_number": 3, "rights_status": "VERIFIED"},
        {"profile_ref": PROFILE_REF, "version_number": True},
        {"profile_ref": PROFILE_REF, "version_number": 3, "policy_sha256": "a" * 64},
    ],
)
async def test_activation_request_rejects_client_policy_and_approval_fields(payload) -> None:
    service = _FakeService()
    app = _mounted_app(_actor(), service)
    response = await _request(
        app,
        "POST",
        f"{_BASE}/enable-simulation",
        payload=payload,
        headers=_csrf_headers(**{"Idempotency-Key": "activation-key"}),
    )
    assert response.status_code == 422
    assert service.calls == []
    assert "VERIFIED" not in response.text
    assert "a" * 64 not in response.text


@pytest.mark.asyncio
async def test_activation_is_idempotency_scoped_and_returns_nonapproval_projection() -> None:
    service = _FakeService()
    app = _mounted_app(_actor(), service)
    response = await _request(
        app,
        "POST",
        f"{_BASE}/enable-simulation",
        payload={"profile_ref": PROFILE_REF, "version_number": 3},
        headers=_csrf_headers(
            **{"Idempotency-Key": "activation-key", "X-Trace-ID": "TRACE_enable"}
        ),
    )
    assert response.status_code == 200, response.text
    assert response.json()["trace_id"] == "TRACE_enable"
    assert response.json()["data"] == {
        "profile_ref": PROFILE_REF,
        "version_number": 3,
        "research_only": True,
        "human_curated": False,
        "publication_status": "not_approved_for_publication_or_operational_use",
        "rights_status": "VERIFIED",
        "execution_status": "SIMULATION_ENABLED",
        "simulation_only": True,
        "clinical_approval": False,
        "ethics_approval": False,
        "psychometric_approval": False,
        "study_ref": "study:synthetic-replay",
        "policy_expires_at": "2026-10-14T12:00:00Z",
        "catalog_state": "SIMULATION_ENABLED",
    }
    assert "profile_sha256" not in response.text
    assert "manifest_sha256" not in response.text
    assert "rights_basis" not in response.text
    call = service.calls[0]
    assert call[:4] == ("enable_simulation", _actor(), PROFILE_REF, 3)
    assert call[4][0] == "activation-key"
    assert call[4][1] == fingerprint({"profile_ref": PROFILE_REF, "version_number": 3})
    assert call[4][2] == fingerprint({
        "actor": _actor().user_id,
        "school_id": _actor().school_id,
        "school_ref": _actor().school_ref,
        "role": _actor().role.value,
        "operation": "school_research_profiles:enable_simulation",
    })


def test_response_dto_rejects_adapter_extra_fields() -> None:
    with pytest.raises(ValueError):
        ResearchProfileCandidateDto.model_validate(
            {**_candidate(), "profile_sha256": "a" * 64}
        )


class _FakePersistence:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def list_profiles(self, actor):
        self.calls.append(("list", actor))
        return []

    async def import_profile(self, actor, profile_ref, version_number, *, at, idempotency):
        self.calls.append(("import", actor, profile_ref, version_number, at, idempotency))
        return _candidate(version_number=version_number)

    async def enable_simulation(
        self, actor, profile_ref, version_number, *, at, idempotency
    ):
        self.calls.append(
            ("enable_simulation", actor, profile_ref, version_number, at, idempotency)
        )
        return {"profile_ref": profile_ref, "version_number": version_number}


@pytest.mark.asyncio
async def test_service_uses_clock_guard_and_delegates_only_list_and_import() -> None:
    persistence = _FakePersistence()
    service = SchoolResearchProfilesService(persistence=persistence, clock=lambda: NOW)
    specialist = _actor()

    assert await service.list_profiles(specialist) == []
    result = await service.import_profile(
        specialist, PROFILE_REF, 3, idempotency=("key", "a" * 64, "b" * 64)
    )
    assert result["version_number"] == 3
    assert persistence.calls[1][4] == NOW

    with pytest.raises(BackendError) as denied:
        await service.list_profiles(_actor(BackendRole.TEACHER))
    assert denied.value.code is ErrorCode.FORBIDDEN
    assert len(persistence.calls) == 2


@pytest.mark.asyncio
async def test_service_activation_delegates_clock_and_specialist_guard() -> None:
    persistence = _FakePersistence()
    service = SchoolResearchProfilesService(persistence=persistence, clock=lambda: NOW)
    request_hash = fingerprint({"profile_ref": PROFILE_REF, "version_number": 3})
    idempotency = ("activation", request_hash, "b" * 64)
    result = await service.enable_simulation(
        _actor(),
        PROFILE_REF,
        3,
        idempotency=idempotency,
    )
    assert result == {"profile_ref": PROFILE_REF, "version_number": 3}
    assert persistence.calls == [
        (
            "enable_simulation",
            _actor(),
            PROFILE_REF,
            3,
            NOW,
            idempotency,
        )
    ]
    with pytest.raises(BackendError) as denied:
        await service.enable_simulation(
            _actor(BackendRole.TEACHER),
            PROFILE_REF,
            3,
            idempotency=("activation", "a" * 64, "b" * 64),
        )
    assert denied.value.code is ErrorCode.FORBIDDEN
    assert len(persistence.calls) == 1
