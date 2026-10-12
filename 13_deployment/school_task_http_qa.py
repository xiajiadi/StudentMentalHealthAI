"""Append-only synthetic task HTTP workflow, using sealed accounts in memory."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sys
from uuid import uuid4

from private_settings import read_private
from school_backend import load_runtime


def run(workspace: Path, repo: Path) -> dict:
    import httpx

    clients, headers, actors = {}, {}, {}
    stage = "runtime_gate"
    status = None
    try:
        load_runtime(workspace, repo)
        credentials = read_private(workspace / "school-accounts.private.dpapi")["credentials"]
        stage = "login"
        for slot in ("alpha.admin", "alpha.student", "alpha.teacher", "beta.student", "beta.teacher"):
            client = httpx.Client(base_url="http://127.0.0.1:8088", timeout=30)
            clients[slot] = client
            user, password = credentials[slot]
            response = client.post("/api/v1/auth/login", json={"username": user, "password": password})
            status = response.status_code
            assert status == 200
            auth = response.json()["data"]
            headers[slot] = {"X-CSRF-Token": auth["csrf_token"]}
            response = client.post("/api/v1/auth/active-context", json=auth["actor"]["available_contexts"][0], headers=headers[slot])
            status = response.status_code
            assert status == 200
            actors[slot] = response.json()["data"]

        def write(slot, path, body=None, key=None):
            return clients[slot].post(path, json=body, headers={**headers[slot], "Idempotency-Key": key or str(uuid4())})

        def checked(response, expected=200):
            nonlocal status
            status = response.status_code
            assert status == expected
            return response.json()["data"]

        admin, student, teacher = (clients[slot] for slot in ("alpha.admin", "alpha.student", "alpha.teacher"))
        ref = "CLASS_QA_" + uuid4().hex
        stage = "metadata_list"
        metadata = checked(student.get("/api/v1/school/assessments?limit=30&skip=0"))
        assert all(set(row) == {"assessment_id", "status", "items_answered", "started_at", "completed_at"} for row in metadata)
        pending = checked(student.get("/api/v1/school/assessments?limit=30&status=created"))
        assert pending and all(row["status"] == "created" and row["started_at"] is None for row in pending)
        assert teacher.get("/api/v1/school/assessments").status_code == 403
        stage = "class_create"
        class_key = str(uuid4())
        checked(write("alpha.admin", "/api/v1/school/classes", {"class_ref": ref}, class_key), 201)
        replay = checked(write("alpha.admin", "/api/v1/school/classes", {"class_ref": ref}, class_key), 201)
        assert replay["class_ref"] == ref
        stage = "roster"
        checked(write("alpha.admin", f"/api/v1/school/classes/{ref}/students", {"student_user_id": actors["alpha.student"]["user_id"]}))
        checked(write("alpha.admin", f"/api/v1/school/classes/{ref}/teachers", {"teacher_user_id": actors["alpha.teacher"]["user_id"]}))
        now = datetime.now(UTC)
        stage = "publish"
        task = checked(write("alpha.admin", f"/api/v1/school/classes/{ref}/tasks", {"opens_at": (now - timedelta(minutes=1)).isoformat(), "due_at": (now + timedelta(days=1)).isoformat()}), 201)["task_ref"]
        stage = "start"
        key = str(uuid4())
        started = checked(write("alpha.student", f"/api/v1/school/tasks/{task}/start", key=key))
        assessment_id = started["assessment_id"]
        repeated = checked(write("alpha.student", f"/api/v1/school/tasks/{task}/start", key=key))
        assert repeated["assessment_id"] == assessment_id
        stage = "cross_school"
        assert write("beta.student", f"/api/v1/school/tasks/{task}/start").status_code == 404
        assert clients["beta.teacher"].get(f"/api/v1/school/classes/{ref}/task-progress").status_code == 404
        stage = "complete"
        for _ in range(100):
            state = checked(student.get(f"/api/v1/assessments/{assessment_id}/state"))
            if state["can_complete"]:
                checked(write("alpha.student", f"/api/v1/assessments/{assessment_id}/complete", {}))
                break
            item = state["current_item"]
            value = item["options"][0]["value"]
            assert value is not None
            checked(write("alpha.student", f"/api/v1/assessments/{assessment_id}/responses", {"item_id": item["item_id"], "response": value}))
        else:
            raise RuntimeError("Bounded workflow limit")
        stage = "teacher_aggregate"
        rows = checked(teacher.get(f"/api/v1/school/classes/{ref}/task-progress"))
        assert len(rows) == 1 and rows[0]["completed_count"] == 1
        assert not {"subject_id", "assessment_id", "score", "responses", "report", "items_answered"}.intersection(rows[0])
        stage = "revoke"
        enrollment = checked(admin.get(f"/api/v1/school/tasks/{task}/enrollments"))[0]["enrollment_ref"]
        checked(write("alpha.admin", f"/api/v1/school/tasks/{task}/enrollments/{enrollment}/revoke"))
        assert student.get(f"/api/v1/assessments/{assessment_id}/state").status_code == 404
        own_records = checked(student.get("/api/v1/school/assessments?limit=100"))
        assert assessment_id not in [item["assessment_id"] for item in own_records]
        counts = checked(teacher.get(f"/api/v1/school/classes/{ref}/task-progress"))[0]
        assert (counts["published_enrollment_count"], counts["active_enrollment_count"], counts["revoked_enrollment_count"], counts["completed_count"]) == (1, 0, 1, 0)
        stage = "history"
        history = checked(student.get("/api/v1/school/tasks/student/history"))
        record = next(item for item in history if item["task_ref"] == task)
        assert record["enrollment_status"] == "REVOKED" and record["assessment_status"] == "completed"
        assert not {"assessment_id", "subject_id", "score", "responses", "report"}.intersection(record)
        evidence = {"schema_version": "psynova.school-task-qa.v1", "synthetic_only": True,
                    "class_ref": ref, "task_ref": task, "assessment_id": assessment_id,
                    "flow": "PASS", "revoked": True}
        (workspace / ("school-task-qa-" + uuid4().hex + ".json")).write_text(json.dumps(evidence), encoding="utf-8")
        return {"native_school_task_flow": "PASS", "real_CAT_completion": "PASS",
                "idempotent_resource_replay": "PASS", "cross_school_denials": "PASS",
                "teacher_aggregate_privacy": "PASS", "revoked_private_read_and_list": "DENIED",
                "lifecycle_only_history": "PASS"}
    except Exception as exc:
        return {"native_task_qa": "FAIL", "stage": stage, "http_status": status,
                "error_type": type(exc).__name__}
    finally:
        for slot, client in clients.items():
            try:
                client.post("/api/v1/auth/logout", headers=headers.get(slot, {}))
            except Exception:
                pass
            client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    for path in (repo / "11_database" / ".venv" / "Lib" / "site-packages", repo / "11_database", repo / "09_backend" / "src"):
        sys.path.insert(0, str(path))
    result = run(args.workspace, repo)
    print(json.dumps(result))
    return 0 if result.get("native_school_task_flow") == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
