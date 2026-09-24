# D4 Slice 3B Controlled Product Evaluation — Preflight Stop Record

**Disposition: CONTROLLER_DECISION_REQUIRED**  
**Stage: PREFLIGHT_BLOCKED — NO FORMAL PRODUCT RUN**  
**Observed: 2026-09-24 20:02 +08:00**

## Baseline and approved inputs

- D4-3B baseline: `b505d3b578c55341add76764f8921831403e4bf3`.
- Branch/worktree: `exp/d4-controlled-product-evaluation-v1` / `D:\Projects\StudentMentalHealthAI-d4-controlled-product-eval`.
- D4-3A accepted tag: `d4-slice3a-r1-accepted` → `dd083d7a9d50e554408571e8b6d8040700d7a88b`.
- Human Gold packet: `D4-PACKET-SLICE3A-CITATION-UTILITY-R1`.
- Approved packet hash: `sha256:cfbe640300c2cbfbfe9616bb20b10b6ed80e7ee1e15169aadf2052ac8de107c6`; canonical `verify_packet_hash()` returned true.
- Approved units: 7 citation-support and 12 answerability. All 12 answerability cases target `university_freshman`; distribution is MUST_ANSWER 5, SHOULD_ABSTAIN 4, SHOULD_ANSWER 1, MUST_ROUTE 1, MUST_DENY 1.

The approved packet is the Human Gold consumer. The underlying answerability source dataset remains the original draft/provenance input. The existing `packet_from_json()` rejects top-level `HUMAN_APPROVED`; a future evaluation-only consumer must parse the approved packet, verify its canonical packet hash and approval fields, and preserve the source-hash provenance. No such consumer was added in this blocked preflight.

## Stop conditions found

**Accepted Runtime identity could not be reproduced.** The required baseline is Ollama 0.33.3 with `qwen2.5:7b-instruct-q4_K_M`, digest `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`, context 8192, f16 KV, parallel 1, max-loaded-models 1, output budget 768, and cloud fallback disabled. The only local Ollama client/server observed was 0.21.1. Its model list contained `qwen2.5:1.5b` and `qwen2.5:0.5b`; the accepted 7B model and digest were absent. No product generation call was made and no substitute model was used.

The machine has an NVIDIA GeForce RTX 3060, driver 596.36, CUDA 13.2, and 12 GB VRAM. This does not satisfy the missing accepted model/runtime identity. The remaining generation settings and cloud-fallback state were not verifiable because no accepted Runtime service was available.

**The approved population scope conflicts with the accepted Backend RAG request mapping.** `09_backend/src/smhai_backend/integrations/rag.py` hardcodes `target_population: "K12学生"` in `HttpRagClient.retrieve` (around line 169). All 12 approved answerability cases target `university_freshman`; the approved Human Gold and case scope were not changed. Resolving this by changing the Backend mapping or rewriting the approved fixture/gold would exceed this handoff. No product source, case, evidence, label, or applicability decision was changed.

Static inspection found a possible evaluation-only RAG injection seam through `RagRuntime` and `create_app(runtime=...)` in `05_rag-engine/src/rag_engine/api/app.py`; it was not exercised and no corpus or index was created. The pending D2 intake was not read or used. Any later run still needs to prove that its temporary corpus and fresh index contain only the approved synthetic evidence.

## Preflight network observation

No D4-3B product or model request occurred. During local runtime inventory, invoking `ollama list` when no Ollama service was running started the installed Ollama app (PIDs 41076 and 49904). Its updater logged an available version and a GitHub download URL; the process had established loopback connections to the local proxy on port 7890. The direct remote destination was not captured. No evaluation, product, student, or credential data was supplied to this updater check. The two processes started by this probe were stopped; no Ollama process or listener on ports 11434/56126 remained afterward. The session therefore cannot be described as having had no external network activity, but the formal D4-3B product data plane never started.

## Run status

- Formal run ID / manifest hash: `NONE / NONE`.
- Product cases executed: `0 / 12`.
- Product requests, Runtime calls, and model calls: `0`.
- Answerability metrics and generated-claim packet: `NOT_COMPUTED / NOT_CREATED`.
- P0/P1 product findings: `NOT_ASSESSED` (no cases were run).
- Promptfoo / model grader: `NOT_USED`.
- Real-student data / pending D2 intake: `NOT_USED`.
- Product source and frozen contracts changed: `false`.
- D4-4 started: `false`; merge, push, and tag: `false`.
- Real pilot: `BLOCKED`.

## Controller decision and remaining stop condition

At `2026-09-24T20:09:49+08:00`, the project owner directed D4-3B to keep product source and Human Gold frozen, run all 12 approved cases as-is once the exact accepted Runtime is available, and report the K12/freshman mismatch as observed product behavior. No product mapping or Human Gold change is authorized. This resolves the scope question above.

A read-only inventory of both configured Ollama model stores (`D:\Dev\caches\ollama-models` and `C:\Users\15848\.ollama\models`) found only manifests for `qwen2.5:0.5b` and `qwen2.5:1.5b`. No Ollama service or listener on `127.0.0.1:11434` is currently available, and the accepted 7B digest remains absent. The required stop condition therefore remains active. Do not substitute or pull another model; resume after the exact accepted runtime/model is made available and its identity/configuration are reverified.

This record is evaluation/governance evidence only; it does not accept D4-3B or change the D4 overall status.
