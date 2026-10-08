# M0 本地原型状态

状态：**工程能力待集成现场验证**。本文记录当前提交中的静态证据和已有测试入口，不代表测试已在本次执行，也不代表本地整栈启动、浏览器到数据库闭环、心理学有效性、真实学生数据使用或正式部署已获验收。

基线：`3c1bd71c85a4ef618cb11adcaa87d4858fda628a`。本 Worker 只负责部署脚本和文档；CAT、学生端、教师端及支持链路仍需由各自负责人交付并集成到同一工作树后再验证。

## 首轮能力矩阵

“源码/测试证据”是对当前仓库文件的静态核对。表中的测试没有在本 Worker 回合运行。除非特别注明，运行状态均为 **未做现场验证**。

| 能力 | 当前可确认范围 | 源码 / 测试证据 | 状态与缺口 |
|---|---|---|---|
| 本地启动与依赖预检 | 启动器检查本地环境、M0 fixture、loopback MySQL listener、Ollama、端口和已有进程清单；通过后会创建专用 demo schema（若不存在）、迁移、构建合成知识导出并启动本地模块。 | `scripts/start-demo.ps1`、`scripts/ensure_m0_database.py`、`13_deployment/LOCAL_DEMO.md` | 脚本存在；本回合未启动或运行 preflight。整栈是否能在目标机器启动，待 Live Stack Owner 验证。 |
| 受管进程停止 | 只针对当前 worktree 的进程清单，核对 PID、可执行文件、启动时间和参数；退出未确认时保留清单并失败。 | `scripts/demo-common.ps1`、`scripts/stop-demo.ps1`、`stop-demo.ps1` | 静态检查；没有进程清理测试或现场停止证据。 |
| 数据库重置 | 当前命令失败关闭；不停止服务、不连接数据库、不删数据。旧的 schema 级 `DROP DATABASE` 路径已移除。 | `scripts/reset-demo.ps1`、`scripts/reset_m0_database.py` | 安全阻断已实现。逐条 M0 记录标记与清理方案缺失，重置能力不可用。 |
| CAT 合成测评 | CAT demo service 有合成题库与配置路径；测试覆盖配置停止点、未知 instrument、当前题目校验和 assessment.v1 映射。 | `01_cat-engine/fixtures/demo_cat_config.v1.json`、`01_cat-engine/fixtures/synthetic_item_bank.v1.json`、`01_cat-engine/tests/integration/test_demo_service.py`、`test_assessment_contract.py` | 仓库内有测试证据；测试未在本回合运行，浏览器链路未验证。 |
| 学生测评页面 | 学生端有测评、结果和主页组件；前端测试覆盖学生流程及与真实 API 的 subject/risk 映射边界。 | `10_frontend/src/views/student/AssessmentView.vue`、`AssessmentResultView.vue`、`StudentResultView.vue`、`10_frontend/tests/student-flow.spec.ts`、`real-api-subject.spec.ts`、`real-api-risk-mapping.spec.ts` | 源码和测试存在；完整浏览器到持久化链路未验证。 |
| 教师查看页面 | 教师概览、学生列表和学生详情页面存在。 | `10_frontend/src/views/teacher/TeacherOverviewView.vue`、`TeacherStudentsView.vue`、`TeacherStudentDetailView.vue`、`10_frontend/tests/router-guard.spec.ts` | 路由与角色 guard 有测试；未找到专门覆盖教师端数据展示的测试，数据授权和现场展示待 Lead 核对。 |
| 支持生成与安全分流 | Backend 测试包含普通、高风险/危机、人工复核和输出门控场景；学生支持页和 reviewer 队列/详情页存在。 | `09_backend/tests/test_backend_round1.py::test_vertical_slice_normal_crisis_review_and_output_gate`、`10_frontend/src/views/student/SupportChatView.vue`、`10_frontend/src/views/reviewer/ReviewQueueView.vue`、`ReviewDetailView.vue` | 有后端测试和前端源码证据；测试依赖是否为合成、mock 或真实组件须按各自 fixture 判断；本回合未运行整栈。 |
| RAG / 本地 Runtime / Safety | 启动器指定 M0 BM25 profile、本地 corpus 路径、loopback 服务地址和 OPA；各模块有独立 service/readiness 或单元测试入口。 | `05_rag-engine/config/rag.m0-demo-bm25.v1.json`、`05_rag-engine/tests/unit/test_api_bm25_runtime.py`、`06_llm-runtime/tests/integration/test_ollama_integration.py`、`08_safety-engine/tests/e2e/test_http_service.py` | 只证明仓库含配置和测试；未验证配置共同启动、Ollama 模型可用、RAG 索引可读或 Safety 真实 readiness。 |
| 后端持久化与健康检查 | 启动器指定 MySQL persistence、HTTP 模块客户端和 `/health/ready`；Backend 的应用与纵向切片测试存在。 | `scripts/start-demo.ps1`、`09_backend/tests/test_backend_round1.py::test_app_factory_lifespan_health_and_dependency_matrix`、`test_vertical_slice_normal_crisis_review_and_output_gate` | 测试是否使用测试容器/替身以测试 fixture 为准；没有本回合 MySQL 登录或 DB migration 验证。 |

## 已知限制与停止条件

- 当前 M0 启动路径依赖同一集成工作树中的 CAT demo 配置/题库、M0 knowledge fixture、BM25 profile，以及本地模块环境；缺失时应停止，不要用旧 corpus、fake Safety 或云服务替代。
- 启动需要已存在的 MySQL loopback listener、专用库名 `smhai_m0_demo`、迁移权限、外置数据库密钥文件、OPA 可执行文件、本机 Ollama 与 `qwen2.5:0.5b`；脚本不会自动安装依赖或下载模型。完整准备步骤见 [LOCAL_DEMO.md](LOCAL_DEMO.md)。
- Preflight 通过只表示脚本前置条件通过；它不会证明 migration、服务 readiness、UI→DB 操作或结果持久化。
- `reset-demo.ps1` 当前稳定返回阻断状态。没有被明确 M0 标记的记录前，不得执行 schema-wide 删除、手工清库或其他范围更大的清理。
- 真实学生数据、真实 pilot、家长端交付、心理学/临床有效性、危机联系人、生产部署和自动通知不在此状态记录的工程证据范围内。

## 后续现场验证输入

Live Stack Owner 需要先确认 Worker 分支已集成到同一 worktree，并确认合成演示配置、外部密钥文件状态、loopback MySQL、OPA、Ollama 本地模型和各模块环境已经准备。随后由 Lead 按批准流程运行 preflight、启动、最小浏览器操作、后端/数据库持久化核对和停止；重置仍需单独的逐条标记方案。所有运行结果应记录实际机器状态、命令、退出码、健康端点结果和未覆盖项。
