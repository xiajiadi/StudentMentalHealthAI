# LLM Runtime Service Reconstruction Round 1 — Human Evidence

Date: 2026-09-07

Runtime-service result: **PASS** for the reconstructed Round 1 surface.

Project-level result: **PARTIAL PASS** because the existing full-module Ruff
surface is not clean and no real llama-server GPU run was available.

## Boundary and provenance

- Baseline: `contract-hardening-r1-accepted`
- Baseline commit: `66cb0e8a5eeecd05c8c5c1a3d0a3018a63920772`
- Branch: `exp/llm-runtime-service-reconstruction-v1`
- Worktree: `D:\Projects\StudentMentalHealthAI-runtime-reconstruction`
- Main worktree: `D:\Projects\StudentMentalHealthAI`; verified clean before and after the run.
- Historical runtime source was not recovered. The implementation is explicitly a
  reconstruction from surviving interfaces, tests, frozen contracts, integration
  decisions, and upstream references.
- No student data, credentials, or private source was used. All prompts in the
  real integration run were synthetic engineering prompts.

## Implemented surface

The worktree now contains:

- `RuntimeService` with lifecycle state, health/readiness, bounded generation,
  retry policy, local-only fallback, structured-output validation, cancellation,
  trace provenance, and buffered result envelopes.
- `ManagedProcess` with explicit argv execution, loopback binding metadata,
  PID/create-time ownership checks, descendant termination, bounded shutdown,
  and no executable-name or broad task-kill behavior.
- `ProviderRegistry` and `ModelRegistry` boundaries with loopback endpoint
  validation, disabled/local-only checks, explicit fallback chains, and no
  `:latest` identity.
- Pooled, `trust_env=False` HTTPX transport with finite component timeouts and
  idempotent cross-thread stream close behavior.
- FastAPI lifespan startup/shutdown, `/internal/llm/models`, singular and
  compatibility plural buffered generation routes, and readiness reporting.
- Native Ollama structured schema forwarding and strict post-generation
  validation; no Markdown-fence or prose repair.
- CPU/GPU detection corrected to use valid `nvidia-smi` query fields. The
  machine reports an RTX 3060 with 12 GiB VRAM and driver 596.36.

## Verification evidence

| Check | Result | Evidence |
|---|---|---|
| Official plus reconstruction tests | `31 passed, 1 skipped` | `uv run --frozen pytest -q` |
| Reconstruction targeted Ruff | Pass | `uvx ruff check src/llm_runtime/runtime src/llm_runtime/api/app.py src/llm_runtime/hardware/detector.py tests/test_runtime_reconstruction.py` |
| Compile check | Pass | `uv run --frozen python -m compileall -q src tests` |
| Real Ollama integration | `3 passed` | `06_llm-runtime/artifacts/ollama_integration.json`, `real_model_switching.json`, `real_fallback.json` |
| Root contract Python tests | `13 passed` | First stage of `00_architecture/tests/run_contract_checks.ps1` |
| Root OpenAPI validator | Pass | Validator installed only into the ignored backend test environment; the root Gate completed successfully |
| Full module Ruff | Partial | 74 legacy findings remain outside the targeted reconstructed surface |
| Main worktree boundary | Pass | `git -C D:\Projects\StudentMentalHealthAI status --porcelain` was empty |
| Temporary server cleanup | Pass | No `ollama` process remained after the managed run |

## Real Ollama evidence

The integration suite used a temporary `ManagedProcess` bound to
`http://127.0.0.1:11434`, with the existing `OLLAMA_MODELS` cache at
`D:\Dev\caches\ollama-models`. The process was stopped through the ownership
aware runtime boundary after the suite.

| Logical identity | Provider identity | Digest | Result |
|---|---|---|---|
| `qwen2.5-0.5b-engineering` | `qwen2.5:0.5b` | `a8b0c51577010a279d933d14c2a8ab4b268079d44c5c8830c0a93900f1827c67` | success |
| `qwen2.5-1.5b-engineering-fallback` | `qwen2.5:1.5b` | `65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b` | success |

Observed behaviors:

- Ollama version `0.21.1`, provider liveness/readiness pass.
- Buffered generation returned non-empty output for both registered models.
- Native structured output returned `{"answer":"OK"}` and passed strict validation.
- Stream ended with `DONE`; cancellation ended with `CANCELLED` and no `DONE`.
- Controlled missing provider model `smhai-acceptance-missing-model:round1`
  normalized to `MODEL_NOT_FOUND`, then selected the registered 1.5B local
  fallback. Trace provenance recorded the primary error, actual model, digest,
  and two attempts.

## Frozen artifact fingerprints

These hashes match the accepted baseline:

| File | SHA-256 |
|---|---|
| `CONTRACTS.md` | `8064776EDEB9277DEA212C4B18C83FA8684E7EF505910732CCB70075B2BE423A` |
| `00_architecture/openapi.v1.json` | `AFF8BF040EF90455CECD7DF9962344F0FA9C9E8017B03186068BEB88F42C4E89` |
| `00_architecture/schemas/assessment.v1.schema.json` | `2D5B5CBD232670CFE6653BA86726E012E4A096874FF4E4CE09A3209344CB4FB9` |
| `00_architecture/schemas/knowledge.v1.schema.json` | `B1ABBB93A6563162C44BC29C2D4570608F91756B58309E753DEB7DF9D087841D` |
| `00_architecture/schemas/generation.v1.schema.json` | `52497665C543267ACF1840E5CCE7E74A2A407C57ECF130E18D35300DC099B0D1` |
| `00_architecture/schemas/config.v1.schema.json` | `2541EB5EFAA4E02B30F16771C3AF13397CD22EC4A0C7EA7363C778A222B70824` |
| `00_architecture/schemas/logging.v1.schema.json` | `A5965C8B327185043C9D68A7165D0A7AA3F68BB837643FFA6BBA74F6C9B76D1C` |

## Limits and deferred work

- The runtime Round 1 surface and root contract Gate are accepted locally; the
  project-level result remains partial for the separate Ruff/GPU limitations.
- Full Ruff cleanup is outside this reconstruction scope; the targeted changed
  surface is clean.
- No real llama-server binary or GPU-serving acceptance run was available.
- The generated JSON files under `06_llm-runtime/artifacts/` are local run
  artifacts ignored by the module policy; the durable summary is the machine
  evaluation JSON in this directory.
