from __future__ import annotations

import sys
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace

import pytest

from smhai_backend.adapters.school_professional_reviews import (
    SchoolProfessionalReviewPersistenceAdapter,
)
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.domains.models import Actor, BackendRole, SchoolRoleContext


class Column:
    def __eq__(self, _other):
        return self

    def __le__(self, _other):
        return self

    def __ge__(self, _other):
        return self

    def __and__(self, _other):
        return self

    def __or__(self, _other):
        return self

    def is_(self, _other):
        return self

    def is_not(self, _other):
        return self

    def in_(self, _other):
        return self


class ModelMeta(type):
    def __getattr__(cls, _name):
        if _name == "specialist_membership_role":
            raise AttributeError(_name)
        return Column()


class Model(metaclass=ModelMeta):
    def __init__(self, **values):
        self.__dict__.update(values)


class Query:
    def __init__(self, *_columns):
        pass

    def join(self, *_args, **_kwargs):
        return self

    def outerjoin(self, *_args, **_kwargs):
        return self

    def distinct(self, *_args, **_kwargs):
        return self

    def where(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def offset(self, *_args, **_kwargs):
        return self

    def with_for_update(self, *_args, **_kwargs):
        return self

    def select_from(self, *_args, **_kwargs):
        return self

    def subquery(self, *_args, **_kwargs):
        return self


class ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, *, scalar_values=(), scalar_rows=(), execute_rows=()):
        self.scalar_values = list(scalar_values)
        self.scalar_rows = list(scalar_rows)
        self.execute_rows = list(execute_rows)
        self.added = []
        self.flush_count = 0

    async def scalar(self, _statement):
        return self.scalar_values.pop(0)

    async def scalars(self, _statement):
        return ScalarRows(self.scalar_rows.pop(0))

    async def execute(self, _statement):
        return ScalarRows(self.execute_rows.pop(0))

    def add(self, record):
        self.added.append(record)

    async def flush(self):
        self.flush_count += 1


class FakeAudit:
    def __init__(self):
        self.records = []
        self.fail = False

    async def append(self, **kwargs):
        self.records.append(kwargs)
        if self.fail:
            raise RuntimeError("synthetic audit failure")


class FakeUow:
    def __init__(self, session=None):
        self.session = session or FakeSession()
        self.audit = FakeAudit()
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, _exc, _tb):
        if exc_type is None:
            self.committed = True
        else:
            self.rolled_back = True


class FakeBackend:
    identity_profile = "school_tenant"
    _select = staticmethod(lambda *columns: Query(*columns))
    _db_models = SimpleNamespace(
        School=Model,
        SchoolClass=Model,
        Account=Model,
        AccountSchoolMembership=Model,
        MembershipRole=Model,
        MeasurementTask=Model,
        SchoolTaskSpecialistAssignment=Model,
        SchoolProfessionalReviewCase=Model,
        SchoolProfessionalReviewEvent=Model,
        TaskEnrollment=Model,
        AssessmentSession=Model,
        Subject=Model,
    )
    _db_enums = SimpleNamespace(
        AuditResult=SimpleNamespace(SUCCESS="SUCCESS"),
        AccountStatus=SimpleNamespace(ACTIVE=SimpleNamespace(value="ACTIVE")),
        AssessmentStatus=SimpleNamespace(COMPLETED=SimpleNamespace(value="COMPLETED")),
        DataOrigin=SimpleNamespace(SYNTHETIC=SimpleNamespace(value="SYNTHETIC")),
        SubjectStatus=SimpleNamespace(ACTIVE=SimpleNamespace(value="ACTIVE")),
    )

    def __init__(self, uows):
        self.uows = list(uows)
        self.now = datetime(2026, 10, 12, tzinfo=UTC)

    def _utc_now(self):
        return self.now

    def _uow(self):
        return self.uows.pop(0)


def specialist_actor():
    context = SchoolRoleContext(
        context_id="role-specialist",
        role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
        school_id=17,
        school_ref="SCHOOL_synthetic",
    )
    return Actor(
        user_id="USER_synthetic-reviewer",
        username="synthetic-reviewer",
        role=BackendRole.PSYCHOLOGICAL_SPECIALIST,
        subject_id=None,
        scope_profile="school_tenant",
        school_id=17,
        school_ref="SCHOOL_synthetic",
        school_contexts=(context,),
    )


def admin_actor():
    context = SchoolRoleContext(
        context_id="role-admin",
        role=BackendRole.ADMIN,
        school_id=17,
        school_ref="SCHOOL_synthetic",
    )
    return Actor(
        user_id="USER_synthetic-admin",
        username="synthetic-admin",
        role=BackendRole.ADMIN,
        subject_id=None,
        scope_profile="school_tenant",
        school_id=17,
        school_ref="SCHOOL_synthetic",
        school_contexts=(context,),
    )


def patch_adapter(adapter, *, role_id=11, account_id=10, task=None):
    actor_checks = []
    async def require_actor(_uow, actor, role_code, at):
        actor_checks.append((actor, role_code, at))
        return account_id, role_id

    async def get_task(_uow, actor, task_ref, *, lock):
        return task or SimpleNamespace(id=20, class_id=30, task_ref=task_ref)

    adapter._require_actor = require_actor
    adapter._task = get_task
    return actor_checks


class FakeEncrypted:
    def __init__(self, ciphertext, key_version, cipher_format_version, payload_schema_version):
        self.ciphertext = ciphertext
        self.key_version = key_version
        self.cipher_format_version = cipher_format_version
        self.payload_schema_version = payload_schema_version


class FakeProtection:
    cipher_format_version = "fernet.v1"

    def __init__(self):
        self.decrypted_payload = None
        self.encrypt_calls = []

    def encrypt_json(self, payload, *, payload_schema_version):
        self.encrypt_calls.append((dict(payload), payload_schema_version))
        self.decrypted_payload = dict(payload)
        return FakeEncrypted(
            b"sealed-note",
            "key-v1",
            self.cipher_format_version,
            payload_schema_version,
        )

    def decrypt_json(self, _encrypted):
        return self.decrypted_payload


def install_fake_crypto(monkeypatch, protection):
    database_layer = ModuleType("database_layer")
    crypto = ModuleType("database_layer.crypto")
    crypto.EncryptedPayload = FakeEncrypted
    monkeypatch.setitem(sys.modules, "database_layer", database_layer)
    monkeypatch.setitem(sys.modules, "database_layer.crypto", crypto)


@pytest.mark.asyncio
async def test_revoke_and_idempotency_replay_work_without_orm_relationship_attributes():
    assignment = SimpleNamespace(
        public_id="assignment-public-id",
        specialist_membership_role_id=55,
        status="ACTIVE",
        revoked_at=None,
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    actor = admin_actor()
    calls = []
    row_for_revoke = assignment
    session = FakeSession(scalar_values=[row_for_revoke, "synthetic-specialist"])
    uow = FakeUow(session)
    backend = FakeBackend([uow])
    adapter = SchoolProfessionalReviewPersistenceAdapter(backend)
    patch_adapter(adapter)

    async def begin(_uow, _idem):
        calls.append("begin")
        return SimpleNamespace(replayed=False, record=object())

    async def complete(_uow, _claim, **kwargs):
        calls.append(("complete", kwargs))

    adapter._school_idempotency_begin = begin
    adapter._school_idempotency_complete = complete
    assert not hasattr(assignment, "specialist_membership_role")
    revoked = await adapter.school_professional_review_revoke(
        actor,
        "TASK_synthetic_1",
        "ASSIGN_assignment-public-id",
        idempotency=("key", "a" * 64, "scope"),
        trace_id="TRACE_synthetic",
    )
    assert revoked["status"] == "REVOKED"
    assert revoked["specialist_user_id"] == "USER_synthetic-specialist"
    assert assignment.revoked_at == backend.now
    assert [call[0] if isinstance(call, tuple) else call for call in calls] == [
        "begin",
        "complete",
    ]
    assert uow.committed
    assert len(uow.audit.records) == 1

    replay_assignment = SimpleNamespace(
        public_id="assignment-public-id",
        specialist_membership_role_id=55,
        status="REVOKED",
        revoked_at=backend.now,
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    replay_uow = FakeUow(
        FakeSession(scalar_values=[replay_assignment, "synthetic-specialist"])
    )
    replay_backend = FakeBackend([replay_uow])
    replay_adapter = SchoolProfessionalReviewPersistenceAdapter(replay_backend)
    patch_adapter(replay_adapter)
    replay_calls = []

    async def replay_begin(_uow, _idem):
        replay_calls.append("begin")
        return SimpleNamespace(
            replayed=True,
            record=SimpleNamespace(
                result_resource_type="school_task_specialist_assignment",
                result_public_id="assignment-public-id",
            ),
        )

    async def unexpected_complete(*_args, **_kwargs):
        raise AssertionError("replay must not complete or mutate the receipt")

    replay_adapter._school_idempotency_begin = replay_begin
    replay_adapter._school_idempotency_complete = unexpected_complete
    replayed = await replay_adapter.school_professional_review_revoke(
        actor,
        "TASK_synthetic_1",
        "ASSIGN_assignment-public-id",
        idempotency=("key", "a" * 64, "scope"),
        trace_id="TRACE_synthetic",
    )
    assert replayed["status"] == "REVOKED"
    assert replay_calls == ["begin"]
    assert replay_uow.audit.records == []
    assert replay_uow.committed


@pytest.mark.asyncio
async def test_revoked_specialist_is_rejected_before_idempotency_replay_lookup():
    uow = FakeUow()
    adapter = SchoolProfessionalReviewPersistenceAdapter(FakeBackend([uow]))
    patch_adapter(adapter)
    calls = []

    async def revoked_assignment(*_args, **_kwargs):
        calls.append("assignment-check")
        raise BackendError(ErrorCode.FORBIDDEN, detail="access denied")

    async def unexpected_begin(*_args, **_kwargs):
        calls.append("idempotency")
        return None

    adapter._active_assignment = revoked_assignment
    adapter._school_idempotency_begin = unexpected_begin
    with pytest.raises(BackendError) as caught:
        await adapter.school_professional_review_open_case(
            specialist_actor(),
            "TASK_synthetic_1",
            "PCR_case-public-id",
            expected_version=1,
            idempotency=("old", "b" * 64, "scope"),
            trace_id="TRACE_synthetic",
        )
    assert caught.value.code is ErrorCode.FORBIDDEN
    assert calls == ["assignment-check"]
    assert uow.rolled_back


@pytest.mark.asyncio
async def test_decision_encrypts_note_and_commits_case_event_audit_and_receipt_together(
    monkeypatch,
):
    row = SimpleNamespace(
        id=99,
        public_id="database-case-id",
        review_ref="review-public-id",
        school_id=17,
        task_enrollment_id=70,
        assessment_session_id=80,
        retention_due_at=None,
        version=4,
        status="IN_REVIEW",
        created_at=datetime(2026, 10, 1),
        updated_at=datetime(2026, 10, 1),
        case_note_ciphertext=None,
        cipher_format_version=None,
        key_version=None,
        payload_schema_version=None,
        closed_at=None,
    )
    session = FakeSession()
    uow = FakeUow(session)
    backend = FakeBackend([uow])
    backend.protection = FakeProtection()
    adapter = SchoolProfessionalReviewPersistenceAdapter(backend)
    patch_adapter(adapter)
    checks = []

    async def active_assignment(_uow, actor, task, *, at, lock):
        checks.append((actor, task, at, lock))
        return object()

    async def begin(_uow, _idem):
        return SimpleNamespace(replayed=False, record=object())

    async def complete(receipt_uow, _claim, **kwargs):
        checks.append(("receipt", receipt_uow, kwargs))

    async def load_case(_uow, _actor, _task, _case_ref, *, lock):
        assert lock
        return row

    async def project(_uow, _actor, _task, current):
        return adapter._case_projection(
            current,
            "TASK_synthetic_1",
            "ENROLL_synthetic_1",
            "ASSESS_synthetic_1",
            adapter._decrypt_note(current),
        )

    adapter._active_assignment = active_assignment
    adapter._school_idempotency_begin = begin
    adapter._school_idempotency_complete = complete
    adapter._case = load_case
    adapter._case_projection_from_row = project
    install_fake_crypto(monkeypatch, backend.protection)

    result_actor = specialist_actor()
    result = await adapter.school_professional_review_process_case(
        result_actor,
        "TASK_synthetic_1",
        "PCR_review-public-id",
        expected_version=4,
        decision="APPROVED",
        note="Synthetic review note.",
        idempotency=("decision", "c" * 64, "scope"),
        trace_id="TRACE_synthetic",
    )

    assert result["status"] == "APPROVED"
    assert result["publication_status"] == "NOT_PUBLISHED"
    assert result["review_note"] == "Synthetic review note."
    assert row.version == 5 and row.closed_at == backend.now
    assert row.case_note_ciphertext == b"sealed-note"
    assert backend.protection.encrypt_calls == [
        ({"note": "Synthetic review note.", "review_ref": "review-public-id"},
         "school_professional_review_note.v1")
    ]
    event = session.added[0]
    assert event.event_type == "TRANSITION"
    assert event.from_status == "IN_REVIEW" and event.to_status == "APPROVED"
    assert event.version == 5 and event.actor_membership_role_id == 11
    assert "note" not in event.__dict__ and "note_ciphertext" not in event.__dict__
    assert uow.audit.records[0]["safe_metadata"] == {
        "source": "school_professional_reviews",
        "state": "APPROVED",
    }
    assert "Synthetic review note." not in str(uow.audit.records[0])
    assert checks[0][0] is result_actor
    assert checks[-1][0] == "receipt" and checks[-1][1] is uow
    assert uow.committed


@pytest.mark.asyncio
async def test_case_note_ciphertext_requires_matching_schema_and_case_reference(monkeypatch):
    protection = FakeProtection()
    backend = FakeBackend([])
    backend.protection = protection
    adapter = SchoolProfessionalReviewPersistenceAdapter(backend)
    install_fake_crypto(monkeypatch, protection)
    row = SimpleNamespace(
        review_ref="review-a",
        case_note_ciphertext=b"encrypted",
        key_version="key-v1",
        cipher_format_version="fernet.v1",
        payload_schema_version="school_professional_review_note.v1",
    )
    protection.decrypted_payload = {"note": "review", "review_ref": "other-case"}
    with pytest.raises(BackendError) as caught:
        adapter._decrypt_note(row)
    assert caught.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE
    assert "other-case" not in str(caught.value)

    row.payload_schema_version = "wrong-schema"
    with pytest.raises(BackendError) as caught:
        adapter._decrypt_note(row)
    assert caught.value.code is ErrorCode.DEPENDENCY_INVALID_RESPONSE


@pytest.mark.asyncio
async def test_expected_version_rejects_values_above_database_integer_range():
    adapter = SchoolProfessionalReviewPersistenceAdapter(FakeBackend([]))
    with pytest.raises(BackendError) as caught:
        await adapter.school_professional_review_open_case(
            specialist_actor(),
            "TASK_synthetic_1",
            "PCR_case-public-id",
            expected_version=2_147_483_648,
            idempotency=("key", "d" * 64, "scope"),
            trace_id="TRACE_synthetic",
        )
    assert caught.value.code is ErrorCode.VALIDATION_FAILED


@pytest.mark.asyncio
async def test_case_queue_projection_never_decrypts_review_note():
    session = FakeSession(execute_rows=[[('enrollment-public-id', 'ASSESS_synthetic_1')]])
    uow = FakeUow(session)
    adapter = SchoolProfessionalReviewPersistenceAdapter(FakeBackend([uow]))

    def unexpected_decrypt(_row):
        raise AssertionError("case queue must not decrypt private review notes")

    adapter._decrypt_note = unexpected_decrypt
    row = SimpleNamespace(
        review_ref="review-public-id",
        version=2,
        status="APPROVED",
        task_enrollment_id=80,
        assessment_session_id=90,
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
        updated_at=datetime(2026, 10, 2, tzinfo=UTC),
    )
    projection = await adapter._case_projection_from_row(
        uow,
        specialist_actor(),
        SimpleNamespace(id=60, class_id=30, task_ref="TASK_synthetic_1"),
        row,
        include_note=False,
    )
    assert projection["review_note"] is None
    assert projection["publication_status"] == "NOT_PUBLISHED"


@pytest.mark.asyncio
async def test_case_detail_audits_only_metadata_after_authorized_projection():
    uow = FakeUow()
    backend = FakeBackend([uow])
    adapter = SchoolProfessionalReviewPersistenceAdapter(backend)
    actor = specialist_actor()
    actor_checks = patch_adapter(adapter)
    row = SimpleNamespace(
        review_ref="review-public-id",
        status="IN_REVIEW",
        case_note_ciphertext=b"synthetic-encrypted-note",
    )
    calls = []
    require_actor = adapter._require_actor

    async def authorize(*args, **kwargs):
        calls.append("authorize")
        return await require_actor(*args, **kwargs)

    async def active_assignment(*_args, **_kwargs):
        calls.append("assignment")

    async def load_case(*_args, **_kwargs):
        calls.append("case")
        return row

    async def project(*_args, **_kwargs):
        calls.append("projection")
        return {"review_note": "Synthetic private review note."}

    async def append_audit(**kwargs):
        calls.append("audit")
        uow.audit.records.append(kwargs)

    adapter._active_assignment = active_assignment
    adapter._require_actor = authorize
    adapter._case = load_case
    adapter._case_projection_from_row = project
    uow.audit.append = append_audit

    result = await adapter.school_professional_review_get_case(
        actor, "TASK_synthetic_1", "PCR_review-public-id"
    )

    assert result["review_note"] == "Synthetic private review note."
    assert actor_checks[0][1] == "psychological_specialist"
    assert calls == ["authorize", "assignment", "case", "projection", "audit"]
    audit_record = uow.audit.records[0]
    assert audit_record["actor_account_id"] == 10
    assert audit_record["action"] == "school_professional_review.case_detail_read"
    assert audit_record["resource_type"] == "school_professional_review_case"
    assert audit_record["resource_public_id"] == "review-public-id"
    assert audit_record["trace_id"].startswith("TRACE_")
    assert set(audit_record) == {
        "action",
        "resource_type",
        "resource_public_id",
        "result",
        "trace_id",
        "actor_account_id",
    }
    assert "Synthetic private review note." not in str(audit_record)
    assert b"synthetic-encrypted-note" not in str(audit_record).encode()
    assert uow.committed


@pytest.mark.asyncio
async def test_case_detail_audit_failure_rolls_back_without_mutating_private_note():
    uow = FakeUow()
    uow.audit.fail = True
    backend = FakeBackend([uow])
    adapter = SchoolProfessionalReviewPersistenceAdapter(backend)
    patch_adapter(adapter)
    row = SimpleNamespace(
        review_ref="review-public-id",
        status="IN_REVIEW",
        case_note_ciphertext=b"existing-encrypted-note",
    )

    async def active_assignment(*_args, **_kwargs):
        return object()

    async def load_case(*_args, **_kwargs):
        return row

    async def project(*_args, **_kwargs):
        return {"review_note": "Synthetic private review note."}

    adapter._active_assignment = active_assignment
    adapter._case = load_case
    adapter._case_projection_from_row = project

    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        await adapter.school_professional_review_get_case(
            specialist_actor(), "TASK_synthetic_1", "PCR_review-public-id"
        )

    assert uow.rolled_back and not uow.committed
    assert row.case_note_ciphertext == b"existing-encrypted-note"
    assert uow.session.added == []
    assert "Synthetic private review note." not in str(uow.audit.records)
    assert b"existing-encrypted-note" not in str(uow.audit.records).encode()


@pytest.mark.asyncio
async def test_case_detail_rechecks_fresh_assignment_before_case_or_note_access():
    uow = FakeUow()
    backend = FakeBackend([uow])
    adapter = SchoolProfessionalReviewPersistenceAdapter(backend)
    patch_adapter(adapter)
    calls = []

    async def revoked_assignment(*_args, **_kwargs):
        calls.append("assignment")
        raise BackendError(ErrorCode.FORBIDDEN, detail="access denied")

    async def unexpected_case(*_args, **_kwargs):
        calls.append("case")
        raise AssertionError("case data must not be loaded after assignment denial")

    adapter._active_assignment = revoked_assignment
    adapter._case = unexpected_case
    adapter._case_projection_from_row = unexpected_case

    with pytest.raises(BackendError) as caught:
        await adapter.school_professional_review_get_case(
            specialist_actor(), "TASK_synthetic_1", "PCR_review-public-id"
        )

    assert caught.value.code is ErrorCode.FORBIDDEN
    assert calls == ["assignment"]
    assert uow.audit.records == []
    assert uow.rolled_back and not uow.committed
    assert backend.uows == []


@pytest.mark.asyncio
async def test_specialist_task_picker_returns_only_assigned_task_metadata():
    published_at = datetime(2026, 10, 1, tzinfo=UTC)
    uow = FakeUow(
        FakeSession(
            execute_rows=[
                [("TASK_synthetic_1", "CLASS_synthetic_1", "Demo Class", published_at)]
            ]
        )
    )
    backend = FakeBackend([uow])
    adapter = SchoolProfessionalReviewPersistenceAdapter(backend)
    actor_checks = patch_adapter(adapter)

    rows = await adapter.school_professional_review_list_tasks(specialist_actor())

    assert actor_checks[0][1] == "psychological_specialist"
    assert rows == [
        {
            "task_ref": "TASK_synthetic_1",
            "class_ref": "CLASS_synthetic_1",
            "class_display_name": "Demo Class",
            "published_at": published_at,
        }
    ]
    assert set(rows[0]) == {"task_ref", "class_ref", "class_display_name", "published_at"}
    assert uow.committed


@pytest.mark.asyncio
async def test_admin_specialist_picker_returns_only_user_id_and_nullable_display_name():
    uow = FakeUow(
        FakeSession(
            execute_rows=[
                [("synthetic-specialist", "Synthetic Specialist"), ("unnamed", None)]
            ]
        )
    )
    backend = FakeBackend([uow])
    adapter = SchoolProfessionalReviewPersistenceAdapter(backend)
    actor_checks = patch_adapter(adapter)

    specialists = await adapter.school_professional_review_list_specialists(admin_actor())

    assert actor_checks[0][1] == "admin"
    assert specialists == [
        {"user_id": "USER_synthetic-specialist", "display_name": "Synthetic Specialist"},
        {"user_id": "USER_unnamed", "display_name": None},
    ]
    assert all(set(row) == {"user_id", "display_name"} for row in specialists)
    assert uow.committed


@pytest.mark.asyncio
async def test_eligible_enrollment_picker_rechecks_assignment_and_returns_safe_page(monkeypatch):
    completed_at = datetime(2026, 10, 2, tzinfo=UTC)
    uow = FakeUow(
        FakeSession(
            scalar_values=[1],
            execute_rows=[[('enrollment-public-id', 'ASSESS_synthetic_1', completed_at, None)]],
        )
    )
    backend = FakeBackend([uow])
    adapter = SchoolProfessionalReviewPersistenceAdapter(backend)
    actor = specialist_actor()
    actor_checks = patch_adapter(adapter)
    assignment_checks = []

    async def check_assignment(_uow, actor_arg, task, *, at, lock):
        assignment_checks.append((actor_arg, task, at, lock))

    adapter._active_assignment = check_assignment
    sqlalchemy = ModuleType("sqlalchemy")
    sqlalchemy.func = SimpleNamespace(count=lambda: Column())
    monkeypatch.setitem(sys.modules, "sqlalchemy", sqlalchemy)

    page = await adapter.school_professional_review_list_eligible_enrollments(
        actor,
        "TASK_synthetic_1",
        offset=0,
        limit=20,
    )

    assert actor_checks[0][1] == "psychological_specialist"
    assert assignment_checks[0][0] is actor
    assert assignment_checks[0][1].task_ref == "TASK_synthetic_1"
    assert assignment_checks[0][2:] == (backend.now, False)
    assert page == {
        "items": [
            {
                "enrollment_ref": "ENROLL_enrollment-public-id",
                "assessment_ref": "ASSESS_synthetic_1",
                "completed_at": completed_at,
                "case_ref": None,
            }
        ],
        "total": 1,
    }
    assert set(page["items"][0]) == {
        "enrollment_ref",
        "assessment_ref",
        "completed_at",
        "case_ref",
    }
    assert uow.committed
