"""Transparent, body-blind HTTP observer used only for closure evidence.

The proxy forwards bytes and status codes without rewriting decisions or
responses.  It records method, path, correlation IDs, length, and a body hash;
request and response bodies never enter the log.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_request_summary(name: str, payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        return {}
    summary: dict[str, object] = {}
    if name == "rag":
        if payload.get("retrieval_id"):
            summary["retrieval_id"] = payload["retrieval_id"]
        summary["top_k"] = payload.get("top_k")
    elif name == "llm":
        for key in ("generation_id", "assessment_id", "retrieval_id", "logical_model_id", "contract_model_id"):
            if payload.get(key) is not None:
                summary[key] = payload[key]
        if isinstance(payload.get("chunk_ids"), list):
            summary["chunk_ids"] = payload["chunk_ids"]
    elif name == "safety":
        context = payload.get("context")
        if isinstance(context, dict):
            for key in ("trace_id", "request_id"):
                if context.get(key) is not None:
                    summary[key] = context[key]
        if payload.get("candidate_text") is not None:
            summary["candidate_present"] = True
            summary["candidate_length"] = len(str(payload["candidate_text"]))
    elif name == "cat":
        for key in ("assessment_id", "subject_id", "item_id"):
            if payload.get(key) is not None:
                summary[key] = payload[key]
    elif name == "ollama":
        for key in ("model", "stream", "keep_alive"):
            if payload.get(key) is not None:
                summary[key] = payload[key]
        options = payload.get("options")
        if isinstance(options, dict):
            for key in ("num_ctx", "num_predict", "temperature", "seed"):
                if options.get(key) is not None:
                    summary[key] = options[key]
    return summary


def _safe_response_summary(name: str, payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        return {}
    summary: dict[str, object] = {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if name == "rag" and isinstance(data, dict):
        if data.get("retrieval_id") is not None:
            summary["retrieval_id"] = data["retrieval_id"]
        chunks = data.get("chunks")
        if isinstance(chunks, list):
            summary["chunk_ids"] = [item.get("chunk_id") for item in chunks if isinstance(item, dict) and item.get("chunk_id")]
            summary["document_ids"] = [item.get("document_id") for item in chunks if isinstance(item, dict) and item.get("document_id")]
            summary["source_ids"] = [item.get("source_id") for item in chunks if isinstance(item, dict) and item.get("source_id")]
            summary["content_hashes"] = [item.get("content_hash") for item in chunks if isinstance(item, dict) and item.get("content_hash")]
        citations = data.get("citations")
        if isinstance(citations, dict):
            items = citations.get("items") or citations.get("citations")
            if isinstance(items, list):
                summary["citation_ids"] = [item.get("citation_id") for item in items if isinstance(item, dict) and item.get("citation_id")]
        elif isinstance(citations, list):
            summary["citation_ids"] = [item.get("citation_id") for item in citations if isinstance(item, dict) and item.get("citation_id")]
    elif name == "llm" and isinstance(data, dict):
        for key in ("model_id", "logical_model_id", "runtime_version", "buffered"):
            if data.get(key) is not None:
                summary[key] = data[key]
        trace = data.get("trace")
        if isinstance(trace, dict):
            for key in ("request_id", "trace_id", "provider_model", "model_revision", "digest", "fallback_used", "hardware"):
                if trace.get(key) is not None:
                    summary[key] = trace[key]
    elif name == "safety" and isinstance(payload, dict):
        decision = payload.get("decision")
        if isinstance(decision, dict):
            for key in ("action", "reason_codes", "requires_human"):
                if decision.get(key) is not None:
                    summary[key] = decision[key]
        for key in ("trace_id", "request_id", "review_reference"):
            if payload.get(key) is not None:
                summary[key] = payload[key]
        summary["crisis_response_present"] = payload.get("crisis_response") is not None
    elif name == "cat" and isinstance(data, dict):
        for key in ("assessment_id", "status", "selected_item_id", "administered_count"):
            if data.get(key) is not None:
                summary[key] = data[key]
    elif name == "ollama" and isinstance(data, dict):
        for key in ("model", "done", "done_reason", "prompt_eval_count", "eval_count", "context_length"):
            if data.get(key) is not None:
                summary[key] = data[key]
    return summary


def create_app() -> FastAPI:
    name = os.environ.get("GPI_PROXY_NAME", "observer")
    upstream = os.environ.get("GPI_UPSTREAM_URL", "http://127.0.0.1:8000").rstrip("/")
    log_path = Path(os.environ.get("GPI_PROXY_LOG", f"{name}.jsonl"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    client = httpx.AsyncClient(base_url=upstream, follow_redirects=False, trust_env=False, timeout=190.0)

    def record(value: dict[str, object]) -> None:
        with lock:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")

    app = FastAPI(title=f"GPI observer {name}", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {"status": "READY", "observer": name, "upstream": upstream}

    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def forward(request: Request, path: str) -> Response:
        body = await request.body()
        request_id = request.headers.get("x-request-id")
        trace_id = request.headers.get("x-trace-id")
        url = "/" + path
        if request.url.query:
            url += "?" + request.url.query
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in {"host", "content-length", "connection"}
        }
        base_event: dict[str, object] = {
            "timestamp": _timestamp(),
            "observer": name,
            "method": request.method,
            "path": "/" + path,
            "request_id": request_id,
            "trace_id": trace_id,
            "body_length": len(body),
            "body_sha256": hashlib.sha256(body).hexdigest() if body else None,
        }
        request_payload: object = None
        if body and request.headers.get("content-type", "").startswith("application/json"):
            try:
                request_payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                request_payload = None
        request_summary = _safe_request_summary(name, request_payload)
        if request_summary:
            base_event["request_summary"] = request_summary
        try:
            response = await client.request(request.method, url, headers=headers, content=body)
        except httpx.HTTPError as exc:
            record({**base_event, "status_code": 503, "upstream_error": type(exc).__name__})
            return Response(
                content=json.dumps({"error": {"code": "UPSTREAM_UNAVAILABLE"}}),
                status_code=503,
                media_type="application/json",
            )
        response_payload: object = None
        if response.content and response.headers.get("content-type", "").startswith("application/json"):
            try:
                response_payload = response.json()
            except (UnicodeDecodeError, ValueError):
                response_payload = None
        response_summary = _safe_response_summary(name, response_payload)
        event = {**base_event, "status_code": response.status_code}
        if response_summary:
            event["response_summary"] = response_summary
        record(event)
        response_headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in {"content-length", "transfer-encoding", "connection", "content-encoding"}
        }
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=response_headers,
            media_type=response.headers.get("content-type"),
        )

    @app.on_event("shutdown")
    async def close_client() -> None:
        await client.aclose()

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("GPI_PROXY_PORT", "8270")), log_level="warning")
