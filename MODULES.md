# Module Registry

本文件登记 16 个子项目的职责、输入输出、依赖和协作边界。每个模块的具体任务以同目录 TASK.md 为准。

## 1. 模块总表

| 模块 | 主要职责 | 主要输入 | 主要输出 | 依赖 | 不能负责 |
| --- | --- | --- | --- | --- | --- |
| 00_architecture | 架构、Contract、版本和集成治理 | 项目决策、变更提案 | 规范、Schema、ADR、fixture 约定 | 无 | 业务功能实现 |
| 01_cat-engine | CAT 选题、估计、终止和模拟 | 已批准题库、答题事件 | Assessment Result | 00、02 | RAG、Prompt、用户页面 |
| 02_item-bank | 题目、参数、版本、导入校验 | CSV/JSON/人工审核资料 | 标准题库 | 00 | 估计和风险解释 |
| 03_assessment-adapter | 外部测评格式适配 | FlexCAT/其他导出 | assessment.v1 | 00、02 | 修改原始工具含义 |
| 04_knowledge-pipeline | 文档解析、清洗、分块和审核流 | 公开/授权资料 | Knowledge Document/Chunk | 00 | 在线检索和生成 |
| 05_rag-engine | 查询、检索、重排、引用 | Assessment 摘要、Approved Chunks | Retrieval Result | 00、04 | 改写测评结果 |
| 06_llm-runtime | 本地模型注册、健康、推理 | 结构化 Prompt | Provider Response | 00 | 决定心理解释 |
| 07_prompt-engine | 模板、角色、版本和输出约束 | Assessment、Retrieval、安全策略 | Generation Request | 00、05、06、08 | 绕过安全规则 |
| 08_safety-engine | 预检、后检、熔断和人工复核 | Assessment、Generation Candidate | Safety Result | 00 | 临床诊断或自主处置 |
| 09_backend | API、权限、编排、错误和审计 | 各模块公开接口 | API Response、流程状态 | 全部运行模块 | 复制算法实现 |
| 10_frontend | 角色页面、状态展示和审核交互 | API Response | 可访问 UI | 09、11 | 直接连接模型/数据库 |
| 11_database | 逻辑模型、迁移、索引和权限 | Contract 对象、审计要求 | 持久化结构 | 00、09 | 业务决策和模型推理 |
| 12_evaluation | 夹具、回归、指标和评价记录 | 合成案例、系统输出 | 测试报告、指标 | 全部受影响模块 | 伪造真实效果 |
| 13_deployment | 本地启动、配置、依赖和排障 | 可运行模块 | 启动方案、运行检查 | 09、11、06 | 把密钥写进仓库 |
| 14_docs | 用户、开发、研究和限制文档 | 已确认事实、测试记录 | 文档、变更记录 | 全部 | 编造功能和证据 |
| 15_demo | 可重复演示和备份素材 | 合成案例、可运行链路 | Demo 脚本、数据、备份 | 09、10、12、13 | 使用真实敏感数据 |

## 2. 依赖分层

~~~text
00_architecture
    ├── 02_item-bank ── 01_cat-engine ── 03_assessment-adapter
    ├── 04_knowledge-pipeline ── 05_rag-engine
    ├── 06_llm-runtime
    ├── 08_safety-engine
    └── 07_prompt-engine
             └── 09_backend ── 10_frontend
                         └── 11_database
12_evaluation / 13_deployment / 14_docs / 15_demo
    consume verified outputs from the layers above
~~~

上图表示逻辑依赖，不要求 Agent 按目录顺序开发；未就绪的上游使用接口桩和合成 fixture。

## 3. 共享资产所有权

| 资产 | 所有人 | 修改方式 |
| --- | --- | --- |
| 根级治理文件 | 项目负责人/架构 Agent | 提案 + 审批 |
| 四项 Contract | 架构 Agent | 变更记录 + 校验器/fixture 更新 |
| 题库格式 | Item Bank | 遵守 Assessment 映射，破坏性变化需审批 |
| Knowledge Schema 资料字段 | Knowledge Pipeline | 遵守引用、审核和版权状态 |
| Safety reason codes | Safety Engine | 需同步 Contract 和测试集 |
| API 路径与错误码 | Backend/架构 Agent | 需同步 Contract |
| 数据库迁移 | Database | 需说明向后兼容和回滚 |
| UI 文案和帮助内容 | Frontend/Docs | Humanizer → Vale；不能超出产品事实 |

## 4. 跨模块交付格式

每个模块向集成负责人交付：

- 变更文件清单；
- 对应 TASK.md 的完成项；
- 输入/输出样例；
- Contract 影响说明；
- 实际验证命令和结果；
- 未覆盖范围；
- 可复用的启动或调用说明。

## 5. 目录修改边界

默认规则是 Agent 只能修改自己负责的模块目录和由任务明确授权的测试/fixture 目录。根级文档、其他模块代码、配置、锁文件和 CI 文件均属于共享变更，必须先提出并获得项目负责人确认。

