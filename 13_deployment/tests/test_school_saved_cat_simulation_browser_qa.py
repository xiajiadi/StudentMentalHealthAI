import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_saved_cat_simulation_browser_qa as qa


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


def test_only_synthetic_specialist_credential_is_projected_then_private_source_cleared():
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


def test_workspace_process_and_runtime_helper_entrypoints_exist_without_execution():
    for name in (
        "_verified_workspace",
        "_inspect_application_listeners",
        "_reject_reparse_path",
        "_clear_private_account_material",
        "_safe_node_environment",
    ):
        assert callable(getattr(qa.owned_workspace, name, None)), name


def test_python_and_node_registries_match_and_screenshots_are_fixed():
    source = qa.NODE_SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"export const UI_STAGE_KEYS = \[(.*?)\];", source, re.DOTALL)
    assert match is not None
    assert tuple(re.findall(r"'([^']+)'", match.group(1))) == qa.UI_STAGE_KEYS
    assert qa.STAGE_KEYS == qa.PREFLIGHT_STAGE_KEYS + qa.UI_STAGE_KEYS + ("screenshots",)
    assert set(qa.SCREENSHOT_STAGES) == set(qa.SCREENSHOTS)
    assert "page.route(" not in source
    assert ".route.fulfill(" not in source
    assert "response_body" not in source
    assert "SYNTHETIC_ALPHA_SPECIALIST" not in source

    setup_match = re.search(r"export const SETUP_SUBSTAGES = \[(.*?)\];", source, re.DOTALL)
    assert setup_match is not None
    assert tuple(re.findall(r"'([^']+)'", setup_match.group(1))) == qa.SETUP_SUBSTAGES
    selection_match = re.search(r"export const SELECTION_SUBSTAGES = \[(.*?)\];", source, re.DOTALL)
    assert selection_match is not None
    assert tuple(re.findall(r"'([^']+)'", selection_match.group(1))) == qa.SELECTION_SUBSTAGES
    aggregate_match = re.search(r"export const AGGREGATE_SUBSTAGES = \[(.*?)\];", source, re.DOTALL)
    assert aggregate_match is not None
    assert tuple(re.findall(r"'([^']+)'", aggregate_match.group(1))) == qa.AGGREGATE_SUBSTAGES
    assert "plan_version_create: 200" in source


def test_child_pass_requires_exact_statuses_and_both_screenshots(tmp_path):
    for name in qa.SCREENSHOTS:
        (tmp_path / name).write_bytes(b"masked screenshot marker")
    child = {
        "workflow": "school-saved-cat-simulation",
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
    assert "response_body" not in result and "credential" not in result

    malformed = dict(child)
    malformed["stages"] = dict(child["stages"])
    del malformed["stages"]["history_switch_clears_result"]
    assert qa._sanitize_child(json.dumps(malformed), 0, tmp_path)["runner_status"] == "FAIL"

    (tmp_path / qa.SCREENSHOTS[0]).unlink()
    missing = qa._sanitize_child(json.dumps(child), 0, tmp_path)
    assert missing["stages"]["desktop_screenshot"] == "FAIL"
    assert missing["stages"]["mobile_screenshot"] == "PASS"


def test_child_failure_drops_free_text_bodies_and_credentials(tmp_path):
    sentinel = "saved-cat-response-password-sentinel"
    child = {
        "workflow": "school-saved-cat-simulation",
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


def test_runner_failure_keeps_only_exit_code_and_whitelisted_stderr_class(tmp_path):
    sentinel = "raw response body and credential sentinel"
    child = {
        "workflow": "school-saved-cat-simulation",
        "status": "FAIL",
        "stages": {key: "FAIL" for key in qa.UI_STAGE_KEYS},
        "screenshots": [],
    }
    result = qa._sanitize_child(json.dumps(child), 1, tmp_path, f"TypeError: {sentinel}")
    assert result["runner_diagnostics"] == {"exit_code": 1, "stderr_class": "TypeError"}
    assert sentinel not in json.dumps(result)
    assert qa._stderr_error_class(f"untrusted prefix TypeError: {sentinel}") == "Unknown"


def test_preparation_failure_keeps_only_fixed_substage_and_http_status(tmp_path):
    child = {
        "workflow": "school-saved-cat-simulation",
        "status": "FAIL",
        "stages": {key: "FAIL" for key in qa.UI_STAGE_KEYS},
        "screenshots": [],
        "failure": {"stage": "synthetic_assets_prepared", "error_class": "Error", "message": "private body"},
        "diagnostics": {"stage": "synthetic_assets_prepared", "substage": "plan_version_create", "http_status": 200},
    }
    result = qa._sanitize_child(json.dumps(child), 2, tmp_path)
    assert result["diagnostics"] == {
        "stage": "synthetic_assets_prepared", "substage": "plan_version_create", "http_status": 200,
    }
    assert "private body" not in json.dumps(result)

    invalid = dict(child)
    invalid["diagnostics"] = {
        "stage": "synthetic_assets_prepared", "substage": "plan_version_create", "http_status": 200,
        "response_body": "body-sentinel",
    }
    safe = qa._sanitize_child(json.dumps(invalid), 2, tmp_path)
    assert "diagnostics" not in safe
    assert "body-sentinel" not in json.dumps(safe)


def test_saved_version_selection_failure_keeps_only_fixed_substage_and_http_status(tmp_path):
    child = {
        "workflow": "school-saved-cat-simulation",
        "status": "FAIL",
        "stages": {key: "FAIL" for key in qa.UI_STAGE_KEYS},
        "screenshots": [],
        "failure": {"stage": "saved_version_selected", "error_class": "TimeoutError"},
        "diagnostics": {"stage": "saved_version_selected", "substage": "plan_row_visible", "http_status": 200},
    }
    result = qa._sanitize_child(json.dumps(child), 2, tmp_path)
    assert result["diagnostics"] == child["diagnostics"]

    invalid = dict(child)
    invalid["diagnostics"] = {
        **child["diagnostics"],
        "selector": "private-selector-sentinel",
    }
    safe = qa._sanitize_child(json.dumps(invalid), 2, tmp_path)
    assert "diagnostics" not in safe
    assert "private-selector-sentinel" not in json.dumps(safe)


def test_aggregate_failure_keeps_only_fixed_substage(tmp_path):
    child = {
        "workflow": "school-saved-cat-simulation",
        "status": "FAIL",
        "stages": {key: "FAIL" for key in qa.UI_STAGE_KEYS},
        "screenshots": [],
        "failure": {"stage": "ui_aggregates_matched_api", "error_class": "Error"},
        "diagnostics": {"stage": "ui_aggregates_matched_api", "substage": "binding_labels"},
    }
    result = qa._sanitize_child(json.dumps(child), 2, tmp_path)
    assert result["diagnostics"] == child["diagnostics"]

    invalid = dict(child)
    invalid["diagnostics"] = {**child["diagnostics"], "visible_text": "private-sentinel"}
    safe = qa._sanitize_child(json.dumps(invalid), 2, tmp_path)
    assert "diagnostics" not in safe
    assert "private-sentinel" not in json.dumps(safe)


def test_all_wrapper_preflight_stages_are_required():
    stages = {key: "PASS" for key in qa.STAGE_KEYS}
    stages["credentials_loaded"] = "FAIL"
    assert qa._result(stages, runner_status="PASS")["status"] == "FAIL"


def test_run_uses_owned_preflight_sealed_stdin_and_sanitized_output(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    browser_cache = tmp_path / "browser-cache"
    browser_cache.mkdir()
    artifacts = workspace / "browser-qa" / "20261013T010203Z-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    artifacts.mkdir(parents=True)
    events = []
    private = _private()
    monkeypatch.setattr(qa, "WORKSPACE", workspace)
    monkeypatch.setattr(qa, "BROWSER_CACHE", browser_cache)
    monkeypatch.setattr(qa.owned_workspace, "_verified_workspace", lambda: (workspace, {"synthetic_only": True}))
    monkeypatch.setattr(qa.owned_workspace, "_inspect_application_listeners", lambda _workspace: events.append("listeners"))
    monkeypatch.setattr(qa.owned_workspace, "_reject_reparse_path", lambda _path: None)
    monkeypatch.setattr(qa.owned_workspace, "_clear_private_account_material", lambda material: material.clear() if isinstance(material, dict) else None)
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
            (artifacts / name).write_bytes(b"masked screenshot marker")
        child = {
            "workflow": "school-saved-cat-simulation",
            "status": "PASS",
            "stages": _ui_stages(),
            "screenshots": list(qa.SCREENSHOTS),
            "response_body": "must-not-persist",
            "secret": "must-not-persist",
        }
        return SimpleNamespace(stdout=json.dumps(child), stderr="private child stderr", returncode=0)

    monkeypatch.setattr(qa.subprocess, "run", fake_subprocess)

    result = qa.run()

    assert events == ["listeners", "runtime", "credentials"]
    assert tuple(captured["payload"]["credentials"]) == ("alpha.psychological_specialist",)
    assert captured["payload"]["credentials"]["alpha.psychological_specialist"]["username"] == "SYNTHETIC_ALPHA_SPECIALIST"
    assert captured["timeout"] >= 600
    assert captured["shell"] is False
    assert captured["environment"]["PLAYWRIGHT_BROWSERS_PATH"] == str(browser_cache)
    assert result["status"] == "PASS"
    assert result["stages"]["backend_runtime_verified"] == "PASS"
    assert "response_body" not in json.dumps(result)
    assert "private child stderr" not in json.dumps(result)
    written = (artifacts / "externalsavedcatsimulationbrowserqa.json").read_text(encoding="utf-8")
    assert "response_body" not in written
    assert "SYNTHETIC_ALPHA_SPECIALIST" not in written
