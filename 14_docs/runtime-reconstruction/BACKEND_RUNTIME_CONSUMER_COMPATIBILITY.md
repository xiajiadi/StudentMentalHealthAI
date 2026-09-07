# Backend Runtime Consumer Compatibility — R1

Date: 2026-09-07  
Backend source policy: read-only  
Probe result: `PASS`

## Boundary exercised

The existing Backend consumer `smhai_backend.integrations.llm.HttpLLMRuntimeClient`
was run without source modification. It used its existing `REAL_HTTP` label and
loopback client configuration to call:

```text
POST http://127.0.0.1:8161/internal/llm/generations
GET  http://127.0.0.1:8161/health/ready
```

The Runtime endpoint was a temporary process using the reconstructed FastAPI
application and a clearly marked synthetic MockProvider behind the configured
`ollama` registry slot. This isolates the consumer contract from model quality.

Observed result:

- Backend health projection returned `READY`.
- The existing client returned `CandidateResponse.label = REAL_HTTP`.
- The buffered response contained the required structured keys
  `summary`, `observations`, `suggestions`, and `disclaimer`.
- Model identity was `MODEL_local_cpu_test` and Runtime version was
  `runtime-backend-probe-0.1.0`.
- The request used `stream=false`, the existing plural route, and synthetic
  fixture metadata only.
- The temporary Runtime process was stopped by its exact PID; no listener
  remained on port 8161.

Machine-readable evidence: `12_evaluation/runtime-reconstruction-r1/backend_runtime_consumer_compatibility.json`.

No file under `09_backend` was modified relative to the formal baseline.
