# D3_SLICE1_ACCEPTANCE_CLOSURE_EVIDENCE

状态：`READY_FOR_CONTROLLER_REVIEW`

验收边界：`EXECUTION_LEAD_REVIEW` / `NOT_CONTROLLER_ACCEPTED`

本文件记录 Controller 已授权的 D3 Slice 1 bounded closure。它只覆盖可信上下文边界、Pyright、README 和回归验证；不授权 D3-2、Backend 接入或任何已接受模块变更。

## 1. Original PARTIAL_PASS

上一轮 Execution-Lead review 为 `PARTIAL_PASS`，阻塞项为 caller-forgeable review/rights/Safety/provenance fields、Pyright touched-scope errors 和缺少 README。

## 2. Controller Repair Authorization

本轮 Controller verdict 为 `D3_SLICE1_PARTIAL_PASS / BOUNDED_ACCEPTANCE_CLOSURE_AUTHORIZED`。允许修改范围仅为 `07_prompt-engine` 源码、测试、README、Pyright 配置及批准的 D3 closure evidence。

## 3. Candidate / Branch / Commit

- worktree: `D:\Projects\StudentMentalHealthAI-v09-integration`
- closure branch: `fix/d3-slice1-acceptance-closure-v1`
- baseline HEAD: `7d0bebe37b9c6c2d20ad1bbc69ee5a111e76c333`
- closure commit: recorded in the final Execution-Lead handoff after the single local commit
- merge/push/tag: none

## 4. Trust Boundary Root Cause

原 API 将普通 mapping 作为 context，直接信任 `execution_mode`、Safety action、content population、chunk review/rights/scope 和 assessment risk。caller 将 pending/unknown 改为 approved/verified 并提供 `PROCEED` 后，结果会从拒绝变成 `PROMPT_RENDERED`。

## 5. Trust Boundary Design

新增不可由普通 mapping 构造的 `TrustedPromptContext` 与 `TrustedChunkContext`。`render()` 只接受可信上下文对象；raw mapping 直接返回 `TRUSTED_CONTEXT_REQUIRED`。可信快照包含 execution/Safety/population/risk 和每个 chunk 的 document、hash、citation locator、review/rights、population/role/risk 状态。请求字段必须与可信快照一致，矛盾即拒绝，渲染使用可信状态。

可信构造 seam 是私有、进程内的内部/test builder；文档明确它不提供加密能力，也不防御同一 Python 进程中主动导入私有名称、改写内存或绕过公共 API 的恶意代码。

## 6. Public vs Trusted Inputs

公共请求保留 assessment、generation request、policy reference、chunk 内容和请求身份等普通输入。审核、权利、Safety、执行模式、人口资格和风险资格只能来自 `TrustedPromptContext`。模板和 policy registry 继续是代码随附的只读内部资产。

## 7. Forgery Negative Tests

新增并通过 8 个负向测试：raw mapping、review forged、rights forged、Safety forged、synthetic claim、population claim、scope mapping、risk state。关键 probe：可信状态为 pending/unknown 时，caller 改成 approved/verified 仍返回 refusal，不会渲染。

## 8. Template Regression

三个模板均保持 `1.0.0`、原始角色/语言/purpose 和原有 SHA-256。三角色正常路径仍通过。

## 9. Citation Regression

精确 chunk identity、document identity、locator、content hash、缺失/额外/重复引用拒绝均保持通过。D2-N1 新 intake 未被使用。

## 10. Psychology Boundary

无 Level 1–5 executable logic、theta/score/band interpretation、diagnosis、clinical band、theta→crisis 或自动 caregiver/teacher notification。高风险、危机和人工复核状态仍拒绝普通渲染。

## 11. Human Review Alignment

当前大学新生方向和合成范围保持不变；17 岁可能涉及未成年人所需门槛未被降低；家长生产交付仍暂停，仅保留 synthetic/demo；D2 新材料仍未发布。

## 12. README Delivery

新增：`07_prompt-engine/README.md`。内容覆盖模块目的、范围、registry/version/hash、可信上下文、公共库安全边界、合成-only、大学新生、parent demo、心理学限制、引用、fixture 来源、验证命令和 Backend 未接受状态。

## 13. Fixture Directory Controller Omission

未创建专用 D3 fixture 目录。Controller 已批准继续复用 `00_architecture/fixtures/`；README 已记录该决定。

## 14. Pyright Diagnosis

上一轮 27 个错误来自 jsonschema 未标注属性、engine 类型收窄/Optional 处理和 tests import path。通过窄范围 third-party wrapper、明确类型收窄和 `07_prompt-engine/pyrightconfig.json` 的 `src` extra path 解决；没有关闭规则、排除模块或 blanket `type: ignore`。

## 15. Pyright Closure

命令：

`D:\Projects\StudentMentalHealthAI-structured-output-compat\09_backend\.venv\Scripts\python.exe -m pyright --project D:\Projects\StudentMentalHealthAI-v09-integration\07_prompt-engine\pyrightconfig.json`

结果：`0 errors, 0 warnings, 0 informations`。

## 16. Fresh Tests

命令：

`D:\Projects\StudentMentalHealthAI-structured-output-compat\09_backend\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider D:\Projects\StudentMentalHealthAI-v09-integration\07_prompt-engine\tests`

结果：`48 passed in 0.49s`，0 failed，0 skipped，0 warnings。

## 17. Ruff

`ruff check 07_prompt-engine/src 07_prompt-engine/tests`：`All checks passed!`，0 findings。

## 18. Compile/import

`compileall` exit 0；`import prompt_engine` 成功。

## 19. Root

canonical `00_architecture/tests/run_contract_checks.ps1`：13 tests passed，exit 0。

## 20. OpenAPI

Root Gate 报告 `openapi.v1.json: OK`。

## 21. Frozen Root

8/8 frozen artifacts 与 C baseline `7d0bebe...` 的 Git blob 一致；没有修改 Contract、Schema 或 OpenAPI。

## 22. Real Data

真实学生数据：`NONE`。只使用公开、合成或脱敏 fixture。

## 23. Changed Files

允许范围内的 D3 文件为：

- `07_prompt-engine/src/prompt_engine/engine.py`
- `07_prompt-engine/src/prompt_engine/contracts.py`
- `07_prompt-engine/src/prompt_engine/__init__.py`
- `07_prompt-engine/tests/test_prompt_engine.py`
- `07_prompt-engine/pyproject.toml`
- `07_prompt-engine/pyrightconfig.json`
- `07_prompt-engine/README.md`
- 原有 D3 registry、模板和其余 Prompt Engine 文件保持不变

## 24. Scope Integrity

没有修改 Backend、RAG、Safety、Runtime、Database、frontend、D2-N1 intake、C worktree 或冻结根文件。未暂存 D1/D2/integration/governance overlays。

## 25. Deferred Governance Overlay

候选中旧 governance overlay 的 reconciliation：`DEFERRED_TO_BASELINE_CONSOLIDATION`。本轮不修改或纳入其内容，主仓库 `D:\Projects\StudentMentalHealthAI\AGENTS.md` 仍是唯一治理权威。

## 26. Remaining P0

当前 D3-1 closure gate 的 P0：`NONE`。D3-2 和产品集成仍未接受。

## 27. Remaining P1

- 后续 D3-2 需要单独规格和 Controller 授权。
- 候选治理 overlay 需在 V0.9 baseline consolidation 时 reconciliation。
- hostile same-process Python 绕过不在本模块安全承诺内。

## 28. Execution Lead Recommendation

`D3_SLICE1_READY_FOR_CONTROLLER_REVIEW`。这不是 `CONTROLLER_ACCEPTED` 或 `FINAL_ACCEPTED`。

## 29. Controller Review Focus

Controller 请核对可信上下文设计、8 个伪造负向测试、48 项 fresh suite、Pyright 0、README 内容、无 unrelated staging，以及单个本地 closure commit。保持 D3-2 停止状态。

## 30. Worker Dispatch Ledger

| worker | model | reasoning | fork_turns | read scope | write scope | result | Lead review |
|---|---|---|---|---|---|---|---|
| `/root/d3_pyright_diagnosis` | `gpt-5.6-luna` | `max` | `none` | Pyright diagnosis | none | dispatch did not return before Lead completion | Lead independently diagnosed and fixed; no Worker write trusted |

本轮未修改任何不相交的 D1/D2/governance 文件，未创建递归 Worker。
