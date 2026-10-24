"""Restore a CurrentUser synthetic backup into a NEW isolated MySQL workspace.

Never reuses a target or modifies the source. Failed targets are retained for
inspection. Native success proves data/key restoration, not browser acceptance.
Run with the existing 11_database environment on Windows.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from create_school_workspace import create, validate_target
from private_settings import read_private
from school_restore_import import import_snapshot
from school_restore_plan import plan_restore, trusted_manifest
from school_schema import CURRENT_SCHOOL_REVISION, SCHOOL_REVISION_CHAIN

CIPHERTEXT_METADATA_COLUMNS = {
    (
        "school_independent_education_reviews",
        "candidate_payload_ciphertext",
    ): (
        "candidate_key_version",
        "candidate_cipher_format_version",
        "candidate_payload_schema_version",
    ),
    (
        "school_independent_education_reviews",
        "reviewed_payload_ciphertext",
    ): (
        "reviewed_key_version",
        "reviewed_cipher_format_version",
        "reviewed_payload_schema_version",
    ),
    (
        "school_staff_invitations",
        "work_contact_ciphertext",
    ): (
        "work_contact_key_version",
        "work_contact_cipher_format_version",
        "work_contact_payload_schema_version",
    ),
}
CIPHERTEXT_PAYLOAD_CONTRACTS = {
    ("school_staff_invitations", "work_contact_ciphertext"): {
        "payload_schema_version": "school-staff-contact.v1",
        "exact_fields": frozenset({"contact"}),
        "string_fields": frozenset({"contact"}),
    },
}


def _record(target: Path, state: dict) -> None:
    path = target / "restore-state.json"
    temporary = target / ".restore-state.tmp"
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(state, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _migrate(target: Path, repository: Path, marker: dict, revision: str) -> None:
    """Use trusted pinned migration code; no credential-bearing child argv."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import URL

    settings = read_private(target / "database.private.dpapi")
    if (
        settings.get("DB_HOST") != "127.0.0.1"
        or settings.get("DB_NAME") != marker["database"]
        or int(settings.get("DB_PORT", 0)) != marker["port"]
    ):
        raise ValueError("Sealed restore target identity does not match")
    url = URL.create("mysql+aiomysql", username=settings["DB_USER"],
                     password=settings["DB_PASSWORD"], host="127.0.0.1",
                     port=marker["port"], database=marker["database"])
    config = Config(str(repository / "11_database" / "alembic.ini"))
    config.set_main_option("script_location", str(repository / "11_database" / "migrations"))
    config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%"))
    previous = os.environ.pop("DATABASE_URL", None)
    try:
        command.upgrade(config, revision)
    finally:
        if previous is not None:
            os.environ["DATABASE_URL"] = previous


def _verify_ciphertexts(
    connection, target: Path, repository: Path, snapshot_revision: str
) -> int:
    """Decrypt synthetic fields in memory only, returning an aggregate count."""
    # Use the exact trusted schema projection for the imported snapshot. Current
    # ORM metadata may contain tables that did not exist in an older restore.
    manifest = trusted_manifest(snapshot_revision)

    from database_layer.crypto import (
        EncryptedPayload,
        FernetDataProtectionProvider,
        WindowsDpapiKeyProvider,
    )

    protection = FernetDataProtectionProvider(
        WindowsDpapiKeyProvider(target / "database-keys.private.dpapi", repository)
    )
    checked = 0
    with connection.cursor() as cursor:
        for table_name, columns in manifest.items():
            encrypted = [column for column in columns if column.endswith("_ciphertext")]
            for column in encrypted:
                mapped_metadata = CIPHERTEXT_METADATA_COLUMNS.get((table_name, column))
                if mapped_metadata is not None:
                    if not all(name in columns for name in mapped_metadata):
                        raise RuntimeError("Trusted encrypted payload metadata is incomplete")
                    key_version_column, cipher_format_column, schema_column = mapped_metadata
                else:
                    prefix = column.removesuffix("_ciphertext") + "_"
                    prefixed_metadata = (
                        f"{prefix}key_version",
                        f"{prefix}cipher_format_version",
                        f"{prefix}payload_schema_version",
                    )
                    plain_metadata = (
                        "key_version",
                        "cipher_format_version",
                        "payload_schema_version",
                    )
                    if all(name in columns for name in prefixed_metadata):
                        key_version_column, cipher_format_column, schema_column = prefixed_metadata
                    elif all(name in columns for name in plain_metadata):
                        key_version_column, cipher_format_column, schema_column = plain_metadata
                    else:
                        raise RuntimeError("Trusted encrypted payload metadata is incomplete")
                cursor.execute(
                    f"SELECT `{column}`,`{key_version_column}`,`{cipher_format_column}`,"
                    f"`{schema_column}` "
                    f"FROM `{table_name}` WHERE `{column}` IS NOT NULL"
                )
                for ciphertext, key_version, cipher_format, payload_schema in cursor.fetchall():
                    contract = CIPHERTEXT_PAYLOAD_CONTRACTS.get((table_name, column))
                    if (
                        contract is not None
                        and payload_schema != contract["payload_schema_version"]
                    ):
                        raise RuntimeError("Encrypted payload schema version is unsupported")
                    value = protection.decrypt_json(EncryptedPayload(
                        ciphertext=ciphertext, key_version=key_version,
                        cipher_format_version=cipher_format, payload_schema_version=payload_schema,
                    ))
                    if not isinstance(value, dict):
                        raise TypeError("Restored encrypted object is invalid")
                    if contract is not None and (
                        set(value) != contract["exact_fields"]
                        or any(
                            not isinstance(value[field_name], str)
                            or not value[field_name]
                            for field_name in contract["string_fields"]
                        )
                    ):
                        raise TypeError("Restored encrypted object is invalid")
                    checked += 1
                    del value
    return checked


def restore(backup_file: Path, source: Path, target: Path, mysql_bin: Path,
            repository: Path, port: int) -> dict:
    from prepare_school_runtime import prepare, verify_process
    from resume_school_workspace import _reject_reparse_path

    # Preflight precedes target creation. The original sealed artifact is read
    # only; source rows and application-key containers are never rewritten.
    _reject_reparse_path(source)
    _reject_reparse_path(backup_file)
    source = source.resolve(strict=True)
    if backup_file.resolve(strict=True).parent != source / "backups":
        raise ValueError("Owned source backup directory required")
    package = read_private(backup_file)
    _reject_reparse_path(source / "workspace.json")
    source_marker = json.loads((source / "workspace.json").read_text(encoding="utf-8"))
    if package["workspace_id"] != source_marker.get("workspace_id"):
        raise ValueError("Backup source identity does not match")
    plan_restore(package, restored_at=datetime.now(UTC))
    # A snapshot may only stay at its revision or move forward. During a
    # staged schema rollout, never create a target for a newer snapshot and
    # subsequently attempt to move it back to an older application runtime.
    if (
        package["revision"] not in SCHOOL_REVISION_CHAIN
        or CURRENT_SCHOOL_REVISION not in SCHOOL_REVISION_CHAIN
        or SCHOOL_REVISION_CHAIN.index(package["revision"])
        > SCHOOL_REVISION_CHAIN.index(CURRENT_SCHOOL_REVISION)
    ):
        raise ValueError("Snapshot is newer than the supported runtime revision")
    resolved = target.resolve(strict=False)
    if resolved == source or resolved.is_relative_to(source) or source.is_relative_to(resolved):
        raise ValueError("Restore target and source must not overlap")
    if port == package["port"]:
        raise ValueError("Restore requires a different isolated port")
    validate_target(target, repository, port)
    created = create(target, mysql_bin, repository, port)
    target = target.resolve(strict=True)
    marker = json.loads((target / "workspace.json").read_text(encoding="utf-8"))
    if marker["workspace_id"] != created["workspace_id"]:
        raise ValueError("New target identity changed")
    state = {"schema_version": "psynova.synthetic-restore-target.v1", "synthetic_only": True,
             "phase": "CREATED", "database": marker["database"], "host": "127.0.0.1",
             "port": port, "workspace_id": marker["workspace_id"],
             "source_workspace_id": package["workspace_id"], "workspace": str(target),
             "data_directory": marker["data_directory"]}
    _record(target, state)
    try:
        verify_process(marker)
        _migrate(target, repository, marker, package["revision"])
        state["phase"] = "SCHEMA_READY"
        _record(target, state)
        private = read_private(target / "database.private.dpapi")
        import pymysql

        connection = pymysql.connect(
            host="127.0.0.1", port=port, database=marker["database"],
            user=private["DB_USER"], password=private["DB_PASSWORD"],
            autocommit=False, connect_timeout=10, read_timeout=30, write_timeout=30,
        )
        try:
            imported = import_snapshot(connection, package, state, restored_at=datetime.now(UTC))
            state["phase"] = "ROWS_IMPORTED"
            _record(target, state)
            key_container = base64.b64decode(package["database_key_container_b64"], validate=True)
            original_key = target / "database-keys.private.dpapi"
            _reject_reparse_path(original_key)
            # Preserve the initializer's unused key. Both paths belong to this
            # newly created private target; no source key is replaced.
            original_key.rename(target / "generated-unused-keys.private.dpapi")
            with original_key.open("xb") as stream:
                stream.write(key_container)
                stream.flush()
                os.fsync(stream.fileno())
            ciphertext_count = _verify_ciphertexts(
                connection, target, repository, package["revision"]
            )
        finally:
            connection.close()
        if package["revision"] != CURRENT_SCHOOL_REVISION:
            state["phase"] = "ADDITIVE_RUNTIME_UPGRADE"
            _record(target, state)
            _migrate(target, repository, marker, CURRENT_SCHOOL_REVISION)
        prepare(target, repository)
        state["snapshot_revision"] = package["revision"]
        state["runtime_revision"] = CURRENT_SCHOOL_REVISION
        state["phase"] = "DATA_KEYS_RUNTIME_VERIFIED_REQUIRES_BROWSER"
        _record(target, state)
        return dict(imported, ciphertext_count=ciphertext_count,
                    status=state["phase"], target=str(target), port=port, ready=False)
    except Exception as exc:  # noqa: BLE001 - persist redacted failure and preserve the target.
        state["failed_phase"] = state["phase"]
        state["phase"] = "FAILED_PRESERVED"
        state["error_type"] = type(exc).__name__
        _record(target, state)
        raise RuntimeError(f"Restore failed ({type(exc).__name__}); preserve target") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--mysql-bin", required=True, type=Path)
    parser.add_argument("--port", type=int, default=3309)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repository / "11_database"))
    try:
        print(json.dumps(restore(args.backup, args.source, args.target, args.mysql_bin,
                                 repository, args.port)))
        return 0
    except Exception as exc:  # noqa: BLE001 - redact driver errors, credentials and synthetic content.
        print(json.dumps({"restore": "BLOCKED", "error_type": type(exc).__name__,
                          "recovery": "Preserve any created target for inspection."}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
