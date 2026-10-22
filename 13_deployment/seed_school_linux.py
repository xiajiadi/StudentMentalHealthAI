"""Idempotently seed the registered synthetic school contexts on Linux."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

SEED_CREDENTIAL_NAME = "school-seed-accounts.json"
SEED_CREDENTIAL_SCHEMA = "psynova.school-seed-accounts.v1"


class _PasswordHasherAdapter:
    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate

    def hash(self, password: str) -> str:
        return self.delegate.hash(password)

    def verify(self, password: str, encoded_hash: str) -> bool:
        return self.delegate.verify(password, encoded_hash)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _seed_credentials() -> dict[str, tuple[str, str]]:
    from database_layer import SCHOOL_SEED_SLOTS
    from database_layer.crypto import read_linux_systemd_credential

    payload = json.loads(
        read_linux_systemd_credential(SEED_CREDENTIAL_NAME).decode("utf-8"),
        object_pairs_hook=_unique_object,
    )
    if (
        type(payload) is not dict
        or set(payload) != {"schema", "credentials"}
        or payload.get("schema") != SEED_CREDENTIAL_SCHEMA
        or type(payload.get("credentials")) is not dict
        or set(payload["credentials"]) != set(SCHOOL_SEED_SLOTS)
    ):
        raise ValueError("synthetic seed credential is invalid")
    credentials: dict[str, tuple[str, str]] = {}
    for slot in SCHOOL_SEED_SLOTS:
        entry = payload["credentials"][slot]
        if (
            type(entry) is not list
            or len(entry) != 2
            or not all(isinstance(item, str) for item in entry)
        ):
            raise ValueError("synthetic seed credential is invalid")
        credentials[slot] = (entry[0], entry[1])
    from database_layer.school_seed import _validated_credentials

    return _validated_credentials(credentials)


async def seed(repository_root: Path) -> dict[str, object]:
    repo = repository_root.resolve(strict=True)
    for path in (
        repo / "11_database",
        repo / "09_backend" / "src",
        repo / "13_deployment",
    ):
        sys.path.insert(0, str(path))
    from linux_school_runtime import (
        configure_import_paths,
        load_school_runtime_credentials,
        validate_key_credential,
        verify_mysql_school_schema,
    )

    configure_import_paths(repo)
    credential = load_school_runtime_credentials()
    validate_key_credential()
    database = verify_mysql_school_schema(credential)
    credentials = _seed_credentials()

    from database_layer import create_engine, create_session_factory
    from database_layer.school_seed import seed_synthetic_school_contexts
    from pwdlib import PasswordHash

    engine = create_engine()
    factory = create_session_factory(engine)
    password_hasher = _PasswordHasherAdapter(PasswordHash.recommended())
    try:
        result = None
        for _ in range(2):
            async with factory() as session, session.begin():
                result = await seed_synthetic_school_contexts(
                    session=session,
                    credentials=credentials,
                    password_hasher=password_hasher,
                )
        assert result is not None
        return {
            "seed": "VERIFIED",
            "idempotent_second_pass": True,
            "database": database["database"],
            "schools": len(result.school_refs),
            "subjects": len(result.subject_refs),
            "role_accounts": len(result.account_public_ids),
            "source": "registered_synthetic_recipe",
        }
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    try:
        print(json.dumps(asyncio.run(seed(args.repo_root)), sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001 - suppress database and credential details.
        print(
            json.dumps(
                {"seed": "BLOCKED", "error_type": type(exc).__name__}, sort_keys=True
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
