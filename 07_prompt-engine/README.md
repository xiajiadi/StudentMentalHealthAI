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

所有事实性建议必须携带本次请求允许的 `source_chunk_ids`。chunk ID、document ID、citation locator、content hash、审核状态、权利状态和 population/role/risk scope 必须同时符合可信内部快照；缺失、重复、额外或不合格引用会拒绝。D2 新提交的 14 个来源、58 个 chunk 没有被本模块使用或发布。

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
