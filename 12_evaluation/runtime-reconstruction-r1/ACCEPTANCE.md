# LLM Runtime Service Reconstruction Round 1 — Acceptance

## Decision

**Runtime-service Round 1: ACCEPTED locally.**

**Project-level acceptance: PARTIAL PASS.** The reconstructed service, root
Gate, and required local integration behavior pass. The existing full-module
Ruff surface remains non-clean, and no real llama-server GPU run was available.

This is a local candidate only. No push, pull request, merge, tag, deployment,
or release action is authorized by this request.

## Acceptance matrix

| Area | Decision | Current evidence |
|---|---|---|
| Reconstruction provenance | Accept | Source inventory records the absence of recoverable service source; no historical implementation is claimed. |
| Frozen-contract boundary | Accept | Root frozen files retain their baseline hashes; no root contract or other module source was changed. |
| Lifecycle | Accept | Explicit `STOPPED → STARTING → READY/DEGRADED → STOPPING → STOPPED` state path; FastAPI lifespan delegates startup/shutdown. |
| Provider boundary | Accept | Provider registry validates IDs, local loopback endpoints, enabled state, and managed/external mode. |
| Model boundary | Accept | Registry-only logical-to-provider mapping, digest-aware discovery, no `:latest`, local-only fallback chain. |
| Buffered generation | Accept | RuntimeService returns provider/model identity, structured attempts, trace, and no raw prompt persistence. |
| Retry and fallback | Accept | Bounded retries are limited to retryable errors; fallback is local-only and excludes structured validation, cancellation, and programming failures. |
| Structured output | Accept | Ollama native JSON schema forwarding plus strict JSON Schema/Pydantic validation; no text repair. |
| Streaming and cancellation | Accept | Internal normalized events; cancellation is terminal and never emits `DONE` afterward. |
| Process ownership | Accept | Managed PID/create-time identity and descendant shutdown; external processes are never terminated by the runtime. |
| Real provider evidence | Accept | Ollama 0.21.1, both qwen2.5 models, stream/structured/cancellation/switching/fallback suite: 3 passed. |
| Root Gate | Accept | 13 contract tests and the OpenAPI validator stage pass. |
| Static quality | Partial | Targeted reconstructed surface passes Ruff; full module reports 74 findings. |
| GPU/llama.cpp | Deferred | Hardware is detected, but no real llama-server binary run was available. |

## Required durable records

- Technical decision: `14_docs/runtime-reconstruction/RUNTIME_SERVICE_TECHNICAL_DECISION_V1.md`
- Source inventory: `14_docs/runtime-reconstruction/CURRENT_RUNTIME_SOURCE_INVENTORY.md`
- Requirements matrix: `14_docs/runtime-reconstruction/RUNTIME_RECONSTRUCTION_REQUIREMENTS_MATRIX.md`
- Conflict register: `14_docs/runtime-reconstruction/RUNTIME_RECONSTRUCTION_CONFLICT_REGISTER.md`
- Design: `14_docs/runtime-reconstruction/RUNTIME_SERVICE_RECONSTRUCTION_DESIGN.md`
- Open-source audit: `14_docs/runtime-reconstruction/OPEN_SOURCE_RUNTIME_REFERENCE_AUDIT.md`
- Human evidence: `12_evaluation/runtime-reconstruction-r1/HUMAN_EVIDENCE.md`
- Machine evaluation: `12_evaluation/runtime-reconstruction-r1/runtime_reconstruction_r1_evaluation.json`

## Handoff state

The candidate branch is ready for review in the isolated worktree. Remaining
work is outside this Round 1 runtime acceptance: decide whether to clean the
existing full-module Ruff findings and provide a real llama-server GPU binary
for a separate acceptance run. Those checks must remain separate from the
passing targeted runtime evidence.
