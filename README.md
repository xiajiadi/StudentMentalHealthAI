# PsyNova 学校平台

PsyNova 提供学生、普通教师、心理老师和学校管理员四类工作台，包含测评任务、保存与恢复、教育支持、资料引用、受控复核和运营管理。

当前交付是 **Windows 本机合成学校与公开研究数据仿真版**。四角色业务、真实本地模型、数据库和安装恢复已有运行证据；这不构成心理测量学验证或学校生产批准。

## 使用与部署

- [本地安装、启动、账号交接和备份恢复](13_deployment/SCHOOL_DELIVERY.md)
- [隔离工作区及完整安装参数](13_deployment/SCHOOL_WORKSPACE.md)
- [当前运行版本、验收证据和已知限制](14_docs/autonomous-delivery/CURRENT_STATE.md)
- [800 人公开研究响应仿真范围](14_docs/autonomous-delivery/EMPIRICAL_SCHOOL_SIMULATION.md)

学校平台使用 `13_deployment/school_install.py` 和 `school_app_lifecycle.py`。根目录的历史 M0 启动脚本不用于当前学校 schema。保留原数据库和失败现场；不要通过重新初始化或 seed 恢复现有工作区。

## 数据与运行要求

仿真学校身份与账号是虚构的；公开研究作答保留原始人群、许可和缺失约定。研究响应、凭据、数据库和模型均在仓库外维护。

本地安装需要已准备的 Python/前端依赖、MySQL 和模型等服务资源。当前备份与账号密封使用 Windows 当前用户 DPAPI，不能直接迁移到其他用户或电脑。正式学校使用前，还需确认目标环境、资源使用权及专业审查。
