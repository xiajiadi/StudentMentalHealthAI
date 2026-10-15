from __future__ import annotations

import ast
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


def _real_dependency_plan_stage_rows():
    return [
        {
            "name": module,
            "state": "planned",
            "target": "node_modules" if module == "10_frontend" else ".venv",
            **({} if module == "10_frontend" else {"python": "3.12.13"}),
        }
        for module in installer.DEPENDENCY_PLAN_STAGE_NAMES
    ]


def test_dependency_plan_accepts_exact_seven_stage_protocol():
    rows = _real_dependency_plan_stage_rows()

    assert len(rows) == 7
    assert installer._dependency_plan_stages_valid(rows)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda rows: rows.pop(),
        lambda rows: rows.__setitem__(2, dict(rows[1])),
        lambda rows: rows.__setitem__(3, {**rows[3], "name": "unknown_module"}),
        lambda rows: rows.__setitem__(4, {**rows[4], "state": "succeeded"}),
    ],
    ids=("missing", "duplicate", "unknown", "wrong-state"),
)
def test_dependency_plan_rejects_nonmatching_stage_protocol(mutate):
    rows = _real_dependency_plan_stage_rows()
    mutate(rows)

    assert not installer._dependency_plan_stages_valid(rows)


def test_dependency_receipt_requires_exact_module_and_integrity_stages():
    rows = [
        {"name": name, "state": "succeeded", "exit_code": 0}
        for name in installer.DEPENDENCY_RECEIPT_STAGE_NAMES
    ]

    assert len(rows) == 8
    assert installer._dependency_stages_match(
        rows,
        installer.DEPENDENCY_RECEIPT_STAGE_NAMES,
        expected_state="succeeded",
        require_success_exit=True,
    )
    for invalid in (
        rows[:-1],
        [*rows[:2], dict(rows[1]), *rows[3:]],
        [*rows[:3], {**rows[3], "name": "unknown_module"}, *rows[4:]],
        [*rows[:4], {**rows[4], "state": "failed"}, *rows[5:]],
        [*rows[:4], {**rows[4], "exit_code": False}, *rows[5:]],
    ):
        assert not installer._dependency_stages_match(
            invalid,
            installer.DEPENDENCY_RECEIPT_STAGE_NAMES,
            expected_state="succeeded",
            require_success_exit=True,
        )


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


def _seed_assignment_value(tree: ast.Module, name: str) -> ast.expr:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return node.value
    raise AssertionError(f"registered seed assignment missing: {name}")


def test_installer_seed_expectations_match_registered_recipe_without_running_seed():
    seed_path = Path(__file__).resolve().parents[2] / "11_database" / "database_layer" / "school_seed.py"
    tree = ast.parse(seed_path.read_text(encoding="utf-8"), filename=str(seed_path))

    recipes = _seed_assignment_value(tree, "SYNTHETIC_SCHOOL_RECIPES")
    assert isinstance(recipes, ast.Tuple)
    recipe_keys = []
    subject_refs = []
    for recipe in recipes.elts:
        assert isinstance(recipe, ast.Call)
        fields = {keyword.arg: ast.literal_eval(keyword.value) for keyword in recipe.keywords}
        recipe_keys.append(fields["key"])
        subject_refs.append(fields["subject_ref"])

    roles = ast.literal_eval(_seed_assignment_value(tree, "SCHOOL_SEED_ROLE_CODES"))
    slots = _seed_assignment_value(tree, "SCHOOL_SEED_SLOTS")
    assert isinstance(slots, ast.Call) and isinstance(slots.func, ast.Name) and slots.func.id == "tuple"
    assert len(slots.args) == 1 and isinstance(slots.args[0], ast.GeneratorExp)
    comprehensions = slots.args[0].generators
    assert len(comprehensions) == 2
    registered_schools = ast.literal_eval(comprehensions[0].iter)
    registered_roles = ast.literal_eval(comprehensions[1].iter)

    assert tuple(recipe_keys) == registered_schools
    assert tuple(registered_roles) == roles
    assert len(set(subject_refs)) == len(subject_refs)
    assert installer.SYNTHETIC_SEED_EXPECTED_RESULT == {
        "recipe": "school-contexts-v1",
        "schools": len(recipe_keys),
        "subjects": len(subject_refs),
        "role_accounts": len(registered_schools) * len(registered_roles),
        "credentials": "current-user DPAPI",
        "specialist_subject_grants": 0,
        "admin_subject_grants": 0,
    }


def _real_school_seed_child_payload():
    return {
        "recipe": "school-contexts-v1",
        "schools": 2,
        "subjects": 2,
        "role_accounts": 8,
        "credentials": "current-user DPAPI",
        "specialist_subject_grants": 0,
        "admin_subject_grants": 0,
    }


def test_synthetic_seed_stage_accepts_registered_child_payload(monkeypatch, tmp_path):
    state = {
        "stages": {name: {"status": "PENDING", "code": None} for name in installer.STAGE_NAMES},
    }
    config = {"state_path": tmp_path / "state.json", "state_temp_path": tmp_path / "state.json.tmp"}
    monkeypatch.setattr(installer, "_write_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(installer, "_run_json", lambda *_args, **_kwargs: (0, _real_school_seed_child_payload()))

    installer._run_stage(config, state, {"synthetic_seed": ["seed"]}, "synthetic_seed")

    assert state["stages"]["synthetic_seed"] == {"status": "PENDING_VERIFICATION", "code": None}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(schools=1),
        lambda payload: payload.update(subjects=1),
        lambda payload: payload.update(role_accounts=4),
        lambda payload: payload.update(schools=True),
        lambda payload: payload.update(subjects=False),
        lambda payload: payload.update(role_accounts=True),
        lambda payload: payload.update(specialist_subject_grants=1),
        lambda payload: payload.update(admin_subject_grants=1),
        lambda payload: payload.update(specialist_subject_grants=False),
        lambda payload: payload.pop("subjects"),
        lambda payload: payload.pop("credentials"),
        lambda payload: payload.update(extra_subject_grants=0),
    ],
    ids=(
        "wrong-school-count", "wrong-subject-count", "wrong-account-count", "bool-schools",
        "bool-subjects", "bool-accounts", "specialist-grant", "admin-grant", "bool-grant",
        "missing-count", "missing-protocol-field", "unexpected-grant-field",
    ),
)
def test_synthetic_seed_stage_rejects_unregistered_or_unsafe_child_payload(
    monkeypatch, tmp_path, mutate
):
    payload = _real_school_seed_child_payload()
    mutate(payload)
    state = {
        "stages": {name: {"status": "PENDING", "code": None} for name in installer.STAGE_NAMES},
    }
    config = {"state_path": tmp_path / "state.json", "state_temp_path": tmp_path / "state.json.tmp"}
    monkeypatch.setattr(installer, "_write_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(installer, "_run_json", lambda *_args, **_kwargs: (0, payload))

    with pytest.raises(installer.InstallError, match="SYNTHETIC_SEED_FAILED"):
        installer._run_stage(config, state, {"synthetic_seed": ["seed"]}, "synthetic_seed")

    assert state["stages"]["synthetic_seed"] == {"status": "FAILED", "code": "SYNTHETIC_SEED_FAILED"}


@pytest.mark.parametrize(
    ("exit_code", "payload", "expected_code"),
    [
        (
            2,
            {"status": "PARTIAL_FAILURE", "code": "POST_MIGRATION_CHECK_FAILED"},
            "SCHEMA_MIGRATION_POSTCHECK_FAILED",
        ),
        (
            2,
            {"status": "PARTIAL_FAILURE", "code": "MIGRATION_FAILED"},
            "SCHEMA_MIGRATION_DDL_FAILED",
        ),
        (
            2,
            {"status": "BLOCKED", "code": "POST_MIGRATION_CHECK_FAILED"},
            "SCHEMA_MIGRATION_FAILED",
        ),
        (
            2,
            {"status": "PARTIAL_FAILURE", "code": "UNRECOGNIZED_CHILD_FAILURE"},
            "SCHEMA_MIGRATION_FAILED",
        ),
        (
            2,
            {
                "status": "PARTIAL_FAILURE",
                "code": "POST_MIGRATION_CHECK_FAILED",
                "detail": "RAW_CHILD_TEXT_SHOULD_NOT_PERSIST",
            },
            "SCHEMA_MIGRATION_FAILED",
        ),
        (2, {"status": [], "code": "POST_MIGRATION_CHECK_FAILED"}, "SCHEMA_MIGRATION_FAILED"),
        (2, {"status": {}, "code": "POST_MIGRATION_CHECK_FAILED"}, "SCHEMA_MIGRATION_FAILED"),
        (2, {"status": None, "code": "POST_MIGRATION_CHECK_FAILED"}, "SCHEMA_MIGRATION_FAILED"),
        (2, {"status": "PARTIAL_FAILURE", "code": []}, "SCHEMA_MIGRATION_FAILED"),
        (2, {"status": "PARTIAL_FAILURE", "code": {}}, "SCHEMA_MIGRATION_FAILED"),
        (2, {"status": "PARTIAL_FAILURE", "code": None}, "SCHEMA_MIGRATION_FAILED"),
    ],
    ids=(
        "postcheck", "ddl", "wrong-status", "unknown-code", "expanded-payload",
        "status-list", "status-dict", "status-null", "code-list", "code-dict", "code-null",
    ),
)
def test_schema_stage_maps_only_exact_migrator_partial_failure_results(
    monkeypatch, tmp_path, exit_code, payload, expected_code
):
    state = {
        "workspace_id": "a" * 32,
        "stages": {
            name: {"status": "PENDING", "code": None}
            for name in installer.STAGE_NAMES
        },
    }
    config = {
        "state_path": tmp_path / "state.json",
        "state_temp_path": tmp_path / "state.json.tmp",
    }
    monkeypatch.setattr(installer, "_write_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(installer, "_run_json", lambda *_args, **_kwargs: (exit_code, payload))

    with pytest.raises(installer.InstallError, match=expected_code):
        installer._run_stage(config, state, {"schema_upgrade": ["migrate"]}, "schema")

    assert state["stages"]["schema"] == {"status": "FAILED", "code": expected_code}
    assert "RAW_CHILD_TEXT_SHOULD_NOT_PERSIST" not in str(state)


def test_schema_stage_does_not_trust_failure_payload_when_child_exits_zero(monkeypatch, tmp_path):
    state = {
        "workspace_id": "a" * 32,
        "stages": {
            name: {"status": "PENDING", "code": None}
            for name in installer.STAGE_NAMES
        },
    }
    config = {
        "state_path": tmp_path / "state.json",
        "state_temp_path": tmp_path / "state.json.tmp",
    }
    monkeypatch.setattr(installer, "_write_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        installer,
        "_run_json",
        lambda *_args, **_kwargs: (
            0,
            {"status": "PARTIAL_FAILURE", "code": "POST_MIGRATION_CHECK_FAILED"},
        ),
    )

    with pytest.raises(installer.InstallError, match="SCHEMA_MIGRATION_FAILED"):
        installer._run_stage(config, state, {"schema_upgrade": ["migrate"]}, "schema")

    assert state["stages"]["schema"] == {
        "status": "FAILED",
        "code": "SCHEMA_MIGRATION_FAILED",
    }


@pytest.mark.parametrize(
    "failure_code",
    ["SCHEMA_MIGRATION_DDL_FAILED", "SCHEMA_MIGRATION_POSTCHECK_FAILED"],
)
def test_schema_migration_stage_codes_round_trip_in_existing_checkpoint_shape(
    tmp_path, failure_code
):
    config = {
        "source_head": "b" * 40,
        "target_head": "b" * 40,
        "source": tmp_path / "source",
        "mysql_bin": tmp_path / "mysql-bin",
        "python_specs": {
            name: tmp_path / f"{name}.exe" for name in installer.PYTHON_MODULES
        },
        "workspace": tmp_path / "workspace",
        "ports": {"database": 3330, "backend": 8104, "frontend": 4194, "standard_cat": 8182},
        "frontend_mode": "preview",
        "llm_profile": "school-gpu-7b",
        "dependency_target": tmp_path / "deps",
    }
    state = installer._new_state(config)
    state["workspace_id"] = "a" * 32
    state["stages"]["dependencies"] = {"status": "COMPLETED", "code": None}
    state["stages"]["workspace"] = {"status": "COMPLETED", "code": None}
    state_path = installer._state_path(config["workspace"])
    temp_path = installer._state_temp_path(config["workspace"])

    installer._mark_stage(
        {"state_path": state_path, "state_temp_path": temp_path},
        state,
        "schema",
        "FAILED",
        failure_code,
    )

    restored = installer._read_state(state_path)
    assert restored["stages"]["schema"] == {"status": "FAILED", "code": failure_code}


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
