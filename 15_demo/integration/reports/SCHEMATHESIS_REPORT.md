# Round 1 Schemathesis 契约模糊测试报告

状态：`PASS`（含两类预期警告）  
日期：2026-09-06

## 执行范围

- Schemathesis：`4.25.2`
- 候选文档：`15_demo/integration/contracts/openapi.integration.candidate.json`
- 目标：`http://127.0.0.1:8080`
- 操作：21/21
- 检查：`not_a_server_error`、`status_code_conformance`、`content_type_conformance`、`response_schema_conformance`
- 生成方式：单 worker、确定性生成、`--max-examples 1`、请求超时 10 秒；未启用有破坏性的状态机流程

## 结果

| 阶段 | 结果 |
| --- | --- |
| probing | success |
| schema_analysis | success |
| examples | skip：Schema 没有 examples |
| coverage | 21 passed |
| fuzzing | 21 passed |
| stateful | skip：按本轮配置关闭 |
| 用例 | 541 generated / 541 passed |

原始 NDJSON：[`ndjson-20260906T024400Z.ndjson`](schemathesis-final-5/ndjson-20260906T024400Z.ndjson)。

## 预期警告

1. 17 个操作在没有有效会话凭据时返回 401/403。这证明认证边界生效，不是把未认证请求当成业务成功。
2. 17 个操作的随机生成数据主要被业务校验拒绝。候选文档已经描述响应形状；这类警告反映业务前置条件，而不是 5xx 或响应契约失败。

没有发现服务器错误、状态码不符合文档、Content-Type 不符合文档或响应 Schema 不符合文档的失败用例。测试不替代带合成凭据的业务主路径验收，主路径由真实 smoke 和 Playwright 记录。
