# 11_database：持久化、迁移与审计存储

## 职责

- 将核心 Contract 映射为最小必要的数据库结构；
- 设计测评、题库、知识、检索、生成、报告、审核和审计关系；
- 提供迁移、索引、约束、访问控制和回滚方案；
- 保存版本与 provenance，使结果可追溯；
- 设计保留、删除和脱敏策略。

## 输入

- CONTRACTS.md 的对象和状态；
- Backend 的 Repository 需求；
- 隐私、访问控制、审计和数据保留要求；
- 合成数据 fixture 和查询场景。

## 输出

- 逻辑数据模型、迁移和初始化 fixture；
- Repository 接口；
- 主键、外键、唯一性、索引和状态约束；
- 审计记录和版本关联；
- 备份、删除、脱敏和回滚说明。

## 禁止事项

- 不擅自增加真实身份字段或扩大数据采集范围；
- 不把完整 Prompt、原始回答和模型上下文无期限保存；
- 不修改业务风险含义或绕过安全状态；
- 不让前端直接访问数据库；
- 不把本机密钥、数据库密码或真实导出数据提交到仓库。

## 接口

- assessment repository；
- knowledge document/chunk repository；
- retrieval log repository；
- generation/report/review repository；
- risk event and audit log repository；
- 所有记录必须能关联业务 ID、schema_version、组件版本和 trace_id。

## 验收标准

- 迁移可在空数据库上重复执行或明确幂等；
- 关键关系、唯一 ID 和状态转换有数据库级或服务级约束；
- 能查询一条完整的 assessment -> retrieval -> generation -> review 链；
- high/crisis 状态和人工复核记录不可被普通写路径覆盖；
- 合成数据初始化和清理可重复；
- 迁移、备份、删除和回滚范围有验证记录。

## 交付物

- 数据模型和迁移文件；
- Repository 接口及测试；
- 合成 fixture；
- 审计/保留/删除设计；
- 与 Backend 集成的查询样例和已知限制。

## Database Round 1 execution state

The following checklist is the module-local execution baseline for the
2026-09-05 Round 1 task. It does not change the frozen root contract.

- [x] DB-R1-01 Governance
- [x] DB-R1-02 MySQL research
- [x] DB-R1-03 SQLAlchemy research
- [x] DB-R1-04 Alembic research
- [x] DB-R1-05 Airflow migration study
- [x] DB-R1-06 Privacy research
- [x] DB-R1-07 Security research
- [x] DB-R1-08 Technical Decision
- [x] DB-R1-09 Privacy Model
- [x] DB-R1-10 Runtime
- [x] DB-R1-11 MySQL 8.4 instance — isolated MySQL 8.4.8 authenticated evidence captured
- [x] DB-R1-12 ORM base
- [x] DB-R1-13 Naming convention
- [x] DB-R1-14 Identity schema
- [x] DB-R1-15 Subject/access schema
- [x] DB-R1-16 Consent schema
- [x] DB-R1-17 Auth session schema
- [x] DB-R1-18 Assessment schema
- [x] DB-R1-19 Support schema
- [x] DB-R1-20 Safety/review schema
- [x] DB-R1-21 Idempotency
- [x] DB-R1-22 Audit
- [x] DB-R1-23 Encryption provider
- [x] DB-R1-24 Key provider
- [x] DB-R1-25 Key rotation
- [x] DB-R1-26 Retention/purge
- [x] DB-R1-27 Alembic setup
- [x] DB-R1-28 Initial migration
- [x] DB-R1-29 Migration tests — real upgrade/check/downgrade/re-upgrade/check passed
- [x] DB-R1-30 Repositories
- [x] DB-R1-31 UnitOfWork
- [x] DB-R1-32 Concurrency tests — real MySQL idempotency race passed
- [x] DB-R1-33 Indexes/EXPLAIN — real EXPLAIN evidence captured
- [x] DB-R1-34 Least privilege — runtime DDL, GRANT, and FILE operations denied
- [x] DB-R1-35 Backup — synthetic logical dump completed
- [x] DB-R1-36 Restore — fresh database restore and complete structural, relational, and cryptographic verification passed
- [x] DB-R1-37 Privacy matrix
- [x] DB-R1-38 Schema docs
- [x] DB-R1-39 ERD
- [x] DB-R1-40 Unit tests
- [x] DB-R1-41 Real MySQL integration — 6 passed against MySQL 8.4.8
- [x] DB-R1-42 Ruff/Pyright — module checks pass
- [x] DB-R1-43 Root Contract — official suite 13 passed, 0 failed
- [x] DB-R1-44 Acceptance closure — PASS for the Round 1 module boundary; production secret/TLS/KMS wiring remains deferred

### Round 1 evidence snapshot

- MySQL 8.4.8 Community, InnoDB, `utf8mb4` / `utf8mb4_0900_ai_ci`, strict SQL mode.
- 19 domain tables plus the Alembic version table; 99 information-schema constraints and 114 indexes.
- `database_round1_evaluation.json` records 16 total tests passed, including 6 real MySQL integration tests, encryption round-trip/wrong-key/rotation checks, migration round-trip, least-privilege denial, logical backup, fresh restore, and root Contract 13/13.
- The run used synthetic data only. Backend cross-module wiring, production KMS/secret-manager integration, TLS deployment, and formal legal/ethics approval are outside this module's Round 1 completion gate.

## Module boundary reminder

`09_backend` has no persistence Protocols or implementations yet. Structural
mapping and an integration request are recorded under `reports/`; this module
does not modify Backend, Safety, or the frozen root contracts.
