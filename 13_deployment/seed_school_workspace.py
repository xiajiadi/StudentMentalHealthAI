"""Explicitly provision the registered synthetic school recipe in an owned schema.

Generated credentials are current-user DPAPI sealed before the atomic database
transaction. Existing credentials/state are verified, never reset or overwritten.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
from pathlib import Path

from private_settings import read_private, write_private
from school_backend import load_runtime


def credentials_for(workspace: Path, slots: tuple[str, ...]) -> dict:
    path = workspace / "school-accounts.private.dpapi"
    if not path.exists():
        nonce = secrets.token_hex(8)
        credentials = {
            slot: ["SYNTHETIC_" + slot.replace(".", "_") + "_" + nonce, secrets.token_urlsafe(32)]
            for slot in slots
        }
        try:
            write_private(path, {"recipe_version": "school-contexts-v1", "credentials": credentials}, exclusive=True)
        except FileExistsError:
            # Another creator won: consume its sealed credentials, never overwrite.
            pass
    private = read_private(path)
    if private.get("recipe_version") != "school-contexts-v1" or not isinstance(private.get("credentials"), dict):
        raise ValueError("Registered sealed school credentials required")
    return private["credentials"]


async def seed(workspace: Path, repo: Path) -> dict:
    load_runtime(workspace, repo)
    from pwdlib import PasswordHash
    from database_layer import create_engine, create_session_factory
    from database_layer.school_seed import SCHOOL_SEED_SLOTS, seed_synthetic_school_contexts
    credentials = credentials_for(workspace, SCHOOL_SEED_SLOTS)
    engine = create_engine()
    try:
        async with create_session_factory(engine)() as session:
            async with session.begin():
                result = await seed_synthetic_school_contexts(session=session, credentials=credentials, password_hasher=PasswordHash.recommended())
        return {"recipe": "school-contexts-v1", "schools": len(result.school_refs), "subjects": len(result.subject_refs), "role_accounts": len(result.account_public_ids), "credentials": "current-user DPAPI", "specialist_subject_grants": 0, "admin_subject_grants": 0}
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    for path in (repo / "11_database" / ".venv" / "Lib" / "site-packages", repo / "11_database", repo / "09_backend" / "src"):
        sys.path.insert(0, str(path))
    try:
        print(json.dumps(asyncio.run(seed(args.workspace, repo))))
        return 0
    except Exception as exc:
        print(json.dumps({"school_seed": "BLOCKED", "error_type": type(exc).__name__, "recovery": "Preserve sealed credentials and existing data for inspection."}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
