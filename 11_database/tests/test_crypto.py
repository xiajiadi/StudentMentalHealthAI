import json
import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from database_layer import crypto
from database_layer.crypto import (
    DevLocalKeyProvider,
    FernetDataProtectionProvider,
    MappingKeyProvider,
    WindowsDpapiKeyProvider,
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


def test_dpapi_provider_rejects_missing_and_malformed_files_without_path_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing_path = tmp_path / "SYNTHETIC_MISSING_KEYFILE_SENTINEL"
    with pytest.raises(EncryptionKeyUnavailable) as missing:
        WindowsDpapiKeyProvider(missing_path)
    assert str(missing_path) not in str(missing.value)

    malformed_path = tmp_path / "SYNTHETIC_MALFORMED_KEYFILE_SENTINEL"
    malformed_path.write_bytes(b"not-a-dpapi-container")
    with pytest.raises(EncryptionKeyUnavailable) as malformed:
        WindowsDpapiKeyProvider(malformed_path)
    assert str(malformed_path) not in str(malformed.value)

    valid_magic_path = tmp_path / "SYNTHETIC_NONWINDOWS_KEYFILE_SENTINEL"
    valid_magic_path.write_bytes(crypto._DPAPI_FILE_MAGIC + b"synthetic-protected-blob")
    monkeypatch.setattr(crypto, "_is_windows", lambda: False)
    with pytest.raises(EncryptionKeyUnavailable) as non_windows:
        WindowsDpapiKeyProvider(valid_magic_path)
    assert "Windows current-user DPAPI is required" == str(non_windows.value)
    assert str(valid_magic_path) not in str(non_windows.value)


def test_dpapi_provider_rejects_invalid_payload_without_value_leak() -> None:
    sentinel = "SYNTHETIC_INVALID_PAYLOAD_SENTINEL"
    with pytest.raises(EncryptionKeyUnavailable) as caught:
        crypto._parse_dpapi_key_payload(
            json.dumps({"active_version": sentinel, "keys": {}}).encode("utf-8")
        )
    assert sentinel not in str(caught.value)


def test_dpapi_provider_sanitizes_protection_and_payload_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "synthetic-protected-file.bin"
    path.write_bytes(crypto._DPAPI_FILE_MAGIC + b"synthetic-blob")
    monkeypatch.setattr(crypto, "_is_windows", lambda: True)

    def raise_synthetic_error(_data: bytes, *, decrypt: bool) -> bytes:
        raise RuntimeError("SYNTHETIC_DPAPI_ERROR_SENTINEL")

    monkeypatch.setattr(
        crypto,
        "_dpapi_transform_current_user",
        raise_synthetic_error,
    )
    with pytest.raises(EncryptionKeyUnavailable) as caught:
        WindowsDpapiKeyProvider(path)
    assert "SYNTHETIC_DPAPI_ERROR_SENTINEL" not in str(caught.value)


def test_dpapi_provider_requires_explicit_external_key_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(crypto.os, "environ", {})
    with pytest.raises(EncryptionKeyUnavailable, match="explicit DATABASE_KEY_FILE"):
        WindowsDpapiKeyProvider.from_env(repository_root=tmp_path)

    inside_repository = tmp_path / "synthetic-repository"
    inside_repository.mkdir()
    with pytest.raises(EncryptionKeyUnavailable, match="outside the repository"):
        WindowsDpapiKeyProvider(
            inside_repository / "synthetic-dpapi-key.bin",
            repository_root=inside_repository,
        )


@pytest.mark.skipif(os.name != "nt", reason="requires Windows current-user DPAPI")
def test_dpapi_provider_reads_synthetic_current_user_protected_file(tmp_path: Path) -> None:
    key = Fernet.generate_key()
    plaintext = json.dumps(
        {"active_version": "synthetic-v1", "keys": {"synthetic-v1": key.decode("ascii")}},
        separators=(",", ":"),
    ).encode("utf-8")
    protected = crypto._dpapi_transform_current_user(plaintext, decrypt=False)
    key_file = tmp_path / "synthetic-dpapi-keys.bin"
    key_file.write_bytes(crypto._DPAPI_FILE_MAGIC + protected)

    provider = WindowsDpapiKeyProvider(key_file)

    assert provider.active_version == "synthetic-v1"
    assert provider.versions() == ("synthetic-v1",)
    assert provider.get_key("synthetic-v1") == key
    assert key not in key_file.read_bytes()
