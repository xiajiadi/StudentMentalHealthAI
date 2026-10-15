# 学校演示依赖准备

`school_prepare_dependencies.py` 准备锁定的 CAT、Backend、Database、RAG、Runtime、Safety 和 Frontend 依赖。它不启动服务、不连接数据库、不安装模型，也不负责创建完整学校运行环境。默认使用本机缓存离线安装。

## 前置条件

- Source 和 Target 是两个互不重叠的 Git 根目录，HEAD 相同。Source 可以有未跟踪的用户文件，但 tracked 内容须与 HEAD 一致；Target 必须是干净的新检出，tracked 文件、模块清单和锁文件都与 HEAD 一致。
- Target 有任何未跟踪、忽略、嵌套仓库、Git 子模块、reparse point 或已有环境时会停止。Source/Target 的本地与 worktree Git 配置须符合受支持的键集合；Source 未跟踪文件不会复制进安装 Target。
- 只接受 Python 锁文件中的公开 PyPI registry 和 npm lockfile 中的公开 npm registry。Python 项目使用登记的 setuptools / Hatchling build backend；Database 不安装项目本身。拒绝仓库内的 `uv.toml`、`.npmrc` 与 `pyproject.toml` 中的 `[tool.uv]` 配置。
- Target 不得包含上述六个 Python 模块的 `.venv` 或 Frontend 的 `node_modules`。工具遇到已有目标会停止，不删除或覆盖。
- 为 CAT 提供现有 Python 3.14；其余五个 Python 模块使用现有 Python 3.12。传入解释器的绝对路径。`uv.exe` 和 `node.exe` 需能从 `PATH` 找到；Frontend 会调用同一 Node 安装目录下的 `node_modules/npm/bin/npm-cli.js`，不会通过 `npm.cmd`、PowerShell shim 或项目脚本运行。
- Python 锁文件、npm lockfile 和依赖包必须已经在本机缓存中；本流程不会访问网络。没有缓存时会报告失败，保留已完成的步骤和部分环境。请用新的 Target 重新准备，不要直接重跑覆盖。

## 只读计划

从仓库根目录运行 PowerShell。计划会读取 Git HEAD、模块登记、锁文件摘要和解释器版本，不创建目录或环境：

```powershell
$source = 'D:\Projects\StudentMentalHealthAI'
$target = 'D:\Dev\projects\smhai-school-deps-plan'
$catPython = 'D:\Dev\pythons\<现有 Python 3.14>\python.exe'
$py312 = 'D:\Dev\pythons\<现有 Python 3.12>\python.exe'

python .\13_deployment\school_prepare_dependencies.py plan `
  --source-root $source `
  --target-root $target `
  --python "01_cat-engine=$catPython" `
  --python "09_backend=$py312" `
  --python "11_database=$py312" `
  --python "05_rag-engine=$py312" `
  --python "06_llm-runtime=$py312" `
  --python "08_safety-engine=$py312"
```

命令输出一行 JSON，包含来源 HEAD、模块清单和锁文件 SHA-256，以及各步骤状态。计划模式允许 Target 尚不存在。

## 安装

先由负责人准备一个与 Source HEAD 相同的隔离 Target 工作树，再运行同一组参数，将 `plan` 改成 `install`。安装器会先检查仓库、模块清单和锁摘要，再逐项执行：

- 六个 Python 模块：`uv sync --frozen --offline --no-config --no-python-downloads --no-dev`，并设置模块 `.venv` 为唯一环境目标。Database 没有项目构建后端，因此只同步其锁定依赖。RAG 和 Safety 使用已锁定的 `runtime` extra；RAG 的该 extra 同时包含稀疏检索与 dense provider 依赖，需准备相应本机缓存。Runtime 使用基础依赖。
- Frontend：预检后在 `10_frontend` 中独占创建 `.school-deps-user.npmrc` 与 `.school-deps-global.npmrc` 两个不同的空文件，再用配对的 `node.exe` 运行 `npm-cli.js ci --offline --ignore-scripts`。两个 npm 配置变量分别指向这两个文件；已有文件或 reparse point 会阻止 npm 步骤，文件不会被覆盖或删除。
- Python 环境：检查解释器版本并导入固定的公开模块。Frontend 校验只读取 `package.json`、lockfile 和已安装包的 `package.json`，不会执行项目脚本。

安装开始前会在 Target 根目录写入 `.school-dependency-preparation-state.json`，并在各步骤开始、结束和复核时原子更新。断电或进程中断时，最后一个步骤可能保持 `running`；失败步骤会记录固定错误类别，不写子进程原文、路径、凭据或 URL。命令结束也会输出逐步骤状态、退出码，以及来源和目标的 HEAD、模块清单与锁摘要。返回码 `0` 表示本次依赖准备和定向检查成功；`1` 表示安装或检查失败；`2` 表示预检阻止运行。它们不代表完整安装、服务启动、浏览器验收或发布通过。

如果某一步失败，已完成的环境与已经创建的空 npm 配置文件会保留以便诊断；工具不会盲目重试、清理或回滚。状态文件、npm 配置文件和部分环境会使 Target 无法通过下一次洁净性检查，应在新的隔离 Target 上重新执行。Target 中的 tracked 源码、模块清单和锁文件必须保持与开始时一致。

## 范围限制

当前覆盖上述七个依赖根。Knowledge Pipeline、MySQL 服务端、OPA 二进制、Guard/Embedding 权重、语料、向量库、Ollama 与模型文件均不由此工具准备。固定 Ollama/7B 的现有独立预检仍需通过；Python 导入成功不代表这些资源已就绪。该流程不读取应用凭据，不继承数据库/SMHAI/Vite/Python/Node 执行覆写或 uv 配置变量；仅保留系统运行所需路径、临时目录、主机提供的 Windows `USERNAME`，以及位于 D 盘且不与 Source 或 Target 重叠的依赖缓存路径。`USERNAME` 只传给子进程用于 Windows 用户名解析，不会写入结果或日志；主机未提供时不伪造该变量。
