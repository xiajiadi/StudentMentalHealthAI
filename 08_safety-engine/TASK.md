# 08_safety-engine：安全规则与人工复核

## 职责

- 对 Assessment 执行生成前风险检查；
- 对模型候选执行输出后检查；
- 维护规则集、reason codes、阻断状态和人工复核状态；
- 对高风险和不确定情况提供确定性的熔断路径；
- 提供普通、边界和高风险测试集及审计结果。

## 输入

- assessment.v1 的脱敏结果；
- Generation Candidate 和结构化输出；
- 目标角色、用途和当前安全配置；
- 已审核的本地转介/提示配置；
- 安全测试案例及 expected behavior。

## 输出

- precheck/postcheck 状态；
- risk level、reason codes、human_review_required；
- allow、warn、block、needs_review 等操作决策；
- 面向用户的已审核安全提示引用；
- 可审计的规则集版本和检查记录。

## 禁止事项

- 不做临床诊断、治疗决策或危机干预替代；
- 不仅依赖 Prompt，也不能被 Prompt 绕过；
- 不在没有经确认配置时编造联系人、电话或应急流程；
- 不把高风险结果降级为 normal 以便演示通过；
- 不泄露敏感原文、规则内部细节或完整模型上下文给普通用户。

## 接口

- precheck(assessment.v1) -> Safety Result；
- postcheck(generation_candidate) -> Safety Result；
- decide(safety_result) -> allow/warn/block/needs_review；
- get_escalation_message(reason_code, locale) -> approved message；
- 输出与 Generation Schema 对齐的 safety 对象和状态。

## 验收标准

- high 和 crisis 必须触发人工复核或安全阻断；
- 后检发现诊断、保证效果、危险建议、虚构引用或越权内容时不能放行；
- 规则集版本、reason codes 和审计 ID 始终可追踪；
- 规则误报/漏报案例都有记录，不把测试结果包装成临床有效性；
- 转介配置缺失时能安全失败；
- Safety Engine 能在模型不可用和模型可用两种情况下独立运行。

## 交付物

- Precheck/Postcheck 接口和规则执行器；
- reason code 注册表；
- 普通、边界、高风险安全 fixture；
- 人工复核状态机说明；
- 安全测试报告、限制和待确认的本地流程清单。

## Round 1 执行说明

- 内部实现位于 `src/safety_engine/`；第三方库只允许通过 adapters 进入内部契约。
- 稳定控制动作是 `PROCEED`、`PROCEED_WITH_BOUNDARY`、`BLOCK`、`REVIEW_REQUIRED`、`CRISIS_ROUTE`；它们不是临床风险等级。
- OPA 是 loopback-only 的必选本地 sidecar；策略文件在 `policies/`，真实策略校验由 OPA CLI 和 REST 运行时共同证明。
- Round 1 的危机样本必须显式标记为 synthetic fixture；模板位于 `templates/crisis/`，状态为 `PENDING_PSYCH_REVIEW`，不包含联系人或电话号码，也不自动通知监护人。
- Qwen3Guard、NeMo、Presidio 的实际兼容性由 `evaluation/harness.py` 运行并写入 `reports/`；Mock 只用于单元测试。
- 检索安全由 `RetrievalSafetyAdapter` 实现，不实现 RAG；因 NeMo IORails 当前没有检索表面，状态明确记录为 `PARTIAL`。
- 详细冻结决策、数据契约、错误语义与限制见 `SAFETY_TECHNICAL_DECISION_V1.md`。

## Round 1 Checklist

- [x] SAFETY-R1-01 Governance：模块边界、数据边界和停止条件已记录。
- [x] SAFETY-R1-02 Technical decision：D-01 至 D-30 已写入冻结决策。
- [x] SAFETY-R1-03 NeMo research：官方 IORails 和当前版本已核验。
- [x] SAFETY-R1-04 Qwen3Guard research：官方模型、revision、输出格式已核验。
- [x] SAFETY-R1-05 Presidio research：官方 Analyzer/Anonymizer API 已核验。
- [x] SAFETY-R1-06 OPA research：官方二进制、REST、Health、Rego 和 CLI 已核验。
- [x] SAFETY-R1-07 Third-party notices：版本、revision、许可证和来源已记录。
- [x] SAFETY-R1-08 Runtime compatibility：Python 3.12、Windows、CPU 和 D 盘缓存已记录。
- [x] SAFETY-R1-09 Domain contracts：Context、Signal、Decision、Trace、ReviewCase 已实现。
- [x] SAFETY-R1-10 Safety Service：输入、输出、检索和健康边界已实现。
- [x] SAFETY-R1-11 NeMo adapter：IORails 输入/输出检查已实现。
- [x] SAFETY-R1-12 Qwen3Guard adapter：本地 CPU provider 和输出归一化已实现。
- [x] SAFETY-R1-13 Presidio adapter：真实检测、脱敏和匿名元数据接口已实现。
- [x] SAFETY-R1-14 Chinese PII recognizers：手机、邮箱、中国居民身份证和合成学号已覆盖。
- [x] SAFETY-R1-15 OPA sidecar：loopback 进程管理和生命周期已实现。
- [x] SAFETY-R1-16 Policy client：仅发送归一化信号并校验动作词表。
- [x] SAFETY-R1-17 Base policies：危机、组件故障、内容、隐私和披露策略已实现。
- [x] SAFETY-R1-18 Crisis route：确定性危机路径已实现。
- [x] SAFETY-R1-19 Crisis templates：五个角色模板均为 `PENDING_PSYCH_REVIEW`。
- [x] SAFETY-R1-20 Clinical boundary：工程级越界规则已实现，不计算临床指标。
- [x] SAFETY-R1-21 Disclosure policy：FULL/SUMMARY/REDACTED/HIDDEN 矩阵已实现。
- [x] SAFETY-R1-22 Human review：状态机、内存仓储和可选 SQLite 已实现。
- [x] SAFETY-R1-23 Fail-closed：策略、隐私、护栏、模型和复核故障均不静默放行。
- [x] SAFETY-R1-24 SafetyTrace：版本、组件、信号 ID、延迟和故障标志已实现。
- [x] SAFETY-R1-25 Synthetic corpus：11 个合成 fixture 已建立。
- [x] SAFETY-R1-26 Evaluation harness：真实组件、路由和熔断证据已生成。
- [x] SAFETY-R1-27 Unit tests：模块单元测试已通过。
- [x] SAFETY-R1-28 Integration tests：NeMo、Presidio、OPA 真实集成已通过。
- [x] SAFETY-R1-29 End-to-end：FastAPI 内部边界与真实评估路径已通过。
- [x] SAFETY-R1-30 Safety Local Contract Compatibility：7/7 冻结 root fixture/schema 兼容性检查已通过且未修改根文件；repository-wide official Root Gate 见 Closure 证据。
- [x] SAFETY-R1-31 Acceptance：验收报告和机器可读证据已生成。

## Safety Round 1 Acceptance Closure

| ID | Closure item | Status |
|---|---|---|
| SAFETY-R1-CLOSE-01 | Reproduce current module state | DONE |
| SAFETY-R1-CLOSE-02 | Inspect official root contract suite | DONE |
| SAFETY-R1-CLOSE-03 | Execute repository-wide root suite | DONE |
| SAFETY-R1-CLOSE-04 | Verify Qwen3Guard checkpoint provenance | DONE |
| SAFETY-R1-CLOSE-05 | Real Qwen3Guard load | DONE |
| SAFETY-R1-CLOSE-06 | Real safe fixture inference | DONE |
| SAFETY-R1-CLOSE-07 | Real unsafe fixture inference | DONE |
| SAFETY-R1-CLOSE-08 | Real ambiguous/controversial fixture inference | DONE |
| SAFETY-R1-CLOSE-09 | Verify SafetySignal normalization | DONE |
| SAFETY-R1-CLOSE-10 | Regenerate safety_round1_evaluation.json | DONE |
| SAFETY-R1-CLOSE-11 | Regression NeMo | DONE |
| SAFETY-R1-CLOSE-12 | Regression Presidio | DONE |
| SAFETY-R1-CLOSE-13 | Regression OPA | DONE |
| SAFETY-R1-CLOSE-14 | Regression Crisis Route | DONE |
| SAFETY-R1-CLOSE-15 | Regression Human Review | DONE |
| SAFETY-R1-CLOSE-16 | Regression Fail Closed | DONE |
| SAFETY-R1-CLOSE-17 | Regression Disclosure | DONE |
| SAFETY-R1-CLOSE-18 | Regression SafetyTrace | DONE |
| SAFETY-R1-CLOSE-19 | Run module tests | DONE |
| SAFETY-R1-CLOSE-20 | Run Ruff / Pyright | DONE |
| SAFETY-R1-CLOSE-21 | Verify Frozen Contract unchanged | DONE |
| SAFETY-R1-CLOSE-22 | Create Closure Evidence | DONE |
| SAFETY-R1-CLOSE-23 | Update original Acceptance Report | DONE |

Closure evidence:

- `reports/SAFETY_ROUND1_CLOSURE_EVIDENCE.md`
- `reports/ROOT_CONTRACT_RECHECK.md`
- `reports/QWEN3GUARD_REAL_EVIDENCE.md`
- `reports/safety_round1_evaluation.json`
