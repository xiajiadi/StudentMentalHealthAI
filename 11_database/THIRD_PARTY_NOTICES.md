# Third-Party Notices

The following projects are dependencies or engineering references for Database
Round 1. No third-party source files were copied into the module.

| Component | Version/baseline | License | Role | Source | Copied vs reference |
| --- | --- | --- | --- | --- | --- |
| MySQL Community Server | Local target 8.4.8; target track 8.4 LTS | GPLv2 | Relational database server and logical backup tools | [MySQL](https://www.mysql.com/) | Runtime dependency |
| SQLAlchemy | 2.0.52 | MIT | Async ORM/Core, engine, sessions, bound SQL | [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) | Runtime dependency |
| Alembic | 1.19.2 | MIT | Explicit schema migrations and drift check | [Alembic](https://github.com/sqlalchemy/alembic) | Runtime/dev dependency |
| aiomysql | 0.3.2 | MIT | Async MySQL DBAPI driver | [aiomysql](https://github.com/aio-libs/aiomysql) | Runtime dependency |
| pyca/cryptography | 46.0.7 | Apache-2.0 / BSD-3-Clause components | Fernet field encryption and key rotation primitives | [cryptography](https://github.com/pyca/cryptography) | Runtime dependency |
| pytest / pytest-asyncio | 9.1.1 / 1.4.0 | MIT / Apache-2.0 | Unit and async integration test harness | [pytest](https://github.com/pytest-dev/pytest) | Dev dependency |
| Ruff | 0.16.6 | MIT | Formatting and static lint | [Ruff](https://github.com/astral-sh/ruff) | Dev dependency |
| Pyright | 1.1.411 | MIT | Static type checking | [Pyright](https://github.com/microsoft/pyright) | Dev dependency |

Airflow, OWASP, and CAC/PIPL are engineering/legal references, not runtime
dependencies. Their URLs and adopted/rejected patterns are recorded in
`research/OPEN_SOURCE_REFERENCE_AUDIT.md`.
