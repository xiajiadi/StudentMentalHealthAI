# 03_assessment-adapter：测评格式适配

## 职责

- 将 FlexCAT 或其他已授权测评导出转换为统一的 assessment.v1；
- 校验来源格式、工具版本、字段映射和数据完整性；
- 保留适配器版本与来源追踪信息；
- 对无法安全映射的字段显式报错；
- 提供离线转换和可重复的转换测试。

## 输入

- FlexCAT/其他工具的 JSON、CSV 或明确格式导出；
- 工具字段映射表和题库版本；
- 已确认的人群范围、维度和解释配置；
- CONTRACTS.md 中 Assessment Schema。

## 输出

- 合法的 assessment.v1；
- 转换报告、警告、拒绝原因和来源哈希；
- 字段映射文档；
- 输入格式样例和输出 fixture；
- 不支持来源的稳定错误码。

## 禁止事项

- 不把原始工具字段未经审查地传播给下游；
- 不擅自把分数映射成风险或诊断；
- 不补造缺失的 theta、标准误、题目参数或人口范围；
- 不改变原始测评工具的题意、计分或解释；
- 不保留不必要的原始导出文件和身份信息。

## 接口

- parse(source_file) -> normalized source object；
- map(normalized, mapping_version) -> assessment.v1；
- validate(result) -> contract errors/warnings；
- 输出 provenance.source_adapter、adapter_version 和 item_bank_version；
- 映射不完整时返回 ASSESSMENT_SCHEMA_INVALID 或专用映射错误。

## 验收标准

- 至少支持一个明确记录的来源格式；
- 合法输入可稳定转换，重复转换结果一致；
- 缺工具版本、未知维度、字段类型错误和身份字段泄露会被拒绝或脱敏；
- 输出通过 assessment.v1 校验；
- 转换不会凭空产生风险等级；
- 有端到端 fixture 覆盖普通、边界和失败输入。

## 交付物

- 格式解析器和映射配置；
- assessment.v1 输出样例；
- 字段映射表和限制说明；
- 转换测试与错误码说明；
- 面向集成 Agent 的调用说明。

