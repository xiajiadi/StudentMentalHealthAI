from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

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
    old_state.pop("workspace_profile_import_state")
    state_path = tmp_path / "old-checkpoint.json"
    state_path.write_text(json.dumps(old_state), encoding="utf-8")
    restored = installer._read_state(state_path)
    assert (
        restored["research_profile_sha256"] == installer.RESEARCH_PROFILE_EMPTY_SHA256
    )
    assert restored["workspace_profile_import_state"] == "UNTRACKED"
    changed_profile_config = {
        **config,
        "research_profile": {"sha256": "f" * 64},
    }
    with pytest.raises(installer.InstallError, match="RESUME_CONFIGURATION_MISMATCH"):
        installer._match_state(restored, changed_profile_config)


def test_old_profile_failure_checkpoint_is_not_assumed_to_have_a_safe_import_boundary(tmp_path):
    config = {
        "source_head": "a" * 40,
        "target_head": "a" * 40,
        "source": tmp_path / "source",
        "mysql_bin": tmp_path / "mysql",
        "python_specs": {
            name: tmp_path / f"{index}.exe"
            for index, name in enumerate(installer.PYTHON_MODULES)
        },
        "workspace": tmp_path / "workspace",
        "ports": {"backend": 8104, "frontend": 4194, "standard_cat": 8182, "database": 3330},
        "frontend_mode": "preview",
        "llm_profile": "school-gpu-7b",
        "dependency_target": tmp_path / "dependencies",
        "research_profile": {"sha256": "c" * 64},
    }
    old_state = installer._new_state(config)
    old_state["workspace_id"] = "a" * 32
    old_state["stages"]["dependencies"] = {"status": "COMPLETED", "code": None}
    old_state["stages"]["workspace"] = {
        "status": "FAILED", "code": "RESEARCH_PROFILE_TARGET_WRITE_FAILED",
    }
    old_state.pop("workspace_profile_import_state")
    state_path = tmp_path / "old-profile-checkpoint.json"
    state_path.write_text(json.dumps(old_state), encoding="utf-8")
    restored = installer._read_state(state_path)

    assert restored["workspace_profile_import_state"] == "UNTRACKED"
    with pytest.raises(installer.InstallError, match="INCOMPLETE_STAGE_PRESERVED_FOR_INSPECTION"):
        installer._validate_resume_workspace_binding(
            restored, workspace_exists=True, allow_profile_import_recovery=True
        )


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


def _workspace_import_config(tmp_path, *, workspace_files=None):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    if workspace_files is None:
        workspace_files = {}
        for name, target_name in (
            ("research_runtime_file", "research-runtime.json"),
            ("research_service_file", "research-service.json"),
        ):
            source = tmp_path / f"{target_name}.source"
            raw = (f'{{"fixture":"{target_name}"}}\n').encode()
            source.write_bytes(raw)
            workspace_files[name] = {
                "source_path": str(source),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "target_name": target_name,
                "max_bytes": 128,
            }
    return {
        "workspace": workspace,
        "ports": {"database": 3330},
        "research_profile": {"workspace_files": workspace_files},
    }


def test_recovery_import_completes_only_missing_exact_files_without_overwrite(tmp_path):
    config = _workspace_import_config(tmp_path)
    destination = config["workspace"] / ".school-research-profile"
    destination.mkdir()
    runtime_record = config["research_profile"]["workspace_files"]["research_runtime_file"]
    runtime_target = destination / runtime_record["target_name"]
    runtime_target.write_bytes(Path(runtime_record["source_path"]).read_bytes())
    original = runtime_target.read_bytes()

    installer._resume_workspace_research_file_import(config)

    assert runtime_target.read_bytes() == original
    for record in config["research_profile"]["workspace_files"].values():
        assert (destination / record["target_name"]).read_bytes() == Path(record["source_path"]).read_bytes()
    installer._verify_workspace_research_files(config)


def test_recovery_import_rejects_extra_files_and_partial_existing_files(tmp_path):
    config = _workspace_import_config(tmp_path)
    destination = config["workspace"] / ".school-research-profile"
    destination.mkdir()
    (destination / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(installer.InstallError, match="RESEARCH_PROFILE_TARGET_CONFLICT"):
        installer._resume_workspace_research_file_import(config)

    (destination / "unexpected.json").unlink()
    first_record = next(iter(config["research_profile"]["workspace_files"].values()))
    partial = destination / first_record["target_name"]
    partial.write_bytes(b"partial-copy")
    with pytest.raises(installer.InstallError, match="RESEARCH_PROFILE_HASH_MISMATCH"):
        installer._resume_workspace_research_file_import(config)
    assert partial.read_bytes() == b"partial-copy"


def test_recovery_import_requires_matching_workspace_identity(tmp_path):
    config = _workspace_import_config(tmp_path)
    (config["workspace"] / "database.private.dpapi").write_bytes(b"sealed-placeholder")
    marker = {
        "schema_version": "psynova.synthetic-workspace.v1",
        "project": "StudentMentalHealthAI",
        "workspace_id": "b" * 32,
        "state": "READY_FOR_MIGRATION",
        "host": "127.0.0.1",
        "port": 3330,
        "database": "smhai_school_demo",
        "synthetic_only": True,
    }
    (config["workspace"] / "workspace.json").write_text(json.dumps(marker), encoding="utf-8")
    state = {"workspace_id": "a" * 32}

    with pytest.raises(installer.InstallError, match="WORKSPACE_IDENTITY_CHANGED"):
        installer._verify_profile_import_workspace_identity(config, state)


def test_recovery_identity_rechecks_owned_listener_and_dpapi_workspace_binding(
    monkeypatch, tmp_path
):
    config = _workspace_import_config(tmp_path)
    workspace_id = "a" * 32
    marker = {
        "schema_version": "psynova.synthetic-workspace.v1",
        "project": "StudentMentalHealthAI",
        "workspace_id": workspace_id,
        "state": "READY_FOR_MIGRATION",
        "host": "127.0.0.1",
        "port": 3330,
        "database": "smhai_school_demo",
        "synthetic_only": True,
    }
    (config["workspace"] / "workspace.json").write_text(json.dumps(marker), encoding="utf-8")
    private_path = config["workspace"] / "database.private.dpapi"
    private_path.write_bytes(b"sealed-placeholder")
    private = {"DB_HOST": "127.0.0.1", "DB_NAME": "smhai_school_demo", "DB_PORT": "3330"}
    calls = []
    preparation = ModuleType("prepare_school_runtime")
    preparation.validate_marker = lambda workspace, repo: marker
    preparation.verify_process = lambda verified: calls.append(("owned-process", verified["workspace_id"]))
    settings = ModuleType("private_settings")
    settings.read_private = lambda path: private if path == private_path else {}
    monkeypatch.setitem(sys.modules, "prepare_school_runtime", preparation)
    monkeypatch.setitem(sys.modules, "private_settings", settings)

    installer._verify_profile_import_workspace_identity(config, {"workspace_id": workspace_id})

    assert calls == [("owned-process", workspace_id)]
    assert private == {}


def test_workspace_identity_is_checkpointed_before_profile_materialization(monkeypatch, tmp_path):
    config = {
        "state_path": tmp_path / "state.json",
        "state_temp_path": tmp_path / "state.json.tmp",
        "research_profile": {"workspace_files": {"research_runtime_file": {}}},
    }
    state = {
        "workspace_id": None,
        "workspace_profile_import_state": "PENDING",
        "stages": {
            name: {"status": "PENDING", "code": None}
            for name in installer.STAGE_NAMES
        },
    }
    writes = []
    events = []
    monkeypatch.setattr(
        installer,
        "_write_state",
        lambda _path, _temp, value, **_kwargs: writes.append(json.loads(json.dumps(value))),
    )
    monkeypatch.setattr(
        installer,
        "_run_json",
        lambda *_args, **_kwargs: (
            0,
            {
                "state": "READY_FOR_MIGRATION",
                "synthetic_only": True,
                "workspace_id": "a" * 32,
            },
        ),
    )

    def fail_import(_config):
        events.append("materialize")
        raise installer.InstallError("RESEARCH_PROFILE_TARGET_WRITE_FAILED")

    monkeypatch.setattr(installer, "_materialize_workspace_research_files", fail_import)
    with pytest.raises(installer.InstallError, match="RESEARCH_PROFILE_TARGET_WRITE_FAILED"):
        installer._run_stage(config, state, {"workspace": ["workspace-create"]}, "workspace")

    materialize_write = writes[-3]
    assert materialize_write["workspace_id"] == "a" * 32
    assert materialize_write["workspace_profile_import_state"] == "PENDING"
    assert materialize_write["stages"]["workspace"]["status"] == "RUNNING"
    assert events == ["materialize"]
    assert state["stages"]["workspace"] == {
        "status": "FAILED",
        "code": "RESEARCH_PROFILE_TARGET_WRITE_FAILED",
    }


def test_resume_recovers_only_import_boundary_without_replaying_workspace_create(
    monkeypatch, tmp_path
):
    config = _workspace_import_config(tmp_path)
    config.update({
        "ports": {"database": 3330, "backend": 8104, "frontend": 4194, "standard_cat": 8182},
        "source_head": "a" * 40,
        "target_head": "a" * 40,
        "source": tmp_path / "source",
        "dependency_target": tmp_path / "deps",
        "mysql_bin": tmp_path / "mysql",
        "python_specs": {
            name: tmp_path / f"{index}.exe"
            for index, name in enumerate(installer.PYTHON_MODULES)
        },
        "frontend_mode": "preview",
        "llm_profile": "school-gpu-7b",
        "state_path": tmp_path / "state.json",
        "state_temp_path": tmp_path / "state.json.tmp",
    })
    config["research_profile"]["sha256"] = "c" * 64
    state = installer._new_state(config)
    state["workspace_id"] = "a" * 32
    state["stages"]["dependencies"] = {"status": "COMPLETED", "code": None}
    state["stages"]["workspace"] = {"status": "RUNNING", "code": None}
    state["workspace_profile_import_state"] = "RUNNING"
    (config["workspace"] / "database.private.dpapi").write_bytes(b"sealed-placeholder")
    (config["workspace"] / "workspace.json").write_text(json.dumps({
        "schema_version": "psynova.synthetic-workspace.v1",
        "project": "StudentMentalHealthAI",
        "workspace_id": "a" * 32,
        "state": "READY_FOR_MIGRATION",
        "host": "127.0.0.1",
        "port": 3330,
        "database": "smhai_school_demo",
        "synthetic_only": True,
    }), encoding="utf-8")
    destination = config["workspace"] / ".school-research-profile"
    destination.mkdir()
    first = next(iter(config["research_profile"]["workspace_files"].values()))
    (destination / first["target_name"]).write_bytes(Path(first["source_path"]).read_bytes())

    events = []
    monkeypatch.setattr(installer, "_validate_configuration", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(installer, "_read_state", lambda _path: state)
    monkeypatch.setattr(installer, "_match_state", lambda *_args: None)
    monkeypatch.setattr(installer, "_verify_completed", lambda *_args: events.append("revalidate-completed"))
    monkeypatch.setattr(installer, "_commands", lambda *_args: {})
    monkeypatch.setattr(installer, "_verify_profile_import_workspace_identity", lambda *_args: events.append("identity"))

    def run_stage(_config, current_state, _commands, name):
        if name == "workspace":
            assert current_state["stages"][name]["status"] == "COMPLETED"
            events.append("workspace-noop")
        elif current_state["stages"][name]["status"] == "PENDING":
            events.append(name)

    monkeypatch.setattr(installer, "_run_stage", run_stage)
    installer.resume(SimpleNamespace())

    assert state["workspace_profile_import_state"] == "COMPLETED"
    assert state["stages"]["workspace"] == {"status": "COMPLETED", "code": None}
    assert events[:3] == ["revalidate-completed", "identity", "workspace-noop"]
    assert "workspace-create" not in events
    installer._verify_workspace_research_files(config)


@pytest.mark.parametrize(
    "stage_status,stage_code,import_state,expected",
    [
        ("RUNNING", None, "RUNNING", True),
        ("FAILED", "RESEARCH_PROFILE_TARGET_WRITE_FAILED", "RUNNING", True),
        ("FAILED", "RESEARCH_PROFILE_TARGET_WRITE_FAILED", "COMPLETED", False),
        ("RUNNING", None, "UNTRACKED", False),
        ("FAILED", "WORKSPACE_CREATE_FAILED", "RUNNING", False),
    ],
)
def test_profile_import_recovery_boundary_is_explicit_and_closed(
    tmp_path, stage_status, stage_code, import_state, expected
):
    config = _workspace_import_config(tmp_path)
    config["research_profile"]["sha256"] = "c" * 64
    state = installer._new_state({
        "source_head": "a" * 40,
        "target_head": "a" * 40,
        "source": tmp_path / "source",
        "dependency_target": tmp_path / "deps",
        "mysql_bin": tmp_path / "mysql",
        "python_specs": {name: tmp_path / f"{index}.exe" for index, name in enumerate(installer.PYTHON_MODULES)},
        "workspace": config["workspace"],
        "ports": {"database": 3330, "backend": 8104, "frontend": 4194, "standard_cat": 8182},
        "frontend_mode": "preview",
        "llm_profile": "school-gpu-7b",
        "research_profile": config["research_profile"],
    })
    state["workspace_id"] = "a" * 32
    state["stages"]["dependencies"] = {"status": "COMPLETED", "code": None}
    state["stages"]["workspace"] = {"status": stage_status, "code": stage_code}
    state["workspace_profile_import_state"] = import_state
    (config["workspace"] / "workspace.json").write_text("{}", encoding="utf-8")

    eligible = installer._research_profile_import_recovery_eligible(
        config, state, workspace_exists=True
    )
    assert eligible is expected
    if expected:
        installer._validate_resume_workspace_binding(
            state, workspace_exists=True, allow_profile_import_recovery=eligible
        )
    else:
        with pytest.raises(installer.InstallError, match="INCOMPLETE_STAGE_PRESERVED_FOR_INSPECTION"):
            installer._validate_resume_workspace_binding(
                state, workspace_exists=True, allow_profile_import_recovery=eligible
            )
