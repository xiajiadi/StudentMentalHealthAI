# StudentMentalHealthAI · 08 Safety Engine

Independent Safety Control Plane for Round 1. The service owns safety
signals, deterministic policy decisions, privacy checks, model-backed input and
output checks, retrieval safety checks, crisis routing, human-review metadata,
and PII-safe traces.

## Boundary

This module does not replace the root API, Assessment Engine, RAG Engine, or
LLM Runtime. It consumes upstream assessment signals and retrieved chunks but
does not calculate theta, standard error, psychometric thresholds, diagnoses, or
clinical risk scores. It has no normal free-form LLM client.

OPA is a mandatory loopback-only sidecar. Presidio is the privacy adapter,
NeMo Guardrails 0.24.x is used through its I/O rail API, and the pinned local
Qwen3Guard-Gen-0.6B provider is CPU-compatible. Retrieval safety is marked
`PARTIAL` because NeMo IORails does not provide a retrieval surface in the
selected release.

## Local run

Use Python 3.12 and keep model/tool caches on D:. The recommended local
commands are:

```powershell
uv sync --extra test
uv sync --extra runtime --extra test
$env:SMHAI_MANAGE_OPA = "1"
$env:SMHAI_OPA_BINARY = "D:\Dev\tools\opa\v1.20.2\opa.exe"
uv run safety-engine
```

The server binds to `127.0.0.1:8190`. It exposes internal endpoints under
`/internal/safety/` and health endpoints under `/health`; it does not edit or
mount the project's frozen root OpenAPI document.

Future callers can use `safety_engine.client.SafetyClient`, which exchanges
JSON dictionaries only and does not depend on any third-party safety adapter.

## Verification

```powershell
uv run pytest
uv run ruff check src tests evaluation
uv run python evaluation\harness.py --help
```

The real-component and acceptance status is recorded in
`reports/SAFETY_RUNTIME_COMPATIBILITY.md` and
`reports/SAFETY_ROUND1_ACCEPTANCE.md`. A skipped or unavailable hard gate is
reported as a blocker, never as a fabricated pass.
