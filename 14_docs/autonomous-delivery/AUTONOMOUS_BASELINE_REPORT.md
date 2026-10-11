# PsyNova 自动交付基线审计

审计日期：2026-10-11
状态：`PARTIAL_PASS`，提交 Project Controller review；不是阶段验收、真实 pilot 批准或交付结论。
范围：Phase I 合成数据工程基线；不读数据库行、不登录 MySQL、不生成模型回答、不启动/停止服务、不执行旧数据库 reset。

## Git 与工作区

- M0 基线：`74372fef547ea6d0eba0e88fd5dd44750d7f1f8e`；初始核验时本地 M0 与 `origin/milestone/m0-end-to-end-engineering-demo` 指向同一提交。
- 当前集成分支：`xiajiadi/autonomous-delivery-20261011`，当前 `HEAD` 仍为上述基线 SHA。基线与当前分支名分开记录；没有提交、推送、合并或打标签。
- 当前工作区包含 Controller 的 `.gitignore`、runner 和 autonomous-delivery 文档改动；这些在审计时尚未纳入 HEAD。保留既有用户未跟踪内容：`10_frontend/output/` 和 `10_frontend/public/assets/heartbridge/login-mark-v2.png`。后一个素材目前未被源码引用。
- 冻结接口仍按 `assessment.v1`、`knowledge.v1`、`generation.v1`、`api.v1` 检查；本审计不修改合同、不用旧 D4 文档覆盖当前 Mission。

## 运行依赖与现场状态

```text
Vue 3 / TypeScript / Vite 前端
  -> FastAPI 后端与 auth / assessment / teacher / support 域
  -> MySQL 持久化适配器（项目演示目标端口 3307）
       -> CAT engine / assessment adapter
       -> Knowledge Pipeline 发布工件 -> RAG（M0 配置为 BM25）
       -> 本地 LLM Runtime（M0 support profile，单次尝试）
       -> Safety / policy decision -> Backend Claim Boundary -> 持久化/响应
```

CAT 引擎核心目前使用 `adaptivetesting==1.2.1`，以合成 GRM 配置做 EAP/BM 估计、MFI 选题、停止判断和 trace；这只证明合成工程流程。Safety 路径对危机输入走单独路由，正常生成链路受 fail-closed gate 约束。演示启动脚本规定 MySQL 3307 和各本地 API/UI 端口；全局 MySQL 3306 不属于本项目恢复范围。

本轮安全现场检查发现：`mysqld` 仅在 `[::]:3306` 监听；3307、4173、8080、8160、8170、8180、8181、8190、11434 均无监听。`start-demo.ps1 -PreflightOnly` 新鲜执行返回退出码 1，报告项目数据库 3307 不可用且存在旧 process manifest。尚未核实 manifest 中 PID/进程所有权，所以没有停止进程或重启服务。`reset-demo.ps1` 当前源码明确阻止 reset，因为缺少逐记录 M0 所有权标记；未执行 reset。未连接数据库，未读取现有数据、权限或密钥，也未调用 Ollama/Runtime。

## 能力与验证状态

| 能力 | 状态 | 源码/证据与边界 |
|---|---|---|
| CAT 合成算法、会话 trace 与模拟 | `VERIFIED_WORKING` | `01_cat-engine/src/cat_engine/providers/adaptivetesting_provider.py`、`api/app.py`；本轮 `tests/unit tests/integration tests/simulation` 28 项通过。只证明合成样本工程行为，不证明题库质量、心理测量学效度或临床解释。 |
| 学生 CAT 到持久化结果的真实 MySQL 闭环 | `IMPLEMENTED_NOT_VERIFIED` | Backend 与数据库 adapter 路径存在；当前 3307 不可用，未做 MySQL 登录、浏览器或真实端到端验证。历史 M0 记录不能替代当前运行证据。 |
| 账号、密码校验、会话和角色授权 | `IMPLEMENTED_NOT_VERIFIED` | `09_backend/src/smhai_backend/adapters/database.py`、`domains/auth/` 有数据库 auth 路径；本轮 backend focused tests 使用内存仓库，不能证明 MySQL 账户登录。 |
| 多角色投影 | `PARTIAL` | `domains/auth/schemas.py:17-22` 的 `ActorDto` 只输出单个 `role`；`10_frontend/src/services/real-api.ts:396,427` 同时读取 `actor.authorized_roles`。数据库适配器按固定优先级选择角色，前后端角色集合并不一致。 |
| 学校租户隔离 | `NOT_IMPLEMENTED` | `11_database/database_layer/models.py:48-130` 的 Account、Subject、SubjectAccessGrant 没有 `school_id`/`tenant_id` 或学校实体关系；现有 subject grant 不能证明跨学校隔离。当前测试覆盖未经授权 subject 拒绝，未覆盖学校间负向访问。 |
| Teacher 后端授权与最小披露 | `PARTIAL` | `09_backend/src/smhai_backend/domains/teacher/service.py:25-188` 限制到 `accessible_subject_ids`、排除非合成记录并投影有限历史/计数；当前结果仍以 subject 为单位，缺少已要求的 Scope A task-level 聚合及相应小群体抑制验证。 |
| Teacher UI Scope A 工作流 | `NOT_IMPLEMENTED` | 前端因缺少安全的 task-summary API 而不发请求、不展示数据；后端单 subject 记录/历史不等于 Scope A 班级任务汇总。 |
| 学校管理员组织、账号、导入、测评任务操作 | `NOT_IMPLEMENTED` | Admin 页面当前读取公开 health 状态；无学校、账户导入、班级/任务等管理业务 API。源码：`10_frontend/src/views/admin/`、`09_backend/src/smhai_backend/domains/`。 |
| 心理专业人员工作流 | `NOT_IMPLEMENTED` | 仅有明确标为不可用的 UI 边界说明；无专业案例/资料查询操作，不复用 `REVIEWER` 安全复核权限。源码：`10_frontend/src/views/specialist/SpecialistWorkspaceView.vue`。 |
| CAT 题库导入、版本与发布治理 | `NOT_IMPLEMENTED` | `02_item-bank/` 只有 `TASK.md`，没有实现源码；`03_assessment-adapter/` 是解释政策适配器，不是 FlexCAT/外部题库导入器。 |
| 知识审核和发布管道 | `PARTIAL` | Pipeline 存在来源、审核、rights metadata gate；gate 记录不能单独证明素材获准使用或权利清除。当前 `data/published/round1/` 导出工件缺失。 |
| RAG M0 检索 | `PARTIAL` | `05_rag-engine/config/rag.m0-demo-bm25.v1.json` 使用 BM25；源代码支持 corpus filter/citation bundle，但当前 published fixture 缺失。本轮 RAG 定向测试 15 pass、1 fail、3 errors，均关联缺少的 `04_knowledge-pipeline/data/published/round1/embedding_ready.jsonl`；不得删断言或降级 gate。M0 真实运行未验证 dense/rerank 路径。 |
| Runtime provider/schema/追踪 | `PARTIAL` | 本轮 Runtime 定向 fake/mock suite 33 pass、2 deprecation warnings；未调用真实模型。`06_llm-runtime/config/runtime.m0-p1-support.v1.json` 限定一次尝试；无云回退/多次重试。 |
| Safety 和危机路由 | `PARTIAL` | 本轮 unit tests 15 pass，使用 fake adapter；无 live OPA/Qwen 验证。危机路由与正常生成分离、错误 fail-closed；模板含 `PENDING_PSYCH_REVIEW`，不代表心理专业批准。 |
| 普通支持 `CLAIM_BOUNDARY` | `BLOCKED` | `09_backend/src/smhai_backend/domains/support/service.py` 保留 Claim Boundary 校验。`13_deployment/M0_SPRINT_STATUS.md:29-44` 记录历史合成请求到该 gate 后 fail-closed、未持久化候选、未生成回答/citation/report；语义分类为 `INDETERMINATE`。本审计没有重放生成，也没有读取候选文本。 |
| 独立于测评的 AI 会话 | `NOT_IMPLEMENTED` | 前端支持页明确说明当前后端要求 `assessment_id`；`domains/support/schemas.py` 的 SupportRequest 要求该字段，service 将请求绑定到测评。当前没有独立本地 AI session。 |
| 前端视觉/真实浏览器运行 | `IMPLEMENTED_NOT_VERIFIED` | Vue 页面和当前样式源码存在，但本轮无服务、无浏览器截图。历史截图/测试不作本轮视觉证明。Mock unit 中发现一项文案断言不匹配：`tests/login-view.spec.ts` 期待旧中文句子，LoginView 已显示 PsyNova 英文登录文案；尚未确认应修产品还是更新测试。 |
| 最终交付素材再分发凭据 | `BLOCKED` | 28 张 Academy 活动图、6 张 Heartbridge 图、14 张其他 PsyNova 图没有逐文件 provenance/license 记录。`M0_SPRINT_STATUS.md:77` 对 Heartbridge 说明来自用户截图启发且为原创，但无逐文件证据。只有 Inter 字体有 `10_frontend/public/assets/fonts/LICENSE-Inter.txt`（OFL）。这表示当前无法确认最终学校交付包的素材再分发依据，不是法律结论。保留未跟踪 login-mark 文件，不复制新增素材。 |
| 自动任务 runner | `PARTIAL` | 当前未跟踪草稿的 17 项 unittest 全通过；其 queue drift、证据改动、attempt 绑定、kernel 锁和独立复核门禁均有回归。初审发现的 dirty-worktree DONE 绕过已由 Controller 增加 clean-tree gate；Lead 独立复验通过。Runner 是任务状态 CLI，不是代码/agent 执行器或密码检测器。 |

## Runner 独立复核

新鲜命令（`13_deployment/`，项目后端虚拟环境）：

```powershell
..\09_backend\.venv\Scripts\python.exe -m unittest -v tests.test_autonomous_runner
```

结果：17/17 通过，覆盖队列依赖、stop/resume、有界尝试、超时恢复、进程间互斥/崩溃释放、evidence 路径、queue drift 与显式同步、attempt/commit/file hash 绑定、dirty-tree 拒绝、拒绝返工和独立 reviewer。初审时 Lead 曾在 disposable Git 仓库复现 dirty `app.py` 仍可 DONE；Controller 随后增加 `require_clean()`。Lead 本轮重新运行全套测试，并在另一个 disposable 仓库完成端到端复验：dirty 源码时 DONE 被拒；恢复干净后，只留下 queue 明确允许保留的两个 baseline 未跟踪素材，DONE 成功。该初审缺口已关闭。

即使补上该门禁，runner 记录的 command 是非敏感命令标识，evidence 是文件 hash；工具不能证明命令确实运行或判断文档里的测试结论为真。独立审查仍需检查原始命令输出和被审 diff。90 分钟 heartbeat 的创建由 Controller 报告；本次没有观察到定时任务实际触发，因此不作为无人值守续跑证明。

## 新鲜验证明细

除非特别说明，均为本轮合成/内存/fake/mock 测试，不连接 MySQL、不访问真实学生数据、不调用在线模型。

| 工作目录 | 命令 | 结果 | 解释 |
|---|---|---|---|
| `01_cat-engine` | `.\.venv\Scripts\python.exe -m pytest -q tests/unit tests/integration tests/simulation` | 28 passed | 命令从模块目录运行；CAT 实现及合成模拟。 |
| `09_backend` | `$env:SMHAI_PERSISTENCE_MODE='memory'; .\.venv\Scripts\python.exe -m pytest -q tests/test_auth_roles.py tests/test_teacher_dashboard.py tests/test_teacher_dashboard_routes.py` | 7 passed | ASGI in-process + InMemory repositories；非数据库 auth/teacher 集成。 |
| `10_frontend` | `$env:VITE_API_MODE='mock'; npm run test:unit -- tests/login-view.spec.ts tests/router-guard.spec.ts tests/teacher-scope.spec.ts tests/specialist-admin.spec.ts` | 3 files / 14 passed；1 file / 1 failed | Mock 测试。单项失败是 LoginView 现文案与旧断言不一致，产品/测试取舍未定。 |
| `04_knowledge-pipeline` | `.\.venv\Scripts\python.exe -m pytest -q tests/unit/test_quality_dedup_review.py tests/unit/test_logging_and_config.py tests/unit/test_contract_and_exports.py tests/unit/test_chunk_strategies.py` | 12 passed | 命令从模块目录运行；选定 unit tests，不替代完整发布链路。 |
| `05_rag-engine` | `.\.venv\Scripts\python.exe -m pytest -q tests/unit tests/integration/test_provider_adapters.py` | 15 passed / 1 failed / 3 errors | 命令从模块目录运行；4 个失败用例需要缺失的 synthetic `embedding_ready.jsonl`；部分 BM25 测试通过内存 fixtures。 |
| `06_llm-runtime` | `.\.venv\Scripts\python.exe -m pytest -q tests/test_errors.py tests/test_domain.py tests/test_mock_provider.py tests/test_contract_boundary.py tests/test_runtime_service.py tests/test_runtime_reconstruction.py tests/test_tracing.py tests/test_validation.py tests/test_m0_support_profile.py tests/test_provider_ollama.py` | 33 passed / 2 warnings | 命令从模块目录运行；fake HTTP/mock providers，没有 live 模型请求。 |
| `08_safety-engine` | `.\.venv\Scripts\python.exe -m pytest -q tests/unit` | 15 passed | 命令从模块目录运行；fake adapters，无 live OPA/Qwen。 |
| `13_deployment` | `..\09_backend\.venv\Scripts\python.exe -m unittest -v tests.test_autonomous_runner` | 17 passed | 命令从 deployment 目录运行；含真实 disposable Git worktree gate 验证。 |
| 项目根目录 | `.\start-demo.ps1 -PreflightOnly` | exit 1 / blocked | 3307 无监听；旧 manifest 所有权未核实。只读预检；未启停服务。 |

历史 `M0_SPRINT_STATUS.md` 和 `M0_HANDS_ON.md` 的浏览器/MySQL/Runtime 记录仅作为既有历史；不等于本轮新鲜验证。当前没有端到端浏览器、真实 MySQL、实际本地模型或完整部署验证。

## 主要阻塞与排序建议

1. **将 runner 草稿纳入受审提交并做 Controller review。** dirty-worktree DONE gate 和 baseline untracked allowlist 已验证；command label 仍是执行者声明，不是进程/输出证明。heartbeat 创建已报告，但首次实际触发尚未证明。
2. **安全恢复隔离开发环境。** 先只读核实旧 process manifest 的 PID、可执行路径和命令行归属；只回收已证实属于此项目的进程。为项目提供 loopback 专用 MySQL 3307，不触碰系统 3306；确认备份与 schema 所有权前不做 reset/DDL。
3. **闭合学校租户、身份和角色。** 建立学校级 account/subject/grant 约束并覆盖 A 校教师读取 B 校数据的拒绝用例；对齐前端授权角色集合与后端角色投影。保持既有公共合同不变，先由 Controller review 内部数据模型/API 方案。
4. **首个纵向业务流：** 学校管理员创建合成学校、账号和测评任务 → 学生登录并完成/恢复 CAT → 结果在项目 MySQL 中持久化 → 教师仅看到 Scope A 规定的 task-level 完成汇总；同时验证跨学校拒绝、原始答案不披露及既有 suppression 规则。教师 UI 当前关闭，应按批准的 Scope A 数据契约实现，不新造阈值。
5. **并行定位普通支持 Claim Boundary。** 以合成请求和保存的非敏感阶段诊断定位验证失败原因；保留 fail-closed、citation binding、单次尝试和无回退约束。不要把候选内容、心理学结论或“修复成功”混为一谈。
6. **恢复合成 RAG fixture/export 流。** 通过正式 Pipeline 导出最小合成 corpus，保持缺失工件断言，重跑相应用例；随后才重新验证 M0 BM25 的真实进程链路。
7. **补足内容治理与交付素材。** 实现/确定合成题库版本管理及管理员操作；对无 provenance 的素材做原创替换，或补齐逐文件来源/许可记录；保留心理专业审核与真实 pilot 作为外部门槛。

## 安全、隐私与未决项

- 本次没有访问、输出或记录数据库凭据、数据库行、候选模型文本、学生数据或新生成内容。只对源代码的配置卫生做了定位；已发现演示/测试账号凭据及 CSRF HMAC key 存在源码字面量，报告不记录其值。应由 Controller 安排移出可提交源码，并确保本地注入机制不把值写入日志/报告。
- 没有重跑 M0 历史支持 POST；历史结果仍为 Claim Boundary fail-closed，分类 `INDETERMINATE`。未要求也未进行任何自动联系、家长通知或心理诊断。
- 真实学生/学校试点、心理学效度/阈值、专业内容批准、素材权利确认和生产部署仍是独立外部门槛。本报告没有授予这些批准，也没有声称达到交付完成度。

## Controller review 建议

请 Controller review runner dirty-worktree 缺口的修复方案、首个学校/租户内部数据模型、Scope A task-level summary 对现有 teacher per-subject API 的差异，以及无逐文件权利凭据素材的原创替换范围。在这些决定完成前，本报告保留 `PARTIAL_PASS`，不提升为最终接受状态。
