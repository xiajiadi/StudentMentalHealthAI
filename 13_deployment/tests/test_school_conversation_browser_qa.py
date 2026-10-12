import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_conversation_browser_qa as qa


def _passed_ui_stages():
    return {key: "PASS" for key in qa.UI_STAGE_KEYS}


def _passed_stages():
    return {key: "PASS" for key in qa.STAGE_KEYS}


def test_only_registered_synthetic_student_credential_is_extracted():
    private = {
        "recipe_version": "school-contexts-v1",
        "credentials": {
            "alpha.student": ["SYNTHETIC_ALPHA_STUDENT", "p" * 24],
            "alpha.admin": ["SYNTHETIC_ALPHA_ADMIN", "admin password sentinel"],
        },
    }

    credential = qa._student_credential(private)

    assert credential["username"] == "SYNTHETIC_ALPHA_STUDENT"
    assert credential["password"] == "p" * 24
    assert "alpha.admin" in private["credentials"]


@pytest.mark.parametrize(
    "private",
    [
        None,
        {"recipe_version": "other", "credentials": {}},
        {"recipe_version": "school-contexts-v1", "credentials": []},
        {
            "recipe_version": "school-contexts-v1",
            "credentials": {"alpha.student": ["real-name-sentinel", "p" * 24]},
        },
        {
            "recipe_version": "school-contexts-v1",
            "credentials": {"alpha.student": ["SYNTHETIC_ALPHA_STUDENT", "short"]},
        },
    ],
)
def test_invalid_student_credential_fails_closed(private):
    with pytest.raises(qa.HarnessError):
        qa._student_credential(private)


def test_private_credential_material_is_cleared_in_memory():
    private = {
        "recipe_version": "school-contexts-v1",
        "credentials": {"alpha.student": ["SYNTHETIC_ALPHA_STUDENT", "p" * 24]},
    }

    qa._clear_private(private)

    assert private == {}


def test_child_pass_requires_exact_stages_and_real_screenshot_file(tmp_path):
    for name in qa.SCREENSHOTS:
        (tmp_path / name).write_bytes(b"synthetic masked screenshot marker")
    child = {
        "workflow": "school-independent-conversation",
        "status": "PASS",
        "stages": _passed_ui_stages(),
        "screenshots": list(qa.SCREENSHOTS),
        "query": "should not be forwarded",
        "response_body": "should not be forwarded",
    }

    result = qa._sanitize_child(json.dumps(child), 0, tmp_path)

    assert result["runner_status"] == "PASS"
    assert result["status"] == "FAIL"  # Python preflight stages were not yet merged.
    assert result["stages"]["desktop_screenshot"] == "PASS"
    assert result["stages"]["mobile_screenshot"] == "PASS"
    assert "query" not in result
    assert "response_body" not in result

    missing_stage = dict(child)
    missing_stage["stages"] = dict(child["stages"])
    del missing_stage["stages"]["citations_absent"]
    failed = qa._sanitize_child(json.dumps(missing_stage), 0, tmp_path)
    assert failed["runner_status"] == "FAIL"
    assert failed["stages"]["citations_absent"] == "FAIL"

    (tmp_path / qa.SCREENSHOTS[0]).unlink()
    missing_desktop = qa._sanitize_child(json.dumps(child), 0, tmp_path)
    assert missing_desktop["runner_status"] == "FAIL"
    assert missing_desktop["stages"]["desktop_screenshot"] == "FAIL"
    assert missing_desktop["stages"]["mobile_screenshot"] == "PASS"


def test_child_failure_discards_raw_error_query_and_credentials(tmp_path):
    sentinel = "private-query-password-sentinel"
    child = {
        "workflow": "school-independent-conversation",
        "status": "FAIL",
        "stages": {key: "FAIL" for key in qa.UI_STAGE_KEYS},
        "screenshots": [],
        "failure": {
            "stage": "abstention_body_verified",
            "error_class": "TimeoutError",
            "message": sentinel,
        },
        "password": sentinel,
        "response_body": sentinel,
    }

    result = qa._sanitize_child(json.dumps(child), 2, tmp_path)

    assert result["failure"] == {
        "stage": "abstention_body_verified",
        "error_class": "TimeoutError",
    }
    assert sentinel not in json.dumps(result)
    assert result["runner_status"] == "FAIL"


def test_result_never_passes_without_all_wrapper_preflight_stages():
    partial = _passed_stages()
    partial["backend_runtime_verified"] = "FAIL"

    result = qa._result(partial, runner_status="PASS")

    assert result["status"] == "FAIL"
    assert result["stages"]["backend_runtime_verified"] == "FAIL"
    assert result["screenshots"] == []


def test_python_and_node_ui_stage_registries_match():
    node_source = qa.NODE_SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"export const UI_STAGE_KEYS = \[(.*?)\];", node_source, re.DOTALL)

    assert match is not None
    node_keys = tuple(re.findall(r"'([^']+)'", match.group(1)))
    assert node_keys == qa.UI_STAGE_KEYS
    assert qa.STAGE_KEYS == qa.PREFLIGHT_STAGE_KEYS + qa.UI_STAGE_KEYS + ("screenshots",)


def test_wrapper_merge_preserves_preflight_and_abstention_poll_receives_conversation_id():
    source = Path(qa.__file__).read_text(encoding="utf-8")
    node_source = qa.NODE_SCRIPT.read_text(encoding="utf-8")

    # Child results include default FAIL values for wrapper-owned preflight keys.
    # Only merge UI-owned stages so those defaults cannot erase successful preflight.
    assert 'stages.update({key: child_result["stages"][key] for key in UI_STAGE_KEYS})' in source
    assert 'stages.update(child_result["stages"])' not in source

    assert "async function waitForPersistedAbstention(page, conversationId)" in node_source
    assert node_source.count("await waitForPersistedAbstention(pageA, conversationId);") == 1
