from __future__ import annotations

import asyncio
import hashlib
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
for _database_path in (
    _REPOSITORY_ROOT / "11_database" / ".venv" / "Lib" / "site-packages",
    _REPOSITORY_ROOT / "11_database",
):
    if _database_path.is_dir() and str(_database_path) not in sys.path:
        sys.path.insert(0, str(_database_path))

from database_layer import enums as db_enums  # noqa: E402
from database_layer import models as db_models  # noqa: E402
from sqlalchemy import create_engine, event, select  # noqa: E402
from sqlalchemy.dialects import mysql  # noqa: E402
from sqlalchemy.dialects.mysql import MEDIUMBLOB  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from smhai_backend.adapters.database import MySqlBackendAdapter  # noqa: E402
from smhai_backend.adapters.school_directory import SchoolDirectoryPersistenceAdapter  # noqa: E402
from smhai_backend.core.errors import BackendError, ErrorCode  # noqa: E402
from smhai_backend.domains.models import Actor, BackendRole, SchoolRoleContext  # noqa: E402
from smhai_backend.domains.school_directory.router import router  # noqa: E402
from smhai_backend.domains.school_directory.schemas import (  # noqa: E402
    SchoolRosterImportRequest,
)
from smhai_backend.domains.school_directory.service import (  # noqa: E402
    SchoolDirectoryService,
    roster_login_name,
    validate_roster_rows,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_school_research_live_scope import _AsyncSessionFacade  # noqa: E402

NOW = datetime(2026, 10, 24, 9, 30)


def _payload(rows: list[dict[str, object]], **extra) -> SchoolRosterImportRequest:
    return SchoolRosterImportRequest.model_validate({"rows": rows, **extra})


def _row(row_no: int, student_number: str, class_ref: str, **extra) -> dict[str, object]:
    return {
        "row_no": row_no,
        "student_number": student_number,
        "display_name": f"合成学生{row_no}",
        "class_ref": class_ref,
        **extra,
    }


def _actor() -> Actor:
    return Actor(
        user_id="USER_admin-public-a",
        username="synthetic-admin",
        role=BackendRole.ADMIN,
        subject_id=None,
        scope_profile="school_tenant",
        school_id=101,
        school_ref="SCHOOL_A",
        school_contexts=(
            SchoolRoleContext(
                context_id="302",
                role=BackendRole.ADMIN,
                school_id=101,
                school_ref="SCHOOL_A",
            ),
        ),
    )


class _Repo:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def add_role(self, **values):
        record = db_models.MembershipRole(**values)
        self.session.add(record)
        self.session.flush()
        return record

    async def create(self, **values):
        record = db_models.Subject(**values)
        self.session.add(record)
        self.session.flush()
        return record


class _SchoolOperations:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def add_student_subject_to_class(
        self, *, school_id: int, class_id: int, subject_id: int,
        admin_membership_role_id: int, at,
    ):
        del admin_membership_role_id
        record = db_models.SchoolClassStudent(
            public_id=f"roster-link-{school_id}-{class_id}-{subject_id}",
            school_id=school_id,
            class_id=class_id,
            subject_id=subject_id,
            status="ACTIVE",
            valid_from=at,
        )
        self.session.add(record)
        self.session.flush()
        return record

    async def add_teacher_role_to_class(
        self, *, school_id: int, class_id: int, teacher_membership_role_id: int,
        admin_membership_role_id: int, at,
    ):
        del admin_membership_role_id
        record = db_models.SchoolClassTeacher(
            public_id=f"teacher-link-{school_id}-{class_id}-{teacher_membership_role_id}",
            school_id=school_id,
            class_id=class_id,
            membership_role_id=teacher_membership_role_id,
            status="ACTIVE",
            valid_from=at,
        )
        self.session.add(record)
        self.session.flush()
        return record

class _Transaction:
    def __init__(self, session: Session):
        self.session = _AsyncSessionFacade(session)
        self._sync_session = session
        self.memberships = _Repo(session)
        self.subjects = _Repo(session)
        self.school_operations = _SchoolOperations(session)

    async def __aenter__(self):
        if not self._sync_session.in_transaction():
            self._sync_session.begin()
        return self

    async def __aexit__(self, exc_type, _exc, _traceback):
        if exc_type is None:
            self._sync_session.commit()
        else:
            self._sync_session.rollback()


class _FastPasswordHash:
    def hash(self, value: str) -> str:
        return "test-hash-" + hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture
def roster_scope(monkeypatch):
    original_dispatch = MEDIUMBLOB._compiler_dispatch
    bigint_cls = type(mysql.BIGINT(unsigned=True))
    original_bigint_dispatch = bigint_cls._compiler_dispatch

    def local_dispatch(value, compiler, **kwargs):
        if compiler.dialect.name == "sqlite":
            return "BLOB"
        return original_dispatch(value, compiler, **kwargs)

    monkeypatch.setattr(MEDIUMBLOB, "_compiler_dispatch", local_dispatch)
    monkeypatch.setattr(
        bigint_cls,
        "_compiler_dispatch",
        lambda value, compiler, **kwargs: (
            "INTEGER"
            if compiler.dialect.name == "sqlite"
            else original_bigint_dispatch(value, compiler, **kwargs)
        ),
    )
    from pwdlib import PasswordHash

    monkeypatch.setattr(PasswordHash, "recommended", staticmethod(_FastPasswordHash))
    engine = create_engine("sqlite:///:memory:")
    event.listen(
        engine,
        "connect",
        lambda connection, _record: connection.create_collation(
            "ascii_bin", lambda left, right: (left > right) - (left < right)
        ),
    )
    selected = {
        "accounts",
        "schools",
        "account_school_memberships",
        "membership_roles",
        "school_classes",
        "school_account_batches",
        "school_account_provisions",
        "school_roster_import_runs",
        "school_roster_import_run_batches",
        "school_account_credentials",
        "subjects",
        "subject_access_grants",
        "idempotency_records",
        "school_class_students",
        "school_class_teachers",
        "auth_sessions",
        "school_staff_invitations",
        "school_staff_invitation_classes",
        "school_password_recovery_tickets",
    }
    db_models.Base.metadata.create_all(
        engine,
        tables=[db_models.Base.metadata.tables[name] for name in selected],
    )
    session = Session(engine, expire_on_commit=False)
    session.add_all(
        [
            db_models.School(
                id=101,
                public_id="school-public-a",
                school_ref="SCHOOL_A",
                display_name="Synthetic School A",
                status="ACTIVE",
                data_origin="SYNTHETIC",
                provenance_ref="SYNTHETIC_REF_AUTH_TENANT_FIXTURE_V1",
            ),
            db_models.Account(
                id=201,
                public_id="admin-public-a",
                login_name="synthetic-admin",
                password_hash="test-admin-hash",
                status="ACTIVE",
            ),
            db_models.AccountSchoolMembership(
                id=301,
                public_id="membership-admin-a",
                account_id=201,
                school_id=101,
                status="ACTIVE",
                valid_from=NOW - timedelta(days=1),
            ),
            db_models.MembershipRole(
                id=302,
                public_id="role-admin-a",
                membership_id=301,
                school_id=101,
                role_code="admin",
                status="ACTIVE",
                valid_from=NOW - timedelta(days=1),
            ),
            db_models.SchoolClass(
                id=401,
                public_id="class-a-public",
                school_id=101,
                class_ref="CLASS_A",
                display_name="甲班",
                grade_level="G7",
                created_by_membership_role_id=302,
                status="ACTIVE",
            ),
            db_models.SchoolClass(
                id=402,
                public_id="class-b-public",
                school_id=101,
                class_ref="CLASS_B",
                display_name="乙班",
                grade_level=None,
                created_by_membership_role_id=302,
                status="ACTIVE",
            ),
            db_models.SchoolClass(
                id=403,
                public_id="class-inactive-public",
                school_id=101,
                class_ref="CLASS_INACTIVE",
                display_name="停用班",
                created_by_membership_role_id=302,
                status="ARCHIVED",
            ),
        ]
    )
    session.commit()

    owner = object.__new__(MySqlBackendAdapter)
    owner.identity_profile = "school_tenant"
    owner._db_models = db_models
    owner._db_enums = db_enums
    owner._select = select
    owner._integrity_error = IntegrityError
    owner._utc_now = lambda: NOW
    owner._uow = lambda: _Transaction(session)
    owner._school_actor_role = MySqlBackendAdapter._school_actor_role.__get__(owner)
    owner._school_idempotency_begin = MySqlBackendAdapter._school_idempotency_begin.__get__(
        owner
    )
    owner._school_idempotency_complete = MySqlBackendAdapter._school_idempotency_complete.__get__(
        owner
    )
    owner._user_from_account = MySqlBackendAdapter._user_from_account.__get__(owner)
    adapter = SchoolDirectoryPersistenceAdapter(owner)

    async def no_audit(*_args, **_kwargs):
        return None

    adapter._school_directory_audit = no_audit
    yield SimpleNamespace(engine=engine, session=session, adapter=adapter, actor=_actor())
    session.close()
    engine.dispose()


def _idempotency(actor: Actor, key: str, payload: SchoolRosterImportRequest):
    from smhai_backend.core.idempotency import fingerprint

    scope = fingerprint(
        {
            "actor": actor.user_id,
            "school_id": actor.school_id,
            "school_ref": actor.school_ref,
            "role": actor.role.value,
            "operation": "school_directory:roster_import",
        }
    )
    return key, fingerprint(payload.model_dump(mode="json")), scope


async def _import_one_student(scope):
    service = SchoolDirectoryService(persistence=scope.adapter)
    payload = _payload([_row(1, "CREDENTIAL-STUDENT", "CLASS_A")])
    imported = await service.import_roster(
        scope.actor,
        payload.rows,
        source_sha256=None,
        idempotency=_idempotency(scope.actor, "credential-roster-key", payload),
        trace_id="TRACE_CREDENTIAL_IMPORT",
    )
    return service, imported["accounts"][0]


async def _issue_one_credential(service, scope, user_id: str, *, ttl_seconds: int = 3600):
    result = await service.issue_initial_credentials(
        scope.actor,
        [user_id],
        ttl_seconds=ttl_seconds,
        trace_id="TRACE_CREDENTIAL_ISSUE",
    )
    return result["credentials"][0]


def test_roster_request_is_strict_bounded_and_normalizes_student_numbers():
    payload = _payload([_row(1, "  ００１-ab ", "CLASS_A")])
    assert payload.rows[0].student_number == "001-AB"
    with pytest.raises(ValueError):
        _payload([_row(1, "STUDENT-1", "CLASS_A", password="not accepted")])
    with pytest.raises(ValueError):
        _payload([_row(index + 1, f"N{index}", "CLASS_A") for index in range(201)])


def test_roster_endpoints_are_registered_on_the_module_local_router():
    routes = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}
    assert ("/school/admin/roster/preview", ("POST",)) in routes
    assert ("/school/admin/roster/import", ("POST",)) in routes
    assert ("/school/admin/roster/imports/{run_ref}", ("GET",)) in routes


def test_roster_login_name_is_stable_school_scoped_and_does_not_contain_student_number():
    value = roster_login_name("SCHOOL_A", "STUDENT-001")
    assert value == roster_login_name("SCHOOL_A", "STUDENT-001")
    assert value != roster_login_name("SCHOOL_B", "STUDENT-001")
    assert value.startswith("SYNTHETIC_ROSTER_SCHOOL_A_")
    assert "STUDENT-001" not in value
    assert len(value) <= 112


def test_row_validation_reports_duplicate_numbers_without_echoing_private_values():
    payload = _payload(
        [
            _row(1, "DUP-001", "CLASS_A"),
            _row(1, "DUP-001", "CLASS_B"),
        ]
    )
    errors = validate_roster_rows("SCHOOL_A", payload.rows)
    assert {item["code"] for item in errors} == {
        "DUPLICATE_ROW_NUMBER",
        "DUPLICATE_STUDENT_NUMBER",
    }
    assert "DUP-001" not in repr(errors)


def test_roster_rejects_formula_like_display_names():
    payload = _payload([_row(1, "STUDENT-1", "CLASS_A", display_name="=HYPERLINK(\"x\")")])
    errors = validate_roster_rows("SCHOOL_A", payload.rows)
    assert errors == [{"row_no": 1, "code": "FORMULA_LIKE_VALUE"}]
    assert "HYPERLINK" not in repr(errors)


@pytest.mark.asyncio
async def test_directory_reports_pending_students_class_scope_for_credential_filter(roster_scope):
    service, imported = await _import_one_student(roster_scope)
    directory = await service.get_directory(roster_scope.actor)
    member = next(item for item in directory["members"] if item["user_id"] == imported["user_id"])
    assert member["provisioning_status"] == "PENDING_ACTIVATION"
    assert member["class_refs"] == ["CLASS_A"]


@pytest.mark.asyncio
async def test_preview_handles_200_rows_across_classes_and_reports_unknown_or_grade_mismatch(
    roster_scope,
):
    service = SchoolDirectoryService(persistence=roster_scope.adapter)
    rows = [
        _row(index + 1, f"STU-{index + 1:03}", "CLASS_A" if index < 120 else "CLASS_B")
        for index in range(200)
    ]
    payload = _payload(rows)
    preview = await service.preview_roster_import(roster_scope.actor, payload.rows)
    assert preview == {
        "valid": True,
        "row_count": 200,
        "errors": [],
        "class_groups": [
            {"class_ref": "CLASS_A", "row_count": 120},
            {"class_ref": "CLASS_B", "row_count": 80},
        ],
    }

    invalid = _payload(
        [
            _row(1, "STU-UNKNOWN", "CLASS_UNKNOWN"),
            _row(2, "STU-GRADE", "CLASS_A", grade_level="G8"),
            _row(3, "STU-INACTIVE", "CLASS_INACTIVE"),
        ]
    )
    result = await service.preview_roster_import(roster_scope.actor, invalid.rows)
    assert {item["row_no"]: item["code"] for item in result["errors"]} == {
        1: "CLASS_UNAVAILABLE",
        2: "GRADE_LEVEL_MISMATCH",
        3: "CLASS_UNAVAILABLE",
    }
    assert result["class_groups"] == [
        {"class_ref": "CLASS_A", "row_count": 1},
        {"class_ref": "CLASS_INACTIVE", "row_count": 1},
        {"class_ref": "CLASS_UNKNOWN", "row_count": 1},
    ]
    assert "STU-" not in repr(result)


@pytest.mark.asyncio
async def test_import_replays_one_parent_run_and_conflicts_on_changed_payload(roster_scope):
    service = SchoolDirectoryService(persistence=roster_scope.adapter)
    rows = [
        _row(index + 1, f"STU-{index + 1:03}", "CLASS_A" if index < 120 else "CLASS_B")
        for index in range(200)
    ]
    payload = _payload(rows, source_sha256="a" * 64)
    idem = _idempotency(roster_scope.actor, "roster-test-key", payload)
    first = await service.import_roster(
        roster_scope.actor,
        payload.rows,
        source_sha256=payload.source_sha256,
        idempotency=idem,
        trace_id="TRACE_TEST_ROSTER",
    )
    replay = await service.import_roster(
        roster_scope.actor,
        payload.rows,
        source_sha256=payload.source_sha256,
        idempotency=idem,
        trace_id="TRACE_TEST_ROSTER_REPLAY",
    )
    assert first["run_ref"] == replay["run_ref"]
    assert first["child_batch_refs"] == replay["child_batch_refs"]
    assert first["summary"] == {"class_count": 2, "batch_count": 3, "student_count": 200}
    assert first["created_count"] == 200
    assert first["skipped_count"] == 0
    assert first["class_groups"] == [
        {"class_ref": "CLASS_A", "row_count": 120},
        {"class_ref": "CLASS_B", "row_count": 80},
    ]
    assert len(first["accounts"]) == 200
    assert len(first["child_batch_refs"]) == 3
    assert sum(item["class_ref"] == "CLASS_A" for item in first["accounts"]) == 120
    assert sum(item["class_ref"] == "CLASS_B" for item in first["accounts"]) == 80
    retrieved = await service.get_roster_import(roster_scope.actor, first["run_ref"])
    assert retrieved["run_ref"] == first["run_ref"]
    assert retrieved["child_batch_refs"] == first["child_batch_refs"]
    assert retrieved["skipped_count"] == 0
    batch_rows = list(
        roster_scope.session.scalars(
            select(db_models.SchoolAccountBatch.row_count).order_by(db_models.SchoolAccountBatch.id)
        ).all()
    )
    assert sorted(batch_rows) == [20, 80, 100]
    persisted_names = list(
        roster_scope.session.scalars(
            select(db_models.Account.login_name).where(
                db_models.Account.login_name.like("SYNTHETIC_ROSTER_%")
            )
        ).all()
    )
    assert len(persisted_names) == 200
    assert all("STU-" not in login_name for login_name in persisted_names)
    assert roster_scope.session.query(db_models.SchoolRosterImportRun).count() == 1
    assert roster_scope.session.query(db_models.SchoolAccountProvision).count() == 200

    changed = _payload([_row(1, "STU-CHANGED", "CLASS_A")])
    different_idem = _idempotency(roster_scope.actor, "roster-test-key", changed)
    with pytest.raises(BackendError) as conflict:
        await service.import_roster(
            roster_scope.actor,
            changed.rows,
            source_sha256=None,
            idempotency=different_idem,
            trace_id="TRACE_TEST_CONFLICT",
        )
    assert conflict.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert "STU-CHANGED" not in str(conflict.value)


@pytest.mark.asyncio
async def test_import_preflight_conflict_and_audit_failure_leave_no_partial_rows(roster_scope):
    service = SchoolDirectoryService(persistence=roster_scope.adapter)
    existing_login = roster_login_name("SCHOOL_A", "STU-TAKEN")
    roster_scope.session.add(
        db_models.Account(
            public_id="existing-student-public",
            login_name=existing_login,
            password_hash="test-hash",
            status="SUSPENDED",
        )
    )
    roster_scope.session.commit()
    conflict_payload = _payload([_row(1, "STU-TAKEN", "CLASS_A")])
    conflict_preview = await service.preview_roster_import(
        roster_scope.actor, conflict_payload.rows
    )
    assert conflict_preview["errors"] == [
        {"row_no": 1, "code": "STUDENT_NUMBER_UNAVAILABLE"}
    ]

    async def fail_audit(*_args, **_kwargs):
        raise RuntimeError("injected fixed audit failure")

    roster_scope.adapter._school_directory_audit = fail_audit
    rollback_rows = [
        _row(index + 1, f"STU-ROLLBACK-{index}", "CLASS_A" if index % 2 else "CLASS_B")
        for index in range(4)
    ]
    payload = _payload(rollback_rows)
    with pytest.raises(RuntimeError, match="injected fixed audit failure"):
        await service.import_roster(
            roster_scope.actor,
            payload.rows,
            source_sha256=None,
            idempotency=_idempotency(roster_scope.actor, "rollback-key", payload),
            trace_id="TRACE_TEST_ROLLBACK",
        )
    assert roster_scope.session.query(db_models.SchoolAccountBatch).count() == 0
    assert roster_scope.session.query(db_models.SchoolRosterImportRun).count() == 0
    assert roster_scope.session.query(db_models.SchoolRosterImportRunBatch).count() == 0
    assert roster_scope.session.query(db_models.SchoolAccountProvision).count() == 0
    assert roster_scope.session.query(db_models.SubjectAccessGrant).count() == 0
    assert roster_scope.session.query(db_models.IdempotencyRecord).count() == 0
    assert roster_scope.session.query(db_models.Account).filter(
        db_models.Account.login_name.like("SYNTHETIC_ROSTER_%"),
        db_models.Account.login_name != existing_login,
    ).count() == 0


@pytest.mark.asyncio
async def test_credential_issue_activates_provision_blocks_login_then_first_login_consumes_token(
    roster_scope,
):
    service, imported = await _import_one_student(roster_scope)
    account = roster_scope.session.scalar(
        select(db_models.Account).where(
            db_models.Account.public_id == imported["user_id"].removeprefix("USER_")
        )
    )
    original_password_hash = account.password_hash
    issued = await _issue_one_credential(service, roster_scope, imported["user_id"])

    assert issued["user_id"] == imported["user_id"]
    assert issued["login_name"] == account.login_name
    assert issued["class_ref"] == "CLASS_A"
    assert issued["credential"]
    assert issued["expires_at"] == NOW + timedelta(seconds=3600)
    assert account.status == "ACTIVE"
    assert account.must_change_password is True
    assert account.password_changed_at is None
    assert account.password_hash == original_password_hash
    provision = roster_scope.session.query(db_models.SchoolAccountProvision).one()
    assert provision.status == "ACTIVE"
    assert provision.activated_at == NOW
    assert roster_scope.session.query(db_models.SchoolClassStudent).count() == 1

    token_hash = hashlib.sha256(issued["credential"].encode()).digest()
    credential = roster_scope.session.query(db_models.SchoolAccountCredential).one()
    assert credential.token_hash == token_hash
    assert issued["credential"] not in repr(credential.__dict__)

    async with _Transaction(roster_scope.session) as uow:
        account = roster_scope.session.scalar(
            select(db_models.Account).where(db_models.Account.id == account.id)
        )
        assert await roster_scope.adapter._persistence._user_from_account(uow, account) is None

    roster_scope.session.add(
        db_models.AuthSession(
            public_id="credential-session-public",
            account_id=account.id,
            session_token_hash=b"s" * 32,
            idle_expires_at=NOW + timedelta(hours=1),
            absolute_expires_at=NOW + timedelta(hours=8),
        )
    )
    roster_scope.session.commit()
    result = await service.complete_initial_credential(
        issued["login_name"],
        "SCHOOL_A",
        token_hash,
        "New-Synthetic-Password-4",
        "TRACE_FIRST_LOGIN",
    )
    assert result == {"status": "PASSWORD_SET"}
    assert account.status == "ACTIVE"
    assert account.must_change_password is False
    assert account.password_changed_at == NOW
    assert account.password_hash != original_password_hash
    assert credential.status == "CONSUMED"
    assert credential.consumed_at == NOW
    session = roster_scope.session.query(db_models.AuthSession).one()
    assert session.revoked_at == NOW
    assert session.revocation_reason == "INITIAL_CREDENTIAL_COMPLETED"

    with pytest.raises(BackendError) as replay:
        await service.complete_initial_credential(
            issued["login_name"],
            "SCHOOL_A",
            token_hash,
            "Another-Synthetic-Password-5",
            "TRACE_FIRST_LOGIN_REPLAY",
        )
    assert replay.value.code is ErrorCode.AUTH_INVALID_CREDENTIALS
    assert replay.value.detail == "initial credential is invalid or expired"


@pytest.mark.asyncio
async def test_active_uninitialized_synthetic_import_can_receive_credential(
    roster_scope,
):
    service, imported = await _import_one_student(roster_scope)
    account = roster_scope.session.scalar(
        select(db_models.Account).where(
            db_models.Account.public_id == imported["user_id"].removeprefix("USER_")
        )
    )
    provision = roster_scope.session.query(db_models.SchoolAccountProvision).one()
    account.status = "ACTIVE"
    account.must_change_password = False
    account.password_changed_at = None
    original_hash = account.password_hash
    provision.status = "ACTIVE"
    provision.activated_at = NOW
    session = db_models.AuthSession(
        public_id="uninitialized-import-session",
        account_id=account.id,
        session_token_hash=b"u" * 32,
        idle_expires_at=NOW + timedelta(hours=1),
        absolute_expires_at=NOW + timedelta(hours=8),
    )
    roster_scope.session.add(session)
    roster_scope.session.commit()

    issued = await _issue_one_credential(service, roster_scope, imported["user_id"])

    assert issued["login_name"] == account.login_name
    assert issued["credential"]
    assert account.status == "ACTIVE"
    assert account.must_change_password is True
    assert account.password_changed_at is None
    assert account.password_hash == original_hash
    assert provision.status == "ACTIVE"
    assert session.revoked_at == NOW
    assert session.revocation_reason == "INITIAL_CREDENTIAL_ISSUED"
    credential = roster_scope.session.query(db_models.SchoolAccountCredential).one()
    assert credential.purpose == "INITIAL_ACTIVATION"
    assert credential.status == "ISSUED"
    assert issued["credential"] not in repr(credential.__dict__)
    result = await service.complete_initial_credential(
        issued["login_name"],
        "SCHOOL_A",
        hashlib.sha256(issued["credential"].encode()).digest(),
        "New-Synthetic-Password-4",
        "TRACE_RECOVERED_FIRST_LOGIN",
    )
    assert result == {"status": "PASSWORD_SET"}
    assert account.must_change_password is False
    assert account.password_changed_at == NOW
    assert account.password_hash != original_hash
    assert credential.status == "CONSUMED"


@pytest.mark.asyncio
async def test_initial_credential_recovery_rejects_non_synthetic_or_previously_issued_accounts(
    roster_scope,
):
    service, imported = await _import_one_student(roster_scope)
    account = roster_scope.session.scalar(
        select(db_models.Account).where(
            db_models.Account.public_id == imported["user_id"].removeprefix("USER_")
        )
    )
    provision = roster_scope.session.query(db_models.SchoolAccountProvision).one()
    account.status = "ACTIVE"
    account.must_change_password = False
    account.password_changed_at = None
    provision.status = "ACTIVE"
    provision.activated_at = NOW
    roster_scope.session.commit()

    school = roster_scope.session.scalar(
        select(db_models.School).where(db_models.School.school_ref == "SCHOOL_A")
    )
    school.data_origin = "PRODUCTION_PENDING"
    roster_scope.session.commit()
    with pytest.raises(BackendError) as non_synthetic:
        await _issue_one_credential(service, roster_scope, imported["user_id"])
    assert non_synthetic.value.code is ErrorCode.FORBIDDEN

    school.data_origin = "SYNTHETIC"
    roster_scope.session.commit()
    first = await _issue_one_credential(service, roster_scope, imported["user_id"])
    credential = roster_scope.session.query(db_models.SchoolAccountCredential).one()
    assert first["credential"]
    account.must_change_password = False
    account.password_changed_at = None
    roster_scope.session.commit()
    with pytest.raises(BackendError) as previously_issued:
        await _issue_one_credential(service, roster_scope, imported["user_id"])
    assert previously_issued.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert credential.status == "ISSUED"


@pytest.mark.asyncio
async def test_credential_resigning_revokes_old_token_and_legacy_activation_is_disabled(
    roster_scope,
):
    service, imported = await _import_one_student(roster_scope)
    account = roster_scope.session.scalar(
        select(db_models.Account).where(
            db_models.Account.public_id == imported["user_id"].removeprefix("USER_")
        )
    )
    original_password_hash = account.password_hash
    first = await _issue_one_credential(service, roster_scope, imported["user_id"])
    second = await _issue_one_credential(service, roster_scope, imported["user_id"])
    assert first["credential"] != second["credential"]
    records = roster_scope.session.query(db_models.SchoolAccountCredential).order_by(
        db_models.SchoolAccountCredential.id
    ).all()
    assert [record.status for record in records] == ["REVOKED", "ISSUED"]
    assert all(first["credential"] not in repr(record.__dict__) for record in records)

    with pytest.raises(BackendError) as old_token:
        await service.complete_initial_credential(
            first["login_name"],
            "SCHOOL_A",
            hashlib.sha256(first["credential"].encode()).digest(),
            "Old-Synthetic-Password-4",
            "TRACE_OLD_CREDENTIAL",
        )
    assert old_token.value.code is ErrorCode.AUTH_INVALID_CREDENTIALS

    with pytest.raises(BackendError) as activate:
        await service.activate_account(
            roster_scope.actor,
            imported["user_id"],
            "Direct-Admin-Password-4",
            trace_id="TRACE_LEGACY_ACTIVATE",
        )
    assert activate.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert account.password_hash == original_password_hash


@pytest.mark.asyncio
async def test_first_login_expired_and_cross_school_fail_with_same_generic_401(roster_scope):
    service, imported = await _import_one_student(roster_scope)
    issued = await _issue_one_credential(service, roster_scope, imported["user_id"])
    token_hash = hashlib.sha256(issued["credential"].encode()).digest()
    credential = roster_scope.session.query(db_models.SchoolAccountCredential).one()
    credential.expires_at = NOW - timedelta(seconds=1)
    roster_scope.session.commit()

    with pytest.raises(BackendError) as expired:
        await service.complete_initial_credential(
            issued["login_name"],
            "SCHOOL_A",
            token_hash,
            "Expired-Synthetic-Password-4",
            "TRACE_EXPIRED_CREDENTIAL",
        )
    with pytest.raises(BackendError) as cross_school:
        await service.complete_initial_credential(
            issued["login_name"],
            "SCHOOL_OTHER",
            token_hash,
            "Cross-School-Password-4",
            "TRACE_CROSS_SCHOOL_CREDENTIAL",
        )
    assert expired.value.code is ErrorCode.AUTH_INVALID_CREDENTIALS
    assert cross_school.value.code is ErrorCode.AUTH_INVALID_CREDENTIALS
    assert expired.value.detail == cross_school.value.detail
    assert expired.value.detail == "initial credential is invalid or expired"
    assert credential.status == "ISSUED"


@pytest.mark.asyncio
async def test_concurrent_first_login_replay_consumes_credential_at_most_once(roster_scope):
    service, imported = await _import_one_student(roster_scope)
    issued = await _issue_one_credential(service, roster_scope, imported["user_id"])
    token_hash = hashlib.sha256(issued["credential"].encode()).digest()

    async def complete(trace_id: str):
        try:
            return await service.complete_initial_credential(
                issued["login_name"],
                "SCHOOL_A",
                token_hash,
                "Concurrent-Synthetic-Password-4",
                trace_id,
            )
        except BackendError as exc:
            return exc.code

    outcomes = await asyncio.gather(complete("TRACE_CONCURRENT_A"), complete("TRACE_CONCURRENT_B"))
    assert outcomes.count({"status": "PASSWORD_SET"}) == 1
    assert outcomes.count(ErrorCode.AUTH_INVALID_CREDENTIALS) == 1
    assert roster_scope.session.query(db_models.SchoolAccountCredential).one().status == "CONSUMED"
