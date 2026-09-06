"""Collect machine-readable, non-secret Round 1 evidence."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.fernet import Fernet
from database_layer import models  # noqa: F401 - registers all mapped tables
from database_layer.base import Base
from database_layer.config import DatabaseSettings, create_engine
from database_layer.crypto import FernetDataProtectionProvider, MappingKeyProvider

MODULE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = MODULE_ROOT.parent
FROZEN_HASHES = {
    "CONTRACTS.md": "2AE5320C5B12EFE57DD90D7352AE192D1BEE8387B595E36DDD3919B90C486CBB",
    "00_architecture/openapi.v1.json": (
        "235C8FDB0B35F2DE870127A18D4CD8C72A1C7795AF02656B2A6C7274AB071897"
    ),
}


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "NOT_INSTALLED"


def contract_status() -> dict[str, Any]:
    results: dict[str, bool] = {}
    for relative, expected in FROZEN_HASHES.items():
        path = PROJECT_ROOT / relative
        digest = (
            hashlib.sha256(path.read_bytes()).hexdigest().upper() if path.exists() else "MISSING"
        )
        results[relative] = digest == expected
    return {"files_unchanged": results, "all_unchanged": all(results.values())}


def restore_closure_evidence() -> dict[str, Any]:
    """Load the real restore-verifier output without manufacturing PASS values."""

    path = MODULE_ROOT / "reports" / "database_round1_restore_verification.json"
    if not path.exists():
        return {"status": "NOT_RUN", "artifact": str(path)}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "UNREADABLE", "artifact": str(path), "error_type": type(exc).__name__}
    if not isinstance(loaded, dict):
        return {"status": "INVALID", "artifact": str(path)}
    return loaded


def run_unit_tests() -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=MODULE_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = f"{completed.stdout}\n{completed.stderr}"

    def count(label: str) -> int:
        found = re.search(rf"(\d+) {label}", output)
        return int(found.group(1)) if found else 0

    parsed = {
        "passed": count("passed"),
        "failed": count("failed"),
        "skipped": count("skipped"),
        "exit_code": completed.returncode,
    }
    return parsed


def crypto_evidence() -> dict[str, bool]:
    key_v1 = Fernet.generate_key()
    key_v2 = Fernet.generate_key()
    old = FernetDataProtectionProvider(MappingKeyProvider({"v1": key_v1}, active_version="v1"))
    rotating = FernetDataProtectionProvider(
        MappingKeyProvider({"v1": key_v1, "v2": key_v2}, active_version="v2")
    )
    encrypted = old.encrypt_json({"text": "synthetic-evidence"}, payload_schema_version="test.v1")
    rotated = rotating.rotate(encrypted)
    wrong = FernetDataProtectionProvider(
        MappingKeyProvider({"wrong": Fernet.generate_key()}, active_version="wrong")
    )
    try:
        wrong.decrypt_json(encrypted)
    except Exception:
        wrong_key_failure = True
    else:
        wrong_key_failure = False
    return {
        "encryption_roundtrip": old.decrypt_json(encrypted)["text"] == "synthetic-evidence",
        "wrong_key_failure": wrong_key_failure,
        "key_rotation": rotated.key_version == "v2"
        and rotating.decrypt_json(rotated)["text"] == "synthetic-evidence",
    }


def run_root_contract() -> dict[str, Any]:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        return {"status": "NOT_RUN_NO_POWERSHELL"}
    contract_script = PROJECT_ROOT / "00_architecture" / "tests" / "run_contract_checks.ps1"
    env = os.environ.copy()
    global_python = Path(r"C:\Python314")
    env["PATH"] = f"{global_python};{env.get('PATH', '')}"
    completed = subprocess.run(
        [
            shell,
            "-NoProfile",
            "-File",
            str(contract_script),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    match = re.search(r"Ran (\d+) tests", output)
    return {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "passed": int(match.group(1)) if match and completed.returncode == 0 else 0,
        "failed": 0 if completed.returncode == 0 else 1,
        "exit_code": completed.returncode,
    }


async def mysql_evidence() -> dict[str, Any]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return {
            "connected": False,
            "status": "BLOCKED_NO_DATABASE_URL",
            "sanitized_url": None,
        }
    try:
        settings = DatabaseSettings(url=url)
        engine = create_engine(settings)
        async with engine.connect() as connection:
            runtime = (
                (
                    await connection.execute(
                        text(
                            "SELECT VERSION() AS version, @@version_comment AS edition, "
                            "@@character_set_database AS charset_name, "
                            "@@collation_database AS collation_name, "
                            "@@default_storage_engine AS default_engine, "
                            "@@time_zone AS time_zone, @@sql_mode AS sql_mode"
                        )
                    )
                )
                .mappings()
                .one()
            )
            table_count = await connection.scalar(
                text(
                    "SELECT COUNT(*) FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'"
                )
            )
            constraint_count = await connection.scalar(
                text(
                    "SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS "
                    "WHERE CONSTRAINT_SCHEMA = DATABASE()"
                )
            )
            index_count = await connection.scalar(
                text(
                    "SELECT COUNT(*) FROM information_schema.STATISTICS "
                    "WHERE TABLE_SCHEMA = DATABASE()"
                )
            )
            migration_head = await connection.scalar(
                text("SELECT version_num FROM database_alembic_version LIMIT 1")
            )
            grants = [row[0] for row in (await connection.execute(text("SHOW GRANTS"))).all()]
        await engine.dispose()
        return {
            "connected": True,
            "status": "CONNECTED",
            "sanitized_url": settings.sanitized_url,
            "version": runtime["version"],
            "edition": runtime["edition"],
            "charset": runtime["charset_name"],
            "collation": runtime["collation_name"],
            "default_engine": runtime["default_engine"],
            "time_zone": runtime["time_zone"],
            "sql_mode": runtime["sql_mode"],
            "table_count": table_count,
            "constraint_count": constraint_count,
            "index_count": index_count,
            "migration_head": migration_head,
            "show_grants": grants,
            "least_privilege": os.environ.get("ROUND1_LEAST_PRIVILEGE", "REVIEW_REQUIRED"),
            "backup": os.environ.get("ROUND1_BACKUP_STATUS", "NOT_RUN"),
            "restore": os.environ.get("ROUND1_RESTORE_STATUS", "NOT_RUN"),
        }
    except Exception as exc:
        return {
            "connected": False,
            "status": f"BLOCKED_{type(exc).__name__}",
            "sanitized_url": "configured-but-hidden",
        }


def main() -> None:
    database_evidence = asyncio.run(mysql_evidence())
    restore_evidence = restore_closure_evidence()
    if database_evidence.get("connected"):
        mysql_version = database_evidence.get("version", "NOT_VERIFIED")
        table_count = database_evidence.get("table_count", len(Base.metadata.tables))
        constraint_count = database_evidence.get("constraint_count", 0)
        index_count = database_evidence.get("index_count", 0)
        migration_head = database_evidence.get("migration_head", "NOT_VERIFIED")
    else:
        mysql_version = "NOT_VERIFIED"
        table_count = len(Base.metadata.tables)
        constraint_count = sum(len(table.constraints) for table in Base.metadata.tables.values())
        index_count = sum(len(table.indexes) for table in Base.metadata.tables.values())
        migration_head = "20260905_0001"
    evidence: dict[str, Any] = {
        "generated_at": "2026-09-05",
        "mysql_version": mysql_version,
        "sqlalchemy_version": package_version("SQLAlchemy"),
        "alembic_version": package_version("alembic"),
        "aiomysql_version": package_version("aiomysql"),
        "cryptography_version": package_version("cryptography"),
        "migration_head": migration_head,
        "migration_test": os.environ.get("ROUND1_MIGRATION_STATUS", "NOT_RUN_NO_REAL_DATABASE"),
        "table_count": table_count,
        "constraint_count": constraint_count,
        "index_count": index_count,
        **crypto_evidence(),
        "least_privilege": os.environ.get("ROUND1_LEAST_PRIVILEGE", "NOT_RUN_NO_REAL_DATABASE"),
        "backup": os.environ.get("ROUND1_BACKUP_STATUS", "NOT_RUN_NO_REAL_DATABASE"),
        "restore": os.environ.get("ROUND1_RESTORE_STATUS", "NOT_RUN_NO_REAL_DATABASE"),
        "restore_verification": restore_evidence.get("overall", restore_evidence.get("status")),
        "restore_migration_match": restore_evidence.get("migration", {}).get("match", False),
        "restore_table_count_match": restore_evidence.get("tables", {}).get("match", False),
        "restore_row_counts_match": restore_evidence.get("summary", {}).get(
            "row_counts_match", False
        ),
        "restore_content_hash_match": restore_evidence.get("summary", {}).get(
            "safe_content_hashes_match", False
        ),
        "restore_ciphertext_hash_match": restore_evidence.get("summary", {}).get(
            "ciphertext_hashes_match", False
        ),
        "restore_fk_integrity": restore_evidence.get("summary", {}).get(
            "foreign_key_integrity", False
        ),
        "restore_schema_sanity": restore_evidence.get("summary", {}).get("schema_sanity", False),
        "overall_restore_verification": restore_evidence.get(
            "overall", restore_evidence.get("status", "NOT_RUN")
        ),
        "restore_verification_artifact": str(
            MODULE_ROOT / "reports" / "database_round1_restore_verification.json"
        ),
        "tests": {
            "unit": run_unit_tests(),
            "real_mysql_integration": os.environ.get(
                "ROUND1_MYSQL_TEST_STATUS", "NOT_RUN_NO_REAL_DATABASE"
            ),
        },
        "root_contract": run_root_contract(),
        "real_student_data": False,
        "frozen_contract_modified": not contract_status()["all_unchanged"],
        "frozen_contract_hashes": contract_status(),
        "real_mysql": database_evidence,
    }
    output = MODULE_ROOT / "reports" / "database_round1_evaluation.json"
    output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
