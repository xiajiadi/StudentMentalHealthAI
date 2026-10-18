# Core Contracts

本文件是跨模块接口的规范来源。当前维护四项 v1 基线：assessment.v1、knowledge.v1、generation.v1、api.v1。

公共 Contract 发布标签 v0.1.0 继续保持 FROZEN。当前本地工作分支为固定题表增加 `risk.level=not_assessed` 的工作扩展，用于明确表达“未进行风险分类”；该扩展不属于 v0.1.0 发布范围，也不代表测量学或专业批准。进入后续发布前必须完成兼容性与版本审查。

## 0.1 机器可读资产

- JSON Schema：00_architecture/schemas/assessment.v1.schema.json
- JSON Schema：00_architecture/schemas/knowledge.v1.schema.json
- JSON Schema：00_architecture/schemas/generation.v1.schema.json
- 配置 Schema：00_architecture/schemas/config.v1.schema.json
- 结构化日志 Schema：00_architecture/schemas/logging.v1.schema.json
- OpenAPI：00_architecture/openapi.v1.json
- Contract Test：00_architecture/tests/test_contracts.py
- 合法 fixture：00_architecture/fixtures/

## 0. 冻结范围与变更规则

### 已冻结

- 顶层版本字段和 ID 前缀；
- 必填字段的语义；
- 状态枚举；
- 高风险阻断不变量；
- API 的 JSON 错误外壳；
- 审计和追踪字段的最小要求。

### 尚未冻结

- 具体测评工具、题目、维度和心理学解释；
- 任意风险阈值和分数 cut-off；
- 最终模型名称、量化参数和硬件；
- 具体转介联系人、电话和机构流程；
- 真实数据字段和研究分析计划。

### 变更规则

任何破坏性变更必须：

1. 先提出变更说明和迁移方案；
2. 更新本文件与受影响的 TASK.md；
3. 更新 fixture、校验器和集成测试；
4. 由项目负责人批准后才能修改版本或实现。

非破坏性新增字段必须标为 optional，并说明默认行为。

## 1. 通用规则

### 1.1 编码和格式

- HTTP 和文件接口默认 UTF-8 JSON；
- 日期时间使用 ISO 8601 UTC，例如 2026-09-04T12:00:00Z；
- 数值使用 JSON number，不把数值塞进字符串；
- 未知值使用 null 或明确的 unknown，禁止用空字符串伪造已知值；
- 所有顶层对象包含对应的 schema_version。

### 1.2 ID

| 对象 | 前缀 | 示例 |
| --- | --- | --- |
| 匿名主体 | SUBJ_ | SUBJ_demo_001 |
| 测评 | ASSESS_ | ASSESS_demo_001 |
| 题目 | ITEM_ | ITEM_demo_001 |
| 知识文档 | KB_ | KB_policy_001 |
| 知识片段 | CHUNK_ | CHUNK_policy_001_003 |
| 检索运行 | RETR_ | RETR_demo_001 |
| 生成 | GEN_ | GEN_demo_001 |
| 报告 | REPORT_ | REPORT_demo_001 |
| Prompt | PROMPT_ | PROMPT_teacher_v1 |
| 模型 | MODEL_ | MODEL_local_primary |
| 请求 | REQ_ | REQ_demo_001 |
| 追踪 | TRACE_ | TRACE_demo_001 |

ID 必须稳定、不可通过 ID 本身推断身份。正式环境不得使用姓名、学号或联系方式作为 ID。

### 1.3 版本

使用 object.vN 形式，例如 assessment.v1。组件版本另行记录，例如 cat_engine_version、prompt_version、model_version。版本字段不能被下游静默覆盖。

### 1.4 Config Contract

配置对象使用 config.v1。配置必须区分环境、组件注册、资源限制和路径引用：

- environment 只允许 local、test、demo、research；
- components 必须声明 backend、database、vector_store、llm_runtime 和 embedding；
- 模型、Embedding、向量库和服务地址使用注册表或环境变量引用；
- limits 必须显式声明超时、检索 top_k 和上下文上限；
- 敏感值只能从环境变量或受控密钥存储读取，不得写入 JSON、日志或仓库；
- 本地数据、模型和缓存路径必须可配置，不能写死系统目录；
- 未知配置键默认拒绝，防止拼写错误造成静默降级。

### 1.5 ID Contract

ID 使用本文件 1.2 的对象前缀和稳定后缀。生成器必须保证同一对象在同一版本内稳定且唯一；ID 不得包含姓名、学号、手机号、邮箱或可逆身份编码。跨模块引用必须使用 ID，不得复制一份可能漂移的对象作为隐式关联。

### 1.6 Version Contract

- 公共 Schema 版本使用 object.vN；
- 公共发布标签使用 SemVer，当前候选为 v0.1.0；
- 组件版本使用可比较的版本标签，并随结果写入 provenance；
- 破坏性字段变更必须升级 Schema 主版本；
- 非破坏性字段只能以 optional 方式新增，并说明默认行为；
- 任何结果都不能被下游静默改写为另一个版本。

### 1.7 Logging Contract

跨模块调用和关键状态转移使用 logging.v1 结构化日志。日志至少包含 timestamp、level、event、component、request_id、trace_id 和 outcome；可选记录 duration_ms、error_code、业务 ID 引用和受控 metadata。

日志规则：

- event、outcome、error_code 使用稳定代码，不用不可控的长自由文本；
- 不记录姓名、学号、联系方式、原始回答、完整 Prompt、模型上下文、密钥或令牌；
- 不把日志当作业务数据源，业务结果写入受控存储；
- ERROR/阻断事件必须有可关联的 request_id 和 trace_id；
- 日志保留、访问和脱敏策略必须按环境配置；
- 任何不确定的敏感字段默认拒绝写入。

## 2. Assessment Schema

### 2.1 用途

表示已完成或正在传递的测评摘要，供 Backend、RAG、安全和报告模块使用。它不是诊断报告，也不包含下游不需要的原始作答。

### 2.2 规范示例

~~~json
{
  "schema_version": "assessment.v1",
  "assessment_id": "ASSESS_demo_001",
  "subject_id": "SUBJ_demo_001",
  "instrument": {
    "instrument_id": "instrument_pending",
    "version": "unconfirmed"
  },
  "population_scope": "pending_confirmation",
  "status": "completed",
  "dimensions": {
    "emotion": {
      "theta": -0.82,
      "se": 0.24,
      "score": null,
      "band": "unknown",
      "interpretation_status": "estimated",
      "items_answered": 5
    }
  },
  "risk": {
    "level": "attention",
    "need_human_review": false,
    "reason_codes": ["RULESET_DEMO_ATTENTION"],
    "ruleset_id": "RULESET_demo_v1"
  },
  "response_summary": {
    "items_answered": 17,
    "duration_seconds": 420
  },
  "provenance": {
    "source_adapter": "demo_adapter",
    "adapter_version": "0.1.0",
    "cat_engine_version": "not_applicable",
    "item_bank_version": "demo.v1"
  },
  "timestamps": {
    "started_at": "2026-09-04T12:00:00Z",
    "completed_at": "2026-09-04T12:07:00Z"
  }
}
~~~

### 2.3 字段与不变量

| 字段 | 必填 | 约束 |
| --- | --- | --- |
| schema_version | 是 | 必须为 assessment.v1 |
| assessment_id | 是 | ASSESS_ 前缀，唯一 |
| subject_id | 是 | SUBJ_ 前缀，匿名化 |
| instrument | 是 | 必须包含工具 ID 和版本；未确认时显式标记 |
| population_scope | 是 | 不得省略人群适用范围 |
| status | 是 | created、in_progress、completed、abandoned、invalid |
| dimensions | 是 | 维度键由已批准工具注册表定义，不能由模型临时生成 |
| risk | 是 | 运行状态，不得描述为临床诊断 |
| response_summary | 是 | 只保留最小摘要，不含原始回答 |
| provenance | 是 | 能回溯适配器、CAT 和题库版本 |
| timestamps | 是 | 完成状态必须有 completed_at |

risk.level 可为 normal、attention、high、crisis，或 `not_assessed`。这是操作分流字段，不是疾病分级；`not_assessed` 明确表示系统没有进行风险分类，不能解释为 normal 或其他心理状态。此类固定题表记录不进入测后个性化生成队列。

若 risk.level 为 high 或 crisis，risk.need_human_review 必须为 true，且 Generation Contract 不得返回可自动发布的个性化建议。

## 3. Knowledge Schema

### 3.1 用途

表示知识文档及其可检索片段。只有来源、使用状态和专业审核状态明确的片段才能进入生产检索。

### 3.2 文档对象

~~~json
{
  "schema_version": "knowledge.v1",
  "document_id": "KB_demo_001",
  "title": "Demo approved source",
  "source": {
    "organization": "pending_confirmation",
    "author": null,
    "published_year": null,
    "source_type": "other",
    "locator": {
      "url": null,
      "file_name": "demo_source.md"
    }
  },
  "language": "zh-CN",
  "population_scope": ["pending_confirmation"],
  "category": "practice_guidance",
  "rights_status": "unknown",
  "review_status": "pending",
  "version": "1.0.0",
  "content_hash": "sha256:pending",
  "ingestion": {
    "pipeline_version": "pending",
    "ingested_at": "2026-09-04T12:00:00Z"
  }
}
~~~

### 3.3 片段对象

~~~json
{
  "schema_version": "knowledge.v1",
  "chunk_id": "CHUNK_demo_001_001",
  "document_id": "KB_demo_001",
  "text": "Approved source text or approved summary.",
  "content_type": "source_excerpt",
  "location": {
    "section": "pending",
    "page_start": null,
    "page_end": null
  },
  "citation": {
    "title": "Demo approved source",
    "organization": "pending_confirmation",
    "locator": "section:pending"
  },
  "population_scope": ["pending_confirmation"],
  "role_scope": ["student", "teacher", "parent"],
  "risk_scope": ["normal", "attention"],
  "review_status": "pending",
  "rights_status": "unknown",
  "content_hash": "sha256:pending",
  "embedding": {
    "model_id": null,
    "model_version": null,
    "status": "not_indexed"
  }
}
~~~

### 3.4 知识不变量

- review_status != approved 的片段不得进入生产检索；
- rights_status 为 unknown 或 restricted 时不得自动发布；
- citation 必须能定位来源；没有定位的片段只能作为待审核素材；
- text 不得混入学生身份信息、未脱敏测评回答或模型生成的假引用；
- 分块、去重和向量化必须保留 document_id、chunk_id 和内容哈希；
- 检索返回值必须保留 chunk_id 和引用信息，不能只返回裸文本。

Knowledge 的受控枚举如下：

- source_type：government、academic、textbook、practice_guidance、local_protocol、other；
- category：policy、theory、practice_guidance、referral、other；
- content_type：source_excerpt、approved_summary；
- rights_status：verified、unknown、restricted；
- review_status：pending、approved、rejected；
- embedding.status：not_indexed、indexed、failed。

具体枚举只有在同步更新校验器、fixture 和受影响模块任务后才能扩展。

## 4. Generation Schema

### 4.1 生成请求

~~~json
{
  "schema_version": "generation.v1",
  "generation_id": "GEN_demo_001",
  "assessment_id": "ASSESS_demo_001",
  "subject_id": "SUBJ_demo_001",
  "target_role": "teacher",
  "purpose": "education_support",
  "language": "zh-CN",
  "safety_mode": "standard",
  "retrieval": {
    "retrieval_id": "RETR_demo_001",
    "chunk_ids": ["CHUNK_demo_001_001"]
  },
  "prompt_ref": {
    "prompt_id": "PROMPT_teacher_v1",
    "prompt_version": "1.0.0"
  },
  "model_policy": {
    "model_id": "MODEL_local_primary",
    "provider_class": "local"
  }
}
~~~

### 4.2 生成结果

~~~json
{
  "schema_version": "generation.v1",
  "generation_id": "GEN_demo_001",
  "status": "needs_review",
  "target_role": "teacher",
  "content": {
    "summary": "待审核的教育支持摘要。",
    "observations": [],
    "suggestions": [
      {
        "text": "建议与学生进行一次非评判性的支持性沟通。",
        "source_chunk_ids": ["CHUNK_demo_001_001"]
      }
    ],
    "disclaimer": "此内容用于教育支持，不构成诊断或治疗建议。"
  },
  "safety": {
    "precheck": "passed",
    "postcheck": "needs_review",
    "reason_codes": ["OUTPUT_REVIEW_REQUIRED"],
    "human_review_required": true
  },
  "provenance": {
    "assessment_id": "ASSESS_demo_001",
    "retrieval_id": "RETR_demo_001",
    "prompt_id": "PROMPT_teacher_v1",
    "prompt_version": "1.0.0",
    "model_id": "MODEL_local_primary",
    "model_version": "pending",
    "runtime_version": "pending"
  },
  "review": {
    "status": "pending",
    "reviewer_id": null,
    "reviewed_at": null
  },
  "created_at": "2026-09-04T12:08:00Z"
}
~~~

### 4.3 生成不变量

- target_role 只允许 student、teacher、parent、admin；
- purpose 当前只允许 education_support，其他用途必须先扩展规范；
- status 只允许 requested、safety_blocked、generating、generated、needs_review、approved、rejected；
- 结构化 content 缺失、引用缺失或安全后检失败时，不得返回 approved；
- Assessment 为 high 或 crisis 时，结果必须是 safety_blocked 或 needs_review，不得自动 approved；
- 所有事实性建议必须带一个或多个已审核 source_chunk_ids，或者明确标注为非事实性沟通模板；
- 输出不得声称诊断、保证效果、替代专业人员或虚构来源；
- 模型原始输出不能直接暴露给普通用户，必须先解析、校验和后检。

## 5. API Contract

### 5.1 基本约定

- 基础路径：/api/v1
- 请求和成功响应：JSON UTF-8
- 每次请求由服务端生成或校验 request_id、trace_id
- 需要重试的写操作支持 Idempotency-Key
- 认证、角色授权和数据范围检查由 Backend 负责
- 服务端内部错误不把堆栈、Prompt、密钥或敏感上下文返回给用户

### 5.2 端点

下表路径均相对于基础路径 /api/v1。

| 方法 | 路径 | 输入 | 成功结果 |
| --- | --- | --- | --- |
| GET | /health | 无 | 服务和依赖的非敏感状态 |
| GET | /assessments | 可选 `limit`、`skip`、`status` | 权限范围内的测评数组 |
| POST | /assessments | 测评工具、匿名主体、配置引用 | 创建 Assessment |
| POST | /assessments/{assessment_id}/responses | 单题回答事件 | 当前测评状态 |
| POST | /assessments/{assessment_id}/complete | 完成请求 | assessment.v1 |
| POST | /retrievals | 查询、角色、Assessment 摘要 | 检索 ID、片段和引用 |
| POST | /safety/checks | Assessment 或 Generation 候选 | 安全状态和 reason codes |
| POST | /generations | Generation Request | generation.v1 |
| GET | /reports/{report_id} | 报告 ID | 权限范围内的报告和审核状态 |
| POST | /reports/{report_id}/reviews | 审核动作和备注 | 更新后的审核状态 |

`GET /assessments` 先按已授权的主体范围筛选，再按开始时间从新到旧、测评 ID 从大到小稳定排序。`limit` 可选，取值为 1–100；`skip` 可选且默认 0；`status` 可选，支持 `created`、`in_progress`、`completed`、`abandoned`、`invalid`。这三个参数都是可选的，不带参数时继续返回旧版的完整结果数组；分页和状态过滤仍使用原有成功响应外壳，不返回额外的总数。

学生测评页每页请求 30 条，点击“加载更多”时使用当前状态筛选和已请求行数作为 `skip`。当返回条数少于 30 时隐藏按钮；刚好返回 30 条时保留按钮，下一次请求为空后再隐藏。

### 5.3 成功响应外壳

~~~json
{
  "request_id": "REQ_demo_001",
  "trace_id": "TRACE_demo_001",
  "data": {}
}
~~~

data 的具体内容由端点映射到本文件规定的对象，不得返回未声明的内部对象。

### 5.4 错误响应外壳

~~~json
{
  "request_id": "REQ_demo_001",
  "trace_id": "TRACE_demo_001",
  "error": {
    "code": "ASSESSMENT_SCHEMA_INVALID",
    "message": "测评结果未通过格式校验。",
    "details": {
      "fields": ["risk.level"]
    },
    "retryable": false
  }
}
~~~

建议错误码按 DOMAIN_REASON 命名，例如：

- AUTH_UNAUTHORIZED
- AUTH_FORBIDDEN
- ASSESSMENT_NOT_FOUND
- ASSESSMENT_SCHEMA_INVALID
- KNOWLEDGE_NOT_APPROVED
- RETRIEVAL_UNAVAILABLE
- MODEL_UNAVAILABLE
- GENERATION_SCHEMA_INVALID
- SAFETY_BLOCKED
- HUMAN_REVIEW_REQUIRED
- CONFLICT_IDEMPOTENCY
- INTERNAL_ERROR

错误信息面向用户时保持简洁；技术细节写入受控日志并通过 request_id 关联。

### 5.5 端点不变量

- Backend 必须在跨模块调用前后校验 Contract；
- 不能通过 API 绕过安全检查或人工审核；
- 高风险请求即使模型可用，也必须遵守阻断状态；
- 重新提交同一 Idempotency-Key 不得产生重复生成或重复审核事件；
- API 日志不得记录原始测评回答、完整 Prompt 或敏感个人信息。

## 6. 端到端最小映射

POST /assessments/{id}/complete 返回 assessment.v1；

POST /retrievals 消费 Assessment 摘要，产生带 retrieval_id 的片段引用；

POST /generations 消费 Assessment、Retrieval 和 Prompt/Model 引用，返回 generation.v1；

POST /reports/{id}/reviews 只改变审核状态和审计信息，不修改原始测评结果、检索结果或模型版本。
