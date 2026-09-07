# RuntimeService Reconstruction V1 — Design

Date: 2026-09-07
Status: `DESIGN BASELINE BEFORE IMPLEMENTATION`
Related: `RUNTIME_SERVICE_TECHNICAL_DECISION_V1.md`,
`RUNTIME_RECONSTRUCTION_REQUIREMENTS_MATRIX.md`

## 1. Component diagram

```text
FastAPI app (loopback only)
  lifespan
    startup / shutdown
        |
        v
  RuntimeService
    |-- RuntimeHealth / RuntimeState
    |-- ProviderRegistry ---- configured provider instances
    |       |-- OllamaProvider -> long-lived LocalHTTPClient -> 127.0.0.1 Ollama
    |       |-- LlamaCppProvider (disabled/deferred)
    |       `-- MockProvider (tests only)
    |-- ModelRegistry -------- logical -> provider -> exact model mapping
    |-- GenerationCoordinator - bounded concurrency and active cancellation
    `-- ManagedProcess or ExternalProcessBinding

Generation path:
  GenerationRequest
      -> registry resolution
      -> bounded acquire
      -> provider generate (buffered)
      -> provider-native schema + strict validation
      -> GenerationResult + RuntimeTrace + attempt evidence
      -> Backend/Safety consumes complete candidate
```

The Runtime never owns Prompt construction, risk interpretation, retrieval,
approval, publication, or browser streaming.

## 2. Module layout

```text
06_llm-runtime/src/llm_runtime/runtime/
  __init__.py       public runtime types
  coordinator.py    bounded generation capacity and cancellation registry
  health.py         runtime state machine and aggregate health snapshot
  process.py        explicit managed process and external binding
  registry.py       ProviderRegistry and provider definitions
  service.py        RuntimeService, fallback, trace and result orchestration
```

Existing `domain`, `providers`, `validation` and `observability` modules stay
the lower-level compatibility layer. No plugin loader, event bus, queue broker
or database persistence is introduced.

## 3. Class responsibilities

### RuntimeService

- resolves a request only through ModelRegistry and ProviderRegistry;
- starts/stops configured resources through the lifecycle boundary;
- performs non-generative readiness checks;
- applies bounded retry and explicit local fallback policy;
- buffers product candidates and creates truthful provenance;
- exposes internal normalized stream events and cancellation;
- never marks a candidate safe, approved, or clinically meaningful.

### ProviderRegistry

- owns provider ID, type, endpoint, enabled state, process mode and provider
  instance;
- validates configured loopback endpoints;
- prevents duplicate IDs and request-time provider selection;
- starts/stops only managed process bindings;
- closes provider clients at shutdown.

### ModelRegistry

- owns logical/contract/provider identity and deterministic order;
- rejects duplicate IDs and `latest` identities;
- exposes an explicit fallback chain and skips disabled/non-local targets;
- reconciles provider discovery into model provenance without inventing digest.

### GenerationCoordinator

- holds one bounded semaphore by default;
- rejects unbounded waiting after `acquire_timeout_seconds`;
- records active request → provider for cancellation;
- releases capacity on every normal/error/cancel path.

### RuntimeHealth

- accepts only legal state transitions;
- separates process liveness from dependency/model readiness;
- returns safe provider/model/process metadata without prompt/output bodies.

### ManagedProcess / ExternalProcessBinding

- `ManagedProcess` owns a configured child tree and its log files;
- `ExternalProcessBinding` is descriptive only and never stops an external
  process;
- process termination verifies PID and creation time before acting.

## 4. Process modes

| Mode | Start | Health | Stop | Ownership |
|---|---|---|---|---|
| `EXTERNAL` | no | yes | close client only; never terminate endpoint | false |
| `MANAGED` | configured argument list, `shell=False` | yes | bounded owned-tree stop | true |

The normal CLI configuration uses external local Ollama. Managed mode is a
tested seam for a harmless child process and is not enabled by HTTP request
data.

## 5. Runtime state machine

```text
STOPPED --startup--> STARTING --all required checks pass--> READY
                         |                                  |
                         |                                  +--> DEGRADED
                         v                                  |
                       FAILED <------------------------------+
                         ^                                      |
                         |                                      v
STOPPING <----------- READY / DEGRADED ----------------------
   |
   +-------------------------------> STOPPED
```

Legal transitions are enforced. An unavailable optional provider can leave
the runtime `READY` when the configured primary use case is ready. An
unavailable primary with a usable local fallback is `DEGRADED`; no healthy
local target is `FAILED`.

## 6. Registry design

Provider definitions are constructed from trusted configuration at process
startup. A request contains a logical model ID only. The service resolves:

```text
logical_model_id
  -> ModelEntry.provider
  -> ProviderRegistry.resolve(provider_id)
  -> ModelEntry.provider_model_id
```

`GenerationRequest.provider_model_id` is not allowed to override the registry
mapping in the service path. It remains a provider-level compatibility field
for direct adapter tests.

Each model target carries:

- logical and Contract IDs;
- exact provider model name;
- priority/order, enabled state, fallback eligibility;
- provider, local-only flag and expected digest;
- context limit and structured-output capability where defined.

No filesystem plugin scan, arbitrary import, arbitrary endpoint, or cloud
provider entry exists.

## 7. Fallback algorithm

```text
candidates = [requested] + explicit fallback_model_id chain
for candidate in candidates:
    if candidate disabled/non-local/provider missing:
        record NOT_RUN attempt and continue only where policy permits
    for same-target attempt in [0, 1] according to configured max_attempts:
        acquire one generation slot
        call provider.generate(candidate)
        if success:
            return complete buffered GenerationResult
        record attempt without prompt/output
        if error is retryable and no output has started and retry remains:
            bounded backoff; retry same candidate
            continue
        break
    if error is fallback-eligible and no partial output:
        record fallback reason and continue to next candidate
    raise stable error; never conceal cancellation/schema/config errors
raise FALLBACK_EXHAUSTED with safe attempt summary
```

The current module configuration permits at most two attempts on a target. A
stream that already emitted a delta is never retried or concatenated with a
second candidate. Cloud candidates are rejected before execution.

## 8. Error taxonomy

The implementation preserves existing values such as `REQUEST_TIMEOUT`,
`MODEL_NOT_FOUND`, `PROVIDER_NOT_READY`, `STREAM_INTERRUPTED`,
`INVALID_STRUCTURED_OUTPUT` and `CANCELLED`, and adds stable equivalent
semantics for:

```text
RUNTIME_NOT_READY       RUNTIME_BUSY
PROVIDER_UNAVAILABLE    PROVIDER_TIMEOUT
PROVIDER_PROTOCOL_ERROR MODEL_NOT_FOUND
MODEL_UNAVAILABLE       CONTEXT_LIMIT_EXCEEDED
STRUCTURED_OUTPUT_INVALID (alias of INVALID_STRUCTURED_OUTPUT)
GENERATION_CANCELLED       (alias of CANCELLED)
GENERATION_FAILED        FALLBACK_EXHAUSTED
PROCESS_START_FAILED     PROCESS_EXITED
PROCESS_STOP_FAILED      CONFIGURATION_ERROR
```

Public errors include code, retryable, provider-safe status and bounded
details. They never include a stack trace, prompt, full output, credential or
student record.

## 9. Structured-output path

```text
Pydantic model (optional helper)
    -> model_json_schema()
JSON Schema mapping
    -> Ollama `format` / llama-server `response_format`
complete text
    -> JSON parse
    -> Draft 2020-12 validation
    -> optional Pydantic model_validate_json
    -> ProviderResponse.structured / GenerationResult
```

No fenced-text extraction, regex patching, prose stripping or silent success
is allowed. A schema failure is not a fallback trigger.

## 10. Streaming and buffering

Providers may stream internally as normalized `START`, `DELTA`, `USAGE`,
`DONE`, `ERROR` and `CANCELLED` events. `RuntimeService.stream_generate` is an
internal diagnostic iterator used by CLI/tests. The product HTTP endpoint
accepts only buffered generation and does not send any provider event to a
browser/student.

The internal stream path maintains an ephemeral buffer for metrics/validation;
on error, cancellation, timeout or incomplete terminal event, the buffer is
discarded. No partial candidate is persisted or returned as final output.

## 11. Cancellation path

1. Register request ID and provider before generation/stream iteration.
2. `RuntimeService.cancel(request_id)` resolves the registered provider and
   calls its cancellation hook.
3. Ollama closes the active local stream; cancellation is normalized to a
   terminal `CANCELLED` event without `DONE`.
4. Coordinator capacity is released in `finally`.
5. FastAPI task cancellation calls the same hook when the synchronous provider
   call is running in a worker thread.

Non-stream provider cancellation is best effort because the surviving sync
provider port does not expose a portable interrupt handle; the bounded HTTP
timeout remains the hard upper bound.

## 12. Startup and shutdown lifecycle

### Startup before `yield`

1. Set `STARTING` and load trusted configuration.
2. Construct registries, providers and process bindings once.
3. Start only configured managed processes.
4. Run provider `/api/version` and non-generative model discovery/readiness.
5. Optionally preload only when explicit `preload_primary=true` is configured.
6. Set `READY`, `DEGRADED` or `FAILED` with a safe health snapshot.

### Shutdown after `yield`

1. Set `STOPPING` and reject new work.
2. Ask active providers to cancel active requests.
3. Wait only within the configured shutdown bound.
4. Close long-lived provider clients.
5. Stop only managed owned trees; never terminate external Ollama.
6. Verify owned process exit and set `STOPPED`.

## 13. Concurrency

The default `max_generation_concurrency=1` protects local model residency and
the accepted GPU scheduler assumption. A finite acquire timeout returns
`RUNTIME_BUSY`. There is no unbounded queue and no automatic worker scaling.

## 14. Security boundary

- loopback-only endpoints and app bind;
- no request-time endpoint/executable/provider selection;
- no shell command strings or PowerShell wrappers;
- no broad process-name kill;
- no cloud fallback;
- no raw prompt/output logs;
- no hidden reasoning exposure;
- no real student data or clinical claims.

## 15. Compatibility mapping

| Existing surface | Reconstruction behavior |
|---|---|
| `RuntimeService(registry, providers, hardware=..., backoff_seconds=...)` | constructor remains valid |
| `service.generate(request)` | returns `GenerationResult` with `.text`, `.response`, `.actual_model_id`, `.trace` |
| `service.stream_generate(request)` | normalized internal iterator |
| `service.cancel(request_id)` | provider cancellation hook |
| `service.discover/health/list_models/load_model/unload_model` | existing CLI/integration methods |
| `llm_runtime.runtime.process.ManagedProcess` | new explicit managed process seam |
| `/internal/llm/generations` | preserved |
| `/internal/llm/generate` and `/internal/llm/models` | added from integration decision as module-local aliases |
| Backend | untouched; current compatibility is tested as a consumer boundary |
| Root Contract/OpenAPI | untouched and hash-checked |
