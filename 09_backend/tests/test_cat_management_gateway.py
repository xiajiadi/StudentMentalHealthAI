from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from smhai_backend.adapters.school_cat_management import SchoolCatManagementPersistenceAdapter
from smhai_backend.app_factory import create_app
from smhai_backend.core.config import BackendSettings, ModuleClientSettings
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.core.request_context import RequestContext
from smhai_backend.domains.cat_management.router import router as cat_management_router
from smhai_backend.domains.cat_management.schemas import (
    CatalogResponseDto,
    SimulationRequestDto,
    SimulationResponseDto,
)
from smhai_backend.domains.cat_management.service import SchoolCatManagementService
from smhai_backend.domains.models import Actor, BackendRole, SchoolRoleContext
from smhai_backend.integrations.cat_management import (
    CAT_MANAGEMENT_READ_TIMEOUT_SECONDS,
    HttpCatManagementClient,
)


def specialist() -> Actor:
    context = SchoolRoleContext(
        context_id="ROLECTX_specialist",
        role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
        school_id=7,
        school_ref="SCHOOL_demo",
    )
    return Actor(
        user_id="USER_specialist",
        username="specialist",
        role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
        subject_id=None,
        scope_profile="school_tenant",
        school_id=7,
        school_ref="SCHOOL_demo",
        school_contexts=(context,),
    )


def catalog_payload() -> dict:
    return {
        "schema_version": "synthetic_cat_management.v1",
        "engineering_only": True,
        "psychological_interpretation_allowed": False,
        "item_bank": {
            "item_bank_id": "ITEMBANK_demo_cat",
            "version": "demo.v1",
            "instrument_id": "CURRENT_SYNTHETIC_GRM",
            "item_count": 9,
            "dimension_count": 1,
            "status": "published",
            "validation": "STRUCTURE_VALID",
        },
        "config": {
            "config_version": "demo.cat.v1",
            "model": "GRM",
            "estimator": "EAP",
            "selection_method": "MFI",
            "min_items": 3,
            "max_items": 8,
            "se_threshold": 0.55,
            "seed": 20260904,
        },
        "simulation": {"available": True, "sample_sizes": [100, 1000], "fixed_seed": 20260904},
    }


def simulation_payload(n_examinees: int = 100) -> dict:
    return {
        "schema_version": "synthetic_cat_management.v1",
        "engineering_only": True,
        "psychological_interpretation_allowed": False,
        "item_bank_id": "ITEMBANK_demo_cat",
        "item_bank_version": "demo.v1",
        "config_version": "demo.cat.v1",
        "n_examinees": n_examinees,
        "seed": 20260904,
        "metrics": {
            "bias": 0.0,
            "rmse": 0.4,
            "mae": 0.3,
            "mean_test_length": 5.2,
            "median_test_length": 5.0,
            "mean_se": 0.51,
        },
        "stopping_reason_distribution": {"SE_THRESHOLD_REACHED": n_examinees},
    }


def context() -> RequestContext:
    return RequestContext("REQ_test", "TRACE_test")


def test_strict_projections_fail_closed_on_unknown_assets_and_private_fields():
    catalog = catalog_payload()
    CatalogResponseDto.model_validate(catalog, strict=True)

    for field, value in (
        ("engineering_only", 1),
        ("psychological_interpretation_allowed", 0),
    ):
        invalid_catalog_flag = catalog_payload()
        invalid_catalog_flag[field] = value
        with pytest.raises(ValidationError):
            CatalogResponseDto.model_validate(invalid_catalog_flag, strict=True)
        invalid_simulation_flag = simulation_payload()
        invalid_simulation_flag[field] = value
        with pytest.raises(ValidationError):
            SimulationResponseDto.model_validate(invalid_simulation_flag, strict=True)

    unknown = catalog_payload()
    unknown["item_bank"]["item_bank_id"] = "ITEMBANK_other"
    with pytest.raises(ValidationError):
        CatalogResponseDto.model_validate(unknown, strict=True)

    private = catalog_payload()
    private["item_bank"]["items"] = [{"stem": "must not cross boundary"}]
    with pytest.raises(ValidationError):
        CatalogResponseDto.model_validate(private, strict=True)

    invalid_metrics = simulation_payload()
    invalid_metrics["metrics"]["rmse"] = float("nan")
    with pytest.raises(ValidationError):
        SimulationResponseDto.model_validate(invalid_metrics, strict=True)

    bad_counts = simulation_payload()
    bad_counts["stopping_reason_distribution"] = {"SE_THRESHOLD_REACHED": 99}
    with pytest.raises(ValidationError):
        SimulationResponseDto.model_validate(bad_counts, strict=True)


def test_simulation_request_forbids_seed_or_batch_override():
    assert SimulationRequestDto.model_validate({}, strict=True).n_examinees == 100
    with pytest.raises(ValidationError):
        SimulationRequestDto.model_validate({"n_examinees": 101}, strict=True)
    with pytest.raises(ValidationError):
        SimulationRequestDto.model_validate({"n_examinees": 100, "seed": 1}, strict=True)
    for invalid in (100.0, 1000.0, True, "100"):
        with pytest.raises(ValidationError):
            SimulationRequestDto.model_validate({"n_examinees": invalid}, strict=True)

    for invalid in (100.0, 1000.0, True, "100"):
        response = simulation_payload()
        response["n_examinees"] = invalid
        with pytest.raises(ValidationError):
            SimulationResponseDto.model_validate(response, strict=True)


class FakeAudit:
    def __init__(self, events):
        self.events = events

    async def append(self, **record):
        self.events.append(("audit", record))


class FakeUow:
    def __init__(self, events):
        self.audit = FakeAudit(events)
        self.events = events

    async def __aenter__(self):
        self.events.append(("uow_open",))
        return self

    async def __aexit__(self, exc_type, _exc, _tb):
        self.events.append(("uow_close", exc_type))


class FakePersistence:
    identity_profile = "school_tenant"
    _db_enums = SimpleNamespace(AuditResult=SimpleNamespace(SUCCESS="SUCCESS"))

    def __init__(self, events, *, deny_call: int | None = None):
        self.events = events
        self.check_count = 0
        self.deny_call = deny_call

    def _uow(self):
        return FakeUow(self.events)

    def _utc_now(self):
        return datetime.now(UTC)

    async def _school_actor_role(self, _uow, _actor, role, _now):
        self.check_count += 1
        self.events.append(("role", role, self.check_count))
        if self.check_count == self.deny_call:
            raise BackendError(ErrorCode.FORBIDDEN, detail="access denied")
        return 42, 84


class FakeClient:
    def __init__(self, events, *, fail=False):
        self.events = events
        self.fail = fail

    async def catalog(self, *, context):
        self.events.append(("catalog", context.trace_id))
        if self.fail:
            raise BackendError(ErrorCode.DEPENDENCY_UNAVAILABLE, detail="unavailable")
        return catalog_payload()

    async def simulate(self, n_examinees, *, context):
        self.events.append(("simulate", n_examinees, context.trace_id))
        return simulation_payload(n_examinees)


@pytest.mark.asyncio
async def test_adapter_authorizes_before_and_after_call_then_audits_only_metadata(monkeypatch):
    events = []
    persistence = FakePersistence(events)
    client = FakeClient(events)
    adapter = SchoolCatManagementPersistenceAdapter(persistence, client)
    monkeypatch.setattr("smhai_backend.adapters.school_cat_management.get_request_context", context)

    result = await adapter.school_cat_management_catalog(specialist())

    assert result["item_bank"]["item_bank_id"] == "ITEMBANK_demo_cat"
    assert [event[0] for event in events if event[0] in {"role", "catalog", "audit"}] == [
        "role",
        "catalog",
        "role",
        "audit",
    ]
    audit = next(event[1] for event in events if event[0] == "audit")
    assert audit == {
        "action": "school_cat_management.catalog_read",
        "resource_type": "school_cat_management",
        "resource_public_id": None,
        "result": "SUCCESS",
        "trace_id": "TRACE_test",
        "actor_account_id": 42,
        "safe_metadata": {"source": "school_cat_management", "state": "SUCCESS"},
    }
    assert "stem" not in repr(audit) and "metrics" not in repr(audit)
    audit_index = next(index for index, event in enumerate(events) if event[0] == "audit")
    second_uow_open = [index for index, event in enumerate(events) if event[0] == "uow_open"][1]
    second_uow_close = [index for index, event in enumerate(events) if event[0] == "uow_close"][1]
    assert second_uow_open < audit_index < second_uow_close


@pytest.mark.asyncio
async def test_adapter_has_no_success_audit_on_upstream_failure_or_revoked_role(monkeypatch):
    monkeypatch.setattr("smhai_backend.adapters.school_cat_management.get_request_context", context)
    events = []
    adapter = SchoolCatManagementPersistenceAdapter(
        FakePersistence(events), FakeClient(events, fail=True)
    )
    with pytest.raises(BackendError) as unavailable:
        await adapter.school_cat_management_catalog(specialist())
    assert unavailable.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
    assert not any(event[0] == "audit" for event in events)

    events.clear()
    adapter = SchoolCatManagementPersistenceAdapter(
        FakePersistence(events, deny_call=2), FakeClient(events)
    )
    with pytest.raises(BackendError) as revoked:
        await adapter.school_cat_management_catalog(specialist())
    assert revoked.value.code is ErrorCode.FORBIDDEN
    assert not any(event[0] == "audit" for event in events)

    events.clear()
    adapter = SchoolCatManagementPersistenceAdapter(
        FakePersistence(events, deny_call=2), FakeClient(events)
    )
    with pytest.raises(BackendError) as revoked_during_simulation:
        await adapter.school_cat_management_simulate(specialist(), 1000)
    assert revoked_during_simulation.value.code is ErrorCode.FORBIDDEN
    assert ("simulate", 1000, "TRACE_test") in events
    assert not any(event[0] == "audit" for event in events)


@pytest.mark.asyncio
async def test_service_denies_non_specialist_before_persistence():
    class NeverCalled:
        async def school_cat_management_catalog(self, _actor):
            raise AssertionError("persistence must not be reached")

    service = SchoolCatManagementService(persistence=NeverCalled())
    teacher = Actor(
        user_id="USER_teacher",
        username="teacher",
        role=BackendRole.TEACHER,
        subject_id=None,
        scope_profile="school_tenant",
        school_id=7,
        school_ref="SCHOOL_demo",
    )
    with pytest.raises(BackendError) as denied:
        await service.catalog(teacher)
    assert denied.value.code is ErrorCode.FORBIDDEN


@pytest.mark.asyncio
async def test_http_client_projects_real_mock_transport_and_maps_busy_without_leaking_body():
    seen = []

    async def handler(request: httpx.Request):
        seen.append(request)
        if request.url.path.endswith("catalog"):
            return httpx.Response(200, json=catalog_payload())
        return httpx.Response(409, json={"detail": "synthetic_cat_simulation_busy"})

    client = HttpCatManagementClient(
        ModuleClientSettings(mode="http", base_url="http://127.0.0.1:8180"),
        transport=httpx.MockTransport(handler),
    )
    try:
        assert (await client.catalog(context=context()))["config"]["seed"] == 20260904
        assert client.client.timeout.read == CAT_MANAGEMENT_READ_TIMEOUT_SECONDS == 600.0
        assert seen[0].headers["X-Trace-ID"] == "TRACE_test"
        with pytest.raises(BackendError) as busy:
            await client.simulate(100, context=context())
        assert busy.value.code is ErrorCode.WORKFLOW_CONFLICT
        assert busy.value.detail == "synthetic_cat_simulation_busy"
        assert seen[1].method == "POST"
        assert seen[1].read() == b'{"n_examinees":100}'
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_http_client_rejects_malformed_projection_without_echoing_upstream():
    async def handler(_request: httpx.Request):
        value = catalog_payload()
        value["student_response"] = "private synthetic payload"
        return httpx.Response(200, json=value)

    client = HttpCatManagementClient(
        ModuleClientSettings(mode="http", base_url="http://127.0.0.1:8180"),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(BackendError) as invalid:
            await client.catalog(context=context())
        assert invalid.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE
        assert "private synthetic payload" not in invalid.value.detail
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint,field,value",
    [
        ("catalog", "engineering_only", 1),
        ("catalog", "psychological_interpretation_allowed", 0),
        ("simulation", "engineering_only", 1),
        ("simulation", "psychological_interpretation_allowed", 0),
    ],
)
async def test_http_client_rejects_numeric_engineering_flags(endpoint, field, value):
    async def handler(request: httpx.Request):
        payload = catalog_payload() if endpoint == "catalog" else simulation_payload()
        payload[field] = value
        return httpx.Response(200, json=payload)

    client = HttpCatManagementClient(
        ModuleClientSettings(mode="http", base_url="http://127.0.0.1:8180"),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(BackendError) as invalid:
            if endpoint == "catalog":
                await client.catalog(context=context())
            else:
                await client.simulate(100, context=context())
        assert invalid.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_http_client_maps_timeout_without_automatic_retry():
    calls = []

    async def handler(_request: httpx.Request):
        calls.append("called")
        raise httpx.ReadTimeout("synthetic timeout")

    client = HttpCatManagementClient(
        ModuleClientSettings(mode="http", base_url="http://127.0.0.1:8180"),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(BackendError) as timed_out:
            await client.catalog(context=context())
        assert timed_out.value.code is ErrorCode.DEPENDENCY_TIMEOUT
        assert calls == ["called"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_http_client_maps_service_unavailable_to_explicit_dependency_error():
    async def handler(_request: httpx.Request):
        return httpx.Response(503, json={"detail": "private upstream diagnostics"})

    client = HttpCatManagementClient(
        ModuleClientSettings(mode="http", base_url="http://127.0.0.1:8180"),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(BackendError) as unavailable:
            await client.catalog(context=context())
        assert unavailable.value.code is ErrorCode.DEPENDENCY_UNAVAILABLE
        assert unavailable.value.retryable is True
        assert "private upstream diagnostics" not in unavailable.value.detail
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_simulation_route_rejects_non_integer_batch_inputs_with_real_csrf(client):
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a"},
    )
    assert login.status_code == 200
    csrf_token = login.json()["data"]["csrf_token"]
    headers = {"X-CSRF-Token": csrf_token}

    invalid_bodies = [
        {"n_examinees": 100.0},
        {"n_examinees": 1000.0},
        {"n_examinees": True},
        {"n_examinees": "100"},
        {"n_examinees": 100, "seed": 20260904},
    ]
    for body in invalid_bodies:
        response = await client.post(
            "/api/v1/school/cat-management/simulations",
            headers=headers,
            json=body,
        )
        assert response.status_code == 422, response.text

    without_csrf = await client.post(
        "/api/v1/school/cat-management/simulations",
        json={},
    )
    assert without_csrf.status_code == 403
    assert without_csrf.json()["code"] == "csrf_failed"


def test_routes_are_registered_outside_the_frozen_openapi_document():
    app = create_app(settings=BackendSettings(environment="test", docs_enabled=True))
    included = [
        route
        for route in app.router.routes
        if getattr(route, "original_router", None) is cat_management_router
    ]
    assert len(included) == 1
    assert included[0].include_context.include_in_schema is False
    assert all("cat-management" not in path for path in app.openapi()["paths"])
    simulation_route = next(
        route for route in cat_management_router.routes if route.path.endswith("/simulations")
    )
    assert simulation_route.dependant.dependencies[0].call.__name__ == "csrf_protected"
