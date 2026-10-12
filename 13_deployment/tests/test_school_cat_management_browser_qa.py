import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_cat_management_browser_qa as qa


def _private():
    return {
        "recipe_version": "school-contexts-v1",
        "credentials": {
            "alpha.admin": ["SYNTHETIC_ALPHA_ADMIN", "a" * 24],
            "alpha.psychological_specialist": ["SYNTHETIC_ALPHA_SPECIALIST", "s" * 24],
        },
    }


def _ui_stages():
    return {key: "PASS" for key in qa.UI_STAGE_KEYS}


def test_only_synthetic_specialist_login_is_projected_and_private_input_is_cleared():
    private = _private()
    credentials = qa._specialist_credentials(private)
    assert tuple(credentials) == ("alpha.psychological_specialist",)
    assert credentials["alpha.psychological_specialist"]["username"] == "SYNTHETIC_ALPHA_SPECIALIST"
    qa._clear_private(private)
    assert private == {}


@pytest.mark.parametrize(
    "replacement",
    [
        ["specialist@example.test", "s" * 24],
        ["SYNTHETIC_SPECIALIST", "short"],
        ["SYNTHETIC_SPECIALIST", 123],
    ],
)
def test_invalid_or_non_synthetic_specialist_credentials_fail_closed(replacement):
    private = _private()
    private["credentials"]["alpha.psychological_specialist"] = replacement
    with pytest.raises(qa.HarnessError):
        qa._specialist_credentials(private)


def test_workspace_helper_entrypoints_are_available_without_running_them():
    for name in (
        "_verified_workspace",
        "_inspect_application_listeners",
        "_reject_reparse_path",
        "_clear_private_account_material",
        "_safe_node_environment",
    ):
        assert callable(getattr(qa.owned_workspace, name, None)), name


def test_child_pass_requires_exact_stage_list_and_both_masked_screenshots(tmp_path):
    for name in qa.SCREENSHOTS:
        (tmp_path / name).write_bytes(b"synthetic masked screenshot marker")
    child = {
        "workflow": "school-cat-management",
        "status": "PASS",
        "stages": _ui_stages(),
        "screenshots": list(qa.SCREENSHOTS),
        "response_body": "response-body-sentinel",
        "credential": "credential-sentinel",
    }

    result = qa._sanitize_child(json.dumps(child), 0, tmp_path)

    assert result["runner_status"] == "PASS"
    assert result["status"] == "FAIL"  # wrapper preflight has not been merged.
    assert result["stages"]["desktop_screenshot"] == "PASS"
    assert result["stages"]["mobile_screenshot"] == "PASS"
    assert "response_body" not in result
    assert "credential" not in result

    malformed = dict(child)
    malformed["stages"] = dict(child["stages"])
    del malformed["stages"]["repeat_simulation_verified"]
    assert qa._sanitize_child(json.dumps(malformed), 0, tmp_path)["runner_status"] == "FAIL"

    (tmp_path / qa.SCREENSHOTS[0]).unlink()
    missing_desktop = qa._sanitize_child(json.dumps(child), 0, tmp_path)
    assert missing_desktop["stages"]["desktop_screenshot"] == "FAIL"
    assert missing_desktop["stages"]["mobile_screenshot"] == "PASS"


def test_child_failure_drops_free_text_bodies_and_credentials(tmp_path):
    sentinel = "cat-response-password-session-sentinel"
    child = {
        "workflow": "school-cat-management",
        "status": "FAIL",
        "stages": {key: "FAIL" for key in qa.UI_STAGE_KEYS},
        "screenshots": [],
        "failure": {
            "stage": "simulation100_verified",
            "error_class": "TimeoutError",
            "message": sentinel,
            "response_body": sentinel,
        },
        "password": sentinel,
    }
    result = qa._sanitize_child(json.dumps(child), 2, tmp_path)
    assert result["failure"] == {"stage": "simulation100_verified", "error_class": "TimeoutError"}
    assert sentinel not in json.dumps(result)


def test_pass_requires_all_wrapper_preflight_stages():
    stages = {key: "PASS" for key in qa.STAGE_KEYS}
    stages["credentials_loaded"] = "FAIL"
    assert qa._result(stages, runner_status="PASS")["status"] == "FAIL"


def test_node_and_python_stage_and_screenshot_registries_match_and_no_response_interception():
    source = qa.NODE_SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"export const UI_STAGE_KEYS = \[(.*?)\];", source, re.DOTALL)
    assert match is not None
    assert tuple(re.findall(r"'([^']+)'", match.group(1))) == qa.UI_STAGE_KEYS
    assert qa.STAGE_KEYS == qa.PREFLIGHT_STAGE_KEYS + qa.UI_STAGE_KEYS + ("screenshots",)
    assert set(qa.SCREENSHOT_STAGES) == set(qa.SCREENSHOTS)
    assert "page.route(" not in source
    assert ".route.fulfill(" not in source
    assert "response_body" not in source
    for selector in (".account-menu", "input, textarea, select"):
        assert selector in source


def test_run_uses_owned_preflight_sealed_stdin_and_sanitized_output(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    browser_cache = tmp_path / "browser-cache"
    browser_cache.mkdir()
    artifacts = workspace / "browser-qa" / "synthetic-run"
    artifacts.mkdir(parents=True)
    events = []
    private = _private()
    monkeypatch.setattr(qa, "WORKSPACE", workspace)
    monkeypatch.setattr(qa, "BROWSER_CACHE", browser_cache)
    monkeypatch.setattr(qa.owned_workspace, "_verified_workspace", lambda: (workspace, {"synthetic_only": True}))
    monkeypatch.setattr(qa.owned_workspace, "_inspect_application_listeners", lambda _workspace: events.append("listeners"))
    monkeypatch.setattr(qa.owned_workspace, "_reject_reparse_path", lambda _path: None)
    monkeypatch.setattr(qa.owned_workspace, "_clear_private_account_material", qa.owned_workspace._clear_private_account_material)
    monkeypatch.setattr(qa.owned_workspace, "_safe_node_environment", lambda: {"PATH": "existing-safe-path"})
    monkeypatch.setitem(sys.modules, "private_settings", SimpleNamespace(read_private=lambda _path: (events.append("credentials") or private)))
    monkeypatch.setitem(sys.modules, "school_backend", SimpleNamespace(load_runtime=lambda _workspace, _repo: events.append("runtime")))
    monkeypatch.setitem(sys.modules, "school_browser_qa", SimpleNamespace(create_artifact_run_dir=lambda _workspace: artifacts))
    monkeypatch.setattr(qa.shutil, "which", lambda _name: "node")
    monkeypatch.setattr(qa, "_safe_node_environment", lambda: {"PATH": "existing-safe-path", "PLAYWRIGHT_BROWSERS_PATH": str(browser_cache)})

    captured = {}

    def fake_subprocess(command, **kwargs):
        captured["command"] = command
        captured["payload"] = json.loads(kwargs["input"])
        captured["timeout"] = kwargs["timeout"]
        captured["shell"] = kwargs["shell"]
        captured["environment"] = kwargs["env"]
        for name in qa.SCREENSHOTS:
            (artifacts / name).write_bytes(b"synthetic masked screenshot marker")
        child = {
            "workflow": "school-cat-management",
            "status": "PASS",
            "stages": _ui_stages(),
            "screenshots": list(qa.SCREENSHOTS),
            "response_body": "must not be persisted",
            "secret": "must not be persisted",
        }
        return SimpleNamespace(stdout=json.dumps(child), stderr="private child stderr", returncode=0)

    monkeypatch.setattr(qa.subprocess, "run", fake_subprocess)

    result = qa.run()

    assert events == ["listeners", "runtime", "credentials"]
    assert captured["payload"]["credentials"]["alpha.psychological_specialist"]["username"] == "SYNTHETIC_ALPHA_SPECIALIST"
    assert tuple(captured["payload"]["credentials"]) == ("alpha.psychological_specialist",)
    assert captured["timeout"] >= 600
    assert captured["shell"] is False
    assert captured["environment"]["PLAYWRIGHT_BROWSERS_PATH"] == str(browser_cache)
    assert result["status"] == "PASS"
    assert result["stages"]["backend_runtime_verified"] == "PASS"
    assert "response_body" not in json.dumps(result)
    assert "private child stderr" not in json.dumps(result)
    written = (artifacts / "externalcatmanagementbrowserqa.json").read_text(encoding="utf-8")
    assert "response_body" not in written
    assert "SYNTHETIC_ALPHA_SPECIALIST" not in written
