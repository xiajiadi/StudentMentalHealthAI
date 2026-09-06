"""Capture a sanitized real-MySQL provenance round trip from the Backend API.

The probe is deliberately a consumer of the public HTTP boundary.  Its direct
database query is read-only and reports only opaque identifiers, metadata,
counts, lengths, and equality checks; it never writes or prints credentials,
cookies, encrypted payloads, or message text.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from sqlalchemy import text

from database_layer.config import DatabaseSettings, create_engine


def _http_json(opener, method: str, url: str, *, body: dict | None = None, csrf: str | None = None) -> dict:
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if csrf:
        headers["X-CSRF-Token"] = csrf
    request = Request(url, data=payload, headers=headers, method=method)
    try:
        with opener.open(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"{method} {url} -> {exc.code}: {detail}") from exc


async def _database_snapshot(database_url: str, report_id: str, message_probe: str) -> dict:
    settings = DatabaseSettings(url=database_url)
    engine = create_engine(settings)
    try:
        async with engine.connect() as connection:
            runtime = (
                await connection.execute(
                    text(
                        "SELECT VERSION() AS version, @@version_comment AS edition, "
                        "@@time_zone AS time_zone, DATABASE() AS database_name"
                    )
                )
            ).mappings().one()
            revision = (
                await connection.execute(
                    text("SELECT version_num FROM database_alembic_version")
                )
            ).scalar_one()
            run = (
                await connection.execute(
                    text(
                        "SELECT id, run_ref, retrieval_ref, generation_ref, status, workflow_action "
                        "FROM support_runs WHERE run_ref = :report_id"
                    ),
                    {"report_id": report_id},
                )
            ).mappings().one()
            evidence = list(
                (
                    await connection.execute(
                        text(
                            "SELECT citation_id, chunk_id, document_id, rank_order, "
                            "source_version, source_hash, citation_title, "
                            "citation_organization, locator "
                            "FROM support_evidence WHERE support_run_id = :run_id "
                            "ORDER BY rank_order, id"
                        ),
                        {"run_id": run["id"]},
                    )
                )
                .mappings()
                .all()
            )
            message_rows = list(
                (
                    await connection.execute(
                        text(
                            "SELECT payload_ciphertext FROM support_messages "
                            "WHERE support_session_id = (SELECT support_session_id "
                            "FROM support_runs WHERE id = :run_id)"
                        ),
                        {"run_id": run["id"]},
                    )
                )
                .scalars()
                .all()
            )
            ciphertext_values = [bytes(value) for value in message_rows if value is not None]
            return {
                "runtime": {
                    "version": str(runtime["version"]),
                    "edition": str(runtime["edition"]),
                    "time_zone": str(runtime["time_zone"]),
                    "database": str(runtime["database_name"]),
                },
                "migration_head": str(revision),
                "run": {
                    "run_ref": str(run["run_ref"]),
                    "retrieval_ref": str(run["retrieval_ref"]),
                    "generation_ref": str(run["generation_ref"]),
                    "status": str(run["status"]),
                    "workflow_action": str(run["workflow_action"]),
                },
                "evidence": [
                    {
                        "citation_id": str(row["citation_id"]),
                        "chunk_id": row["chunk_id"],
                        "document_id": row["document_id"],
                        "rank": int(row["rank_order"]),
                        "source_version": row["source_version"],
                        "source_hash": row["source_hash"],
                        "title": row["citation_title"],
                        "organization": row["citation_organization"],
                        "locator": row["locator"],
                    }
                    for row in evidence
                ],
                "encrypted_message_count": len(ciphertext_values),
                "encrypted_message_bytes": [len(value) for value in ciphertext_values],
                "plaintext_probe_matches": sum(
                    message_probe.encode("utf-8") in value for value in ciphertext_values
                ),
            }
    finally:
        await engine.dispose()


def _api_snapshot(backend_url: str, report_id: str) -> dict:
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    root = backend_url.rstrip("/")
    login = _http_json(
        opener,
        "POST",
        f"{root}/api/v1/auth/login",
        body={"username": "student_a", "password": "synthetic-student-a"},
    )
    csrf = str(login["data"]["csrf_token"])
    report = _http_json(opener, "GET", f"{root}/api/v1/reports/{report_id}")["data"]
    citations = list(report.get("citations") or [])
    generation = report.get("generation") or {}
    provenance = generation.get("provenance") or {}
    return {
        "report_id": str(report.get("report_id")),
        "status": report.get("status"),
        "safety_action": report.get("safety_action"),
        "normal_generation": bool(report.get("normal_generation", True)),
        "citation_count": len(citations),
        "citations": citations,
        "retrieval_id": provenance.get("retrieval_id"),
        "model_id": provenance.get("model_id"),
        "generation_id": generation.get("generation_id"),
        "integration_labels": report.get("integration_labels"),
        "content_present": report.get("content") is not None,
        "session_cookie_names": sorted(cookie.name for cookie in jar),
        "csrf_received": bool(csrf),
    }


def _canonical_citation(value: dict) -> dict:
    return {
        "citation_id": value.get("citation_id"),
        "chunk_id": value.get("chunk_id"),
        "document_id": value.get("document_id"),
        "rank": value.get("rank"),
        "source_version": value.get("source_version"),
        "source_hash": value.get("source_hash"),
        "title": value.get("title"),
        "organization": value.get("organization"),
        "locator": value.get("locator"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-url", default=os.environ.get("SMHAI_BACKEND_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--phase", choices=("capture", "post-restart"), required=True)
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL is required")
    state = json.loads(args.state.read_text(encoding="utf-8"))
    report_id = str(state["reports"]["normal"]["report_id"])
    api = _api_snapshot(args.backend_url, report_id)
    message_probe = "我想把这次合成演示中的学习压力拆成一个今天可以完成的小行动。"
    database = asyncio.run(_database_snapshot(args.database_url, report_id, message_probe))
    api_citations = [_canonical_citation(item) for item in api["citations"]]
    db_citations = [_canonical_citation(item) for item in database["evidence"]]
    result = {
        "phase": args.phase,
        "backend_url": args.backend_url,
        "report_id": report_id,
        "api": api,
        "database": database,
        "provenance": {
            "retrieval_count": len(api_citations),
            "support_result_count": len(api_citations),
            "persisted_count": len(db_citations),
            "api_readback_count": len(api_citations),
            "identity_match": api_citations == db_citations,
            "silent_truncation": len(api_citations) != len(db_citations)
            or api_citations != db_citations,
            "plaintext_not_persisted": database["plaintext_probe_matches"] == 0,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"phase": args.phase, "report_id": report_id, "citation_count": len(api_citations), "identity_match": result["provenance"]["identity_match"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
