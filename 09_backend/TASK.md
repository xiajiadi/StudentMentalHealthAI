# 09_backend：API 与业务编排

## 职责

- 提供 api.v1 规定的 HTTP 入口；
- 负责认证、角色授权、资源范围、状态机和幂等；
- 编排 CAT、Adapter、RAG、Prompt、Runtime、Safety 和 Database；
- 统一错误外壳、请求追踪、审计和报告查询；
- 保持算法模块与 UI、数据库之间的边界。

## 输入

- 前端或适配器的 HTTP 请求；
- 各模块公开接口和核心 Contract；
- 用户角色、权限和数据范围；
- 数据库 Repository；
- 配置、规则集和模型注册表引用。

## 输出

- api.v1 成功/错误响应；
- 测评、检索、生成、审核和报告的流程状态；
- request_id、trace_id 和审计事件；
- 对用户可理解且不暴露内部细节的错误信息。

## 禁止事项

- 不把 CAT、RAG、Prompt 或安全算法复制进 Backend；
- 不允许 API 绕过安全检查、人工复核或权限；
- 不让前端直接连接数据库、向量库或模型；
- 不记录完整 Prompt、原始回答、密钥或身份信息；
- 不在接口层编造测评解释、风险阈值或报告事实。

## 接口

- GET /api/v1/health；
- GET /api/v1/assessments（可选 limit、skip、status；在授权主体范围内分页）；
- POST /api/v1/assessments；
- POST /api/v1/assessments/{assessment_id}/responses；
- POST /api/v1/assessments/{assessment_id}/complete；
- POST /api/v1/retrievals；
- POST /api/v1/safety/checks；
- POST /api/v1/generations；
- GET /api/v1/reports/{report_id}；
- POST /api/v1/reports/{report_id}/reviews；
- 所有写操作遵守 Idempotency-Key 和 CONTRACTS.md 的错误外壳。

## 验收标准

- 每个端点都有请求校验、权限检查、成功响应和错误响应；
- 跨模块调用前后均进行 Contract 校验；
- high/crisis 流程不能自动发布个性化建议；
- 重试不会重复创建生成或审核事件；
- 依赖不可用时返回稳定错误码和可追踪 request_id；
- 至少一条合成案例端到端冒烟通过。

## 交付物

- API 路由、服务编排和 Repository 接口；
- 鉴权/角色权限矩阵；
- 错误码和状态机映射；
- Contract/API 测试；
- 本地运行与调用示例、未覆盖范围。

## Round 1 治理与执行记录

根契约 v0.1.0 保持 FROZEN。Backend Round 1 只修改本模块、backend-specific
research 和 reports；不修改其他模块，不创建数据库 schema、SQLAlchemy、
Alembic、DDL，不直接调用 Ollama，不计算 CAT theta/SE，不复制 RAG 或
Safety 算法。

完成的 Round 1 任务：

- BACKEND-R1-01 Governance
- BACKEND-R1-02 OSS research
- BACKEND-R1-03 Standards review
- BACKEND-R1-04 Technical Decision
- BACKEND-R1-05 Python runtime
- BACKEND-R1-06 App Factory
- BACKEND-R1-07 Config
- BACKEND-R1-08 Request Context
- BACKEND-R1-09 Problem Details
- BACKEND-R1-10 Structured Logging
- BACKEND-R1-11 Repository Ports
- BACKEND-R1-12 InMemory Adapters
- BACKEND-R1-13 Auth
- BACKEND-R1-14 Session
- BACKEND-R1-15 CSRF
- BACKEND-R1-16 Authorization
- BACKEND-R1-17 Rate Limit
- BACKEND-R1-18 HTTP Client Base
- BACKEND-R1-19 Safety Client
- BACKEND-R1-20 Real Safety Integration
- BACKEND-R1-21 CAT Client
- BACKEND-R1-22 RAG Client
- BACKEND-R1-23 LLM Client
- BACKEND-R1-24 Support Orchestrator
- BACKEND-R1-25 Review Projection
- BACKEND-R1-26 Health
- BACKEND-R1-27 Audit
- BACKEND-R1-28 Idempotency
- BACKEND-R1-29 API Inventory
- BACKEND-R1-30 Unit Tests
- BACKEND-R1-31 Integration Tests
- BACKEND-R1-32 Security Tests
- BACKEND-R1-33 Vertical Slice
- BACKEND-R1-34 Static Quality
- BACKEND-R1-35 Root Contract
- BACKEND-R1-36 Acceptance

具体证据、真实与 ContractFake 边界以及未完成的跨模块接口见
research/OPEN_SOURCE_REFERENCE_AUDIT.md、BACKEND_TECHNICAL_DECISION_V1.md、
reports/ 和各 integration request。
