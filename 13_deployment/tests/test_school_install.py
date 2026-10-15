from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_install as installer


def test_python_specs_require_exact_supported_module_set(tmp_path):
    paths = {
        module: tmp_path / f"python-{index}.exe"
        for index, module in enumerate(installer.PYTHON_MODULES)
    }
    specs = [f"{module}={path}" for module, path in paths.items()]

    parsed = installer._parse_python_specs(specs)

    assert parsed == paths
    with pytest.raises(installer.InstallError):
        installer._parse_python_specs(specs[:-1])
    with pytest.raises(installer.InstallError):
        installer._parse_python_specs([*specs, specs[0]])
    with pytest.raises(installer.InstallError):
        installer._parse_python_specs([*specs[:-1], "99_unknown=C:\\python.exe"])


@pytest.mark.parametrize(
    "ports",
    [
        (3308, 8104, 4194, 8182),
        (3399, 65535, 1024, 8182),
    ],
)
def test_port_profile_accepts_distinct_loopback_ports(ports):
    installer._validate_ports(*ports)


@pytest.mark.parametrize(
    "ports",
    [
        (3307, 8104, 4194, 8182),
        (3330, 8104, 8104, 8182),
        (3330, 8104, 4194, 4194),
        (3330, 80, 4194, 8182),
    ],
)
def test_port_profile_rejects_legacy_or_colliding_ports(ports):
    with pytest.raises(installer.InstallError):
        installer._validate_ports(*ports)


def test_owned_ready_application_status_does_not_claim_whole_platform_ready():
    config = {"ports": {"backend": 8104, "frontend": 4194, "standard_cat": 8182}}
    status = {
        "status": "RUNNING",
        "workspace_id": "a" * 32,
        "manifest_is_current_revision": True,
        "manifest_revision": installer.CURRENT_SCHOOL_REVISION,
        "database": "VERIFIED",
        "whole_ready": False,
        "services": {
            name: {
                "port": port,
                "owned_process": True,
                "listener": "OWNED",
                "ready": True,
            }
            for name, port in config["ports"].items()
        },
        "standard_cat": {"readiness": "READY", "port": 8182},
    }

    assert installer._verify_app_status(status, config, "a" * 32)
    state = installer._new_state({
        "source_head": "b" * 40,
        "target_head": "b" * 40,
        "source": Path("D:/external/source"),
        "mysql_bin": Path("D:/external/mysql-bin"),
        "python_specs": {name: Path(f"D:/python/{index}.exe") for index, name in enumerate(installer.PYTHON_MODULES)},
        "workspace": Path("D:/external/workspace"),
        "ports": config["ports"],
        "frontend_mode": "preview",
        "llm_profile": "school-gpu-7b",
        "dependency_target": Path("D:/external/dependencies"),
    })
    assert installer._summary(state)["whole_ready"] is False
    status["services"]["backend"]["listener"] = "MISSING_OR_FOREIGN"
    assert not installer._verify_app_status(status, config, "a" * 32)


def test_resume_never_replays_running_or_pending_verification_stages(monkeypatch, tmp_path):
    config = {
        "state_path": tmp_path / "state.json",
        "state_temp_path": tmp_path / "state.json.tmp",
    }
    state = {
        "stages": {name: {"status": "PENDING", "code": None} for name in installer.STAGE_NAMES},
    }
    state["stages"]["workspace"]["status"] = "RUNNING"
    state["stages"]["synthetic_seed"]["status"] = "PENDING_VERIFICATION"
    monkeypatch.setattr(installer, "_run_json", lambda *args, **kwargs: pytest.fail("child command replayed"))

    with pytest.raises(installer.InstallError, match="INCOMPLETE_STAGE_PRESERVED_FOR_INSPECTION"):
        installer._run_stage(config, state, {}, "workspace")
    installer._run_stage(config, state, {}, "synthetic_seed")


@pytest.mark.parametrize("dependency_status", ["PENDING", "COMPLETED"])
def test_resume_allows_first_workspace_creation_when_prior_workspace_stage_never_started(dependency_status):
    state = {
        "workspace_id": None,
        "stages": {name: {"status": "PENDING", "code": None} for name in installer.STAGE_NAMES},
    }
    state["stages"]["dependencies"]["status"] = dependency_status

    installer._validate_resume_workspace_binding(state, workspace_exists=False)


@pytest.mark.parametrize("workspace_status,workspace_id", [("RUNNING", None), ("FAILED", None), ("PENDING", "a" * 32)])
def test_resume_rejects_missing_workspace_after_creation_started_or_identity_assigned(
    workspace_status, workspace_id
):
    state = {
        "workspace_id": workspace_id,
        "stages": {name: {"status": "PENDING", "code": None} for name in installer.STAGE_NAMES},
    }
    state["stages"]["workspace"]["status"] = workspace_status

    expected_code = (
        "INCOMPLETE_STAGE_PRESERVED_FOR_INSPECTION"
        if workspace_status in {"RUNNING", "FAILED"}
        else "WORKSPACE_STAGE_NOT_RESTARTABLE"
    )
    with pytest.raises(installer.InstallError, match=expected_code):
        installer._validate_resume_workspace_binding(state, workspace_exists=False)


def test_resume_rejects_missing_workspace_when_a_later_stage_is_not_pending():
    state = {
        "workspace_id": None,
        "stages": {name: {"status": "PENDING", "code": None} for name in installer.STAGE_NAMES},
    }
    state["stages"]["schema"]["status"] = "COMPLETED"

    with pytest.raises(installer.InstallError, match="WORKSPACE_STAGE_NOT_RESTARTABLE"):
        installer._validate_resume_workspace_binding(state, workspace_exists=False)


def test_resume_revalidates_completed_dependencies_before_first_workspace_creation(monkeypatch, tmp_path):
    workspace = tmp_path / "fresh-workspace"
    state = {
        "workspace_id": None,
        "stages": {name: {"status": "PENDING", "code": None} for name in installer.STAGE_NAMES},
    }
    state["stages"]["dependencies"]["status"] = "COMPLETED"
    config = {"workspace": workspace, "state_path": tmp_path / "state.json"}
    events = []

    monkeypatch.setattr(installer, "_validate_configuration", lambda *args, **kwargs: config)
    monkeypatch.setattr(installer, "_read_state", lambda path: state)
    monkeypatch.setattr(installer, "_match_state", lambda *args: None)
    monkeypatch.setattr(installer, "_commands", lambda *args: {})
    monkeypatch.setattr(installer, "_verify_completed", lambda *args: events.append("revalidate"))

    def run_stage(stage_config, current_state, commands, name):
        if name == "dependencies":
            assert current_state["stages"][name]["status"] == "COMPLETED"
            events.append("dependencies-noop")
            return
        if name == "workspace":
            events.append(name)
            current_state["stages"][name]["status"] = "COMPLETED"
            current_state["workspace_id"] = "a" * 32
            return
        assert current_state["stages"]["workspace"]["status"] == "COMPLETED"

    monkeypatch.setattr(installer, "_run_stage", run_stage)
    monkeypatch.setattr(installer, "_summary", lambda current_state: {"status": "TESTED"})
    monkeypatch.setattr(installer, "_write_state", lambda *args, **kwargs: None)

    assert installer.resume(type("Args", (), {})()) == {"status": "TESTED"}
    assert events == ["revalidate", "dependencies-noop", "workspace"]
    assert not workspace.exists()


def test_checkpoint_is_content_free_and_written_atomically(tmp_path):
    workspace = tmp_path / ".StudentMentalHealthAI-school-install-20261016-v"
    state_path = installer._state_path(workspace)
    temp_path = installer._state_temp_path(workspace)
    state = installer._new_state({
        "source_head": "b" * 40,
        "target_head": "b" * 40,
        "source": tmp_path / "source",
        "mysql_bin": tmp_path / "mysql-bin",
        "python_specs": {name: tmp_path / f"{name}.exe" for name in installer.PYTHON_MODULES},
        "workspace": workspace,
        "ports": {"database": 3330, "backend": 8104, "frontend": 4194, "standard_cat": 8182},
        "frontend_mode": "preview",
        "llm_profile": "school-gpu-7b",
        "dependency_target": tmp_path / "deps",
    })
    state["credentials"] = "must-never-be-stored"

    with pytest.raises(installer.InstallError, match="CHECKPOINT_FIELDS_INVALID"):
        installer._write_state(state_path, temp_path, state, initial=True)
    assert not state_path.exists()
    del state["credentials"]
    installer._write_state(state_path, temp_path, state, initial=True)
    saved = json.loads(state_path.read_text(encoding="utf-8"))

    assert not temp_path.exists()
    assert "must-never-be-stored" not in state_path.read_text(encoding="utf-8")
    assert saved["schema"] == installer.STATE_SCHEMA
