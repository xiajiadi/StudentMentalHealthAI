from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from database_layer.crypto import (
    DevLocalKeyProvider,
    FernetDataProtectionProvider,
    MappingKeyProvider,
)
from database_layer.errors import EncryptionFailure, EncryptionKeyUnavailable


def make_provider() -> FernetDataProtectionProvider:
    return FernetDataProtectionProvider(
        MappingKeyProvider(
            {"v1": Fernet.generate_key(), "v2": Fernet.generate_key()},
            active_version="v1",
        )
    )


def test_ciphertext_round_trip_and_plaintext_absence() -> None:
    provider = make_provider()
    phrase = "synthetic-private-assessment-answer"
    encrypted = provider.encrypt_json(
        {"payload_schema_version": "assessment-response.v1", "text": phrase},
        payload_schema_version="assessment-response.v1",
    )

    assert phrase.encode("utf-8") not in encrypted.ciphertext
    assert provider.decrypt_json(encrypted)["text"] == phrase
    assert encrypted.cipher_format_version == "fernet.v1"
    assert encrypted.key_version == "v1"


def test_wrong_key_fails_explicitly() -> None:
    original = make_provider()
    encrypted = original.encrypt_json({"text": "synthetic"}, payload_schema_version="test.v1")
    wrong = FernetDataProtectionProvider(
        MappingKeyProvider({"v1": Fernet.generate_key()}, active_version="v1")
    )

    with pytest.raises(EncryptionFailure):
        wrong.decrypt_json(encrypted)


def test_key_rotation_preserves_plaintext_and_changes_version() -> None:
    key_v1 = Fernet.generate_key()
    key_v2 = Fernet.generate_key()
    old = FernetDataProtectionProvider(MappingKeyProvider({"v1": key_v1}, active_version="v1"))
    rotating = FernetDataProtectionProvider(
        MappingKeyProvider({"v1": key_v1, "v2": key_v2}, active_version="v2")
    )
    encrypted = old.encrypt_json({"answer": 3}, payload_schema_version="assessment-response.v1")
    rotated = rotating.rotate(encrypted)

    assert rotated.key_version == "v2"
    assert rotating.decrypt_json(rotated) == {"answer": 3}
    with pytest.raises(EncryptionFailure):
        old.decrypt_json(rotated)


def test_dev_key_provider_rejects_repository_path(tmp_path: Path) -> None:
    key_file = tmp_path / "database-keys.json"
    key_file.write_text('{"active_version":"v1","keys":{"v1":"invalid"}}', encoding="utf-8")
    with pytest.raises(EncryptionKeyUnavailable):
        DevLocalKeyProvider(key_file, repository_root=tmp_path)
