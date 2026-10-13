# 学校演示依赖准备

`school_prepare_dependencies.py` 只准备锁定的 CAT、Backend、Database 和 Frontend 依赖。它不启动服务、不连接数据库、不安装模型，也不负责创建完整学校运行环境。默认使用本机缓存离线安装。

## 前置条件

- Source 和 Target 是两个互不重叠的 Git 根目录，HEAD 相同；Target 是干净的新检出，且包含相同的模块清单、项目清单和锁文件。
- Target 不得包含 CAT、Backend、Database 的 `.venv` 或 Frontend 的 `node_modules`。工具遇到已有目标会停止，不删除或覆盖。
- 为 CAT 提供现有 Python 3.14；Backend 和 Database 使用现有 Python 3.12。传入解释器的绝对路径。`uv`、`npm` 和本地 `node` 需能从 `PATH` 找到。
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
  --python "11_database=$py312"
```

命令输出一行 JSON，包含来源 HEAD、模块清单和锁文件 SHA-256，以及各步骤状态。计划模式允许 Target 尚不存在。

## 安装

先由负责人准备一个与 Source HEAD 相同的隔离 Target 工作树，再运行同一组参数，将 `plan` 改成 `install`。安装器会先检查仓库、模块清单和锁摘要，再逐项执行：

- CAT、Backend、Database：`uv sync --frozen --offline --no-python-downloads --no-dev`，并设置模块 `.venv` 为唯一环境目标。Database 没有项目构建后端，因此只同步其锁定依赖。
- Frontend：`npm ci --offline --ignore-scripts`。
- Python 环境：检查解释器版本并导入固定的公开模块。Frontend 校验只读取 `package.json`、lockfile 和已安装包的 `package.json`，不会执行项目脚本。

命令结束会输出逐步骤状态、退出码或固定错误类别，以及来源和目标的 HEAD、模块清单与锁摘要。子进程输出会被捕获，不写入报告。返回码 `0` 表示本次依赖准备和这些定向检查成功；`1` 表示安装或检查失败；`2` 表示预检阻止运行。它们不代表完整安装、服务启动、浏览器验收或发布通过。

如果某一步失败，已完成的环境会保留以便诊断；工具不会盲目重试、清理或回滚。应在新的隔离 Target 上重新执行。Target 中的源码和锁文件必须保持与开始时一致。

## 范围限制

当前只覆盖上述四个依赖根。Safety、RAG、Runtime、Knowledge Pipeline、MySQL 服务、向量库、Embedding 和模型均不在本流程中。该流程不读取应用凭据，不继承数据库/SMHAI/Vite/Python/Node 执行覆写或 uv 配置变量；仅保留系统运行所需路径、临时目录和位于 D 盘的依赖缓存路径。
