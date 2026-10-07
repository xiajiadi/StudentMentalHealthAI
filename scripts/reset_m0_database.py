"""Drop and recreate only the explicitly named loopback M0 demo schema."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "11_database"))
from database_layer.config import DatabaseSettings


async def main() -> None:
    settings = DatabaseSettings.from_env()
    url = make_url(settings.url)
    if url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Reset requires a loopback MySQL host.")
    if url.database != "smhai_m0_demo":
        raise SystemExit("Reset requires the schema name `smhai_m0_demo` exactly.")
    admin_url = url.set(database=None)
    engine = create_async_engine(admin_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.exec_driver_sql("DROP DATABASE IF EXISTS `smhai_m0_demo`")
            await connection.exec_driver_sql(
                "CREATE DATABASE `smhai_m0_demo` CHARACTER SET utf8mb4 "
                "COLLATE utf8mb4_0900_ai_ci"
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
