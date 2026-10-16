from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace

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


def _dependency_retry_fixture(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "dependencies"
    source.mkdir()
    target.mkdir()
    for relative in installer.DEPENDENCY_PIN_FILES:
        for root in (source, target):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"pinned:{relative}\n", encoding="utf-8")
    config = {
        "source": source,
        "dependency_target": target,
        "source_head": "a" * 40,
        "target_head": "a" * 40,
        "workspace": tmp_path / "workspace",
        "state_path": tmp_path / "install-state.json",
        "state_temp_path": tmp_path / "install-state.json.tmp",
        "ports": {"database": 3339, "backend": 8113, "frontend": 4203, "standard_cat": 8189},
        "python_specs": {},
        "mysql_bin": tmp_path,
        "frontend_mode": "preview",
        "llm_profile": "school-gpu-7b",
        "research_profile": {"sha256": installer.RESEARCH_PROFILE_EMPTY_SHA256},
    }
    state = {
        "workspace_id": None,
        "dependency_module_manifest_sha256": None,
        "stages": {name: {"status": "PENDING", "code": None} for name in installer.STAGE_NAMES},
    }
    state["stages"]["dependencies"] = {"status": "FAILED", "code": "DEPENDENCY_RECEIPT_UNAVAILABLE"}
    return config, state


def _stub_clean_git(monkeypatch, config):
    monkeypatch.setattr(
        installer,
        "_validate_git_root",
        lambda root, *, require_clean: config["source_head"] if root in {config["source"], config["dependency_target"]} else None,
    )
    monkeypatch.setattr(installer, "_git_output", lambda *_args, **_kwargs: "")


def test_dependency_child_error_is_projected_before_receipt_read(monkeypatch, tmp_path):
    state = {"stages": {name: {"status": "PENDING", "code": None} for name in installer.STAGE_NAMES}}
    config = {"state_path": tmp_path / "state.json", "state_temp_path": tmp_path / "state.json.tmp"}
    payload = {
        "schema_version": "school-dependency-preparation.v1",
        "mode": "install",
        "status": "blocked",
        "error_class": "TargetHasUntrackedOrIgnoredFiles",
        "stages": [],
    }
    monkeypatch.setattr(installer, "_write_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(installer, "_run_dependency_preparation", lambda *_args, **_kwargs: (2, payload))
    monkeypatch.setattr(installer, "_dependency_receipt", lambda *_args: pytest.fail("receipt masked child failure"))

    with pytest.raises(installer.InstallError) as caught:
        installer._run_stage(config, state, {"dependencies": ["python", "-B"]}, "dependencies")

    assert caught.value.code == "DEPENDENCY_TARGET_NOT_CLEAN"
    assert caught.value.details == {
        "exit_code": 2,
        "stage": "preflight",
        "error_code": "TargetHasUntrackedOrIgnoredFiles",
    }
    assert state["stages"]["dependencies"] == {"status": "FAILED", "code": "DEPENDENCY_TARGET_NOT_CLEAN"}


def test_dependency_invalid_json_reports_child_exit_code_without_raw_output(monkeypatch):
    monkeypatch.setattr(
        installer.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=7, stdout=b"not-json private output", stderr=b"ignored"),
    )

    with pytest.raises(installer.InstallError) as caught:
        installer._run_dependency_preparation(["python", "-B"], timeout=10)

    assert caught.value.code == "STAGE_RESULT_INVALID"
    assert caught.value.details == {"exit_code": 7, "stage": "child_output", "error_code": "InvalidJson"}
    assert "private output" not in str(caught.value)


def test_retry_flag_is_available_only_for_resume():
    required = [
        "--dependency-target-root", "D:/deps",
        "--workspace", "D:/workspace",
        "--mysql-bin", "D:/mysql/bin",
        "--database-port", "3339",
        "--backend-port", "8113",
        "--frontend-port", "4203",
    ]
    for index, module in enumerate(installer.PYTHON_MODULES):
        required.extend(("--python", f"{module}=D:/python/{index}/python.exe"))

    parsed = installer.build_parser().parse_args(["resume", "--retry-failed-dependencies", *required])

    assert parsed.retry_failed_dependencies is True
    with pytest.raises(SystemExit):
        installer.build_parser().parse_args(["install", "--retry-failed-dependencies", *required])


def test_failed_dependency_resume_defaults_to_fail_closed(monkeypatch, tmp_path):
    config, state = _dependency_retry_fixture(tmp_path)
    monkeypatch.setattr(installer, "_validate_configuration", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(installer, "_read_state", lambda _path: state)
    monkeypatch.setattr(installer, "_match_state", lambda *_args: None)
    monkeypatch.setattr(installer, "_verify_completed", lambda *_args: None)
    monkeypatch.setattr(installer, "_commands", lambda *_args: {"dependencies": ["python", "-B"]})
    monkeypatch.setattr(installer, "_write_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(installer, "_run_dependency_preparation", lambda *_args, **_kwargs: pytest.fail("default resume retried dependencies"))

    with pytest.raises(installer.InstallError, match="INCOMPLETE_STAGE_PRESERVED_FOR_INSPECTION"):
        installer.resume(SimpleNamespace(retry_failed_dependencies=False))


def test_explicit_dependency_retry_is_pinned_and_records_old_failure(monkeypatch, tmp_path):
    config, state = _dependency_retry_fixture(tmp_path)
    events = []
    child_payload = {
        "schema_version": "school-dependency-preparation.v1",
        "mode": "install",
        "run_state": "completed",
        "stages": [],
    }
    monkeypatch.setattr(installer, "_validate_configuration", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(installer, "_read_state", lambda _path: state)
    monkeypatch.setattr(installer, "_match_state", lambda *_args: None)
    monkeypatch.setattr(installer, "_verify_completed", lambda *_args: None)
    monkeypatch.setattr(installer, "_commands", lambda *_args: {"dependencies": ["python", "-B", "prepare"]})
    monkeypatch.setattr(installer, "_write_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(installer, "_run_dependency_preparation", lambda command, **_kwargs: (events.append(command[1]) or (0, child_payload)))
    monkeypatch.setattr(
        installer,
        "_dependency_receipt",
        lambda *_args: {"run_state": "completed", "target_module_manifest_sha256": "b" * 64},
    )
    _stub_clean_git(monkeypatch, config)
    real_run_stage = installer._run_stage

    def run_stage(stage_config, current_state, commands, name, **kwargs):
        if name == "dependencies":
            return real_run_stage(stage_config, current_state, commands, name, **kwargs)
        events.append(name)
        current_state["stages"][name] = {"status": "COMPLETED", "code": None}

    monkeypatch.setattr(installer, "_run_stage", run_stage)
    monkeypatch.setattr(installer, "_summary", lambda _state: {"status": "TESTED"})

    result = installer.resume(SimpleNamespace(retry_failed_dependencies=True))

    assert result == {"status": "TESTED"}
    assert events[0] == "-B"
    assert state["stages"]["dependencies"] == {"status": "COMPLETED", "code": None}
    assert state["dependency_module_manifest_sha256"] == "b" * 64
    start_path, result_path = installer._dependency_retry_paths(config, 1)
    start = json.loads(start_path.read_text(encoding="utf-8"))
    record = json.loads(result_path.read_text(encoding="utf-8"))
    assert start["prior_failure_code"] == "DEPENDENCY_RECEIPT_UNAVAILABLE"
    assert start["attempt"] == 1
    assert isinstance(start["started_at"], str)
    assert record["status"] == "COMPLETED"
    assert record["install_code"] is None
    assert record["exit_code"] is None


def test_failed_dependency_retry_keeps_original_and_child_failure_records(monkeypatch, tmp_path):
    config, state = _dependency_retry_fixture(tmp_path)
    monkeypatch.setattr(installer, "_validate_configuration", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(installer, "_read_state", lambda _path: state)
    monkeypatch.setattr(installer, "_match_state", lambda *_args: None)
    monkeypatch.setattr(installer, "_verify_completed", lambda *_args: None)
    monkeypatch.setattr(installer, "_commands", lambda *_args: {"dependencies": ["python", "-B", "prepare"]})
    monkeypatch.setattr(installer, "_write_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        installer,
        "_run_dependency_preparation",
        lambda *_args, **_kwargs: (
            2,
            {
                "schema_version": "school-dependency-preparation.v1",
                "mode": "install",
                "status": "blocked",
                "error_class": "TargetHasUntrackedOrIgnoredFiles",
                "stages": [],
            },
        ),
    )
    monkeypatch.setattr(installer, "_dependency_receipt", lambda *_args: pytest.fail("receipt masked child failure"))
    _stub_clean_git(monkeypatch, config)

    with pytest.raises(installer.InstallError, match="DEPENDENCY_TARGET_NOT_CLEAN"):
        installer.resume(SimpleNamespace(retry_failed_dependencies=True))

    assert state["stages"]["dependencies"] == {"status": "FAILED", "code": "DEPENDENCY_TARGET_NOT_CLEAN"}
    start_path, result_path = installer._dependency_retry_paths(config, 1)
    start = json.loads(start_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert start["prior_failure_code"] == "DEPENDENCY_RECEIPT_UNAVAILABLE"
    assert result["status"] == "FAILED"
    assert result["exit_code"] == 2
    assert result["stage"] == "preflight"
    assert result["error_code"] == "TargetHasUntrackedOrIgnoredFiles"
    assert result["install_code"] == "DEPENDENCY_TARGET_NOT_CLEAN"


def test_failed_dependency_stage_requires_explicit_retry_capability(monkeypatch, tmp_path):
    config, state = _dependency_retry_fixture(tmp_path)
    monkeypatch.setattr(installer, "_write_state", lambda *_args, **_kwargs: pytest.fail("stage must not transition"))

    with pytest.raises(installer.InstallError, match="INCOMPLETE_STAGE_PRESERVED_FOR_INSPECTION"):
        installer._run_stage(config, state, {"dependencies": ["python", "-B"]}, "dependencies")

    assert state["stages"]["dependencies"] == {"status": "FAILED", "code": "DEPENDENCY_RECEIPT_UNAVAILABLE"}


def test_retry_persists_failed_to_running_without_pending_window(monkeypatch, tmp_path):
    config, state = _dependency_retry_fixture(tmp_path)
    writes = []
    child_payload = {
        "schema_version": "school-dependency-preparation.v1",
        "mode": "install",
        "run_state": "completed",
        "stages": [],
    }
    monkeypatch.setattr(installer, "_validate_configuration", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(installer, "_read_state", lambda _path: state)
    monkeypatch.setattr(installer, "_match_state", lambda *_args: None)
    monkeypatch.setattr(installer, "_verify_completed", lambda *_args: None)
    monkeypatch.setattr(installer, "_commands", lambda *_args: {"dependencies": ["python", "-B", "prepare"]})
    monkeypatch.setattr(installer, "_write_state", lambda _path, _temp, current: writes.append(current["stages"]["dependencies"]["status"]))
    monkeypatch.setattr(installer, "_run_dependency_preparation", lambda *_args, **_kwargs: (0, child_payload))
    monkeypatch.setattr(
        installer,
        "_dependency_receipt",
        lambda *_args: {"run_state": "completed", "target_module_manifest_sha256": "b" * 64},
    )
    _stub_clean_git(monkeypatch, config)
    real_run_stage = installer._run_stage

    def complete_remaining_stages(stage_config, current_state, commands, name, **kwargs):
        if name == "dependencies":
            return real_run_stage(stage_config, current_state, commands, name, **kwargs)
        current_state["stages"][name] = {"status": "COMPLETED", "code": None}

    monkeypatch.setattr(installer, "_run_stage", complete_remaining_stages)
    monkeypatch.setattr(installer, "_summary", lambda _state: {"status": "TESTED"})

    installer.resume(SimpleNamespace(retry_failed_dependencies=True))

    assert writes[0] == "RUNNING"
    assert "PENDING" not in writes
    assert state["stages"]["dependencies"] == {"status": "COMPLETED", "code": None}


def test_retry_checkpoint_transition_failure_keeps_default_resume_fail_closed(monkeypatch, tmp_path):
    config, state = _dependency_retry_fixture(tmp_path)
    writes = 0
    child_calls = []

    def write_state(*_args, **_kwargs):
        nonlocal writes
        writes += 1
        if writes == 1:
            raise installer.InstallError("CHECKPOINT_PERSIST_FAILED")

    monkeypatch.setattr(installer, "_validate_configuration", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(installer, "_read_state", lambda _path: state)
    monkeypatch.setattr(installer, "_match_state", lambda *_args: None)
    monkeypatch.setattr(installer, "_verify_completed", lambda *_args: None)
    monkeypatch.setattr(installer, "_commands", lambda *_args: {"dependencies": ["python", "-B", "prepare"]})
    monkeypatch.setattr(installer, "_write_state", write_state)
    monkeypatch.setattr(
        installer,
        "_run_dependency_preparation",
        lambda *_args, **_kwargs: child_calls.append("called") or (0, {}),
    )
    _stub_clean_git(monkeypatch, config)

    with pytest.raises(installer.InstallError, match="CHECKPOINT_PERSIST_FAILED"):
        installer.resume(SimpleNamespace(retry_failed_dependencies=True))

    assert child_calls == []
    assert state["stages"]["dependencies"] == {"status": "FAILED", "code": "CHECKPOINT_PERSIST_FAILED"}
    _start_path, result_path = installer._dependency_retry_paths(config, 1)
    assert json.loads(result_path.read_text(encoding="utf-8"))["status"] == "FAILED"

    with pytest.raises(installer.InstallError, match="INCOMPLETE_STAGE_PRESERVED_FOR_INSPECTION"):
        installer.resume(SimpleNamespace(retry_failed_dependencies=False))
    assert child_calls == []


@pytest.mark.parametrize("mutation,expected", [
    ("later_stage", "INCOMPLETE_STAGE_PRESERVED_FOR_INSPECTION"),
    ("target_dirty", "DEPENDENCY_TARGET_NOT_CLEAN"),
    ("lock_changed", "DEPENDENCY_LOCK_PIN_CHANGED"),
    ("manifest_changed", "DEPENDENCY_MANIFEST_PIN_CHANGED"),
    ("ignored_file", "DEPENDENCY_TARGET_NOT_CLEAN"),
    ("workspace_exists", "INCOMPLETE_STAGE_PRESERVED_FOR_INSPECTION"),
    ("source_head", "SOURCE_TARGET_HEAD_MISMATCH"),
])
def test_dependency_retry_rejects_unsafe_stage_or_pin_changes(monkeypatch, tmp_path, mutation, expected):
    config, state = _dependency_retry_fixture(tmp_path)
    _stub_clean_git(monkeypatch, config)
    if mutation == "later_stage":
        state["stages"]["workspace"] = {"status": "FAILED", "code": "WORKSPACE_CREATE_FAILED"}
    elif mutation == "lock_changed":
        (config["dependency_target"] / "05_rag-engine" / "uv.lock").write_text("changed\n", encoding="utf-8")
    elif mutation == "manifest_changed":
        (config["dependency_target"] / "MODULES.md").write_text("changed\n", encoding="utf-8")
    elif mutation == "ignored_file":
        monkeypatch.setattr(installer, "_git_output", lambda *_args, **_kwargs: "!! 13_deployment/__pycache__/")
    elif mutation == "workspace_exists":
        config["workspace"].mkdir()
    elif mutation == "source_head":
        monkeypatch.setattr(
            installer,
            "_validate_git_root",
            lambda root, *, require_clean: ("c" * 40) if root == config["dependency_target"] else config["source_head"],
        )
    else:
        def dirty(root, *, require_clean):
            if root == config["dependency_target"] and require_clean:
                raise installer.InstallError("DEPENDENCY_TARGET_NOT_CLEAN")
            return config["source_head"]
        monkeypatch.setattr(installer, "_validate_git_root", dirty)
    with pytest.raises(installer.InstallError, match=expected):
        installer._validate_dependency_retry(config, state)


def test_dependency_retry_still_requires_a_complete_receipt(monkeypatch, tmp_path):
    state = {"stages": {name: {"status": "PENDING", "code": None} for name in installer.STAGE_NAMES}}
    config = {"state_path": tmp_path / "state.json", "state_temp_path": tmp_path / "state.json.tmp"}
    monkeypatch.setattr(installer, "_write_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        installer,
        "_run_dependency_preparation",
        lambda *_args, **_kwargs: (0, {"schema_version": "school-dependency-preparation.v1", "mode": "install", "run_state": "completed"}),
    )
    monkeypatch.setattr(installer, "_dependency_receipt", lambda *_args: (_ for _ in ()).throw(installer.InstallError("DEPENDENCY_RECEIPT_UNAVAILABLE")))

    with pytest.raises(installer.InstallError, match="DEPENDENCY_RECEIPT_UNAVAILABLE"):
        installer._run_stage(config, state, {"dependencies": ["python", "-B"]}, "dependencies")
    assert state["stages"]["dependencies"] == {"status": "FAILED", "code": "DEPENDENCY_RECEIPT_UNAVAILABLE"}


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
