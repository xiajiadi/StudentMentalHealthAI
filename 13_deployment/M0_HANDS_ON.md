# M0 本地演示操作

本指南面向已集成 M0 原型分支的 Windows 开发机。它只覆盖合成演示。启动会连接专用 loopback MySQL、运行迁移、生成本地 M0 knowledge/BM25 运行文件并启动本地服务；开始前先确认当前工作树和目标数据库确实是演示环境。

## 1. 准备环境

先按 [LOCAL_DEMO.md](LOCAL_DEMO.md) 准备 PowerShell 7.4+、`uv`、Node.js/npm、各模块本地虚拟环境、OPA、Ollama 和 `qwen2.5:0.5b`。不要把依赖装入全局 Python，也不要把密钥放入仓库。

必须满足以下条件：

- MySQL 已启动并只监听 loopback；目标 schema 精确为 `smhai_m0_demo`。
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

启动器可能在 Ollama 尚未运行时启动本机 `ollama serve`，但不会下载模型。其后会创建专用 schema（仅当不存在）、运行迁移、构建仅供 M0 使用的本地知识导出和 BM25 索引，并按顺序启动 OPA、CAT、RAG、Runtime、Safety、Backend、Frontend。缺依赖或 readiness 失败时不会切到 fake/云 fallback。

所有服务 ready 后，在浏览器打开 `http://127.0.0.1:4173/`。只使用页面提供的合成演示账号和合成信息；不要输入真实姓名、学号、联系方式、测评回答或其他真实学生数据。可按页面当前开放能力体验学生测评、结果/支持页面，以及教师和 reviewer 可访问的页面。需要验证某个具体业务闭环时，以其专项测试和 Live Stack Owner 的实测记录为准，不能仅凭页面能打开就认定端到端链路通过。

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

会返回退出码 `2` 并说明重置被阻断，不会停止服务、连接数据库或修改数据。现有 schema 没有能逐条识别全部 M0 演示记录的持久化标记；旧版 schema 级 `DROP DATABASE` 已禁用。等待批准的 marker-aware reset 实现，不要通过手工 SQL、删除 schema 或清理其他进程来恢复初始状态。

## 运行状态解释

- **Preflight PASS**：脚本可确认的前置条件通过，不代表服务已启动。
- **服务 ready**：启动器观测到对应健康端点返回成功，不代表浏览器到数据库的完整业务闭环已验证。
- **Reset BLOCKED**：当前不具备安全的逐条演示数据清理能力。

本地原型不构成心理学有效性、临床能力、真实学生数据授权、真实 pilot 或正式部署验收。完整边界见 [M0_SPRINT_STATUS.md](M0_SPRINT_STATUS.md)。
