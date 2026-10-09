# M0 本地原型状态

更新时间：2026-10-09

## 当前结论

- **P0：** `P0_HANDS_ON_USABLE_WITH_RESET_LIMITATION`。学生 CAT、结果、历史和教师授权数据可供合成演示；正式 P0 仍被安全 Reset 阻断。
- **P1：** `M0_FULL_E2E_NOT_READY`。唯一的新浏览器支持请求经过 RAG、Runtime、Safety 和 Backend 内容解析，最后在 `CLAIM_BOUNDARY` 被拒绝；没有发布回答、citation 或报告。
- **整体：** `M0_BLOCKED`，交由 Controller 审查。本报告不代表 Controller acceptance。

## 集成快照

- 工作树：`D:\Projects\StudentMentalHealthAI-m0-integration`
- 分支：`milestone/m0-end-to-end-engineering-demo`
- 本轮已验证的实现快照：`fb148b8d80925b150dbed5cae0e5afc447868382`
- 本轮基线：`637750286da02b0ae2afbbf0af3601d66712f589`
- 以上是本轮源码与浏览器验证快照；本文件和操作手册作为 docs-only 更新另行本地提交。未 push、未 merge 默认分支、未打 tag。

## 能力矩阵

| 能力 | 本轮现场证据 | 状态 |
|---|---|---|
| Student 登录、退出 | 独立 F 浏览器验证登录、退出 | 通过 |
| CAT | 两条不同 synthetic response 路径，各完成并保存 8 项；刷新后两条新记录仍在历史 | 通过；不代表心理测量有效 |
| 历史持久化 | F 确认本轮两条记录刷新后仍在；整栈重启后的历史恢复沿用先前集成证据，本轮 F 未重复重启验证 | 刷新通过；重启为既有证据 |
| Teacher Dashboard | 浏览器登录、概览、授权主体 `SUBJ_demo_a` 详情；未见原始作答或对话字段 | 授权详情通过 |
| 未授权主体 | `SUBJ_demo_c` 的 Backend GET 返回 403；UI 检查发生在 403 被确认完成之前，未能确认页面拒绝提示 | API 隔离通过；UI 呈现未确认 |
| Demo Reset | 学生首页现显示 `BLOCKED · 暂不可用`；Reset 脚本 fail-closed 并返回 2 | 安全阻断，未执行清理 |
| AI 支持 | 本轮唯一一次浏览器 POST 返回 502 / `DEPENDENCY_INVALID_RESPONSE`，Backend 在 `CLAIM_BOUNDARY` 拒绝 | 未恢复 |
| 支持报告 / citation | 回答未展示；无生成报告 ID、0 条 citation；失败运行诊断已持久化 | 未通过 |
| 启动与停止 | 停止脚本只停止当前工作树登记的 M0 服务；预检 PASS，整栈启动后六个 loopback 服务均为 200 | 通过 |

## 本轮支持请求的安全证据

- 场景：`M0-SUPPORT-ROUTINE-OVERPLAN-V1`，合成教育支持问题。
- 浏览器 `POST /api/v1/support/requests`：**1 次**；无重发。
- Prompt：`PROMPT_student_synthetic_v1@1.1.0`，SHA-256 `8a4ff84416e9477c749e21591a086a79ff020773c7edb41ba0ec55b15f74a7cb`。模板内容未改。
- Runtime profile：`m0-p1-support`；配置文件 `06_llm-runtime/config/runtime.m0-p1-support.v1.json`；`max_attempts=1`、cloud fallback 关闭、无本地 fallback。
- 模型：`qwen2.5:0.5b`，digest `a8b0c51577010a279d933d14c2a8ab4b268079d44c5c8830c0a93900f1827c67`；硬件探测为 RTX 3060 / 12 GiB。
- Backend 持久化的最新 `support_run`：`FAILED` / `CLAIM_BOUNDARY` / `dependency_invalid_response` / `candidate_persisted=false`；安全 trace 为 `TRACE_726a8687e0c619c04c798914075311ad`。
- 实际 provider metadata：`attempt_count=1`、`retry_count=0`、`fallback_attempted=false`、`fallback_count=0`。Runtime 请求过一次，没有自动重试或模型 fallback。
- Runtime 与 RAG 已执行；Output Safety 通过后流程推进到 `CONTENT_VALIDATION`，GenerationContent 解析完成。精确 Safety action 未写入失败记录。随后 Backend `CLAIM_BOUNDARY` fail-closed，citation binding 未发生。
- 回答未显示或持久化；没有生成报告，citation 数为 0。刷新后 UI 显示一条失败支持历史项；该项不是成功报告。
- 语义故障分类：`INDETERMINATE`。持久化安全元数据不包含候选语义或极性；未推断肯定式或否定式内容。

## Reset 阻塞

- `reset-demo.ps1` 当前安全返回退出码 2；不停止服务、不连接数据库、不改数据。
- 旧 `smhai_m0_demo` 中 `audit_events`、`idempotency_records` 等记录没有足够的逐条 M0 ownership 标记，不能安全删除。`SYNTHETIC` 标记本身不足以证明归属。
- 数据库用户有全局 `CREATE`，但 `ALL PRIVILEGES` 仅覆盖现有 `smhai_m0_demo`；未观察到 `GRANT OPTION`。schema 列表只有旧库；本轮没有创建新 schema，也没有删除旧记录。
- Reset UI 已明确显示阻断状态。不要通过手工 SQL、DROP schema、添加标签或切换共享数据库绕过。

## 验证记录

- Frontend：全量 Vitest **34 passed / 10 files**；typecheck、lint、production build 均通过。Reset UI 聚焦测试 9/9 通过。
- Backend：全量 pytest **133 passed**；聚焦 D3 chain/trust-context 25 passed；Pyright 对改动文件 **0 errors**。
- LLM Runtime：全量 pytest **34 passed, 1 skipped**。跳过项是需要显式开启的真实 Ollama 集成测试；本轮未额外直接调用 Runtime generation。
- Ruff check 通过。Runtime 改动文件 format check 通过；Backend format check 在未改动的 `database.py` 行报告 3 处基线格式差异，没有为此重排整文件。
- `git diff --check` 通过。Gitleaks / TruffleHog 未安装，专用 secret scan 未执行。
- 合成危机绕过普通 RAG/Runtime、zero-evidence、EvidenceBundle 和 citation binding 的离线回归通过；本轮没有额外发送 crisis 或 zero-evidence 浏览器请求。
- 独立 F：Student/CAT/History、Teacher 授权详情、Reset UI 和一次支持请求已现场验证；Teacher 未授权页面在 403 完成后的可见状态仍未确认。支持结果为 `QA_BLOCKED`，不是 P0/P1 acceptance。

## 用户操作入口

- 预检：在集成工作树运行 `.\start-demo.ps1 -PreflightOnly`
- 启动：`.\start-demo.ps1`
- UI：`http://127.0.0.1:4173/`
- 停止：`.\stop-demo.ps1`
- Reset：学生首页显示 `BLOCKED · 暂不可用`；手动运行 `.\reset-demo.ps1` 只会返回 2，不会删除数据。
- Teacher 演示账号由本机 Windows User 环境变量保管；本文件不含凭据值。

本原型仅限 synthetic demo，不代表心理学有效性、临床能力、真实学生授权、Real Pilot、D4 Formal 或正式部署验收。
