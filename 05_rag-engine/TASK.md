# 05_rag-engine · Round 1 Task Ledger

## 职责

根据合法的 Assessment 摘要、目标角色和安全状态，从已审核的 Knowledge
片段中执行可追溯检索、引用组装和检索评估；不生成答案，不解释心理测量结果。

## 输入

合法的 assessment.v1 摘要、目标角色、风险状态、04_knowledge-pipeline
的 approved embedding-ready Knowledge 输出，以及本模块检索配置。

## 输出

retrieval_id、结构化 RetrievalPlan、带 stage scores 的检索结果、ContextBundle、
CitationBundle、RetrievalTrace 和确定性评测报告。

## 禁止事项

不索引真实学生个人数据；不返回未批准或 rights_status 不允许的片段；不把
subject_id、姓名、学号或原始回答放入查询；不调用 LLM 做 query rewrite 或答案生成；
不修改 Frozen Contract。

## 接口

build_query(assessment_summary, role, safety_state) -> RetrievalPlan；
retrieve(plan) -> RetrievalResult；provider adapter、citation 和 trace 均通过
稳定的内部 Domain Model 交互。

## 验收标准

只返回 approved 且 rights_status=verified、角色/人群/风险匹配的片段；每个结果可
定位到文档和章节/页码；固定索引、查询和配置时结果可复现；无结果、索引不可用或
依赖不可用时返回稳定状态，不制造引用。

## 交付物

RAG 技术决策与第三方通知、provider adapters、索引/查询/引用/trace 实现、Golden
Dataset、IR metrics、benchmark、contract/integration tests、runtime compatibility
report 和 Round 1 acceptance report。

状态只使用 `TODO`、`IN_PROGRESS`、`DONE`、`BLOCKED`。`DONE` 表示本模块代码或研究交付及其证据已完成；存在未完成的真实依赖或门禁时，相关任务保持 `BLOCKED`。

| ID | 状态 | 交付与证据 |
| --- | --- | --- |
| RAG-R1-01 | DONE | 已读取根治理、Frozen Contracts、OpenAPI、Knowledge Round 1 输出；未修改根合同。 |
| RAG-R1-02 | DONE | [`RAG_TECHNICAL_DECISION_V1.md`](RAG_TECHNICAL_DECISION_V1.md)，1.0 / PROVISIONALLY_FROZEN。 |
| RAG-R1-03 | DONE | 已研究 FlagEmbedding 当前 API、版本、许可证及 BGE-M3 / reranker 官方示例。 |
| RAG-R1-04 | DONE | 已研究 Chroma PersistentClient、cosine、where filter 与 query embeddings。 |
| RAG-R1-05 | DONE | 已研究 Qdrant local mode、named vectors、prefetch 与 native RRF。 |
| RAG-R1-06 | DONE | 已研究 BM25S tokenizer、index、retrieve、save/load API。 |
| RAG-R1-07 | DONE | 已研究 RAGFlow retrieval、metadata filter、rerank candidate 与 citation ordering。 |
| RAG-R1-08 | DONE | 已研究 Haystack / LlamaIndex pipeline、retriever、router、metadata 边界。 |
| RAG-R1-09 | DONE | 已研究 Ragas context precision/recall、faithfulness、answer relevance；未作为唯一门禁。 |
| RAG-R1-10 | DONE | [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) 已记录版本、revision、license、用途、是否复制。 |
| RAG-R1-11 | DONE | `EmbeddingProvider`、输出形状校验、版本信息与稳定错误边界已实现。 |
| RAG-R1-12 | DONE | BGE-M3 真实 adapter 已加载并在 CPU 上完成 1024 维 query/corpus embedding；模型版本 1.4.2。 |
| RAG-R1-13 | DONE | `VectorStoreProvider` 已实现 provider-neutral dense/sparse/hybrid 接口。 |
| RAG-R1-14 | DONE | Chroma 1.5.9 persistent adapter 已实现并由真实 Chroma client integration test 验证。 |
| RAG-R1-15 | DONE | Qdrant 1.19.0 local named-vector / native RRF PoC 已真实运行。 |
| RAG-R1-16 | DONE | `BM25SRetriever` 及中文 CJK bigram tokenizer 已实现。 |
| RAG-R1-17 | DONE | BM25S 0.3.11 build、retrieve、save/load 与中文检索已真实运行。 |
| RAG-R1-18 | DONE | BGE-M3 实测返回非空 `lexical_weights`；已记录 sparse output 观测，Qdrant 实际混合基线仍为后续范围。 |
| RAG-R1-19 | DONE | provider-independent RRF 已实现，保留 dense/sparse/fusion stage scores。 |
| RAG-R1-20 | DONE | `RerankerProvider`、NoOp 显式禁用边界与 candidate-only 接口已实现。 |
| RAG-R1-21 | DONE | BGE reranker adapter 已以 FlagEmbedding 1.4.2、官方 revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` 完成真实离线加载与 score probe。 |
| RAG-R1-22 | DONE | 无 LLM 的确定性 `QueryBuilder` 已实现，含身份 token 拒绝。 |
| RAG-R1-23 | DONE | `RetrievalPlan` 已实现候选池、final_k、层预算、风险和查询类型字段。 |
| RAG-R1-24 | DONE | policy/theory/intervention 路由及 role/population/risk/review/rights filter 已实现。 |
| RAG-R1-25 | DONE | `IndexBuilder` 已实现稳定 fingerprint、重建、stale ID 清理和显式生命周期。 |
| RAG-R1-26 | DONE | `IndexManifest` 已记录 corpus/model/store/distance/config/eligible IDs。BM25 另有稳定 lexical manifest。 |
| RAG-R1-27 | DONE | `RetrievalTrace` 已记录各 stage、各 stage score、provider/index/corpus 版本和 latency。 |
| RAG-R1-28 | DONE | `ContextBuilder` 已实现上下文长度预算、去重与截断状态。 |
| RAG-R1-29 | DONE | `CitationBundle` 已绑定 S<N>、chunk/document、title/organization/locator/source。 |
| RAG-R1-30 | DONE | `evaluation/golden_queries.jsonl` 已建立 30 条、覆盖 7 类查询且引用 ID 均来自真实 Knowledge export。 |
| RAG-R1-31 | DONE | Hit、Recall、Precision、MRR、nDCG、P50/P95 的确定性纯函数与测试已实现。 |
| RAG-R1-32 | DONE | Mock dense 仅作 test-only smoke；真实 BGE-M3 + Chroma Dense benchmark 已通过。 |
| RAG-R1-33 | DONE | BM25S 30-query benchmark 已完成，见 `reports/rag_eval_round1.json`。 |
| RAG-R1-34 | DONE | 真实 Dense+Rerank 与 Hybrid+Rerank 30-query benchmark 已通过工程门禁，含 rerank 前后 Trace 证据。 |
| RAG-R1-35 | DONE | 真实 BGE-M3 dense + BM25S Hybrid benchmark 已通过；Qdrant dense/sparse/native-RRF 仍明确为 POC。 |
| RAG-R1-36 | DONE | 22 tests passed；包含 reranker integration、BM25S、Chroma、Qdrant、frozen OpenAPI envelope 和 Knowledge schema 边界。 |
| RAG-R1-37 | DONE | [`reports/RAG_RUNTIME_COMPATIBILITY.md`](reports/RAG_RUNTIME_COMPATIBILITY.md) 已生成。 |
| RAG-R1-38 | DONE | [`reports/RAG_ROUND1_ACCEPTANCE.md`](reports/RAG_ROUND1_ACCEPTANCE.md) 已更新；保留初始 PARTIAL PASS 历史，Closure 结论为 Round 1 engineering PASS。 |

## Round 1 commands

```powershell
    uv sync --offline --extra runtime --extra test
    $env:SMHAI_RUN_RERANKER_INTEGRATION='1'
    .venv\Scripts\python.exe -m pytest -q
    .venv\Scripts\python.exe -m compileall -q src tests
    uv run rag-engine-benchmark --mode all --offline --real-models --rerank --output reports/rag_eval_round1.json
    powershell -NoProfile -ExecutionPolicy Bypass -File .\00_architecture\tests\run_contract_checks.ps1
```

模型权重与 provider cache 位于 D 盘环境目录，不进入源码或 Git 交付物。Closure
已重新建立 Dense、Dense+Rerank、Hybrid、Hybrid+Rerank 指标，并保存真实
rerank 前后证据；Qdrant 真实 BGE dense+sparse benchmark 仍是 P1，不阻塞本轮
Full PASS。

## RAG ROUND 1 ACCEPTANCE CLOSURE

本清单只覆盖 Round 1 收尾，不启动 Round 2。`DONE` 仅表示对应证据已真实
完成；未完成的真实依赖或门禁仍保持 `IN_PROGRESS` 或 `BLOCKED`。

| ID | 状态 | 交付与证据 |
| --- | --- | --- |
| RAG-R1-CLOSE-01 | DONE | 在 reranker integration opt-in 明确开启的条件下重现当前 RAG 测试：22 passed，3 warnings。 |
| RAG-R1-CLOSE-02 | DONE | 已读取 root gate 源码并确认 TASK 必需 headings。 |
| RAG-R1-CLOSE-03 | DONE | 已完成 TASK governance headings 的最小修复；未改 root Contract。 |
| RAG-R1-CLOSE-04 | DONE | 已核对 FlagEmbedding API、官方模型来源、revision、许可证和权重哈希。 |
| RAG-R1-CLOSE-05 | DONE | 官方 `BAAI/bge-reranker-v2-m3` 权重已缓存到 D 盘并通过大小/SHA-256 校验。 |
| RAG-R1-CLOSE-06 | DONE | 真实 BGE reranker offline load 与 score probe 已通过；runtime health 为 `ok`。 |
| RAG-R1-CLOSE-07 | DONE | 真实 Dense -> BGE Reranker integration 已完成并通过 30-query benchmark。 |
| RAG-R1-CLOSE-08 | DONE | 真实 Hybrid -> BGE Reranker integration 已完成并通过 30-query benchmark。 |
| RAG-R1-CLOSE-09 | DONE | exact keyword、semantic paraphrase、policy 三类 query 均有 rerank before/after Trace。 |
| RAG-R1-CLOSE-10 | DONE | 完整 30-query Golden Dataset、6 configurations benchmark 已完成。 |
| RAG-R1-CLOSE-11 | DONE | GQ_029/GQ_030 已在六条配置中重跑并记录；reranker 不提供 abstention。 |
| RAG-R1-CLOSE-12 | DONE | citation 顺序、final_context、rerank candidates/Trace 字段回归通过。 |
| RAG-R1-CLOSE-13 | DONE | Frozen Contract、Knowledge schema、OpenAPI envelope 相关模块检查通过。 |
| RAG-R1-CLOSE-14 | DONE | repository-wide root Contract / Governance suite：13 passed，0 failed；OpenAPI validator OK。 |
| RAG-R1-CLOSE-15 | DONE | `uv sync --offline`、`compileall` 和完整 pytest 均通过。 |
| RAG-R1-CLOSE-16 | DONE | [`reports/RAG_RETRIEVAL_BENCHMARK.md`](reports/RAG_RETRIEVAL_BENCHMARK.md) 与 JSON 已更新为最终六条配置结果。 |
| RAG-R1-CLOSE-17 | DONE | Acceptance Report 已更新；[`reports/RAG_ROUND1_CLOSURE_EVIDENCE.md`](reports/RAG_ROUND1_CLOSURE_EVIDENCE.md) 已生成。 |
