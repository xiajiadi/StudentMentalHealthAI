"""Run a synthetic API round trip and emit provenance/execution-state evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "09_backend" / "src"))

from smhai_backend.app_factory import create_app
from smhai_backend.core.config import BackendSettings, RateLimitSettings


async def run_probe() -> dict[str, object]:
    settings = BackendSettings(
        environment="test",
        rate_limit=RateLimitSettings(
            login_max_requests=5,
            support_max_requests=10,
            window_seconds=60,
        ),
    )
    app = create_app(settings=settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"Accept": "application/json"},
        ) as client:
            login = await client.post(
                "/api/v1/auth/login",
                json={"username": "student_a", "password": "synthetic-student-a"},
            )
            login.raise_for_status()
            csrf_token = login.json()["data"]["csrf_token"]
            csrf_headers = {"X-CSRF-Token": csrf_token}

            assessment = await client.post(
                "/api/v1/assessments",
                headers=csrf_headers,
                json={
                    "subject_id": "SUBJ_demo_a",
                    "instrument_id": "instrument.synthetic",
                    "instrument_version": "1.0",
                },
            )
            assessment.raise_for_status()
            assessment_id = assessment.json()["data"]["assessment_id"]
            response = await client.post(
                f"/api/v1/assessments/{assessment_id}/responses",
                headers=csrf_headers,
                json={"item_id": "ITEM_synthetic_1", "response": 1.0},
            )
            response.raise_for_status()
            complete = await client.post(
                f"/api/v1/assessments/{assessment_id}/complete",
                headers=csrf_headers,
                json={},
            )
            complete.raise_for_status()

            normal = await client.post(
                "/api/v1/support/requests",
                headers=csrf_headers,
                json={
                    "assessment_id": assessment_id,
                    "target_role": "student",
                    "message": "provenance round trip fixture",
                },
            )
            normal.raise_for_status()
            normal_data = normal.json()["data"]
            report = await client.get(f"/api/v1/reports/{normal_data['report_id']}")
            report.raise_for_status()
            report_data = report.json()["data"]
            citations = normal_data["citations"]
            normal_provenance = normal_data["generation"]["provenance"]

            crisis = await client.post(
                "/api/v1/support/requests",
                headers=csrf_headers,
                json={
                    "assessment_id": assessment_id,
                    "target_role": "student",
                    "message": "SYNTHETIC_CRISIS_SIGNAL",
                },
            )
            crisis.raise_for_status()
            crisis_data = crisis.json()["data"]
            crisis_provenance = crisis_data["generation"]["provenance"]

            return {
                "schema_version": "contract-api-hardening.provenance-evidence.v1",
                "synthetic_fixture_only": True,
                "normal": {
                    "support_status": normal.status_code,
                    "generation_status": normal_provenance["generation_status"],
                    "candidate_source": normal_provenance["candidate_source"],
                    "model_id_present": bool(normal_provenance["model_id"]),
                    "citation_count": len(citations),
                    "citation_identity": {
                        "chunk_id_present": bool(citations[0]["chunk_id"]),
                        "document_id_present": bool(citations[0]["document_id"]),
                        "rank_present": citations[0]["rank"] is not None,
                        "source_version_present": bool(citations[0]["source_version"]),
                        "source_hash_present": bool(citations[0]["source_hash"]),
                    },
                    "report_citations_equal": report_data["citations"] == citations,
                    "report_generation_status": report_data["generation"]["provenance"][
                        "generation_status"
                    ],
                },
                "crisis": {
                    "support_status": crisis.status_code,
                    "generation_status": crisis_provenance["generation_status"],
                    "candidate_source": crisis_provenance["candidate_source"],
                    "model_id_is_null": crisis_provenance["model_id"] is None,
                    "model_version_is_null": crisis_provenance["model_version"] is None,
                    "runtime_version_is_null": crisis_provenance["runtime_version"] is None,
                },
            }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = asyncio.run(run_probe())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
