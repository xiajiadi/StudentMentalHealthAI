"""Initialize one empty school and one administrator in an owned workspace."""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
from pathlib import Path

from private_settings import read_private, write_private
from school_backend import load_runtime

REPO = Path(__file__).resolve().parents[1]
OWNER_FILE = "local-school-owner.private.dpapi"


def owner_settings(workspace: Path, *, create: bool = False) -> dict[str, str]:
    marker = json.loads((workspace / "workspace.json").read_text(encoding="utf-8"))
    identity = marker["workspace_id"]
    expected = {
        "schema": "psynova.school-empty-owner.v1",
        "workspace_id": identity,
        "school_ref": "SCHOOL_LOCAL_" + identity.upper(),
        "username": "school.admin",
    }
    path = workspace / OWNER_FILE
    if create and not path.exists():
        try:
            write_private(path, {**expected, "password": secrets.token_urlsafe(32)}, exclusive=True)
        except FileExistsError:
            pass
    settings = read_private(path)
    if (
        set(settings) != {*expected, "password"}
        or any(settings[key] != value for key, value in expected.items())
        or type(settings["password"]) is not str
        or len(settings["password"]) < 32
    ):
        raise ValueError("Local administrator settings do not match this workspace")
    return settings


async def initialize(workspace: Path) -> str:
    load_runtime(workspace, REPO)
    from database_layer import create_engine, create_session_factory, models as m
    from database_layer.provenance import SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF
    from database_layer.seed import seed_reference_roles
    from pwdlib import PasswordHash
    from sqlalchemy import func, select

    engine = create_engine()
    try:
        async with create_session_factory(engine)() as session, session.begin():
            if (workspace / OWNER_FILE).exists():
                settings = owner_settings(workspace)
                existing = await session.scalar(
                    select(m.School.id).where(m.School.school_ref == settings["school_ref"])
                )
                if existing is not None:
                    return "ALREADY_INITIALIZED"
            for table in (m.School, m.Account, m.SchoolClass, m.Subject, m.MeasurementTask):
                if await session.scalar(select(func.count()).select_from(table)):
                    raise ValueError("Only an untouched workspace can be initialized")
            await seed_reference_roles(session)
            settings = owner_settings(workspace, create=True)
            school = m.School(
                school_ref=settings["school_ref"], display_name="本地学校",
                data_origin="SYNTHETIC", provenance_ref=SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF,
            )
            account = m.Account(
                login_name=settings["username"],
                password_hash=PasswordHash.recommended().hash(settings["password"]),
            )
            session.add_all((school, account))
            await session.flush()
            membership = m.AccountSchoolMembership(
                account_id=account.id, school_id=school.id, display_name="学校管理员",
            )
            session.add(membership)
            await session.flush()
            session.add(m.MembershipRole(
                membership_id=membership.id, school_id=school.id, role_code="admin",
            ))
            return "INITIALIZED"
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--show-initial-admin", action="store_true")
    args = parser.parse_args()
    for path in (REPO / "11_database" / ".venv" / "Lib" / "site-packages", REPO / "11_database"):
        sys.path.insert(0, str(path))
    try:
        if args.show_initial_admin:
            settings = owner_settings(args.workspace)
            print(f"{settings['username']}\n{settings['password']}")
        else:
            print(json.dumps({"status": asyncio.run(initialize(args.workspace))}))
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error_type": type(exc).__name__}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
