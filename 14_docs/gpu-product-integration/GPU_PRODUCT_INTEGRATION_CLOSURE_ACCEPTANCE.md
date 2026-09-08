# GPU Product Integration Closure Acceptance

## Controller disposition

**PARTIAL_PASS — controller review required.**

The closure evidence proves the real service composition, accepted synthetic RAG boundary, dedicated RTX3060 Ollama resource ownership, real Safety behavior, fail-closed Safety-down behavior, local CPU fallback, MySQL persistence, module regressions and frozen-root integrity. It does not qualify for Full Pass because the mandatory normal product gate is `0/3`.

## Acceptance checklist

- [x] Baseline `2972be77e537ef03033332039a6ed0eed8e451ef`.
- [x] Isolated branch and worktree.
- [x] Main checkout preserved.
- [x] Accepted Round 1 publication restored; D2 candidate not used.
- [x] Real Backend, CAT, RAG, RuntimeService, Ollama, Safety, OPA and MySQL composition.
- [x] Dedicated formal model and exact digest verified.
- [x] Three crisis flows with zero normal generation calls.
- [x] Real Output Safety controlled fixture blocked and not delivered.
- [x] Two Safety-down requests failed closed.
- [x] Three local CPU fallback product flows passed.
- [x] CAT, Knowledge, RAG, Runtime, Safety, Backend and Database regressions passed.
- [x] Root contract/OpenAPI gate passed.
- [x] Frozen root hashes unchanged.
- [ ] Three normal flows pass with generated grounded content.
- [ ] Normal citation identity round trip passes.
- [ ] Full Pass status and candidate commit.

## Blocking decision

Do not create a candidate commit from this round. The blocker is not resolved by changing the accepted publication, reducing the RAG result, bypassing Output Safety, or replacing RuntimeService with a fake. A product owner/controller must decide whether to address the structured-output budget/prompt/schema interaction in product code while preserving the frozen RAG identity.

After that product-level decision and implementation, rerun the normal 3/3 gate, citation round trip, full live flow and relevant regressions. Only then may the controller reconsider Full Pass and the one-time local candidate commit.

## Evidence index

- Machine evaluation: `12_evaluation/gpu-product-integration-closure-r1/gpu_product_integration_closure_evaluation.json`
- Normal flows: `12_evaluation/gpu-product-integration-closure-r1/full_real_normal_flows.json`
- Crisis flows: `12_evaluation/gpu-product-integration-closure-r1/full_real_crisis_flows.json`
- Safety-down: `12_evaluation/gpu-product-integration-closure-r1/safety_down_results.json`
- Fallback: `12_evaluation/gpu-product-integration-closure-r1/product_fallback_results.json`
- Resource ownership: `12_evaluation/gpu-product-integration-closure-r1/gpu_resource_ownership.json`
- Root hashes: `12_evaluation/gpu-product-integration-closure-r1/frozen_root_hashes_before.json` and `frozen_root_hashes_after.json`
