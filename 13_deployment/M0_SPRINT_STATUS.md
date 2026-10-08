# M0 本地原型状态

更新时间：2026-10-09

状态：**P0 主业务链路已通过真实浏览器操作；P0 验收仍受安全重置阻塞。P1 正常支持链仍被 Backend CLAIM_BOUNDARY 拦截。**

## 当前集成快照

- 集成工作树：`D:\Projects\StudentMentalHealthAI-m0-integration`
- 分支：`milestone/m0-end-to-end-engineering-demo`
- 本轮真实浏览器与整栈验证代码快照：`27ca23a00901bb36fe04decb58e1ccf4b592b846`
- 冲刺基线：`3c1bd71c85a4ef618cb11adcaa87d4858fda628a`
- 本地修改和提交仅用于该 M0 分支；未 push、未 merge 默认分支、未打 tag。

## 能力矩阵

| Capability | API | UI | 持久化 | 状态 / 阻塞 |
|---|---|---|---|---|
| Synthetic Student 登录、退出和重登 | 真实 Backend | 已验证 | 用户和会话由本机服务处理；退出后 `/auth/me` 为 401 | 通过 |
| CAT 测评 | 真实 CAT + Backend | 两条不同作答路径已验证 | 刷新恢复；完成结果重启后可读 | 通过；规则化合成演示，不代表已验证心理测量 |
| 学生测评与历史 | 真实 Backend + MySQL | 开始、答题、停止、结果、历史均已验证 | 整栈重启后历史仍在 | 通过 |
| Teacher Dashboard | 真实 Teacher API + MySQL | 概览、授权学生详情、无权主体拒绝均已验证 | 来自当前合成数据库记录 | 通过；只显示非临床摘要 |
| 教师 / Reviewer 退出 | 服务端 logout | 教师真实浏览器已验证；Reviewer 有 focused UI tests | 服务端会话撤销 | 源码与测试通过；Reviewer 未做现场登录 |
| AI 支持 | 真实 Backend → RAG → Runtime → Safety → Backend gate | 1 次真实合成 UI 提交 | 新建运行记录为 `FAILED`；candidate 未保存，无报告 | 阻塞于 `CLAIM_BOUNDARY` |
| Citation / 报告 / 支持历史 | 有路径 | 本轮请求未到发布阶段 | 无新报告、0 条引用 | 未通过；没有伪造答案 |
| 一键启动 / 停止 | 本机脚本 | 启动后可用浏览器访问 | MySQL demo schema | 启动、readiness、停止和重启已验证 |
| Demo Reset | 脚本 fail-closed | 页面明确显示不可用 | 未清理任何数据 | 阻塞；没有逐条 M0 marker，禁止手工 SQL 或 DROP DATABASE |

## 真实浏览器证据

- 学生以合成账号登录，完成两次 8 项测评。`never` 路径题目序列为 `008, 003, 002, 001, 004, 006, 009, 005`；`always` 路径为 `008, 003, 005, 007, 002, 009, 001, 004`。路径在第 3 题分叉；服务端按配置达到 8 项停止条件并保存结果。
- 测评中途刷新后恢复同一测评和已保存作答；完成后进入学生历史。服务栈停止并重新启动后，两次完成结果仍可从 UI 打开。
- 学生退出后，向 Backend 查询认证状态返回 401；随后重新登录成功，首页仍显示前述两条已完成测评。教师退出后 `/auth/me` 返回 401；教师概览展示授权范围内的合成记录，未知主体详情页显示无权访问。
- 本轮从已完成测评结果页进入支持对话，提交了 1 次合成请求。页面显示 Backend 拒绝发布；MySQL 最新 `support_run` 为 `FAILED`，白名单字段为 `failure_stage=CLAIM_BOUNDARY`、`failure_code=dependency_invalid_response`、`failure_component=BACKEND`、`candidate_persisted=false`。candidate 原文只在 Backend 内存中解析，未持久化或展示；当前测评没有新报告或引用。
- 故障分类：`INDETERMINATE`。留存的白名单数据库诊断没有候选字段语义/极性，不能据此断定肯定式断言或否定式边界说明。
- 支持请求计数：本轮真实 UI 提交 1 次；前端 `send` 对应一次 `createSupport`，没有客户端自动重试。Runtime 配置允许最多 2 次 provider attempt；Backend 当前丢弃 Runtime trace，因此本次 provider-level `retry_count` 无法从持久化元数据独立核实，状态为 **NOT_EXPOSED**，不报告为已证明的 0。

## CAT 与教师的当前含义

CAT 分支来自当前合成规则选择器，能观察到回答影响后续题目及配置停止条件。结果页明确标识 `SYNTHETIC / DEMO / 非诊断`，不提供心理学解释。教师端只显示授权范围内的合成测评状态与聚合计数，不返回作答、量表参数或对话正文。

## 验证记录

测试结果来自本轮集成中各模块 fresh 执行；不同命令的测试集合有重叠，不应相加：

- Frontend：`vitest run` **33 passed / 10 files**；typecheck、build、lint 均通过。
- Backend：集成后的全量 pytest **118 passed**；教师服务/路由 **6 passed**，Ruff 通过。
- CAT demo service：**4 passed**；Backend CAT/assessment：**8 passed**。
- Prompt engine：**56 passed**；D3 Backend integration / chain：**48 passed**。
- `git diff --check`：通过。Gitleaks/TruffleHog 未安装，未报告为已执行。
- 零证据弃答、合成危机绕过普通 RAG/Runtime 和 claim gate 有离线回归测试；本轮未通过额外浏览器请求触发危机或零证据场景。
- 独立 F 复核：最新退出实现源码检查通过；文档在复核时仍落后，当前文件刷新后待 F 只读复核。独立 Reviewer 未重复运行本机服务或测试。

## 主要阻塞

1. **P0 Reset：** `reset-demo.ps1` 当前返回 2，不连接数据库、不停止服务、不改数据。`audit_events` 和 `idempotency_records` 缺少足以证明每条记录属于 M0 的关联标记，现有 `SYNTHETIC` 来源不足以安全清理。
2. **P1 Support：** Prompt 改进后的一次真实支持请求仍在 Backend `CLAIM_BOUNDARY` 失败；没有已批准回答、citation 或报告。候选原文未持久化，本次安全元数据不足以确定语义分类。
3. **Runtime trace：** `HttpLLMRuntimeClient` 未将 Runtime 的 attempt/retry metadata 保留到 allowlisted diagnostics，provider-level retry 数不能现场核实。
4. **Demo account：** 已创建本地 `m0_teacher_demo` synthetic teacher，仅获得原 teacher seed 对两个 active synthetic subject 的相同授权范围。Windows User 环境保存 `SMHAI_M0_TEACHER_USERNAME` 与 `SMHAI_M0_TEACHER_PASSWORD`；密码未写入仓库或聊天。新账号 API 登录、Teacher overview（200）、logout 和 logout 后 `/auth/me`（401）已验证；浏览器 Teacher 场景使用原 synthetic seed account。

## 操作入口

- 启动：在集成工作树执行 `.\start-demo.ps1`
- 预检：`.\start-demo.ps1 -PreflightOnly`
- UI：`http://127.0.0.1:4173/`
- 停止：`.\stop-demo.ps1`
- 重置：`.\reset-demo.ps1` 当前会安全返回阻断码 2；不要尝试手工数据库清理。

本原型仅使用合成数据，不代表心理学有效性、临床能力、真实学生授权、Real Pilot、D4 Formal 或正式部署验收。
