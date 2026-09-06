# 07_prompt-engine：角色 Prompt 与结构化生成请求

## 职责

- 管理 system、student、teacher、parent 和 safety 相关模板；
- 将模板、Assessment 摘要、检索引用、安全约束和输出 Schema 组装起来；
- 为每个 Prompt 维护 ID、版本、适用角色、变更说明和审核状态；
- 输出符合 generation.v1 的请求；
- 让 Prompt 变更可比较、可回归和可审计。

## 输入

- assessment.v1 的脱敏摘要；
- RAG Engine 的 retrieval_id、approved chunk_ids 和引用；
- Safety Engine 的安全约束；
- 角色、语言、用途和输出字段配置；
- 已审核的模板和 Prompt 版本。

## 输出

- Generation Request；
- 渲染后的内部 Prompt 摘要或哈希；
- Prompt 版本和变更记录；
- 缺少引用、角色不支持、风险不允许时的拒绝结果。

## 禁止事项

- 不自行分类风险或修改安全结论；
- 不把原始身份信息、未脱敏回答或未审核自由文本放进 Prompt；
- 不让模型自由决定输出字段、引用或审核状态；
- 不写“诊断”“治疗保证”或替代专业人员的指令；
- 不用 Prompt 文字绕过 08_safety-engine 的阻断。

## 接口

- resolve_template(role, version) -> approved template；
- render(assessment_summary, retrieval_context, safety_constraints) -> generation.v1 request；
- validate_prompt(request) -> issues；
- register_version(prompt_id, version, changes) -> registry entry；
- Generation Request 必须包含 assessment_id、subject_id、target_role、retrieval、prompt_ref 和 model_policy。

## 验收标准

- 学生、教师和家长模板有明确目标和输出差异；
- 所有事实性建议都要求引用 source_chunk_ids；
- 普通、attention、high/crisis 状态对应不同安全约束；
- 模板缺失、版本不存在和引用不合规会被拒绝；
- 同一输入、模板和配置可以复现请求摘要；
- Prompt 变更能触发对应 Evaluation 回归。

## 交付物

- Prompt 目录结构和模板元数据规范；
- 至少三类角色的占位模板；
- Generation Request fixture；
- Prompt 版本/变更记录；
- Prompt 安全检查清单和回归说明。

