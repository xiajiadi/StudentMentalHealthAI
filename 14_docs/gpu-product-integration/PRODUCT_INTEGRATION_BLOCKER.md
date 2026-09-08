# Product Integration Blocker

ID: `GPI-BLOCKER-001`  
Severity: **P1 / hard-gate blocker for Full Pass**  
Status: **OPEN**

## Symptom

With the accepted Round 1 publication restored, all three synthetic normal product flows complete CAT and reach real RAG and the formal GPU Ollama path, but Backend returns HTTP 502. RuntimeService records:

```text
error_code: INVALID_STRUCTURED_OUTPUT
validation: json_parse
line: 26
column: 9
provider: ollama_gpu
provider_model: qwen2.5:7b-instruct-q4_K_M
retry: false
```

The three final traces are recorded in `12_evaluation/gpu-product-integration-closure-r1/logs/runtime-service-primary.jsonl`. The normal flow evidence records HTTP 502 for `GPI_NORMAL_01`, `GPI_NORMAL_02` and `GPI_NORMAL_03`.

## Reproduction boundary

The reproduction uses only synthetic data and the frozen product path:

1. Accepted publication hash: `2d5736ae741d675ca5856b8004665ea3043aeccea34e2b007498ff04c2b501a2`.
2. Real BGE-M3 + BM25S + RRF retrieval, reranker OFF.
3. Backend prompt: the existing product prompt builder; no source patch.
4. RuntimeService request config: `num_predict=384`, `temperature=0.1`, `top_p=0.9`, `seed=20260906`, `context_length=8192`.
5. Dedicated Ollama 0.33.3, exact Qwen2.5 7B Q4_K_M digest `845dbda0...b697e` on RTX3060.
6. Real RuntimeService structured-output validation.

## Independent comparison

[ollama_structured_output_diagnosis.jsonl](../../12_evaluation/gpu-product-integration-closure-r1/ollama_structured_output_diagnosis.jsonl) calls the same local model directly with the same schema, seed and context:

| Case | Response | Result |
| --- | --- | --- |
| Exact accepted chunk IDs | 700 chars; SHA-256 `0724991b...d2746d85` | JSON parse fails at line 26, column 9 |
| Neutral control chunk IDs | 533 chars; SHA-256 `f23a9d20...0ba57aa` | JSON parses as the required object |

This makes the failure reproducible and specific to the exact accepted prompt identity/structured-output interaction. It is not evidence that GPU was skipped: the formal Ollama endpoint returned HTTP 200 for all three product generation requests, and resource evidence verified the exact model and GPU allocation. It is also not a reason to substitute the D2 corpus.

## Impact

- Normal hard gate: `0/3`.
- Normal generated content: `0`.
- Normal citation identity round trip: not passable from failed normal responses.
- Crisis, controlled Output Safety, Safety-down and fallback gates remain independently evidenced.
- Closure status: `PARTIAL_PASS`; no candidate commit.

## Resolution boundary

The following would require a product-level decision and must not be applied silently in this closure:

- increase or otherwise redesign the structured-output budget;
- change the prompt/schema contract so source chunk identity does not cause invalid model output;
- add a validated RuntimeService repair/retry policy that preserves truthfulness and does not hide invalid output.

Any resolution must preserve the accepted RAG publication identity, keep real Output Safety in the path, rerun all three normal flows and citation round trip, and update the frozen technical decision if the contract changes. No acceptance-only workaround is recorded as a pass.
