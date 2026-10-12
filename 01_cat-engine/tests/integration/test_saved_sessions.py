"""Saved-version session routing and session-owned CAT execution checks."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy

import pytest
from test_management_api import asgi_request

from cat_engine.api.app import CatRuntime, create_app


def _saved_payload(
    runtime: CatRuntime,
    *,
    assessment_id: str,
    suffix: str,
    max_items: int = 3,
) -> dict:
    bank_document = deepcopy(runtime.item_bank.to_dict())
    bank_document["item_bank_id"] = f"ITEMBANK_saved_{suffix}"
    bank_document["version"] = f"saved.bank.{suffix}"
    bank_document["instrument_id"] = f"SYNTHETIC_SAVED_{suffix}"
    bank_document["metadata"]["instrument_version"] = f"saved.instrument.{suffix}"
    for item in bank_document["items"]:
        item["stem"] = f"保存版本 {suffix} 的合成题：{item['stem']}"

    config_document = runtime.config.to_dict()
    config_document.update(
        config_version=f"saved.config.{suffix}",
        min_items=max_items,
        max_items=max_items,
        se_threshold=None,
    )
    uuid_suffix = f"{int(suffix[-1], 36) + 1:012d}"
    uuid = f"00000000-0000-4000-8000-{uuid_suffix}"
    return {
        "assessment_id": assessment_id,
        "subject_id": "SUBJ_saved_demo",
        "instrument_id": bank_document["instrument_id"],
        "instrument_version": bank_document["metadata"]["instrument_version"],
        "binding_ref": f"CSBIND_{uuid}",
        "activation_ref": f"CACT_{uuid}",
        "plan_version_ref": f"CPVER_{uuid}",
        "bank_version_ref": f"CBVER_{uuid}",
        "bank_document": bank_document,
        "config_document": config_document,
    }


def _request(app, method: str, path: str, payload: dict | None = None):
    return asyncio.run(asgi_request(app, method, path, payload))


def _reverse_mapping_order(value):
    if isinstance(value, dict):
        return {key: _reverse_mapping_order(value[key]) for key in reversed(value)}
    if isinstance(value, list):
        return [_reverse_mapping_order(item) for item in value]
    return value


def test_saved_sessions_own_distinct_assets_and_coexist_with_fixture():
    runtime = CatRuntime()
    app = create_app(runtime=runtime)
    initial_health_status, initial_health = _request(app, "GET", "/health/ready")
    assert initial_health_status == 200
    assert initial_health["synthetic_fixture_only"] is True
    assert initial_health["supports_saved_versions"] is True
    saved_three = _saved_payload(
        runtime, assessment_id="ASSESS_saved_three", suffix="v1", max_items=3
    )
    saved_four = _saved_payload(
        runtime, assessment_id="ASSESS_saved_four", suffix="v2", max_items=4
    )

    status_three, three = _request(app, "POST", "/internal/cat/saved-sessions", saved_three)
    status_four, four = _request(app, "POST", "/internal/cat/saved-sessions", saved_four)
    fixture_request = {
        "assessment_id": "ASSESS_mixed_fixture",
        "subject_id": "SUBJ_fixture_demo",
        "instrument_id": runtime.item_bank.instrument_id,
        "instrument_version": runtime.item_bank.metadata["instrument_version"],
    }
    fixture_status, fixture = _request(
        app, "POST", "/internal/cat/sessions", fixture_request
    )

    assert status_three == status_four == fixture_status == 200
    assert three["cat_binding_mode"] == four["cat_binding_mode"] == "SAVED_VERSION"
    assert three["current_item"]["prompt"].startswith("保存版本 v1 的合成题：")
    assert four["current_item"]["prompt"].startswith("保存版本 v2 的合成题：")
    assert three["max_items"] == 3
    assert four["max_items"] == 4
    assert three["config_version"] == "saved.config.v1"
    assert four["config_version"] == "saved.config.v2"
    assert three["item_bank_version"] == "saved.bank.v1"
    assert four["item_bank_version"] == "saved.bank.v2"
    assert three["saved_binding"] == {
        "binding_ref": saved_three["binding_ref"],
        "activation_ref": saved_three["activation_ref"],
        "plan_version_ref": saved_three["plan_version_ref"],
        "bank_version_ref": saved_three["bank_version_ref"],
    }
    assert fixture["cat_binding_mode"] == "FIXTURE"
    assert fixture["synthetic_fixture_only"] is True
    assert fixture["synthetic_engineering_only"] is True
    assert fixture["saved_binding"] is None
    assert three["synthetic_fixture_only"] is False
    assert three["synthetic_engineering_only"] is True
    assert runtime.sessions["ASSESS_saved_three"].item_bank.item_bank_id == "ITEMBANK_saved_v1"
    assert runtime.sessions["ASSESS_saved_four"].config.max_items == 4
    assert "items" not in json.dumps(three["saved_binding"])

    health_status, health = _request(app, "GET", "/health/ready")
    capability_status, capabilities = _request(app, "GET", "/capabilities")
    assert health_status == capability_status == 200
    assert health["synthetic_fixture_only"] is False
    assert health["supports_saved_versions"] is True
    assert capabilities["synthetic_fixture_only"] is False
    assert capabilities["synthetic_engineering_only"] is True
    assert capabilities["supports_saved_versions"] is True
    assert "saved_session_start" in capabilities["operations"]


def test_saved_session_reuse_requires_exact_subject_refs_and_documents():
    runtime = CatRuntime()
    app = create_app(runtime=runtime)
    payload = _saved_payload(
        runtime, assessment_id="ASSESS_saved_reuse", suffix="v1", max_items=3
    )
    status, original = _request(app, "POST", "/internal/cat/saved-sessions", payload)
    reuse_status, reused = _request(app, "POST", "/internal/cat/saved-sessions", payload)
    assert status == reuse_status == 200
    assert reused == original

    for field, prefix in (
        ("binding_ref", "CSBIND"),
        ("activation_ref", "CACT"),
        ("plan_version_ref", "CPVER"),
        ("bank_version_ref", "CBVER"),
    ):
        changed = deepcopy(payload)
        changed[field] = f"{prefix}_00000000-0000-4000-8000-000000000099"
        assert _request(app, "POST", "/internal/cat/saved-sessions", changed)[0] == 409

    changed = deepcopy(payload)
    changed["bank_document"]["items"][0]["stem"] += " changed"
    assert _request(app, "POST", "/internal/cat/saved-sessions", changed)[0] == 409

    changed = deepcopy(payload)
    changed["config_document"]["max_items"] = 4
    assert _request(app, "POST", "/internal/cat/saved-sessions", changed)[0] == 409

    changed = deepcopy(payload)
    changed["subject_id"] = "SUBJ_other_demo"
    assert _request(app, "POST", "/internal/cat/saved-sessions", changed)[0] == 409

    fixture_request = {
        "assessment_id": payload["assessment_id"],
        "subject_id": "SUBJ_saved_demo",
        "instrument_id": runtime.item_bank.instrument_id,
        "instrument_version": runtime.item_bank.metadata["instrument_version"],
    }
    assert _request(app, "POST", "/internal/cat/sessions", fixture_request)[0] == 409

    fixture_id = "ASSESS_fixture_then_saved"
    fixture_request["assessment_id"] = fixture_id
    assert _request(app, "POST", "/internal/cat/sessions", fixture_request)[0] == 200
    changed = _saved_payload(runtime, assessment_id=fixture_id, suffix="v2")
    assert _request(app, "POST", "/internal/cat/saved-sessions", changed)[0] == 409


def test_saved_session_identity_hash_preserves_raw_numeric_and_null_representations():
    runtime = CatRuntime()
    app = create_app(runtime=runtime)
    payload = _saved_payload(
        runtime, assessment_id="ASSESS_saved_source_identity", suffix="v1", max_items=3
    )
    payload["bank_document"]["items"][0]["parameters"]["a"] = 1
    payload["bank_document"]["metadata"]["notice"] = None

    status, original = _request(app, "POST", "/internal/cat/saved-sessions", payload)
    assert status == 200
    ordered_retry = _reverse_mapping_order(deepcopy(payload))
    retry_status, retried = _request(
        app, "POST", "/internal/cat/saved-sessions", ordered_retry
    )
    assert retry_status == 200
    assert retried == original

    changed_number = deepcopy(payload)
    changed_number["bank_document"]["items"][0]["parameters"]["a"] = 1.0
    assert _request(app, "POST", "/internal/cat/saved-sessions", changed_number)[0] == 409

    omitted_null = deepcopy(payload)
    omitted_null["bank_document"]["metadata"].pop("notice")
    assert _request(app, "POST", "/internal/cat/saved-sessions", omitted_null)[0] == 409


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["bank_document"].update(status="draft"),
        lambda payload: payload["bank_document"]["metadata"].update(synthetic=1),
        lambda payload: payload["bank_document"]["metadata"].update(
            psychological_interpretation_allowed=0
        ),
        lambda payload: payload.update(instrument_id="wrong.instrument"),
        lambda payload: payload.update(binding_ref="CSBIND_bad"),
        lambda payload: payload.update(unexpected="field"),
    ],
)
def test_saved_session_start_rejects_invalid_documents_and_identity(mutation):
    runtime = CatRuntime()
    app = create_app(runtime=runtime)
    payload = _saved_payload(runtime, assessment_id="ASSESS_saved_invalid", suffix="v1")
    mutation(payload)
    status, _ = _request(app, "POST", "/internal/cat/saved-sessions", payload)
    assert status == 422
    assert runtime.sessions == {}


def test_saved_session_completion_uses_bound_versions():
    runtime = CatRuntime()
    app = create_app(runtime=runtime)
    payload = _saved_payload(
        runtime, assessment_id="ASSESS_saved_complete", suffix="v1", max_items=3
    )
    status, state = _request(app, "POST", "/internal/cat/saved-sessions", payload)
    assert status == 200

    while not state["can_complete"]:
        item_id = state["current_item"]["item_id"]
        status, state = _request(
            app,
            "POST",
            f"/internal/cat/sessions/{payload['assessment_id']}/responses",
            {"item_id": item_id, "response": "sometimes"},
        )
        assert status == 200

    status, completed = _request(
        app,
        "POST",
        f"/internal/cat/sessions/{payload['assessment_id']}/complete",
        {"manual": False},
    )
    assert status == 200
    assert completed["state"]["cat_binding_mode"] == "SAVED_VERSION"
    assert completed["state"]["max_items"] == 3
    assert completed["provider"]["item_bank_version"] == "saved.bank.v1"
    assert completed["provider"]["config_version"] == "saved.config.v1"
    assert completed["assessment"]["instrument"] == {
        "instrument_id": payload["instrument_id"],
        "version": payload["instrument_version"],
    }
