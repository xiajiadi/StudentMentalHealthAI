from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_install as installer


def _args(**overrides):
    values = {
        name: None
        for name, _sha_name, _flag, _sha_flag, _limit in installer.RESEARCH_FILE_PAIRS
    }
    for _name, sha_name, _flag, _sha_flag, _limit in installer.RESEARCH_FILE_PAIRS:
        values[sha_name] = None
    for name, _flag, _kind in installer.RESEARCH_PATH_ARGUMENTS:
        values[name] = None
    for name, _flag in installer.RESEARCH_VALUE_ARGUMENTS:
        values[name] = None
    for name, _flag in installer.RESEARCH_BOOLEAN_ARGUMENTS:
        values[name] = False
    values.update(overrides)
    return SimpleNamespace(**values)


def test_research_profile_is_default_off_and_checkpoint_digest_is_legacy_compatible(
    tmp_path,
):
    profile = installer._validate_research_profile(
        _args(), source=Path(__file__).resolve().parents[2]
    )
    assert profile["enabled"] is False
    assert profile["sha256"] == installer.RESEARCH_PROFILE_EMPTY_SHA256

    config = {
        "source_head": "a" * 40,
        "target_head": "a" * 40,
        "source": Path("D:/source"),
        "mysql_bin": Path("D:/mysql"),
        "python_specs": {
            name: Path(f"D:/python/{index}.exe")
            for index, name in enumerate(installer.PYTHON_MODULES)
        },
        "workspace": Path("D:/workspace"),
        "ports": {
            "backend": 8104,
            "frontend": 4194,
            "standard_cat": 8182,
            "database": 3330,
        },
        "frontend_mode": "preview",
        "llm_profile": "school-gpu-7b",
        "dependency_target": Path("D:/dependencies"),
    }
    old_state = installer._new_state(config)
    old_state.pop("research_profile_sha256")
    state_path = tmp_path / "old-checkpoint.json"
    state_path.write_text(json.dumps(old_state), encoding="utf-8")
    restored = installer._read_state(state_path)
    assert (
        restored["research_profile_sha256"] == installer.RESEARCH_PROFILE_EMPTY_SHA256
    )
    changed_profile_config = {
        **config,
        "research_profile": {"sha256": "f" * 64},
    }
    with pytest.raises(installer.InstallError, match="RESUME_CONFIGURATION_MISMATCH"):
        installer._match_state(restored, changed_profile_config)


@pytest.mark.parametrize(
    "overrides",
    [
        {"research_runtime_file": Path("D:/runtime.json")},
        {"research_source_rights_verified": True},
        {"enable_research_education_worker": True},
        {"enable_research_education_input_review_continuation": True},
        {"research_programme_manifest_file": Path("D:/manifest.json")},
    ],
    ids=(
        "unpaired-config",
        "rights-without-policy",
        "worker-without-study",
        "continuation-without-draft",
        "manifest-without-worker",
    ),
)
def test_research_profile_rejects_incomplete_or_unbound_opt_ins(overrides):
    with pytest.raises(installer.InstallError, match="RESEARCH_PROFILE_INCOMPLETE"):
        installer._validate_research_profile(
            _args(**overrides), source=Path(__file__).resolve().parents[2]
        )


def test_research_profile_detects_config_hash_drift(tmp_path):
    config_file = tmp_path / "student.json"
    config_file.write_text("{}", encoding="utf-8")
    wrong_hash = "0" * 64
    with pytest.raises(installer.InstallError, match="RESEARCH_PROFILE_HASH_MISMATCH"):
        installer._validate_research_profile(
            _args(
                research_student_config_file=config_file,
                research_student_config_sha256=wrong_hash,
            ),
            source=Path(__file__).resolve().parents[2],
        )


def test_research_profile_digest_binds_source_path_and_file_sha(tmp_path, monkeypatch):
    import school_research_student_config

    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    raw = b"{}"
    first.write_bytes(raw)
    second.write_bytes(raw)
    source_config = object()
    monkeypatch.setattr(
        school_research_student_config,
        "load_student_research_config",
        lambda _path, _sha: source_config,
    )
    common = {"research_student_config_sha256": hashlib.sha256(raw).hexdigest()}

    first_profile = installer._validate_research_profile(
        _args(research_student_config_file=first, **common),
        source=Path(__file__).resolve().parents[2],
    )
    second_profile = installer._validate_research_profile(
        _args(research_student_config_file=second, **common),
        source=Path(__file__).resolve().parents[2],
    )
    assert first_profile["sha256"] != second_profile["sha256"]


def test_complete_study_profile_calls_existing_closed_validators(tmp_path, monkeypatch):
    import school_backend

    backend_source = str(Path(__file__).resolve().parents[2] / "09_backend" / "src")
    if backend_source not in sys.path:
        sys.path.insert(0, backend_source)
    from smhai_backend.domains.school_research import managed

    runtime_file = tmp_path / "runtime.json"
    service_file = tmp_path / "service.json"
    study_file = tmp_path / "study-use.json"
    cat_python = tmp_path / "cat-python.exe"
    cat_source = tmp_path / "cat-source"
    cat_dependencies = tmp_path / "cat-dependencies"
    for path, content in (
        (runtime_file, b"runtime fixture bytes"),
        (service_file, b"service fixture bytes"),
        (study_file, b"study fixture bytes"),
        (cat_python, b"interpreter fixture"),
    ):
        path.write_bytes(content)
    cat_source.mkdir()
    cat_dependencies.mkdir()
    hashes = {
        "research_runtime_sha256": hashlib.sha256(
            runtime_file.read_bytes()
        ).hexdigest(),
        "research_service_sha256": hashlib.sha256(
            service_file.read_bytes()
        ).hexdigest(),
        "research_study_use_sha256": hashlib.sha256(
            study_file.read_bytes()
        ).hexdigest(),
    }
    observed = {}
    monkeypatch.setattr(
        managed,
        "validate_managed_research_config_pair",
        lambda **kwargs: observed.setdefault("managed", kwargs),
    )
    monkeypatch.setattr(
        school_backend,
        "_research_service_base_url",
        lambda *_args: "http://127.0.0.1:58540",
    )
    monkeypatch.setattr(school_backend, "_parse_study_end", lambda value: value)
    monkeypatch.setattr(
        school_backend,
        "_validate_study_use_policy",
        lambda **kwargs: observed.setdefault("study", kwargs),
    )
    profile = installer._validate_research_profile(
        _args(
            research_runtime_file=runtime_file,
            research_service_file=service_file,
            research_cat_python=cat_python,
            research_cat_source=cat_source,
            research_cat_dependencies=cat_dependencies,
            research_study_use_file=study_file,
            research_source_rights_verified=True,
            research_latest_study_end="2027-06-30T00:00:00Z",
            **hashes,
        ),
        source=Path(__file__).resolve().parents[2],
    )

    assert set(profile["workspace_files"]) == {
        "research_runtime_file",
        "research_service_file",
        "research_study_use_file",
    }
    assert observed["managed"]["runtime_config_file"] == runtime_file.resolve()
    assert observed["study"]["study_file"] == study_file.resolve()
    assert observed["study"]["latest_end"] == "2027-06-30T00:00:00Z"


def test_backend_preflight_and_lifecycle_start_receive_same_research_arguments(
    tmp_path,
):
    arguments = {
        name: None
        for name, _sha_name, _flag, _sha_flag, _limit in installer.RESEARCH_FILE_PAIRS
    }
    for _name, sha_name, _flag, _sha_flag, _limit in installer.RESEARCH_FILE_PAIRS:
        arguments[sha_name] = None
    for name, _flag, _kind in installer.RESEARCH_PATH_ARGUMENTS:
        arguments[name] = None
    for name, _flag in installer.RESEARCH_VALUE_ARGUMENTS:
        arguments[name] = None
    for name, _flag in installer.RESEARCH_BOOLEAN_ARGUMENTS:
        arguments[name] = False
    arguments.update(
        research_runtime_file=str(tmp_path / "original-runtime.json"),
        research_runtime_sha256="a" * 64,
        research_service_file=str(tmp_path / "original-service.json"),
        research_service_sha256="b" * 64,
        research_cat_python=str(tmp_path / "cat-python.exe"),
        research_cat_source=str(tmp_path / "cat-source"),
        research_cat_dependencies=str(tmp_path / "cat-dependencies"),
        research_study_use_file=str(tmp_path / "original-study.json"),
        research_study_use_sha256="c" * 64,
        research_source_rights_verified=True,
        research_latest_study_end="2027-06-30T00:00:00Z",
        enable_research_education_worker=True,
    )
    profile = {
        "arguments": arguments,
        "workspace_files": {
            "research_runtime_file": {"target_name": "research-runtime.json"},
            "research_service_file": {"target_name": "research-service.json"},
            "research_study_use_file": {"target_name": "research-study-use.json"},
        },
    }
    config = {
        "dependency_target": tmp_path / "dependencies",
        "workspace": tmp_path / "fresh-workspace",
        "source": tmp_path / "source",
        "mysql_bin": tmp_path / "mysql",
        "python_specs": {
            name: tmp_path / f"{name}.exe" for name in installer.PYTHON_MODULES
        },
        "ports": {
            "database": 3330,
            "backend": 8104,
            "frontend": 4194,
            "standard_cat": 8182,
        },
        "frontend_mode": "preview",
        "llm_profile": "school-gpu-7b",
        "research_profile": profile,
    }

    commands = installer._commands(config)

    preflight_args = commands["backend_preflight"][1:]
    start_args = commands["application_start"][1:]
    research_flags = [
        flag for _name, _sha, flag, _sha_flag, _limit in installer.RESEARCH_FILE_PAIRS
    ] + [flag for _name, flag, _kind in installer.RESEARCH_PATH_ARGUMENTS]
    for flag in research_flags:
        assert (flag in preflight_args) is (flag in start_args)
    for expected in (
        "--research-source-rights-verified",
        "--research-latest-study-end",
        "--enable-research-education-worker",
    ):
        assert expected in preflight_args and expected in start_args
    assert (
        str(config["workspace"] / ".school-research-profile" / "research-runtime.json")
        in preflight_args
    )
    assert (
        str(config["workspace"] / ".school-research-profile" / "research-runtime.json")
        in start_args
    )
    assert str(tmp_path / "original-runtime.json") not in preflight_args + start_args


def test_research_cli_flags_use_workspace_imported_files_and_keep_opt_ins_explicit(
    tmp_path,
):
    arguments = {
        name: None
        for name, _sha_name, _flag, _sha_flag, _limit in installer.RESEARCH_FILE_PAIRS
    }
    for _name, sha_name, _flag, _sha_flag, _limit in installer.RESEARCH_FILE_PAIRS:
        arguments[sha_name] = None
    for name, _flag, _kind in installer.RESEARCH_PATH_ARGUMENTS:
        arguments[name] = None
    for name, _flag in installer.RESEARCH_VALUE_ARGUMENTS:
        arguments[name] = None
    for name, _flag in installer.RESEARCH_BOOLEAN_ARGUMENTS:
        arguments[name] = False
    arguments.update(
        research_runtime_file="D:/provided/runtime.json",
        research_runtime_sha256="a" * 64,
        research_study_use_file="D:/provided/study.json",
        research_study_use_sha256="b" * 64,
        research_source_rights_verified=True,
        research_latest_study_end="2027-06-30T00:00:00Z",
        enable_research_education_worker=True,
    )
    profile = {
        "arguments": arguments,
        "workspace_files": {
            "research_runtime_file": {"target_name": "research-runtime.json"},
            "research_study_use_file": {"target_name": "research-study-use.json"},
        },
    }

    result = installer._research_cli_arguments(
        {"research_profile": profile, "workspace": tmp_path / "fresh"}
    )

    assert (
        str(tmp_path / "fresh" / ".school-research-profile" / "research-runtime.json")
        in result
    )
    assert "D:/provided/runtime.json" not in result
    assert "--research-source-rights-verified" in result
    assert "--enable-research-education-worker" in result
    assert "--enable-research-education-input-review-continuation" not in result


def test_installer_research_flags_match_existing_lifecycle_contract():
    import school_app_lifecycle as lifecycle

    existing_flags = {
        **lifecycle.RESEARCH_CONFIG_FLAGS,
        **lifecycle.RESEARCH_STUDY_USE_FLAGS,
        **lifecycle.RESEARCH_PROGRAMME_MANIFEST_FLAGS,
        **lifecycle.STUDENT_RESEARCH_CONFIG_FLAGS,
        **lifecycle.RESEARCH_EDUCATION_DRAFT_CONFIG_FLAGS,
    }
    for name, _sha_name, path_flag, sha_flag, _limit in installer.RESEARCH_FILE_PAIRS:
        if name in existing_flags:
            assert path_flag == existing_flags[name]
        if _sha_name in existing_flags:
            assert sha_flag == existing_flags[_sha_name]
    for name, flag, _kind in installer.RESEARCH_PATH_ARGUMENTS:
        assert flag == existing_flags[name]
    assert (
        lifecycle.RESEARCH_EDUCATION_WORKER_FLAG == "--enable-research-education-worker"
    )
    assert (
        lifecycle.RESEARCH_PROGRAMME_WORKER_FLAG == "--enable-research-programme-worker"
    )


def test_workspace_research_import_is_exclusive_and_resume_detects_tampering(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source_file = tmp_path / "study-use.json"
    raw = b'{"schema":"test"}\n'
    source_file.write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    profile = {
        "workspace_files": {
            "research_study_use_file": {
                "source_path": str(source_file),
                "sha256": sha,
                "target_name": "research-study-use.json",
                "max_bytes": 128,
            }
        }
    }
    config = {"workspace": workspace, "research_profile": profile}

    installer._materialize_workspace_research_files(config)
    target = workspace / ".school-research-profile" / "research-study-use.json"
    assert target.read_bytes() == raw
    installer._verify_workspace_research_files(config)
    with pytest.raises(
        installer.InstallError, match="RESEARCH_PROFILE_TARGET_CONFLICT"
    ):
        installer._materialize_workspace_research_files(config)

    target.write_bytes(b"changed")
    with pytest.raises(installer.InstallError, match="RESEARCH_PROFILE_HASH_MISMATCH"):
        installer._verify_workspace_research_files(config)
