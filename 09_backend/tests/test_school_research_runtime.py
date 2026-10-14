from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
for _candidate in (
    REPO / "11_database",
    REPO / "11_database" / ".venv" / "Lib" / "site-packages",
):
    if _candidate.is_dir() and str(_candidate.resolve()) not in sys.path:
        sys.path.insert(0, str(_candidate.resolve()))

from cryptography.fernet import Fernet  # noqa: E402
from database_layer.crypto import MappingKeyProvider  # noqa: E402
from database_layer.research_keys import derive_research_service_bearer  # noqa: E402

from smhai_backend.domains.school_research.client import ResearchCATHttpClient  # noqa: E402
from smhai_backend.domains.school_research.runtime import (  # noqa: E402
    ResearchCATBindingPin,
    ResearchCATRuntime,
    ResearchCATRuntimeError,
)  # noqa: E402
from smhai_backend.domains.school_research.trust import (  # noqa: E402
    ParameterOrigin,
    PublicationStatusProjection,
    ResearchProfileRegistry,
    ResearchProfileRegistryEntry,
)  # noqa: E402

PROFILE_DIR = Path(
    r"D:\Dev\datasets\psynova-public-research\research-profiles\promis-pediatric-anxiety-8-item-subset-20261014-r1"
)
PROFILE_PATH = PROFILE_DIR / "profile.json"
MANIFEST_PATH = PROFILE_DIR / "manifest.json"
EXPECTED_PROFILE_SHA256 = "a2720adf10496f495efe21262de0e1890650847a84aff770aa025e9da825acf3"
EXPECTED_MANIFEST_SHA256 = "984d395c29c26c1ce728d97790abf99d583ef47518ee6e058e067c8e8c15f524"
PROFILE_REF = "promis-pediatric-anxiety-8-item-subset-20261014-r1"
CONFIG_VERSION = "runtime-test-config-v1"
CONFIG_SHA256 = "b" * 64
SCHOOL_ID = 71
BINDING_REF = "promis-pediatric-binding-01"


def _public_registry() -> ResearchProfileRegistry:
    if not PROFILE_PATH.is_file() or not MANIFEST_PATH.is_file():
        pytest.skip("pinned external PROMIS research profile is not staged on this host")
    profile_doc = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    profile_sha = hashlib.sha256(PROFILE_PATH.read_bytes()).hexdigest()
    manifest_sha = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
    assert profile_sha == EXPECTED_PROFILE_SHA256
    assert manifest_sha == EXPECTED_MANIFEST_SHA256
    entry = ResearchProfileRegistryEntry(
        profile_ref=PROFILE_REF,
        profile_schema="psynova.research-profile.v3",
        expected_profile_sha256=profile_sha,
        expected_manifest_sha256=manifest_sha,
        source_family=profile_doc["instrument_family"],
        parameter_origin=ParameterOrigin.PUBLISHED_ROUNDED_REFERENCE,
        profile_path=PROFILE_PATH,
        manifest_path=MANIFEST_PATH,
    )
    return ResearchProfileRegistry(allowed_root=PROFILE_DIR, entries=(entry,))


def _provider() -> MappingKeyProvider:
    return MappingKeyProvider({"v1": Fernet.generate_key()}, active_version="v1")


def _runtime(
    *,
    provider: Any | None = None,
    pins: tuple[ResearchCATBindingPin, ...] | None = None,
    registry: Any | None = None,
    school_id: int = SCHOOL_ID,
    base_url: str = "http://127.0.0.1:8182",
    versions: tuple[str, ...] = ("v1",),
    signing_version: str = "v1",
) -> ResearchCATRuntime:
    return ResearchCATRuntime(
        profile_registry=registry or _public_registry(),
        binding_pins=pins
        or (
            ResearchCATBindingPin(
                binding_ref=BINDING_REF,
                profile_ref=PROFILE_REF,
                config_version=CONFIG_VERSION,
                config_sha256=CONFIG_SHA256,
            ),
        ),
        loopback_base_url=base_url,
        school_id=school_id,
        retained_key_provider=provider or _provider(),
        signing_version=signing_version,
        accepted_key_versions=versions,
    )


def _metadata(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "binding_ref": BINDING_REF,
        "school_id": SCHOOL_ID,
        "profile_ref": PROFILE_REF,
        "profile_sha256": EXPECTED_PROFILE_SHA256,
        "config_version": CONFIG_VERSION,
        "config_sha256": CONFIG_SHA256,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_runtime_constructs_private_client_from_pinned_unapproved_profile() -> None:
    provider = _provider()
    registry = _public_registry()
    projection = registry.load(PROFILE_REF)
    assert projection.publication_status_projection is PublicationStatusProjection.NOT_APPROVED

    runtime = _runtime(provider=provider, registry=registry)
    client = runtime.client_for_binding(_metadata())

    assert isinstance(client, ResearchCATHttpClient)
    assert client._binding_ref == BINDING_REF
    assert client._profile_sha256 == EXPECTED_PROFILE_SHA256
    assert client._config_sha256 == CONFIG_SHA256
    assert client._snapshot_verifier.school_scope == f"school:{SCHOOL_ID}"
    assert client._token == derive_research_service_bearer(
        provider, key_version="v1", school_scope=f"school:{SCHOOL_ID}"
    )
    assert "token" not in repr(runtime).casefold()
    assert "key" not in repr(runtime).casefold()


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("school_id", SCHOOL_ID + 1, "binding_school_mismatch"),
        ("profile_ref", "other-profile", "binding_pin_mismatch"),
        ("profile_sha256", "c" * 64, "profile_pin_mismatch"),
        ("config_version", "other-config", "binding_pin_mismatch"),
        ("config_sha256", "d" * 64, "binding_pin_mismatch"),
    ],
)
def test_runtime_fails_closed_when_db_metadata_differs_from_server_pin(
    field: str, value: object, expected_code: str
) -> None:
    runtime = _runtime()
    with pytest.raises(ResearchCATRuntimeError) as exc_info:
        runtime.client_for_binding(_metadata(**{field: value}))
    assert exc_info.value.code == expected_code
    assert str(exc_info.value) == expected_code


def test_binding_ref_must_be_pinned_and_ambiguous_implicit_match_fails() -> None:
    runtime = _runtime()
    with pytest.raises(ResearchCATRuntimeError, match="binding_not_pinned"):
        runtime.client_for_binding(_metadata(binding_ref="not-configured"))
    with pytest.raises(ResearchCATRuntimeError, match="binding_metadata_invalid"):
        runtime.client_for_binding(_metadata(binding_ref=None))

    duplicate_match = ResearchCATBindingPin(
        binding_ref="promis-pediatric-binding-02",
        profile_ref=PROFILE_REF,
        config_version=CONFIG_VERSION,
        config_sha256=CONFIG_SHA256,
    )
    runtime = _runtime(
        pins=(
            ResearchCATBindingPin(BINDING_REF, PROFILE_REF, CONFIG_VERSION, CONFIG_SHA256),
            duplicate_match,
        )
    )
    implicit = _metadata()
    delattr(implicit, "binding_ref")
    with pytest.raises(ResearchCATRuntimeError, match="binding_pin_ambiguous_or_missing"):
        runtime.client_for_binding(implicit)
    explicit = runtime.client_for_binding(_metadata(binding_ref=duplicate_match.binding_ref))
    assert explicit._binding_ref == duplicate_match.binding_ref


def test_duplicate_binding_pin_rejected_at_configuration() -> None:
    pin = ResearchCATBindingPin(BINDING_REF, PROFILE_REF, CONFIG_VERSION, CONFIG_SHA256)
    with pytest.raises(ResearchCATRuntimeError, match="binding_pin_duplicate"):
        _runtime(pins=(pin, pin))


def test_runtime_configuration_cannot_be_mutated_after_construction() -> None:
    runtime = _runtime()
    with pytest.raises(AttributeError, match="configuration is immutable"):
        runtime._school_id = SCHOOL_ID + 1


def test_unknown_retained_key_version_fails_without_exposing_provider_detail() -> None:
    runtime = _runtime(provider=_provider(), versions=("v1", "retired-v0"))
    with pytest.raises(ResearchCATRuntimeError) as exc_info:
        runtime.client_for_binding(_metadata())
    assert exc_info.value.code == "research_client_construction_failed"
    assert "retired-v0" not in str(exc_info.value)
    assert "key" not in repr(runtime).casefold()


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8182",
        "http://localhost:8182",
        "http://192.0.2.4:8182",
        "http://user:password@127.0.0.1:8182",
        "http://127.0.0.1:8182/path",
        "http://127.0.0.1:8182/?x=1",
    ],
)
def test_runtime_rejects_noncanonical_or_nonloopback_url(url: str) -> None:
    with pytest.raises(ResearchCATRuntimeError):
        _runtime(base_url=url)


def test_runtime_rejects_wrong_school_and_untrusted_profile_projection() -> None:
    with pytest.raises(ResearchCATRuntimeError, match="school_id_invalid"):
        _runtime(school_id=True)  # type: ignore[arg-type]

    class IncompatibleRegistry:
        def load(self, _profile_ref: str) -> object:
            return SimpleNamespace(
                profile_ref=PROFILE_REF,
                profile_sha256=EXPECTED_PROFILE_SHA256,
                repository_schema_compatible=False,
            )

    runtime = _runtime(registry=IncompatibleRegistry())
    with pytest.raises(ResearchCATRuntimeError, match="profile_pin_mismatch"):
        runtime.client_for_binding(_metadata())


def test_binding_pin_schema_and_key_version_inputs_are_strict() -> None:
    with pytest.raises(ResearchCATRuntimeError, match="binding_pin_invalid"):
        ResearchCATBindingPin(BINDING_REF, PROFILE_REF, CONFIG_VERSION, "not-a-hash")
    with pytest.raises(ResearchCATRuntimeError, match="key_versions_invalid"):
        _runtime(versions=("v1", "v1"))
    with pytest.raises(ResearchCATRuntimeError, match="key_versions_invalid"):
        _runtime(signing_version="v2", versions=("v1",))


def test_observed_corpus_pin_resolution_uses_no_snapshot_key_material():
    class NoKeyReads:
        def get_key(self, *_args):
            pytest.fail("observed source resolution must not read keys")

        def versions(self):
            pytest.fail("observed source resolution must not read key versions")

    runtime = _runtime(provider=NoKeyReads())
    metadata = _metadata(
        corpus_sha256="7c723fbdb2590a24cc3fa33adb70c8affb323e3688ce3f0477620bd6507d7f32",
        case_count=800,
    )
    corpus = runtime.observed_corpus_for_binding(metadata)
    assert corpus.row_count == 800
    assert runtime.observed_corpus_for_binding(metadata) is corpus
    assert "_rows" not in repr(corpus)
    with pytest.raises(ResearchCATRuntimeError) as failure:
        runtime.observed_corpus_for_binding(_metadata(corpus_sha256="a" * 64, case_count=800))
    assert failure.value.code == "observed_corpus_pin_mismatch"
    with pytest.raises(ResearchCATRuntimeError):
        runtime.observed_corpus_for_binding(_metadata(corpus_sha256=None, case_count=None))


def test_observed_corpus_binding_rejects_bool_school_identity():
    runtime = _runtime(school_id=1)
    with pytest.raises(ResearchCATRuntimeError) as failure:
        runtime.observed_corpus_for_binding(_metadata(school_id=True))
    assert failure.value.code == "binding_school_mismatch"
