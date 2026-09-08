# GPU Product Integration Final Closure Evidence

Status: **GPU_PRODUCT_INTEGRATION_FULL_PASS_READY_FOR_CONTROLLER_REVIEW**
Round: `STRUCTURED_OUTPUT_PRODUCT_COMPATIBILITY_CLOSURE_R1`

This document records the evidence after the minimal structured-output product
compatibility fix. It is a Controller handoff, not an Accepted/merged/released
verdict.

## 1. Original PARTIAL PASS

The preserved GPI Round 1 evidence was `PARTIAL_PASS`. The original blocker was
Normal product generation: the exact accepted RAG publication and product prompt
reached the formal GPU Runtime/Ollama path, which returned HTTP 200 followed by
malformed JSON and `INVALID_STRUCTURED_OUTPUT`. Normal product was 0/3 in that
round; crisis, safety-down, controlled safety and CPU fallback evidence remained
valid.

The partial evidence was checkpointed locally as commit
`e31d44423dd64592c11320b98b063eb90bdd8268` on the preserved GPI branch.

## 2. Structured Output Blocker

The exact product-shaped prompt failed deterministically in 3/3 direct/runtime
reproductions with `num_predict=384`:

- HTTP status: `200`;
- response length: `700`;
- JSON parse: line `26`, column `9`;
- `done=true`, `done_reason=length`, `eval_count=384`;
- RuntimeService error: `INVALID_STRUCTURED_OUTPUT`;
- provider parser replay: failed on the same bytes.

The response ended inside the second suggestion's `source_chunk_ids` array.

## 3. Root Cause

Root cause class: `OUTPUT_TRUNCATION`. The owning product module is
`09_backend/src/smhai_backend/integrations/llm.py`, in
`HttpLLMRuntimeClient`'s request configuration. The product hard-coded
`max_output_tokens=384`, which was below the deterministic completion required
by the exact accepted-provenance prompt.

The budget ladder was:

| `num_predict` | Result |
| ---: | --- |
| 384 | FAIL / `length` / 384 tokens |
| 512 | FAIL / `length` / 512 tokens |
| 640 | FAIL / `length` / 640 tokens |
| 768 | PASS / `stop` / 742 tokens |
| 1024 | PASS / `stop` / 742 tokens |

No transport corruption or schema mismatch was found.

## 4. Minimized Reproducer

`12_evaluation/structured-output-compat-r1/minimized_reproducer.json` records
the before/after boundary. It proves the exact accepted publication, exact
product prompt, native schema and formal model fail at 384 and pass at 768.

Raw request/response payloads remain under the ignored local-only
`_local-evidence/structured-output-compat/` directory. Committed evidence keeps
hashes, lengths, termination metadata and limited excerpts only.

## 5. Fix Scope

The product change is one configuration value:

```text
09_backend/src/smhai_backend/integrations/llm.py
config.max_output_tokens: 384 -> 768
```

The added Backend regression test covers both sides of the structural boundary:
truncated JSON is rejected, while the current exact accepted chunk identities
produce a valid `GenerationContent` object at the configured budget.

No RAG, Safety, RuntimeService, CAT, Database, Frontend or frozen-root source
was changed.

## 6. Why Rejected Workarounds Were Rejected

No generic JSON repair, regex extraction, first-object extraction, malformed JSON
acceptance, schema weakening, blind retry, model switch, CPU-as-primary switch,
cloud fallback, citation disabling or neutral-ID substitution was used.

Prompt/evidence serialization and citation projection were not needed: the
minimal provider-request budget fix resolved the failure while preserving exact
external provenance identity.

## 7. Exact Provider Compatibility

Formal direct-provider check: **3/3 PASS**.

All runs used Ollama `0.33.3`, model
`qwen2.5:7b-instruct-q4_K_M`, digest
`845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`, context
`8192`, KV `f16`, parallel `1`, seed `20260906`, temperature `0.1`, top-p `0.9`,
and `num_predict=768`. Each returned valid structured output with required keys
`summary`, `observations`, `suggestions` and `disclaimer`, exact accepted
`source_chunk_ids`, and `finish_reason=stop`.

Evidence: `12_evaluation/structured-output-compat-r1/post_fix_compatibility.json`.

## 8. RuntimeService Compatibility

Formal RuntimeService check: **3/3 PASS**. Each result was structured-valid,
used the formal GPU provider/model/digest, had `fallback_used=false`, and ended
with `finish_reason=stop`. Six transport generations were observed across the
three direct and three RuntimeService checks.

## 9. Normal 3/3

The existing full-real GPI harness recorded **Normal 3/3**. All three flows were
HTTP 202 generated responses with content present, `generation_status=EXECUTED`,
`candidate_source=MODEL_EXECUTED`, and the formal local GPU model identity.

## 10. Normal Real RAG

All three Normal flows performed one real RAG request and returned accepted
publication provenance. The service reported hybrid retrieval with BGE-M3 and
BM25S, reranker disabled, corpus version
`sha256:4553317e36b1064880df01643a3171f7937e0ec420ead380c5d6702f2396aad2`, and
14 eligible chunks. The accepted publication SHA-256 remained
`2d5736ae741d675ca5856b8004665ea3043aeccea34e2b007498ff04c2b501a2`.

## 11. Normal GPU Correlation

Each Normal flow has a non-null trace, request, retrieval and generation identity,
one Runtime generation event, one Ollama generation event, the exact formal
model/digest, timestamp-aligned `ollama ps`, and `nvidia-smi`/process evidence.
Formal GPU attribution is **3/3** with no fallback.

The resource snapshot records Ollama's observed `GPU_PARTIAL` residency
classification for the model snapshot, while the acceptance correlation is
unambiguous: every Normal Runtime event and Ollama event names the exact formal
GPU model/digest and no Normal flow uses CPU fallback. This is recorded rather
than hidden in `gpu_resource_ownership.json`.

## 12. Output Safety 3/3

All three real GPU-generated Normal candidates passed through real Output Safety
before delivery. The harness recorded `output_safety_real=3` and no direct
candidate delivery before a Safety verdict.

## 13. Citation Round Trip

Citation round trip: **3/3 PASS**. For every Normal flow, retrieved provenance,
generation evidence projection, approved citations, MySQL `support_evidence`,
and report/API citations had equal chunk/document/citation identity sets.

Identity mismatches: `0`. Fabricated citations: `0`. Unknown citations: `0`.
Orphan citations: `0`. No citation slot projection was introduced.

## 14. MySQL Persistence

Real MySQL persistence passed for all three Normal flows. Each had one
`COMPLETED` support run, approved output persisted, truthful formal model
identity, `fallback_used=false`, persisted Safety identity and five persisted
citation identities. No prohibited raw content was persisted. Migration head was
`20260906_0002`.

## 15. Fallback Regression 3/3

The impacted local CPU fallback regression passed **3/3** with the local
`qwen2.5-1.5b` fallback model, real Safety processing and content present.
Cloud calls: `0`. The formal GPU model was not silently used as the fallback
claim.

## 16. Crisis Sanity

Crisis sanity passed **3/3**. Each flow used `CRISIS_ROUTE`, had no normal
content, and recorded:

```text
RAG calls = 0
Runtime generation calls = 0
Ollama generation calls = 0
```

## 17. Safety-down Inheritance/Sanity

Safety-down sanity passed **2/2** and failed closed with HTTP 503. Both flows
recorded no RAG, Runtime or Ollama generation call. The previously accepted
Safety-down behavior was not redesigned.

## 18. Controlled Output Safety

Controlled unsafe-output sanity: **PASS**. Real Safety returned a blocking
decision; direct delivery was false; and the unsafe candidate was not persisted
as an approved output.

## 19. GPI Decision Fidelity

The corrected authoritative register materializes **GPI-01 through GPI-50**:

- materialized: `50/50`;
- semantic deviations: `0`;
- renumbering corrected: `true`;
- behavior changed merely for governance: `false`.

Evidence: `GPI_CONTROLLER_DECISION_FIDELITY_REPORT.md` and
`GPU_PRODUCT_INTEGRATION_TECHNICAL_DECISION_V1_1_CONTROLLER_CORRECTION.md`.

## 20. Module Regressions

- Runtime: `31 passed, 1 skipped` (the skipped test is the opt-in real Ollama integration test).
- Backend: `18 passed`.
- RAG: `18 passed, 4 skipped` (opt-in reranker integration gates).
- Safety: `20 passed, 1 skipped` (the separate Qwen CPU gate).

The skipped tests were pre-existing opt-in gates and are not represented as
passes.

## 21. Root Contract

The canonical Root Contract gate passed: 13 tests passed and the OpenAPI
validator reported `OK`; the gate ended with
`A-phase contract, Schema, and OpenAPI checks passed.`

## 22. Frozen Root

Frozen-root before/after hashes are equal. The canonical root contract files,
`CONTRACTS.md`, generation schema, config schema, logging schema and candidate
OpenAPI artifact remain unchanged. The fix branch started from the preserved
GPI checkpoint; the accepted runtime baseline remains
`2972be77e537ef03033332039a6ed0eed8e451ef`.

## 23. Git State

The fix is isolated on branch `fix/structured-output-product-compat-v1` in
`D:\Projects\StudentMentalHealthAI-structured-output-compat`. Main remains
preserved. No merge, push or accepted tag was performed. The final local fix
commit is created only after this evidence and the final diff are inspected.

## 24. Remaining P1

No product P0/P1 blocker remains for Controller review. The orchestration script
returned a nonzero cleanup code because one PID had already exited before its
`taskkill` call; a fresh explicit post-run probe found every target GPI port free.
This is recorded in `post_run_cleanup_probe.json` and is a harness cleanup
robustness note, not a product-flow failure.

## 25. Recommendation

Recommend:

`GPU_PRODUCT_INTEGRATION_FULL_PASS_READY_FOR_CONTROLLER_REVIEW`

Wait for Project Controller final review. Do not merge, push or create an
accepted tag.
