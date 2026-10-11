"""Application-level field encryption using pyca/cryptography Fernet."""

from __future__ import annotations

import base64
import ctypes
import json
import os
from collections.abc import Mapping
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken

from .errors import EncryptionFailure, EncryptionKeyUnavailable


class KeyProvider(Protocol):
    """Key lookup contract; key material never belongs in MySQL or source."""

    @property
    def active_version(self) -> str: ...

    def get_key(self, version: str) -> bytes: ...

    def versions(self) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class EncryptedPayload:
    """Ciphertext plus non-secret metadata required for safe decryption."""

    ciphertext: bytes
    key_version: str
    cipher_format_version: str
    payload_schema_version: str


class MappingKeyProvider:
    """Test-only/in-process provider for generated keys."""

    def __init__(self, keys: Mapping[str, bytes], active_version: str) -> None:
        self._keys = dict(keys)
        self._active_version = active_version
        if active_version not in self._keys:
            raise EncryptionKeyUnavailable("active encryption key version is missing")
        for version, key in self._keys.items():
            try:
                Fernet(key)
            except (TypeError, ValueError) as exc:
                raise EncryptionKeyUnavailable(
                    f"invalid key material for version {version}"
                ) from exc

    @property
    def active_version(self) -> str:
        return self._active_version

    def get_key(self, version: str) -> bytes:
        try:
            return self._keys[version]
        except KeyError as exc:
            raise EncryptionKeyUnavailable(
                "requested encryption key version is unavailable"
            ) from exc

    def versions(self) -> tuple[str, ...]:
        return tuple(self._keys)


class DevLocalKeyProvider:
    """Development provider backed by a JSON file outside the repository.

    Expected shape::

        {"active_version": "v1", "keys": {"v1": "<url-safe-fernet-key>"}}

    This provider intentionally does not create a key file implicitly.  A
    missing file is a startup error rather than an accidental data-loss path.
    """

    def __init__(self, key_file: Path, repository_root: Path | None = None) -> None:
        resolved = key_file.expanduser().resolve()
        if repository_root is not None:
            repo = repository_root.expanduser().resolve()
            if resolved == repo or repo in resolved.parents:
                raise EncryptionKeyUnavailable(
                    "development key file must be outside the repository"
                )
        try:
            raw = json.loads(resolved.read_text(encoding="utf-8"))
            active = raw["active_version"]
            encoded_keys = raw["keys"]
            if not isinstance(active, str) or not isinstance(encoded_keys, dict):
                raise ValueError
            keys = {
                str(version): str(value).encode("ascii") for version, value in encoded_keys.items()
            }
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise EncryptionKeyUnavailable(
                "development encryption key file is unavailable"
            ) from exc
        self._delegate = MappingKeyProvider(keys, active)
        self.path = resolved

    @classmethod
    def from_env(cls, repository_root: Path | None = None) -> DevLocalKeyProvider:
        configured = os.environ.get(
            "DATABASE_KEY_FILE", r"D:\Dev\secrets\studentmentalhealthai\database-keys.json"
        )
        return cls(Path(configured), repository_root=repository_root)

    @property
    def active_version(self) -> str:
        return self._delegate.active_version

    def get_key(self, version: str) -> bytes:
        return self._delegate.get_key(version)

    def versions(self) -> tuple[str, ...]:
        return self._delegate.versions()


_DPAPI_FILE_MAGIC = b"PSYNOVA-DPAPI-v1\x00"
_DPAPI_UI_FORBIDDEN = 0x1
_MAX_DPAPI_FILE_BYTES = 1024 * 1024


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _is_windows() -> bool:
    return os.name == "nt"


def _dpapi_transform_current_user(data: bytes, *, decrypt: bool) -> bytes:
    """Protect or unprotect bytes with current-user Windows DPAPI."""

    if not _is_windows():
        raise EncryptionKeyUnavailable("Windows current-user DPAPI is required")
    if not data or len(data) > _MAX_DPAPI_FILE_BYTES:
        raise EncryptionKeyUnavailable("DPAPI input is invalid")

    source_buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = _DataBlob(
        len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte))
    )
    target = _DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    if decrypt:
        transform = crypt32.CryptUnprotectData
        transform.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
    else:
        transform = crypt32.CryptProtectData
        transform.argtypes = [
            ctypes.POINTER(_DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
    transform.restype = wintypes.BOOL

    # UI_FORBIDDEN is the only flag. Omitting LOCAL_MACHINE keeps the blob
    # scoped to the current Windows user.
    if not transform(
        ctypes.byref(source),
        None,
        None,
        None,
        None,
        _DPAPI_UI_FORBIDDEN,
        ctypes.byref(target),
    ):
        raise EncryptionKeyUnavailable("Windows current-user DPAPI operation failed")
    if not target.pbData:
        raise EncryptionKeyUnavailable("Windows current-user DPAPI output is invalid")
    try:
        if target.cbData > _MAX_DPAPI_FILE_BYTES:
            raise EncryptionKeyUnavailable("Windows current-user DPAPI output is invalid")
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _parse_dpapi_key_payload(plaintext: bytes) -> MappingKeyProvider:
    try:
        payload = json.loads(
            plaintext.decode("utf-8"), object_pairs_hook=_unique_json_object
        )
        if not isinstance(payload, dict) or set(payload) != {"active_version", "keys"}:
            raise ValueError
        active_version = payload["active_version"]
        encoded_keys = payload["keys"]
        if (
            not isinstance(active_version, str)
            or not active_version
            or not isinstance(encoded_keys, dict)
            or not encoded_keys
        ):
            raise ValueError
        keys: dict[str, bytes] = {}
        for version, encoded_key in encoded_keys.items():
            if (
                not isinstance(version, str)
                or not version
                or not isinstance(encoded_key, str)
                or not encoded_key
            ):
                raise ValueError
            keys[version] = encoded_key.encode("ascii")
        return MappingKeyProvider(keys, active_version)
    except Exception:
        raise EncryptionKeyUnavailable("DPAPI encryption key payload is invalid") from None


class WindowsDpapiKeyProvider:
    """Key provider for the current-user ``PSYNOVA-DPAPI-v1`` file format."""

    def __init__(self, key_file: Path, repository_root: Path | None = None) -> None:
        try:
            resolved = key_file.expanduser().resolve()
            repository = repository_root.expanduser().resolve() if repository_root else None
        except Exception:
            raise EncryptionKeyUnavailable("DPAPI encryption key file is unavailable") from None
        if repository is not None and (resolved == repository or repository in resolved.parents):
            raise EncryptionKeyUnavailable(
                "DPAPI encryption key file must be outside the repository"
            )
        try:
            container = resolved.read_bytes()
        except Exception:
            raise EncryptionKeyUnavailable("DPAPI encryption key file is unavailable") from None
        if (
            len(container) <= len(_DPAPI_FILE_MAGIC)
            or len(container) > _MAX_DPAPI_FILE_BYTES
            or not container.startswith(_DPAPI_FILE_MAGIC)
        ):
            raise EncryptionKeyUnavailable("DPAPI encryption key file is invalid")
        if not _is_windows():
            raise EncryptionKeyUnavailable("Windows current-user DPAPI is required")
        try:
            plaintext = _dpapi_transform_current_user(
                container[len(_DPAPI_FILE_MAGIC) :], decrypt=True
            )
            delegate = _parse_dpapi_key_payload(plaintext)
        except Exception:
            raise EncryptionKeyUnavailable("DPAPI encryption key file is invalid") from None
        self._delegate = delegate

    @classmethod
    def from_env(cls, repository_root: Path | None = None) -> WindowsDpapiKeyProvider:
        configured = os.environ.get("DATABASE_KEY_FILE")
        if not configured or not configured.strip():
            raise EncryptionKeyUnavailable(
                "school_tenant requires an explicit DATABASE_KEY_FILE DPAPI key file"
            )
        return cls(Path(configured), repository_root=repository_root)

    @property
    def active_version(self) -> str:
        return self._delegate.active_version

    def get_key(self, version: str) -> bytes:
        return self._delegate.get_key(version)

    def versions(self) -> tuple[str, ...]:
        return self._delegate.versions()


class FernetDataProtectionProvider:
    """Versioned JSON-before-Fernet field protection provider."""

    cipher_format_version = "fernet.v1"

    def __init__(self, key_provider: KeyProvider) -> None:
        self.key_provider = key_provider

    def encrypt_json(
        self,
        payload: Mapping[str, object],
        *,
        payload_schema_version: str,
    ) -> EncryptedPayload:
        if not payload_schema_version:
            raise EncryptionFailure("payload schema version is required")
        try:
            serialized = json.dumps(
                dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            key_version = self.key_provider.active_version
            ciphertext = Fernet(self.key_provider.get_key(key_version)).encrypt(serialized)
        except (TypeError, ValueError) as exc:
            raise EncryptionFailure("payload is not JSON serializable") from exc
        return EncryptedPayload(
            ciphertext=ciphertext,
            key_version=key_version,
            cipher_format_version=self.cipher_format_version,
            payload_schema_version=payload_schema_version,
        )

    def decrypt_json(self, encrypted: EncryptedPayload) -> dict[str, object]:
        if encrypted.cipher_format_version != self.cipher_format_version:
            raise EncryptionFailure("unsupported ciphertext format")
        try:
            key = self.key_provider.get_key(encrypted.key_version)
            plaintext = Fernet(key).decrypt(encrypted.ciphertext)
            decoded = json.loads(plaintext.decode("utf-8"))
        except (
            EncryptionKeyUnavailable,
            InvalidToken,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise EncryptionFailure("ciphertext authentication or decoding failed") from exc
        if not isinstance(decoded, dict):
            raise EncryptionFailure("encrypted payload must decode to a JSON object")
        return decoded

    def rotate(self, encrypted: EncryptedPayload) -> EncryptedPayload:
        """Decrypt with the recorded old key and encrypt with the active key."""

        payload = self.decrypt_json(encrypted)
        return self.encrypt_json(payload, payload_schema_version=encrypted.payload_schema_version)


def generate_key_file(path: Path, *, active_version: str = "v1") -> None:
    """Create a development key file when explicitly invoked by a local operator."""

    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = base64.urlsafe_b64encode(os.urandom(32))
    path.write_text(
        json.dumps(
            {"active_version": active_version, "keys": {active_version: key.decode("ascii")}},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        # Windows ACLs are managed by the operator; do not make key setup fail
        # solely because chmod is not supported by the filesystem.
        pass
