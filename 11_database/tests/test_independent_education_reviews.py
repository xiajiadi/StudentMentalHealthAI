from __future__ import annotations

import ast
import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from database_layer.crypto import FernetDataProtectionProvider, MappingKeyProvider
from database_layer.models import SchoolIndependentEducationReview
from database_layer.school_independent_education_reviews import (
    IndependentEducationReviewError,
    SchoolIndependentEducationReviewRepository,
)

_NOW = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
_DRAFT_SCHEMA = "independent-research-education-reviewed-draft.v1"


def test_withdrawn_keeps_published_revocation_timestamp_in_migration() -> None:
    model_check = next(
        constraint
        for constraint in SchoolIndependentEducationReview.__table__.constraints
        if getattr(constraint, "name", None)
        == "ck_school_independent_education_reviews_state_timestamps_match"
    )
    model_sql = re.sub(r"\s+", "", str(model_check.sqltext))
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20261016_0024_student_independent_education_reviews.py"
    )
    tree = ast.parse(migration_path.read_text(encoding="utf-8"))
    migration_sql = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "CheckConstraint" or not node.args:
            continue
        kwargs = {item.arg: item.value for item in node.keywords if item.arg is not None}
        if isinstance(kwargs.get("name"), ast.Constant) and kwargs["name"].value == (
            "ck_school_independent_education_reviews_state_timestamps_match"
        ):
            migration_sql = ast.literal_eval(node.args[0])
            break

    assert migration_sql is not None
    normalized_migration_sql = re.sub(r"\s+", "", migration_sql)
    assert model_sql == normalized_migration_sql
    assert "(revoked_atISNULLOR(published_atISNOTNULLANDcontent_revision>=1))" in model_sql


class _Session:
    def __init__(self):
        self.added = []

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None


def _draft(protection):
    return protection.encrypt_json(
        {
            "schema_version": _DRAFT_SCHEMA,
            "title": "Synthetic title",
            "body": "Synthetic body kept unchanged.",
            "citations": [{"citation_id": "CITATION_test_1"}],
            "source_cards": [{"chunk_id": "CHUNK_SCHOOL_RESEARCH_RECORD_1"}],
            "candidate_content_sha256": "a" * 64,
            "source_manifest_sha256": "b" * 64,
            "publish_safety_check": None,
        },
        payload_schema_version=_DRAFT_SCHEMA,
    )


def _row(protection):
    encrypted = _draft(protection)
    return SchoolIndependentEducationReview(
        id=1,
        public_id="00000000-0000-4000-8000-000000000001",
        review_ref="EDUREV_" + "e" * 32,
        school_id=1,
        subject_id=2,
        support_session_id=3,
        support_run_id=4,
        reviewer_membership_role_id=5,
        consent_notice_version="independent-education-share.v1",
        status="DRAFT",
        state_version=3,
        content_revision=2,
        reviewed_content_sha256="c" * 64,
        reviewed_payload_ciphertext=encrypted.ciphertext,
        reviewed_cipher_format_version=encrypted.cipher_format_version,
        reviewed_key_version=encrypted.key_version,
        reviewed_payload_schema_version=encrypted.payload_schema_version,
        created_at=_NOW.replace(tzinfo=None),
        updated_at=_NOW.replace(tzinfo=None),
        reviewed_at=_NOW.replace(tzinfo=None),
        retention_due_at=None,
    )


def test_publish_safety_receipt_is_encrypted_without_revising_draft_content() -> None:
    protection = FernetDataProtectionProvider(
        MappingKeyProvider({"test-only": Fernet.generate_key()}, "test-only")
    )
    session = _Session()
    repository = SchoolIndependentEducationReviewRepository(session, protection)
    row = _row(protection)
    safety_receipt = {
        "operation": "OUTPUT",
        "action": "PROCEED_WITH_BOUNDARY",
        "reason_codes": ["SYNTHETIC_TEST"],
        "requires_human": False,
        "decision_id": "DEC_test_publish",
        "trace_id": "TRACE_test_publish",
        "checked_material_sha256": "d" * 64,
    }
    published_payload = {
        "schema_version": _DRAFT_SCHEMA,
        "title": "Synthetic title",
        "body": "Synthetic body kept unchanged.",
        "citations": [{"citation_id": "CITATION_test_1"}],
        "source_cards": [{"chunk_id": "CHUNK_SCHOOL_RESEARCH_RECORD_1"}],
        "candidate_content_sha256": "a" * 64,
        "source_manifest_sha256": "b" * 64,
        "publish_safety_check": safety_receipt,
    }

    updated = asyncio.run(
        repository.transition(
            row=row,
            expected_version=3,
            to_status="PUBLISHED",
            actor_membership_role_id=5,
            reviewer_membership_role_id=5,
            trace_id="TRACE_test_publish",
            now=_NOW,
            reviewed_payload=published_payload,
        )
    )
    restored = asyncio.run(repository.get_reviewed_payload(updated))

    assert updated.status == "PUBLISHED"
    assert updated.state_version == 4
    assert updated.content_revision == 2
    assert updated.reviewed_at == _NOW.replace(tzinfo=None)
    assert restored is not None
    assert restored["title"] == "Synthetic title"
    assert restored["body"] == "Synthetic body kept unchanged."
    assert restored["publish_safety_check"] == safety_receipt
    assert session.added[-1].event_type == "PUBLISHED"


def test_publish_without_safety_receipt_is_rejected_without_state_change() -> None:
    protection = FernetDataProtectionProvider(
        MappingKeyProvider({"test-only": Fernet.generate_key()}, "test-only")
    )
    repository = SchoolIndependentEducationReviewRepository(_Session(), protection)
    row = _row(protection)
    unsafe_payload = {
        "schema_version": _DRAFT_SCHEMA,
        "title": "Synthetic title",
        "body": "Synthetic body kept unchanged.",
        "citations": [{"citation_id": "CITATION_test_1"}],
        "source_cards": [{"chunk_id": "CHUNK_SCHOOL_RESEARCH_RECORD_1"}],
        "candidate_content_sha256": "a" * 64,
        "source_manifest_sha256": "b" * 64,
        "publish_safety_check": None,
    }

    with pytest.raises(IndependentEducationReviewError) as raised:
        asyncio.run(
            repository.transition(
                row=row,
                expected_version=3,
                to_status="PUBLISHED",
                actor_membership_role_id=5,
                reviewer_membership_role_id=5,
                trace_id="TRACE_test_publish",
                now=_NOW,
                reviewed_payload=unsafe_payload,
            )
        )

    assert raised.value.code == "PUBLISH_SAFETY_RECEIPT_REQUIRED"
    assert row.status == "DRAFT"
    assert row.state_version == 3

    invalid_payload = dict(unsafe_payload)
    invalid_payload["publish_safety_check"] = {
        "operation": "OUTPUT",
        "action": "PROCEED",
        "reason_codes": ["SYNTHETIC_TEST"],
        "requires_human": True,
        "decision_id": None,
        "trace_id": "TRACE_test_publish",
        "checked_material_sha256": "d" * 64,
    }
    with pytest.raises(IndependentEducationReviewError) as raised:
        asyncio.run(
            repository.transition(
                row=row,
                expected_version=3,
                to_status="PUBLISHED",
                actor_membership_role_id=5,
                reviewer_membership_role_id=5,
                trace_id="TRACE_test_publish",
                now=_NOW,
                reviewed_payload=invalid_payload,
            )
        )

    assert raised.value.code == "PUBLISH_SAFETY_RECEIPT_INVALID"
    assert row.status == "DRAFT"
    assert row.state_version == 3


def test_revoked_review_can_only_be_withdrawn_and_keeps_revocation_history() -> None:
    protection = FernetDataProtectionProvider(
        MappingKeyProvider({"test-only": Fernet.generate_key()}, "test-only")
    )
    repository = SchoolIndependentEducationReviewRepository(_Session(), protection)
    row = _row(protection)
    row.status = "PUBLISHED"
    row.state_version = 4
    row.published_at = _NOW.replace(tzinfo=None)

    revoked = asyncio.run(
        repository.transition(
            row=row,
            expected_version=4,
            to_status="REVOKED",
            actor_membership_role_id=5,
            reviewer_membership_role_id=5,
            trace_id="TRACE_revoke_review",
            now=_NOW,
        )
    )
    revoked_at = revoked.revoked_at
    published_at = revoked.published_at
    withdrawn = asyncio.run(
        repository.transition(
            row=revoked,
            expected_version=5,
            to_status="WITHDRAWN",
            actor_membership_role_id=2,
            trace_id="TRACE_withdraw_review",
            now=_NOW.replace(minute=1),
        )
    )

    assert withdrawn.status == "WITHDRAWN"
    assert withdrawn.revoked_at == revoked_at
    assert withdrawn.published_at == published_at
    assert withdrawn.state_version == 6
    with pytest.raises(IndependentEducationReviewError) as raised:
        asyncio.run(
            repository.transition(
                row=withdrawn,
                expected_version=6,
                to_status="SHARED",
                actor_membership_role_id=2,
                reviewer_membership_role_id=5,
                trace_id="TRACE_reshare_after_withdraw",
                now=_NOW.replace(minute=2),
            )
        )
    assert raised.value.code == "STALE_OR_INVALID_TRANSITION"
    assert row.content_revision == 2
