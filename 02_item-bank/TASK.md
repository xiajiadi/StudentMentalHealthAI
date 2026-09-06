# 02_item-bank：题库与参数管理

## 职责

- 管理题目文本、选项、维度、模型参数、来源、版本和启用状态；
- 支持 CSV、JSON 或经批准的其他格式导入；
- 执行 ID、字段、参数范围、维度和版本校验；
- 输出 CAT Engine 和 Assessment Adapter 可消费的标准题库；
- 保留题目来源和审核状态，支持可追溯导出。

## 输入

- 经过授权的题目资料、题库导出文件和参数文件；
- 已确认的测评工具注册表；
- 02 模块配置和 CONTRACTS.md；
- 项目负责人/心理学负责人确认的题目审核结果。

## 输出

- 标准化题目集合；
- 题库版本、内容哈希和变更摘要；
- 导入/导出报告；
- 结构错误、重复 ID、缺参数、参数越界和未知维度的错误信息；
- 提供给 CAT Engine 的可用题目查询接口。

## 禁止事项

- 不修改题目原意、量表计分规则或心理学解释；
- 不自行补填缺失参数或把默认值伪装成校准值；
- 不决定风险阈值、诊断等级或生成话术；
- 不把未审核题目标记为生产可用；
- 不在题库文件中保存真实学生身份信息。

## 接口

- import(source) -> validation report + draft item bank；
- validate(item_bank) -> errors/warnings + content hash；
- list_available(instrument, version, dimension) -> approved items；
- export(version, format) -> standardized item data；
- 每条题目必须能映射到题目 ID、工具版本、维度、参数来源和审核状态。

## 验收标准

- 重复 ID、未知维度、缺少必填字段和非法参数都会被拒绝；
- 草稿、审核中、已批准和停用题目状态可区分；
- 题库版本可复现，导出后重新导入不改变语义字段；
- CAT Engine 只能读取已批准且启用的题目；
- 题目来源和变更记录可查询；
- 测试中不出现真实身份数据。

## 交付物

- 题库数据模型和验证器；
- 合法/非法导入 fixture；
- 题库版本登记和变更说明模板；
- CAT Engine 查询接口或 Mock；
- 导入导出使用说明。

