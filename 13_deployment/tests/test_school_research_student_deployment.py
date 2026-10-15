from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_backend as backend
import school_research_student_config as student_config
from school_research_student_config import (
    MANIFEST_SHA256,
    R3_MANIFEST_SHA256,
    SAFETY_BASE_URL,
    STUDY_REF,
    SUPPORTED_MANIFEST_SHA256S,
    StudentResearchConfigError,
    load_student_research_config,
    restore_student_research_config,
)


def _document(
    manifest_file: Path,
    *,
    manifest_sha256: str = MANIFEST_SHA256,
    **overrides: object,
) -> dict[str, object]:
    return {
        "enabled": True,
        "school_id": 41,
        "purpose": "RESEARCH_SIMULATION",
        "study_ref": STUDY_REF,
        "manifest_file": str(manifest_file),
        "manifest_sha256": manifest_sha256,
        "safety_base_url": SAFETY_BASE_URL,
        "consumer_age_min": 14,
        "consumer_age_max": 17,
        **overrides,
    }


def _write_config(path: Path, payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def test_student_lane_is_explicitly_off_and_environment_cannot_enable_it(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "SMHAI_SCHOOL_RESEARCH_STUDENT_CONVERSATION__ENABLED", "true"
    )
    args = backend.build_parser().parse_args(["--workspace", str(tmp_path)])
    settings, research = backend.build_cli_settings_kwargs(args)
    assert research == {}
    assert settings["school_research_student_conversation"] == {"enabled": False}
    from smhai_backend.core.config import BackendSettings

    parsed = BackendSettings(
        _env_file=None, school_csrf_secret="a" * 64, **settings
    )
    assert parsed.school_research_student_conversation.enabled is False


def test_student_config_requires_the_explicit_file_hash_pair(tmp_path):
    args = backend.build_parser().parse_args(
        ["--workspace", str(tmp_path), "--research-student-config-file", str(tmp_path / "x.json")]
    )
    with pytest.raises(backend.ResearchCLIConfigError) as exc:
        backend.build_cli_settings_kwargs(args)
    assert exc.value.code == "student_research_config_incomplete"


def test_student_config_reads_exact_core_fields_and_pinned_manifest(tmp_path, monkeypatch):
    assert MANIFEST_SHA256 == (
        "70637b39cb11a34de91599a1a32e9e1a6edff6a76b19cc1b11895ee7170e9974"
    )
    assert SUPPORTED_MANIFEST_SHA256S == frozenset(
        {
            MANIFEST_SHA256,
            R3_MANIFEST_SHA256,
        }
    )
    source_manifest = tmp_path / "pinned-source-manifest.json"
    source_manifest.write_text('{"test_fixture":"source contents are not output"}', encoding="utf-8")
    source_sha = hashlib.sha256(source_manifest.read_bytes()).hexdigest()
    # This stubs only the external-byte fixture for parser plumbing; a separate
    # assertion above keeps the production allowlist fixed to the two reviewed pins.
    monkeypatch.setattr(
        student_config, "SUPPORTED_MANIFEST_SHA256S", frozenset({source_sha})
    )
    config_file = tmp_path / "student-config.json"
    config_sha = _write_config(
        config_file,
        _document(source_manifest, manifest_sha256=source_sha),
    )
    args = backend.build_parser().parse_args(
        [
            "--workspace", str(tmp_path),
            "--research-student-config-file", str(config_file),
            "--research-student-config-sha256", config_sha,
        ]
    )
    settings, research = backend.build_cli_settings_kwargs(args)
    assert research == {}
    lane = settings["school_research_student_conversation"]
    assert lane == _document(source_manifest, manifest_sha256=source_sha)
    assert "school_research_enabled" not in settings

    with pytest.raises(StudentResearchConfigError):
        load_student_research_config(config_file, "0" * 64)

    wrong_source = tmp_path / "wrong-source.json"
    wrong_sha = _write_config(
        wrong_source, _document(source_manifest, manifest_sha256="0" * 64)
    )
    with pytest.raises(StudentResearchConfigError):
        load_student_research_config(wrong_source, wrong_sha)


def test_closed_manifest_pins_agree_across_runtime_layers():
    backend_source = Path(__file__).resolve().parents[2] / "09_backend" / "src"
    sys.path.insert(0, str(backend_source))
    from safety_engine.retrieval.research_student import (
        SUPPORTED_MANIFEST_SHA256S as safety_pins,
    )
    from smhai_backend.core.config import (
        SUPPORTED_MANIFEST_SHA256S as backend_pins,
    )

    assert SUPPORTED_MANIFEST_SHA256S == safety_pins == backend_pins
    assert SUPPORTED_MANIFEST_SHA256S == frozenset(
        {
            MANIFEST_SHA256,
            R3_MANIFEST_SHA256,
        }
    )


def test_r3_external_config_loads_only_when_its_exact_manifest_is_selected(tmp_path):
    manifest_value = os.environ.get("PSYNOVA_STUDENT_RESEARCH_MANIFEST_R3")
    if not manifest_value:
        pytest.skip(
            "Set PSYNOVA_STUDENT_RESEARCH_MANIFEST_R3 for the external R3 load probe"
        )
    manifest_path = Path(manifest_value)
    config_file = tmp_path / "student-config-r3.json"
    config_sha = _write_config(
        config_file,
        _document(manifest_path, manifest_sha256=R3_MANIFEST_SHA256),
    )

    loaded = load_student_research_config(config_file, config_sha)
    restored = restore_student_research_config(loaded.manifest_value())

    assert loaded.manifest_sha256 == R3_MANIFEST_SHA256
    assert loaded.core_settings()["manifest_sha256"] == R3_MANIFEST_SHA256
    assert restored is not None
    assert restored.manifest_sha256 == R3_MANIFEST_SHA256


def test_student_config_rejects_duplicate_keys_and_nonfinite_json(tmp_path):
    duplicate = tmp_path / "duplicate.json"
    raw = (
        b'{"enabled":true,"enabled":true,"school_id":41,'
        b'"purpose":"RESEARCH_SIMULATION"}'
    )
    duplicate.write_bytes(raw)
    with pytest.raises(StudentResearchConfigError):
        load_student_research_config(duplicate, hashlib.sha256(raw).hexdigest())

    nonfinite = tmp_path / "nonfinite.json"
    raw = b'{"enabled":NaN}'
    nonfinite.write_bytes(raw)
    with pytest.raises(StudentResearchConfigError):
        load_student_research_config(nonfinite, hashlib.sha256(raw).hexdigest())
