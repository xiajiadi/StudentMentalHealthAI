# Current Runtime Source Inventory

Inventory date: 2026-09-07
Baseline: `contract-hardening-r1-accepted` at
`66cb0e8a5eeecd05c8c5c1a3d0a3018a63920772`

## Reconciliation result

The accepted baseline contains no `06_llm-runtime/src/llm_runtime/runtime/`
directory. The required orchestration imports therefore fail before test
execution. This is a missing-source finding, not a source recovery.

Read-only history and object inspection found no recoverable implementation:

- reachable history has the Runtime package, providers, tests, CLI imports and
  reports, but no `runtime/service.py` or `runtime/process.py`;
- the official test imports are `llm_runtime.runtime.service.RuntimeService`
  and `llm_runtime.runtime.process.ManagedProcess`;
- the current CLI imports `RuntimeService` and the current API constructs it
  through `build_service()`;
- the GPU closure report records the same three collection errors and states
  that the acceptance-only GPU wrapper is not the product service;
- `git fsck --full --no-reflogs --unreachable` exposed unreachable objects, but
  no source candidate was found in the inspected unreachable commits/trees;
- the historical reports are requirements evidence only.

## Surviving source map

| Area | File | Surviving responsibility | Reconstruction impact |
|---|---|---|---|
| Domain DTOs | `06_llm-runtime/src/llm_runtime/domain/models.py` | `ModelEntry`, `GenerationRequest`, `ProviderResponse`, stream events, usage and trace DTOs | Reuse; add only registry/provenance fields required by the new policy |
| Model registry | `06_llm-runtime/src/llm_runtime/domain/registry.py` | JSON loading, logical/contract/provider ID resolution, discovery reconciliation | Extend with deterministic enablement, fallback and local-only checks |
| Error boundary | `06_llm-runtime/src/llm_runtime/errors.py` | stable `LLMRuntimeError`, provider/HTTP mapping | Extend taxonomy without changing existing values used by tests |
| Provider port | `06_llm-runtime/src/llm_runtime/providers/base.py` | sync discovery, health, lifecycle, generate, stream and cancel interface | Preserve |
| Ollama provider | `06_llm-runtime/src/llm_runtime/providers/ollama.py` | native `/api/version`, `/api/tags`, `/api/show`, `/api/ps`, `/api/generate`, `/api/chat`, `/api/pull` | Preserve semantics; allow only client close/line-decoding compatibility fixes |
| HTTP transport | `06_llm-runtime/src/llm_runtime/providers/http.py` | local JSON and stream transport, active cancellation table | Make the client long-lived, `trust_env=false`, finite-timeout and closeable |
| llama.cpp PoC | `06_llm-runtime/src/llm_runtime/providers/llama_cpp.py` | OpenAI-compatible health/discovery/generation/SSE adapter | Preserve as deferred diagnostic provider |
| Mock provider | `06_llm-runtime/src/llm_runtime/providers/mock.py` | deterministic synthetic lifecycle/generation/stream/cancel behavior | Primary unit-test double; never real evidence |
| Validation | `06_llm-runtime/src/llm_runtime/validation.py` | JSON parse plus Draft 2020-12 schema validation | Keep strict; no arbitrary repair |
| Trace | `06_llm-runtime/src/llm_runtime/observability/tracing.py` | privacy-filtered logging and `RuntimeTraceBuilder` | Reuse; attach attempt evidence |
| Hardware | `06_llm-runtime/src/llm_runtime/hardware/detector.py` | truthful host/GPU observation | Reuse |
| Module API | `06_llm-runtime/src/llm_runtime/api/app.py` | loopback FastAPI health/capabilities and buffered generation boundary | Wire one lifespan and reconstructed service |
| CLI | `06_llm-runtime/src/llm_runtime/cli.py` | config-driven provider construction and service commands | Wire explicit ProviderRegistry/process definitions |
| Configuration | `06_llm-runtime/config/*.json` | local Ollama, disabled cloud fallback, model identities and retry values | Source of configured provider/model policy |
| Tests | `06_llm-runtime/tests/` | existing provider/domain/validation tests plus blocked Runtime tests | Official expectations; matrix maps each before implementation |

## Missing source symbols

| Symbol/import | Evidence | Status before reconstruction |
|---|---|---|
| `llm_runtime.runtime.__init__` | CLI/API/tests and integration inventory | absent |
| `llm_runtime.runtime.service.RuntimeService` | official tests, CLI, reports, integration decision | absent |
| `llm_runtime.runtime.process.ManagedProcess` | official process test, GPU closure report | absent |
| `ProviderRegistry` | reconstruction architecture and integration requirement | absent |
| `GenerationResult` | reports, API mapping and reconstruction request | absent |
| runtime state/health coordinator | architecture and reconstruction request | absent |

## Import/API observations

1. `cli.py` already imports `.runtime.service`, so the current module does not
   import successfully even though all provider code is present.
2. `api/app.py` currently exposes `/health/live`, `/health/ready`, `/health`,
   `/capabilities`, and `/internal/llm/generations`; it constructs its Runtime
   at import time but performs no lifecycle startup.
3. Backend Round 1 deliberately used `CONTRACT_FAKE` because no formal LLM
   HTTP service was present. This round may publish the module-local loopback
   surface but must not modify Backend.

## Scope boundary

New source is limited to `06_llm-runtime/src/llm_runtime/runtime/`, compatible
domain/error/HTTP lifecycle changes in `06_llm-runtime`, and reconstruction
tests. Evidence and evaluation files are under the two explicitly allowed
documentation/evaluation paths. No other module source or frozen root asset is
owned by this reconstruction.
