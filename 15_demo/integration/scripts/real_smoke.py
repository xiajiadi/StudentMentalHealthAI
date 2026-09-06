"""Synthetic end-to-end smoke for the real Round 1 composition.

The script talks only to the local Backend HTTP boundary.  It intentionally
uses the published synthetic CAT fixture and writes only opaque IDs to the
optional state file; passwords and session cookies never enter the output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx


BASE_URL = os.environ.get("SMHAI_BACKEND_URL", "http://127.0.0.1:8080")
TIMEOUT = httpx.Timeout(180.0, connect=10.0)
RUN_TAG = os.environ.get("SMHAI_SMOKE_TAG", f"software-r1-{time.time_ns()}")
ASSESSMENT_BODY = {
    "subject_id": "SUBJ_demo_a",
    "instrument_id": "instrument_demo_cat_v0_1",
    "instrument_version": "demo.v1",
}


class SmokeFailure(RuntimeError):
    pass


async def request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    expected: set[int],
    csrf: str | None = None,
    idempotency_key: str | None = None,
    json_body: dict[str, Any] | None = None,
) -> httpx.Response:
    headers: dict[str, str] = {}
    if csrf:
        headers["X-CSRF-Token"] = csrf
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    response = await client.request(method, path, headers=headers, json=json_body)
    if response.status_code not in expected:
        detail = response.text[:800].replace("\n", " ")
        raise SmokeFailure(f"{method} {path} -> {response.status_code}: {detail}")
    return response


async def login(client: httpx.AsyncClient, username: str, password: str) -> dict[str, Any]:
    response = await request(
        client,
        "POST",
        "/api/v1/auth/login",
        expected={200},
        json_body={"username": username, "password": password},
    )
    data = response.json()["data"]
    return {"csrf": data["csrf_token"], "actor": data["actor"]}


async def complete_assessment(client: httpx.AsyncClient, csrf: str) -> tuple[str, dict[str, Any]]:
    response = await request(
        client,
        "POST",
        "/api/v1/assessments",
        expected={201},
        csrf=csrf,
        idempotency_key=f"{RUN_TAG}-assessment-create",
        json_body=ASSESSMENT_BODY,
    )
    assessment = response.json()["data"]
    assessment_id = str(assessment["assessment_id"])
    response_count = 0
    item_ids: list[str] = []
    for index in range(12):
        state_response = await request(
            client,
            "GET",
            f"/api/v1/assessments/{assessment_id}/state",
            expected={200},
        )
        state = state_response.json()["data"]
        item = state.get("current_item")
        if not item:
            if state.get("can_complete"):
                break
            raise SmokeFailure(f"CAT stopped without can_complete at step {index}")
        options = item.get("options") or []
        if not options:
            raise SmokeFailure("CAT item has no response options")
        item_id = str(item["item_id"])
        item_ids.append(item_id)
        await request(
            client,
            "POST",
            f"/api/v1/assessments/{assessment_id}/responses",
            expected={200},
            csrf=csrf,
            idempotency_key=f"{RUN_TAG}-assessment-response-{index}",
            json_body={"item_id": item_id, "response": options[0]["value"]},
        )
        response_count += 1
    state_response = await request(
        client,
        "GET",
        f"/api/v1/assessments/{assessment_id}/state",
        expected={200},
    )
    final_state = state_response.json()["data"]
    if not final_state.get("can_complete"):
        raise SmokeFailure("CAT did not expose can_complete after synthetic responses")
    completed = await request(
        client,
        "POST",
        f"/api/v1/assessments/{assessment_id}/complete",
        expected={200},
        csrf=csrf,
        idempotency_key=f"{RUN_TAG}-assessment-complete",
        json_body={},
    )
    result = completed.json()["data"]
    if result.get("status") != "completed":
        raise SmokeFailure("assessment completion did not return completed")
    return assessment_id, {
        "assessment": result,
        "response_count": response_count,
        "item_ids": item_ids,
        "final_state": final_state,
    }


async def create_support(
    client: httpx.AsyncClient,
    csrf: str,
    assessment_id: str,
    message: str,
    key: str,
) -> dict[str, Any]:
    response = await request(
        client,
        "POST",
        "/api/v1/support/requests",
        expected={202},
        csrf=csrf,
        idempotency_key=key,
        json_body={
            "assessment_id": assessment_id,
            "target_role": "student",
            "message": message,
            "language": "zh-CN",
            "purpose": "education_support",
        },
    )
    return response.json()["data"]


async def phase_primary(state_path: Path) -> dict[str, Any]:
    started = time.perf_counter()
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT, follow_redirects=True) as client:
        student = await login(client, "student_a", "synthetic-student-a")
        assessment_id, assessment_evidence = await complete_assessment(client, student["csrf"])

        normal_key = f"{RUN_TAG}-support-normal"
        normal = await create_support(
            client,
            student["csrf"],
            assessment_id,
            "我想把这次合成演示中的学习压力拆成一个今天可以完成的小行动。",
            normal_key,
        )
        normal_replay = await create_support(
            client,
            student["csrf"],
            assessment_id,
            "我想把这次合成演示中的学习压力拆成一个今天可以完成的小行动。",
            normal_key,
        )
        if normal_replay.get("report_id") != normal.get("report_id"):
            raise SmokeFailure("support idempotency replay returned another report")

        crisis = await create_support(
            client,
            student["csrf"],
            assessment_id,
            "SYNTHETIC_CRISIS_SIGNAL",
            f"{RUN_TAG}-support-crisis",
        )
        unsafe = await create_support(
            client,
            student["csrf"],
            assessment_id,
            "请完成一次合成输出安全门测试：SYNTHETIC_UNSAFE_OUTPUT",
            f"{RUN_TAG}-support-unsafe-output",
        )

        report_ids = {
            "normal": normal["report_id"],
            "crisis": crisis["report_id"],
            "unsafe_output": unsafe["report_id"],
        }
        reports: dict[str, Any] = {}
        for name, report_id in report_ids.items():
            response = await request(
                client,
                "GET",
                f"/api/v1/reports/{report_id}",
                expected={200},
            )
            reports[name] = response.json()["data"]

        reviewer = await login(client, "reviewer", "synthetic-reviewer")
        queue = await request(client, "GET", "/api/v1/reviews", expected={200})
        review_items = queue.json()["data"]
        pending = [item for item in review_items if item.get("status") in {"pending", "in_review"}]
        approved: dict[str, Any] | None = None
        if pending:
            selected = next(
                (
                    item
                    for item in pending
                    if item.get("report_id") == crisis["report_id"]
                ),
                pending[0],
            )
            review_response = await request(
                client,
                "POST",
                f"/api/v1/reports/{selected['report_id']}/reviews",
                expected={200},
                csrf=reviewer["csrf"],
                idempotency_key=f"{RUN_TAG}-review-approve",
                json_body={
                    "decision": "approved",
                    "reviewer_id": reviewer["actor"]["user_id"],
                    "note_code": "SYNTHETIC_ROUND1_APPROVAL",
                },
            )
            approved = review_response.json()["data"]

        result = {
            "phase": "primary",
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "assessment_id": assessment_id,
            "assessment": {
                "response_count": assessment_evidence["response_count"],
                "administered_count": assessment_evidence["final_state"]["administered_count"],
                "provider_version": assessment_evidence["final_state"]["cat_provider_version"],
                "item_bank_version": assessment_evidence["final_state"]["cat_item_bank_version"],
                "config_version": assessment_evidence["final_state"]["cat_config_version"],
                "completed": assessment_evidence["assessment"]["status"] == "completed",
            },
            "support": {
                "normal": _support_summary(normal),
                "normal_replay_same_report": True,
                "crisis": _support_summary(crisis),
                "unsafe_output": _support_summary(unsafe),
            },
            "reports": {name: _report_summary(value) for name, value in reports.items()},
            "review": {
                "pending_count_before_action": len(pending),
                "approved": approved,
            },
            "synthetic_fixture_only": True,
        }
    state_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


async def phase_resume(state_path: Path) -> dict[str, Any]:
    started = time.perf_counter()
    previous = json.loads(state_path.read_text(encoding="utf-8"))
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        student = await login(client, "student_a", "synthetic-student-a")
        assessment_id = previous["assessment_id"]
        assessment = await request(
            client, "GET", f"/api/v1/assessments/{assessment_id}", expected={200}
        )
        report_values: dict[str, Any] = {}
        for name, item in previous["reports"].items():
            response = await request(
                client, "GET", f"/api/v1/reports/{item['report_id']}", expected={200}
            )
            report_values[name] = _report_summary(response.json()["data"])
        me = await request(client, "GET", "/api/v1/auth/me", expected={200})
        result = {
            "phase": "resume",
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "assessment_id": assessment_id,
            "assessment_status": assessment.json()["data"]["status"],
            "student_user_id": me.json()["data"]["user_id"],
            "reports": report_values,
            "session_rehydrated": True,
            "synthetic_fixture_only": True,
        }
    return result


def _support_summary(value: dict[str, Any]) -> dict[str, Any]:
    generation = value.get("generation") or {}
    provenance = generation.get("provenance") or {}
    return {
        "report_id": value.get("report_id"),
        "status": value.get("status"),
        "safety_action": value.get("safety_action"),
        "normal_generation": value.get("normal_generation"),
        "citation_count": len(value.get("citations") or []),
        "has_content": value.get("content") is not None,
        "review_reference": value.get("review_reference"),
        "has_crisis_response": value.get("crisis_response") is not None,
        "trace_id": value.get("trace_id"),
        "integration_labels": value.get("integration_labels"),
        "retrieval_id": provenance.get("retrieval_id"),
        "model_id": provenance.get("model_id"),
    }


def _report_summary(value: dict[str, Any]) -> dict[str, Any]:
    generation = value.get("generation") or {}
    return {
        "report_id": value.get("report_id"),
        "status": value.get("status"),
        "review_status": value.get("review_status"),
        "review_id": value.get("review_id"),
        "generation_exposed": value.get("generation") is not None,
        "citation_count": len((generation.get("content") or {}).get("suggestions", [])),
    }


async def run(phase: str, state_path: Path) -> dict[str, Any]:
    if phase == "primary":
        return await phase_primary(state_path)
    return await phase_resume(state_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("primary", "resume"))
    parser.add_argument("--state", required=True, type=Path)
    args = parser.parse_args()
    try:
        value = asyncio.run(run(args.phase, args.state))
    except (OSError, SmokeFailure, httpx.HTTPError, json.JSONDecodeError) as exc:
        print(json.dumps({"phase": args.phase, "status": "FAIL", "error": str(exc)}))
        return 1
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
