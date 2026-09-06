# Database Round 1

This module provides the versioned relational persistence foundation for
StudentMentalHealthAI. It owns MySQL/SQLAlchemy/Alembic models, constraints,
field encryption persistence, domain repositories, transaction boundaries,
privacy/lifecycle controls, and backup/restore procedures. It does not own HTTP
routes, authorization policy, CAT/RAG/LLM behavior, or Safety interpretation.

## Local setup

Use the module's Python 3.12 environment and configure an async MySQL URL
without committing it:

```powershell
uv sync --dev
$env:DATABASE_URL = 'mysql+aiomysql://<user>:<password>@127.0.0.1:3306/<round1_test_db>?charset=utf8mb4'
$env:DB_NAME = '<round1_test_db>'
```

Create a development key outside the repository when needed:

```powershell
uv run python scripts/init_dev_key.py
$env:DATABASE_KEY_FILE = 'D:\Dev\secrets\studentmentalhealthai\database-keys.json'
```

The key file is never part of a migration or database row. Tests generate
dedicated in-process keys instead.

## Migrations

Migrations are explicit. The application does not run them during import or
startup:

```powershell
.\scripts\run_migrations.ps1 -Action upgrade
.\scripts\run_migrations.ps1 -Action check
```

The initial revision is a reviewed static migration and does not import live
ORM models. `downgrade` is guarded to database names that explicitly identify a
test/round1/synthetic/restore database.

## Verification

Pure tests do not use SQLite as an acceptance database:

```powershell
uv run pytest -q
uv run ruff format --check database_layer migrations scripts tests
uv run ruff check database_layer migrations scripts tests
uv run pyright database_layer migrations scripts tests
uv run python -m compileall -q database_layer migrations scripts tests
```

Real MySQL integration and operational backup/restore checks require a
dedicated test database and credentials supplied through the environment. The
scripts refuse broad or ambiguous destructive targets and never contain a DB
password. For a fully isolated local rehearsal, the module also provides
`scripts/run_local_mysql_round1.ps1`; it creates a fresh MySQL 8.4 data
directory under `D:\Dev\studentmentalhealthai`, uses a temporary loopback
port, and stops the instance after producing the machine-readable evidence
report.

## Privacy boundary

Assessment answers/results, support messages, safety details, and review notes
are encrypted JSON bytes. Raw session tokens, CSRF tokens, passwords,
encryption keys, internal prompts, chain-of-thought, unsafe rejected
candidates, and raw RAG chunks are not persisted. Round 1 fixtures are
synthetic only. See `DATA_PRIVACY_MODEL_V1.md` and the reports directory for
the evidence and known limitations.
