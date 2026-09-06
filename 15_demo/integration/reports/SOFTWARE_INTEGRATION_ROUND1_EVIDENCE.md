# Software Integration Round 1 — Evidence

状态：`PASS`（V0.9 合成可运行基线）  
日期：2026-09-06  
范围：本地 Windows、单机 loopback 服务、MySQL 8.4、合成 fixture；不使用真实学生数据，不作临床结论。

## 1. 组合边界

```text
Vue + RealApiProvider
        ↓ 生成的 Hey API 客户端 / Cookie + CSRF
FastAPI Backend/BFF :8080
        ├─ MySQL 适配器 → MySQL :3307
        └─ loopback HTTP
             CAT :8180 · RAG :8170 · LLM Runtime :8160 · Safety :8190
```

Backend 内部只持有短数据库事务。支持流程在外部调用前提交 `REQUESTED`，外部调用完成后再提交结果；危机和输出安全门路径不会把未批准候选写入 `APPROVED_OUTPUT`。

## 2. 服务健康矩阵

| 服务 | 结果 | 关键实证 |
| --- | --- | --- |
| Backend | `200 / ok` | `v0.1.0`；CAT、RAG、LLM Runtime、Safety 均标记 `READY / REAL_HTTP` |
| CAT | `READY` | `adaptivetesting-1.2.1`；`ITEMBANK_demo_cat`；`demo.v1`；`demo.cat.v1`；合成 fixture |
| RAG | `READY` | hybrid；14 个 eligible chunks；BGE-M3 / FlagEmbedding 1.4.2；CPU fp32；1024 维；本地缓存；默认不启用 reranker |
| LLM Runtime | Ollama ready | Ollama 0.21.1；`qwen2.5:0.5b` 已加载；`qwen2.5:1.5b` fallback ready；llama.cpp 404 按允许范围 deferred |
| Safety | `READY` | OPA 1.20.2；Presidio 2.2.364；NeMo Guardrails 0.24.0；Qwen3Guard 本地 revision `fada3b2f655b89601929198343c94cd2f64d93cc`；human review 1.0 |

## 3. 真实主路径

主 smoke 使用 `student_a` 合成账号、`SUBJ_demo_a` 和 CAT 发布 fixture。输出状态文件：`D:\Dev\studentmentalhealthai\software-integration-round1-20260906\real_smoke_state_final.json`。

| 场景 | 结果 | 关键字段 |
| --- | --- | --- |
| CAT | `PASS` | `ASSESS_bb98f25911ee4c1b84025d1b478f5782`；8/8 responses；8 administered；completed；真实 CAT provider |
| Normal | `PASS` | `REPORT_4d12c6624d004b01bf1a7804d472e9e3`；`generated`；`PROCEED_WITH_BOUNDARY`；有内容；SupportResult 有 5 条引用；`RETR_329da2351b0208086c54`；`TRACE_3769175a35ee8f22235a8b2ee4715cbd` |
| Normal replay | `PASS` | 同一 idempotency key 重放得到同一 report id |
| Crisis | `PASS` | `REPORT_1429d620fd194618b277b089d4df099e`；`needs_review`；`CRISIS_ROUTE`；无 content、无引用；`RETR_not_run`；有 `REVIEW_8c3f18aef9ee4e22858f2dad43fbaca9` |
| Output unsafe | `PASS` | `REPORT_dfec56565ee340b3a88481adbe34053f`；`safety_blocked`；`BLOCK`；无 content、无引用、无 review；候选只在 Safety 检查时追加合成 sentinel |
| Reviewer | `PASS` | Crisis review 已由 `synthetic-reviewer` 批准；报告从 pending 变为 approved |

Crisis 记录的 `RETR_not_run`、`normal_generation=false` 和无内容证明 Backend 在 Safety 输入判定后停止，没有调用 RAG 或 LLM Runtime。输出安全门的最终数据库记录同样没有 `APPROVED_OUTPUT`。

## 4. 重启与持久化

Backend 停止后以同一 MySQL 配置重新启动，`real_smoke.py resume` 返回：

```text
session_rehydrated=true
assessment_status=completed
normal report=generated
crisis report=approved
unsafe report=safety_blocked
report ids reused=true
```

主数据库当前为合成 Round 1 运行库，包含若干重试/诊断记录；最终记录的数据库投影如下：

| `run_ref` | DB status | workflow action | retrieval |
| --- | --- | --- | --- |
| `REPORT_4d12c6624d004b01bf1a7804d472e9e3` | `COMPLETED` | `PROCEED_WITH_BOUNDARY` | `RETR_329da2351b0208086c54` |
| `REPORT_1429d620fd194618b277b089d4df099e` | `BLOCKED` | `CRISIS_ROUTE` | `RETR_not_run` |
| `REPORT_dfec56565ee340b3a88481adbe34053f` | `BLOCKED` | `BLOCK` | `RETR_not_run` |

这三条记录的消息种类分别为：Normal `USER_INPUT + APPROVED_OUTPUT`；Crisis `USER_INPUT`；Output unsafe `USER_INPUT`。三类消息均为密文列；unsafe 场景没有批准输出消息。

主运行库行数快照：accounts 4、subjects 2、assessment_sessions 19、assessment_responses 147、assessment_results 16、support_sessions 22、support_runs 22、support_messages 31、safety_decisions 18、review_cases 6、review_events 9、idempotency_records 204、audit_events 253。密文非空计数分别为 assessment responses 147、assessment results 16、support messages 31、Safety details 18。

数据库模块另用 `smhai_software_round1_20260906` 做隔离回归；迁移命令返回 `No new upgrade operations detected.`。

## 5. 失败与安全门

- Safety-down 传输探针指向未监听的 loopback 端口，返回 `dependency_timeout`、HTTP 504、`fail_closed=true`。
- Backend 既有 `test_safety_down_fails_closed` 通过，并确认该分支不调用 RAG/LLM。
- Playwright 专项在一个仅用于故障 UI 验证的 Backend 上通过：CAT 仍使用 HTTP，Safety 指向 8199，前端保留在测评完成页，显示“这一步没有完成”和“重试”，没有伪造报告。
- Qwen CPU 真实 gate 使用显式 opt-in 单独通过 1/1；默认模块回归保持跳过，避免把模型评估混入普通快速回归。

## 6. 契约与生成客户端

- 根合同 `00_architecture/openapi.v1.json` 仍为 9 paths / 9 operations。
- 候选文档为 OpenAPI 3.1.0，21 paths / 21 operations；`openapi-spec-validator` 通过。
- `oasdiff 1.28.0` 比较根合同与候选文档：exit 0，`No breaking changes to report, but specs are different`。
- Schemathesis 4.25.2：21/21 operations，coverage 21 passed，fuzzing 21 passed，541/541 generated cases passed；仅保留无凭据认证和随机业务数据两类预期警告。详见 [`SCHEMATHESIS_REPORT.md`](SCHEMATHESIS_REPORT.md)。
- Hey API `@hey-api/openapi-ts 0.99.0` 重新生成 16/16 文件；canonical 与新生成目录 missing 0、extra 0、changed 0。canonical manifest SHA-256：`DE5C74FD83A0B2BB2B15804FC9507AA57ADDBFF45008B2E6755ECAB1984723DC`。

## 7. 回归结果

| 范围 | 结果 |
| --- | --- |
| 官方根合同 | 13/13 passed |
| Backend | pytest 12 passed；Ruff、Pyright、compileall passed |
| Database | pytest 16 passed；Ruff、Pyright、Alembic check passed |
| CAT | 24 passed |
| RAG | 18 passed；4 个 reranker gate 按开关跳过 |
| LLM Runtime | 23 passed；1 个 Ollama integration gate 按开关跳过 |
| Safety | 20 passed；1 个 Qwen gate 默认跳过；Qwen CPU 定向 gate 1 passed；Ruff passed |
| Frontend | typecheck、production build、unit 9/9、ESLint passed |
| Browser | 真实 Normal + Crisis 浏览器上下文 2/2；Safety-down UI 1/1；默认 Mock 3/3，3 个 real-only 用例按模式跳过 |

## 8. 根合同冻结校验

| 文件 | SHA-256 |
| --- | --- |
| `00_architecture/openapi.v1.json` | `235C8FDB0B35F2DE870127A18D4CD8C72A1C7795AF02656B2A6C7274AB071897` |
| `00_architecture/schemas/assessment.v1.schema.json` | `56B9FC990261D0B826EEEA0E84417754798EF3A980F50A414CCB565168375A52` |
| `00_architecture/schemas/knowledge.v1.schema.json` | `5334533DB35B30840F57E8012208037A6809BFED7CE08094BDA1517C801D8BCF` |
| `00_architecture/schemas/generation.v1.schema.json` | `8365D7EA825A30D9429361107750E87E8C6446D0A6576C47F3A8ECE564DCA62C` |
| `CONTRACTS.md` | `2AE5320C5B12EFE57DD90D7352AE192D1BEE8387B595E36DDD3919B90C486CBB` |
| `09_backend/reports/BACKEND_API_INVENTORY.md` | `D6A2E79013CC724E609065C4E8226D1A2F8767E0012D2020A17D1D4E093B8158` |

## 9. 本轮明确 deferred

RAG abstention/no-evidence、Qdrant 生产基准、reranker 默认启用、Qwen3Guard streaming、GPU/RTX3060 调优、llama.cpp、全 Docker/Kubernetes/service mesh、生产认证、OTel/Jaeger/Grafana、Argilla、专家确认的危机措辞、通知、临床验证、真实学校 pilot、多语言验证、生产 review reconciliation daemon、广泛负载测试和最终视觉 polish 均未被伪装成 Round 1 已完成。
