import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_account_lifecycle_staff_recovery_browser_qa as qa


def test_sanitizer_keeps_only_stages_and_safe_failure_fields():
    secret = "credential-canary-do-not-emit"
    payload = {
        "status": "FAIL",
        "stages": {"admin_login": "PASS", "recovery_issued": "PASS", "unexpected": "PASS"},
        "credential": secret,
        "failure": {"stage": "reset_complete", "code": "RESET_FAILED", "message": secret},
    }

    safe = qa._safe_child_result(json.dumps(payload), 2)

    assert safe["status"] == "FAIL"
    assert safe["stages"]["admin_login"] == "PASS"
    assert safe["stages"]["recovery_issued"] == "PASS"
    assert "unexpected" not in safe["stages"]
    assert safe["failure"] == {"stage": "reset_complete", "code": "RESET_FAILED"}
    assert secret not in json.dumps(safe)


def test_sanitizer_rejects_non_json_without_echoing_child_output():
    secret = "private-child-output"
    assert qa._safe_child_result(secret, 1) == {
        "status": "FAIL",
        "failure": {"stage": "browser_runner", "code": "INVALID_RESULT"},
    }
