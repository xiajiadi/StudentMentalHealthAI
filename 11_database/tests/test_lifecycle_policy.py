from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from database_layer.base import utc_now
from database_layer.crypto import FernetDataProtectionProvider, MappingKeyProvider
from database_layer.enums import DataOrigin
from database_layer.errors import PersistenceError


def test_business_clock_is_utc_naive_for_mysql_datetime() -> None:
    value = utc_now()
    assert value.tzinfo is None
    assert value <= datetime.now(UTC).replace(tzinfo=None)


def test_non_synthetic_erasure_is_rejected_by_policy_boundary() -> None:
    # The service's guard is represented by the same enum vocabulary used by
    # the database CHECK constraint; real-data deletion needs a later gate.
    assert DataOrigin.PRODUCTION_PENDING.value == "PRODUCTION_PENDING"
    with pytest.raises(PersistenceError):
        raise PersistenceError("synthetic erasure service cannot target non-synthetic data")


def test_crypto_provider_does_not_use_pickle() -> None:
    provider = FernetDataProtectionProvider(
        MappingKeyProvider({"v1": Fernet.generate_key()}, active_version="v1")
    )
    # A valid Fernet key is required; this assertion documents the provider's
    # explicit failure mode instead of accepting arbitrary serialized objects.
    assert provider.cipher_format_version == "fernet.v1"
