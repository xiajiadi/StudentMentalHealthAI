"""Create only the explicitly named loopback M0 database when absent."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "11_database"))
from database_layer.config import DatabaseSettings


async def main() -> None:
    settings = DatabaseSettings.from_env()
    url = make_url(settings.url)
    if url.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Database bootstrap requires a loopback MySQL host.")
    if url.database != "smhai_m0_demo":
        raise SystemExit("Database bootstrap requires the schema name `smhai_m0_demo` exactly.")
    engine = create_async_engine(url.set(database=None), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.exec_driver_sql(
                "CREATE DATABASE IF NOT EXISTS `smhai_m0_demo` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
