# Open-Source Integration Reference Audit

## Scope

本审计只记录本轮真实组合所复用的成熟组件、采用的设计边界和未采用的替代方案。它不引入新的依赖，也不把参考项目包装成已实现能力。

## Reference and adoption matrix

| Reference | Local evidence / version | Decision | Use in this round |
| --- | --- | --- | --- |
| NVIDIA NeMo Guardrails | Safety readiness: `0.24.0` | Adopt existing component | Real input/retrieval/output Safety boundary; no new wrapper dependency. |
| QwenLM Qwen3Guard | revision `fada3b2f655b89601929198343c94cd2f64d93cc` | Adopt accepted source of truth | CPU/float32 guard model; readiness and controlled unsafe fixture are recorded. |
| Microsoft Presidio | readiness: `2.2.364` | Adopt existing component | PII signal detection and Safety decision inputs. |
| Open Policy Agent | binary/policy: `1.20.2` | Adopt existing policy boundary | OPA health and policy decision; unavailable Safety remains fail-closed. |
| AISIX Presidio guardrail design | Architectural reference only | Conceptual reuse | Layered PII detection and policy projection are consistent with the existing Safety composition; no code or dependency copied. |
| Grounded LLM / provenance patterns | Existing frozen `generation.v1` and RAG citation contracts | Adopt existing contract | Retrieval IDs, chunk IDs, content hashes and citation identity remain traceable. |
| OpenTelemetry correlation concepts | Existing request/trace IDs and sanitized observer events | Adapt existing local convention | Correlation is kept inside current contracts and logs; no new telemetry package is added. |
| Ollama native API | accepted provider adapter in Runtime Reconstruction | Adopt existing adapter | RuntimeService owns Ollama calls; Backend has no direct Ollama call. |
| BM25S + BGE-M3 hybrid retrieval | existing RAG module implementation | Adopt existing module | Dense+sparse RRF with reranker OFF; exact accepted publication is the boundary. |

## What was deliberately not adopted

- No ContractFake in the product closure path. The final machine evidence reports `realness_contract_fake_count: 0`.
- No cloud model, OpenAI endpoint, hosted fallback or network generation path.
- No new LLM orchestration framework; the accepted RuntimeService remains the composition point.
- No new vector database or reranker. The accepted Round 1 boundary is the published local corpus plus current BGE-M3/BM25S implementation.
- No product source patch to hide the structured-output failure. A source-level fix would require a new technical decision and its own regression.

## Dependency and license boundary

本轮只使用现有项目环境和已接受本地工具：dedicated Ollama 0.33.3、MySQL 8.4、OPA 1.20.2 以及模块现有 Python environments。没有修改项目依赖清单；root gate 为验证环境临时补齐的 `openapi-spec-validator` 只安装在目标 worktree 的 ignored backend venv，不是产品依赖变更。

## Audit conclusion

成熟组件的职责边界清晰：RuntimeService 负责模型选择和 fallback，RAG 负责 grounded retrieval，Safety 负责 fail-closed policy and output screening，OPA 负责 policy decision，Backend 负责产品编排和 MySQL persistence。剩余阻塞不是缺少开源组件，而是 exact accepted chunk identities 触发了当前 formal Qwen structured-output parse failure，详见 [PRODUCT_INTEGRATION_BLOCKER.md](PRODUCT_INTEGRATION_BLOCKER.md)。
