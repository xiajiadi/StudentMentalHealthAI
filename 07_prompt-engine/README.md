# Prompt Engine · D3 Slice 1

`07_prompt-engine` 是一个独立、可测试的 Prompt 组装模块。它读取已校验的 `assessment.v1`、`generation.v1` 请求和 `knowledge.v1` 引用，按本地只读 registry 选择模板，返回渲染结果或稳定的工程拒绝。

## 当前范围

D3 Slice 1 只覆盖合成工程夹具：模板 ID/版本、角色和语言匹配、大学新生合成人群 mapping、引用约束、确定性 Prompt 哈希、拒绝路径和内部审计投影。当前策略是 `synthetic_demo`，人群是 `UNIVERSITY_FRESHMEN_SYNTHETIC_DEMO`。

本模块不调用 Backend、RAG、Safety、Runtime 或 LLM，也不发布结果。D3-2 的 Backend 接入、模型调用、输出 Safety、持久化和端到端产品链路尚未被本切片接受。

## Registry、模板和哈希

模板和 policy registry 是随代码审查的只读资产。调用方只能选择精确的 `prompt_id`、`prompt_version` 和角色；模块不会选择 `latest`、读取请求提供的模板正文或加载任意路径。模板内容按 UTF-8、LF 规范化后计算 SHA-256，registry 中的哈希必须与实际文件匹配。

当前包含 student、teacher 和 parent synthetic-demo 三个 `1.0.0` 模板。parent 模板只保留合成演示能力，不恢复当前暂停的家长端产品交付。

## 请求与可信上下文

普通请求数据可以表达角色、语言、请求身份和允许的证据身份。审核状态、权利状态、Safety 决定、执行模式、人口资格、角色/风险资格等门控信息必须来自 `TrustedPromptContext` 的受控内部快照；任意 caller mapping 不能通过写入 `approved`、`verified`、`PROCEED` 或 `synthetic_demo` 获得资格。矛盾的请求字段会被拒绝，可信状态优先用于渲染和拒绝。

当前 API 的权限分离是公共库边界：普通消费者使用 `render(..., trusted_context=...)` 时不能用原始 mapping 提升资格。私有测试构造 seam 只用于合成夹具和受控内部 port；它不是加密能力，也不防御同一 Python 进程中主动导入私有名称、修改内存或绕过 API 的恶意代码。

## 心理学与数据边界

本切片不解释 theta、SE、score 或 band，不生成 Level 1–5，不做诊断、临床判断或 theta→危机推断，也不自动通知家长或教师。高风险、危机和需要人工审核的 assessment 会拒绝普通渲染。真实学生数据和真实 pilot 不在本模块范围内。

D3-1 的 Prompt 组装路径要求事实性建议携带本次请求允许的 `source_chunk_ids`，并由 D3-1 的 trusted retrieval validation 将 chunk ID、document ID、citation locator、content hash、审核状态、权利状态和 population/role/risk scope 与可信内部快照比对；缺失、重复、额外或不合格引用会拒绝。D3-3 的 role projection 只接收不含源文本的 opaque citation shape（`source_chunk_id` 与可选 locator），不在本切片重新绑定 trusted RAG/chunk snapshot；该绑定与 D3-4 的 Backend/RAG 接入一起处理。D2 新提交的 14 个来源、58 个 chunk 没有被本模块使用或发布。

## Fixtures and verification

测试继续复用仓库冻结的合成 fixture：
`00_architecture/fixtures/`。这是 Controller 明确批准的选择，不另建 D3 专用 fixture 目录。

在候选 worktree 根目录运行：

```powershell
$env:PYTHONPATH = "$PWD\07_prompt-engine\src"
& D:\Projects\StudentMentalHealthAI-structured-output-compat\09_backend\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider 07_prompt-engine\tests
& D:\Projects\StudentMentalHealthAI-structured-output-compat\09_backend\.venv\Scripts\python.exe -m ruff check 07_prompt-engine\src 07_prompt-engine\tests
& D:\Projects\StudentMentalHealthAI-structured-output-compat\09_backend\.venv\Scripts\python.exe -m pyright --project 07_prompt-engine\pyrightconfig.json
& D:\Projects\StudentMentalHealthAI-structured-output-compat\09_backend\.venv\Scripts\python.exe -m compileall -q 07_prompt-engine\src
```

项目 Root Gate 仍使用现有的：

`00_architecture\tests\run_contract_checks.ps1`

它验证冻结 Contract、Schema 和 OpenAPI；通过 Root Gate 不等于 D3-2 或全产品集成已接受。

## D3 Slice 3 · Role Projection & Minimum Disclosure R1

D3-3 位于本模块的独立 role_projection 子模块。它接收 D3-2 的
role-neutral interpretation_result.v1，结合受控的 audience context 和精确
的 role-projection policy，生成供后续 Prompt 处理的结构化投影。D3-3 不做
CAT 计算、心理学解释、自然语言生成、Safety 决策、RAG 检索或 Backend
编排；D3-4 仍未开始。

### 调用边界

核心入口是：

    from prompt_engine.role_projection import project, prompt_input

    result = project(
        source_result,
        policy_reference,
        trusted_audience_context,
        citations=approved_citations,
    )
    prompt_payload = prompt_input(result.prompt)

project 要求传入精确的 policy_id、policy_version 和 policy_hash，
并校验 D3-2 source status、角色、用途、关系、执行模式和披露授权。策略
registry 位于
07_prompt-engine/assets/role_projection_policy_registry.v1.json，结果结构
位于 07_prompt-engine/schemas/role_projection_result.v1.schema.json。

TrustedAudienceContext 只能通过受控的内部/test seam 构造；普通
dict/JSON 不能凭自己写入角色、关系、用途或授权。这个 seam 是进程内的
capability-like 边界，不是加密隔离，也不防御同一 Python 进程中主动导入
私有名称、改写内存或绕过 API 的恶意代码。真实身份、关系、认证和法律/
监护人同意流程属于后续 Backend 边界，当前没有实现。

### 当前策略与角色

当前 registry 只有三条明确版本化策略，全部为 SYNTHETIC_DEMO only，
只接受 D3-2 的 MEASUREMENT_ONLY，且 allowed_claim_codes 为空：

| 角色 | 用途 | 关系 | 当前公开结果 |
|---|---|---|---|
| STUDENT_SELF | SELF_UNDERSTANDING | SELF | READY_FOR_PROMPT；仅公开 D3-2 允许的安全限制和引用，当前没有心理学 claims |
| TEACHER_SUPPORT | EDUCATIONAL_SUPPORT | ASSIGNED_SUPPORT | NO_PERSONALIZED_DISCLOSURE；claims、limitations 和 citations 均为空 |
| PARENT_DEMO | SYNTHETIC_PARENT_DEMO | SYNTHETIC_DEMO | NO_PERSONALIZED_DISCLOSURE；当前只保留合成演示入口，不公开个性化内容 |

SYSTEM_ADMIN 和 UNKNOWN 不是心理内容 audience，使用相同的粗粒度
拒绝形状。真实用户模式、真实家长披露和年龄单独授权均会 fail closed；
17 岁不会自动授予家长访问权。当前家长端产品交付仍暂停。

策略选择使用 canonical JSON SHA-256，并在 registry 加载和实际使用前再次
校验 typed policy 的 hash。不存在 latest、default、wildcard 或其他
隐式 fallback。投影只允许保留、删除、脱敏或压制 D3-2 已批准的 claims，
不能新增、升级、重解释或合并成更强的心理学 claim。

### PromptFacingProjection 与 AuditProjection

D3-3 提供两个不同的 typed surface：

- PromptFacingProjection 只包含 status、claims、limitations 和
  citations。它通过显式 allowlist 构造，不包含 policy identity、review
  metadata、关系/授权细节、Safety action、压制原因或内部 trust metadata。
- AuditProjection 保存受控审计字段，例如 policy identity、source status、
  Safety action、trusted relation、review metadata、emitted/suppressed claim
  codes 和请求追踪标识。它不能传给 prompt_input；Prompt-facing API 会拒绝
  combined result 或 audit surface。

Prompt-facing denial 使用稳定的粗粒度形状，避免暴露 hidden claim、construct、
结果是否存在或 suppressed count。当前实现不向 Prompt surface 重建
theta、SE、score、band、interval 或 latent value，也不生成诊断、风险、
临床严重度、危机或治疗语义。D3-2 的 BYPASS_SAFETY 会停止普通投影，
Safety action 只保留在 audit，不泄露给 Teacher/Parent payload。

### 状态与数据边界

当前 canonical projection statuses 包括
READY_FOR_PROMPT、NO_PERSONALIZED_DISCLOSURE、各类 ABSTAIN_*、
ABSTAIN_SOURCE_STATUS 和 BYPASS_SAFETY。详细拒绝原因留在 audit；公共
结果只返回允许的粗粒度状态。D2 新提交的 14 个来源和 58 个 fragments
未被本模块使用或发布。

D1 当前仍是 RECEIVED / REVISIONS_REQUIRED / SIGNATURE_BLANK，不能从该
状态推导心理学批准。真实学生数据和真实 pilot 仍禁止/阻塞；当前策略、
测试和演示只使用合成 fixture。

### D3-3 verification scope

D3-3 的专项测试位于：

- 07_prompt-engine/tests/test_role_projection.py
- 07_prompt-engine/tests/test_role_projection_contracts.py

现有 Prompt Engine 的 pytest、Ruff、Pyright、compile/import 和 Root Gate
命令仍适用；Lead 负责记录本轮 fresh 结果、D3-1/D3-2 回归、机器证据和
Controller review 状态。D3-3 工程实现不等于心理学批准、real-pilot
readiness 或 production readiness。
