from __future__ import annotations

from types import SimpleNamespace

import pytest

from smhai_backend.core.config import ModuleClientSettings
from smhai_backend.core.errors import BackendError
from smhai_backend.core.request_context import RequestContext
from smhai_backend.integrations.safety import ContractFakeSafetyClient
from smhai_backend.integrations.student_research_safety import (
    SchoolResearchStudentSafetyClient,
)

_HASH = "a" * 64
_STUDY = "school-noncommercial-rag-research-2027-06"


def _package():
    record = SimpleNamespace(
        record_id="THEORY_RECORD",
        source_id="THEORY_SOURCE",
        text="A short public educational excerpt.",
        excerpt_sha256=_HASH,
        student_retrieval_eligible=True,
    )
    source = SimpleNamespace(
        source_id="THEORY_SOURCE",
        rights_status="VERIFIED_WITH_CONDITIONS",
        rights_scope_note="Attribution required; noncommercial research use.",
        student_retrieval_eligible=True,
    )
    return SimpleNamespace(
        manifest_sha256=_HASH,
        package_id="student-package-v1",
        study_ref=_STUDY,
        records=(record,),
        sources=(source,),
    )


class _StubResearchSafetyClient(SchoolResearchStudentSafetyClient):
    def __init__(self):
        super().__init__(
            standard_safety=ContractFakeSafetyClient(),
            settings=ModuleClientSettings(mode="http", base_url="http://127.0.0.1:8191"),
            package=_package(),
            expected_manifest_sha256=_HASH,
            expected_package_id="student-package-v1",
            expected_study_ref=_STUDY,
        )
        self.calls = []

    async def post_json(self, path, payload, *, context, headers=None):
        self.calls.append((path, payload))
        return {
            "operation": "RETRIEVAL",
            "decision": {
                "action": "PROCEED",
                "reason_codes": ["NO_BLOCKING_SIGNAL"],
                "requires_human": False,
                "trace_id": context.trace_id,
            },
            "trace_id": context.trace_id,
        }


def _chunk():
    return {
        "chunk_id": "CHUNK_SCHOOL_RESEARCH_THEORY_RECORD",
        "text": "A short public educational excerpt.",
        "content_hash": f"sha256:{_HASH}",
        "review_status": "pending",
        "rights_status": "verified",
        "population_scope": ["secondary_school_student"],
        "role_scope": ["student"],
        "risk_scope": ["normal"],
        "citation": {"title": "Public source", "organization": "Publisher", "locator": "source"},
    }


@pytest.mark.asyncio
async def test_research_safety_projects_only_exact_pinned_public_chunk_metadata():
    client = _StubResearchSafetyClient()
    context = RequestContext(request_id="REQ_test", trace_id="TRACE_test")

    result = await client.check_retrieval(
        {
            "current_user_message": "private student text must not be forwarded",
            "conversation_metadata": {"private": "not forwarded"},
        },
        [_chunk()],
        context,
    )

    assert result.decision.action == "PROCEED"
    path, payload = client.calls[0]
    assert path == "/_research/safety/check-retrieval"
    assert payload == {
        "schema_version": "psynova.school-student-research-safety.v1",
        "request_id": "REQ_test",
        "trace_id": "TRACE_test",
        "study_ref": _STUDY,
        "package_id": "student-package-v1",
        "manifest_sha256": _HASH,
        "purpose": "RESEARCH_SIMULATION",
        "consumer_age_scope": "14-17",
        "chunks": [
            {
                "chunk_id": "CHUNK_SCHOOL_RESEARCH_THEORY_RECORD",
                "content": "A short public educational excerpt.",
                "metadata": {
                    "source_id": "THEORY_SOURCE",
                    "record_id": "THEORY_RECORD",
                    "content_hash": _HASH,
                    "manifest_sha256": _HASH,
                    "rights_scope_note": "Attribution required; noncommercial research use.",
                    "review_status": "pending",
                    "rights_status": "verified",
                    "role_scope": ["student"],
                    "population_scope": ["secondary_school_student"],
                    "risk_scope": ["normal"],
                },
            }
        ],
    }


@pytest.mark.asyncio
async def test_research_safety_rejects_unpinned_chunk_before_network_call():
    client = _StubResearchSafetyClient()
    chunk = _chunk()
    chunk["content_hash"] = f"sha256:{'b' * 64}"

    with pytest.raises(BackendError):
        await client.check_retrieval(
            {},
            [chunk],
            RequestContext(request_id="REQ_test", trace_id="TRACE_test"),
        )

    assert client.calls == []


def test_research_safety_client_refuses_any_nonisolated_url():
    with pytest.raises(ValueError, match="pins are invalid"):
        SchoolResearchStudentSafetyClient(
            standard_safety=ContractFakeSafetyClient(),
            settings=ModuleClientSettings(mode="http", base_url="http://127.0.0.1:8190"),
            package=_package(),
            expected_manifest_sha256=_HASH,
            expected_package_id="student-package-v1",
            expected_study_ref=_STUDY,
        )
