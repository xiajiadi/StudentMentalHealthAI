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

The final report may recommend `RUNTIME_RECONSTRUCTION_FULL_PASS_READY_FOR_CONTROLLER_REVIEW`
only when every required gate is supported by current evidence. Missing real
Ollama, fallback, or GPU evidence remains `PARTIAL_PASS`; it is not converted
to a synthetic pass. The recommendation is not a Controller `ACCEPTED` status.

## Controller-Frozen Decision Register — RTS-01..RTS-52

The following register is the materialized decision source for this closure.
The numbering and substance are preserved exactly so that implementation,
tests, and evidence can be reconciled without reopening the architecture.

1. RTS-01 — This Round is a Reconstruction and must not be described as restoration of historical Runtime source.
2. RTS-02 — Formal baseline is `contract-hardening-r1-accepted`.
3. RTS-03 — Use an independent Runtime Reconstruction branch/worktree.
4. RTS-04 — Tests are one Requirements Evidence source, not the sole Source of Truth.
5. RTS-05 — A multi-source Requirements Matrix is mandatory.
6. RTS-06 — Preserve the existing accepted Ollama Provider; do not rewrite it without a concrete compatibility reason.
7. RTS-07 — RuntimeService is an orchestration layer and does not reimplement the Ollama protocol.
8. RTS-08 — ProviderRegistry and ModelRegistry are separate responsibilities.
9. RTS-09 — Registries are explicit/config-driven; no dynamic plugin scanning.
10. RTS-10 — Formal model identities must not use ambiguous `latest`.
11. RTS-11 — Primary/fallback execution must record truthful actual provider/model identity.
12. RTS-12 — `cloud_fallback=false`.
13. RTS-13 — Fallback is restricted to explicitly registered local targets.
14. RTS-14 — Fallback ordering is deterministic.
15. RTS-15 — Only operational failures are fallback-eligible by default.
16. RTS-16 — Safety/policy/invalid-request failures must not trigger model fallback.
17. RTS-17 — Structured-output validation failure must not silently trigger model fallback.
18. RTS-18 — No blind retry.
19. RTS-19 — Any retry must be bounded and evidence-backed.
20. RTS-20 — Every retry/fallback attempt must leave auditable trace evidence.
21. RTS-21 — Provider exceptions map to a stable Runtime error taxonomy.
22. RTS-22 — FastAPI uses lifespan for Runtime startup/shutdown.
23. RTS-23 — One RuntimeService instance per service process.
24. RTS-24 — V0.9 Runtime HTTP service assumes a single worker.
25. RTS-25 — Provider HTTP clients are long-lived/lifespan-scoped.
26. RTS-26 — Local provider HTTP traffic uses `trust_env=false`.
27. RTS-27 — Connect/read/write/pool timeouts are finite and explicit.
28. RTS-28 — Runtime HTTP service is loopback-only.
29. RTS-29 — Normal requests cannot inject arbitrary provider endpoints or executables.
30. RTS-30 — Process modes are explicitly EXTERNAL or MANAGED.
31. RTS-31 — RuntimeService never terminates an EXTERNAL process.
32. RTS-32 — MANAGED process ownership records PID + creation time + ownership identity.
33. RTS-33 — Process launch uses `shell=False`.
34. RTS-34 — Windows managed-process handling uses safe process group/tree semantics.
35. RTS-35 — Shutdown attempts graceful bounded termination before killing owned descendants.
36. RTS-36 — Broad process-image kill such as `taskkill /IM ollama.exe /F` is prohibited.
37. RTS-37 — No infinite watchdog/restart loop.
38. RTS-38 — Unexpected provider/process exit transitions Runtime into explicit FAILED/DEGRADED semantics.
39. RTS-39 — Ollama readiness uses control-plane checks such as version/tags/model availability and does not generate text.
40. RTS-40 — Model loading/unloading uses Ollama-native `keep_alive` semantics.
41. RTS-41 — Structured output uses provider-native JSON Schema.
42. RTS-42 — Pydantic schema/validation is the canonical structured-output model source.
43. RTS-43 — Regex/Markdown-fence/prose JSON repair is not accepted as successful structured output.
44. RTS-44 — Thinking/reasoning is disabled/not exposed by default and must not be persisted as product content.
45. RTS-45 — Product generation produces a fully buffered candidate before downstream Safety evaluation.
46. RTS-46 — Internal provider streaming may exist, but must not stream raw tokens directly to Student/Browser.
47. RTS-47 — Partial candidate from cancel/error/incomplete stream is discarded.
48. RTS-48 — After output has started, Runtime does not automatically switch to a fallback model.
49. RTS-49 — Default generation concurrency = 1.
50. RTS-50 — Runtime logs model/provider/fallback/metrics/status metadata, but does not log full prompt/output by default.
51. RTS-51 — This Round does not modify Root Contract, Backend, Safety, RAG, Database or Frontend source.
52. RTS-52 — Only Project Controller may grant ACCEPTED status or create accepted tags.

Materialization result: `52/52` decisions present. The supplementary
compatibility decisions above this register remain subordinate to RTS-01..52
and are reconciled in `RUNTIME_DECISION_FIDELITY_RECONCILIATION.md`.
