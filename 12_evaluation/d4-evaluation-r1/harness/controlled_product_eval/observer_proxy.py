"""Transparent loopback observers for D4-3B RAG and Runtime service calls.

The proxy forwards request/response bytes unchanged. Logs contain only safe
correlation, identity, population, and evidence metadata; prompts and generated
text are never written to disk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response

from .manifest import is_loopback_url
from .post_runtime_diagnostic import project_runtime_candidate

_SAFETY_ACTIONS = frozenset(
    {"PROCEED", "PROCEED_WITH_BOUNDARY", "BLOCK", "REVIEW_REQUIRED", "CRISIS_ROUTE"}
)
_SAFETY_REASON_CODES = frozenset(
    {
        "NO_BLOCKING_SIGNAL",
        "EXPLICIT_CRISIS_SIGNAL",
        "CONTENT_UNSAFE",
        "PROMPT_INJECTION",
        "JAILBREAK",
        "CLINICAL_OVERREACH",
        "CONTENT_CONTROVERSIAL",
        "PII_DETECTED",
        "DISCLOSURE_RESTRICTED",
        "ASSESSMENT_SIGNAL_RECEIVED",
        "RETRIEVAL_SOURCE_INELIGIBLE",
        "COMPONENT_UNAVAILABLE",
        "SAFETY_SERVICE_UNAVAILABLE",
        "POLICY_ENGINE_UNAVAILABLE",
        "POLICY_EVALUATION_FAILED",
        "GUARD_MODEL_UNAVAILABLE",
        "PRIVACY_ENGINE_UNAVAILABLE",
        "GUARDRAIL_CHECK_FAILED",
        "INVALID_SAFETY_CONTEXT",
        "REVIEW_QUEUE_FAILED",
        "CRISIS_TEMPLATE_UNAVAILABLE",
        "RETRIEVAL_SAFETY_CHECK_FAILED",
    }
)
_SAFETY_STAGES = {
    "/internal/safety/check-input": "INPUT",
    "/internal/safety/check-retrieval": "RETRIEVAL",
    "/internal/safety/check-output": "OUTPUT",
}
_RUN_ID = re.compile(r"^(?:D4RUN|D4SMOKE)-[A-Za-z0-9][A-Za-z0-9._-]*$")


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _hash_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_request_summary(name: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    summary: dict[str, Any] = {}
    if name == "rag":
        for key in ("target_population", "target_role", "retrieval_id", "top_k"):
            if value.get(key) is not None:
                summary[key] = value[key]
        query = value.get("query")
        if isinstance(query, str):
            summary["query_sha256"] = _hash_text(query)
            summary["query_length"] = len(query)
    else:
        for key in ("generation_id", "assessment_id", "retrieval_id", "logical_model_id", "contract_model_id"):
            if value.get(key) is not None:
                summary[key] = value[key]
        chunk_ids = value.get("chunk_ids")
        if isinstance(chunk_ids, list):
            summary["chunk_ids"] = [item for item in chunk_ids if isinstance(item, str)]
    return summary


def _safe_trace(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    fields = (
        "target_population",
        "corpus_id",
        "corpus_identity",
        "collection_id",
        "index_id",
        "publication_id",
        "source_identity",
        "retrieval_id",
        "request_id",
        "trace_id",
        "model_id",
        "logical_model_id",
        "provider_model",
        "model_revision",
        "runtime_version",
        "digest",
        "fallback_used",
        "hardware",
        "finish_reason",
        "context_length",
        "output_budget",
    )
    return {field: value[field] for field in fields if value.get(field) is not None}


def _safe_response_summary(name: str, value: Any, request_summary: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return project_runtime_candidate(value) if name == "llm" else {}
    data = value.get("data") if isinstance(value.get("data"), dict) else value
    summary: dict[str, Any] = {}
    if name == "rag":
        if data.get("retrieval_id") is not None:
            summary["retrieval_id"] = data["retrieval_id"]
        trace = _safe_trace(data.get("trace"))
        if trace:
            summary["trace"] = trace
        summary["target_population"] = trace.get("target_population", request_summary.get("target_population"))
        chunks = data.get("chunks")
        if isinstance(chunks, list):
            summary["chunk_ids"] = [item.get("chunk_id") for item in chunks if isinstance(item, dict) and isinstance(item.get("chunk_id"), str)]
            summary["document_ids"] = [item.get("document_id") for item in chunks if isinstance(item, dict) and isinstance(item.get("document_id"), str)]
            summary["source_ids"] = [item.get("source_id") for item in chunks if isinstance(item, dict) and isinstance(item.get("source_id"), str)]
            summary["content_hashes"] = [item.get("content_hash") for item in chunks if isinstance(item, dict) and isinstance(item.get("content_hash"), str)]
    else:
        trace = _safe_trace(data.get("trace"))
        if trace:
            summary.update(trace)
        for key in ("model_id", "logical_model_id", "runtime_version"):
            if data.get(key) is not None:
                summary.setdefault(key, data[key])
        if "fallback_used" not in summary and isinstance(data.get("fallback_used"), bool):
            summary["fallback_used"] = data["fallback_used"]
        summary.update(project_runtime_candidate(data))
        # Candidate text, prompt text, token values, and raw trace data are never logged.
    return summary


def _safe_runtime_health(value: Any) -> dict[str, Any] | None:
    """Keep only readiness and model identity fields from Runtime health."""

    if not isinstance(value, dict) or value.get("status") != "READY":
        return None
    health = value.get("health")
    if not isinstance(health, dict):
        return None
    if health.get("readiness") != "pass" or health.get("cloud_fallback") is not False:
        return None
    models = health.get("models")
    providers = health.get("providers")
    if not isinstance(models, dict) or not isinstance(providers, dict):
        return None
    safe_models: dict[str, dict[str, Any]] = {}
    for logical_id, model in models.items():
        if not isinstance(logical_id, str) or not isinstance(model, dict):
            continue
        fields = ("logical_model_id", "provider_model_id", "availability", "inference_readiness", "loaded")
        safe_models[logical_id] = {field: model[field] for field in fields if model.get(field) is not None}
    return {
        "state": health.get("state"),
        "readiness": health.get("readiness"),
        "runtime_version": health.get("runtime_version"),
        "cloud_fallback": health.get("cloud_fallback"),
        "models": safe_models,
        "provider_ids": sorted(key for key in providers if isinstance(key, str)),
    }


def create_observer_app(
    *, name: str, upstream: str, events_file: str | Path, run_id: str | None = None
) -> FastAPI:
    if name not in {"rag", "llm", "safety"}:
        raise ValueError("observer name must be 'rag', 'llm', or 'safety'")
    if name == "safety" and (not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id)):
        raise ValueError("Safety observer requires a valid run ID")
    if not is_loopback_url(upstream):
        raise ValueError("observer upstream must be HTTP loopback")
    parsed = urlparse(upstream)
    if parsed.path not in ("", "/"):
        raise ValueError("observer upstream URL cannot include a path")
    event_path = Path(events_file)
    event_path.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    client = httpx.AsyncClient(
        base_url=upstream.rstrip("/"),
        timeout=httpx.Timeout(190.0),
        follow_redirects=False,
        trust_env=False,
    )
    app = FastAPI(title=f"D4-3B {name} observer", version="1.0")

    def record(event: dict[str, Any]) -> None:
        with lock:
            with event_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        if name == "safety":
            try:
                upstream_response = await client.get("/health/ready")
                upstream_payload = upstream_response.json() if upstream_response.status_code == 200 else {}
            except (httpx.HTTPError, ValueError):
                return {"status": "NOT_READY", "observer": name, "upstream": upstream.rstrip("/")}
            if not isinstance(upstream_payload, dict) or upstream_payload.get("status") != "READY":
                return {"status": "NOT_READY", "observer": name, "upstream": upstream.rstrip("/")}
            return {
                "status": "READY",
                "observer": name,
                "upstream": upstream.rstrip("/"),
                "service_identity": {"service": "safety_control_plane"},
            }
        if name == "rag":
            try:
                upstream_response = await client.get("/health")
                upstream_payload = upstream_response.json() if upstream_response.status_code == 200 else {}
            except (httpx.HTTPError, ValueError):
                return {"status": "NOT_READY", "observer": name, "upstream": upstream.rstrip("/")}
            if not isinstance(upstream_payload, dict) or upstream_payload.get("status") != "READY":
                return {"status": "NOT_READY", "observer": name, "upstream": upstream.rstrip("/")}
            fields = (
                "service",
                "retrieval_mode",
                "corpus_version",
                "eligible_chunk_count",
                "evaluation_only",
                "synthetic_fixture_only",
                "index_id",
                "index_reused",
                "eligible_chunk_ids",
                "index_manifest_hash",
                "corpus_manifest_hash",
                "source_packet_id",
                "source_packet_hash",
                "input_manifest_hash",
                "config_hash",
            )
            identity = {field: upstream_payload[field] for field in fields if field in upstream_payload}
            return {
                "status": "READY",
                "observer": name,
                "upstream": upstream.rstrip("/"),
                "service_identity": identity,
            }
        try:
            upstream_response = await client.get("/health/ready")
            upstream_payload = upstream_response.json() if upstream_response.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            return {"status": "NOT_READY", "observer": name, "upstream": upstream.rstrip("/")}
        runtime_identity = _safe_runtime_health(upstream_payload)
        if runtime_identity is None:
            return {"status": "NOT_READY", "observer": name, "upstream": upstream.rstrip("/")}
        return {
            "status": "READY",
            "observer": name,
            "upstream": upstream.rstrip("/"),
            "service_identity": runtime_identity,
        }

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    async def forward(request: Request, path: str) -> Response:
        body = await request.body()
        request_path = "/" + path
        url = request_path
        if request.url.query:
            url += "?" + request.url.query
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in {"host", "content-length", "connection", "transfer-encoding"}
        }
        payload: Any = None
        if (
            name != "safety"
            and body
            and request.headers.get("content-type", "").startswith("application/json")
        ):
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = None
        request_id = request.headers.get("x-request-id")
        trace_id = request.headers.get("x-trace-id")
        safety_stage = _SAFETY_STAGES.get(request_path) if name == "safety" else None
        if name == "safety":
            event = {
                "timestamp": _timestamp(),
                "observer": name,
                "run_id": run_id,
                "request_id": request_id,
                "trace_id": trace_id,
                "stage": safety_stage,
            }
        else:
            request_summary = _safe_request_summary(name, payload)
            event = {
                "timestamp": _timestamp(),
                "observer": name,
                "method": request.method,
                "path": request_path,
                "request_id": request_id,
                "trace_id": trace_id,
                "request_body_sha256": hashlib.sha256(body).hexdigest() if body else None,
                "request_body_length": len(body),
                "request_summary": request_summary,
            }
        try:
            upstream_response = await client.request(request.method, url, headers=headers, content=body)
        except httpx.HTTPError as exc:
            if name != "safety" or safety_stage is not None:
                error_event = {**event, "status_code": 503}
                if name != "safety":
                    error_event["upstream_error"] = type(exc).__name__
                else:
                    error_event.update({"action": None, "reason_codes": []})
                record(error_event)
            return Response(
                content=b'{"error":{"code":"UPSTREAM_UNAVAILABLE"}}',
                status_code=503,
                media_type="application/json",
            )
        response_payload: Any = None
        if upstream_response.content and upstream_response.headers.get("content-type", "").startswith("application/json"):
            try:
                response_payload = upstream_response.json()
            except ValueError:
                response_payload = None
        if name == "safety":
            if safety_stage is not None:
                data = response_payload if isinstance(response_payload, dict) else {}
                decision = data.get("decision") if isinstance(data.get("decision"), dict) else {}
                action = decision.get("action")
                codes = decision.get("reason_codes")
                safe_codes = (
                    [code for code in codes if isinstance(code, str) and code in _SAFETY_REASON_CODES]
                    if isinstance(codes, list)
                    else []
                )
                record(
                    {
                        **event,
                        "status_code": upstream_response.status_code,
                        "action": action if action in _SAFETY_ACTIONS else None,
                        "reason_codes": safe_codes,
                    }
                )
        else:
            response_summary = _safe_response_summary(name, response_payload, request_summary)
            record({**event, "status_code": upstream_response.status_code, "response_summary": response_summary})
        response_headers = {
            key: value
            for key, value in upstream_response.headers.items()
            if key.lower() not in {"content-length", "transfer-encoding", "connection", "content-encoding"}
        }
        return Response(
            content=upstream_response.content,
            status_code=upstream_response.status_code,
            headers=response_headers,
            media_type=upstream_response.headers.get("content-type"),
        )

    @app.on_event("shutdown")
    async def close_client() -> None:
        await client.aclose()

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one D4-3B loopback observer proxy")
    parser.add_argument("--name", choices=("rag", "llm", "safety"), required=True)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--events-file", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    app = create_observer_app(
        name=args.name,
        upstream=args.upstream,
        events_file=args.events_file,
        run_id=args.run_id,
    )
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
