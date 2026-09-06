# Round 1 候选 OpenAPI 变更报告

状态：`PASS`（候选文档，不替换冻结根合同）  
日期：2026-09-06

## 比较对象

| 文档 | 版本 / 范围 | SHA-256 |
| --- | --- | --- |
| `00_architecture/openapi.v1.json` | 冻结根合同，9 个路径 / 9 个操作 | `235C8FDB0B35F2DE870127A18D4CD8C72A1C7795AF02656B2A6C7274AB071897` |
| `15_demo/integration/contracts/openapi.integration.candidate.json` | Round 1 候选，21 个路径 / 21 个操作 | `BE71134A1691C87A5BDF7874C8B68A667897CCD94FFD00497DF7AA24A10757BB` |

候选文档保留冻结根合同的 9 个 operationId：
`getHealth`、`createAssessment`、`recordAssessmentResponse`、`completeAssessment`、`createRetrieval`、`checkSafety`、`createGeneration`、`getReport`、`reviewReport`。

## 验证结果

使用本地 `oasdiff 1.28.0`：

```text
oasdiff breaking 00_architecture/openapi.v1.json 15_demo/integration/contracts/openapi.integration.candidate.json --format markdown --fail-on ERR
exit=0
No breaking changes to report, but specs are different
```

候选文档另经 `openapi-spec-validator` 验证通过，版本为 OpenAPI `3.1.0`。

## 变更性质

候选文档只做集成边界的增量描述：

- 增加 Backend 的会话、认证、CAT 状态、支持请求、报告读取和复核投影路径；
- 补充 RFC 9457 `application/problem+json` 问题响应、401/403/422/502/503/504 语义；
- 描述 HttpOnly 会话 Cookie 与 `X-CSRF-Token` 的安全边界；
- 保留根合同已有路径、Schema 引用、版本和 operationId；
- 生成客户端由候选文档重新生成，并与 canonical 目录逐文件无漂移。

未修改 `00_architecture/openapi.v1.json`、根 Schema、`CONTRACTS.md` 或 Backend API inventory。候选文档仍是 Round 1 交付物，正式根合同变更需另行走版本、迁移和批准流程。
