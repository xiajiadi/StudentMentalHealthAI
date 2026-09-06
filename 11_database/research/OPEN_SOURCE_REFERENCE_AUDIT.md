# Open-Source Reference Audit

Research date: 2026-09-05. Stars are the GitHub page value observed during
the audit when exposed; they are not an adoption or quality claim. No source
code was copied into this module. The implementation uses public interfaces
and engineering patterns with local code written for this project.

| Source | URL | Version/revision | Stars if available | License | Files/docs inspected | Adopted pattern | Rejected pattern | Code copied? | Attribution needed? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MySQL Community Server | [MySQL 8.4 manual](https://dev.mysql.com/doc/refman/8.4/en/) | 8.4 reference manual; local client/server evidence targets 8.4.8 | N/A | GPLv2 for Community Server | Release model, charset, FK, JSON, InnoDB encryption, backup/recovery chapters | LTS track, InnoDB, utf8mb4, explicit collation, logical backup baseline | Innovation track as Round 1 default; claiming TDE/legal compliance | No | Documentation link retained |
| SQLAlchemy | [sqlalchemy/sqlalchemy](https://github.com/sqlalchemy/sqlalchemy) and [2.0 docs](https://docs.sqlalchemy.org/en/20/) | 2.0.52 current documentation release; GitHub main inspected | 12.1k observed | MIT | README, asyncio extension, MySQL dialect | `DeclarativeBase`, `Mapped[]`, `mapped_column()`, `AsyncEngine`, `AsyncSession`, `async_sessionmaker`, bound expressions | Legacy Query style, global AsyncSession, implicit async lazy I/O | No | Documentation link retained |
| Alembic | [sqlalchemy/alembic](https://github.com/sqlalchemy/alembic) and [docs](https://alembic.sqlalchemy.org/en/latest/) | 1.19.2 documentation/current baseline | GitHub page value not relied on | MIT | README, migration docs, cookbook/autogenerate guidance | Explicit revision, async env, reviewed autogenerate, upgrade/downgrade stairway, `alembic check` | Importing live ORM models from migration scripts; auto-running migrations at app import | No | Documentation link retained |
| Apache Airflow | [apache/airflow](https://github.com/apache/airflow), [metadata update guide](https://github.com/apache/airflow/blob/main/contributing-docs/14_metadata_database_updates.rst), [database setup](https://airflow.apache.org/docs/apache-airflow/stable/howto/set-up-database.html) | main guide inspected; stable docs 3.3.1 observed | GitHub value not used | Apache-2.0 | Metadata database update guide and setup guidance | Migration review discipline, isolated version table, MySQL encoding/strict-mode awareness | Airflow schema, DAG/application semantics, zero-date workaround, or migration code | No | Reference credited in this audit |
| pyca/cryptography | [pyca/cryptography](https://github.com/pyca/cryptography), [Fernet docs](https://cryptography.io/en/latest/fernet/) | Local dependency 46.0.7; docs page observed 51.0.0-dev1 | 4.8k observed | Apache-2.0 / BSD-3-Clause components | Fernet and MultiFernet API guidance | Fernet recipe, authenticated decrypt failure, MultiFernet-style rotation concept | Custom AES/MAC/padding/nonce/token implementation; storing keys in DB | No | Documentation link retained |
| OWASP Cheat Sheet Series | [Database Security](https://cheatsheetseries.owasp.org/cheatsheets/Database_Security_Cheat_Sheet.html), [Cryptographic Storage](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html), [Key Management](https://cheatsheetseries.owasp.org/cheatsheets/Key_Management_Cheat_Sheet.html) | Pages accessed 2026-09-05 | N/A | CC BY-SA 4.0 | Least privilege, sensitive storage, key lifecycle, logging, backup guidance | Control mapping, least privilege, key separation, no sensitive logs | Treating a cheat sheet as product certification or legal approval | No | URLs retained |
| CAC / PIPL text | [Official CAC publication](https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm) | Law text published 2021-08-20 | N/A | Official government publication | Articles 6, 19, 28, 29, 31, 47, 51, 55-56 | Engineering mapping to minimization, retention, sensitive data, deletion, PIPIA gate | Legal interpretation, final retention duration, or compliance claim by the database agent | No | Official source link retained |

## Review conclusion

The adopted patterns are deliberately narrow: mature library primitives,
explicit migrations, field-level privacy controls, and least-privilege
evidence. The module does not copy schemas, silently import third-party code,
or convert references into legal/clinical claims.
