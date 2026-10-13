import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from smhai_backend.core.config import BackendSettings
from smhai_backend.domains.school_research import bootstrap
from smhai_backend.domains.school_research.runtime import ResearchCATRuntimeError

ROOT = Path(r"D:\Dev\datasets\psynova-public-research")
PROFILE = ROOT / "research-profiles/promis-pediatric-anxiety-8-item-subset-20261014-r1"
PROFILE_SHA = "a2720adf10496f495efe21262de0e1890650847a84aff770aa025e9da825acf3"
MANIFEST_SHA = "984d395c29c26c1ce728d97790abf99d583ef47518ee6e058e067c8e8c15f524"


def document():
    return {
        "schema": "psynova.school-research-runtime.v1", "school_id": 1,
        "resource_root": str(ROOT), "signing_version": "v1", "accepted_key_versions": ["v1"],
        "profiles": [{
            "profile_ref": "promis-pediatric-anxiety-8-item-subset-20261014-r1",
            "profile_schema": "psynova.research-profile.v3",
            "expected_profile_sha256": PROFILE_SHA, "expected_manifest_sha256": MANIFEST_SHA,
            "source_family": "PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
            "parameter_origin": "PUBLISHED_ROUNDED_REFERENCE",
            "profile_path": str(PROFILE / "profile.json"),
            "manifest_path": str(PROFILE / "manifest.json"),
            "expected_fit_sha256": None, "expected_calibration_sha256": None,
        }],
        "bindings": [{"binding_ref": "r_promis8", "profile_ref":
                      "promis-pediatric-anxiety-8-item-subset-20261014-r1",
                      "config_version": "research-test-8", "config_sha256": "a" * 64}],
    }


def load(tmp_path, value, *, expected=None):
    path = tmp_path / "server-registry.json"
    raw = value if type(value) is bytes else json.dumps(value).encode()
    path.write_bytes(raw)
    return bootstrap.load_research_runtime(
        configuration_file=path, expected_sha256=expected or hashlib.sha256(raw).hexdigest(),
        loopback_base_url="http://127.0.0.1:8182",
        retained_key_provider=SimpleNamespace(get_key=lambda _: None, versions=lambda: ("v1",)),
    )


def test_actual_public_source_configuration_loads_without_enabling_or_reading_keys(tmp_path):
    if not (PROFILE / "profile.json").is_file():
        pytest.skip("pinned research source is not mounted")
    value = document()
    runtime = load(tmp_path, value)
    assert callable(runtime.client_for_binding)
    source = json.loads((PROFILE / "profile.json").read_bytes())
    assert source["publication_status"] == "not_approved"


@pytest.mark.parametrize("mutation", [
    lambda x: x.update(secret="private-secret"),
    lambda x: x.update(schema="unknown"),
    lambda x: x.update(profiles=[]),
    lambda x: x.update(bindings=[]),
    lambda x: x["bindings"][0].update(profile_ref="unregistered"),
    lambda x: x["profiles"][0].update(profile_path="relative/profile.json"),
    lambda x: x["profiles"][0].update(parameter_origin="private-secret"),
])
def test_invalid_configuration_is_stable_and_redacted(tmp_path, mutation):
    value = document()
    mutation(value)
    with pytest.raises(ResearchCATRuntimeError) as error:
        load(tmp_path, value)
    assert str(error.value) == "runtime_configuration_invalid"
    assert error.value.__suppress_context__


@pytest.mark.parametrize("raw", [b'{"schema":1,"schema":2}', b'{"value":NaN}', b'[]', b'\xff'])
def test_duplicate_nonfinite_and_invalid_json_rejected(tmp_path, raw):
    with pytest.raises(ResearchCATRuntimeError, match="runtime_configuration_invalid"):
        load(tmp_path, raw)


def test_wrong_server_pin_rejected_before_registry_load(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("registry must not load after a wrong configuration pin")
    monkeypatch.setattr(bootstrap, "ResearchProfileRegistry", unexpected)
    with pytest.raises(ResearchCATRuntimeError):
        load(tmp_path, document(), expected="0" * 64)


def test_disabled_configuration_does_not_touch_files_or_provider(monkeypatch):
    def unexpected(**kwargs):
        raise AssertionError("disabled service must be inert")
    monkeypatch.setattr(bootstrap, "load_research_runtime", unexpected)
    assert bootstrap.build_school_research_service(
        SimpleNamespace(school_research_enabled=False), None
    ) is None
    assert BackendSettings(_env_file=None).school_research_enabled is False


@pytest.mark.parametrize("values", [
    {}, {"identity_profile": "school_tenant", "school_csrf_secret": "a" * 64},
    {"environment": "production", "identity_profile": "school_tenant",
     "school_csrf_secret": "a" * 64, "persistence_mode": "mysql"},
])
def test_partial_or_production_configuration_is_rejected(values):
    with pytest.raises(ValueError, match="research CAT requires explicit nonproduction"):
        BackendSettings(_env_file=None, school_research_enabled=True, **values)
