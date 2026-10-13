# 首次初始化 synthetic school schema

本工具只迁移显式指定的、当前用户拥有的全新学校 workspace。它不安装依赖、启动 MySQL、创建数据库或迁移旧库。

先用现有 `create_school_workspace.py` 在新的外部目录初始化独立 MySQL。该步骤要求显式提供已安装 vendor MySQL 的 `bin` 目录和专用端口；目标不能使用注册 source workspace 的默认3308端口，也不能指向注册 source 路径。工具不会查找或安装 MySQL。创建成功后，从 marker 读取公开 `workspace_id`，然后使用当前 checkout 的 Database 虚拟环境运行计划和迁移：

```powershell
$python = '.\11_database\.venv\Scripts\python.exe'
$migrate = '.\13_deployment\migrate_school_workspace.py'
$workspace = '<absolute external workspace>'
$port = 3315
$workspaceId = (Get-Content -LiteralPath (Join-Path $workspace 'workspace.json') -Raw | ConvertFrom-Json).workspace_id

& $python $migrate plan --workspace $workspace --expected-port $port --workspace-id $workspaceId
& $python $migrate upgrade --workspace $workspace --expected-port $port --workspace-id $workspaceId
```

`plan` 只检查公开 marker、路径和目标 DB 虚拟环境是否存在；它不启动校验子进程、不检查 listener、不连接数据库，也不读取 DPAPI 密封设置。`upgrade` 会核验 DACL、guardian PID/可执行文件/创建时间/完整 argv 与 loopback listener，再用 DPAPI 中的 `psynova_builder` 在进程内验证目标端口、datadir、schema 和权限。权限必须精确为全局 `USAGE` 与 `smhai_school_demo` schema 范围的 `ALL PRIVILEGES`，不得带角色或 `GRANT OPTION`；root 身份不会用于迁移。

首次迁移只接受零表 schema，且 workspace 尚无 runtime、auth 或 seed 状态文件。Alembic 命令固定为 `upgrade 20261014_0011`，凭据只进入清洁子进程的 `DATABASE_URL` 环境，不进入参数、终端输出或日志。进程身份、DACL 和 listener 的 PowerShell 检查只继承必要的系统路径/用户环境，并附加固定 `PSYNOVA_MIGRATION_*` 参数；不会继承 DB、SMHAI、Vite、token、Python 或 Node 覆盖变量。成功后重新以 builder 身份连接，并使用同一只读 `information_schema` metadata 比对核验迁移结果。迁移报错或超时均标记为 partial，不自动判定事务状态或重试；需要保留现场供后续检查。

若数据库已是当前 `20261014_0011`，工具会将当前 checkout 的 `database_layer.Base.metadata` 作为受信任期望，并通过同一个 builder DBAPI connection 只读查询 MySQL `information_schema` 获取实际 schema；同时核对固定 Alembic revision、表/列集合、列类型、nullable、`AUTO_INCREMENT` 和模型明确声明的逐列排序规则、主键、命名 unique、外键源/目标列及删除/更新动作、命名 check 定义和显式索引的名称、列顺序及 unique 标记。CHECK 名称比较还接受由 `20261011_0003_school_membership_context.py` 明确给出的旧 CHECK 名称经 configured naming convention 展开后、使用当前 SQLAlchemy MySQL dialect 编译出的唯一物理名；这包括 dialect 对长名称确定性截断生成的哈希后缀。该表示兼容不修改数据库，也不放宽约束本身：每个受影响 CHECK 必须恰好出现一次，表达式规范化结果与 expected 完全相同且 `ENFORCED=YES`；未知名称、缺失约束、重复约束、表达式变化或未强制约束均 fail closed。canonical 与对应历史物理名可在约束之间组合出现，但不能同时代表同一个 logical CHECK。只规范化 MySQL 整数显示宽度、BOOL/TINYINT(1) 别名、约束表达式空白/括号，以及可识别的主键、unique backing 和外键支撑自动索引。缺少受信任元数据或实际结构不符会 fail closed。该比较不覆盖列默认值、完整字符集与表级排序规则、表引擎，也不比较索引算法、可见性和前缀长度等完整物理属性，故 `ALREADY_CURRENT` 仅表示上述 metadata 核验范围通过，不宣称所有物理属性等价。历史版本、非空未知 schema、迁移部分状态或已检查范围内的 schema drift 均拒绝；失败时保留 workspace 供检查，不自动回滚、降级、重置或重试。

迁移实现目前只接受空 schema 首次迁移或 exact-current `20261014_0011` 校验；它没有 0010→0011 的 workspace upgrade 路径。目标 H 与 G 仍处于 `20261013_0010`，本轮没有对它们执行迁移。0010 仍是受支持的历史 snapshot revision；这不表示它通过当前 runtime/lifecycle 的 0011 revision 要求。需要单独批准并实现/验证这两个已有 workspace 的升级步骤。

迁移通过后，按 [SCHOOL_WORKSPACE.md](SCHOOL_WORKSPACE.md) 继续创建 runtime 权限并运行合成角色 seed。该工具本身不启动 CAT、Backend 或 Frontend。
