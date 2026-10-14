import base64
import hashlib
import hmac

import pytest
from database_layer.crypto import MappingKeyProvider
from database_layer.research_keys import (
    ResearchKeyError,
    ResearchSnapshotKeyring,
    derive_research_service_bearer,
    derive_research_snapshot_mac_key,
)


def provider(active="v1"):
    return MappingKeyProvider(
        {"v1": base64.urlsafe_b64encode(b"a" * 32),
         "v2": base64.urlsafe_b64encode(b"b" * 32)}, active
    )


def ring(active="v1", versions=("v1",), scope="school:1"):
    return ResearchSnapshotKeyring(
        provider(active), school_scope=scope,
        signing_version=active, accepted_versions=versions,
    )


def test_restore_retained_provider_and_scope_reproduces_signature():
    signature = ring().sign(b"synthetic-state")
    assert ring().verify(b"synthetic-state", signature)
    assert signature == ring().sign(b"synthetic-state")
    assert not ring(scope="school:2").verify(b"synthetic-state", signature)
    assert not ring().verify(b"tampered", signature)


def test_rotation_primitive_retains_explicit_old_versions():
    old = ring().sign(b"state")
    rotated = ring("v2", ("v1", "v2"))
    assert rotated.verify(b"state", old)
    assert rotated.sign(b"state").startswith("rk1.v2.")
    assert not ring("v2", ("v2",)).verify(b"state", old)
    assert not ring().verify(b"state", rotated.sign(b"state"))


def test_service_and_snapshot_material_use_distinct_contexts():
    token = derive_research_service_bearer(provider(), key_version="v1", school_scope="school:1")
    assert len(token) >= 32 and token.isascii()
    assert token == derive_research_service_bearer(
        provider(), key_version="v1", school_scope="school:1"
    )
    assert token != derive_research_service_bearer(
        provider(), key_version="v1", school_scope="school:2"
    )
    forged = "rk1.v1." + hmac.new(token, b"state", hashlib.sha256).hexdigest()
    assert not ring().verify(b"state", forged)
    assert token.decode() not in repr(ring())


def test_trusted_child_mac_handoff_matches_retained_keyring_without_master_key():
    key = derive_research_snapshot_mac_key(
        provider(), key_version="v1", school_scope="school:1"
    )
    assert type(key) is bytes and len(key) == 32
    signature = "rk1.v1." + hmac.new(key, b"state", hashlib.sha256).hexdigest()
    assert ring().verify(b"state", signature)
    assert key != base64.urlsafe_b64decode(provider().get_key("v1"))
    assert key != derive_research_snapshot_mac_key(
        provider(), key_version="v1", school_scope="school:2"
    )
    assert key != derive_research_snapshot_mac_key(
        provider(), key_version="v2", school_scope="school:1"
    )


@pytest.mark.parametrize("signature", [None, True, "", "v1", "rk1.v3." + "a" * 64,
                                       "rk1.v1." + "A" * 64, "rk1.v1." + "a" * 63])
def test_bad_signatures_fail_closed(signature):
    assert not ring().verify(b"state", signature)


@pytest.mark.parametrize("versions", [(), ["v1"], ("v1", "v1"), (True,), ("v2",)])
def test_invalid_version_selection(versions):
    with pytest.raises(ResearchKeyError):
        ring(versions=versions)


@pytest.mark.parametrize("scope", ["", "school.1", "x\x00y", True])
def test_invalid_scope(scope):
    with pytest.raises(ResearchKeyError, match="research_key_scope_invalid"):
        ring(scope=scope)


def test_provider_error_does_not_echo_secret_or_source_exception():
    class Broken:
        def get_key(self, version):
            raise ValueError("private-secret-material")
    with pytest.raises(ResearchKeyError) as error:
        ResearchSnapshotKeyring(
            Broken(), school_scope="school:1", signing_version="v1", accepted_versions=("v1",)
        )
    assert str(error.value) == "research_key_unavailable"
    assert error.value.__suppress_context__ is True
