# Runtime Service Reconstruction Round 1 — Controller Evidence

Date: 2026-09-07  
Engineering status: **ENGINEERING PASS — READY FOR CONTROLLER REVIEW**  
Controller status: **PENDING FINAL ACCEPTANCE**

This is a closure evidence package for the reconstructed RuntimeService. It is
not a Controller acceptance, does not create an accepted tag, and does not
authorize push, merge, deployment, or release.

## Scope and boundary

- Baseline: `contract-hardening-r1-accepted`
- Baseline commit: `66cb0e8a5eeecd05c8c5c1a3d0a3018a63920772`
- Candidate implementation commit: `6293144d921ea43c298327bd6a5063cd84e13b8b`
- Closure worktree: `D:\Projects\StudentMentalHealthAI-runtime-reconstruction`
- Main worktree: `D:\Projects\StudentMentalHealthAI`
- Root, Backend, Safety, RAG, Database, CAT, and Frontend source: unchanged
- Student data and credentials: not used

## Gate summary

| Gate | Current result |
|---|---|
| RTS decision fidelity | `52/52`, semantic deviations `0` |
| Pyright reconstructed scope | `0 errors, 0 warnings` |
| Ruff differential | baseline `79`, candidate `23`, new `0`, touched files `0` |
| Tests | `31 passed, 1 skipped`, explicit skip reconciled |
| Backend consumer | Existing `REAL_HTTP` client compatibility probe `PASS` |
| GPU RuntimeService smoke | `3/3` structured valid, exact model/digest, no fallback |
| Root Gate | `13` Python tests and OpenAPI validation pass |
| Frozen root hashes | all seven match baseline |
| Main preservation | clean before/after |

## Current GPU evidence

The formal smoke used the isolated Ollama `0.33.3` executable and model cache
under `D:\Dev\tools\StudentMentalHealthAI\gpu-acceptance`, bound only to
`127.0.0.1:11437`.

- Provider model: `qwen2.5:7b-instruct-q4_K_M`
- Digest: `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`
- GPU: NVIDIA GeForce RTX 3060, 12288 MiB, driver `596.36`
- Context: `8192`; KV: `f16`; parallel: `1`
- Runtime result: `3/3` strict structured responses, `fallback_used=false` on
  every request, actual provider model exact on every trace
- `ollama ps`: `100% GPU`, `CONTEXT 8192`
- `nvidia-smi`: CUDA compute process observed and GPU memory in use
- Ollama Runtime log: `D:\Dev\tools\StudentMentalHealthAI\gpu-acceptance\logs\runtime_service_gpu_smoke_20260907.stderr.log`
- Machine evidence: `12_evaluation/runtime-reconstruction-r1/runtime_reconstruction_gpu_smoke.json`

The managed process recorded PID/create-time ownership and stopped in
`STOPPED` state. No isolated Ollama or llama-server process remained after the
run.

## Static and test evidence

The exact commands, baselines, remaining legacy findings, and the one explicit
opt-in skip are documented in `PYRIGHT_RECONCILIATION.md`,
`RUFF_DIFFERENTIAL_RECONCILIATION.md`, and
`SKIPPED_TEST_RECONCILIATION.md`.

## Recommendation

The current evidence supports the engineering recommendation
`RUNTIME_RECONSTRUCTION_FULL_PASS_READY_FOR_CONTROLLER_REVIEW`.
Controller status remains `PENDING FINAL ACCEPTANCE`.
