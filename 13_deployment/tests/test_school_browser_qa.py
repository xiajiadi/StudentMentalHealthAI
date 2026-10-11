import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_browser_qa as qa


def _passed_stages():
    return {key: "PASS" for key in qa.STAGE_KEYS}


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
