# 04_knowledge-pipeline：心理健康知识处理流水线

## 职责

- 处理经授权的 PDF、DOCX、Markdown 或其他文档；
- 完成解析、清洗、去重、分块、元数据补全和内容哈希；
- 维护文档/片段来源、页码/章节、版权状态和审核状态；
- 输出 RAG 可消费的 knowledge.v1 文档和片段；
- 为人工审核提供清晰的素材状态和问题报告。

## 输入

- 公开或获得授权的知识资料；
- 来源、组织、年份、适用人群和版权/使用信息；
- 分块、清洗和审核配置；
- CONTRACTS.md 中 Knowledge Schema。

## 输出

- Knowledge Document 和 Knowledge Chunk；
- Embedding-ready JSONL 或等价结构；
- 解析失败、缺来源、重复、乱码和版权状态报告；
- 文档与片段内容哈希；
- 待审核和已批准的可检索集合。

## 禁止事项

- 不把未核实网页、模型生成文本或二手转述伪装成权威来源；
- 不删除导致引用失效的页码、章节或段落定位；
- 不把学生身份信息、原始测评回答或自由文本混入知识库；
- 不自行决定临床建议、风险阈值或危机处置；
- 不让 pending、rejected、restricted 片段进入生产检索。

## 接口

- ingest(document) -> knowledge document draft；
- clean_and_chunk(document) -> knowledge chunks；
- validate(document/chunk) -> issues；
- publish_approved(version) -> approved chunk collection；
- 每个 chunk 必须携带 document_id、chunk_id、citation、population_scope、role_scope、risk_scope 和 review_status。

## 验收标准

- 至少一种文档格式可重复解析；
- 片段都有稳定 ID、内容哈希和可定位引用；
- 缺来源、版权未知、空文本和重复片段有明确处理；
- 未批准片段不能被发布到检索索引；
- 清洗不会悄悄改变来源事实；
- 输出符合 knowledge.v1 并能被 RAG Engine 读取。

## 交付物

- 解析/清洗/分块流水线；
- 合法、乱码、缺引用、重复和敏感信息 fixture；
- Knowledge Schema 输出样例；
- 审核队列和发布说明；
- 一份资料来源与版权状态登记表。

## Round 1 执行记录（2026-09-04）

- 已建立 `CanonicalDocument`、`DocumentParser`、显式 `ParserRouter` 和来源登记；
- 已实际安装并运行 `docling==2.125.0`，解析 PDF 与 DOCX，验证标题/层级、页码、段落顺序、表格块、Markdown/JSON 表示和 `HierarchicalChunker` 基线；
- 已支持带 YAML front matter 的 `human_curated=true` Markdown，并保留显式人工 chunk 标记；
- 已实现 Policy、Theory、Intervention 三种具有不同结构行为的策略；
- 已实现 SHA-256、稳定 ID、非破坏性文件/内容去重、结构化 PASS/WARN/FAIL 质量门、人工审核门、`knowledge.v1` Schema 验证、JSONL 和 manifest 导出；
- MinerU 已完成版本/许可/Windows 兼容性调查，适配器保留但实际安装和运行状态为 `PENDING`；
- 真实运行结果与限制见 `reports/KNOWLEDGE_ROUND1_ACCEPTANCE.md`。
