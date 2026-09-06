# LLM Runtime Round 1 Acceptance

Evidence date: 2026-09-05  
Decision scope: CPU Engineering Round 1  
GPU Acceptance: `DEFERRED`

## 1. Conclusion

`PARTIAL PASS`

The `06_llm-runtime` CPU path, real Ollama chain and module tests passed. The
repository-wide root contract command is not fully green because an existing
`05_rag-engine/TASK.md` governance subtest fails; that module was outside this
task and was not modified. The external OpenAPI validator could not be
downloaded because the PyPI request timed out. llama.cpp execution and GPU
acceptance remain explicitly pending/deferred.

## 2. Scope

This acceptance covers CPU Engineering Round 1. It does not approve a clinical
model, psychological interpretation, Prompt Engine, Safety Engine, RAG
integration, cloud route, or GPU performance claim.

GPU Acceptance is `DEFERRED`.

## 3. Hardware

| Field | Observed value |
| --- | --- |
| OS | Windows 11 Professional, build 10.0.26200, 64-bit |
| CPU | Intel(R) Core(TM) Ultra 9 185H |
| CPU cores / threads | 16 / 22 |
| RAM | 33,752,997,888 bytes (31.4349 GiB; 32,961,912 KB) |
| GPU | No usable NVIDIA GPU detected |
| CUDA | Not available / not accepted |
| NVIDIA driver | Not available; `nvidia-smi` returned a permissions failure |

The detector reports `gpu_present=false`, `gpus=[]` and `profile=CPU_ONLY`.
No GPU attributes were inferred.

## 4. Open-source Research

| Project | Round 1 status |
| --- | --- |
| Ollama | `INTEGRATED` |
| llama.cpp | `POC`; execution `PENDING` |
| vLLM | `REFERENCE ONLY` / future server runtime |
| SGLang | `REFERENCE ONLY` / high-performance reference |
| LocalAI | `REFERENCE ONLY` / runtime architecture reference |
| Olla | `REFERENCE ONLY` / health-routing-recovery reference |
| GPUStack | `REFERENCE ONLY` / future deployment reference |
| LiteLLM | `REFERENCE ONLY` / future gateway reference |

The exact research versions and licenses are recorded in
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

## 5. Ollama

- Installed client/service: `0.21.1`.
- Public release version observed during research: `v0.33.3`.
- Native `/api/version` health check: passed.
- Endpoint: `http://127.0.0.1:11434`.
- Local model cache: `D:\Dev\caches\ollama-models`.
- Because the installed older Windows service ignored the redirected model
  environment during pull, `C:\Users\15848\.ollama\models` was made a
  directory junction to the D-drive cache. Model bytes are on D, not C.
- The service was started for evidence collection and can be stopped after
  acceptance; no public bind or cloud endpoint was configured.

## 6. CPU Test Model

| Field | Evidence |
| --- | --- |
| Logical model | `qwen2.5-0.5b-engineering` |
| Contract model | `MODEL_local_cpu_test` |
| Provider model | `qwen2.5:0.5b` |
| Source | Ollama Library: `https://ollama.com/library/qwen2.5` |
| Revision/tag | `qwen2.5:0.5b` |
| Digest | `a8b0c51577010a279d933d14c2a8ab4b268079d44c5c8830c0a93900f1827c67` |
| Size | 397,821,319 bytes |
| Format / quantization | GGUF / Q4_K_M |
| License | Apache-2.0, as returned by local model metadata and official model record |
| Status | `READY`; real CPU smoke chain passed |
| Purpose | `ENGINEERING TEST MODEL`, not a final psychological model |

## 7. Proposal Model

`qwen2.5-7b-instruct` remains registered as `MODEL_local_primary` with provider
candidate `qwen2.5:7b`, official Qwen GGUF source, and first quantization
candidate `Q4_K_M`. It is `REGISTERED` with `GPU_VALIDATION_DEFERRED`; it was not
downloaded or tested on this host.

## 8. Model Registry

`PASS` for configuration-driven registry and separated identities.

| Logical model ID | Contract model ID | Provider model ID |
| --- | --- | --- |
| `qwen2.5-0.5b-engineering` | `MODEL_local_cpu_test` | `qwen2.5:0.5b` |
| `qwen2.5-1.5b-engineering-fallback` | `MODEL_local_cpu_fallback` | `qwen2.5:1.5b` |
| `qwen2.5-7b-instruct` | `MODEL_local_primary` | `qwen2.5:7b` |

## 9. Discovery

`PASS`. Real `GET /api/tags` discovered one local model, and real
`POST /api/show` returned its digest, GGUF format, Q4_K_M quantization and
Apache license metadata. The registry reconciliation path was also exercised
through `RuntimeService.discover()`.

## 10. Health

`PASS`.

- Provider liveness: `pass`.
- Provider readiness: `pass`.
- Model availability before load: `available`.
- Model inference readiness before load: `ready`.
- Model inference readiness after load: `loaded`.
- The synthetic smoke generation completed with a non-empty response.

## 11. Lifecycle

`PASS` on the real Ollama model.

- Preload: native empty generation with `keep_alive=-1`, response
  `done_reason=load`.
- Loaded check: `/api/ps` reported the model.
- Unload: native empty generation with `keep_alive=0`, response
  `done_reason=unload`.
- Unloaded check: `/api/ps` reported `loaded=false` after the adapter's short
  acknowledgement wait.

## 12. Generate

`PASS`. Real non-streaming Ollama generation used synthetic engineering text,
returned non-empty content and `finish_reason=stop`. The recorded usage was
38 prompt tokens, 63 completion tokens and 101 total tokens. No student or
clinical prompt was used.

## 13. Streaming

`PASS`. The real normalized event sequence was:

```text
START -> DELTA* -> USAGE -> DONE
```

The integration evidence contained no delta after `DONE`; Ollama NDJSON was
not exposed to the upper layer.

## 14. Structured Output

`PASS`. The real request sent an engineering JSON Schema requiring an object
with a non-empty string `answer` and no additional properties. Ollama returned
`{"answer":"OK"}` through its native `format` field, and the runtime parsed
and validated it with Draft 2020-12 JSON Schema.

## 15. Cancellation

`PASS` for the real Ollama stream test. A long synthetic generation terminated
after cancellation with:

```text
START -> DELTA -> DELTA -> DELTA -> CANCELLED
```

No `DONE` was emitted after cancellation. The adapter closes the active local
HTTP stream and normalizes close-related races to `CANCELLED`.

## 16. Error Mapping

`PASS` in unit coverage and provider boundary code.

| Input condition | Normalized code |
| --- | --- |
| HTTP 404 containing a missing model message | `MODEL_NOT_FOUND` |
| HTTP 503 while loading | `PROVIDER_NOT_READY`, retryable |
| Provider message containing CUDA OOM | `OUT_OF_MEMORY`, not retryable |
| Invalid structured JSON or schema mismatch | `INVALID_STRUCTURED_OUTPUT` |
| Stream ending before terminal event | `STREAM_INTERRUPTED` |

## 17. Retry

`PASS` in unit coverage. A transient, pre-stream synthetic timeout was retried
once with the configured bounded backoff and then returned
`REQUEST_TIMEOUT`. The service does not retry or concatenate a stream after a
delta has been emitted.

## 18. Fallback

`PASS` in unit coverage with an explicit local fallback entry.

```text
requested_model = primary
actual_model    = fallback
reason          = PROVIDER_UNAVAILABLE
```

The real 1.5B candidate was not downloaded; this evidence is architecture and
Mock-provider recovery coverage, not a claim of two real models.

## 19. Cloud Fallback

`DISABLED`. Runtime configuration sets `cloud_fallback=false`; no cloud
provider is registered, called or used as an implicit fallback.

## 20. RuntimeTrace

Real `RuntimeService` evidence (`TRACE_ollama_runtime_service`):

| Field | Value |
| --- | --- |
| Request | `REQ_ollama_runtime_service` |
| Logical/provider model | `qwen2.5-0.5b-engineering` / `qwen2.5:0.5b` |
| Revision / digest / quantization | `qwen2.5:0.5b` / `a8b0c515...1827c67` / `Q4_K_M` |
| Runtime version | `0.1.0` |
| Prompt / completion tokens | 37 / 24 |
| TTFT | `N/A` for non-streaming request |
| Generation / total latency | 520.24 ms / 520.24 ms |
| Tokens per second | 46.13, based on provider token count |
| Retry / fallback | 0 / none |
| Finish / error | `stop` / none |

## 21. llama.cpp

`POC / PENDING`. `LlamaCppProvider` targets `llama-server` through
`/health`, `/v1/models` and `/v1/chat/completions`, including SSE and
post-generation schema validation. `ManagedProcess` provides start, readiness,
PID, stdout/stderr paths and shutdown. No `llama-server.exe` or GGUF server
run was available for this acceptance, so no real llama.cpp result is claimed.

## 22. vLLM

`REFERENCE / FUTURE`. vLLM was researched for OpenAI-compatible serving,
structured outputs, batching, quantization and Qwen support. It is not a
Round 1 dependency or integration.

## 23. CPU Benchmark

Real local benchmark for `qwen2.5:0.5b` with Ollama `0.21.1`; no internet
benchmark values were substituted.

| Measurement | Value |
| --- | ---: |
| Load/preload call | 1,097.73 ms |
| Warm non-stream request 1 | 798.28 ms; 43.84 tok/s |
| Warm non-stream request 2 | 591.87 ms; 59.13 tok/s |
| Stream TTFT | 134.10 ms |
| Stream total latency | 586.02 ms; 59.72 tok/s |
| Stream completion tokens | 35 |
| Observed RAM | 31.4349 GiB |

Non-streaming TTFT was recorded as `N/A`; the benchmark did not invent a
first-token value. The load value is a model preload call, not a fresh process
startup measurement. No SLA is declared.

## 24. GPU Acceptance

`DEFERRED`.

Reason: the expected external RTX 3060 12GB was not connected. `nvidia-smi`
was permission-limited and returned no usable GPU row. Therefore no VRAM,
CUDA, Qwen2.5-7B, Q4_K_M/Q5_K_M comparison, GPU throughput, or GPU stability
claim is made.

## 25. Tests

| Command | Result |
| --- | --- |
| `uv sync --extra test` | Passed; isolated module environment created |
| `.venv\Scripts\python.exe -X utf8 -m pytest -q` | 23 passed, 1 opt-in real integration skipped |
| `$env:SMHAI_RUN_OLLAMA_INTEGRATION='1'; .venv\Scripts\python.exe -X utf8 -m pytest -q` | 24 passed, 0 failed |
| `.venv\Scripts\python.exe -X utf8 -m compileall -q src tests evaluation` | Passed |
| Runtime JSON configuration parse | Passed |
| `uv tree --depth 2` / installed-package check | Passed; no large optional LLM frameworks installed |

## 26. Contract Tests

The runtime boundary test validates its `GenerationRequest` serialization
against frozen `generation.v1` and passed.

The root command, run with UTF-8 enabled, produced 13 tests with 1 failed
subtest, 42 passed subtests. The four OpenAPI shape/operation tests inside that
suite passed. The failed subtest was the existing
`05_rag-engine` governance-heading check. The project script's separate
`openapi-spec-validator` step was attempted but its PyPI download timed out.

## 27. Frozen Contract

`NOT MODIFIED`. No root schema, OpenAPI document, root governance document or
other frozen Contract was changed. No Contract Change Request was required.

## 28. Privacy

`PASS`. All prompts and fixtures were synthetic engineering text. No real
student, assessment, counseling or psychological result data was used. Logs
and traces omit prompt bodies and raw provider chunks.

## 29. Dependencies

The module's runtime dependency is `jsonschema 4.26.0`; test dependency is
`pytest 9.1.1`, with their normal transitive packages. LangChain, LlamaIndex,
LocalAI, LiteLLM, vLLM and SGLang are not installed as dependencies.

The project contains Ruff configuration, but Ruff was not installed locally
and `uvx ruff check src tests evaluation` could not fetch PyPI after three
timeouts. mypy and pyright are not configured. This is recorded rather than
reported as a lint pass.

## 30. Known Limitations

- The installed Ollama service is `0.21.1`, older than the researched public
  `v0.33.3`; API behavior should be rechecked after any service upgrade.
- llama.cpp has a provider PoC but no local server binary/model execution.
- The real 1.5B fallback candidate was not downloaded; fallback behavior is
  covered with Mock Provider.
- GPU acceptance, Qwen2.5-7B testing and quantization comparison are deferred.
- Runtime integration with Prompt Engine, Safety Engine and RAG is intentionally
  out of scope for this round.

## 31. Blockers

1. Repository-wide root governance gate: `05_rag-engine/TASK.md` does not
   contain the headings required by the existing root test. It is outside this
   task and must be repaired by its owning module.
2. The external `openapi-spec-validator` could not be fetched because the
   package index request timed out; internal OpenAPI tests passed.
3. RTX 3060 eGPU and llama-server execution are future validation items, not
   CPU Ollama implementation failures.

## 32. Recommendation

`CONDITIONAL APPROVE LLM RUNTIME ROUND 2` for continued local-runtime work,
provided the repository-wide acceptance label remains `PARTIAL PASS` until the
root governance subtest and external OpenAPI validator are cleared. Round 2
should not treat GPU or llama.cpp execution as already accepted.

## 33. Acceptance Closure

Closure evidence date: 2026-09-05  
Closure scope: CPU Engineering Round 1 only

Section 1 above remains the historical acceptance record (`PARTIAL PASS`) at
the time of the original review. This section records the subsequent,
evidence-first closure run; it does not rewrite that historical fact.

### 33.1 P0-1 Root Contract Gate

The formal project command was rerun from the repository root at
`2026-09-05T01:48:25+08:00`:

```powershell
.\00_architecture\tests\run_contract_checks.ps1
```

Result: `13 passed, 0 failed`, with `Ran 13 tests in 0.116s`, `OK`,
`openapi.v1.json: OK`, and script exit code 0. The previously recorded
`05-rag-engine` governance-heading failure is not present in the current
checkout. Its TASK currently contains `职责`、`输入`、`输出`、`禁止事项`、`接口`、
`验收标准`、`交付物`; no 05-rag file was modified in this closure.

See [`ROOT_CONTRACT_RECHECK.md`](ROOT_CONTRACT_RECHECK.md).

### 33.2 P0-2 External OpenAPI Validator

The root script's real external validator step passed against the frozen
`00_architecture/openapi.v1.json` target. The validator process returned exit
code 0 and reported `openapi.v1.json: OK`. Independent version output was:

```text
openapi-spec-validator 0.9.0
```

The four internal OpenAPI tests in the same root run also passed. The frozen
OpenAPI document was not modified.

See [`OPENAPI_EXTERNAL_VALIDATION.md`](OPENAPI_EXTERNAL_VALIDATION.md).

### 33.3 P1-1 Second Real Ollama Model

The official [Ollama Qwen2.5 Library](https://ollama.com/library/qwen2.5)
still lists `qwen2.5:1.5b`. The model was pulled with the real Ollama CLI and
the output reached SHA-256 verification, manifest write and `success`. The
installed runtime was kept at `0.21.1`; no upgrade was performed.

| Field | Observed value |
| --- | --- |
| Logical model ID | `qwen2.5-1.5b-engineering-fallback` |
| Provider model ID | `qwen2.5:1.5b` |
| Digest | `65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b` |
| Size | 986,061,892 bytes |
| Format / quantization | GGUF / Q4_K_M |
| License | Apache-2.0 |
| Discovery | real `GET /api/tags` and `/api/show` |
| Cache | `D:\Dev\caches\ollama-models` |

The ModelRegistry entry is now `READY` / `SUPPORTED` with this provenance.

### 33.4 Real Model Switching

The full real Ollama integration command was rerun:

```powershell
$env:SMHAI_RUN_OLLAMA_INTEGRATION = '1'
.venv\Scripts\python.exe -X utf8 -m pytest -q
```

The test generated two successful RuntimeService calls using the same
synthetic engineering prompt:

| Logical model ID | Provider model ID | Result | Latency | Trace ID |
| --- | --- | --- | ---: | --- |
| `qwen2.5-0.5b-engineering` | `qwen2.5:0.5b` | success | 1723.11 ms | `TRACE_ollama_switch_1` |
| `qwen2.5-1.5b-engineering-fallback` | `qwen2.5:1.5b` | success | 2727.65 ms | `TRACE_ollama_switch_2` |

No business prompt or provider-specific branch was added to switch models;
logical model resolution selected the two real provider IDs.

See [`REAL_MODEL_SWITCHING_EVIDENCE.md`](REAL_MODEL_SWITCHING_EVIDENCE.md).

### 33.5 Real Local Fallback and RuntimeTrace

The controlled Test Registry pointed the primary logical model to the absent
real provider model `smhai-acceptance-missing-model:round1` and the fallback
logical model to real `qwen2.5:1.5b`. The live Ollama Provider returned HTTP
404, normalized as `MODEL_NOT_FOUND`; RuntimeService then completed real local
inference with the fallback.

`TRACE_ollama_real_fallback` recorded:

| Field | Value |
| --- | --- |
| `requested_model` | `qwen2.5-controlled-missing-primary` |
| `requested_provider_model` | `smhai-acceptance-missing-model:round1` |
| `primary_error_normalized_code` | `MODEL_NOT_FOUND` |
| `fallback_attempted` | `true` |
| `fallback_model` | `qwen2.5-1.5b-engineering-fallback` |
| `fallback_provider_model` | `qwen2.5:1.5b` |
| `fallback_reason` | `MODEL_NOT_FOUND` |
| `actual_model` | `qwen2.5-1.5b-engineering-fallback` |
| `fallback_generation_success` | `true` |
| `retry_count` / `fallback_count` | `0` / `1` |
| `latency_ms` | 2886.34 |

The test kept Ollama alive and did not use Mock Provider or any cloud route.

See [`REAL_FALLBACK_EVIDENCE.md`](REAL_FALLBACK_EVIDENCE.md).

### 33.6 Regression and Dependency Closure

| Command | Result |
| --- | --- |
| `.venv\Scripts\python.exe -X utf8 -m pytest -q` | 23 passed, 1 existing opt-in integration skip |
| `$env:SMHAI_RUN_OLLAMA_INTEGRATION='1'; .venv\Scripts\python.exe -X utf8 -m pytest -q` | 26 passed, 0 failed, 0 skipped; 13.95s |
| `.venv\Scripts\python.exe -X utf8 -m compileall -q src tests evaluation` | exit 0 |
| `uv sync --extra test` | exit 0; 13 resolved, 12 checked |
| `uv lock --check` | exit 0 |
| `uv pip check` | exit 0; all installed packages compatible |
| `uv tree --depth 2` | jsonschema 4.26.0, pytest 9.1.1; no cloud/runtime framework dependency |
| `uvx ruff check src tests evaluation` | blocked after 3 network retries; not reported as PASS |

The real run covered discovery, provider/model health, lifecycle, generation,
streaming, structured output and cancellation in addition to switching and
fallback. No test was deleted, newly skipped or xfailed. Prompts remained
synthetic engineering text only, and no cloud request was executed.

### 33.7 Frozen and Deferred Boundaries

- Frozen Contracts: `NOT MODIFIED`.
- Cloud fallback: `DISABLED`; production and test registries explicitly use
  `cloud_fallback=false`.
- Validated Runtime Version: `0.21.1`; API behavior was validated against the
  installed version.
- llama.cpp: `POC / PENDING`; no false integration claim is made.
- GPU Acceptance: `DEFERRED_BY_HARDWARE_AVAILABILITY`; the RTX 3060 eGPU was
  not connected and no GPU result is claimed.

### 33.8 Final Gate

The supplied Full PASS conditions are now met: module unit and real
integration tests pass, real model switching and real model-level fallback
pass, the full root suite passes, the external OpenAPI validator exits 0, no
root test was skipped or altered, frozen Contracts are unchanged, cloud
fallback is disabled, and the privacy boundary passes.

`PASS`

`LLM RUNTIME ROUND 1 = ACCEPTED. Eligible to proceed to Round 2. GPU Acceptance remains separately deferred.`

The closure evidence index is
[`LLM_RUNTIME_ROUND1_CLOSURE_EVIDENCE.md`](LLM_RUNTIME_ROUND1_CLOSURE_EVIDENCE.md).
