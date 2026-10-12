import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_browser_qa as qa


def _passed_stages():
    return {key: "PASS" for key in qa.STAGE_KEYS}


def _passed_task_stages():
    return {key: "PASS" for key in qa.TASK_STAGE_KEYS}


def test_workflow_dispatch_preserves_auth_default_and_rejects_unknown():
    assert qa._node_script_for_workflow("auth") == qa.NODE_SCRIPT
    assert qa._node_script_for_workflow("school-tasks") == qa.TASK_NODE_SCRIPT
    with pytest.raises(qa.HarnessError):
        qa._node_script_for_workflow("unknown")
    result = qa.run(Path("D:/missing-workspace"), "unknown")
    assert result["stage"] == "workflow_gate"
    assert result["failure_class"] == "HarnessError"


def test_workspace_must_be_owned_external_path(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    workspace = tmp_path / qa.WORKSPACE_PREFIX
    workspace.mkdir()

    assert qa.validate_workspace_path(workspace, repo) == workspace.resolve()

    with pytest.raises(qa.HarnessError):
        qa.validate_workspace_path(repo / qa.WORKSPACE_PREFIX, repo)
    with pytest.raises(qa.HarnessError):
        qa.validate_workspace_path(tmp_path / "unrelated", repo)


def test_only_registered_alpha_credential_slots_are_forwarded():
    accounts = {
        slot: [f"SYNTHETIC_{slot.replace('.', '_')}", "p" * 32]
        for slot in qa.ACCOUNT_SLOTS
    }
    accounts["beta.student"] = ["SYNTHETIC_beta_student", "p" * 32]

    result = qa.validate_credentials({
        "recipe_version": "school-contexts-v1",
        "credentials": accounts,
    })

    assert set(result) == set(qa.ACCOUNT_SLOTS)
    assert "beta.student" not in result


def test_school_admin_frontend_and_backend_roles_are_mapped_explicitly():
    frontend_role, api_role, expected_path = qa.ACCOUNT_SLOTS["alpha.admin"]

    assert frontend_role == "SCHOOL_ADMIN"
    assert api_role == "ADMIN"
    assert expected_path == "/admin/overview"


@pytest.mark.parametrize(
    "private",
    [
        None,
        {"recipe_version": "other", "credentials": {}},
        {"recipe_version": "school-contexts-v1", "credentials": []},
        {
            "recipe_version": "school-contexts-v1",
            "credentials": {"alpha.student": ["real-name-sentinel", "p" * 32]},
        },
    ],
)
def test_invalid_or_incomplete_credentials_fail_closed(private):
    with pytest.raises(qa.HarnessError):
        qa.validate_credentials(private)


def test_sanitizer_drops_credentials_raw_errors_and_untrusted_paths(tmp_path):
    secret = "password-sentinel-never-output"
    artifact_dir = tmp_path / "browser-qa"
    artifact_dir.mkdir()
    screenshot = artifact_dir / "alpha-student.png"
    screenshot.write_bytes(b"synthetic screenshot marker")
    child = {
        "status": "PASS",
        "username": secret,
        "password": secret,
        "exception": f"database failed with {secret}",
        "results": [
            {
                "slot": "alpha.student",
                "status": "PASS",
                "expected_role": "SCHOOL_ADMIN",
                "expected_path": "/exfiltrate",
                "screenshot": f"D:/private/{secret}.png",
                "stages": _passed_stages(),
                "error": secret,
            },
            {
                "slot": "alpha.teacher",
                "status": "FAIL",
                "failure_class": f"ValueError:{secret}",
                "error": secret,
            },
        ],
    }

    result = qa.sanitize_child_output(
        json.dumps(child), artifact_dir=artifact_dir, child_exit_code=0
    )
    rendered = json.dumps(result)

    assert secret not in rendered
    assert result["results"][0]["expected_role"] == "STUDENT"
    assert result["results"][0]["expected_api_role"] == "STUDENT"
    assert result["results"][0]["expected_path"] == "/student/home"
    assert result["results"][0]["screenshot"] == str(screenshot)
    assert result["results"][1]["failure_class"] == "BrowserCheckFailed"
    assert "error" not in result["results"][1]


def test_child_pass_without_expected_screenshot_is_reported_failed(tmp_path):
    result = qa.sanitize_child_output(
        json.dumps({
            "results": [
                {"slot": slot, "status": "PASS"}
                for slot in qa.ACCOUNT_SLOTS
            ]
        }),
        artifact_dir=tmp_path,
        child_exit_code=0,
    )

    assert result["status"] == "FAIL"
    assert result["pass_count"] == 0
    assert result["fail_count"] == len(qa.ACCOUNT_SLOTS)


def test_error_redaction_discards_exception_message():
    secret = "credential-error-sentinel"
    result = qa.safe_error_result("runtime_gate", RuntimeError(secret))

    assert secret not in json.dumps(result)
    assert result == {
        "status": "FAIL",
        "stage": "runtime_gate",
        "failure_class": "HarnessError",
        "slot_count": len(qa.ACCOUNT_SLOTS),
        "pass_count": 0,
        "fail_count": len(qa.ACCOUNT_SLOTS),
    }


@pytest.mark.parametrize(
    "stages",
    [
        {},
        {key: "PASS" for key in qa.STAGE_KEYS[:-1]},
        {**_passed_stages(), "unexpected_stage": "PASS"},
        {**_passed_stages(), "auth_me": "UNKNOWN"},
    ],
)
def test_sanitizer_requires_exact_complete_stage_allowlist(tmp_path, stages):
    artifact_dir = tmp_path / "browser-qa"
    artifact_dir.mkdir()
    (artifact_dir / "alpha-student.png").write_bytes(b"marker")
    child = {"results": [{"slot": "alpha.student", "status": "PASS", "stages": stages}]}

    result = qa.sanitize_child_output(
        json.dumps(child), artifact_dir=artifact_dir, child_exit_code=0
    )

    assert result["results"][0]["status"] == "FAIL"
    assert result["results"][0]["failure_class"] == "BrowserCheckFailed"
    assert result["pass_count"] == 0


def test_sanitizer_fails_nonzero_child_exit_even_when_all_evidence_passes(tmp_path):
    artifact_dir = tmp_path / "browser-qa"
    artifact_dir.mkdir()
    results = []
    for slot in qa.ACCOUNT_SLOTS:
        (artifact_dir / f"{slot.replace('.', '-')}.png").write_bytes(b"marker")
        results.append({"slot": slot, "status": "PASS", "stages": _passed_stages()})

    result = qa.sanitize_child_output(
        json.dumps({"status": "PASS", "results": results}),
        artifact_dir=artifact_dir,
        child_exit_code=17,
    )

    assert result["status"] == "FAIL"
    assert result["runner_status"] == "FAIL"
    assert result["pass_count"] == 0
    assert result["fail_count"] == len(qa.ACCOUNT_SLOTS)


def test_task_sanitizer_requires_all_stages_and_real_screenshot_artifacts(tmp_path):
    for name in qa.TASK_SCREENSHOTS:
        (tmp_path / name).write_bytes(b"synthetic screenshot marker")
    secret = "password-sentinel-never-output"
    child = {
        "workflow": "school-tasks",
        "status": "PASS",
        "stages": _passed_task_stages(),
        "screenshots": list(qa.TASK_SCREENSHOTS),
        "username": secret,
        "api_response": {"assessment_id": "private", "risk": "private"},
        "error": secret,
    }

    result = qa.sanitize_task_child_output(
        json.dumps(child), artifact_dir=tmp_path, child_exit_code=0
    )
    assert result["status"] == "PASS"
    assert set(result["stages"]) == set(qa.TASK_STAGE_KEYS)
    assert all(stage == "PASS" for stage in result["stages"].values())
    assert secret not in json.dumps(result)
    assert "api_response" not in result
    assert "assessment_id" not in json.dumps(result)

    missing_stage = {**child, "stages": {**_passed_task_stages(), "admin_revoke": "FAIL"}}
    failed = qa.sanitize_task_child_output(
        json.dumps(missing_stage), artifact_dir=tmp_path, child_exit_code=0
    )
    assert failed["status"] == "FAIL"
    assert failed["stages"]["admin_revoke"] == "FAIL"
    assert failed["stages"]["class_created"] == "PASS"
    assert "screenshots" not in failed

    missing_stage = {**child, "stages": _passed_task_stages()}
    del missing_stage["stages"]["admin_revoke"]
    incomplete = qa.sanitize_task_child_output(
        json.dumps(missing_stage), artifact_dir=tmp_path, child_exit_code=0
    )
    assert incomplete["status"] == "FAIL"
    assert incomplete["stages"]["admin_revoke"] == "FAIL"
    assert incomplete["stages"]["class_created"] == "PASS"

    (tmp_path / qa.TASK_SCREENSHOTS[-1]).unlink()
    missing_screenshot = qa.sanitize_task_child_output(
        json.dumps(child), artifact_dir=tmp_path, child_exit_code=0
    )
    assert missing_screenshot["status"] == "FAIL"


def test_task_failure_diagnostic_is_allowlisted_and_may_include_fixed_masked_screenshot(tmp_path):
    failure_screenshot = tmp_path / qa.FAILURE_SCREENSHOT_NAME
    failure_screenshot.write_bytes(b"masked screenshot marker")
    secret = "private exception message sentinel"
    child = {
        "workflow": "school-tasks",
        "status": "FAIL",
        "stages": {**_passed_task_stages(), "cat_started": "FAIL"},
        "failure": {
            "stage": "cat_started",
            "error_class": "WorkflowResponseError",
            "screenshot": qa.FAILURE_SCREENSHOT_NAME,
            "message": secret,
            "password": secret,
            "diagnostics": {
                "route_mode": "student_assessment_session",
                "cat_substage": "question_ready",
                "selectors": {key: key == "assessment_loading" for key in qa.FAILURE_SELECTOR_KEYS},
                "responses": [{
                    "method": "GET", "status": 200,
                    "endpoint": "/api/v1/assessments/{assessment_id}/state",
                    "url": f"/api/v1/assessments/{secret}/state?token={secret}",
                    "headers": {"Authorization": secret}, "body": secret,
                }],
                "raw_path": f"/student/assessment/{secret}",
            },
        },
    }
    result = qa.sanitize_task_child_output(
        json.dumps(child), artifact_dir=tmp_path, child_exit_code=2
    )
    assert result["failure"] == {
        "stage": "cat_started",
        "error_class": "WorkflowResponseError",
        "screenshot": str(failure_screenshot),
        "route_mode": "student_assessment_session",
        "cat_substage": "question_ready",
        "selectors": {
            key: key == "assessment_loading" for key in qa.FAILURE_SELECTOR_KEYS
        },
        "responses": [{
            "method": "GET", "status": 200,
            "endpoint": "/api/v1/assessments/{assessment_id}/state",
        }],
    }
    assert secret not in json.dumps(result)

    child["failure"]["diagnostics"]["cat_substage"] = "question_ready " + secret
    unsafe_substage = qa.sanitize_task_child_output(
        json.dumps(child), artifact_dir=tmp_path, child_exit_code=2
    )
    assert "cat_substage" not in unsafe_substage["failure"]
    assert secret not in json.dumps(unsafe_substage)

    child["failure"]["stage"] = "not-an-allowlisted-stage"
    invalid = qa.sanitize_task_child_output(
        json.dumps(child), artifact_dir=tmp_path, child_exit_code=2
    )
    assert "failure" not in invalid


def test_task_sanitizer_rejects_unknown_workflow_and_untrusted_screenshot_path(tmp_path):
    child = {
        "workflow": "other",
        "status": "PASS",
        "stages": _passed_task_stages(),
        "screenshots": ["../private.png", *qa.TASK_SCREENSHOTS[1:]],
    }
    result = qa.sanitize_task_child_output(
        json.dumps(child), artifact_dir=tmp_path, child_exit_code=0
    )
    assert result["status"] == "FAIL"
    assert result["failure_class"] == "BrowserWorkflowFailed"


def test_artifact_runs_get_unique_exclusive_subdirectories_and_preserve_old_files(tmp_path):
    workspace = tmp_path / qa.WORKSPACE_PREFIX
    workspace.mkdir()

    first = qa.create_artifact_run_dir(workspace)
    old_screenshot = first / "alpha-student.png"
    old_screenshot.write_bytes(b"preserve")
    second = qa.create_artifact_run_dir(workspace)

    assert first.parent == second.parent == workspace / "browser-qa"
    assert first != second
    assert old_screenshot.read_bytes() == b"preserve"


def test_node_environment_excludes_database_and_application_secrets():
    environment = qa.safe_node_environment({
        "PATH": "node-path",
        "SystemRoot": "windows-root",
        "DB_PASSWORD": "db-secret-sentinel",
        "SMHAI_SCHOOL_CSRF_SECRET": "csrf-secret-sentinel",
        "DATABASE_URL": "url-secret-sentinel",
        "MYSQL_PWD": "mysql-secret-sentinel",
        "API_TOKEN": "unrelated-secret-sentinel",
    })

    assert environment == {"PATH": "node-path", "SystemRoot": "windows-root"}
