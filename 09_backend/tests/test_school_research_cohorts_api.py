from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError

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
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.school_research_cohorts.router import router

PATH = "/api/v1/school/research-cohorts/seal"


def _actor(role=BackendRole.ADMIN, scope="school_tenant"):
    return Actor(
        user_id="USER_demo_admin", username="demo-admin", role=role,
        subject_id=None, scope_profile=scope, school_id=1, school_ref="SCHOOL_demo",
    )


def _payload():
    return {"binding_ref": "promis-research-01", "profile_version_number": 3,
            "batch_refs": [f"BATCH_demo_{n}" for n in range(8)]}


class _Service:
    def __init__(self):
        self.calls = []

    async def seal_cohort(self, actor, **kwargs):
        self.calls.append((actor, kwargs))
        return {
            "cohort_ref": "COHORT_demo_01", "study_ref": "STUDY_demo_01",
            "profile_ref": "promis-research-01", "profile_version_number": 3,
            "source_population_scope": "PROMIS_US_GENPOP_CHILD_SELF_REPORT_8_17",
            "instrument_id": "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET", "status": "SEALED",
            "subject_count": 800, "class_count": 8, "assigned_distinct_cases": 800,
            "sealed_at": datetime(2026, 10, 14, tzinfo=UTC),
            "response_origin": "PUBLIC_OBSERVED", "research_only": True,
            "publication_status": "not_approved_for_publication_or_operational_use",
        }


class _Auth:
    async def actor_for_session(self, *args, **kwargs):
        raise error(ErrorCode.AUTH_SESSION_EXPIRED, detail="authentication is required")


def _app(actor=None, service=None):
    app = FastAPI()
    app.state.container = SimpleNamespace(
        settings=SimpleNamespace(cookie_name="smhai_dev_session", allowed_origins=[],
                                 auth=SimpleNamespace(csrf_header_name="X-CSRF-Token")),
        auth=_Auth(), school_research_cohorts=service,
    )
    app.add_exception_handler(BackendError, backend_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(router, prefix="/api/v1")

    @app.middleware("http")
    async def context(request, call_next):
        request.state.request_context = make_context(request)
        return await call_next(request)

    if actor is not None:
        async def provide_actor(request: Request):
            request.state.session = SimpleNamespace(csrf_token="demo-csrf")
            return actor
        app.dependency_overrides[current_actor] = provide_actor
    return app


async def _post(app, payload=None, headers=None):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://testserver") as client:
        return await client.post(PATH, json=payload or _payload(), headers=headers)


HEADERS = {"X-CSRF-Token": "demo-csrf", "Idempotency-Key": "demo-cohort-seal-01"}


@pytest.mark.asyncio
@pytest.mark.parametrize("actor,status", [
    (None, 401), (_actor(BackendRole.STUDENT), 403),
    (_actor(BackendRole.TEACHER), 403), (_actor(BackendRole.PSYCHOLOGICAL_SPECIALIST), 403),
    (_actor(scope="legacy"), 403),
])
async def test_only_school_admin_can_seal(actor, status):
    service = _Service()
    result = await _post(_app(actor, service), headers=HEADERS)
    assert result.status_code == status
    assert service.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("headers,status", [
    ({"Idempotency-Key": "demo-cohort-seal-01"}, 403),
    ({"X-CSRF-Token": "demo-csrf"}, 422),
])
async def test_csrf_and_idempotency_are_required(headers, status):
    service = _Service()
    result = await _post(_app(_actor(), service), headers=headers)
    assert result.status_code == status
    assert service.calls == []


@pytest.mark.asyncio
async def test_unconfigured_service_fails_closed():
    result = await _post(_app(_actor()), headers=HEADERS)
    assert result.status_code == 503


@pytest.mark.asyncio
async def test_seal_has_normalized_fingerprint_and_content_free_receipt():
    service = _Service()
    payload = _payload()
    payload["batch_refs"].reverse()
    result = await _post(_app(_actor(), service), payload, HEADERS)
    assert result.status_code == 201
    actor, call = service.calls[0]
    assert actor == _actor()
    assert call["batch_refs"] == tuple(sorted(payload["batch_refs"]))
    assert call["idempotency"][1] == fingerprint(_payload())
    assert result.json()["data"]["assigned_distinct_cases"] == 800
    assert not {"case_index", "subject_id", "corpus_sha256", "answers"} & set(result.json()["data"])


@pytest.mark.asyncio
async def test_client_provenance_rejected_before_service():
    service = _Service()
    result = await _post(_app(_actor(), service), {**_payload(), "case_index": 0}, HEADERS)
    assert result.status_code == 422
    assert service.calls == []
