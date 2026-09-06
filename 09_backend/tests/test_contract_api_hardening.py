from __future__ import annotations

import json
from pathlib import Path

import pytest

from smhai_backend.app_factory import create_app

from .conftest import completed_assessment, login


def _operations(document: dict) -> list[tuple[str, str, dict]]:
    values: list[tuple[str, str, dict]] = []
    for path, path_item in document["paths"].items():
        for method, operation in path_item.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                values.append((method, path, operation))
    return values


def test_source_openapi_has_typed_successes_stable_ids_and_problem_schema() -> None:
    document = create_app().openapi()
    operations = _operations(document)
    operation_ids = [operation["operationId"] for _, _, operation in operations]
    assert document["openapi"].startswith("3.1.")
    assert len(operation_ids) == len(set(operation_ids)) == 21
    assert "ProblemDetails" in document["components"]["schemas"]
    assert "sessionCookie" in document["components"]["securitySchemes"]
    assert "csrfToken" in document["components"]["securitySchemes"]

    for _, _, operation in operations:
        for status, response in operation["responses"].items():
            if status.startswith("2"):
                content = response.get("content", {})
                schema = content.get("application/json", {}).get("schema")
                assert schema and schema != {}, (operation["operationId"], status)
            if status.startswith("4") or status.startswith("5"):
                if "application/problem+json" in response.get("content", {}):
                    assert response["content"]["application/problem+json"]["schema"]

    mutation = document["paths"]["/api/v1/support/requests"]["post"]
    assert {"sessionCookie": [], "csrfToken": []} in mutation["security"]


@pytest.mark.asyncio
async def test_validation_error_is_typed_and_does_not_echo_input(client) -> None:
    secret_fixture = "SYNTHETIC_INPUT_SHOULD_NOT_BE_ECHOED"
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "student_a", "password": "synthetic-student-a", "extra": secret_fixture},
    )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "urn:smhai:problem:validation_failed"
    assert body["code"] == "validation_failed"
    assert body["errors"][0]["loc"][0] == "body"
    assert secret_fixture not in response.text


@pytest.mark.asyncio
async def test_provenance_and_not_run_identity_survive_report_projection(client) -> None:
    csrf_token = await login(client)
    assessment_id = await completed_assessment(client, csrf_token)

    normal = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "assessment_id": assessment_id,
            "target_role": "student",
            "message": "provenance round trip fixture",
        },
    )
    assert normal.status_code == 202
    normal_data = normal.json()["data"]
    assert normal_data["generation"]["provenance"]["generation_status"] == "EXECUTED"
    assert normal_data["generation"]["provenance"]["candidate_source"] == "CONTROLLED_SYNTHETIC"
    assert normal_data["generation"]["provenance"]["model_id"]
    assert normal_data["citations"][0]["chunk_id"] == "CHUNK_backend_0"
    assert normal_data["citations"][0]["document_id"] == "KB_backend_synthetic"
    assert normal_data["citations"][0]["source_hash"].startswith("sha256:")

    report = await client.get(f"/api/v1/reports/{normal_data['report_id']}")
    assert report.status_code == 200
    report_data = report.json()["data"]
    assert report_data["citations"] == normal_data["citations"]

    crisis = await client.post(
        "/api/v1/support/requests",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "assessment_id": assessment_id,
            "target_role": "student",
            "message": "SYNTHETIC_CRISIS_SIGNAL",
        },
    )
    assert crisis.status_code == 202
    crisis_generation = crisis.json()["data"]["generation"]
    assert crisis_generation["provenance"]["generation_status"] == "NOT_RUN"
    assert crisis_generation["provenance"]["candidate_source"] == "NOT_RUN"
    assert crisis_generation["provenance"]["model_id"] is None
    assert crisis_generation["provenance"]["model_version"] is None
    assert crisis_generation["provenance"]["runtime_version"] is None


def test_candidate_file_is_source_generated_and_has_no_runtime_patch_marker() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "00_architecture"
        / "contracts"
        / "candidates"
        / "openapi.hardened.candidate.json"
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["openapi"].startswith("3.1.")
    assert len(_operations(document)) == 21
    assert "_apply_runtime_contract" not in path.read_text(encoding="utf-8")
