# Architecture

本文件描述系统边界、数据流、信任边界、模块依赖和集成约束。它只规定工程结构，不替代心理学工具的专业验证。

## 1. 架构目标

- 让 CAT、知识库、RAG、本地 LLM、Prompt、安全、应用和数据库可以独立开发；
- 用稳定的 Contract 连接模块，避免模块间直接依赖内部实现；
- 默认本地处理，必要的外部连接显式配置并可审计；
- 所有个性化生成都经过安全策略和人工复核状态控制；
- 让每个结果可回答：依据了什么测评、什么知识、什么模型、什么 Prompt、谁审核过。

## 2. 逻辑组件

| 层 | 组件 | 主要职责 |
| --- | --- | --- |
| 入口 | Student / Teacher / Parent / Admin UI | 发起测评、查看受控结果、提交审核，不直接调用模型 |
| 编排 | Backend API / Service Layer | 鉴权、状态机、调用顺序、错误转换和审计 |
| 测评 | CAT Engine / Item Bank / Assessment Adapter | 选题、估计、终止、题库校验、外部格式适配 |
| 知识 | Knowledge Pipeline / RAG Engine | 清洗、分块、检索、重排、上下文和引用 |
| 智能 | Prompt Engine / LLM Runtime | 组装受控 Prompt、调用本地模型、解析结构化输出 |
| 安全 | Safety Engine | 预检、生成约束、后检、熔断、人工复核 |
| 持久化 | Database / Audit Store | 保存最小必要业务数据和可追溯元数据 |
| 评估 | Evaluation / Demo / Docs | 合成案例、回归、专家评价准备、演示和记录 |

## 3. 主数据流

1. 用户或适配器创建测评会话；
2. CAT Engine 从已审核题库选择题目，返回测评结果；
3. Backend 校验 Assessment Schema，写入测评摘要和版本信息；
4. Safety Engine 对结果执行生成前风险检查；
5. RAG Engine 根据维度、角色和风险状态构造查询，只检索允许使用的 Knowledge Chunk；
6. Prompt Engine 将角色模板、测评上下文、检索上下文、安全约束和输出 Schema 组合成请求；
7. LLM Runtime 通过本地 Provider 生成结构化候选；
8. Safety Engine 执行输出后检；
9. 普通状态可以进入待发布/已批准流程，高风险或不确定状态进入人工复核；
10. Backend 保存 Generation、引用、版本、审核和错误记录；
11. UI 只展示当前权限允许的结果，不展示不必要的内部模型细节。

## 4. 信任边界

### 4.1 不可信输入

- 外部测评导出文件；
- 用户提交的文本；
- 知识文档和文档元数据；
- 模型输出；
- 第三方 Provider 响应。

所有这些输入必须经过 Schema、格式、大小、编码、权限和安全校验。

### 4.2 可信配置

- 经过审核的题库版本；
- 经过审核的知识文档和片段；
- Prompt 模板及版本；
- 风险规则和转介配置；
- 模型注册表和运行策略。

可信不代表永久正确；每项都要有版本、负责人和审核状态。

### 4.3 敏感数据边界

原始作答和可识别信息只能停留在受控的数据边界内。RAG、Prompt、模型和普通日志默认使用脱敏后的摘要，不接收姓名、学号、联系方式或未审核的自由文本。

## 5. 适配器约束

### 5.1 测评适配器

所有 FlexCAT 或其他来源必须转成 assessment.v1。适配器不得把来源字段原样扩散给下游，也不得在转换时自行解释心理含义。

### 5.2 LLM Provider

Runtime 对上层只暴露统一能力：健康检查、模型信息、同步生成、流式生成（可选）、超时、取消、错误分类和结构化输出。Ollama、llama.cpp 或其他 Provider 只能存在于适配器内部。

### 5.3 向量库和 Embedding

RAG 上层只依赖检索接口和结果结构，不依赖 ChromaDB 的内部对象。Embedding 模型和向量库的版本必须进入检索审计记录。

## 6. 关键状态机

### 6.1 测评

created -> in_progress -> completed

异常状态：abandoned、invalid。completed 只代表数据收集完成，不代表临床或心理学结论成立。

### 6.2 生成

流程节点：requested -> precheck -> retrieving -> generating -> postcheck -> generated。

阻断分支：precheck -> safety_blocked；postcheck -> needs_review。

人工处理后：needs_review -> approved | rejected。precheck、retrieving、generating 和 postcheck 是流程节点，不是 Generation Result 的可发布状态。

### 6.3 知识片段

ingested -> parsed -> chunked -> pending_review -> approved | rejected

只有 approved 且版权/使用状态允许的片段可以进入生产检索。

## 7. 可观测性与审计

每次跨模块调用至少传递：

- request_id
- trace_id
- 相关业务 ID
- schema_version
- 组件版本
- 操作结果和错误码

日志不得包含原始敏感回答、完整 Prompt 中的身份信息或未脱敏模型上下文。审计需要记录引用和版本，不等于复制全部敏感内容。

## 8. 配置边界

配置由环境变量、受控配置文件和版本化注册表组成。业务代码只能读取已声明的 config.v1 字段；未知字段、缺失必填组件和不允许的路径/密钥写法必须在启动时失败。模型、Embedding、向量库、数据库和缓存路径都必须可替换。

## 9. 架构变更规则

任何改变以下内容的修改都必须先更新 CONTRACTS.md，后更新实现：

- 必填字段、字段类型或枚举；
- ID 规则；
- 高风险处理路径；
- API 路径或错误格式；
- 版本/审计字段；
- 数据访问边界。
