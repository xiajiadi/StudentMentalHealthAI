# LLM Runtime Technical Decision V1

Document Version: 1.0  
Status: PROVISIONALLY_FROZEN  
Date: 2026-09-04  
Depends on: Contract v0.1.0 FROZEN

This document freezes the Round 1 engineering boundary for `06_llm-runtime`.
It does not change a root Contract, select a clinical model, approve real
student data, or claim GPU acceptance.

## 1. Round 1 boundary

The module owns:

```text
model registry -> provider resolution -> lifecycle -> generation
                -> stream normalization -> structured validation
                -> retry/fallback -> trace and health
```

The module consumes a provider-neutral `GenerationRequest` containing the
frozen `generation.v1` identity plus runtime-only prompt/config fields. Prompt
construction remains in `07_prompt-engine`; safety decisions remain in
`08_safety-engine`; retrieval remains in `05_rag-engine`.

The root `generation.v1`, `config.v1`, `logging.v1`, and `api.v1` assets are
read-only inputs. No Contract Change Request was needed.

## 2. Provider decisions

| Provider | Round 1 position | Boundary | Current evidence |
| --- | --- | --- | --- |
| Ollama | `PRIMARY_LOCAL_RUNTIME` | Native `/api` adapter for discovery, metadata, lifecycle, generation, NDJSON streaming and JSON Schema format | Real local service/model test; actual installed version is recorded in the acceptance report |
| llama.cpp | `SECONDARY_LOW_LEVEL_RUNTIME` | `llama-server` OpenAI-compatible adapter plus managed-process seam | Provider PoC implemented; binary/model execution is recorded as PENDING unless run |
| vLLM | `FUTURE_SERVER_RUNTIME` | Research only; OpenAI server and structured-output reference | Not a Round 1 dependency |
| SGLang | `HIGH_PERFORMANCE_REFERENCE` | Research only; server/grammar architecture reference | Not a Round 1 dependency |
| LocalAI | `RUNTIME_ARCHITECTURE_REFERENCE` | Research only; backend and hardware abstraction reference | Not a Round 1 dependency |
| Olla | `HEALTH_ROUTING_RECOVERY_REFERENCE` | Research only; health, circuit breaker, recovery and stream retry ideas | Not deployed as an extra proxy layer |
| GPUStack | `FUTURE_DEPLOYMENT_REFERENCE` | Research only; GPU discovery/scheduling/deployment reference | Not a Round 1 dependency |
| LiteLLM | `FUTURE_GATEWAY_REFERENCE` | Research only; provider normalization/routing/error reference | Cloud fallback remains disabled |

The implementation uses no copied third-party source code. The research record
and exact public versions observed during this run are in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## 3. Ollama API choice

Ollama's native API is used for the primary adapter because the Round 1
management requirements need `/api/tags`, `/api/show`, `/api/ps`,
`/api/version`, and the native `keep_alive` lifecycle behavior. Prompt-based
generation uses `/api/generate`; callers that provide role messages use
`/api/chat`. Both paths share the same normalization and validation boundary.
Generation uses:

- `stream: false` for a complete response;
- `stream: true` for NDJSON normalization;
- `format` containing a JSON Schema for structured output;
- `options.num_predict`, `temperature`, `top_p`, optional `top_k`, `num_ctx`,
  `seed` and `stop`;
- `keep_alive` for preload, reuse and immediate unload;
- `think` passed only when a caller explicitly configures it.

The OpenAI-compatible endpoint is not used to emulate management features that
the native API exposes directly. The provider owns all Ollama field mapping so
upper layers never depend on Ollama chunks.

The default endpoint is `http://127.0.0.1:11434`. Cloud API endpoints and cloud
fallback are not configured or called.

## 4. Model registry and provenance

`config/models.v1.json` is the configuration-driven registry. Every entry
separates:

- `logical_model_id`, stable for the project;
- `contract_model_id`, the `MODEL_` identity used by `generation.v1`;
- `provider_model_id`, specific to Ollama or llama-server;
- source repository, revision/tag, digest, format, quantization, license and size;
- capabilities, hardware profile, compatibility and runtime status.

The official proposal baseline remains registered as:

```text
logical_model_id:  qwen2.5-7b-instruct
provider_model_id: qwen2.5:7b
source:            Qwen/Qwen2.5-7B-Instruct-GGUF
quantization:      Q4_K_M (first GPU candidate)
validation:        DEFERRED_GPU_VALIDATION
```

The current CPU engineering model is the officially listed `qwen2.5:0.5b`.
It is only a runtime engineering test model, not a final psychological model.
Its actual digest, size and quantization are populated from local Ollama
discovery/show responses after download; no unknown values are invented in the
registry.

## 5. llama.cpp boundary

The secondary adapter targets `llama-server`, not `llama-cpp-python` as the
only implementation. It uses:

- `GET /health` for server readiness;
- `GET /v1/models` for configured server model discovery;
- `POST /v1/chat/completions` for generation and SSE streaming;
- post-generation JSON Schema validation even when `response_format` is sent;
- `ManagedProcess` for a future local `llama-server.exe` lifecycle.

The provider does not claim portable load/unload semantics because
`llama-server` model lifecycle is normally process-scoped. If a binary and
small GGUF are available, the PoC can be run without changing `RuntimeService`.

## 6. Health and lifecycle

Health is intentionally layered:

1. provider liveness: endpoint responds;
2. provider readiness: provider can serve requests;
3. model availability: model is discovered;
4. inference readiness: model is loaded/ready for inference.

Ollama preload uses a native empty generation with `keep_alive: -1`; unload uses
the same API with `keep_alive: 0`. A request never starts the Ollama process or
downloads a model itself.

## 7. Streaming, cancellation and recovery

All providers emit `RuntimeStreamEvent` values:

```text
START -> DELTA* -> [USAGE] -> DONE
START -> DELTA* -> ERROR
START -> DELTA* -> CANCELLED
```

After `DONE`, no delta is accepted. A stream that has already emitted a delta
is never transparently retried and concatenated with a second response. A
pre-start transient HTTP failure may be retried a bounded number of times;
provider-specific failures are normalized to the stable error domain.

Fallback is local-only and explicit in the registry. The trace records the
requested and actual logical model plus the reason. There is no cloud provider
entry and no implicit remote fallback.

## 8. Structured output

The provider may ask the runtime engine for JSON Schema constrained output, but
the runtime still parses the result and validates it with Draft 2020-12 JSON
Schema. Syntax-only `json.loads` success is not sufficient. Invalid JSON,
missing required fields, wrong types and additional-property violations become
`INVALID_STRUCTURED_OUTPUT`.

Runtime output is never marked `approved`; approval and post-safety review are
owned by downstream safety/orchestration layers.

## 9. Hardware policy

`HardwareDetector` reports host facts and only reports `gpu_present=true` when
`nvidia-smi` returns an actual GPU row. A missing executable, permission error,
non-zero exit or empty output is not converted into synthetic GPU data.

Round 1 is CPU-first. The expected RTX 3060 12 GB eGPU is future hardware; its
acceptance is deferred until it is physically connected and `nvidia-smi` plus
real Ollama/llama.cpp tests succeed.

## 10. Privacy and network

- Round 1 prompts and fixtures are synthetic only.
- `subject_id` and Contract IDs are not written into provider prompts by this
  module unless the caller explicitly includes a runtime prompt (which remains
  the caller's responsibility).
- Structured logs contain IDs, versions, status and timings, not full prompts or
  raw provider bodies.
- Local services default to `127.0.0.1`; no `0.0.0.0` binding is configured.
- Model files and runtime logs stay outside the repository; the configured
  Ollama model directory is `D:\Dev\caches\ollama-models`.

## 11. Validation and non-goals

Round 1 does not install LangChain, LlamaIndex, LocalAI, LiteLLM, vLLM or
SGLang. It does not build a model store UI, prompt engine, safety engine, RAG
pipeline, tool-calling agent, cloud route or clinical interpretation layer.

Benchmarks report observed values only. No TTFT, throughput or latency SLA is
declared from a network benchmark.
