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


def _write_synthetic_marker(workspace, *, port=3330):
    (workspace / "workspace.json").write_text(json.dumps({
        "schema_version": "psynova.synthetic-workspace.v1",
        "project": "StudentMentalHealthAI",
        "workspace_id": "a" * 32,
        "state": "READY_FOR_MIGRATION",
        "host": "127.0.0.1",
        "port": port,
        "database": "smhai_school_demo",
        "synthetic_only": True,
    }), encoding="utf-8")


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
    _write_synthetic_marker(workspace)

    assert qa.validate_workspace_path(workspace, repo) == workspace.resolve()

    with pytest.raises(qa.HarnessError):
        qa.validate_workspace_path(repo / qa.WORKSPACE_PREFIX, repo)
    with pytest.raises(qa.HarnessError):
        qa.validate_workspace_path(tmp_path / "unrelated", repo)


def test_custom_workspace_requires_explicit_distinct_loopback_ports_and_marker(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    workspace = tmp_path / ".StudentMentalHealthAI-school-install-test"
    workspace.mkdir()
    _write_synthetic_marker(workspace)

    assert qa.validate_workspace_path(workspace, repo, allow_custom_name=True) == workspace.resolve()
    assert qa._loopback_urls(workspace, 8104, 4194)[2:] == (
        "http://127.0.0.1:4194", "http://127.0.0.1:8104",
    )
    with pytest.raises(qa.HarnessError):
        qa._loopback_urls(workspace, None, None)
    with pytest.raises(qa.HarnessError):
        qa._loopback_urls(workspace, 8104, 8104)
    with pytest.raises(qa.HarnessError):
        qa._loopback_urls(workspace, 3330, 4194)


def test_custom_workspace_marker_must_be_synthetic_loopback_and_registered_schema(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    workspace = tmp_path / ".StudentMentalHealthAI-school-install-test"
    workspace.mkdir()
    _write_synthetic_marker(workspace)
    marker_path = workspace / "workspace.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["synthetic_only"] = False
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    with pytest.raises(qa.HarnessError):
        qa.validate_workspace_path(workspace, repo, allow_custom_name=True)


def test_owner_gate_requires_current_schema_and_live_owned_app_services():
    status = {
        "status": "RUNNING",
        "manifest_is_current_revision": True,
        "database": "VERIFIED",
        "services": {
            "backend": {"port": 8104, "owned_process": True, "listener": "OWNED", "ready": True},
            "frontend": {"port": 4194, "owned_process": True, "listener": "OWNED", "ready": True},
        },
    }
    assert qa.verify_owned_application_services(status, backend_port=8104, frontend_port=4194)
    status["services"]["frontend"]["listener"] = "MISSING_OR_FOREIGN"
    assert not qa.verify_owned_application_services(status, backend_port=8104, frontend_port=4194)


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
            *[
                {"slot": slot, "status": "FAIL", "error": secret}
                for slot in ("alpha.psychological_specialist", "alpha.admin")
            ],
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


def test_auth_sanitizer_fails_closed_on_duplicate_missing_unknown_or_malformed_slots(tmp_path):
    artifact_dir = tmp_path / "browser-qa"
    artifact_dir.mkdir()
    for slot in qa.ACCOUNT_SLOTS:
        (artifact_dir / f"{slot.replace('.', '-')}.png").write_bytes(b"masked synthetic screenshot")

    passing = [
        {"slot": slot, "status": "PASS", "stages": _passed_stages()}
        for slot in qa.ACCOUNT_SLOTS
    ]
    student = next(item for item in passing if item["slot"] == "alpha.student")
    fail_then_pass = [
        {**student, "status": "FAIL", "stages": {**_passed_stages(), "forbidden_route": "FAIL"}},
        *[item for item in passing if item["slot"] != "alpha.student"],
        student,
    ]
    pass_then_fail = [
        *passing,
        {**student, "status": "FAIL", "stages": {**_passed_stages(), "forbidden_route": "FAIL"}},
    ]
    unknown = [*passing, {"slot": "beta.student", "status": "PASS", "stages": _passed_stages()}]
    missing = [item for item in passing if item["slot"] != "alpha.student"]
    malformed = [*passing[:-1], {"slot": [], "status": "PASS", "stages": _passed_stages()}]

    for children in (fail_then_pass, pass_then_fail, unknown, missing, malformed):
        result = qa.sanitize_child_output(
            json.dumps({"results": children}), artifact_dir=artifact_dir, child_exit_code=0,
        )
        assert result["status"] == "FAIL"
        assert result["runner_status"] == "FAIL"
        assert result["pass_count"] == 0
        assert result["fail_count"] == len(qa.ACCOUNT_SLOTS)
        assert all(item["status"] == "FAIL" for item in result["results"])


def test_auth_sanitizer_retains_only_allowlisted_browser_diagnostics(tmp_path):
    artifact_dir = tmp_path / "browser-qa"
    artifact_dir.mkdir()
    (artifact_dir / "alpha-student.png").write_bytes(b"masked synthetic screenshot")
    children = []
    for slot in qa.ACCOUNT_SLOTS:
        stages = _passed_stages()
        item = {"slot": slot, "status": "PASS", "stages": stages}
        if slot == "alpha.student":
            stages["forbidden_route"] = "FAIL"
            item["status"] = "FAIL"
            item["diagnostic"] = {
                "stage": "forbidden_route",
                "substage": "role_redirect",
                "code": "ROLE_REDIRECT_NOT_COMPLETED",
                "current_path": "admin_overview",
                "message": "sensitive detail must not pass through",
            }
        elif slot == "alpha.psychological_specialist":
            stages["forbidden_route"] = "FAIL"
            item["status"] = "FAIL"
            item["diagnostic"] = {
                "stage": "student_history",
                "substage": "metadata_response",
                "code": "DTO_INVALID",
                "current_path": "student_home",
                "message": "sensitive detail must not pass through",
            }
        children.append(item)

    result = qa.sanitize_child_output(
        json.dumps({"results": children}), artifact_dir=artifact_dir, child_exit_code=0
    )

    student = result["results"][0]
    assert student["stages"]["screenshot"] == "PASS"
    assert student["stages"]["forbidden_route"] == "FAIL"
    assert student["failure"] == {
        "stage": "forbidden_route",
        "substage": "role_redirect",
        "code": "ROLE_REDIRECT_NOT_COMPLETED",
        "current_path": "admin_overview",
    }
    specialist = result["results"][2]
    assert specialist["failure"] == {
        "stage": "student_history",
        "substage": "metadata_response",
        "code": "DTO_INVALID",
        "current_path": "student_home",
    }
    assert "message" not in json.dumps(result)


def test_student_history_request_diagnostics_remain_fixed_and_allowlisted():
    for code in (
        "REQUEST_NOT_STARTED",
        "REQUEST_FAILED",
        "REQUEST_PENDING_PROBE_200",
        "REQUEST_PENDING_PROBE_FAILED",
        "REQUEST_PENDING_PROBE_EVALUATION_FAILED",
    ):
        diagnostic = qa._sanitize_auth_diagnostic({
            "stage": "student_history",
            "substage": "metadata_response",
            "code": code,
            "current_path": "student_history",
        })
        assert diagnostic == {
            "stage": "student_history",
            "substage": "metadata_response",
            "code": code,
            "current_path": "student_history",
        }
    for code in (
        "ASSESSMENT_LIBRARY_NOT_VISIBLE",
        "ASSESSMENT_LOADING_DID_NOT_SETTLE",
        "CARD_COUNT_MISMATCH",
    ):
        assert qa._sanitize_auth_diagnostic({
            "stage": "student_history",
            "substage": "metadata_render",
            "code": code,
            "current_path": "student_history",
        }) == {
            "stage": "student_history",
            "substage": "metadata_render",
            "code": code,
            "current_path": "student_history",
        }
    diagnostic = qa._sanitize_auth_diagnostic({
        "stage": "student_history",
        "substage": "metadata_response",
        "code": "RESPONSE_NOT_RECEIVED",
        "current_path": "student_home",
        "checkpoint": "response_wait_completed",
        "message": "discarded",
    })
    assert diagnostic == {
        "stage": "student_history",
        "substage": "metadata_response",
        "code": "RESPONSE_NOT_RECEIVED",
        "current_path": "student_home",
        "checkpoint": "response_wait_completed",
    }
    assert qa._sanitize_auth_diagnostic({
        "stage": "student_history",
        "substage": "route",
        "code": "ROUTE_NOT_REACHED",
        "current_path": "student_home",
    }) == {
        "stage": "student_history",
        "substage": "route",
        "code": "ROUTE_NOT_REACHED",
        "current_path": "student_home",
    }
    for code in ("RESPONSE_NOT_RECEIVED", "HTTP_STATUS", "ENVELOPE_INVALID"):
        assert qa._sanitize_auth_diagnostic({
            "stage": "student_feedback",
            "substage": "feedback_request",
            "code": code,
            "current_path": "student_feedback",
        }) == {
            "stage": "student_feedback",
            "substage": "feedback_request",
            "code": code,
            "current_path": "student_feedback",
        }


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

    # CAT completion occurs after the student has left the initial start phase.
    child["stages"] = {**_passed_task_stages(), "cat_completed": "FAIL"}
    child["failure"] = {
        "stage": "cat_completed",
        "error_class": "TimeoutError",
        "diagnostics": {"cat_substage": "complete", "question_text": secret},
    }
    completed = qa.sanitize_task_child_output(
        json.dumps(child), artifact_dir=tmp_path, child_exit_code=2
    )
    assert completed["failure"]["cat_substage"] == "complete"
    assert "question_text" not in completed["failure"]
    assert secret not in json.dumps(completed)

    child["failure"] = {
        "stage": "cat_completed",
        "error_class": "TimeoutError",
        "diagnostics": "invalid diagnostics shape",
        "cat_substage": "progress",
    }
    malformed_nested = qa.sanitize_task_child_output(
        json.dumps(child), artifact_dir=tmp_path, child_exit_code=2
    )
    assert "cat_substage" not in malformed_nested["failure"]

    # Older Node output flattened diagnostics into failure; retain the safe fields.
    child["failure"] = {
        "stage": "cat_completed",
        "error_class": "TimeoutError",
        "cat_substage": "progress",
        "route_mode": "student_assessment_session",
        "selectors": {key: key == "assessment_loading" for key in qa.FAILURE_SELECTOR_KEYS},
        "responses": [{
            "method": "POST",
            "status": 200,
            "endpoint": "/api/v1/assessments/{assessment_id}/responses",
            "answer": secret,
            "url": f"/api/v1/assessments/{secret}/responses",
        }],
        "answer": secret,
    }
    legacy_flat = qa.sanitize_task_child_output(
        json.dumps(child), artifact_dir=tmp_path, child_exit_code=2
    )
    assert legacy_flat["failure"]["cat_substage"] == "progress"
    assert legacy_flat["failure"]["responses"] == [{
        "method": "POST",
        "status": 200,
        "endpoint": "/api/v1/assessments/{assessment_id}/responses",
    }]
    assert secret not in json.dumps(legacy_flat)

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


@pytest.mark.parametrize(
    "screenshots",
    [
        [*qa.TASK_SCREENSHOTS[:-1], qa.TASK_SCREENSHOTS[0]],
        [*qa.TASK_SCREENSHOTS[:-1], "unknown.png"],
        [*qa.TASK_SCREENSHOTS[:-1], []],
    ],
)
def test_task_sanitizer_fails_closed_on_duplicate_unknown_or_malformed_screenshot_slots(tmp_path, screenshots):
    for name in qa.TASK_SCREENSHOTS:
        (tmp_path / name).write_bytes(b"masked synthetic screenshot")
    child = {
        "workflow": "school-tasks", "status": "PASS",
        "stages": _passed_task_stages(), "screenshots": screenshots,
    }
    result = qa.sanitize_task_child_output(
        json.dumps(child), artifact_dir=tmp_path, child_exit_code=0,
    )
    assert result["status"] == "FAIL"
    assert result["failure_class"] == "BrowserWorkflowFailed"
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


def test_node_environment_discovers_local_playwright_cache_only_for_current_process(monkeypatch, tmp_path):
    monkeypatch.setattr(qa.os, "environ", {"PATH": "node-path", "SystemRoot": "windows-root"})
    monkeypatch.setattr(qa.Path, "home", lambda: tmp_path)
    original_is_dir = qa.Path.is_dir

    def is_dir_without_shared_cache(path):
        if str(path).casefold() == "d:\\dev\\tools\\playwright-browsers":
            return False
        return original_is_dir(path)

    monkeypatch.setattr(qa.Path, "is_dir", is_dir_without_shared_cache)
    cache = tmp_path / "AppData" / "Local" / "ms-playwright"
    cache.mkdir(parents=True)
    environment = qa.safe_node_environment()

    assert environment == {
        "PATH": "node-path",
        "SystemRoot": "windows-root",
        "PLAYWRIGHT_BROWSERS_PATH": str(cache),
    }


def test_browser_prerequisite_diagnostic_is_closed_and_contains_no_paths(tmp_path):
    secret = "browser-path-secret-sentinel"
    children = [
        {"slot": slot, "status": "FAIL", "stages": {}}
        for slot in qa.ACCOUNT_SLOTS
    ]
    result = qa.sanitize_child_output(
        json.dumps({
            "results": children,
            "browser_prerequisite": {
                "status": "FAIL", "code": "HEADLESS_SHELL_EXECUTABLE_MISSING",
                "path": secret,
            },
            "unexpected": secret,
        }),
        artifact_dir=tmp_path,
        child_exit_code=2,
    )

    assert result["browser_prerequisite"] == {
        "status": "FAIL", "code": "HEADLESS_SHELL_EXECUTABLE_MISSING",
    }
    assert secret not in json.dumps(result)

    malformed = qa.sanitize_child_output(
        json.dumps({
            "results": children,
            "browser_prerequisite": {"status": "PASS", "code": "HEADLESS_SHELL_EXECUTABLE_MISSING"},
        }),
        artifact_dir=tmp_path,
        child_exit_code=2,
    )
    assert malformed["browser_prerequisite"] == {
        "status": "FAIL", "code": "INVALID_DIAGNOSTIC",
    }

    launch_failure = qa.sanitize_child_output(
        json.dumps({
            "results": children,
            "browser_prerequisite": {"status": "PASS", "code": "READY"},
            "browser_launch_failure_code": secret,
        }),
        artifact_dir=tmp_path,
        child_exit_code=2,
    )
    assert launch_failure["browser_launch_failure_code"] == "INVALID_DIAGNOSTIC"
    assert secret not in json.dumps(launch_failure)


def test_sanitized_report_is_persisted_without_raw_child_output(tmp_path):
    artifact_dir = tmp_path / "exclusive-run"
    artifact_dir.mkdir()
    secret = "raw-child-secret-sentinel"
    safe = qa.sanitize_child_output(
        json.dumps({
            "password": secret,
            "results": [
                {"slot": slot, "status": "FAIL", "stages": {}, "exception": secret}
                for slot in qa.ACCOUNT_SLOTS
            ],
            "browser_prerequisite": {"status": "PASS", "code": "READY"},
        }),
        artifact_dir=artifact_dir,
        child_exit_code=0,
    )

    result = qa.persist_sanitized_report(artifact_dir, "auth", safe)
    report_path = Path(result["evidence_report_path"])
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert result["evidence_report_status"] == "PERSISTED"
    assert report["schema_version"] == "psynova.school-browser-qa-report.v1"
    assert report["workflow"] == "auth"
    assert report["result"] == result
    assert secret not in report_path.read_text(encoding="utf-8")


def test_sanitized_report_collision_fails_closed_without_overwriting(tmp_path):
    artifact_dir = tmp_path / "exclusive-run"
    artifact_dir.mkdir()
    report_path = artifact_dir / "sanitized-report.json"
    report_path.write_text("preserve-existing", encoding="utf-8")

    result = qa.persist_sanitized_report(artifact_dir, "auth", qa._result_shell())

    assert report_path.read_text(encoding="utf-8") == "preserve-existing"
    assert result["status"] == "FAIL"
    assert result["failure_class"] == "SafeReportPersistenceFailed"
    assert result["evidence_report_status"] == "UNAVAILABLE"
    assert "evidence_report_path" not in result
