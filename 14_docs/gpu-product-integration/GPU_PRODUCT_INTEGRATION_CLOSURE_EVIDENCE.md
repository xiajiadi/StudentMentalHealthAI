# GPU Product Integration Closure Evidence

## Machine result

Final status: **`PARTIAL_PASS`**  
Machine record: [gpu_product_integration_closure_evaluation.json](../../12_evaluation/gpu-product-integration-closure-r1/gpu_product_integration_closure_evaluation.json)

| Gate | Result | Evidence |
| --- | --- | --- |
| Baseline / branch / isolated worktree | PASS | `environment_manifest.json` |
| Realness | PASS | Backend, CAT, RAG, Runtime, Ollama, Safety, OPA and MySQL all labelled REAL; ContractFake count 0 |
| Accepted RAG boundary | PASS | `synthetic_rag_boundary.json`; hash `2d5736ae...b501a2` |
| Dedicated GPU Ollama | PASS for resource identity | 0.33.3, exact digest, Q4_K_M, context 8192, `size_vram == size` in `gpu_resource_ownership.json` |
| Safety readiness | PASS | Qwen3Guard, NeMo, Presidio, OPA and human review all ready |
| CAT regression | PASS | `24 passed in 21.79s` |
| Knowledge regression | PASS | `18 passed, 2 warnings in 25.36s` |
| RAG regression | PASS | `18 passed, 4 skipped, 3 warnings in 2.28s` |
| Runtime regression | PASS | `31 passed, 1 skipped, 2 warnings in 1.77s` |
| Safety regression | PASS | `20 passed, 1 skipped, 3 warnings in 13.00s` |
| Backend regression | PASS | `16 passed in 4.41s` |
| Database regression | PASS | `10 passed, 6 skipped in 0.18s` |
| Root contract / OpenAPI gate | PASS | 13 contract tests and OpenAPI validation passed |
| Frozen root integrity | PASS | 8/8 hashes unchanged; `frozen_root_hashes_after.json` |
| Normal product flow | FAIL hard gate | 0/3; all three returned HTTP 502 after RuntimeService structured-output rejection |
| Normal citation round trip | NOT PASS | depends on generated normal content; `citation_roundtrip.json` |
| Crisis | PASS | 3/3; zero normal RAG/Runtime/Ollama/GPU generation calls |
| Controlled Output Safety | PASS | real PROMPT_INJECTION fixture blocked; no delivery or approved-output persistence |
| Safety-down | PASS | 2/2 HTTP 503 fail-closed; zero RAG/Runtime/Ollama calls |
| Product fallback | PASS | 3/3 local CPU fallback through full product path and Output Safety |
| Cleanup | PASS | explicit PID cleanup, `cleanup.json`, acceptance ports free |

## Required identity

- Primary model: `qwen2.5:7b-instruct-q4_K_M`
- Primary digest: `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`
- Ollama: `0.33.3`
- Formal context: `8192`
- KV cache: `f16`
- Parallel: `1`
- GPU: NVIDIA GeForce RTX 3060, 12 GB
- Safety Qwen3Guard revision: `fada3b2f655b89601929198343c94cd2f64d93cc`
- MySQL: `8.4.8`, migration head `20260906_0002`
- Real student data: none

## Current blocker

The exact accepted RAG publication changes the Backend prompt chunk identities. A body-blind live trace shows real RAG success and real GPU Ollama HTTP 200, followed by RuntimeService `INVALID_STRUCTURED_OUTPUT` (`json_parse`, line 26, column 9) for all three normal flows. The controlled local Ollama comparison is recorded in [ollama_structured_output_diagnosis.jsonl](../../12_evaluation/gpu-product-integration-closure-r1/ollama_structured_output_diagnosis.jsonl): exact IDs fail deterministically, neutral control IDs pass. See [PRODUCT_INTEGRATION_BLOCKER.md](PRODUCT_INTEGRATION_BLOCKER.md).

## Privacy and source scope

Observer logs record method, path, lengths, hashes and semantic summaries only; raw request/response bodies are absent. No secrets or real student data were used. Product source directories and frozen root files are unchanged. No commit, push, merge or tag was created.
