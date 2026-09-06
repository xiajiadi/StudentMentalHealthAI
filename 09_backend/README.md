# StudentMentalHealthAI Backend

09_backend is the application orchestration and backend-for-frontend layer.
It owns HTTP concerns, session authentication, authorization, workflow ordering,
safe DTOs, audit metadata, and integration ports. It does not implement CAT
estimation, retrieval/reranking, LLM inference, Safety policy, or database
schema.

## Local run

This module uses an isolated Python 3.12 environment.

    uv sync --extra test --extra quality
    uv run python -m smhai_backend.main

The development server binds to 127.0.0.1:8080. The default local/test
configuration uses contract-faithful in-memory adapters and a synthetic
Safety adapter. To attempt the real Safety HTTP service, set
SMHAI_SAFETY__MODE=http and keep the service at the configured loopback URL
(normally http://127.0.0.1:8190).

The default adapters are process-local, non-durable, single-worker development
adapters. They are not production persistence and are not safe for multiple
workers. The Database Agent will provide persistent adapters later; this round
does not create SQLAlchemy models, migrations, tables, or DDL.

## Verification

    uv run pytest
    uv run ruff format --check src tests scripts
    uv run ruff check src tests scripts
    uv run pyright
    uv run python -m compileall -q src tests scripts
    uv run openapi-spec-validator reports/backend_round1_openapi.json

Use scripts/run_vertical_slice.py for the synthetic end-to-end harness and
scripts/run_real_safety_integration.py only when the real local Safety service
is available. Neither harness uses real student data.
