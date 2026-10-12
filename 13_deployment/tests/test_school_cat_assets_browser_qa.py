import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_cat_assets_browser_qa as qa


def _private():
    return {
        "recipe_version": "school-contexts-v1",
        "credentials": {qa.SPECIALIST_SLOT: ["SYNTHETIC_ALPHA_SPECIALIST", "s" * 24]},
    }


def _all_ui_pass():
    return {key: "PASS" for key in qa.UI_STAGE_KEYS}


def test_child_must_match_exact_stages_and_masked_screenshot_allowlist(tmp_path):
    for name in qa.SCREENSHOTS:
        (tmp_path / name).write_bytes(b"synthetic masked image marker")
    child = {
        "workflow": "school-cat-assets",
        "status": "PASS",
        "stages": _all_ui_pass(),
        "screenshots": list(qa.SCREENSHOTS),
        "response_body": "response-body-sentinel",
        "credential": "credential-sentinel",
    }
    result = qa._sanitize_child(json.dumps(child), 0, tmp_path)
    assert result["runner_status"] == "PASS"
    assert result["status"] == "FAIL"  # Wrapper preflight is independent.
    assert result["stages"]["history_reload_verified"] == "PASS"
    assert "response_body" not in json.dumps(result)
    assert "credential-sentinel" not in json.dumps(result)

    missing_stage = dict(child)
    missing_stage["stages"] = dict(child["stages"])
    del missing_stage["stages"]["plan_version_saved"]
    assert qa._sanitize_child(json.dumps(missing_stage), 0, tmp_path)["runner_status"] == "FAIL"

    missing_image = qa._sanitize_child(json.dumps(child), 0, tmp_path / "absent")
    assert missing_image["stages"]["desktop_screenshot"] == "FAIL"
    assert missing_image["stages"]["mobile_screenshot"] == "FAIL"


def test_failure_free_text_and_credential_material_are_not_returned(tmp_path):
    sentinel = "private-response-password-ref-sentinel"
    child = {
        "workflow": "school-cat-assets",
        "status": "FAIL",
        "stages": {key: "FAIL" for key in qa.UI_STAGE_KEYS},
        "screenshots": [],
        "failure": {"stage": "plan_created", "error_class": "TimeoutError", "message": sentinel, "body": sentinel},
        "password": sentinel,
    }
    result = qa._sanitize_child(json.dumps(child), 2, tmp_path)
    assert result["failure"] == {"stage": "plan_created", "error_class": "TimeoutError"}
    assert sentinel not in json.dumps(result)


def test_result_requires_every_preflight_and_ui_stage():
    stages = {key: "PASS" for key in qa.STAGE_KEYS}
    assert qa._result(stages, runner_status="PASS")["status"] == "PASS"
    stages["owned_processes_verified"] = "FAIL"
    assert qa._result(stages, runner_status="PASS")["status"] == "FAIL"


def test_python_and_node_stage_and_screenshot_registries_are_identical():
    source = qa.NODE_SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"export const UI_STAGE_KEYS = \[(.*?)\];", source, re.DOTALL)
    assert match is not None
    assert tuple(re.findall(r"'([^']+)'", match.group(1))) == qa.UI_STAGE_KEYS
    assert qa.STAGE_KEYS == qa.PREFLIGHT_STAGE_KEYS + qa.UI_STAGE_KEYS + ("screenshots",)
    assert set(qa.SCREENSHOT_STAGES) == set(qa.SCREENSHOTS)
    assert "page.route(" not in source
    assert ".route.fulfill(" not in source
    for selector in (".account-menu", "input, textarea, select"):
        assert selector in source


def test_wrapper_reuses_owned_preflight_and_passes_only_sealed_specialist_credentials(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    browser_cache = tmp_path / "playwright-cache"
    browser_cache.mkdir()
    artifacts = workspace / "browser-qa" / "20261012T010203Z-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    artifacts.mkdir(parents=True)
    private = _private()
    events = []

    monkeypatch.setattr(qa, "BROWSER_CACHE", browser_cache)
    monkeypatch.setattr(qa.owned_cat.owned_workspace, "_verified_workspace", lambda: (workspace, {"synthetic_only": True}))
    monkeypatch.setattr(qa.owned_cat.owned_workspace, "_inspect_application_listeners", lambda _workspace: events.append("listeners"))
    monkeypatch.setattr(qa.owned_cat.owned_workspace, "_reject_reparse_path", lambda _path: None)
    monkeypatch.setattr(qa.owned_cat.owned_workspace, "_safe_node_environment", lambda: {"PATH": "safe-existing"})
    monkeypatch.setitem(sys.modules, "private_settings", SimpleNamespace(read_private=lambda _path: (events.append("credentials") or private)))
    monkeypatch.setitem(sys.modules, "school_backend", SimpleNamespace(load_runtime=lambda _workspace, _repo: events.append("runtime")))
    monkeypatch.setitem(sys.modules, "school_browser_qa", SimpleNamespace(create_artifact_run_dir=lambda _workspace: artifacts))
    monkeypatch.setattr(qa.shutil, "which", lambda _name: "node")
    monkeypatch.setattr(qa, "_safe_node_environment", lambda: {"PATH": "safe-existing", "PLAYWRIGHT_BROWSERS_PATH": str(browser_cache)})
    captured = {}

    def fake_subprocess(command, **kwargs):
        captured["command"] = command
        captured["payload"] = json.loads(kwargs["input"])
        captured["timeout"] = kwargs["timeout"]
        captured["shell"] = kwargs["shell"]
        captured["environment"] = kwargs["env"]
        for name in qa.SCREENSHOTS:
            (artifacts / name).write_bytes(b"synthetic masked image marker")
        child = {
            "workflow": "school-cat-assets", "status": "PASS", "stages": _all_ui_pass(),
            "screenshots": list(qa.SCREENSHOTS), "response_body": "drop-me", "credentials": "drop-me",
        }
        return SimpleNamespace(stdout=json.dumps(child), stderr="private stderr", returncode=0)

    monkeypatch.setattr(qa.subprocess, "run", fake_subprocess)
    result = qa.run()

    assert events == ["listeners", "runtime", "credentials"]
    assert tuple(captured["payload"]["credentials"]) == (qa.SPECIALIST_SLOT,)
    assert captured["payload"]["credentials"][qa.SPECIALIST_SLOT]["username"] == "SYNTHETIC_ALPHA_SPECIALIST"
    assert captured["timeout"] >= 600
    assert captured["shell"] is False
    assert captured["environment"]["PLAYWRIGHT_BROWSERS_PATH"] == str(browser_cache)
    assert result["status"] == "PASS"
    assert "response_body" not in json.dumps(result)
    assert "private stderr" not in json.dumps(result)
    report = (artifacts / "externalcatassetsbrowserqa.json").read_text(encoding="utf-8")
    assert "SYNTHETIC_ALPHA_SPECIALIST" not in report
    assert "response_body" not in report


def test_reused_owned_workspace_and_credential_helpers_are_callable():
    for name in (
        "_verified_workspace", "_inspect_application_listeners", "_reject_reparse_path",
        "_clear_private_account_material", "_safe_node_environment",
    ):
        assert callable(getattr(qa.owned_cat.owned_workspace, name, None)), name
    assert callable(qa.owned_cat._specialist_credentials)
    assert callable(qa.owned_cat._clear_private)
