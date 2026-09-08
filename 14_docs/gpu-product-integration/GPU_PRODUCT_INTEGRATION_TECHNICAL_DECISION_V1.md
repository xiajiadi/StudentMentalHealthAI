# GPU Product Integration Technical Decision V1

Status: **FROZEN**  
Round: `GPU_PRODUCT_INTEGRATION_CLOSURE_R1`  
Baseline: `2972be77e537ef03033332039a6ed0eed8e451ef`  
Branch: `exp/gpu-product-integration-closure-v1`  
Worktree: `D:\Projects\StudentMentalHealthAI-gpu-product-integration-closure`

## Decision

本轮只做 acceptance-only 的真实产品组合验证，不修改冻结产品源代码、根契约或接口治理。产品路径固定为：

`Backend → real Input Safety → real RAG → accepted RuntimeService → dedicated Ollama → real Output Safety → MySQL persistence`

危机路径在 Input Safety 返回 `CRISIS_ROUTE` 后终止于 Backend，不调用正常 RAG、RuntimeService、Ollama 或 GPU。主模型失败时只允许走已接受的本地 CPU fallback，不允许云端 fallback。

| Area | Frozen decision |
| --- | --- |
| RAG | BGE-M3 dense + BM25S sparse hybrid + RRF; reranker OFF |
| Primary runtime | accepted `RuntimeService` + official `OllamaProvider` |
| Primary model | `qwen2.5:7b-instruct-q4_K_M` |
| Primary digest | `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e` |
| Ollama | dedicated 0.33.3 endpoint, local-only, context 8192, KV f16, parallel 1 |
| GPU | NVIDIA GeForce RTX 3060, 12 GB; primary `GPU_FULL` |
| Safety | Qwen3Guard revision `fada3b2f655b89601929198343c94cd2f64d93cc`, CPU/float32; NeMo Guardrails; Presidio; OPA 1.20.2; fail closed |
| Database | fresh isolated MySQL 8.4 synthetic database; migration head `20260906_0002` |
| Fallback | local `qwen2.5:1.5b`, CPU, digest `65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b` |

## Controller requirements GPI-01 through GPI-50

The following IDs preserve the controller numbering and headings exactly. The acceptance state is recorded in the closure evidence; a failed hard gate remains failed and is not weakened by this document.

| ID | Controller requirement |
| --- | --- |
| GPI-01 | PRIMARY OBJECTIVE — compose the real Backend, CAT, RAG, Runtime, Ollama, GPU, Safety, OPA and MySQL product path. |
| GPI-02 | FROZEN TECHNICAL DECISION — keep the accepted stack and model identities unchanged. |
| GPI-03 | GIT PREFLIGHT — verify baseline, branch and isolated worktree before execution. |
| GPI-04 | MAIN PRESERVATION — preserve the original main checkout and its working state. |
| GPI-05 | FROZEN ROOT PREFLIGHT — hash the frozen root artifacts before the run. |
| GPI-06 | NO EXPERIMENTAL BRANCH MERGES — do not merge experimental work into the closure baseline. |
| GPI-07 | D2 INDEPENDENCE — do not use the Runtime Reconstruction D2 corpus as product evidence. |
| GPI-08 | RECONSTRUCT ACCEPTED SYNTHETIC RAG BOUNDARY — restore the accepted Round 1 publication boundary. |
| GPI-09 | SYNTHETIC BOUNDARY RESTORATION ORDER — restore Knowledge publication before starting real RAG. |
| GPI-10 | ACCEPTED RAG IDENTITY — prove corpus, provider and retrieval identity with hashes and versions. |
| GPI-11 | GPU RUNTIME — use the accepted RuntimeService GPU entry and real provider path. |
| GPI-12 | DEDICATED OLLAMA — use only the dedicated 0.33.3 local Ollama instance for the formal model. |
| GPI-13 | RESOURCE OWNERSHIP — keep GPU ownership with the formal 7B Ollama process. |
| GPI-14 | VERIFY RESOURCE OWNERSHIP — verify model digest, VRAM allocation, context and device. |
| GPI-15 | REAL SAFETY SOURCE OF TRUTH — use the accepted Safety engine and not a ContractFake Safety path. |
| GPI-16 | SAFETY COMPONENT READINESS — require OPA, Presidio, NeMo, Qwen3Guard and human review readiness. |
| GPI-17 | QWEN3GUARD RULE — use the accepted revision on CPU with float32. |
| GPI-18 | NEMO RULE — execute the real NeMo Guardrails boundary. |
| GPI-19 | PRESIDIO RULE — execute the real Presidio boundary. |
| GPI-20 | OPA RULE — execute OPA 1.20.2 policy decisions and fail closed when unavailable. |
| GPI-21 | REAL DATABASE — use a fresh isolated MySQL 8.4 database for all product persistence. |
| GPI-22 | DATABASE PREFLIGHT — prove database identity, migration execution and synthetic-only data. |
| GPI-23 | FULL-REAL DEFINITION — label Backend, CAT, RAG, Runtime, Ollama, Safety, OPA and MySQL real. |
| GPI-24 | SERVICE READINESS MATRIX — record all required service readiness and identity fields. |
| GPI-25 | NORMAL FLOW — HARD GATE — execute three independent synthetic normal product flows. |
| GPI-26 | NORMAL FLOW REQUIRED SEQUENCE — prove CAT, input Safety, RAG, Runtime, Ollama, output Safety and persistence order. |
| GPI-27 | NORMAL FLOW TRACE — preserve request, trace, retrieval, generation, model, digest and GPU evidence. |
| GPI-28 | NORMAL RAG REQUIREMENT — require real grounded retrieval and reject silent ungrounded generation. |
| GPI-29 | CITATION ROUND TRIP — preserve citation identity from RAG through API and MySQL report projections. |
| GPI-30 | GPU PROOF DURING PRODUCT FLOW — observe the formal GPU model during a product request. |
| GPI-31 | REAL OUTPUT SAFETY — NORMAL — run all normal candidates through real Output Safety. |
| GPI-32 | CRISIS FLOW — HARD GATE — execute three crisis product flows. |
| GPI-33 | CRISIS ZERO-CALL INVARIANT — crisis must perform zero normal RAG and generation calls. |
| GPI-34 | ZERO-CALL EVIDENCE — record CAT, Safety, Runtime, Ollama and GPU call counts for crisis. |
| GPI-35 | ACCEPTANCE-ONLY OBSERVER — observe loopback traffic without storing request or response bodies. |
| GPI-36 | CONTROLLED OUTPUT-SAFETY TEST — prove a real unsafe fixture is blocked before delivery. |
| GPI-37 | OUTPUT-SAFETY PERSISTENCE — prove blocked unsafe content is not persisted as approved output. |
| GPI-38 | SAFETY-DOWN — HARD GATE — execute two Safety-unavailable product requests. |
| GPI-39 | SAFETY-DOWN EXPECTED BEHAVIOR — fail closed with no RAG, Runtime or Ollama generation. |
| GPI-40 | SAFETY RESTORE — restore the real Safety service before subsequent product flows. |
| GPI-41 | PRODUCT FALLBACK — HARD GATE — test fallback through the real product path, not a unit-only call. |
| GPI-42 | PRIMARY FAILURE INJECTION — make only the primary local model unavailable. |
| GPI-43 | FALLBACK TARGET — use the accepted local `qwen2.5:1.5b` target. |
| GPI-44 | FALLBACK MUST BE LOCAL — prohibit cloud providers and cloud fallback. |
| GPI-45 | FALLBACK EXECUTION DEVICE — prove the fallback executes on CPU with no meaningful VRAM allocation. |
| GPI-46 | FALLBACK PRODUCT FLOW — execute three controlled fallback product completions. |
| GPI-47 | FALLBACK SAFETY — require real Output Safety on all fallback candidates. |
| GPI-48 | NORMAL PERSISTENCE — persist normal workflow, generated content and citation evidence truthfully. |
| GPI-49 | CRISIS PERSISTENCE — persist crisis review state without normal generated content or citations. |
| GPI-50 | FALLBACK PERSISTENCE — persist truthful fallback identity and Safety-reviewed output. |

## Non-negotiable boundaries

- 本轮没有提交、推送、合并、打 tag，也没有修改主 checkout。
- 不使用真实学生数据；所有请求、账号、assessment 和数据库均为 synthetic fixture。
- 不把旧轮成功结果当作当前 exact publication 的成功证据。
- 当前闭环状态由 machine evidence 决定为 `PARTIAL_PASS`，因为 GPI-25、GPI-29 依赖的正常生成硬门未通过。
