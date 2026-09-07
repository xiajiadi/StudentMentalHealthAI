# RuntimeService Reconstruction V1 — Technical Decision

Status: `FROZEN FOR THIS RECONSTRUCTION ROUND`
Date: 2026-09-07
Baseline: `contract-hardening-r1-accepted` (`66cb0e8a5eeecd05c8c5c1a3d0a3018a63920772`)
Scope: `06_llm-runtime` source plus reconstruction evidence under `12_evaluation` and `14_docs`

## Decision

Build a new, small `RuntimeService Reconstruction V1`. The implementation is
not a historical restoration. The accepted evidence proves intended behavior
but no recoverable source lineage; current source is the Provider/Domain layer
and the missing orchestration layer is reconstructed from the evidence matrix.

The service remains a local-only orchestration boundary:

```text
FastAPI lifespan
    -> RuntimeService
        -> ProviderRegistry
        -> ModelRegistry
        -> GenerationCoordinator
        -> RuntimeHealth
        -> ManagedProcess / ExternalProcessBinding
            -> existing provider adapters
```

## Frozen choices for this round

1. Ollama remains the primary local provider. The existing native adapter is
   preserved; only a minimal HTTP-client lifecycle correction is permitted so
   that the provider can own one long-lived loopback client and close it.
2. `cloud_fallback` is explicitly `false`. No cloud provider is registered and
   no request value can select a provider or endpoint.
3. Model selection is registry-only. Logical model IDs resolve to a configured
   provider and exact provider model name. `latest` is rejected as a formal
   production identity.
4. Fallback is explicit, local, ordered, and bounded. A same-target retry is
   permitted only for the existing accepted transient policy: at most one
   retry after a retryable pre-output failure. No mid-stream retry or fallback
   is performed after a delta.
5. Product generation is buffered. `stream_generate` is an internal normalized
   diagnostic interface; the HTTP product surface rejects `stream=true`.
6. Structured output uses the provider-native JSON Schema field and then strict
   JSON Schema/Pydantic validation. Invalid output is a failure and is never
   repaired into success.
7. Runtime process ownership is explicit: `EXTERNAL` is never terminated by
   this service; `MANAGED` is spawned from a configured argument list and only
   its verified process tree may be stopped.
8. Runtime concurrency defaults to one generation and has a finite acquire
   timeout. The service uses a single-worker assumption; no watchdog, queue
   broker, or implicit parallel model runner is introduced.
9. FastAPI uses one lifespan context. Startup constructs/starts configured
   resources and performs non-generative readiness checks; shutdown cancels
   active work, closes providers, and stops only owned processes.
10. Root Contracts, Backend, Safety, RAG, and other module source remain
    read-only in this round.

## Accepted compatibility decisions

The historical Round 1 report and current official unit test require one
bounded retry for a transient pre-stream timeout. This is retained as an
explicit policy, not a blind retry loop. The reconstruction evidence records
this as a resolved conflict against the stricter candidate default of zero
same-target retries.

The integration decision names `/internal/llm/generate` and
`/internal/llm/models`; the surviving API exposes the plural
`/internal/llm/generations`. The reconstruction keeps the existing route as a
compatibility alias and adds the singular module-local route plus models
inventory. Neither route changes the frozen root API.

## Non-goals

- historical source recovery;
- LiteLLM, a gateway, cloud routing, load balancing, or arbitrary plugins;
- rewriting Ollama or replacing it with `ollama-python`;
- backend wiring, Safety policy, RAG behavior, clinical interpretation, or
  real student data;
- an infinite process watchdog or GPU benchmark matrix;
- claiming GPU acceptance when the narrow smoke is not executed in this
  worktree.

## Acceptance interpretation

The final report may recommend `RUNTIME_RECONSTRUCTION_ENGINEERING_PASS_READY_FOR_CONTROLLER_REVIEW`
only when every required gate is supported by current evidence. Missing real
Ollama, fallback, or GPU evidence remains `PARTIAL_PASS`; it is not converted
to a synthetic pass.
