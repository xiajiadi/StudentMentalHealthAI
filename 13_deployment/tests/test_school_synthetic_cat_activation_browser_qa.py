"""Offline tests for sanitized synthetic saved-CAT activation browser QA."""
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_synthetic_cat_activation_browser_qa as qa


def _ui_pass() -> dict[str, str]:
    return {key: "PASS" for key in qa.UI_STAGE_KEYS}


def test_child_output_requires_exact_stages_and_every_existing_screenshot(tmp_path):
    for name in qa.SCREENSHOTS:
        (tmp_path / name).write_bytes(b"synthetic masked screenshot marker")
    child = {
        "workflow": "synthetic-cat-activation",
        "status": "PASS",
        "stages": {**_ui_pass(), "screenshots": "PASS"},
        "screenshots": list(qa.SCREENSHOTS),
        "api_statuses": {"task_publish": 201, "task_start": 200, "private": 200},
        "failure": {"stage": "admin_login", "error_class": "TimeoutError", "message": "private sentinel"},
        "response_body": "private sentinel",
        "credentials": "private sentinel",
    }
    result = qa._sanitize_child(json.dumps(child), 0, tmp_path)
    assert result["runner_status"] == "PASS"
    assert result["stages"]["task_activation_matched"] == "PASS"
    assert result["api_statuses"] == {"task_publish": 201, "task_start": 200}
    assert "private sentinel" not in json.dumps(result)

    wrong_stages = dict(child)
    wrong_stages["stages"] = dict(child["stages"])
    wrong_stages["stages"].pop("cat_version_provenance_matched")
    assert qa._sanitize_child(json.dumps(wrong_stages), 0, tmp_path)["runner_status"] == "FAIL"

    absent_image = qa._sanitize_child(json.dumps(child), 0, tmp_path / "absent")
    assert absent_image["runner_status"] == "FAIL"
    assert absent_image["stages"]["teacher_mobile_screenshot"] == "FAIL"


def test_failure_text_status_injection_and_unexpected_child_fields_are_not_forwarded(tmp_path):
    sentinel = "private-bank-stem-answer-password-sentinel"
    child = {
        "workflow": "synthetic-cat-activation",
        "status": "FAIL",
        "stages": {**{key: "FAIL" for key in qa.UI_STAGE_KEYS}, "screenshots": "FAIL"},
        "screenshots": [],
        "api_statuses": {"task_publish": True, "activation_create": sentinel},
        "failure": {"stage": "task_published_201", "error_class": "Error", "message": sentinel},
        "body": sentinel,
    }
    result = qa._sanitize_child(json.dumps(child), 2, tmp_path)
    assert result["runner_status"] == "FAIL"
    assert result["failure"] == {"stage": "task_published_201", "error_class": "Error"}
    assert result["api_statuses"] == {}
    assert sentinel not in json.dumps(result)


def test_python_and_node_registries_and_no_interception_are_aligned():
    source = qa.NODE_SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"export const UI_STAGE_KEYS = \[(.*?)\];", source, re.DOTALL)
    assert match is not None
    assert tuple(re.findall(r"'([^']+)'", match.group(1))) == qa.UI_STAGE_KEYS
    api_match = re.search(r"export const API_STATUS_KEYS = \[(.*?)\];", source, re.DOTALL)
    assert api_match is not None
    assert tuple(re.findall(r"'([^']+)'", api_match.group(1))) == qa.API_STATUS_KEYS
    assert qa.STAGE_KEYS == qa.PREFLIGHT_STAGE_KEYS + qa.UI_STAGE_KEYS + ("screenshots",)
    assert set(qa.SCREENSHOT_STAGES) == set(qa.SCREENSHOTS)
    assert "page.route(" not in source
    assert ".route.fulfill(" not in source
    for route in qa.ACCOUNT_ROUTES.values():
        assert route[0] and route[1] and route[2].startswith("/")


def test_wrapper_reuses_owned_preflight_and_passes_only_four_alpha_credentials(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    browser_cache = tmp_path / "playwright-cache"
    browser_cache.mkdir()
    artifacts = workspace / "browser-qa" / "20261013T010203Z-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    artifacts.mkdir(parents=True)
    private = {"synthetic_only": True}
    events: list[str] = []
    credentials = {
        "alpha.psychological_specialist": {"username": "SYNTHETIC_SPECIALIST", "password": "s" * 24},
        "alpha.teacher": {"username": "SYNTHETIC_TEACHER", "password": "t" * 24},
        "alpha.student": {"username": "SYNTHETIC_STUDENT", "password": "u" * 24},
        "alpha.admin": {"username": "SYNTHETIC_ADMIN", "password": "a" * 24},
    }

    monkeypatch.setattr(qa, "BROWSER_CACHE", browser_cache)
    monkeypatch.setattr(qa, "os", SimpleNamespace(environ={}))
    monkeypatch.setattr(qa.owned_workspace, "_verified_workspace", lambda: (workspace, {"synthetic_only": True}))
    monkeypatch.setattr(qa.owned_workspace, "_inspect_application_listeners", lambda _workspace: events.append("listeners"))
    monkeypatch.setattr(qa.owned_workspace, "_reject_reparse_path", lambda _path: None)
    monkeypatch.setattr(qa.owned_workspace, "_clear_private_account_material", lambda value: events.append("clear_private") if value is private else None)
    monkeypatch.setitem(sys.modules, "private_settings", SimpleNamespace(read_private=lambda _path: (events.append("credentials") or private)))
    monkeypatch.setitem(sys.modules, "school_backend", SimpleNamespace(load_runtime=lambda _workspace, _repo: events.append("runtime")))
    monkeypatch.setitem(sys.modules, "school_browser_qa", SimpleNamespace(
        create_artifact_run_dir=lambda _workspace: artifacts,
        validate_credentials=lambda _private: credentials,
    ))
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
            (artifacts / name).write_bytes(b"synthetic masked screenshot marker")
        child = {
            "workflow": "synthetic-cat-activation", "status": "PASS",
            "stages": {**_ui_pass(), "screenshots": "PASS"},
            "screenshots": list(qa.SCREENSHOTS), "response_body": "drop-me", "credentials": "drop-me",
        }
        return SimpleNamespace(stdout=json.dumps(child), stderr="private stderr", returncode=0)

    monkeypatch.setattr(qa.subprocess, "run", fake_subprocess)
    result = qa.run()

    assert events == ["listeners", "runtime", "credentials", "clear_private"]
    assert set(captured["payload"]["credentials"]) == set(qa.ACCOUNT_ROUTES)
    assert captured["payload"]["accounts"]["alpha.admin"]["api_role"] == "ADMIN"
    assert captured["timeout"] == 900
    assert captured["shell"] is False
    assert captured["environment"]["PLAYWRIGHT_BROWSERS_PATH"] == str(browser_cache)
    assert result["status"] == "PASS"
    assert "drop-me" not in json.dumps(result)
    assert "private stderr" not in json.dumps(result)
    report = (artifacts / "external-synthetic-cat-activation-browser-qa.json").read_text(encoding="utf-8")
    assert "SYNTHETIC_ADMIN" not in report
    assert "response_body" not in report
    for account in captured["payload"]["credentials"].values():
        account["username"] = ""
        account["password"] = ""


def test_preflight_result_requires_all_stages():
    stages = {key: "PASS" for key in qa.STAGE_KEYS}
    assert qa._result(stages, runner_status="PASS")["status"] == "PASS"
    stages["activation_metadata_matched"] = "FAIL"
    assert qa._result(stages, runner_status="PASS")["status"] == "FAIL"


def test_backend_task_start_dto_accepts_real_first_item_count_semantics():
    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo / "09_backend" / "src"))
    from smhai_backend.domains.school_tasks.schemas import TaskStartDto

    assessment_service = (repo / "09_backend" / "src" / "smhai_backend" / "domains" / "assessment" / "service.py").read_text(encoding="utf-8")
    assert '"status": "created"' in assessment_service
    assert 'record.assessment["status"] = "in_progress"' in assessment_service
    fixture = json.loads((repo / "01_cat-engine" / "fixtures" / "synthetic_item_bank.v1.json").read_text(encoding="utf-8"))
    item = fixture["items"][0]
    cat_current_item = {
        "item_id": item["item_id"],
        "prompt": item["stem"],
        "response_type": item["response_type"],
        "options": [{"value": option, "label": option} for option in item["response_options"]],
    }
    dto = TaskStartDto.model_validate({
        "task_ref": "TASK_synthetic_qa",
        "assessment_id": "ASSESS_synthetic_qa",
        "subject_id": "SUBJ_synthetic_qa",
        "status": "created",
        "selected_item_id": cat_current_item["item_id"],
        "current_item": cat_current_item,
        "answered_count": 0,
        "administered_count": 0,
        "can_complete": False,
        "max_items": 3,
    })
    projected = dto.model_dump(mode="json")
    assert projected["administered_count"] == 0
    assert projected["selected_item_id"] == projected["current_item"]["item_id"]
    assert projected["current_item"]["options"][0] == {"value": "never", "label": "never"}


def test_backend_teacher_progress_dto_accepts_database_aggregate_projection():
    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo / "09_backend" / "src"))
    sys.path.insert(0, str(repo / "11_database"))
    from database_layer.repositories import TaskProgressCounts
    from smhai_backend.domains.school_tasks.schemas import TeacherTaskProgressDto

    counts = TaskProgressCounts(
        published_enrollment_count=1,
        active_enrollment_count=1,
        revoked_enrollment_count=0,
        not_started_count=0,
        created_count=0,
        in_progress_count=0,
        completed_count=1,
        abandoned_count=0,
        invalid_count=0,
    )
    dto = TeacherTaskProgressDto.model_validate({
        "class_ref": "CLASS_synthetic_qa",
        "task_ref": "TASK_synthetic_qa",
        "task_status": "PUBLISHED",
        "opens_at": datetime(2026, 10, 13, tzinfo=UTC),
        "due_at": None,
        **asdict(counts),
    })
    projected = dto.model_dump(mode="json")
    assert projected["completed_count"] == 1
    assert projected["active_enrollment_count"] == 1
    assert projected["opens_at"] == "2026-10-13T00:00:00Z"
