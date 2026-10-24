import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_account_lifecycle_first_login_qa as qa


def test_first_login_browser_result_keeps_only_allowlisted_evidence():
    canary = "secret-canary-do-not-emit"
    payload = {
        "status": "FAIL",
        "stages": {"admin_login": "PASS", "first_login": "FAIL", "unexpected": "PASS"},
        "viewport_widths": {"390": 390, "999": 1000},
        "student_viewport_widths": {"390": 389, "999": 1000},
        "screenshots": {
            "admin_390": r"D:\safe\account-lifecycle-admin-390.png",
            "student_390": r"D:\safe\account-lifecycle-student-390.png",
            "first_login_390": r"D:\safe\account-lifecycle-first-login-390.png",
            "other": canary,
        },
        "credential": canary,
        "failure": {
            "stage": "first_login",
            "code": "ACTION_TIMEOUT",
            "checkpoint": "first_login_form",
            "message": canary,
        },
    }

    safe = qa._safe_result(json.dumps(payload), 2)

    assert safe["status"] == "FAIL"
    assert safe["stages"] == {
        "admin_login": "PASS",
        "admin_workspace": "FAIL",
        "keyboard_tabs": "FAIL",
        "first_login_mobile": "FAIL",
        "first_login": "FAIL",
        "student_login": "FAIL",
        "role_denied": "FAIL",
        "viewport_1440": "FAIL",
        "viewport_1024": "FAIL",
        "viewport_768": "FAIL",
        "viewport_390": "FAIL",
        "logout": "FAIL",
        "credential_replay_rejected": "FAIL",
    }
    assert safe["viewport_widths"] == {"390": 390}
    assert safe["student_viewport_widths"] == {"390": 389}
    assert safe["screenshots"] == {
        "admin_390": r"D:\safe\account-lifecycle-admin-390.png",
        "student_390": r"D:\safe\account-lifecycle-student-390.png",
        "first_login_390": r"D:\safe\account-lifecycle-first-login-390.png",
    }
    assert safe["failure"] == {
        "stage": "first_login",
        "code": "ACTION_TIMEOUT",
        "checkpoint": "first_login_form",
    }
    assert canary not in json.dumps(safe)


def test_invalid_child_output_is_reported_without_raw_stdout():
    safe = qa._safe_result("credential-value-not-json", 1)
    assert safe == {
        "status": "FAIL",
        "failure": {"stage": "browser_runner", "code": "INVALID_RESULT"},
    }
