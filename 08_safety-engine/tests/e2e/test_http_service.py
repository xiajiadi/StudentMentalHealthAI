from __future__ import annotations

from fastapi.testclient import TestClient

from safety_engine.api import create_app


def _payload(message: str, metadata: dict | None = None) -> dict:
    return {
        "context": {
            "trace_id": "http-trace-001",
            "request_id": "http-request-001",
            "actor_role": "STUDENT",
            "age_group": "ADOLESCENT",
            "current_user_message": message,
            "conversation_metadata": metadata or {},
        }
    }


def test_internal_http_crisis_route_is_deterministic(make_service):
    service, _ = make_service()
    app = create_app(service=service)

    with TestClient(app) as client:
        response = client.post(
            "/internal/safety/check-input",
            json=_payload(
                "SYNTHETIC_CRISIS_SIGNAL",
                {"synthetic_fixture": True, "explicit_crisis_signal": True},
            ),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["action"] == "CRISIS_ROUTE"
    assert body["normal_llm_invoked"] is False
    assert body["review_case"]["status"] == "PENDING"


def test_internal_http_review_creation_is_metadata_only(make_service):
    service, _ = make_service()
    app = create_app(service=service)

    with TestClient(app) as client:
        response = client.post(
            "/internal/safety/reviews",
            json={
                "decision_id": "DEC_http_001",
                "trace_id": "trace-http-review-001",
                "reason_codes": ["CLINICAL_OVERREACH"],
                "actor_role": "REVIEWER",
                "disclosure_policy": "FULL",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["review_id"] == body["review_case_id"]
    assert body["notification_sent"] is False
    assert body["synthetic_fixture_only"] is True
