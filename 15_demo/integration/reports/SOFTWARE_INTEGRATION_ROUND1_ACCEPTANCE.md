# Software Integration Round 1 — Acceptance

结论：`PASS / ACCEPTED`  
基线：V0.9 本地合成可运行基线  
日期：2026-09-06

本结论只覆盖 Software Integration Round 1。它不代表临床有效性、真实学校试点、生产认证、通知闭环或发布签署。

## 验收矩阵

| 验收项 | 结果 | 证据 |
| --- | --- | --- |
| Stage 0 OSS research | PASS | `14_docs/SOFTWARE_INTEGRATION_OSS_RESEARCH.md`；记录版本、采用/拒绝理由和许可证检查 |
| Stage 1 interface inventory / reconciliation | PASS | `14_docs/INTEGRATION_INTERFACE_INVENTORY.md`、`14_docs/INTEGRATION_CONTRACT_RECONCILIATION.md` |
| Technical decision baseline | PASS | `14_docs/SOFTWARE_INTEGRATION_TECHNICAL_DECISION_V1.md`，v1.0 provisionally frozen |
| 冻结根合同 | PASS | 官方根合同 13/13；六个冻结文件 SHA-256 与基线一致 |
| Database boundary | PASS | 既有迁移 head；专用 MySQL 回归库 Alembic check 无新操作；数据库测试 16/16；敏感字段密文计数与对应行数一致 |
| Real service composition | PASS | Backend :8080 通过 MySQL + CAT :8180 + RAG :8170 + LLM :8160 + Safety :8190；健康矩阵全部 READY / REAL_HTTP |
| Login / session / CSRF | PASS | 真实浏览器登录、HttpOnly 会话 Cookie、CSRF mutation headers、跨源凭据均通过 |
| Real CAT | PASS | `ASSESS_bb98f25911ee4c1b84025d1b478f5782`；8 项响应；真实 `adaptivetesting-1.2.1` |
| Normal support | PASS | `REPORT_4d12c6624d004b01bf1a7804d472e9e3`；真实 RAG + buffered LLM + Output Safety；有引用和 trace |
| Crisis route | PASS | HTTP smoke 与浏览器上下文用例通过；`CRISIS_ROUTE`、无内容、`RETR_not_run`、人工复核引用；RAG/LLM 未调用 |
| Safety-down | PASS | 未监听 Safety loopback 探针返回 504/fail-closed；Backend 行为测试通过；Safety-down 浏览器 UI 1/1 显示可恢复错误和重试 |
| Output-unsafe | PASS | `BLOCK`、无 content、无 approved output；候选 sentinel 只用于 Safety 检查 |
| Human review | PASS | Crisis review 进入 pending，并由 synthetic reviewer 批准；状态重启后保留 |
| Idempotency | PASS | Normal support replay 复用同一 report id；数据库持久化 idempotency records |
| Restart recovery | PASS | Backend 重启后 `resume` 能从 MySQL 重建 assessment、Normal、Crisis、Output-unsafe 投影；report ids 相同 |
| Frontend RealApiProvider | PASS | login、CAT、support、report、review queue/detail/action 使用真实客户端；首页/教师汇总缺少后端接口时显示明确空状态，不使用夹具冒充真实数据 |
| Generated Hey API client | PASS | `@hey-api/openapi-ts 0.99.0`；16/16 文件无漂移 |
| Candidate OpenAPI | PASS | OpenAPI 3.1.0 validator 通过；oasdiff 1.28.0 exit 0，无 breaking change |
| Schemathesis | PASS | 21/21 operations；541/541 cases；coverage/fuzzing 全通过；两类预期 warning 已披露 |
| Browser regression | PASS | 真实 Normal + Crisis browser-context 2/2；Safety-down UI 1/1；默认 Mock 3/3 |
| Module regression | PASS | CAT 24；RAG 18 + 4 个显式 reranker skip；LLM 23 + 1 个显式 Ollama skip；Safety 20 + 1 个显式 Qwen skip，Qwen CPU 定向 gate 1 |

## 交付物

- [`SOFTWARE_INTEGRATION_OSS_RESEARCH.md`](../../../14_docs/SOFTWARE_INTEGRATION_OSS_RESEARCH.md)
- [`INTEGRATION_INTERFACE_INVENTORY.md`](../../../14_docs/INTEGRATION_INTERFACE_INVENTORY.md)
- [`SOFTWARE_INTEGRATION_TECHNICAL_DECISION_V1.md`](../../../14_docs/SOFTWARE_INTEGRATION_TECHNICAL_DECISION_V1.md)
- [`INTEGRATION_CONTRACT_RECONCILIATION.md`](../../../14_docs/INTEGRATION_CONTRACT_RECONCILIATION.md)
- [`openapi.integration.candidate.json`](../contracts/openapi.integration.candidate.json)
- [`OPENAPI_CHANGE_REPORT.md`](OPENAPI_CHANGE_REPORT.md)
- [`SCHEMATHESIS_REPORT.md`](SCHEMATHESIS_REPORT.md)
- [`SOFTWARE_INTEGRATION_ROUND1_EVIDENCE.md`](SOFTWARE_INTEGRATION_ROUND1_EVIDENCE.md)
- [`integration_round1_evaluation.json`](integration_round1_evaluation.json)

## 约束与未纳入结论的内容

根合同、根 Schema、根 API inventory 和 `CONTRACTS.md` 未被修改。所有数据均为 synthetic / engineering only；没有临床阈值、诊断、治疗、真实学生信息或自动通知。

RAG abstention、Qdrant 生产基准、reranker 默认启用、Qwen streaming、GPU、llama.cpp、生产认证、OTel、Argilla、专家危机措辞、通知、临床验证、真实 pilot、多语言、生产 review daemon、广泛负载测试和最终视觉 polish 保持 deferred。没有发现需要阻断 Round 1 的合同冲突、Schema 重设计、策略变更或许可证冲突。
