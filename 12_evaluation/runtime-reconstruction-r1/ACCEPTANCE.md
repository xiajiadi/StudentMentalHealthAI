# LLM Runtime Service Reconstruction Round 1 — Acceptance

## Decision

**Historical candidate report: superseded by the final closure package.**

**Historical project result: PARTIAL PASS.** The candidate report remains an
evidence record, not a Controller acceptance. The current closure result is
recorded under `14_docs/runtime-reconstruction/` with Controller status
`PENDING FINAL ACCEPTANCE`.

This is a local candidate only. No push, pull request, merge, tag, deployment,
or release action is authorized by this request.

## Acceptance matrix

| Area | Historical evidence state | Current evidence |
|---|---|---|
| Reconstruction provenance | Recorded | Source inventory records the absence of recoverable service source; no historical implementation is claimed. |
| Frozen-contract boundary | Recorded | Root frozen files retain their baseline hashes; no root contract or other module source was changed. |
| Lifecycle | Recorded | Explicit `STOPPED → STARTING → READY/DEGRADED → STOPPING → STOPPED` state path; FastAPI lifespan delegates startup/shutdown. |
| Provider boundary | Recorded | Provider registry validates IDs, local loopback endpoints, enabled state, and managed/external mode. |
| Model boundary | Recorded | Registry-only logical-to-provider mapping, digest-aware discovery, no `:latest`, local-only fallback chain. |
| Buffered generation | Recorded | RuntimeService returns provider/model identity, structured attempts, trace, and no raw prompt persistence. |
| Retry and fallback | Recorded | Bounded retries are limited to retryable errors; fallback is local-only and excludes structured validation, cancellation, and programming failures. |
| Structured output | Recorded | Ollama native JSON schema forwarding plus strict JSON Schema/Pydantic validation; no text repair. |
| Streaming and cancellation | Recorded | Internal normalized events; cancellation is terminal and never emits `DONE` afterward. |
| Process ownership | Recorded | Managed PID/create-time identity and descendant shutdown; external processes are never terminated by the runtime. |
| Real provider evidence | Historical pass | Ollama 0.21.1, both qwen2.5 models, stream/structured/cancellation/switching/fallback suite: 3 passed. |
| Root Gate | Historical pass | 13 contract tests and the OpenAPI validator stage pass. |
| Static quality | Historical partial | The prior report measured 74 findings; the closure package provides a fresh 79→69 differential with 0 new findings and clean touched Runtime files. |
| GPU/llama.cpp | Historical deferred | The candidate report had no product GPU run; the closure package now contains a separate fresh RuntimeService GPU smoke through isolated Ollama 0.33.3. |

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

The candidate branch and its closure evidence are ready for Controller review
in the isolated worktree. This historical file does not grant or imply
`ACCEPTED`; see the canonical closure package for the current engineering
status and remaining Controller decision.
