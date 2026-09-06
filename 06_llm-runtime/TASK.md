# 06_llm-runtime：本地大模型运行层

## 职责

- 为上层提供统一的本地 LLM Provider 接口；
- 管理模型注册、能力信息、健康检查、超时和错误分类；
- 支持结构化输出解析，必要时支持流式输出；
- 支持 Mock Provider，使测试不依赖真实模型；
- 记录模型、Runtime 和配置版本，便于复现。

## 输入

- Prompt Engine 生成的结构化请求；
- 模型注册表、上下文长度和资源配置；
- 本地 Provider 的健康状态；
- 超时、重试、取消和输出格式策略。

## 输出

- Provider Response；
- 模型 ID、版本、Runtime 版本和耗时摘要；
- 结构化解析成功或失败状态；
- MODEL_UNAVAILABLE、TIMEOUT、INVALID_OUTPUT 等稳定错误；
- 健康检查和模型能力报告。

## 禁止事项

- 不在 Runtime 内编写角色 Prompt 或心理解释；
- 不绕过 Safety Engine 直接发布输出；
- 不把模型下载、缓存或密钥写入系统目录或仓库；
- 不默认把外部云 Provider 作为隐式回退；
- 不把原始敏感测评数据写入模型日志。

## 接口

- health() -> runtime health；
- list_models() -> registered model metadata；
- generate(request) -> provider response；
- cancel(request_id) -> cancellation result；
- parse_structured(response, schema) -> validated candidate；
- Provider 实现可替换，Ollama/llama.cpp 等细节不得泄露给上层业务接口。

## 验收标准

- Mock Provider 可在无模型环境完成测试；
- Provider 不可用、超时、空响应和非法 JSON 都有稳定处理；
- 真实模型调用前后都能关联 request_id、model_id 和版本；
- 结构化输出不通过校验时不能伪装成功；
- 本地模型与缓存路径可配置，默认不写入 C 盘系统目录；
- 未经安全后检的结果不会通过 Runtime 被标记为 approved。

## 交付物

- LLMProvider 抽象接口；
- 至少一个本地 Provider Adapter 和一个 Mock Provider；
- 模型注册表样例；
- 健康检查、错误恢复和配置说明；
- 性能/资源测量记录及未覆盖的硬件范围。

## Round 1 execution checklist

The following checklist is the execution record for the CPU-first Round 1
scope. Items marked `PENDING` are not represented as completed in the
acceptance report.

| ID | Work item | Status |
| --- | --- | --- |
| LLM-R1-01 | Read governance / frozen contracts | DONE |
| LLM-R1-02 | Create LLM_RUNTIME_TECHNICAL_DECISION_V1.md | DONE |
| LLM-R1-03 | Study Ollama | DONE |
| LLM-R1-04 | Study llama.cpp | DONE |
| LLM-R1-05 | Study vLLM | DONE |
| LLM-R1-06 | Study SGLang | DONE |
| LLM-R1-07 | Study LocalAI | DONE |
| LLM-R1-08 | Study Olla | DONE |
| LLM-R1-09 | Study GPUStack | DONE |
| LLM-R1-10 | Study LiteLLM | DONE |
| LLM-R1-11 | Create THIRD_PARTY_NOTICES | DONE |
| LLM-R1-12 | Create Runtime compatibility report | DONE |
| LLM-R1-13 | Implement Domain models | DONE |
| LLM-R1-14 | Implement LLMProvider | DONE |
| LLM-R1-15 | Implement ModelRegistry | DONE |
| LLM-R1-16 | Implement HardwareDetector | DONE |
| LLM-R1-17 | Implement OllamaProvider | DONE |
| LLM-R1-18 | Install / verify CPU test model | DONE |
| LLM-R1-19 | Provider health | DONE |
| LLM-R1-20 | Model health / smoke test | DONE |
| LLM-R1-21 | Model lifecycle | DONE |
| LLM-R1-22 | Generation | DONE |
| LLM-R1-23 | Streaming | DONE |
| LLM-R1-24 | Structured output | DONE |
| LLM-R1-25 | Cancellation | LIMITED / UNIT COVERED |
| LLM-R1-26 | Error normalization | DONE |
| LLM-R1-27 | Retry | DONE |
| LLM-R1-28 | Local fallback | DONE |
| LLM-R1-29 | RuntimeTrace | DONE |
| LLM-R1-30 | Benchmark | DONE |
| LLM-R1-31 | LlamaCppProvider PoC | DONE / EXECUTION PENDING |
| LLM-R1-32 | Unit tests | DONE |
| LLM-R1-33 | Integration tests | DONE |
| LLM-R1-34 | Contract tests | DONE / runtime boundary PASS; root suite PARTIAL due existing 05_rag-engine governance subtest |
| LLM-R1-35 | Generate acceptance | DONE / PARTIAL PASS |

## LLM ROUND 1 ACCEPTANCE CLOSURE

This independent checklist closes only the outstanding CPU Engineering Round 1
acceptance items. It does not start Round 2 or rewrite the historical result
above.

| ID | Work item | Status | Evidence |
| --- | --- | --- | --- |
| LLM-R1-CLOSE-01 | Reproduce current root contract failure | DONE | Current formal root script: 13 tests passed, 0 failed; historical 05-rag failure is not reproducible. |
| LLM-R1-CLOSE-02 | Determine ownership of RAG TASK governance failure | DONE | `AGENT_RULES.md` assigns one module per Agent and requires a cross-directory proposal; current 05 TASK already has all required headings. |
| LLM-R1-CLOSE-03 | Resolve or hand off RAG governance-only failure safely | DONE | No 05-rag file changed; no handoff required because the current governance test passes. |
| LLM-R1-CLOSE-04 | Re-run full root contract suite | DONE | [`reports/ROOT_CONTRACT_RECHECK.md`](reports/ROOT_CONTRACT_RECHECK.md) records the full script and exit code 0. |
| LLM-R1-CLOSE-05 | Run external OpenAPI validator | DONE | [`reports/OPENAPI_EXTERNAL_VALIDATION.md`](reports/OPENAPI_EXTERNAL_VALIDATION.md); `openapi-spec-validator 0.9.0`, exit code 0. |
| LLM-R1-CLOSE-06 | Download/verify second real Ollama fallback model | DONE | `qwen2.5:1.5b` was pulled, SHA-256 verified and discovered by `/api/tags`; provenance is in the closure reports. |
| LLM-R1-CLOSE-07 | Run real local model switching test | DONE | [`reports/REAL_MODEL_SWITCHING_EVIDENCE.md`](reports/REAL_MODEL_SWITCHING_EVIDENCE.md); both logical-to-provider mappings generated successfully. |
| LLM-R1-CLOSE-08 | Run real local failover test | DONE | [`reports/REAL_FALLBACK_EVIDENCE.md`](reports/REAL_FALLBACK_EVIDENCE.md); real 404 `MODEL_NOT_FOUND` switched to real 1.5B inference. |
| LLM-R1-CLOSE-09 | Verify RuntimeTrace records fallback | DONE | `TRACE_ollama_real_fallback` records primary error, normalized code, fallback IDs, success, retry count and fallback count. |
| LLM-R1-CLOSE-10 | Re-run LLM unit/integration tests | DONE | Unit: 23 passed, 1 existing opt-in skip; full real run: 26 passed, 0 failed, 0 skipped. |
| LLM-R1-CLOSE-11 | Re-run dependency/compile checks | DONE | `uv sync`, `uv lock --check`, `uv pip check`, dependency tree and compileall passed; Ruff remained network-blocked and is recorded as such. |
| LLM-R1-CLOSE-12 | Update acceptance evidence | DONE | [`reports/LLM_RUNTIME_ROUND1_CLOSURE_EVIDENCE.md`](reports/LLM_RUNTIME_ROUND1_CLOSURE_EVIDENCE.md) and section 33 of the acceptance report. |
| LLM-R1-CLOSE-13 | Final PASS gate evaluation | DONE | CPU Engineering Round 1 closure gate is `PASS`; GPU remains `DEFERRED`, llama.cpp remains `PENDING`. |

Closure invariants: frozen Contracts were not modified; cloud fallback remains
disabled; all real prompts were synthetic engineering text; no cloud request
was executed; Ollama stayed at installed version `0.21.1`; no test was deleted,
skipped or xfailed to obtain the result.
