"""Seed reference roles and one synthetic linked case into a test database."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database_layer.config import DatabaseSettings, create_engine, create_session_factory
from database_layer.crypto import DevLocalKeyProvider, FernetDataProtectionProvider
from database_layer.seed import seed_reference_roles, seed_synthetic_case


async def main() -> None:
    module_root = Path(__file__).resolve().parents[1]
    settings = DatabaseSettings.from_env()
    engine = create_engine(settings)
    protection = FernetDataProtectionProvider(DevLocalKeyProvider.from_env(module_root.parent))
    session_factory = create_session_factory(engine)
    async with session_factory.begin() as session:
        inserted = await seed_reference_roles(session)
        fixture = await seed_synthetic_case(session, protection=protection)
    await engine.dispose()
    print({"reference_roles_inserted": inserted, "synthetic_fixture": fixture})


if __name__ == "__main__":
    asyncio.run(main())
