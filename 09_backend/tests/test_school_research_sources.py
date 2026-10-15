from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from rag_engine.research.student_education import (
    SchoolStudentPackageError,
    load_school_student_package,
)

from smhai_backend.core.errors import (
    BackendError,
    ErrorCode,
    backend_error_handler,
    error,
    unhandled_error_handler,
    validation_error_handler,
)
from smhai_backend.core.request_context import make_context
from smhai_backend.domains.auth.dependencies import current_actor
from smhai_backend.domains.models import Actor, BackendRole, SchoolRoleContext
from smhai_backend.domains.school_research_sources.router import router
from smhai_backend.domains.school_research_sources.service import SchoolResearchSourcesService

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
SCHOOL_ID = 71
STUDY_REF = "school-noncommercial-rag-research-2027-06"
BASE = "/api/v1/school/research-sources"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _source(source_id: str, layer: str, text: str) -> tuple[dict[str, object], dict[str, object]]:
    source: dict[str, object] = {
        "source_id": source_id,
        "title": f"Public source {source_id}",
        "canonical_url": f"https://example.org/{source_id.lower()}",
        "publisher": "Example publisher",
        "publication_date": "2024",
        "source_population_scope": "Source population as stated by the publication",
        "source_language": "English",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": "Example publisher, CC BY 4.0",
        "rights_evidence_url": f"https://example.org/{source_id.lower()}/rights",
        "rights_evidence_sha256": _sha(f"{source_id}-rights"),
        "rights_status": "VERIFIED_WITH_CONDITIONS",
        "rights_scope_note": "Noncommercial research with attribution",
        "student_retrieval_eligible": True,
        "source_capture_sha256": _sha(f"{source_id}-capture"),
    }
    record = {
        "record_id": f"{source_id}_RECORD",
        "source_id": source_id,
        "layer": layer,
        "text": text,
        "locator": "Abstract",
        "excerpt_sha256": _sha(text),
        "source_population_scope": source["source_population_scope"],
        "consumer_scope": "secondary_school_student_13_18",
        "language": "English",
        "certainty": "Source statement only",
        "role_fit": "General education only",
        "student_retrieval_eligible": True,
    }
    return source, record


def _manifest(*, rights_status: str = "VERIFIED_WITH_CONDITIONS") -> dict[str, object]:
    rows = [
        _source("SRC_POLICY", "policy", "Policy source text"),
        _source("SRC_THEORY", "theory", "Theory source text"),
        _source("SRC_INTERVENTION", "intervention", "Intervention source text"),
    ]
    sources = [source for source, _ in rows]
    if rights_status != "VERIFIED_WITH_CONDITIONS":
        sources[0]["rights_status"] = rights_status
        sources[0]["student_retrieval_eligible"] = False
        rows[0][1]["student_retrieval_eligible"] = False
    return {
        "schema_version": "psynova.school-research-student-knowledge.v1",
        "package_id": "student-source-package-fixture-v1",
        "package_status": "ENGINEERING_REVIEWED_RESEARCH_ONLY",
        "reviewer_kind": "AI_ENGINEERING",
        "review_ref": "source-review-fixture-v1",
        "consumer_scope": "secondary_school_student_13_18",
        "study_ref": STUDY_REF,
        "use_policy": {
            "scope": "ISOLATED_GENERAL_EDUCATION_SIMULATION",
            "noncommercial": True,
            "valid_through": "2027-06-30T15:59:59Z",
            "audience": "Fictional secondary-school student simulation only",
            "allowed_content": (
                "English source excerpts and source-bound general educational information only"
            ),
            "prohibited_content": [
                "individualized advice", "assessment score interpretation", "diagnosis",
                "treatment", "crisis or risk inference", "claims of guaranteed personal outcome",
            ],
            "language": (
                "Preserve source wording in English; no translation is represented as source text."
            ),
        },
        "flags": {
            "human_curated": False,
            "professional_approval": False,
            "ethics_approval": False,
            "clinical_approval": False,
            "psychometric_approval": False,
            "publication_eligible": False,
            "production_use": False,
        },
        "role_scope": ["student"],
        "risk_scope": ["normal"],
        "review_status": "pending",
        "sources": sources,
        "records": [record for _, record in rows],
    }


def _load_package(tmp_path: Path, manifest: dict[str, object] | None = None):
    raw = json.dumps(manifest or _manifest(), ensure_ascii=False, separators=(",", ":")).encode()
    path = tmp_path / "source-package-manifest.json"
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    package = load_school_student_package(
        path,
        expected_manifest_sha256=digest,
        expected_study_ref=STUDY_REF,
        now=NOW,
    )
    return package, digest


def _actor(
    role: BackendRole = BackendRole.PSYCHOLOGICAL_SPECIALIST,
    *,
    school_id: int = SCHOOL_ID,
    scope_profile: str = "school_tenant",
) -> Actor:
    return Actor(
        user_id="USER_synthetic_specialist",
        username="synthetic-specialist",
        role=role,
        subject_id=None,
        scope_profile=scope_profile,
        school_id=school_id,
        school_ref="SCHOOL_synthetic",
        school_contexts=(
            SchoolRoleContext(
                context_id="ROLE_synthetic_specialist",
                role=role,
                school_id=school_id,
                school_ref="SCHOOL_synthetic",
            ),
        ),
    )


class _Auth:
    async def actor_for_session(self, *_args, **_kwargs):
        raise error(ErrorCode.AUTH_SESSION_EXPIRED, detail="authentication is required")


def _app(actor: Actor | None, service: Any | None):
    app = FastAPI()
    app.state.container = SimpleNamespace(
        settings=SimpleNamespace(
            cookie_name="smhai_dev_session",
            auth=SimpleNamespace(csrf_header_name="X-CSRF-Token"),
            allowed_origins=[],
        ),
        auth=_Auth(),
        school_research_sources=service,
    )
    app.add_exception_handler(BackendError, backend_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
    from fastapi.exceptions import RequestValidationError

    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(router, prefix="/api/v1")

    @app.middleware("http")
    async def request_context(request, call_next):
        request.state.request_context = make_context(request)
        return await call_next(request)

    if actor is not None:

        async def provide_actor(request: Request):
            return actor

        app.dependency_overrides[current_actor] = provide_actor
    return app


async def _request(app, method: str, path: str):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path)


def _service(package, digest: str, *, expected_school_id: int = SCHOOL_ID, clock=lambda: NOW):
    return SchoolResearchSourcesService(
        package=package,
        expected_school_id=expected_school_id,
        expected_manifest_sha256=digest,
        expected_study_ref=STUDY_REF,
        clock=clock,
    )


@pytest.mark.asyncio
async def test_specialist_catalog_and_detail_project_only_validated_source_metadata(
    tmp_path: Path,
) -> None:
    package, digest = _load_package(tmp_path)
    app = _app(_actor(), _service(package, digest))

    page_response = await _request(app, "GET", f"{BASE}/catalog?limit=2&offset=0")
    assert page_response.status_code == 200
    page = page_response.json()["data"]
    assert page["schema_version"] == "school.research-source-catalog.v1"
    assert page["total"] == 3 and page["limit"] == 2 and page["has_more"] is True
    assert {item["source_ref"] for item in page["items"]} == {"SRC_INTERVENTION", "SRC_POLICY"}
    assert all("text" not in item and "source_path" not in item for item in page["items"])
    assert page["review"] == {
        "package_status": "ENGINEERING_REVIEWED_RESEARCH_ONLY",
        "reviewer_kind": "AI_ENGINEERING",
        "review_status": "pending",
        "professional_approval": False,
        "ethics_approval": False,
        "clinical_approval": False,
        "psychometric_approval": False,
        "publication_eligible": False,
        "production_use": False,
    }

    detail_response = await _request(app, "GET", f"{BASE}/SRC_POLICY")
    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert detail["source_ref"] == "SRC_POLICY"
    assert detail["layers"] == ["policy"]
    assert detail["rights_status"] == "VERIFIED_WITH_CONDITIONS"
    assert detail["license"] == "CC BY 4.0"
    assert detail["rights_scope_note"] == "Noncommercial research with attribution"
    assert "text" not in detail and "records" not in detail and "source_path" not in detail


@pytest.mark.asyncio
async def test_catalog_rejects_other_roles_and_cross_school_specialist(tmp_path: Path) -> None:
    package, digest = _load_package(tmp_path)
    service = _service(package, digest)
    for actor in (
        _actor(BackendRole.TEACHER),
        _actor(BackendRole.PSYCHOLOGICAL_SPECIALIST, school_id=SCHOOL_ID + 1),
    ):
        response = await _request(_app(actor, service), "GET", f"{BASE}/catalog")
        assert response.status_code == 403
        assert response.json()["code"] == "forbidden"


@pytest.mark.asyncio
async def test_missing_catalog_service_and_untrusted_package_fail_closed(tmp_path: Path) -> None:
    unavailable = await _request(_app(_actor(), None), "GET", f"{BASE}/catalog")
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "dependency_unavailable"

    package, digest = _load_package(tmp_path)
    revoked_source = replace(package.sources[0], rights_status="REVOKED")
    malformed_package = replace(package, sources=(revoked_source, *package.sources[1:]))
    service = _service(malformed_package, digest)
    response = await _request(_app(_actor(), service), "GET", f"{BASE}/catalog")
    assert response.status_code == 502
    assert response.json()["code"] == "dependency_invalid_response"


@pytest.mark.asyncio
async def test_expired_package_and_revoked_manifest_are_unavailable(tmp_path: Path) -> None:
    package, digest = _load_package(tmp_path)
    expired = _service(package, digest, clock=lambda: datetime(2027, 7, 1, tzinfo=UTC))
    response = await _request(_app(_actor(), expired), "GET", f"{BASE}/catalog")
    assert response.status_code == 503
    assert response.json()["code"] == "dependency_unavailable"

    with pytest.raises(SchoolStudentPackageError, match="STUDENT_SOURCE_RIGHTS_INVALID"):
        _load_package(tmp_path, _manifest(rights_status="REVOKED"))


def test_pending_rights_source_remains_visible_without_retrieval_eligibility(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    pending_source, pending_record = _source(
        "SRC_PENDING", "intervention", "Pending source is metadata only"
    )
    pending_source["rights_status"] = "PENDING"
    pending_source["student_retrieval_eligible"] = False
    pending_record["student_retrieval_eligible"] = False
    sources = manifest["sources"]
    records = manifest["records"]
    assert isinstance(sources, list) and isinstance(records, list)
    sources.append(pending_source)
    records.append(pending_record)
    package, digest = _load_package(tmp_path, manifest)

    page = _service(package, digest).list_sources(_actor())
    pending = next(item for item in page.items if item.source_ref == "SRC_PENDING")
    assert pending.rights_status == "PENDING"
    assert pending.retrieval_eligible is False


@pytest.mark.asyncio
async def test_catalog_query_is_closed_and_unknown_source_is_not_found(tmp_path: Path) -> None:
    package, digest = _load_package(tmp_path)
    app = _app(_actor(), _service(package, digest))
    unknown_query = await _request(app, "GET", f"{BASE}/catalog?path=private")
    assert unknown_query.status_code == 422
    unknown_source = await _request(app, "GET", f"{BASE}/SRC_NOT_PRESENT")
    assert unknown_source.status_code == 404
