import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_professional_review_browser_qa as qa


def _refs():
    return {
        "class_ref": "CLASS_" + "a" * 32,
        "task_ref": "TASK_" + "b" * 32,
        "enrollment_ref": "ENROLL_" + "c" * 32,
    }


def _private():
    return {
        "recipe_version": "school-contexts-v1",
        "credentials": {
            "alpha.admin": ["SYNTHETIC_ALPHA_ADMIN", "a" * 24],
            "alpha.psychological_specialist": ["SYNTHETIC_ALPHA_SPECIALIST", "s" * 24],
        },
    }


def _passed_ui_stages():
    return {key: "PASS" for key in qa.UI_STAGE_KEYS}


def test_setup_requires_exact_native_review_scope_checks_and_opaque_refs():
    setup = _refs()
    assert qa._validate_setup(setup) == setup

    setup_with_duplicate = {**setup, "task_ref": setup["class_ref"]}
    with pytest.raises(qa.HarnessError):
        qa._validate_setup(setup_with_duplicate)

    malformed = {**setup, "enrollment_ref": "student@example.test"}
    with pytest.raises(qa.HarnessError):
        qa._validate_setup(malformed)


def test_setup_loader_accepts_only_the_root_owned_passed_setup_artifact(tmp_path):
    workspace = tmp_path / "workspace"
    logs = workspace / "logs"
    logs.mkdir(parents=True)
    setup_path = logs / f"professional-review-browser-setup-{'a' * 32}.json"
    evidence = {
        "status": "PASS",
        "scope": "NATIVE_SYNTHETIC_PROFESSIONAL_REVIEW",
        "checks": {
            "assignment_replay_csrf_cross_school": "PASS",
            "real_cat_binding_incomplete_denial": "PASS",
        },
        **_refs(),
    }
    setup_path.write_text(json.dumps(evidence), encoding="utf-8")
    assert qa._read_setup(setup_path, workspace) == _refs()

    evidence["checks"]["real_cat_binding_incomplete_denial"] = "FAIL"
    setup_path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(qa.HarnessError):
        qa._read_setup(setup_path, workspace)

    wrong_name = logs / "setup.json"
    wrong_name.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(qa.HarnessError):
        qa._read_setup(wrong_name, workspace)


def test_only_the_two_expected_synthetic_login_credentials_are_extracted_and_cleared():
    private = _private()
    credentials = qa._review_credentials(private)
    assert set(credentials) == {"alpha.admin", "alpha.psychological_specialist"}
    assert credentials["alpha.admin"]["username"] == "SYNTHETIC_ALPHA_ADMIN"
    assert (
        credentials["alpha.psychological_specialist"]["username"]
        == "SYNTHETIC_ALPHA_SPECIALIST"
    )
    qa._clear_private(private)
    assert private == {}


def test_harness_imports_callable_owned_workspace_entrypoints():
    for name in (
        "_verified_workspace",
        "_inspect_application_listeners",
        "_reject_reparse_path",
        "_clear_private_account_material",
        "_safe_node_environment",
    ):
        assert callable(getattr(qa.owned_workspace, name, None)), name


@pytest.mark.parametrize(
    "slot,value",
    [
        ("alpha.admin", ["admin@example.test", "p" * 24]),
        ("alpha.psychological_specialist", ["SYNTHETIC_SPECIALIST", "short"]),
        ("alpha.psychological_specialist", ["SYNTHETIC_SPECIALIST", 123]),
    ],
)
def test_invalid_role_credentials_fail_closed(slot, value):
    private = _private()
    private["credentials"][slot] = value
    with pytest.raises(qa.HarnessError):
        qa._review_credentials(private)


def test_child_pass_requires_exact_stage_registry_and_all_masked_artifacts(tmp_path):
    for name in qa.SCREENSHOTS:
        (tmp_path / name).write_bytes(b"synthetic masked screenshot marker")
    child = {
        "workflow": "school-professional-review",
        "status": "PASS",
        "stages": _passed_ui_stages(),
        "screenshots": list(qa.SCREENSHOTS),
        "response_body": "must not survive sanitization",
    }

    result = qa._sanitize_child(json.dumps(child), 0, tmp_path)

    assert result["runner_status"] == "PASS"
    assert result["status"] == "FAIL"  # wrapper preflight has not been merged.
    assert result["stages"]["desktop_screenshot"] == "PASS"
    assert result["stages"]["mobile_screenshot"] == "PASS"
    assert "response_body" not in result

    missing_stage = dict(child)
    missing_stage["stages"] = dict(child["stages"])
    del missing_stage["stages"]["decision_saved"]
    assert (
        qa._sanitize_child(json.dumps(missing_stage), 0, tmp_path)["runner_status"]
        == "FAIL"
    )

    desktop_name = next(
        name
        for name, stage in qa.SCREENSHOT_STAGES.items()
        if stage == "desktop_screenshot"
    )
    (tmp_path / desktop_name).unlink()
    missing_file = qa._sanitize_child(json.dumps(child), 0, tmp_path)
    assert missing_file["stages"]["desktop_screenshot"] == "FAIL"
    assert missing_file["stages"]["mobile_screenshot"] == "PASS"


def test_child_failure_discards_credentials_messages_and_response_bodies(tmp_path):
    sentinel = "setup-reference-and-password-sentinel"
    child = {
        "workflow": "school-professional-review",
        "status": "FAIL",
        "stages": {key: "FAIL" for key in qa.UI_STAGE_KEYS},
        "screenshots": [],
        "failure": {
            "stage": "decision_saved",
            "error_class": "TimeoutError",
            "message": sentinel,
        },
        "password": sentinel,
        "response_body": sentinel,
    }

    result = qa._sanitize_child(json.dumps(child), 2, tmp_path)

    assert result["failure"] == {
        "stage": "decision_saved",
        "error_class": "TimeoutError",
    }
    assert sentinel not in json.dumps(result)
    assert result["runner_status"] == "FAIL"


def test_workflow_cannot_pass_without_all_wrapper_preflight_stages():
    stages = {key: "PASS" for key in qa.STAGE_KEYS}
    stages["setup_refs_validated"] = "FAIL"
    assert qa._result(stages, runner_status="PASS")["status"] == "FAIL"


def test_python_and_node_stage_registries_match_and_ui_does_not_mock_or_intercept():
    source = qa.NODE_SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"export const UI_STAGE_KEYS = \[(.*?)\];", source, re.DOTALL)
    assert match is not None
    assert tuple(re.findall(r"'([^']+)'", match.group(1))) == qa.UI_STAGE_KEYS
    assert qa.STAGE_KEYS == qa.PREFLIGHT_STAGE_KEYS + qa.UI_STAGE_KEYS + (
        "screenshots",
    )
    assert "page.route(" not in source
    assert ".route.fulfill(" not in source
    assert "response_body" not in source


def test_python_and_node_map_each_of_the_three_screenshots_to_its_stage():
    assert len(qa.SCREENSHOTS) == 3
    assert set(qa.SCREENSHOT_STAGES) == set(qa.SCREENSHOTS)
    assert qa.SCREENSHOT_STAGES == {
        "admin-professional-assignment.png": "admin_assignment_screenshot",
        "specialist-professional-review-desktop.png": "desktop_screenshot",
        "specialist-professional-review-mobile.png": "mobile_screenshot",
    }
    source = qa.NODE_SCRIPT.read_text(encoding="utf-8")
    block = re.search(r"export const SCREENSHOT_STAGES = \{(.*?)\};", source, re.DOTALL)
    assert block is not None
    node_mapping = dict(re.findall(r"'([^']+)': '([^']+)'", block.group(1)))
    assert node_mapping == qa.SCREENSHOT_STAGES
