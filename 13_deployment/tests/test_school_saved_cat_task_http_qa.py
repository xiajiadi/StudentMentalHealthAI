import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(REPO / "09_backend" / "src"))
import school_saved_cat_task_http_qa as qa
from smhai_backend.domains.auth.schemas import ActorDto


def _continuation(workspace_id="workspace-safe"):
    run_id = "a" * 32
    return {
        "schema_version": qa.CONTINUATION_SCHEMA,
        "workspace_id": workspace_id,
        "run_id": run_id,
        "class_ref": "CLASS_SYNTHETIC_TASK",
        "task_refs": {
            name: f"TASK_SYNTHETIC_{name.upper()}" for name in ("a", "b", "c")
        },
        "assessment_refs": {
            name: f"ASSESS_SYNTHETIC_{name.upper()}" for name in ("a", "b")
        },
        "activation_ref": "CACT_00000000-0000-0000-0000-000000000001",
        "bank_ref": "CBANK_00000000-0000-0000-0000-000000000002",
        "bank_version_ref": "CBVER_00000000-0000-0000-0000-000000000003",
        "plan_ref": "CPLAN_00000000-0000-0000-0000-000000000004",
        "plan_version_ref": "CPVER_00000000-0000-0000-0000-000000000005",
        "bank_version": "saved.bank.synthetic",
        "instrument_version": "synthetic_item_bank.v1 / demo.v1",
        "config_version": "saved.cat.synthetic",
        "first_item_ref": "ITEM_SYNTHETIC_1",
        "expected_next_item_ref": "ITEM_SYNTHETIC_2",
        "response_key": f"saved-cat-task-{run_id}-response-first",
        "complete_key": f"saved-cat-task-{run_id}-complete",
    }


def _activation(status="ACTIVE"):
    return {
        "activation_ref": "CACT_00000000-0000-0000-0000-000000000001",
        "plan_version_ref": "CPVER_00000000-0000-0000-0000-000000000005",
        "bank_version_ref": "CBVER_00000000-0000-0000-0000-000000000003",
        "plan_name": "合成方案",
        "plan_version_number": 1,
        "bank_name": "合成题库",
        "bank_version_number": 1,
        "status": status,
        "revision": 2 if status == "REVOKED" else 1,
        "created_at": "2026-10-13T00:00:00Z",
        "revoked_at": "2026-10-13T00:01:00Z" if status == "REVOKED" else None,
    }


def test_continuation_contains_only_exact_refs_versions_and_idempotency_keys():
    value = _continuation()
    assert qa._validate_continuation(value, "workspace-safe") is value
    assert "answer" not in json.dumps(value).lower()
    for forbidden in (
        "cookies",
        "password",
        "credential",
        "response_value",
        "responses",
    ):
        changed = dict(value)
        changed[forbidden] = "secret-sentinel"
        with pytest.raises(qa.HarnessError):
            qa._validate_continuation(changed, "workspace-safe")


def test_continuation_rejects_wrong_workspace_and_malformed_reference():
    with pytest.raises(qa.HarnessError):
        qa._validate_continuation(_continuation(), "another-workspace")
    value = _continuation()
    value["expected_next_item_ref"] = "private-item-id"
    with pytest.raises(qa.HarnessError):
        qa._validate_continuation(value, "workspace-safe")


def test_activation_metadata_is_exact_and_never_accepts_documents():
    wrapped = {
        "engineering_only": True,
        "psychological_interpretation_allowed": False,
        "activation": _activation(),
    }
    assert qa._validate_activation(wrapped, status="ACTIVE")["status"] == "ACTIVE"
    wrapped["activation"]["bank_document"] = {"private": "sentinel"}
    with pytest.raises(qa.HarnessError):
        qa._validate_activation(wrapped)


def test_template_preserves_distinct_bank_version_and_instrument_identity():
    template = {
        "engineering_only": True,
        "psychological_interpretation_allowed": False,
        "item_count": 3,
        "dimension_count": 1,
        "bank_document": {
            "version": "demo.v1",
            "metadata": {"instrument_version": "synthetic_item_bank.v1 / demo.v1"},
            "items": [{"item_id": f"ITEM_SYNTHETIC_{i}"} for i in range(1, 4)],
        },
        "config_document": {"min_items": 3, "max_items": 3},
    }
    bank, _ = qa._verify_template(template)
    assert bank["version"] != bank["metadata"]["instrument_version"]
    bank["metadata"]["instrument_version"] = bank["version"]
    with pytest.raises(qa.HarnessError):
        qa._verify_template(template)


def test_state_projection_checks_version_bound_ordered_resume():
    state = {
        "assessment_id": "ASSESS_SYNTHETIC_A",
        "subject_id": "SUBJ_SYNTHETIC_A",
        "status": "in_progress",
        "selected_item_id": "ITEM_SYNTHETIC_2",
        "current_item": {
            "item_id": "ITEM_SYNTHETIC_2",
            "options": [{"value": "never"}, {"value": "often"}],
        },
        "current_index": 1,
        "answered_count": 1,
        "administered_count": 1,
        "can_complete": False,
        "max_items": 3,
        "cat_provider_version": "1.0",
        "cat_item_bank_version": "saved.bank.synthetic",
        "cat_config_version": "saved.cat.synthetic",
    }
    qa._verify_state(
        state,
        assessment_ref="ASSESS_SYNTHETIC_A",
        status="in_progress",
        answered=1,
        bank_version="saved.bank.synthetic",
        config_version="saved.cat.synthetic",
        current_item_ref="ITEM_SYNTHETIC_2",
    )
    state["current_index"] = 0
    with pytest.raises(qa.HarnessError):
        qa._verify_state(
            state,
            assessment_ref="ASSESS_SYNTHETIC_A",
            status="in_progress",
            answered=1,
            bank_version="saved.bank.synthetic",
            config_version="saved.cat.synthetic",
            current_item_ref="ITEM_SYNTHETIC_2",
        )


def test_list_payload_accepts_arrays_and_rejects_missing_envelope_data():
    response = SimpleNamespace(
        status_code=200, json=lambda: {"data": [{"task_ref": "TASK_SYNTHETIC_A"}]}
    )
    statuses = {}
    assert qa._payload(response, 200, "teacher_progress_completed", statuses) == [
        {"task_ref": "TASK_SYNTHETIC_A"}
    ]
    assert statuses == {"teacher_progress_completed": 200}
    malformed = SimpleNamespace(status_code=200, json=lambda: {"payload": []})
    with pytest.raises(qa.HarnessError):
        qa._payload(malformed, 200, "teacher_progress_completed", {})


def test_mutation_helpers_use_expected_methods_and_security_headers():
    class Client:
        def __init__(self):
            self.call = None

        def patch(self, path, **kwargs):
            self.call = ("PATCH", path, kwargs)
            return "response"

        def post(self, path, **kwargs):
            self.call = ("POST", path, kwargs)
            return "response"

    client = Client()
    session = {"client": client, "csrf_token": "csrf-safe"}
    assert (
        qa._patch(
            session, "/resource/CACT_safe", {"expected_revision": 1}, key="stable-key"
        )
        == "response"
    )
    method, path, kwargs = client.call
    assert method == "PATCH" and path == "/resource/CACT_safe"
    assert kwargs["headers"]["X-CSRF-Token"] == "csrf-safe"
    assert kwargs["headers"]["Idempotency-Key"] == "stable-key"


def test_error_result_and_evidence_keep_only_allowlisted_diagnostics(
    tmp_path, monkeypatch
):
    stages = qa._empty_stages(2)
    stages["workspace_owned"] = "PASS"
    result = qa._result(
        2,
        stages,
        api_statuses={"task_a_state_after_cat_restart": 409, "untrusted_key": 201},
        failure={
            "stage": "saved_version_and_history_verified",
            "error_class": "TimeoutError",
            "message": "secret-sentinel",
        },
    )
    workspace = tmp_path / "owned"
    (workspace / "logs").mkdir(parents=True)
    evidence = (
        workspace / "logs" / f"{qa.EVIDENCE_PREFIX}{'a' * 32}-phase2-{'b' * 32}.json"
    )
    monkeypatch.setattr(qa.owned_workspace, "_reject_reparse_path", lambda path: None)
    qa._write_evidence(workspace, evidence, result)
    stored = evidence.read_text(encoding="utf-8")
    decoded = json.loads(stored)
    assert decoded["api_statuses"] == {"task_a_state_after_cat_restart": 409}
    assert decoded["failure"] == {
        "stage": "saved_version_and_history_verified",
        "error_class": "TimeoutError",
    }
    assert "secret-sentinel" not in stored
    assert "untrusted_key" not in stored


def test_failure_stage_selects_first_unfinished_fixed_stage():
    stages = qa._empty_stages(2)
    stages["workspace_owned"] = "PASS"
    stages["owned_processes_verified"] = "PASS"
    assert qa._first_pending_stage(2, stages) == "backend_runtime_verified"


def test_login_context_selection_uses_real_seed_refs_and_auth_actor_dto():
    seed_source = ast.parse(
        (REPO / "11_database" / "database_layer" / "school_seed.py").read_text(
            encoding="utf-8"
        )
    )
    recipe_assignment = next(
        node
        for node in seed_source.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "SYNTHETIC_SCHOOL_RECIPES"
            for target in node.targets
        )
    )
    seed_refs = {
        fields["key"]: fields["school_ref"]
        for fields in (
            {
                keyword.arg: ast.literal_eval(keyword.value)
                for keyword in recipe.keywords
            }
            for recipe in recipe_assignment.value.elts
        )
    }
    assert seed_refs == {
        "alpha": "SYNTHETIC_SCHOOL_SEED_ALPHA_V1",
        "beta": "SYNTHETIC_SCHOOL_SEED_BETA_V1",
    }
    assert qa.SCHOOL_REFS == seed_refs
    assert qa.ACCOUNT_SCHOOL["alpha.psychological_specialist"] == seed_refs["alpha"]
    assert qa.ACCOUNT_SCHOOL["beta.student"] == seed_refs["beta"]

    actor = ActorDto.model_validate(
        {
            "user_id": "USER_SYNTHETIC_TEST",
            "username": "SYNTHETIC_TEST",
            "role": "STUDENT",
            "subject_id": "SUBJ_SYNTHETIC_SCHOOL_SEED_ALPHA_V1",
            "available_contexts": [
                {"role": "PSYCHOLOGICAL_SPECIALIST", "school_ref": seed_refs["alpha"]},
                {"role": "ADMIN", "school_ref": seed_refs["alpha"]},
                {"role": "STUDENT", "school_ref": seed_refs["alpha"]},
                {"role": "TEACHER", "school_ref": seed_refs["alpha"]},
                {"role": "STUDENT", "school_ref": seed_refs["beta"]},
            ],
        }
    ).model_dump(mode="json")
    assert qa._select_context(actor, "alpha.psychological_specialist") == {
        "role": "PSYCHOLOGICAL_SPECIALIST",
        "school_ref": seed_refs["alpha"],
    }
    assert qa._select_context(actor, "beta.student") == {
        "role": "STUDENT",
        "school_ref": seed_refs["beta"],
    }
    actor["available_contexts"][0]["school_ref"] = "SCHOOL_synthetic_a"
    with pytest.raises(qa.HarnessError):
        qa._select_context(actor, "alpha.psychological_specialist")

    class Response:
        status_code = 200

        def __init__(self, data):
            self.data = data

        def json(self):
            return {"data": self.data}

    class Client:
        def __init__(self, login_actor):
            self.login_actor = login_actor
            self.context_payload = None

        def post(self, path, *, json, headers):
            if path == "/api/v1/auth/login":
                return Response({"actor": self.login_actor, "csrf_token": "csrf-test"})
            if path == "/api/v1/auth/active-context":
                self.context_payload = json
                selected = dict(self.login_actor)
                selected["role"] = json["role"]
                selected["active_context"] = json
                return Response(selected)
            raise AssertionError("unexpected endpoint")

    actor = ActorDto.model_validate(
        {
            "user_id": "USER_SYNTHETIC_SPECIALIST_TEST",
            "username": "SYNTHETIC_SPECIALIST_TEST",
            "role": "ADMIN",
            "subject_id": None,
            "available_contexts": [
                {"role": "PSYCHOLOGICAL_SPECIALIST", "school_ref": seed_refs["alpha"]},
                {"role": "ADMIN", "school_ref": seed_refs["alpha"]},
            ],
        }
    ).model_dump(mode="json")
    client = Client(actor)
    httpx = SimpleNamespace(Client=lambda **kwargs: client)
    sessions = {}
    statuses = {}
    session = qa._login(
        httpx,
        {
            "alpha.psychological_specialist": {
                "username": "SYNTHETIC_SPECIALIST_TEST",
                "password": "synthetic-test-password",
            }
        },
        "alpha.psychological_specialist",
        sessions,
        statuses,
    )
    assert client.context_payload == {
        "role": "PSYCHOLOGICAL_SPECIALIST",
        "school_ref": seed_refs["alpha"],
    }
    assert session["school_ref"] == seed_refs["alpha"]
    assert statuses["login_alpha_psychological_specialist"] == 200
    assert statuses["context_alpha_psychological_specialist"] == 200

    wrong_actor = dict(actor)
    wrong_actor["available_contexts"] = [
        {"role": "PSYCHOLOGICAL_SPECIALIST", "school_ref": "SCHOOL_synthetic_a"}
    ]
    wrong_client = Client(wrong_actor)
    with pytest.raises(qa._Failure) as failure:
        qa._login(
            SimpleNamespace(Client=lambda **kwargs: wrong_client),
            {
                "alpha.psychological_specialist": {
                    "username": "SYNTHETIC_SPECIALIST_TEST",
                    "password": "synthetic-test-password",
                }
            },
            "alpha.psychological_specialist",
            {},
            {},
        )
    assert failure.value.substage == "context_choice"
    assert failure.value.http_status == 200


def test_auth_failure_diagnostic_contains_only_fixed_substage_and_http_status(tmp_path):
    stages = qa._empty_stages(1)
    failure = qa._failure_record(
        qa._Failure(
            "specialist_login",
            "HarnessError",
            substage="context_choice",
            http_status=200,
        )
    )
    result = qa._result(
        1,
        stages,
        failure={**failure, "message": "private-response-sentinel", "cookie": "secret"},
    )
    assert result["failure"] == {
        "stage": "specialist_login",
        "error_class": "HarnessError",
        "substage": "context_choice",
        "http_status": 200,
    }
    assert "private-response-sentinel" not in json.dumps(result)
    assert '"secret"' not in json.dumps(result)
    workspace = tmp_path / "owned"
    (workspace / "logs").mkdir(parents=True)
    evidence = (
        workspace / "logs" / f"{qa.EVIDENCE_PREFIX}{'a' * 32}-phase1-{'b' * 32}.json"
    )
    qa._write_evidence(workspace, evidence, result)
    stored = evidence.read_text(encoding="utf-8")
    assert json.loads(stored)["failure"] == result["failure"]
    assert "private-response-sentinel" not in stored


def test_evidence_writer_filters_unknown_fields_and_keys_and_uses_exclusive_owned_path(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "owned"
    (workspace / "logs").mkdir(parents=True)
    monkeypatch.setattr(qa.owned_workspace, "_reject_reparse_path", lambda path: None)
    evidence_path = qa._new_evidence_path(workspace, "a" * 32, 2)
    result = {
        "workflow": "school-saved-cat-task-http-qa",
        "phase": 2,
        "status": "FAIL",
        "stages": {
            "workspace_owned": "PASS",
            "made_up_stage": "PASS",
        },
        "api_statuses": {
            "task_a_state_after_cat_restart": 200,
            "made_up_endpoint": 201,
            "logout_specialist": "200",
        },
        "failure": {
            "stage": "cat_restart_restored_exact_session",
            "error_class": "UntrustedException",
            "substage": "private_selector",
            "http_status": "200",
            "message": "response-body-secret",
        },
        "response_body": "response-body-secret",
        "cookie": "cookie-secret",
        "evidence_path": "untrusted-output-path",
    }
    qa._write_evidence(workspace, evidence_path, result)
    written = evidence_path.read_text(encoding="utf-8")
    stored = json.loads(written)
    assert set(stored) == {
        "workflow",
        "phase",
        "status",
        "stages",
        "api_statuses",
        "failure",
    }
    assert set(stored["stages"]) == set(qa.PHASE2_STAGE_KEYS)
    assert stored["stages"]["workspace_owned"] == "PASS"
    assert stored["stages"]["owned_processes_verified"] == "FAIL"
    assert stored["api_statuses"] == {"task_a_state_after_cat_restart": 200}
    assert stored["failure"] == {
        "stage": "cat_restart_restored_exact_session",
        "error_class": "HarnessError",
    }
    for secret in (
        "made_up_stage",
        "made_up_endpoint",
        "private_selector",
        "response-body-secret",
        "cookie-secret",
        "untrusted-output-path",
    ):
        assert secret not in written
    with pytest.raises(qa.HarnessError):
        qa._write_evidence(workspace, evidence_path, result)


def test_evidence_writer_rejects_paths_outside_logs_and_outside_continuation_paths(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "owned"
    logs = workspace / "logs"
    logs.mkdir(parents=True)
    monkeypatch.setattr(qa.owned_workspace, "_reject_reparse_path", lambda path: None)
    result = qa._result(1, qa._empty_stages(1))
    outside_evidence = (
        tmp_path / f"{qa.EVIDENCE_PREFIX}{'a' * 32}-phase1-{'b' * 32}.json"
    )
    with pytest.raises(qa.HarnessError):
        qa._write_evidence(workspace, outside_evidence, result)

    valid_evidence_path = qa._new_evidence_path(workspace, "a" * 32, 1)
    outside_continuation = (
        tmp_path / f"{qa.CONTINUATION_PREFIX}{'c' * 32}{qa.CONTINUATION_SUFFIX}"
    )
    outside_continuation.write_text("not-used-as-data", encoding="utf-8")
    result["continuation_path"] = str(outside_continuation)
    with pytest.raises(qa.HarnessError):
        qa._write_evidence(workspace, valid_evidence_path, result)


@pytest.mark.parametrize("phase", (1, 2))
def test_evidence_path_allocation_failure_forces_phase_failure_without_raw_error(
    phase, tmp_path, monkeypatch
):
    secret = "path-error-private-sentinel"

    def fail_allocation(workspace, run_id, selected_phase):
        assert selected_phase == phase
        raise OSError(secret)

    monkeypatch.setattr(qa, "_new_evidence_path", fail_allocation)
    evidence_path, failure = qa._allocate_evidence_path(tmp_path, "a" * 32, phase)
    stages = {key: "PASS" for key in qa.STAGES_BY_PHASE[phase]}
    result = qa._result(phase, stages, failure=failure, evidence_path=evidence_path)
    assert evidence_path is None
    assert result["status"] == "FAIL"
    assert result["failure"] == {
        "stage": "sessions_logged_out",
        "error_class": "HarnessError",
        "substage": "evidence_path",
    }
    assert secret not in json.dumps(result)


def test_continuation_path_requires_direct_file_under_owned_logs(tmp_path, monkeypatch):
    workspace = tmp_path / "owned"
    logs = workspace / "logs"
    logs.mkdir(parents=True)
    monkeypatch.setattr(qa.owned_workspace, "_reject_reparse_path", lambda path: None)
    path = logs / f"{qa.CONTINUATION_PREFIX}{'a' * 32}{qa.CONTINUATION_SUFFIX}"
    path.write_text("sealed-marker", encoding="utf-8")
    assert qa._continuation_path(workspace, path) == path.resolve()
    nested = logs / "subdir"
    nested.mkdir()
    nested_file = nested / path.name
    nested_file.write_text("sealed-marker", encoding="utf-8")
    with pytest.raises(qa.HarnessError):
        qa._continuation_path(workspace, nested_file)
