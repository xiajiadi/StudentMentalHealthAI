# M0 本地演示操作

本指南面向已集成 M0 原型的 Windows 开发机，只覆盖合成演示。启动会连接专用 loopback MySQL、运行迁移、生成本地 M0 knowledge/BM25 运行文件并启动本地服务。当前凭据有全局 `CREATE` 权限，但 `ALL PRIVILEGES` 仅限既有 `smhai_m0_demo`，未观察到 `GRANT OPTION`。新 schema 可能被命名或创建，但现有授权不足以迁移、播种并运行 M0；本轮没有创建任何新 schema。开始前确认工作树和目标数据库都是演示环境，并保留旧工作区及其数据。

## 1. 准备环境

先按 [LOCAL_DEMO.md](LOCAL_DEMO.md) 准备 PowerShell 7.4+、`uv`、Node.js/npm、各模块本地虚拟环境、OPA、Ollama 和 `qwen2.5:0.5b`。不要把依赖装入全局 Python，也不要把密钥放入仓库。

必须满足以下条件：

- MySQL 已启动并只监听 loopback；目标 schema 精确为现有 `smhai_m0_demo`。
- 当前数据库用户有全局 `CREATE`，但 `ALL PRIVILEGES` 仅授予既有 schema，且未观察到 `GRANT OPTION`。因此能创建空 schema 不等于具备 M0 初始化权限；若目标 schema 不存在，不要手动建库、改用共享库或清理旧库。当前 schema 列表只有旧 `smhai_m0_demo`，没有新工作区。
- `DB_USER`、`DB_PASSWORD`、`DB_HOST`、`DB_PORT`、`DB_NAME` 或等价的 `DATABASE_URL` 由本机安全配置提供。不要把连接串或密码贴入命令、文档、截图或日志。
- `DATABASE_KEY_FILE` 指向仓库外已存在的密钥文件；未设置时脚本检查数据库模块约定的外部默认路径。
- `SMHAI_OPA_BINARY` 指向本地 OPA 可执行文件，或安装在脚本默认检查的位置。
- M0 所需 fixture/profile 已进入当前集成工作树，所有服务端口可用。
- 可选地设置 `SMHAI_M0_DATA_ROOT` 到仓库外目录。默认运行目录为 worktree 同级的隐藏目录。

## 2. 预检

在已集成的仓库根目录执行：

```powershell
.\start-demo.ps1 -PreflightOnly
```

该命令不启动服务、迁移数据库或写入 corpus/index。它会检查本机端口和 MySQL listener，并在 Ollama 已运行时请求 loopback API 以确认本地模型。
`BLOCKED` 时按提示修复缺少的命令、环境、fixture、端口或本地依赖后重试；不要更换为共享数据库或外部模型服务来绕过检查。

## 3. 启动和使用

确认预检通过后：

```powershell
.\start-demo.ps1
```

启动器可能在 Ollama 尚未运行时启动本机 `ollama serve`，但不会下载模型。其后对现有专用 schema 运行迁移、构建仅供 M0 使用的本地知识导出和 BM25 索引，并按顺序启动 OPA、CAT、RAG、Runtime、Safety、Backend、Frontend。当前权限只覆盖旧 schema；对新 schema 缺少完整初始化所需的授权。若目标库不存在或数据库准备失败，启动应视为未完成。本轮没有创建新 schema。不要改用共享库或删除旧 schema 来绕过。缺依赖或 readiness 失败时不会切到 fake/云 fallback。

所有服务 ready 后，在浏览器打开 `http://127.0.0.1:4173/`。只使用合成账号和合成信息；不要输入真实姓名、学号、联系方式、测评回答或其他真实学生数据。

- **Student：** 保持默认的“学生”身份及页面预填的合成账号信息，提交登录后进入学生工作区。不要将真实个人信息输入演示。
- **Teacher：** 选择“教师”身份；账号信息由本机运行环境保管，变量名为 `SMHAI_M0_TEACHER_USERNAME` 和 `SMHAI_M0_TEACHER_PASSWORD`。在本机登录表单中使用这组账号信息，不要把密码写入仓库、终端记录、日志或聊天。该演示账号的授权范围仅覆盖两个合成主体。
- **Reviewer：** 使用本机 synthetic seed account；本轮未现场复核 reviewer 登录流程。
- **AI 支持：** 当前真实合成请求被 Backend `CLAIM_BOUNDARY` 安全门拒绝，没有回答、引用或报告。不要为获取回答而重复提交相同问题。

登录后，Student 可从“大学新生适应测评”选择“开始测评”，逐题选择页面提供的选项并提交；如需离开，选择“暂停并离开”，之后可从学生空间继续。完成时按页面提示完成测评并查看结构化记录。当前 Lead 提供的浏览器证据中，两条合成作答路径均在配置的 8 项后完成，结果标记为 `SYNTHETIC / DEMO / 非诊断`；这不表示心理测量有效。

结果页显示已保存的测评记录，并可返回学生空间查看测评历史。历史项可重新打开结果；刷新或整栈重启后的恢复情况见状态记录。Teacher 可查看授权范围内的匿名主体、测评状态和记录摘要；选择未授权主体应显示无权访问。Teacher 页面不提供原始作答或支持对话。

以上浏览器结果来自 Lead 提供的既有集成快照证据，本 Worker 未复跑浏览器或服务。需要验证具体业务闭环时，以 [M0_SPRINT_STATUS.md](M0_SPRINT_STATUS.md) 和专项证据中的来源标注为准；不能仅凭页面能打开就认定端到端通过。

服务端口和依赖准备命令见 [LOCAL_DEMO.md](LOCAL_DEMO.md)。启动后检查终端中的 readiness 结果；浏览器地址能打开不等于每个依赖均可用。

## 4. 停止

执行：

```powershell
.\stop-demo.ps1
```

停止脚本只处理当前 worktree 启动器登记且身份仍吻合的进程。它不会停止启动前已存在的 Ollama，不会清理本地 corpus/index 或数据库。若进程退出无法确认，脚本会保留进程清单并报告错误；先人工核对该 PID，不要手工结束同端口的其他进程。

## 5. 重置不可用

当前执行：

```powershell
.\reset-demo.ps1
```

按当前 Lead evidence，此命令因无法安全识别并逐条清理全部 M0 演示记录而返回退出码 `2`。被阻断时它不会停止服务、连接数据库或修改数据；**旧 schema 和其中已有数据仍保留，不会因此清空或创建新的工作区**。虽然当前用户有全局 `CREATE` 权限，但这不提供新 schema 所需的完整迁移、播种和运行授权，也不改变 Reset 阻断状态。旧版 schema 级 `DROP DATABASE` 已禁用。不要通过手工 SQL、删除 schema 或清理其他进程来恢复初始状态。

## 运行状态解释

- **Preflight PASS**：脚本可确认的前置条件通过，不代表服务已启动。
- **服务 ready**：启动器观测到对应健康端点返回成功，不代表浏览器到数据库的完整业务闭环已验证。
- **Reset BLOCKED**：当前不能安全逐条识别和清理 M0 演示记录；失败关闭意味着旧 schema 与数据保持原样，不代表重置成功，也不代表新工作区已创建。全局 `CREATE` 权限不代表新 schema 已具备完整 M0 运行权限。

本地原型不构成心理学有效性、临床能力、真实学生数据授权、真实 pilot 或正式部署验收。完整边界见 [M0_SPRINT_STATUS.md](M0_SPRINT_STATUS.md)。
