"""Run phase 1 or 2 of the two-phase saved-CAT school-task HTTP proof.

The helper uses the externally owned synthetic workspace, current-user sealed
accounts and exact loopback runtime checks. It never writes API bodies, answers,
credentials, cookies, exception messages or database contents to evidence files.
Phase 1 writes only allowlisted references to a new DPAPI continuation file;
Root restarts CAT before invoking phase 2.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import school_directory_browser_qa as owned_workspace

REPO = owned_workspace.REPO
BACKEND_URL = owned_workspace.BACKEND_URL
ACCOUNT_FILE = "school-accounts.private.dpapi"
CONTINUATION_SCHEMA = "psynova.school-saved-cat-task-http-continuation.v1"
CONTINUATION_PREFIX = "school-saved-cat-task-continuation-"
EVIDENCE_PREFIX = "school-saved-cat-task-http-evidence-"
CONTINUATION_SUFFIX = ".dpapi"
EVIDENCE_SUFFIX = ".json"
ACTIVATION_API = "/api/v1/school/cat-assets"


def _school_refs_from_seed_source() -> dict[str, str]:
    source_path = REPO / "11_database" / "database_layer" / "school_seed.py"
    try:
        tree = ast.parse(
            source_path.read_text(encoding="utf-8"), filename=str(source_path)
        )
    except (OSError, SyntaxError, UnicodeError):
        raise RuntimeError("synthetic school seed references unavailable") from None
    value = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "SYNTHETIC_SCHOOL_RECIPES"
            for target in node.targets
        ):
            value = node.value
            break
    if not isinstance(value, ast.Tuple):
        raise TypeError("synthetic school seed references unavailable")
    result: dict[str, str] = {}
    for entry in value.elts:
        if not isinstance(entry, ast.Call) or not isinstance(entry.func, ast.Name):
            raise TypeError("synthetic school seed references unavailable")
        fields = {}
        try:
            fields = {
                keyword.arg: ast.literal_eval(keyword.value)
                for keyword in entry.keywords
            }
        except (ValueError, TypeError):
            raise RuntimeError("synthetic school seed references unavailable") from None
        key, school_ref = fields.get("key"), fields.get("school_ref")
        if (
            key not in {"alpha", "beta"}
            or not isinstance(school_ref, str)
            or not re.fullmatch(r"SYNTHETIC_SCHOOL_SEED_(?:ALPHA|BETA)_V1", school_ref)
            or key in result
        ):
            raise RuntimeError("synthetic school seed references unavailable")
        result[key] = school_ref
    if set(result) != {"alpha", "beta"}:
        raise RuntimeError("synthetic school seed references unavailable")
    return result


SCHOOL_REFS = _school_refs_from_seed_source()
ACCOUNT_SCHOOL = {
    "alpha.admin": SCHOOL_REFS["alpha"],
    "alpha.student": SCHOOL_REFS["alpha"],
    "alpha.teacher": SCHOOL_REFS["alpha"],
    "alpha.psychological_specialist": SCHOOL_REFS["alpha"],
    "beta.student": SCHOOL_REFS["beta"],
}
ACCOUNT_ROLES = {
    "alpha.admin": "ADMIN",
    "alpha.student": "STUDENT",
    "alpha.teacher": "TEACHER",
    "alpha.psychological_specialist": "PSYCHOLOGICAL_SPECIALIST",
    "beta.student": "STUDENT",
}

PHASE1_STAGE_KEYS = (
    "workspace_owned",
    "owned_processes_verified",
    "backend_runtime_verified",
    "credentials_loaded",
    "specialist_login",
    "template_verified",
    "role_csrf_and_cross_school_denials",
    "bank_and_plan_created",
    "activation_created_replayed_and_conflicted",
    "admin_eligible_metadata_verified",
    "class_and_roster_created",
    "three_tasks_published",
    "generic_school_assessment_denied",
    "task_a_started_and_first_response_saved",
    "task_b_created_without_responses",
    "activation_revoked_and_assets_archived",
    "in_progress_task_retained",
    "created_task_blocked",
    "unstarted_task_blocked",
    "new_publish_blocked",
    "continuation_sealed",
    "sessions_logged_out",
)
PHASE2_STAGE_KEYS = (
    "workspace_owned",
    "owned_processes_verified",
    "backend_runtime_verified",
    "continuation_loaded",
    "credentials_loaded",
    "saved_version_and_history_verified",
    "admin_metadata_excludes_revoked_activation",
    "cat_restart_restored_exact_session",
    "remaining_responses_saved_and_completed",
    "frozen_result_provenance_verified",
    "teacher_aggregate_only_verified",
    "enrollment_revoked",
    "cached_response_replay_denied",
    "cached_completion_replay_denied",
    "state_read_denied",
    "student_metadata_excludes_revoked_assessment",
    "sessions_logged_out",
)
STAGES_BY_PHASE = {1: PHASE1_STAGE_KEYS, 2: PHASE2_STAGE_KEYS}

API_STATUS_KEYS = (
    "login_specialist",
    "context_specialist",
    "template_specialist",
    "template_admin",
    "template_teacher",
    "bank_csrf_denial",
    "teacher_bank_denial",
    "admin_bank_denial",
    "admin_bank_document_denial",
    "beta_assets_denial",
    "generic_create_first",
    "generic_create_same_key",
    "bank_create",
    "plan_create",
    "activation_csrf_denial",
    "activation_admin_filtered_denial",
    "activation_create",
    "activation_replay",
    "activation_duplicate",
    "activation_admin_list",
    "class_create",
    "student_assign",
    "teacher_assign",
    "task_a_publish",
    "task_b_publish",
    "task_c_publish",
    "beta_task_start",
    "task_a_start",
    "task_a_state_initial",
    "task_a_response_1",
    "task_a_state_after_response",
    "task_b_start",
    "task_b_state_initial",
    "activation_revoke",
    "plan_archive",
    "bank_archive",
    "task_a_state_after_revoke",
    "task_b_state_after_revoke",
    "task_c_start_after_revoke",
    "task_d_publish_after_revoke",
    "activation_admin_list_after_revoke",
    "bank_version_read",
    "plan_version_read",
    "activation_history_read",
    "task_a_state_after_cat_restart",
    "task_a_response_2",
    "task_a_state_after_response_2",
    "task_a_response_3",
    "task_a_state_after_response_3",
    "task_a_complete",
    "task_a_completed_state",
    "teacher_progress_completed",
    "task_a_enrollment_list",
    "task_a_enrollment_revoke",
    "cached_response_after_revoke",
    "cached_complete_after_revoke",
    "task_a_state_after_enrollment_revoke",
    "student_assessment_metadata_after_revoke",
    "student_task_history_after_revoke",
    "logout_specialist",
    "logout_admin",
    "logout_student",
    "logout_teacher",
    "logout_beta_student",
    "login_alpha_psychological_specialist",
    "context_alpha_psychological_specialist",
    "login_alpha_admin",
    "context_alpha_admin",
    "login_alpha_student",
    "context_alpha_student",
    "login_alpha_teacher",
    "context_alpha_teacher",
    "login_beta_student",
    "context_beta_student",
    "logout_alpha_psychological_specialist",
    "logout_alpha_admin",
    "logout_alpha_student",
    "logout_alpha_teacher",
    "logout_beta_student",
)
SAFE_FAILURE_CLASSES = {
    "HarnessError",
    "AssertionError",
    "Error",
    "OSError",
    "PermissionError",
    "FileNotFoundError",
    "ValueError",
    "TypeError",
    "KeyError",
    "TimeoutError",
    "TimeoutException",
    "ConnectError",
    "ConnectTimeout",
    "ReadTimeout",
    "WriteTimeout",
    "RemoteProtocolError",
    "HTTPStatusError",
    "JSONDecodeError",
    "UnicodeDecodeError",
    "RuntimeError",
}
SAFE_FAILURE_SUBSTAGES = {
    "login_request",
    "login_http",
    "login_projection",
    "context_choice",
    "context_post",
    "context_mismatch",
    "evidence_path",
}

REF_PATTERNS = {
    "class_ref": re.compile(r"^CLASS_[A-Za-z0-9][A-Za-z0-9_.-]{0,120}$"),
    "task_ref": re.compile(r"^TASK_[A-Za-z0-9][A-Za-z0-9_.-]{0,120}$"),
    "assessment_ref": re.compile(r"^ASSESS_[A-Za-z0-9][A-Za-z0-9_.-]{0,120}$"),
    "activation_ref": re.compile(r"^CACT_[A-Za-z0-9-]{36}$"),
    "bank_ref": re.compile(r"^CBANK_[A-Za-z0-9-]{36}$"),
    "bank_version_ref": re.compile(r"^CBVER_[A-Za-z0-9-]{36}$"),
    "plan_ref": re.compile(r"^CPLAN_[A-Za-z0-9-]{36}$"),
    "plan_version_ref": re.compile(r"^CPVER_[A-Za-z0-9-]{36}$"),
    "enrollment_ref": re.compile(r"^ENROLL_[A-Za-z0-9-]{36}$"),
    "item_ref": re.compile(r"^ITEM_[A-Za-z0-9][A-Za-z0-9_.-]{0,120}$"),
}
ACTIVATION_FIELDS = {
    "activation_ref",
    "plan_version_ref",
    "bank_version_ref",
    "plan_name",
    "plan_version_number",
    "bank_name",
    "bank_version_number",
    "status",
    "revision",
    "created_at",
    "revoked_at",
}
STATE_FIELDS = {
    "assessment_id",
    "subject_id",
    "status",
    "selected_item_id",
    "current_item",
    "current_index",
    "answered_count",
    "administered_count",
    "can_complete",
    "max_items",
    "cat_provider_version",
    "cat_item_bank_version",
    "cat_config_version",
}
PROGRESS_FIELDS = {
    "class_ref",
    "task_ref",
    "task_status",
    "opens_at",
    "due_at",
    "published_enrollment_count",
    "active_enrollment_count",
    "revoked_enrollment_count",
    "not_started_count",
    "created_count",
    "in_progress_count",
    "completed_count",
    "abandoned_count",
    "invalid_count",
}
CONTINUATION_FIELDS = {
    "schema_version",
    "workspace_id",
    "run_id",
    "class_ref",
    "task_refs",
    "assessment_refs",
    "activation_ref",
    "bank_ref",
    "bank_version_ref",
    "plan_ref",
    "plan_version_ref",
    "bank_version",
    "instrument_version",
    "config_version",
    "first_item_ref",
    "expected_next_item_ref",
    "response_key",
    "complete_key",
}


class HarnessError(RuntimeError):
    """Fixed safe failure; free-form messages are never serialized."""


class _Failure(HarnessError):
    def __init__(
        self,
        stage: str,
        error_class: str = "HarnessError",
        *,
        substage: str | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__("workflow failed")
        self.stage = stage
        self.error_class = (
            error_class if error_class in SAFE_FAILURE_CLASSES else "HarnessError"
        )
        self.substage = substage if substage in SAFE_FAILURE_SUBSTAGES else None
        self.http_status = (
            http_status
            if type(http_status) is int and 100 <= http_status <= 599
            else None
        )


def _failure_record(exc: _Failure) -> dict[str, Any]:
    result: dict[str, Any] = {"stage": exc.stage, "error_class": exc.error_class}
    if exc.substage is not None:
        result["substage"] = exc.substage
    if exc.http_status is not None:
        result["http_status"] = exc.http_status
    return result


def _empty_stages(phase: int) -> dict[str, str]:
    return {key: "FAIL" for key in STAGES_BY_PHASE[phase]}


def _first_pending_stage(phase: int, stages: dict[str, str]) -> str:
    return next(
        (key for key in STAGES_BY_PHASE[phase] if stages.get(key) != "PASS"),
        STAGES_BY_PHASE[phase][-1],
    )


def _safe_statuses(values: Any) -> dict[str, int]:
    if not isinstance(values, dict):
        return {}
    return {
        name: status
        for name, status in values.items()
        if name in API_STATUS_KEYS and type(status) is int and 100 <= status <= 599
    }


def _result(
    phase: int,
    stages: dict[str, str] | None = None,
    *,
    api_statuses: dict[str, int] | None = None,
    failure: dict[str, Any] | None = None,
    continuation_path: Path | None = None,
    evidence_path: Path | None = None,
) -> dict[str, Any]:
    stage_keys = STAGES_BY_PHASE[phase]
    safe_stages = {
        key: "PASS" if stages and stages.get(key) == "PASS" else "FAIL"
        for key in stage_keys
    }
    passed = all(value == "PASS" for value in safe_stages.values()) and failure is None
    result: dict[str, Any] = {
        "workflow": "school-saved-cat-task-http-qa",
        "phase": phase,
        "status": "PASS" if passed else "FAIL",
        "stages": safe_stages,
        "api_statuses": _safe_statuses(api_statuses),
    }
    if continuation_path is not None and phase == 1:
        result["continuation_path"] = str(continuation_path)
    if evidence_path is not None:
        result["evidence_path"] = str(evidence_path)
    if failure and failure.get("stage") in stage_keys:
        name = failure.get("error_class")
        result["failure"] = {
            "stage": failure["stage"],
            "error_class": name if name in SAFE_FAILURE_CLASSES else "HarnessError",
        }
        substage = failure.get("substage")
        if isinstance(substage, str) and substage in SAFE_FAILURE_SUBSTAGES:
            result["failure"]["substage"] = substage
        status = failure.get("http_status")
        if type(status) is int and 100 <= status <= 599:
            result["failure"]["http_status"] = status
    return result


def _safe_text(value: Any, maximum: int = 160) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= maximum
        and value.isascii()
        and all(character.isprintable() for character in value)
    )


def _safe_display_text(value: Any, maximum: int = 160) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= maximum
        and all(character.isprintable() for character in value)
    )


def _validate_activation(data: Any, *, status: str | None = None) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != {
        "engineering_only",
        "psychological_interpretation_allowed",
        "activation",
    }:
        raise HarnessError("activation shape")
    activation = data.get("activation")
    if (
        data.get("engineering_only") is not True
        or data.get("psychological_interpretation_allowed") is not False
        or not isinstance(activation, dict)
        or set(activation) != ACTIVATION_FIELDS
        or not REF_PATTERNS["activation_ref"].fullmatch(
            str(activation.get("activation_ref", ""))
        )
        or not REF_PATTERNS["plan_version_ref"].fullmatch(
            str(activation.get("plan_version_ref", ""))
        )
        or not REF_PATTERNS["bank_version_ref"].fullmatch(
            str(activation.get("bank_version_ref", ""))
        )
        or activation.get("status") not in {"ACTIVE", "REVOKED"}
        or status is not None
        and activation.get("status") != status
        or type(activation.get("revision")) is not int
        or type(activation.get("plan_version_number")) is not int
        or type(activation.get("bank_version_number")) is not int
        or not _safe_display_text(activation.get("plan_name"), 120)
        or not _safe_display_text(activation.get("bank_name"), 120)
        or not isinstance(activation.get("created_at"), str)
        or activation.get("revoked_at") is not None
        and not isinstance(activation.get("revoked_at"), str)
    ):
        raise HarnessError("activation metadata invalid")
    return activation


def _validate_activation_list(data: Any) -> list[dict[str, Any]]:
    if (
        not isinstance(data, dict)
        or set(data)
        != {
            "engineering_only",
            "psychological_interpretation_allowed",
            "items",
            "has_more",
        }
        or data.get("engineering_only") is not True
        or data.get("psychological_interpretation_allowed") is not False
        or not isinstance(data.get("items"), list)
        or type(data.get("has_more")) is not bool
    ):
        raise HarnessError("activation list invalid")
    for item in data["items"]:
        if not isinstance(item, dict) or set(item) != ACTIVATION_FIELDS:
            raise HarnessError("activation list metadata invalid")
        _validate_activation(
            {
                "engineering_only": True,
                "psychological_interpretation_allowed": False,
                "activation": item,
            }
        )
    return data["items"]


def _validate_continuation(value: Any, workspace_id: str) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != CONTINUATION_FIELDS
        or value.get("schema_version") != CONTINUATION_SCHEMA
        or value.get("workspace_id") != workspace_id
        or not re.fullmatch(r"[a-f0-9]{32}", str(value.get("run_id", "")))
    ):
        raise HarnessError("continuation invalid")
    for name in (
        "class_ref",
        "activation_ref",
        "bank_ref",
        "bank_version_ref",
        "plan_ref",
        "plan_version_ref",
    ):
        if not isinstance(value.get(name), str) or not REF_PATTERNS[name].fullmatch(
            value[name]
        ):
            raise HarnessError("continuation reference invalid")
    tasks = value.get("task_refs")
    assessments = value.get("assessment_refs")
    if not isinstance(tasks, dict) or set(tasks) != {"a", "b", "c"}:
        raise HarnessError("continuation tasks invalid")
    if not isinstance(assessments, dict) or set(assessments) != {"a", "b"}:
        raise HarnessError("continuation assessments invalid")
    if any(
        not REF_PATTERNS["task_ref"].fullmatch(str(item)) for item in tasks.values()
    ):
        raise HarnessError("continuation task reference invalid")
    if any(
        not REF_PATTERNS["assessment_ref"].fullmatch(str(item))
        for item in assessments.values()
    ):
        raise HarnessError("continuation assessment reference invalid")
    for name in ("first_item_ref", "expected_next_item_ref"):
        if not isinstance(value.get(name), str) or not REF_PATTERNS[
            "item_ref"
        ].fullmatch(value[name]):
            raise HarnessError("continuation item reference invalid")
    for name in ("bank_version", "instrument_version", "config_version"):
        if not _safe_text(value.get(name), 120):
            raise HarnessError("continuation version invalid")
    for name in ("response_key", "complete_key"):
        if not isinstance(value.get(name), str) or not re.fullmatch(
            r"saved-cat-task-[a-f0-9]{32}-[a-z-]+", value[name]
        ):
            raise HarnessError("continuation key invalid")
    return value


def _continuation_path(workspace: Path, path: Path) -> Path:
    if not path.is_absolute():
        raise HarnessError("continuation path invalid")
    owned_workspace._reject_reparse_path(path)
    logs = (workspace / "logs").resolve(strict=True)
    resolved = path.resolve(strict=True)
    try:
        relative = resolved.relative_to(logs)
    except ValueError:
        raise HarnessError("continuation path invalid") from None
    if (
        not resolved.is_file()
        or len(relative.parts) != 1
        or not re.fullmatch(
            re.escape(CONTINUATION_PREFIX)
            + r"[a-f0-9]{32}"
            + re.escape(CONTINUATION_SUFFIX),
            resolved.name,
        )
    ):
        raise HarnessError("continuation path invalid")
    return resolved


def _new_evidence_path(workspace: Path, run_id: str, phase: int) -> Path:
    if phase not in {1, 2} or not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise HarnessError("evidence identity invalid")
    owned_workspace._reject_reparse_path(workspace)
    logs = workspace / "logs"
    logs.mkdir(exist_ok=True)
    owned_workspace._reject_reparse_path(logs)
    workspace_root = workspace.resolve(strict=True)
    logs_root = logs.resolve(strict=True)
    if logs_root.parent != workspace_root:
        raise HarnessError("evidence directory invalid")
    path = (
        logs / f"{EVIDENCE_PREFIX}{run_id}-phase{phase}-{uuid4().hex}{EVIDENCE_SUFFIX}"
    )
    if path.exists() or path.is_symlink():
        owned_workspace._reject_reparse_path(path)
        raise HarnessError("evidence collision")
    return path


def _allocate_evidence_path(
    workspace: Path, run_id: str, phase: int
) -> tuple[Path | None, dict[str, Any] | None]:
    try:
        return _new_evidence_path(workspace, run_id, phase), None
    except Exception:  # noqa: BLE001 - expose only a fixed evidence failure.
        return None, {
            "stage": "sessions_logged_out",
            "error_class": "HarnessError",
            "substage": "evidence_path",
        }


def _evidence_path(workspace: Path, path: Path) -> Path:
    if (
        not isinstance(workspace, Path)
        or not isinstance(path, Path)
        or not path.is_absolute()
    ):
        raise HarnessError("evidence path invalid")
    owned_workspace._reject_reparse_path(workspace)
    workspace_root = workspace.resolve(strict=True)
    logs_root = (workspace / "logs").resolve(strict=True)
    owned_workspace._reject_reparse_path(workspace / "logs")
    if path.exists() or path.is_symlink():
        owned_workspace._reject_reparse_path(path)
    resolved = path.resolve(strict=False)
    try:
        relative = resolved.relative_to(logs_root)
    except ValueError:
        raise HarnessError("evidence path invalid") from None
    if (
        logs_root.parent != workspace_root
        or len(relative.parts) != 1
        or not re.fullmatch(
            re.escape(EVIDENCE_PREFIX)
            + r"[a-f0-9]{32}-phase[12]-[a-f0-9]{32}"
            + re.escape(EVIDENCE_SUFFIX),
            resolved.name,
        )
        or resolved.exists()
        or resolved.is_symlink()
    ):
        raise HarnessError("evidence path invalid")
    return resolved


def _sanitize_evidence_result(workspace: Path, result: Any) -> dict[str, Any]:
    if (
        not isinstance(result, dict)
        or result.get("workflow") != "school-saved-cat-task-http-qa"
        or type(result.get("phase")) is not int
        or result["phase"] not in STAGES_BY_PHASE
        or not isinstance(result.get("status"), str)
        or result["status"] not in {"PASS", "FAIL"}
        or not isinstance(result.get("stages"), dict)
    ):
        raise HarnessError("evidence result invalid")
    phase = result["phase"]
    stages = {
        key: "PASS" if result["stages"].get(key) == "PASS" else "FAIL"
        for key in STAGES_BY_PHASE[phase]
    }
    status = (
        "PASS"
        if result["status"] == "PASS"
        and all(value == "PASS" for value in stages.values())
        else "FAIL"
    )
    safe: dict[str, Any] = {
        "workflow": "school-saved-cat-task-http-qa",
        "phase": phase,
        "status": status,
        "stages": stages,
        "api_statuses": _safe_statuses(result.get("api_statuses")),
    }
    failure = result.get("failure")
    if isinstance(failure, dict) and failure.get("stage") in STAGES_BY_PHASE[phase]:
        error_class = failure.get("error_class")
        safe_failure = {
            "stage": failure["stage"],
            "error_class": (
                error_class
                if isinstance(error_class, str) and error_class in SAFE_FAILURE_CLASSES
                else "HarnessError"
            ),
        }
        substage = failure.get("substage")
        if isinstance(substage, str) and substage in SAFE_FAILURE_SUBSTAGES:
            safe_failure["substage"] = substage
        http_status = failure.get("http_status")
        if type(http_status) is int and 100 <= http_status <= 599:
            safe_failure["http_status"] = http_status
        safe["failure"] = safe_failure
    continuation = result.get("continuation_path")
    if continuation is not None and phase == 1:
        if not isinstance(continuation, str):
            raise HarnessError("evidence continuation invalid")
        safe["continuation_path"] = str(
            _continuation_path(workspace, Path(continuation))
        )
    return safe


def _write_evidence(workspace: Path, path: Path, result: Any) -> None:
    path = _evidence_path(workspace, path)
    safe = _sanitize_evidence_result(workspace, result)
    safe = {
        key: safe[key]
        for key in (
            "workflow",
            "phase",
            "status",
            "stages",
            "api_statuses",
            "failure",
            "continuation_path",
        )
        if key in safe
    }
    with path.open("x", encoding="utf-8") as output:
        output.write(json.dumps(safe, separators=(",", ":")) + "\n")


def _clear_credentials(credentials: dict[str, dict[str, str]] | None) -> None:
    if not isinstance(credentials, dict):
        return
    for account in credentials.values():
        if isinstance(account, dict):
            account["username"] = ""
            account["password"] = ""
    credentials.clear()


def _validate_credentials(private: Any) -> dict[str, dict[str, str]]:
    from school_browser_qa import validate_credentials

    values = validate_credentials(private)
    credentials = dict(values)
    all_slots = private.get("credentials") if isinstance(private, dict) else None
    beta = all_slots.get("beta.student") if isinstance(all_slots, dict) else None
    if not isinstance(beta, (list, tuple)) or len(beta) != 2:
        raise HarnessError("synthetic accounts unavailable")
    username, password = beta
    if (
        not isinstance(username, str)
        or not username.startswith("SYNTHETIC_")
        or not username.isascii()
        or not all(character.isalnum() or character == "_" for character in username)
        or not isinstance(password, str)
        or not 16 <= len(password) <= 512
    ):
        raise HarnessError("synthetic accounts unavailable")
    credentials["beta.student"] = {"username": username, "password": password}
    if set(credentials) != set(ACCOUNT_SCHOOL):
        raise HarnessError("synthetic account set invalid")
    return credentials


def _api_error_code(response: Any) -> str | None:
    try:
        value = response.json()
    except Exception:  # noqa: BLE001 - parsing failures become a fixed diagnostic only.
        return None
    code = value.get("code") if isinstance(value, dict) else None
    return code if isinstance(code, str) and len(code) <= 64 else None


def _expected_status(
    response: Any, expected: int, status_key: str, statuses: dict[str, int]
) -> Any:
    status = response.status_code
    statuses[status_key] = status
    if status != expected:
        raise HarnessError("HTTP status mismatch")
    return response


def _data(
    response: Any, expected: int, status_key: str, statuses: dict[str, int]
) -> Any:
    _expected_status(response, expected, status_key, statuses)
    try:
        envelope = response.json()
    except Exception:  # noqa: BLE001 - response parsing is intentionally sanitized.
        raise HarnessError("response envelope invalid") from None
    if not isinstance(envelope, dict) or not isinstance(envelope.get("data"), dict):
        raise HarnessError("response envelope invalid")
    return envelope["data"]


def _payload(
    response: Any, expected: int, status_key: str, statuses: dict[str, int]
) -> Any:
    """Read an envelope payload without assuming its resource is an object."""
    _expected_status(response, expected, status_key, statuses)
    try:
        envelope = response.json()
    except Exception:  # noqa: BLE001 - response parsing is intentionally sanitized.
        raise HarnessError("response envelope invalid") from None
    if not isinstance(envelope, dict) or "data" not in envelope:
        raise HarnessError("response envelope invalid")
    return envelope["data"]


def _expect_problem(
    response: Any,
    expected: int,
    code: str,
    status_key: str,
    statuses: dict[str, int],
) -> None:
    _expected_status(response, expected, status_key, statuses)
    if _api_error_code(response) != code:
        raise HarnessError("expected API denial mismatch")


def _header(
    session: dict[str, Any], key: str | None = None, *, csrf: bool = True
) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if csrf:
        headers["X-CSRF-Token"] = session["csrf_token"]
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _post(
    session: dict[str, Any],
    path: str,
    body: Any,
    *,
    key: str | None = None,
    csrf: bool = True,
):
    return session["client"].post(
        path, json=body, headers=_header(session, key, csrf=csrf)
    )


def _patch(
    session: dict[str, Any],
    path: str,
    body: Any,
    *,
    key: str | None = None,
    csrf: bool = True,
):
    return session["client"].patch(
        path, json=body, headers=_header(session, key, csrf=csrf)
    )


def _get(session: dict[str, Any], path: str):
    return session["client"].get(path, headers=_header(session))


def _select_context(actor: Any, slot: str) -> dict[str, str]:
    if not isinstance(actor, dict) or not isinstance(
        actor.get("available_contexts"), list
    ):
        raise HarnessError("login projection invalid")
    role = ACCOUNT_ROLES[slot]
    school_ref = ACCOUNT_SCHOOL[slot]
    matches = []
    for context in actor["available_contexts"]:
        if not isinstance(context, dict) or set(context) != {"role", "school_ref"}:
            raise HarnessError("login context projection invalid")
        if context.get("role") == role and context.get("school_ref") == school_ref:
            matches.append(context)
    if len(matches) != 1:
        raise HarnessError("active school context unavailable")
    return matches[0]


def _login(
    httpx: Any,
    credentials: dict[str, dict[str, str]],
    slot: str,
    sessions: dict[str, dict[str, Any]],
    statuses: dict[str, int],
    *,
    failure_stage: str = "specialist_login",
) -> dict[str, Any]:
    client = httpx.Client(base_url=BACKEND_URL, timeout=30, trust_env=False)
    session: dict[str, Any] = {
        "client": client,
        "csrf_token": "",
        "user_id": "",
        "school_ref": ACCOUNT_SCHOOL[slot],
    }
    sessions[slot] = session
    login_status_key = f"login_{slot.replace('.', '_')}"
    try:
        login_response = client.post(
            "/api/v1/auth/login",
            json={
                "username": credentials[slot]["username"],
                "password": credentials[slot]["password"],
            },
            headers={"Accept": "application/json"},
        )
    except Exception as exc:  # noqa: BLE001 - expose only an allowlisted error class.
        raise _Failure(
            failure_stage, type(exc).__name__, substage="login_request"
        ) from None
    try:
        auth = _data(login_response, 200, login_status_key, statuses)
    except HarnessError:
        raise _Failure(
            failure_stage,
            substage="login_http",
            http_status=statuses.get(login_status_key),
        ) from None
    actor = auth.get("actor")
    if (
        not isinstance(actor, dict)
        or not _safe_text(actor.get("user_id"), 128)
        or not isinstance(actor.get("available_contexts"), list)
        or not isinstance(auth.get("csrf_token"), str)
        or not auth["csrf_token"]
    ):
        raise _Failure(
            failure_stage,
            substage="login_projection",
            http_status=statuses.get(login_status_key),
        )
    session["csrf_token"] = auth["csrf_token"]
    session["user_id"] = actor["user_id"]
    if isinstance(actor.get("subject_id"), str):
        session["subject_id"] = actor["subject_id"]
    try:
        context = _select_context(actor, slot)
    except HarnessError:
        raise _Failure(
            failure_stage,
            substage="context_choice",
            http_status=statuses.get(login_status_key),
        ) from None
    context_status_key = f"context_{slot.replace('.', '_')}"
    try:
        active = client.post(
            "/api/v1/auth/active-context",
            json=context,
            headers=_header(session),
        )
    except Exception as exc:  # noqa: BLE001 - expose only an allowlisted error class.
        raise _Failure(
            failure_stage, type(exc).__name__, substage="context_post"
        ) from None
    try:
        selected = _data(active, 200, context_status_key, statuses)
    except HarnessError:
        raise _Failure(
            failure_stage,
            substage="context_post",
            http_status=statuses.get(context_status_key),
        ) from None
    selected_actor = selected.get("actor", selected)
    if (
        not isinstance(selected_actor, dict)
        or selected_actor.get("user_id") != session["user_id"]
        or selected_actor.get("active_context") != context
    ):
        raise _Failure(
            failure_stage,
            substage="context_mismatch",
            http_status=statuses.get(context_status_key),
        )
    if isinstance(selected_actor.get("subject_id"), str):
        session["subject_id"] = selected_actor["subject_id"]
    return session


def _logout_sessions(
    sessions: dict[str, dict[str, Any]], statuses: dict[str, int]
) -> bool:
    success = True
    for slot, session in tuple(sessions.items()):
        try:
            if session.get("csrf_token"):
                response = session["client"].post(
                    "/api/v1/auth/logout", headers=_header(session)
                )
                key = f"logout_{slot.replace('.', '_')}"
                statuses[key] = response.status_code
                success = success and response.status_code == 200
        except Exception:  # noqa: BLE001 - do not serialize logout errors or response data.
            success = False
        finally:
            session["csrf_token"] = ""
            session["user_id"] = ""
            try:
                session["client"].close()
            except Exception:  # noqa: BLE001 - do not serialize client shutdown errors.
                success = False
    sessions.clear()
    return success


def _check_flags(data: Any) -> None:
    if (
        not isinstance(data, dict)
        or data.get("engineering_only") is not True
        or data.get("psychological_interpretation_allowed") is not False
    ):
        raise HarnessError("engineering flags invalid")


def _verify_template(data: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        not isinstance(data, dict)
        or set(data)
        != {
            "engineering_only",
            "psychological_interpretation_allowed",
            "bank_document",
            "config_document",
            "item_count",
            "dimension_count",
        }
        or data.get("engineering_only") is not True
        or data.get("psychological_interpretation_allowed") is not False
        or type(data.get("item_count")) is not int
        or data["item_count"] < 3
        or data.get("dimension_count") != 1
    ):
        raise HarnessError("template shape invalid")
    bank, config = data.get("bank_document"), data.get("config_document")
    metadata = bank.get("metadata") if isinstance(bank, dict) else None
    instrument_version = (
        metadata.get("instrument_version") if isinstance(metadata, dict) else None
    )
    if (
        not isinstance(bank, dict)
        or not isinstance(config, dict)
        or not _safe_text(bank.get("version"), 120)
        or not _safe_text(instrument_version, 64)
        or bank.get("version") == instrument_version
        or not isinstance(bank.get("items"), list)
        or len(bank["items"]) != data["item_count"]
        or not all(isinstance(item, dict) for item in bank["items"])
        or type(config.get("min_items")) is not int
        or type(config.get("max_items")) is not int
    ):
        raise HarnessError("template identity invalid")
    return bank, config


def _verify_state(
    data: Any,
    *,
    assessment_ref: str,
    status: str,
    answered: int,
    bank_version: str,
    config_version: str,
    current_item_ref: str | None = None,
) -> dict[str, Any]:
    if (
        not isinstance(data, dict)
        or set(data) != STATE_FIELDS
        or data.get("assessment_id") != assessment_ref
        or data.get("status") != status
        or data.get("answered_count") != answered
        or data.get("administered_count") != answered
        or data.get("current_index") != answered
        or data.get("max_items") != 3
        or data.get("cat_item_bank_version") != bank_version
        or data.get("cat_config_version") != config_version
    ):
        raise HarnessError("assessment state mismatch")
    item = data.get("current_item")
    if answered < 3:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("item_id"), str)
            or not REF_PATTERNS["item_ref"].fullmatch(item["item_id"])
            or not isinstance(item.get("options"), list)
            or len(item["options"]) < 2
            or not all(
                isinstance(option, dict)
                and _safe_display_text(option.get("value"), 160)
                for option in item["options"]
            )
        ):
            raise HarnessError("current item invalid")
        if current_item_ref is not None and item["item_id"] != current_item_ref:
            raise HarnessError("current item did not restore")
        if data.get("selected_item_id") != item["item_id"]:
            raise HarnessError("selected item/state mismatch")
    elif item is not None or data.get("can_complete") is not True:
        raise HarnessError("CAT stopping state mismatch")
    return data


def _task_publish_data(data: Any, *, activation_ref: str, class_ref: str) -> str:
    if (
        not isinstance(data, dict)
        or data.get("class_ref") != class_ref
        or data.get("activation_ref") != activation_ref
        or data.get("cat_binding_mode") not in {None, "SAVED_VERSION"}
        or not REF_PATTERNS["task_ref"].fullmatch(str(data.get("task_ref", "")))
        or data.get("status") != "PUBLISHED"
        or data.get("plan_name") is None
        or type(data.get("plan_version_number")) is not int
    ):
        raise HarnessError("task publish binding mismatch")
    return data["task_ref"]


def _validate_continuation_result(value: Any, workspace_id: str) -> dict[str, Any]:
    return _validate_continuation(value, workspace_id)


def _prepare_owned_runtime(workspace: Path) -> dict[str, Any]:
    for module_path in (
        REPO / "11_database" / ".venv" / "Lib" / "site-packages",
        REPO / "11_database",
        REPO / "09_backend" / "src",
        REPO / "13_deployment",
    ):
        sys.path.insert(0, str(module_path))
    from school_backend import load_runtime

    marker = owned_workspace._verified_workspace()[1]
    owned_workspace._inspect_application_listeners(workspace)
    load_runtime(workspace, REPO)
    for name in tuple(os.environ):
        if name.upper().startswith(("DB_", "SMHAI_")) or name.upper() in {
            "DATABASE_URL",
            "DATABASE_KEY_FILE",
            "MYSQL_PWD",
        }:
            os.environ.pop(name, None)
    return marker


def _load_credentials(workspace: Path) -> tuple[Any, dict[str, dict[str, str]]]:
    owned_workspace._reject_reparse_path(workspace / ACCOUNT_FILE)
    from private_settings import read_private

    private = read_private(workspace / ACCOUNT_FILE)
    try:
        return private, _validate_credentials(private)
    except Exception:
        owned_workspace._clear_private_account_material(private)
        raise


def _metadata_without_private_documents(data: Any, activation_ref: str) -> None:
    items = _validate_activation_list(data)
    matching = [item for item in items if item.get("activation_ref") == activation_ref]
    if len(matching) != 1 or matching[0].get("status") != "ACTIVE":
        raise HarnessError("admin activation metadata unavailable")


def _version_document(
    data: Any, version_ref: str, bank_version: str, instrument_version: str
) -> dict[str, Any]:
    if (
        not isinstance(data, dict)
        or set(data)
        != {
            "engineering_only",
            "psychological_interpretation_allowed",
            "version",
            "bank_document",
        }
        or data.get("engineering_only") is not True
        or data.get("psychological_interpretation_allowed") is not False
        or not isinstance(data.get("version"), dict)
        or data["version"].get("version_ref") != version_ref
        or not isinstance(data.get("bank_document"), dict)
    ):
        raise HarnessError("bank version response invalid")
    document = data["bank_document"]
    metadata = document.get("metadata")
    if (
        document.get("version") != bank_version
        or not isinstance(metadata, dict)
        or metadata.get("instrument_version") != instrument_version
        or not isinstance(document.get("items"), list)
    ):
        raise HarnessError("bank version identity mismatch")
    return document


def _version_config(
    data: Any, version_ref: str, bank_version_ref: str, config_version: str
) -> dict[str, Any]:
    if (
        not isinstance(data, dict)
        or set(data)
        != {
            "engineering_only",
            "psychological_interpretation_allowed",
            "version",
            "bank_version_ref",
            "config_document",
        }
        or data.get("engineering_only") is not True
        or data.get("psychological_interpretation_allowed") is not False
        or not isinstance(data.get("version"), dict)
        or data["version"].get("version_ref") != version_ref
        or data.get("bank_version_ref") != bank_version_ref
        or not isinstance(data.get("config_document"), dict)
        or data["config_document"].get("config_version") != config_version
        or data["config_document"].get("min_items") != 3
        or data["config_document"].get("max_items") != 3
        or data["config_document"].get("se_threshold") != 0.001
    ):
        raise HarnessError("plan version identity mismatch")
    return data["config_document"]


def _choose_first_response(document: dict[str, Any], item_ref: str) -> str:
    items = [item for item in document["items"] if item.get("item_id") == item_ref]
    if len(items) != 1:
        raise HarnessError("response item unavailable")
    options = items[0].get("response_options")
    if (
        not isinstance(options, list)
        or not options
        or not _safe_display_text(options[0], 160)
    ):
        raise HarnessError("response option unavailable")
    return options[0]


def _problem_code(response: Any) -> str | None:
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - parse untrusted API errors only in memory.
        return None
    return (
        body.get("code")
        if isinstance(body, dict) and isinstance(body.get("code"), str)
        else None
    )


def _phase1(
    workspace: Path,
    marker: dict[str, Any],
    credentials: dict[str, dict[str, str]],
    stages: dict[str, str],
    statuses: dict[str, int],
    sessions: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, Path | None, str]:
    stage = "specialist_login"
    run_id = uuid4().hex
    continuation_path: Path | None = None
    specialist = _login(
        _httpx(), credentials, "alpha.psychological_specialist", sessions, statuses
    )
    stages[stage] = "PASS"

    stage = "template_verified"
    template_data = _data(
        _get(specialist, f"{ACTIVATION_API}/template"),
        200,
        "template_specialist",
        statuses,
    )
    bank_template, config_template = _verify_template(template_data)
    base_identity = bank_template["metadata"]["instrument_version"]
    stages[stage] = "PASS"

    stage = "role_csrf_and_cross_school_denials"
    admin = _login(
        _httpx(), credentials, "alpha.admin", sessions, statuses, failure_stage=stage
    )
    student = _login(
        _httpx(), credentials, "alpha.student", sessions, statuses, failure_stage=stage
    )
    teacher = _login(
        _httpx(), credentials, "alpha.teacher", sessions, statuses, failure_stage=stage
    )
    beta = _login(
        _httpx(), credentials, "beta.student", sessions, statuses, failure_stage=stage
    )
    admin_template = _get(admin, f"{ACTIVATION_API}/template")
    _expect_problem(admin_template, 403, "forbidden", "template_admin", statuses)
    teacher_template = _get(teacher, f"{ACTIVATION_API}/template")
    _expect_problem(teacher_template, 403, "forbidden", "template_teacher", statuses)
    beta_assets = _get(beta, f"{ACTIVATION_API}/activations")
    _expect_problem(beta_assets, 403, "forbidden", "beta_assets_denial", statuses)
    admin_bank_create = _post(
        admin,
        f"{ACTIVATION_API}/banks",
        {
            "display_name": "Synthetic admin write denial",
            "bank_document": bank_template,
        },
        key=f"saved-cat-task-{run_id}-admin-write-denial",
    )
    _expect_problem(admin_bank_create, 403, "forbidden", "admin_bank_denial", statuses)
    csrf_denial = _post(
        specialist,
        f"{ACTIVATION_API}/banks",
        {"display_name": "Synthetic CSRF rejection", "bank_document": bank_template},
        key=f"saved-cat-task-{run_id}-csrf-test",
        csrf=False,
    )
    _expect_problem(csrf_denial, 403, "csrf_failed", "bank_csrf_denial", statuses)
    teacher_write = _post(
        teacher,
        f"{ACTIVATION_API}/banks",
        {"display_name": "Synthetic role rejection", "bank_document": bank_template},
        key=f"saved-cat-task-{run_id}-teacher-write",
    )
    _expect_problem(teacher_write, 403, "forbidden", "teacher_bank_denial", statuses)
    stages[stage] = "PASS"

    stage = "bank_and_plan_created"
    bank_document = deepcopy(bank_template)
    bank_document["item_bank_id"] = f"ITEMBANK_saved_cat_task_{run_id[:10]}"
    bank_document["version"] = f"saved.bank.{run_id[:10]}"
    bank_document["status"] = "published"
    if bank_document.get("metadata", {}).get("instrument_version") != base_identity:
        raise _Failure(stage)
    config_document = deepcopy(config_template)
    config_document["config_version"] = f"saved.cat.task.{run_id[:10]}"
    config_document["min_items"] = 3
    config_document["max_items"] = 3
    config_document["se_threshold"] = 0.001
    bank_name = f"合成任务题库 {run_id[:8]}"
    plan_name = f"合成任务方案 {run_id[:8]}"
    bank_body = {"display_name": bank_name, "bank_document": bank_document}
    bank_data = _data(
        _post(
            specialist,
            f"{ACTIVATION_API}/banks",
            bank_body,
            key=f"saved-cat-task-{run_id}-bank",
        ),
        201,
        "bank_create",
        statuses,
    )
    _check_flags(bank_data)
    bank_meta = bank_data.get("bank")
    bank_ref = bank_meta.get("bank_ref") if isinstance(bank_meta, dict) else None
    bank_version_ref = bank_data.get("version_ref")
    if (
        not isinstance(bank_ref, str)
        or not REF_PATTERNS["bank_ref"].fullmatch(bank_ref)
        or not isinstance(bank_version_ref, str)
        or not REF_PATTERNS["bank_version_ref"].fullmatch(bank_version_ref)
        or not isinstance(bank_meta.get("versions"), list)
        or len(bank_meta["versions"]) != 1
        or bank_meta["versions"][0].get("version_ref") != bank_version_ref
        or bank_meta["versions"][0].get("item_count") != len(bank_document["items"])
    ):
        raise _Failure(stage)
    plan_body = {
        "display_name": plan_name,
        "bank_version_ref": bank_version_ref,
        "config_document": config_document,
    }
    plan_data = _data(
        _post(
            specialist,
            f"{ACTIVATION_API}/plans",
            plan_body,
            key=f"saved-cat-task-{run_id}-plan",
        ),
        201,
        "plan_create",
        statuses,
    )
    _check_flags(plan_data)
    plan_meta = plan_data.get("plan")
    plan_ref = plan_meta.get("plan_ref") if isinstance(plan_meta, dict) else None
    plan_version_ref = plan_data.get("version_ref")
    if (
        not isinstance(plan_ref, str)
        or not REF_PATTERNS["plan_ref"].fullmatch(plan_ref)
        or not isinstance(plan_version_ref, str)
        or not REF_PATTERNS["plan_version_ref"].fullmatch(plan_version_ref)
        or not isinstance(plan_meta.get("versions"), list)
        or len(plan_meta["versions"]) != 1
        or plan_meta["versions"][0].get("version_ref") != plan_version_ref
    ):
        raise _Failure(stage)
    stages[stage] = "PASS"

    stage = "activation_created_replayed_and_conflicted"
    no_csrf = _post(
        specialist,
        f"{ACTIVATION_API}/plan-versions/{plan_version_ref}/activations",
        {},
        key=f"saved-cat-task-{run_id}-activation-no-csrf",
        csrf=False,
    )
    _expect_problem(no_csrf, 403, "csrf_failed", "activation_csrf_denial", statuses)
    activation_path = f"{ACTIVATION_API}/plan-versions/{plan_version_ref}/activations"
    activation_key = f"saved-cat-task-{run_id}-activation"
    activation_data = _data(
        _post(specialist, activation_path, {}, key=activation_key),
        201,
        "activation_create",
        statuses,
    )
    activation = _validate_activation(activation_data, status="ACTIVE")
    if (
        activation["plan_version_ref"] != plan_version_ref
        or activation["bank_version_ref"] != bank_version_ref
    ):
        raise _Failure(stage)
    replay_data = _data(
        _post(specialist, activation_path, {}, key=activation_key),
        201,
        "activation_replay",
        statuses,
    )
    replayed = _validate_activation(replay_data, status="ACTIVE")
    if replayed["activation_ref"] != activation["activation_ref"]:
        raise _Failure(stage)
    duplicate = _post(
        specialist,
        activation_path,
        {},
        key=f"saved-cat-task-{run_id}-activation-duplicate",
    )
    _expect_problem(
        duplicate, 409, "workflow_conflict", "activation_duplicate", statuses
    )
    stages[stage] = "PASS"

    stage = "admin_eligible_metadata_verified"
    admin_list = _data(
        _get(admin, f"{ACTIVATION_API}/activations"),
        200,
        "activation_admin_list",
        statuses,
    )
    _check_flags(admin_list)
    activations = _validate_activation_list(admin_list)
    matching = [
        item
        for item in activations
        if item["activation_ref"] == activation["activation_ref"]
    ]
    if len(matching) != 1 or matching[0]["status"] != "ACTIVE":
        raise _Failure(stage)
    filtered_admin = _get(
        admin, f"{ACTIVATION_API}/activations?plan_version_ref={plan_version_ref}"
    )
    _expect_problem(
        filtered_admin,
        422,
        "validation_failed",
        "activation_admin_filtered_denial",
        statuses,
    )
    admin_document = _get(admin, f"{ACTIVATION_API}/bank-versions/{bank_version_ref}")
    _expect_problem(
        admin_document, 403, "forbidden", "admin_bank_document_denial", statuses
    )
    stages[stage] = "PASS"

    stage = "class_and_roster_created"
    class_ref = f"CLASS_SAVED_CAT_TASK_{run_id}"
    class_data = _data(
        _post(
            admin,
            "/api/v1/school/classes",
            {"class_ref": class_ref},
            key=f"saved-cat-task-{run_id}-class",
        ),
        201,
        "class_create",
        statuses,
    )
    if class_data.get("class_ref") != class_ref:
        raise _Failure(stage)
    _data(
        _post(
            admin,
            f"/api/v1/school/classes/{class_ref}/students",
            {"student_user_id": student["user_id"]},
            key=f"saved-cat-task-{run_id}-student",
        ),
        200,
        "student_assign",
        statuses,
    )
    _data(
        _post(
            admin,
            f"/api/v1/school/classes/{class_ref}/teachers",
            {"teacher_user_id": teacher["user_id"]},
            key=f"saved-cat-task-{run_id}-teacher",
        ),
        200,
        "teacher_assign",
        statuses,
    )
    stages[stage] = "PASS"

    stage = "three_tasks_published"
    now = datetime.now(UTC)
    task_window = {
        "opens_at": (now - timedelta(minutes=1)).isoformat(),
        "due_at": (now + timedelta(days=2)).isoformat(),
        "activation_ref": activation["activation_ref"],
    }
    task_refs: dict[str, str] = {}
    for label, status_key in (
        ("a", "task_a_publish"),
        ("b", "task_b_publish"),
        ("c", "task_c_publish"),
    ):
        task_data = _data(
            _post(
                admin,
                f"/api/v1/school/classes/{class_ref}/tasks",
                task_window,
                key=f"saved-cat-task-{run_id}-publish-{label}",
            ),
            201,
            status_key,
            statuses,
        )
        task_refs[label] = _task_publish_data(
            task_data, activation_ref=activation["activation_ref"], class_ref=class_ref
        )
    stages[stage] = "PASS"

    stage = "generic_school_assessment_denied"
    generic_body = {
        "subject_id": "SUBJ_synthetic_invalid-placeholder",
        "instrument_id": "synthetic-only",
        "instrument_version": "engineering-only",
    }
    # subject_id is validated before the role gate; use the active student's
    # server-issued SUBJECT reference without writing it to continuation/evidence.
    student_subject = student.get("subject_id")
    if not isinstance(student_subject, str) or not student_subject.startswith("SUBJ_"):
        raise _Failure(stage)
    generic_body["subject_id"] = student_subject
    generic_key = f"saved-cat-task-{run_id}-generic-start"
    first_generic = _post(student, "/api/v1/assessments", generic_body, key=generic_key)
    _expect_problem(first_generic, 403, "forbidden", "generic_create_first", statuses)
    same_generic = _post(student, "/api/v1/assessments", generic_body, key=generic_key)
    _expect_problem(same_generic, 403, "forbidden", "generic_create_same_key", statuses)
    beta_denial = _post(
        beta,
        f"/api/v1/school/tasks/{task_refs['a']}/start",
        {},
        key=f"saved-cat-task-{run_id}-beta-start",
    )
    _expect_problem(beta_denial, 404, "resource_not_found", "beta_task_start", statuses)
    stages[stage] = "PASS"

    stage = "task_a_started_and_first_response_saved"
    start_data = _data(
        _post(
            student,
            f"/api/v1/school/tasks/{task_refs['a']}/start",
            {},
            key=f"saved-cat-task-{run_id}-start-a",
        ),
        200,
        "task_a_start",
        statuses,
    )
    assessment_a = start_data.get("assessment_id")
    if (
        not REF_PATTERNS["assessment_ref"].fullmatch(str(assessment_a))
        or start_data.get("task_ref") != task_refs["a"]
    ):
        raise _Failure(stage)
    state0 = _data(
        _get(student, f"/api/v1/assessments/{assessment_a}/state"),
        200,
        "task_a_state_initial",
        statuses,
    )
    state0 = _verify_state(
        state0,
        assessment_ref=assessment_a,
        status="created",
        answered=0,
        bank_version=bank_document["version"],
        config_version=config_document["config_version"],
    )
    initial_item = state0["current_item"]
    first_item_ref = initial_item["item_id"]
    first_option_value = initial_item["options"][0]["value"]
    response_key = f"saved-cat-task-{run_id}-response-first"
    response_data = _data(
        _post(
            student,
            f"/api/v1/assessments/{assessment_a}/responses",
            {"item_id": first_item_ref, "response": first_option_value},
            key=response_key,
        ),
        200,
        "task_a_response_1",
        statuses,
    )
    after_first = _verify_state(
        response_data,
        assessment_ref=assessment_a,
        status="in_progress",
        answered=1,
        bank_version=bank_document["version"],
        config_version=config_document["config_version"],
    )
    expected_next = after_first["current_item"]["item_id"]
    _verify_state(
        _data(
            _get(student, f"/api/v1/assessments/{assessment_a}/state"),
            200,
            "task_a_state_after_response",
            statuses,
        ),
        assessment_ref=assessment_a,
        status="in_progress",
        answered=1,
        bank_version=bank_document["version"],
        config_version=config_document["config_version"],
        current_item_ref=expected_next,
    )
    stages[stage] = "PASS"

    stage = "task_b_created_without_responses"
    start_b = _data(
        _post(
            student,
            f"/api/v1/school/tasks/{task_refs['b']}/start",
            {},
            key=f"saved-cat-task-{run_id}-start-b",
        ),
        200,
        "task_b_start",
        statuses,
    )
    assessment_b = start_b.get("assessment_id")
    if not isinstance(assessment_b, str) or not REF_PATTERNS[
        "assessment_ref"
    ].fullmatch(assessment_b):
        raise _Failure(stage)
    _verify_state(
        _data(
            _get(student, f"/api/v1/assessments/{assessment_b}/state"),
            200,
            "task_b_state_initial",
            statuses,
        ),
        assessment_ref=assessment_b,
        status="created",
        answered=0,
        bank_version=bank_document["version"],
        config_version=config_document["config_version"],
    )
    stages[stage] = "PASS"

    stage = "activation_revoked_and_assets_archived"
    revoked_data = _data(
        _patch(
            specialist,
            f"{ACTIVATION_API}/activations/{activation['activation_ref']}",
            {"expected_revision": activation["revision"], "status": "REVOKED"},
            key=f"saved-cat-task-{run_id}-revoke-activation",
        ),
        200,
        "activation_revoke",
        statuses,
    )
    revoked = _validate_activation(revoked_data, status="REVOKED")
    if revoked["revision"] != activation["revision"] + 1:
        raise _Failure(stage)
    plan_patch = _data(
        _patch(
            specialist,
            f"{ACTIVATION_API}/plans/{plan_ref}",
            {"expected_revision": 1, "status": "ARCHIVED"},
            key=f"saved-cat-task-{run_id}-archive-plan",
        ),
        200,
        "plan_archive",
        statuses,
    )
    _check_flags(plan_patch)
    bank_patch = _data(
        _patch(
            specialist,
            f"{ACTIVATION_API}/banks/{bank_ref}",
            {"expected_revision": 1, "status": "ARCHIVED"},
            key=f"saved-cat-task-{run_id}-archive-bank",
        ),
        200,
        "bank_archive",
        statuses,
    )
    _check_flags(bank_patch)
    stages[stage] = "PASS"

    stage = "in_progress_task_retained"
    state_after_revoke = _verify_state(
        _data(
            _get(student, f"/api/v1/assessments/{assessment_a}/state"),
            200,
            "task_a_state_after_revoke",
            statuses,
        ),
        assessment_ref=assessment_a,
        status="in_progress",
        answered=1,
        bank_version=bank_document["version"],
        config_version=config_document["config_version"],
        current_item_ref=expected_next,
    )
    del state_after_revoke
    stages[stage] = "PASS"

    stage = "created_task_blocked"
    blocked_b = _get(student, f"/api/v1/assessments/{assessment_b}/state")
    _expect_problem(
        blocked_b, 409, "workflow_conflict", "task_b_state_after_revoke", statuses
    )
    stages[stage] = "PASS"

    stage = "unstarted_task_blocked"
    blocked_c = _post(
        student,
        f"/api/v1/school/tasks/{task_refs['c']}/start",
        {},
        key=f"saved-cat-task-{run_id}-start-c-after-revoke",
    )
    _expect_problem(
        blocked_c, 409, "workflow_conflict", "task_c_start_after_revoke", statuses
    )
    stages[stage] = "PASS"

    stage = "new_publish_blocked"
    blocked_publish = _post(
        admin,
        f"/api/v1/school/classes/{class_ref}/tasks",
        task_window,
        key=f"saved-cat-task-{run_id}-publish-d-after-revoke",
    )
    _expect_problem(
        blocked_publish,
        409,
        "workflow_conflict",
        "task_d_publish_after_revoke",
        statuses,
    )
    admin_after_revoke = _data(
        _get(admin, f"{ACTIVATION_API}/activations"),
        200,
        "activation_admin_list_after_revoke",
        statuses,
    )
    _check_flags(admin_after_revoke)
    if any(
        item["activation_ref"] == activation["activation_ref"]
        for item in _validate_activation_list(admin_after_revoke)
    ):
        raise _Failure(stage)
    stages[stage] = "PASS"

    continuation = {
        "schema_version": CONTINUATION_SCHEMA,
        "workspace_id": marker["workspace_id"],
        "run_id": run_id,
        "class_ref": class_ref,
        "task_refs": task_refs,
        "assessment_refs": {"a": assessment_a, "b": assessment_b},
        "activation_ref": activation["activation_ref"],
        "bank_ref": bank_ref,
        "bank_version_ref": bank_version_ref,
        "plan_ref": plan_ref,
        "plan_version_ref": plan_version_ref,
        "bank_version": bank_document["version"],
        "instrument_version": base_identity,
        "config_version": config_document["config_version"],
        "first_item_ref": first_item_ref,
        "expected_next_item_ref": expected_next,
        "response_key": response_key,
        "complete_key": f"saved-cat-task-{run_id}-complete",
    }
    _validate_continuation(continuation, marker["workspace_id"])
    continuation_path = (
        workspace / "logs" / f"{CONTINUATION_PREFIX}{run_id}{CONTINUATION_SUFFIX}"
    )
    from private_settings import write_private

    write_private(continuation_path, continuation, exclusive=True)
    return continuation, continuation_path, stage


def _phase2(
    workspace: Path,
    marker: dict[str, Any],
    continuation: dict[str, Any],
    credentials: dict[str, dict[str, str]],
    stages: dict[str, str],
    statuses: dict[str, int],
    sessions: dict[str, dict[str, Any]],
) -> str:
    stage = "saved_version_and_history_verified"
    specialist = _login(
        _httpx(),
        credentials,
        "alpha.psychological_specialist",
        sessions,
        statuses,
        failure_stage=stage,
    )
    bank_data = _data(
        _get(
            specialist,
            f"{ACTIVATION_API}/bank-versions/{continuation['bank_version_ref']}",
        ),
        200,
        "bank_version_read",
        statuses,
    )
    bank_document = _version_document(
        bank_data,
        continuation["bank_version_ref"],
        continuation["bank_version"],
        continuation["instrument_version"],
    )
    plan_data = _data(
        _get(
            specialist,
            f"{ACTIVATION_API}/plan-versions/{continuation['plan_version_ref']}",
        ),
        200,
        "plan_version_read",
        statuses,
    )
    _version_config(
        plan_data,
        continuation["plan_version_ref"],
        continuation["bank_version_ref"],
        continuation["config_version"],
    )
    history_data = _data(
        _get(
            specialist,
            f"{ACTIVATION_API}/activations?plan_version_ref={continuation['plan_version_ref']}",
        ),
        200,
        "activation_history_read",
        statuses,
    )
    _check_flags(history_data)
    history = _validate_activation_list(history_data)
    historical = [
        item
        for item in history
        if item["activation_ref"] == continuation["activation_ref"]
    ]
    if len(historical) != 1 or historical[0]["status"] != "REVOKED":
        raise _Failure(stage)
    stages[stage] = "PASS"
    response_value = _choose_first_response(
        bank_document, continuation["first_item_ref"]
    )

    admin = _login(
        _httpx(),
        credentials,
        "alpha.admin",
        sessions,
        statuses,
        failure_stage="admin_metadata_excludes_revoked_activation",
    )
    admin_activations = _data(
        _get(admin, f"{ACTIVATION_API}/activations"),
        200,
        "activation_admin_list_after_revoke",
        statuses,
    )
    _check_flags(admin_activations)
    if any(
        item["activation_ref"] == continuation["activation_ref"]
        for item in _validate_activation_list(admin_activations)
    ):
        raise _Failure("admin_metadata_excludes_revoked_activation")
    stages["admin_metadata_excludes_revoked_activation"] = "PASS"

    stage = "cat_restart_restored_exact_session"
    student = _login(
        _httpx(),
        credentials,
        "alpha.student",
        sessions,
        statuses,
        failure_stage=stage,
    )
    assessment_a = continuation["assessment_refs"]["a"]
    state = _verify_state(
        _data(
            _get(student, f"/api/v1/assessments/{assessment_a}/state"),
            200,
            "task_a_state_after_cat_restart",
            statuses,
        ),
        assessment_ref=assessment_a,
        status="in_progress",
        answered=1,
        bank_version=continuation["bank_version"],
        config_version=continuation["config_version"],
        current_item_ref=continuation["expected_next_item_ref"],
    )
    stages[stage] = "PASS"

    stage = "remaining_responses_saved_and_completed"
    current = state["current_item"]
    for index, status_key in ((2, "task_a_response_2"), (3, "task_a_response_3")):
        if current is None or current.get("item_id") is None:
            raise _Failure(stage)
        chosen = current["options"][0]["value"]
        response_key = f"saved-cat-task-{continuation['run_id']}-response-{index}"
        progress = _data(
            _post(
                student,
                f"/api/v1/assessments/{assessment_a}/responses",
                {"item_id": current["item_id"], "response": chosen},
                key=response_key,
            ),
            200,
            status_key,
            statuses,
        )
        verified = _verify_state(
            progress,
            assessment_ref=assessment_a,
            status="in_progress",
            answered=index,
            bank_version=continuation["bank_version"],
            config_version=continuation["config_version"],
        )
        if index == 2:
            _verify_state(
                _data(
                    _get(student, f"/api/v1/assessments/{assessment_a}/state"),
                    200,
                    "task_a_state_after_response_2",
                    statuses,
                ),
                assessment_ref=assessment_a,
                status="in_progress",
                answered=2,
                bank_version=continuation["bank_version"],
                config_version=continuation["config_version"],
                current_item_ref=verified["current_item"]["item_id"],
            )
            current = verified["current_item"]
        else:
            current = verified["current_item"]
    completion = _data(
        _post(
            student,
            f"/api/v1/assessments/{assessment_a}/complete",
            {},
            key=continuation["complete_key"],
        ),
        200,
        "task_a_complete",
        statuses,
    )
    if not isinstance(completion, dict) or completion.get("status") != "completed":
        raise _Failure(stage)
    stages[stage] = "PASS"

    stage = "frozen_result_provenance_verified"
    if (
        set(completion)
        != {
            "schema_version",
            "assessment_id",
            "subject_id",
            "instrument",
            "population_scope",
            "status",
            "dimensions",
            "risk",
            "response_summary",
            "provenance",
            "timestamps",
        }
        or completion.get("schema_version") != "assessment.v1"
        or completion.get("assessment_id") != assessment_a
        or not isinstance(completion.get("instrument"), dict)
        or completion["instrument"].get("version") != continuation["instrument_version"]
        or not isinstance(completion.get("provenance"), dict)
        or completion["provenance"].get("item_bank_version")
        != continuation["bank_version"]
        or not isinstance(completion.get("response_summary"), dict)
        or completion["response_summary"].get("items_answered") != 3
    ):
        raise _Failure(stage)
    completed_state = _data(
        _get(student, f"/api/v1/assessments/{assessment_a}/state"),
        200,
        "task_a_completed_state",
        statuses,
    )
    if (
        completed_state.get("assessment_id") != assessment_a
        or completed_state.get("status") != "completed"
        or completed_state.get("cat_item_bank_version") != continuation["bank_version"]
        or completed_state.get("cat_config_version") != continuation["config_version"]
    ):
        raise _Failure(stage)
    stages[stage] = "PASS"

    stage = "teacher_aggregate_only_verified"
    teacher = _login(
        _httpx(),
        credentials,
        "alpha.teacher",
        sessions,
        statuses,
        failure_stage=stage,
    )
    progress_data = _payload(
        _get(teacher, "/api/v1/school/teacher/task-progress"),
        200,
        "teacher_progress_completed",
        statuses,
    )
    if not isinstance(progress_data, list):
        raise _Failure(stage)
    rows = [
        row
        for row in progress_data
        if isinstance(row, dict)
        and row.get("task_ref") == continuation["task_refs"]["a"]
    ]
    if (
        len(rows) != 1
        or set(rows[0]) != PROGRESS_FIELDS
        or rows[0].get("completed_count") != 1
        or rows[0].get("active_enrollment_count") != 1
        or rows[0].get("revoked_enrollment_count") != 0
    ):
        raise _Failure(stage)
    stages[stage] = "PASS"

    admin = sessions["alpha.admin"]
    stage = "enrollment_revoked"
    enrollment_data = _payload(
        _get(
            admin, f"/api/v1/school/tasks/{continuation['task_refs']['a']}/enrollments"
        ),
        200,
        "task_a_enrollment_list",
        statuses,
    )
    if not isinstance(enrollment_data, list):
        raise _Failure(stage)
    if any(
        not isinstance(row, dict) or set(row) != {"enrollment_ref", "status"}
        for row in enrollment_data
    ):
        raise _Failure(stage)
    active = [
        row
        for row in enrollment_data
        if isinstance(row, dict) and row.get("status") == "ACTIVE"
    ]
    if len(active) != 1 or not REF_PATTERNS["enrollment_ref"].fullmatch(
        str(active[0].get("enrollment_ref", ""))
    ):
        raise _Failure(stage)
    enrollment_ref = active[0]["enrollment_ref"]
    revoke = _post(
        admin,
        f"/api/v1/school/tasks/{continuation['task_refs']['a']}/enrollments/{enrollment_ref}/revoke",
        {},
        key=f"saved-cat-task-{continuation['run_id']}-enrollment-revoke",
    )
    _expected_status(revoke, 200, "task_a_enrollment_revoke", statuses)
    revoke_data = revoke.json().get("data") if isinstance(revoke.json(), dict) else None
    if not isinstance(revoke_data, dict) or revoke_data.get("status") != "REVOKED":
        raise _Failure(stage)
    stages[stage] = "PASS"

    stage = "cached_response_replay_denied"
    cached_response = _post(
        student,
        f"/api/v1/assessments/{assessment_a}/responses",
        {"item_id": continuation["first_item_ref"], "response": response_value},
        key=continuation["response_key"],
    )
    _expect_problem(
        cached_response,
        404,
        "resource_not_found",
        "cached_response_after_revoke",
        statuses,
    )
    stages[stage] = "PASS"

    stage = "cached_completion_replay_denied"
    cached_complete = _post(
        student,
        f"/api/v1/assessments/{assessment_a}/complete",
        {},
        key=continuation["complete_key"],
    )
    _expect_problem(
        cached_complete,
        404,
        "resource_not_found",
        "cached_complete_after_revoke",
        statuses,
    )
    stages[stage] = "PASS"

    stage = "state_read_denied"
    denied_state = _get(student, f"/api/v1/assessments/{assessment_a}/state")
    _expect_problem(
        denied_state,
        404,
        "resource_not_found",
        "task_a_state_after_enrollment_revoke",
        statuses,
    )
    stages[stage] = "PASS"

    stage = "student_metadata_excludes_revoked_assessment"
    own_metadata = _payload(
        _get(student, "/api/v1/school/assessments?limit=100"),
        200,
        "student_assessment_metadata_after_revoke",
        statuses,
    )
    if (
        not isinstance(own_metadata, list)
        or any(
            not isinstance(row, dict)
            or set(row)
            != {
                "assessment_id",
                "status",
                "items_answered",
                "started_at",
                "completed_at",
            }
            for row in own_metadata
        )
        or any(row["assessment_id"] == assessment_a for row in own_metadata)
    ):
        raise _Failure(stage)
    history = _payload(
        _get(student, "/api/v1/school/tasks/student/history"),
        200,
        "student_task_history_after_revoke",
        statuses,
    )
    if not isinstance(history, list):
        raise _Failure(stage)
    history_a = [
        row
        for row in history
        if isinstance(row, dict)
        and row.get("task_ref") == continuation["task_refs"]["a"]
    ]
    if (
        len(history_a) != 1
        or set(history_a[0])
        != {
            "task_ref",
            "class_ref",
            "task_status",
            "enrollment_status",
            "assessment_status",
            "started_at",
            "completed_at",
        }
        or history_a[0].get("enrollment_status") != "REVOKED"
        or history_a[0].get("assessment_status") != "completed"
        or {"assessment_id", "subject_id", "score", "responses", "report"}.intersection(
            history_a[0]
        )
    ):
        raise _Failure(stage)
    stages[stage] = "PASS"
    return stage


def _httpx() -> Any:
    import httpx

    return httpx


def _preflight(
    workspace: Path,
) -> tuple[dict[str, Any], Any, dict[str, dict[str, str]]]:
    marker = _prepare_owned_runtime(workspace)
    private, credentials = _load_credentials(workspace)
    owned_workspace._clear_private_account_material(private)
    return marker, private, credentials


def run_phase1() -> dict[str, Any]:
    phase = 1
    stages = _empty_stages(phase)
    statuses: dict[str, int] = {}
    sessions: dict[str, dict[str, Any]] = {}
    credentials: dict[str, dict[str, str]] | None = None
    private: Any = None
    evidence_path: Path | None = None
    continuation_path: Path | None = None
    continuation: dict[str, Any] | None = None
    failure_stage = "workspace_owned"
    failure: dict[str, Any] | None = None
    workspace: Path | None = None
    try:
        workspace, marker = owned_workspace._verified_workspace()
        stages["workspace_owned"] = "PASS"
        failure_stage = "owned_processes_verified"
        owned_workspace._inspect_application_listeners(workspace)
        stages[failure_stage] = "PASS"
        failure_stage = "backend_runtime_verified"
        _prepare_owned_runtime(workspace)
        stages[failure_stage] = "PASS"
        failure_stage = "credentials_loaded"
        private, credentials = _load_credentials(workspace)
        owned_workspace._clear_private_account_material(private)
        private = None
        stages[failure_stage] = "PASS"
        continuation, continuation_path, failure_stage = _phase1(
            workspace, marker, credentials, stages, statuses, sessions
        )
        stages["continuation_sealed"] = "PASS"
    except _Failure as exc:
        failure = _failure_record(exc)
    except Exception as exc:  # noqa: BLE001 - only a fixed safe class is exposed.
        name = type(exc).__name__
        failure = {
            "stage": _first_pending_stage(phase, stages),
            "error_class": name if name in SAFE_FAILURE_CLASSES else "HarnessError",
        }
    finally:
        logged_out = _logout_sessions(sessions, statuses)
        stages["sessions_logged_out"] = (
            "PASS" if logged_out and sessions == {} else "FAIL"
        )
        owned_workspace._clear_private_account_material(private)
        _clear_credentials(credentials)
    if workspace is not None:
        run_id = continuation["run_id"] if continuation else uuid4().hex
        evidence_path, evidence_failure = _allocate_evidence_path(
            workspace, run_id, phase
        )
        if failure is None:
            failure = evidence_failure
    result = _result(
        phase,
        stages,
        api_statuses=statuses,
        failure=failure,
        continuation_path=continuation_path,
        evidence_path=evidence_path,
    )
    if evidence_path is not None:
        try:
            _write_evidence(workspace, evidence_path, result)
        except Exception:  # noqa: BLE001 - evidence failure is a fixed status only.
            result = _result(
                phase,
                stages,
                api_statuses=statuses,
                failure=failure
                or {
                    "stage": "sessions_logged_out",
                    "error_class": "HarnessError",
                    "substage": "evidence_path",
                },
                continuation_path=continuation_path,
            )
    return result


def run_phase2(continuation_arg: Path) -> dict[str, Any]:
    phase = 2
    stages = _empty_stages(phase)
    statuses: dict[str, int] = {}
    sessions: dict[str, dict[str, Any]] = {}
    credentials: dict[str, dict[str, str]] | None = None
    private: Any = None
    failure_stage = "workspace_owned"
    failure: dict[str, Any] | None = None
    workspace: Path | None = None
    continuation: dict[str, Any] | None = None
    validated_state_path: Path | None = None
    try:
        workspace, marker = owned_workspace._verified_workspace()
        stages["workspace_owned"] = "PASS"
        failure_stage = "owned_processes_verified"
        owned_workspace._inspect_application_listeners(workspace)
        stages[failure_stage] = "PASS"
        failure_stage = "backend_runtime_verified"
        _prepare_owned_runtime(workspace)
        stages[failure_stage] = "PASS"
        failure_stage = "continuation_loaded"
        state_path = _continuation_path(workspace, continuation_arg)
        validated_state_path = state_path
        from private_settings import read_private

        private = read_private(state_path)
        continuation = _validate_continuation(private, marker["workspace_id"])
        stages[failure_stage] = "PASS"
        failure_stage = "credentials_loaded"
        credentials = _validate_credentials_from_file(workspace)
        stages[failure_stage] = "PASS"
        failure_stage = _phase2(
            workspace,
            marker,
            continuation,
            credentials,
            stages,
            statuses,
            sessions,
        )
    except _Failure as exc:
        failure = _failure_record(exc)
    except Exception as exc:  # noqa: BLE001 - only a fixed safe class is exposed.
        name = type(exc).__name__
        failure = {
            "stage": _first_pending_stage(phase, stages),
            "error_class": name if name in SAFE_FAILURE_CLASSES else "HarnessError",
        }
    finally:
        logged_out = _logout_sessions(sessions, statuses)
        stages["sessions_logged_out"] = (
            "PASS" if logged_out and sessions == {} else "FAIL"
        )
        owned_workspace._clear_private_account_material(private)
        _clear_credentials(credentials)
    evidence_path: Path | None = None
    if workspace is not None:
        run_id = continuation["run_id"] if continuation else uuid4().hex
        evidence_path, evidence_failure = _allocate_evidence_path(
            workspace, run_id, phase
        )
        if failure is None:
            failure = evidence_failure
    result = _result(
        phase,
        stages,
        api_statuses=statuses,
        failure=failure,
        continuation_path=validated_state_path,
        evidence_path=evidence_path,
    )
    if evidence_path is not None:
        try:
            _write_evidence(workspace, evidence_path, result)
        except Exception:  # noqa: BLE001 - evidence failure is a fixed status only.
            result = _result(
                phase,
                stages,
                api_statuses=statuses,
                failure=failure
                or {
                    "stage": "sessions_logged_out",
                    "error_class": "HarnessError",
                    "substage": "evidence_path",
                },
                continuation_path=validated_state_path,
            )
    return result


def _validate_credentials_from_file(workspace: Path) -> dict[str, dict[str, str]]:
    private, credentials = _load_credentials(workspace)
    owned_workspace._clear_private_account_material(private)
    return credentials


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("1", "2"), required=True)
    parser.add_argument("--continuation", type=Path)
    args = parser.parse_args(argv)
    if args.phase == "1" and args.continuation is not None:
        print(json.dumps(_result(1, _empty_stages(1)), separators=(",", ":")))
        return 2
    if args.phase == "2" and args.continuation is None:
        print(json.dumps(_result(2, _empty_stages(2)), separators=(",", ":")))
        return 2
    result = run_phase1() if args.phase == "1" else run_phase2(args.continuation)
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
