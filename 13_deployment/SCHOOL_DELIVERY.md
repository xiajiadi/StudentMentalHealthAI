# 学校平台本地交付指南

本指南用于在 Windows 本地安装、启动并演示合成数据版学校平台。它不代表 AI 全链路、测量学、伦理或生产验收。

当前唯一维护分支为 `main`。从 PsyNova 主仓库运行安装和生命周期入口；不要使用已归档的历史工作树启动 workspace。`school_app_lifecycle.py` 以脚本所在仓库作为源码根目录，`start` 与 `resume` 的预览模式会从该仓库的 `10_frontend` 重新执行类型检查和构建。已运行的预览是静态快照，代码提交后需要下一次受支持的 `start`/`resume` 才会刷新。

## 安装与启动

1. 从唯一维护的 PsyNova 源仓库运行 `13_deployment/school_install.py`。
2. 先执行 `plan`，核对源码 SHA、依赖工作树、绝对 workspace 路径、空闲端口和六个模块的 Python 解释器。
3. 复核计划后，用同一组参数执行 `install`。阶段完成后用 `resume` 继续。
4. 阶段失败或保留在 `running` 时，保留现场并按闭合错误码恢复；不要删除 checkpoint 或重放 seed。

数据库 workspace 放在仓库之外的新目录。页面由源仓库中的 Frontend 提供；切换 workspace 或端口不需要复制另一套 UI。安装参数和六个模块解释器的格式见 [SCHOOL_WORKSPACE.md](SCHOOL_WORKSPACE.md)。

安装成功后，用 `09_backend/.venv` 运行官方生命周期。`plan` 只读；`status` 查看 Backend、Frontend 和 worker 状态；`stop` 只停止本 lifecycle 管理的应用进程，不停止 MySQL 或共享模块。

```powershell
$expectedBranch = 'main'
$actualBranch = (git branch --show-current).Trim()
if ($actualBranch -ne $expectedBranch) { throw "Run lifecycle from $expectedBranch; current branch is $actualBranch" }

$py = '.\09_backend\.venv\Scripts\python.exe'
$life = '.\13_deployment\school_app_lifecycle.py'
$workspace = '<绝对 workspace 路径>'
& $py $life plan --workspace $workspace --frontend-mode preview --llm-profile school-gpu-7b
& $py $life start --workspace $workspace --frontend-mode preview --llm-profile school-gpu-7b
& $py $life status --workspace $workspace
& $py $life stop --workspace $workspace
```

### 从已停止 manifest 恢复

先用受支持的 `stop` 完成应用停止，再用 `resume-plan` 只读核对保存的端口、profile、CAT 与研究 worker；仅在返回 `PLAN_ONLY` 且保存配置 pins 通过校验时执行 `resume`。恢复命令只接受完整 `STOPPED` manifest，不接受启动参数覆盖，也不会替你停止仍在运行的进程。意外关机后 manifest 可能仍为 `RUNNING`；先用 `status` 核对归属，再按受支持的 `stop` 流程确认停止，不能直接 resume 或手改 manifest。部分失败、owner 不匹配、监听器残留或配置 pin 改变时，计划会阻止恢复。

```powershell
& $py $life resume-plan --workspace $workspace
& $py $life resume --workspace $workspace
```

恢复会重新校验当前源码、配置文件和 CAT pin，并从保存配置启动 Backend/Frontend 与已启用的 CAT。它不启动 MySQL 或共享 Runtime、RAG、Safety、Ollama；这些依赖须按各自正式入口单独恢复。`resume-plan` 只给脱敏摘要，不打印路径、完整配置或命令行；`resume` 沿用现有启动检查，不代表 whole-ready。

Backend、Frontend 和 CAT 端口可由启动参数指定；部署时选空闲端口并保持前后端配置一致。Lifecycle 的标准 CAT 默认端口是 `8180`；fresh installer 的默认值是 `8182`，以实际 checkpoint 为准。

`school-gpu-7b` 明确选择本地 7B profile；模型不可用时不会自动切换到 CPU 测试模型。标准 CAT 只有在传入 `--enable-standard-cat` 后才由 lifecycle 管理。

启动后先检查 `status` 的 owner、listener 和 readiness，再进入角色页面。四角色浏览器 QA 会从密封账号文件中在内存读取合成账号；它的报告只保留脱敏结果，不提供人工账号密码。

## 四角色演示顺序

| 顺序 | 角色 | 可演示的操作 |
|---|---|---|
| 1 | 学校管理员 | 在合成学校内配置班级、账号和任务；查看运营审计元数据，不查看个人心理正文。 |
| 2 | 心理老师 | 查看已分配任务、题库/测评配置和待复核记录；专业发布动作仍由有权限人员逐项处理。 |
| 3 | 普通教师 | 查看所授权班级的任务进度和非敏感汇总；不得查看个人测评结果、原始回答或私聊。 |
| 4 | 学生 | 完成或恢复本人测评，查看本人完成状态；个人反馈只有在相应内容已获专业预批准并发布后才可见。 |

默认使用登记的合成学校和合成账户。完成测评不等于测量结果有效；合成题目或分数不能支持诊断、临床解释或正式量表效度结论。

## 外部服务与权限边界

| 依赖 | 默认本机地址/配置 | 交付时的检查 |
|---|---|---|
| CAT | `127.0.0.1:8180` 默认值，可配置 | 仅在启用 CAT 时检查独立服务和 lifecycle 状态。 |
| RAG | `127.0.0.1:8170` | 使用已批准的本地知识库；检查检索来源与服务健康。 |
| LLM Runtime | `127.0.0.1:8160` | 核对 `school-gpu-7b` profile 与模型身份；失败时保持不可用。 |
| Safety | `127.0.0.1:8190` | 必须可用并执行现有输入、检索、输出安全门；不可关闭或绕过。 |
| Ollama host | `127.0.0.1:11437` | `school_llm_runtime.py` 固定 Ollama `0.33.3` 与注册的 Qwen 2.5 7B 文件摘要；不下载、替换或静默回退模型。 |

这些是当前代码中的默认 loopback 端口；端口冲突时按各服务的正式配置调整，不能把某台电脑的绝对路径当作产品要求。

Lifecycle 只管理学校 Backend/Frontend 和明确启用的 CAT。安装成功或页面可打开，不表示 RAG、Runtime、Safety、OPA、Guard 或模型已就绪；需要分别确认这些外部服务的健康状态和 owner。

研究 Runtime 是单独显式配置的 `8161` host，复用固定本地模型，不应与默认应用 Runtime 混为一谈。

研究配置必须显式提供成对的配置文件和 SHA-256，并通过现有 Backend/lifecycle 校验。路径、研究授权声明和 worker 开关不会替代伦理、心理测量学或生产审批；未配置的研究流程保持关闭。

## 合成账号与数据保护

账号凭据保存在 workspace 的 `school-accounts.private.dpapi`，由 Windows 当前用户 DPAPI 保护。

官方浏览器 QA 在内存中读取并校验登记的合成账号，不会把密码作为命令参数或写入报告。这条路径用于自动验证，不是人工凭据交接。

用源仓库的 `pythonw.exe` 启动本地窗口：

```powershell
$source = '<源仓库绝对路径>'
& "$source\09_backend\.venv\Scripts\pythonw.exe" `
  "$source\13_deployment\school_account_handoff.py"
```

在窗口输入外部 workspace 绝对路径和 `workspace.json` 中的 UUID。工具会先核对合成 workspace、Backend 的只读 owner/权限预检和账号文件 DACL，再显示登记的 alpha 四角色账号名；密码默认隐藏，只有选中一个账号并点击“显示所选账号密码”后才暂显。关闭或切换账号会清空显示控件；工具不写日志、文件、剪贴板或截图。

该工具仅在创建这些 DPAPI 文件的 Windows 用户会话中可用。若操作者没有已授权账号，需由项目负责人安排受控凭据交付；不要解密后复制、打印或放入仓库。

运行数据库身份与 workspace 创建身份分离，权限限定在本校 schema 的读写操作。不要复用、清空或恢复到已有 workspace；备份与恢复只能使用官方新目标流程。

## 备份与恢复

官方备份先验证 workspace 所有权、schema 和 sealed runtime 配置，再在 workspace 的 `backups` 目录创建 DPAPI 密封文件并读回校验：

```powershell
$dbpy = '.\11_database\.venv\Scripts\python.exe'
& $dbpy .\13_deployment\school_backup.py --workspace $workspace
```

恢复只接受该 workspace 的官方备份，目标必须是未存在的新绝对路径，且使用不同的空闲 MySQL 端口：

```powershell
& $dbpy .\13_deployment\restore_school_workspace.py `
  --backup '<源 workspace\backups 下的密封备份文件>' `
  --source $workspace --target '<新的绝对 workspace 路径>' `
  --mysql-bin '<vendor MySQL bin 目录>' --port <新端口>
```

恢复验证包含迁移、行导入和密钥解密；`DATA_KEYS_RUNTIME_VERIFIED_REQUIRES_BROWSER` 表示数据库/密钥恢复完成，浏览器验收仍未完成。恢复目标和 DPAPI 密钥仅可由原 Windows 用户使用；跨用户或跨机器复制不构成可移植备份。失败目标须保留调查，不手工改 checkpoint、覆盖旧备份或重置旧数据库。

## 验收边界

四角色浏览器检查证明对应的合成角色路径，不等于完整 AI 交付。`whole_ready` 仍由独立依赖与真实业务路径证据决定。临床、伦理、心理测量学、真实学生数据和学校生产部署需要独立授权，本指南不提供这些批准。
