"""Purpose-separated research authentication keys from a retained key provider.

HKDF usage follows pyca's key-derivation-functions documentation. No key is
generated, persisted, logged, or rotated here. The caller chooses a stable
school scope and explicit retained versions. Restoring the provider and scope
restores verification; deleting old versions deliberately prevents it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .crypto import KeyProvider

_VERSION = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_SCOPE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_:-]{0,127}\Z")
_SIGNATURE = re.compile(r"rk1\.([A-Za-z0-9_-]{1,64})\.([0-9a-f]{64})\Z")
_SALT = b"PsyNova research authentication HKDF-SHA256 v1"


class ResearchKeyError(ValueError):
    """Stable error that never exposes underlying provider/key values."""


def _derive(provider: KeyProvider, version: str, scope: str, purpose: str) -> bytes:
    if type(version) is not str or not _VERSION.fullmatch(version):
        raise ResearchKeyError("research_key_version_invalid")
    if type(scope) is not str or not _SCOPE.fullmatch(scope):
        raise ResearchKeyError("research_key_scope_invalid")
    try:
        encoded = provider.get_key(version)
        if type(encoded) is not bytes:
            raise ValueError
        source = base64.b64decode(encoded, altchars=b"-_", validate=True)
        if len(source) != 32:
            raise ValueError
        # Context is unambiguous: neither version nor scope may contain NUL.
        info = b"\0".join(part.encode("ascii") for part in (purpose, version, scope))
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=_SALT, info=info).derive(source)
    except Exception:
        raise ResearchKeyError("research_key_unavailable") from None


def derive_research_service_bearer(
    provider: KeyProvider, *, key_version: str, school_scope: str
) -> bytes:
    """Return ASCII bearer material only to trusted service launch/client wiring."""
    key = _derive(provider, key_version, school_scope, "research-service-bearer")
    return base64.urlsafe_b64encode(key).rstrip(b"=")


def derive_research_snapshot_mac_key(
    provider: KeyProvider, *, key_version: str, school_scope: str
) -> bytes:
    """Derive MAC material for a trusted child handoff, never the master key.

    Callers must keep these bytes in memory and send them only over the owned
    private process pipe. This API is not a credential or HTTP projection.
    """
    return _derive(provider, key_version, school_scope, "research-snapshot-mac")


@dataclass(frozen=True, slots=True, init=False)
class ResearchSnapshotKeyring:
    """Versioned signer compatible with the CAT SnapshotAuthenticator protocol.

    This is a keyring primitive, not a deployed rotation/recovery workflow.
    All accepted key versions are explicitly selected by the caller; an input
    signature cannot cause arbitrary provider lookups.
    """

    signing_version: str
    school_scope: str
    _keys: Mapping[str, bytes] = field(repr=False, compare=False)

    def __init__(
        self, provider: KeyProvider, *, school_scope: str,
        signing_version: str, accepted_versions: tuple[str, ...],
    ) -> None:
        if (
            type(accepted_versions) is not tuple or not accepted_versions
            or any(type(version) is not str for version in accepted_versions)
            or len(set(accepted_versions)) != len(accepted_versions)
            or signing_version not in accepted_versions
        ):
            raise ResearchKeyError("research_key_versions_invalid")
        keys = {
            version: derive_research_snapshot_mac_key(
                provider, key_version=version, school_scope=school_scope
            )
            for version in accepted_versions
        }
        object.__setattr__(self, "signing_version", signing_version)
        object.__setattr__(self, "school_scope", school_scope)
        object.__setattr__(self, "_keys", MappingProxyType(keys))

    def sign(self, payload: bytes) -> str:
        if type(payload) is not bytes:
            raise ResearchKeyError("research_signature_payload_invalid")
        digest = hmac.new(self._keys[self.signing_version], payload, hashlib.sha256).hexdigest()
        return f"rk1.{self.signing_version}.{digest}"

    def verify(self, payload: bytes, signature: str) -> bool:
        if type(payload) is not bytes or type(signature) is not str:
            return False
        match = _SIGNATURE.fullmatch(signature)
        if match is None:
            return False
        version, supplied = match.groups()
        key = self._keys.get(version)
        if key is None:
            return False
        expected = hmac.new(key, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, supplied)
