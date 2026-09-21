"""Evaluation-only Runtime HTTP harness for the D3VAL output gate.

This file is not product configuration and is never used by the Normal case.
It implements the buffered Runtime HTTP response shape consumed by Backend and
returns the exact synthetic candidate used by the accepted ContractFake tests.
"""

from __future__ import annotations

import os
from typing import Any

import uvicorn
from fastapi import FastAPI, Request


# This is the exact accepted synthetic candidate used by the in-process
# Backend/Safety integration test.  The real HTTP harness keeps the same
# structured candidate and lets the real output Safety service decide.
UNSAFE_CANDIDATE = (
    '{"summary":"theta indicates a diagnosis","observations":[],'
    '"suggestions":[{"text":"Use the cited synthetic guidance.",'
    '"source_chunk_ids":["CHUNK_backend_0"]}],'
    '"disclaimer":"synthetic fixture"}'
)

app = FastAPI(title="D3VAL evaluation-only output-unsafe Runtime harness", version="D3VAL-1.0")


@app.get("/health/live")
async def health_live() -> dict[str, Any]:
    return {"status": "LIVE", "service": "d3val_output_unsafe_runtime"}


@app.get("/health/ready")
async def health_ready() -> dict[str, Any]:
    return {
        "status": "READY",
        "service": "llm_runtime",
        "health": {"synthetic_fixture_only": True, "candidate": "theta indicates a diagnosis"},
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    return await health_ready()


@app.get("/internal/llm/models")
async def models() -> dict[str, Any]:
    return {
        "models": [
            {
                "logical_model_id": "d3val-output-unsafe",
                "contract_model_id": "MODEL_d3val_output_unsafe",
                "provider_model_id": "d3val-output-unsafe",
                "status": "READY",
            }
        ],
        "cloud_fallback": False,
    }


@app.post("/internal/llm/generate")
@app.post("/internal/llm/generations")
async def generations(request: Request) -> dict[str, Any]:
    payload = await request.json()
    return {
        "request_id": payload.get("request_id"),
        "trace_id": payload.get("trace_id"),
        "data": {
            "text": UNSAFE_CANDIDATE,
            "model_id": str(payload.get("contract_model_id") or "MODEL_d3val_output_unsafe"),
            "logical_model_id": "d3val-output-unsafe",
            "model_version": "d3val-output-unsafe-1.0",
            "runtime_version": "d3val-output-unsafe-harness-1.0",
            "trace": {"buffered": True, "synthetic_fixture_only": True},
            "buffered": True,
            "synthetic_fixture_only": True,
        },
    }


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("D3VAL_UNSAFE_RUNTIME_PORT", "8261")))
