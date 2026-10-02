from __future__ import annotations

import json

import httpx
import pytest
from harness.controlled_product_eval import observer_proxy
from harness.controlled_product_eval.observer_proxy import create_observer_app


@pytest.mark.asyncio
async def test_safety_observer_records_only_run_bound_allowlisted_decision(tmp_path, monkeypatch):
    real_async_client = httpx.AsyncClient

    async def upstream_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/safety/check-input"
        assert b"FREE_TEXT_SENTINEL" in request.content
        return httpx.Response(
            200,
            json={
                "operation": "INPUT",
                "trace_id": "TRACE_D4RUN-SAFETY-1",
                "crisis_response": "PRIVATE_RESPONSE_SENTINEL",
                "decision": {
                    "action": "CRISIS_ROUTE",
                    "reason_codes": ["EXPLICIT_CRISIS_SIGNAL", "UNAPPROVED_REASON_SENTINEL"],
                    "requires_human": True,
                    "trace_id": "TRACE_D4RUN-SAFETY-1",
                },
            },
        )

    def mock_upstream_client(*args, **kwargs):
        return real_async_client(
            *args,
            transport=httpx.MockTransport(upstream_handler),
            **kwargs,
        )

    monkeypatch.setattr(observer_proxy.httpx, "AsyncClient", mock_upstream_client)
    events_path = tmp_path / "safety.jsonl"
    app = create_observer_app(
        name="safety",
        upstream="http://127.0.0.1:8190",
        events_file=events_path,
        run_id="D4RUN-SAFETY-1",
    )
    async with app.router.lifespan_context(app), real_async_client(
        transport=httpx.ASGITransport(app=app),
        base_url="http://observer.test",
    ) as client:
        response = await client.post(
            "/internal/safety/check-input",
            headers={
                "X-Request-ID": "REQ_D4RUN-SAFETY-1",
                "X-Trace-ID": "TRACE_D4RUN-SAFETY-1",
                "Content-Type": "application/json",
            },
            content=b'{"context":{"current_user_message":"FREE_TEXT_SENTINEL"}}',
        )

    assert response.status_code == 200
    assert response.json()["decision"]["action"] == "CRISIS_ROUTE"
    rows = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert rows == [
        {
            "action": "CRISIS_ROUTE",
            "observer": "safety",
            "reason_codes": ["EXPLICIT_CRISIS_SIGNAL"],
            "request_id": "REQ_D4RUN-SAFETY-1",
            "run_id": "D4RUN-SAFETY-1",
            "stage": "INPUT",
            "status_code": 200,
            "timestamp": rows[0]["timestamp"],
            "trace_id": "TRACE_D4RUN-SAFETY-1",
        }
    ]
    serialized = events_path.read_text(encoding="utf-8")
    for forbidden in (
        "FREE_TEXT_SENTINEL",
        "PRIVATE_RESPONSE_SENTINEL",
        "UNAPPROVED_REASON_SENTINEL",
        "request_body_sha256",
        "request_body_length",
    ):
        assert forbidden not in serialized
