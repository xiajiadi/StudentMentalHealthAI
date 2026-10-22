# PsyNova Linux 合成学校演示部署

本方案仅用于 ECS 上的合成演示；它不配置 DeepSeek、前端、公网域名或 Nginx，也不接触旧河源数据库。现有 Windows DPAPI 启动器保持原样。

## 操作员授权命令

安装器默认只打印计划。完成源代码分阶段传输并核对工作树提交后，由操作员在 ECS 交互式输入 sudo 密码运行：

```bash
sudo /usr/bin/python3.12 /home/psynova/apps/psynova/staging/linux-school-demo/13_deployment/bootstrap_linux_school_demo.py --install
```

命令不会把 sudo 密码放入参数。安装器要求目标 schema `smhai_school_demo` 尚不存在；若 schema、专用账号、目标安装目录、systemd 单元或凭据文件已经存在，安装立即停止，不覆盖、不清库，也不自动重试。

## 预期效果

- `/opt/psynova-school-demo/release` 保存 root 所有、服务账号不可写的后端和数据库源码；独立 Python 3.12 虚拟环境从两个已锁定的 `uv.lock` 安装依赖。
- 创建非登录账号 `psynova-school-demo`。systemd 服务只读取 `LoadCredentialEncrypted` 注入的运行账号、Fernet 密钥和合成演示账号凭据。
- 建立 utf8mb4 Schema `smhai_school_demo`。应用账号仅有该 Schema 的 `SELECT/INSERT/UPDATE/DELETE`；迁移账号仅在该 Schema 获得 `CREATE/ALTER/INDEX/REFERENCES` 和所需 DML 权限，不授予 `DROP` 或 `GRANT OPTION`。迁移成功后账号锁定，加密迁移凭据删除。
- 使用现有 Alembic 迁移链到 `20261016_0024`，核对表、外键、CHECK、唯一约束、InnoDB 和排序规则。任何非空且不在预期 head 的状态都停止，保留现场。
- 使用现有合成学校种子创建 2 所学校、2 个主题、8 个四角色账号；在同一服务运行中执行两次以验证幂等。账号密码保存在 systemd 加密凭据，不写进日志或安装摘要。
- 执行真实 `LoadCredentialEncrypted` Provider 探针；启动前检查 MySQL 身份、版本、运行账号授权和 revision。启动后通过 HTTP 测四角色登录、角色拒绝、跨学校主题拒绝，并用登录会话验证后端重启后的数据库持久性。
- Backend 只监听 `127.0.0.1:8088`，MySQL 只监听 `127.0.0.1:3306`。不启用或改动 Nginx。

## 失败处理

安装器只输出固定错误类别，不输出密码、Token、数据库 URL 或低层 SQL 错误。出现 `BLOCKED` 时保留当前文件、MySQL 状态和 systemd 日志，先检查后再决定恢复；不得直接重跑、清空 schema 或删除未确认归属的数据。

该 ECS 当前是 MySQL 8.0.46，超出本项目冻结的 MySQL 8.4 LTS 版本基线。本次兼容范围只针对其合成演示迁移；不能据此宣称生产支持或升级既有项目的数据库验收状态。
