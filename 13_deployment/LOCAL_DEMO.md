# M0 本地工程演示运行手册

范围：仅合成演示。服务默认绑定 `127.0.0.1`；不连接云服务，不启用 `contract_fake`。该运行手册不是发布、研究或心理学有效性验收。

## 前置准备

- Windows PowerShell、`uv`、Node.js/npm、MySQL 8.x 和 Ollama CLI。
- CAT、Backend、Database、Safety 使用 Python 3.12/3.14 项目本地环境；RAG、Runtime 和 Knowledge Pipeline 使用各自 `pyproject.toml` 支持的 Python 版本。环境分别创建在每个模块的 `.venv` 中，不安装到全局 Python。
- 在仓库根目录执行以下项目本地依赖准备命令。Safety 的 `runtime` extra 含 NeMo/Presidio、PyTorch 和 Transformers，下载量较大；启动器不自动安装这些依赖，也不会下载模型。

  ```powershell
  Push-Location 01_cat-engine; uv sync --python 3.14 --locked; Pop-Location
  Push-Location 04_knowledge-pipeline; uv sync --python 3.12 --locked; Pop-Location
  Push-Location 05_rag-engine; uv sync --python 3.12 --locked; uv pip install --python .venv\Scripts\python.exe bm25s==0.3.11; Pop-Location
  Push-Location 06_llm-runtime; uv sync --python 3.12 --locked; Pop-Location
  Push-Location 08_safety-engine; uv sync --python 3.12 --locked --extra runtime; Pop-Location
  Push-Location 09_backend; uv sync --python 3.12 --locked; Pop-Location
  Push-Location 11_database; uv sync --python 3.12 --locked; Pop-Location
  Push-Location 10_frontend; npm ci; Pop-Location
  ```
- 本机 Ollama 应含项目注册的本地工程模型 `qwen2.5:0.5b`。启动器会在 Ollama 未运行时尝试以 `127.0.0.1:11434` 启动本机 `ollama serve`；不会下载模型。缺模型时需先按本机 Ollama 使用流程安装，再重试。
- MySQL 必须运行于 loopback 且 listener 只能绑定 `127.0.0.1` 或 `::1`；wildcard/all-interface listener 会被拒绝。只允许专用数据库名 `smhai_m0_demo`。在用户级环境中配置 `DB_USER`、`DB_PASSWORD`、`DB_HOST=127.0.0.1`、`DB_PORT` 和 `DB_NAME=smhai_m0_demo`，或使用等价的 loopback `DATABASE_URL`。该账号必须能创建该 schema 和运行模块迁移；重置还需能删除/重建此专用 schema。连接值不写入仓库、不由脚本回显。数据库迁移还需要外部 `DATABASE_KEY_FILE`；未设置时使用数据库模块约定的外部默认路径。密钥文件必须已存在且位于仓库之外。
- 如需更换运行数据位置，可将 `SMHAI_M0_DATA_ROOT` 指向仓库外本机目录。默认位置是 worktree 同级的隐藏运行目录，避免与其他 worktree 共用。
- A/B/C/D 的集成改动须先进入同一工作树。启动器要求 CAT fixture、B 的 M0 BM25S profile 与 M0 knowledge fixture；若当前工作树尚未包含它们，检查会停止且不执行迁移。

## 启动

在集成后的仓库根目录运行：

```powershell
.\start-demo.ps1
```

只运行前置检查（不会迁移数据库、构建 corpus 或启动进程）：

```powershell
.\start-demo.ps1 -PreflightOnly
```

启动前检查项目本地依赖、RAG 是否显式使用 BM25S 和 M0 corpus 路径、专用 loopback 数据库目标、外部数据库密钥文件、Ollama/模型状态及应用端口。通过后按顺序执行数据库迁移、仅从 `04_knowledge-pipeline/fixtures/m0_demo/freshman_study_routine.md` 构建独立知识导出、启动 CAT/RAG/本地 Runtime/Safety/Backend/Frontend，并检查每个服务的 `/health/ready`。Backend 以 MySQL persistence 和 HTTP 模块客户端启动，缺少任一依赖时停止，不回退到内存或 fake 模式。

服务端口：CAT `8180`、RAG `8170`、Runtime `8160`、Safety `8190`、Backend `8080`、Frontend `4173`。浏览器地址为 `http://127.0.0.1:4173/`。RAG corpus 与 BM25 index、临时运行配置、进程清单写入本地运行目录，不会放入 Git。

Backend 启动时调用现有 MySQL adapter 的幂等 synthetic identity bootstrap；测评 instrument 与 item bank 由 CAT 配置/fixture 提供。启动器本身不输出账号密码或密钥。

## 停止与重置

```powershell
.\stop-demo.ps1
```

只停止本 worktree 清单记录且 PID、可执行路径、启动时间和启动参数仍吻合的进程。启动器自己启动的 Ollama 也会被停止；启动前已经存在的 Ollama 不会被停止。

```powershell
.\reset-demo.ps1
```

重置先停止本 worktree 管理的服务，并要求交互输入 `smhai_m0_demo`。之后只删除并重建 loopback 上名称精确为 `smhai_m0_demo` 的专用 MySQL schema，再运行迁移。Backend 下次启动时重新建立 synthetic identities。重置不会清理其他数据库、model cache、历史工作树或本地运行目录。用于生产、共享或非 loopback 数据库的配置会被拒绝；数据库账号还需拥有创建和删除该专用 schema 的权限。

浏览器 Demo Reset 入口只提供运行此脚本的指引；后端没有已确认的浏览器安全 reset API，页面不会声称重置成功。

## 故障处理与边界

- `BLOCKED` 前置检查不会运行迁移或删除数据库。按列出的变量名/依赖/端口问题处理后重试；不要将数据库名改成其他共享库来绕过检查。
- Ollama 模型缺失时需本地准备模型；启动器不访问模型仓库、不使用云 fallback。
- BGE-M3 与 embedding cache 不属于 M0 BM25S 路径的依赖。BM25S profile、corpus 路径或 eligible demo chunk 不满足时启动失败，不读取 Round 1/K12/D3-validation corpus。
- Safety runtime 依赖缺失或 health readiness 为 `NOT_READY` 时启动失败，不使用 fake Safety。
- 本手册的启动健康检查不等于端到端 UI→DB 验收。`PreflightOnly` 只检查脚本前置条件；需要真实 UI-to-DB smoke 后才能报告该闭环已验证。
- 真实学生数据、真实 pilot、正式部署、云 fallback、D4 Formal 和心理学/临床有效性声明均不属于此演示。
