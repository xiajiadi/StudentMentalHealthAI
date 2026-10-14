from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from safety_engine.adapters.base import AdapterResult
from safety_engine.crisis import CrisisTemplateRepository
from safety_engine.domain import Action, ComponentHealth
from safety_engine.retrieval.research_student import (
    PINNED_CONSUMER_AGE_SCOPE,
    PINNED_MANIFEST_SHA256,
    PINNED_STUDY_REF,
    ResearchStudentRetrievalSafetyAdapter,
    ResearchStudentSourceRegistry,
)
from safety_engine.review import HumanReviewService, InMemoryReviewRepository
from safety_engine.service import SafetyEngineConfig, SafetyService
from school_research_safety_host import (
    HEALTH_PATH,
    MAX_REQUEST_BYTES,
    REQUEST_SCHEMA,
    ROUTE_PATH,
    ResearchSafetyHostError,
    create_app,
    preflight,
)


class _Privacy:
    component = "presidio"
    version = "unit-test"

    def health(self):
        return ComponentHealth(
            component=self.component, available=True, ready=True, version=self.version
        )

    def detect(self, content, *, trace_id):
        return AdapterResult(status="PASSED")


class _Guard:
    component = "nemo_guardrails"
    version = "unit-test"

    def health(self):
        return ComponentHealth(
            component=self.component, available=True, ready=True, version=self.version
        )

    async def check_input(self, content, *, trace_id):
        return AdapterResult(status="PASSED")

    async def check_output(self, content, *, trace_id):
        return AdapterResult(status="PASSED")


class _Qwen:
    component = "qwen3guard"
    version = "unit-test"

    def health(self):
        return ComponentHealth(
            component=self.component, available=True, ready=True, version=self.version
        )


class _Policy:
    component = "opa"
    version = "unit-test"
    policy_revision = "unit-test"

    def health(self):
        return ComponentHealth(
            component=self.component, available=True, ready=True, version=self.version
        )

    def evaluate(self, policy_input):
        codes = {signal["reason_code"] for signal in policy_input["signals"]}
        if {"RETRIEVAL_SOURCE_INELIGIBLE", "PROMPT_INJECTION"} & codes:
            return {
                "action": "BLOCK",
                "reason_codes": ["CONTENT_UNSAFE"],
                "requires_human": False,
            }
        return {
            "action": "PROCEED",
            "reason_codes": ["NO_BLOCKING_SIGNAL"],
            "requires_human": False,
        }


def _service(registry):
    safety_root = Path(__file__).resolve().parents[2] / "08_safety-engine"
    privacy = _Privacy()
    return SafetyService(
        privacy=privacy,
        nemo=_Guard(),
        qwen=_Qwen(),
        policy=_Policy(),
        review=HumanReviewService(InMemoryReviewRepository()),
        crisis_templates=CrisisTemplateRepository(safety_root / "templates" / "crisis"),
        config=SafetyEngineConfig(policy_revision="unit-test"),
        retrieval=ResearchStudentRetrievalSafetyAdapter(privacy, registry),  # type: ignore[arg-type]
    )


def _registry(clock=None):
    manifest = os.environ.get("PSYNOVA_STUDENT_RESEARCH_MANIFEST")
    if not manifest:
        import pytest

        pytest.skip(
            "Set PSYNOVA_STUDENT_RESEARCH_MANIFEST to the externally pinned package"
        )
    return ResearchStudentSourceRegistry.load(
        Path(manifest),
        expected_manifest_sha256=PINNED_MANIFEST_SHA256,
        study_ref=PINNED_STUDY_REF,
        consumer_age_scope=PINNED_CONSUMER_AGE_SCOPE,
        clock=clock or (lambda: datetime(2026, 10, 15, tzinfo=UTC)),
    )


def _payload(registry, record_id="INTERVENTION-WHO-PHYSICAL-ACTIVITY-START-2020"):
    record = registry._records[record_id]
    return {
        "schema_version": REQUEST_SCHEMA,
        "request_id": "req_research_safe_01",
        "trace_id": "trace_research_safe_01",
        "study_ref": PINNED_STUDY_REF,
        "package_id": registry.package_id,
        "manifest_sha256": registry.manifest_sha256,
        "purpose": "RESEARCH_SIMULATION",
        "consumer_age_scope": "14-17",
        "chunks": [
            {
                "chunk_id": "chunk_research_01",
                "content": record.text,
                "metadata": {
                    "source_id": record.source_id,
                    "record_id": record.record_id,
                    "content_hash": record.content_sha256,
                    "manifest_sha256": registry.manifest_sha256,
                    "rights_scope_note": registry._sources[
                        record.source_id
                    ].rights_scope_note,
                    "review_status": "pending",
                    "rights_status": "verified",
                    "role_scope": ["student"],
                    "population_scope": ["secondary_school_student"],
                    "risk_scope": ["normal"],
                },
            }
        ],
    }


def test_private_host_exposes_only_health_and_research_retrieval():
    registry = _registry()
    service = _service(registry)
    app = create_app(
        service, registry, clock=lambda: datetime(2026, 10, 15, tzinfo=UTC)
    )

    assert {route.path for route in app.routes} == {HEALTH_PATH, ROUTE_PATH}
    assert app.state.research_only is True
    assert app.state.professional_approval is False
    assert app.state.publication_eligible is False
    assert app.state.production_use is False


def test_route_runs_safety_service_and_returns_only_decision_trace():
    registry = _registry()
    service = _service(registry)
    app = create_app(
        service, registry, clock=lambda: datetime(2026, 10, 15, tzinfo=UTC)
    )

    with TestClient(app) as client:
        response = client.post(ROUTE_PATH, json=_payload(registry))

    assert response.status_code == 200
    body = response.json()
    assert body["operation"] == "RETRIEVAL"
    assert body["trace"]["request_id"] == "req_research_safe_01"
    assert body["trace"]["trace_id"] == "trace_research_safe_01"
    assert body["decision"]["action"] == Action.PROCEED.value
    assert "Doing some physical activity" not in response.text
    assert "record_id" not in response.text
    assert "source_id" not in response.text


def test_cdc_pending_source_is_blocked_without_returning_content():
    registry = _registry()
    service = _service(registry)
    app = create_app(
        service, registry, clock=lambda: datetime(2026, 10, 15, tzinfo=UTC)
    )
    payload = _payload(registry, "TRACE-CDC-SCHOOL-CONNECTEDNESS-2024")
    content = payload["chunks"][0]["content"]

    with TestClient(app) as client:
        response = client.post(ROUTE_PATH, json=payload)

    assert response.status_code == 200
    assert response.json()["decision"]["action"] == Action.BLOCK.value
    assert content not in response.text


def test_scope_mismatch_extra_fields_and_query_are_closed():
    registry = _registry()
    service = _service(registry)
    app = create_app(
        service, registry, clock=lambda: datetime(2026, 10, 15, tzinfo=UTC)
    )
    payload = _payload(registry)
    payload["package_id"] = "other-package"
    marker = payload["chunks"][0]["content"]

    with TestClient(app) as client:
        wrong_scope = client.post(ROUTE_PATH, json=payload)
        malformed = client.post(
            ROUTE_PATH, json={**_payload(registry), "unexpected": marker}
        )
        query = client.post(f"{ROUTE_PATH}?anything=secret", json=_payload(registry))

    assert wrong_scope.status_code == 403
    assert wrong_scope.json() == {"detail": {"code": "RESEARCH_SAFETY_SCOPE_DENIED"}}
    assert malformed.status_code == 422
    assert "unexpected" not in malformed.text and marker not in malformed.text
    assert query.status_code == 422
    assert "secret" not in query.text


def test_duplicate_json_keys_and_oversized_request_are_rejected_without_echo():
    registry = _registry()
    service = _service(registry)
    app = create_app(
        service, registry, clock=lambda: datetime(2026, 10, 15, tzinfo=UTC)
    )
    payload = json.dumps(_payload(registry), separators=(",", ":"))
    duplicate_key_payload = payload.replace(
        '"request_id":',
        '"schema_version":"psynova.school-student-research-safety.v1","request_id":',
        1,
    )
    oversized = b'{"body":"' + (b"x" * MAX_REQUEST_BYTES) + b'"}'

    with TestClient(app) as client:
        duplicate = client.post(ROUTE_PATH, content=duplicate_key_payload)
        too_large = client.post(ROUTE_PATH, content=oversized)

    assert duplicate.status_code == 422
    assert duplicate.json() == {"detail": {"code": "RESEARCH_SAFETY_REQUEST_INVALID"}}
    assert too_large.status_code == 413
    assert too_large.json() == {"detail": {"code": "RESEARCH_SAFETY_REQUEST_TOO_LARGE"}}


def test_expired_study_blocks_route_before_request_processing():
    registry = _registry()
    service = _service(registry)
    expired_clock = lambda: (
        datetime(2027, 6, 30, 15, 59, 59, tzinfo=UTC) + timedelta(seconds=1)
    )
    app = create_app(service, registry, clock=expired_clock)
    payload = _payload(registry)

    with TestClient(app) as client:
        response = client.post(ROUTE_PATH, json=payload)
        health = client.get(HEALTH_PATH)

    assert response.status_code == 410
    assert response.json() == {"detail": {"code": "RESEARCH_STUDY_EXPIRED"}}
    assert health.status_code == 410
    assert health.json() == {"status": "EXPIRED"}


def test_preflight_rejects_nonloopback_or_managed_shared_opa(monkeypatch):
    manifest = os.environ.get("PSYNOVA_STUDENT_RESEARCH_MANIFEST")
    if not manifest:
        import pytest

        pytest.skip(
            "Set PSYNOVA_STUDENT_RESEARCH_MANIFEST to the externally pinned package"
        )
    monkeypatch.setenv("SMHAI_OPA_URL", "https://example.invalid")
    try:
        preflight(
            manifest_file=Path(manifest),
            manifest_sha256=PINNED_MANIFEST_SHA256,
            study_ref=PINNED_STUDY_REF,
            consumer_age_scope=PINNED_CONSUMER_AGE_SCOPE,
            check_port=False,
        )
    except ResearchSafetyHostError as exc:
        assert exc.code == "SHARED_OPA_ENDPOINT_INVALID"
    else:
        raise AssertionError("nonloopback OPA endpoint must fail closed")
    monkeypatch.setenv("SMHAI_OPA_URL", "http://127.0.0.1:8181")
    monkeypatch.setenv("SMHAI_MANAGE_OPA", "1")
    try:
        preflight(
            manifest_file=Path(manifest),
            manifest_sha256=PINNED_MANIFEST_SHA256,
            study_ref=PINNED_STUDY_REF,
            consumer_age_scope=PINNED_CONSUMER_AGE_SCOPE,
            check_port=False,
        )
    except ResearchSafetyHostError as exc:
        assert exc.code == "SHARED_OPA_MUST_NOT_BE_MANAGED_BY_RESEARCH_HOST"
    else:
        raise AssertionError("research host must not own the shared OPA process")
