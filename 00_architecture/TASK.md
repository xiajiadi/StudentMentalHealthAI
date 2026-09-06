# 00_architecture：总架构与 Contract 治理

## 职责

- 维护项目总体架构、模块边界、依赖关系和版本策略；
- 维护四项核心 Contract 的规范、示例、枚举和不变量；
- 收集模块变更提案，识别破坏性变化并要求迁移方案；
- 维护 ADR、集成门禁和跨模块 fixture 约定；
- 维护机器可读 JSON Schema、OpenAPI 和 Contract Test；
- 明确 Config、ID、Version、Logging 的字段级规则；
- 把未确认的研究、伦理、量表和部署决策明确列出。

## 输入

- PROJECT.md、ARCHITECTURE.md、ROADMAP.md、CONTRACTS.md、MODULES.md；
- 项目负责人确认的产品、测评、隐私和安全决策；
- 各模块提交的接口变更提案、fixture 和验证结果。

## 输出

- 可被所有 Agent 直接引用的根级规范；
- assessment.v1、knowledge.v1、generation.v1、api.v1 的示例和校验要求；
- 版本/ID/错误码登记；
- ADR、依赖图、集成检查清单；
- 可运行的 Schema/OpenAPI/Contract 验证入口；
- 待确认决策表和风险清单。

## 禁止事项

- 不实现 CAT、RAG、模型、前端或数据库业务功能；
- 不自行决定研究对象、量表解释、风险阈值、转介流程或临床结论；
- 不把示例字段、示例分数或暂定技术栈写成已验证事实；
- 不为了让某个模块通过而放宽高风险阻断；
- 不直接覆盖其他模块的代码或私自改动 Contract。

## 接口

- 规范来源：根目录 CONTRACTS.md；
- 变更入口：变更提案 + ADR + 受影响 TASK.md；
- 交付格式：版本、字段映射、兼容策略、fixture、验证命令和未覆盖范围；
- 集成检查：确认所有跨模块输入输出均能映射到公开 Contract。

## 验收标准

- 四项 Contract 的字段、状态、ID、错误外壳和安全不变量没有互相矛盾；
- 机器可读 Schema、OpenAPI 和文档示例彼此一致；
- Config、ID、Version、Logging 规则有正向和负向测试；
- 每个模块 TASK.md 都能找到输入、输出、禁止事项和验收标准；
- 对至少一个合法样例和一个拒绝样例给出明确行为；
- 破坏性变化有版本升级和迁移说明；
- 待确认事项不会被下游当成默认科学结论；
- 负责人可以据此分发并行任务而无需重新解释边界。

## 交付物

- 根级治理文件更新；
- Contract 示例和校验 fixture 约定；
- ADR/变更记录；
- 集成前检查清单；
- 面向项目负责人的未决问题清单。
