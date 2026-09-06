"""Verify a restored synthetic database without printing decrypted content."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database_layer.config import DatabaseSettings, create_engine, create_session_factory
from database_layer.crypto import (
    DevLocalKeyProvider,
    EncryptedPayload,
    FernetDataProtectionProvider,
)
from database_layer.models import AssessmentResponse
from sqlalchemy import select


async def main() -> None:
    module_root = Path(__file__).resolve().parents[1]
    engine = create_engine(DatabaseSettings.from_env())
    protection = FernetDataProtectionProvider(DevLocalKeyProvider.from_env(module_root.parent))
    async with create_session_factory(engine)() as session:
        response = (
            await session.execute(
                select(AssessmentResponse).order_by(AssessmentResponse.id).limit(1)
            )
        ).scalar_one_or_none()
        if response is None or response.response_ciphertext is None:
            raise SystemExit("restored synthetic encrypted response is missing")
        payload = protection.decrypt_json(
            EncryptedPayload(
                ciphertext=response.response_ciphertext,
                key_version=response.key_version or "",
                cipher_format_version=response.cipher_format_version or "",
                payload_schema_version=response.payload_schema_version or "",
            )
        )
    await engine.dispose()
    print(
        json.dumps(
            {"decryptable": isinstance(payload, dict), "payload_keys": sorted(payload)}, indent=2
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
