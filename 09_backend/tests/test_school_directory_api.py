from __future__ import annotations

from dataclasses import replace
from typing import get_args

import pytest
from pydantic import SecretStr, ValidationError

from smhai_backend.adapters.database import (
    REQUIRED_DATABASE_REVISION,
    REQUIRED_SCHOOL_TENANT_DATABASE_REVISION,
    MySqlBackendAdapter,
)
from smhai_backend.app_factory import create_app
from smhai_backend.core.config import BackendSettings
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.school_directory.router import _batch_idempotency, _import_responses
from smhai_backend.domains.school_directory.router import router as school_directory_router
from smhai_backend.domains.school_directory.schemas import (
    AccountActivationRequest,
    AccountBatchRequest,
    DirectoryMemberDto,
    DisplayNameRequest,
)
from smhai_backend.domains.school_directory.service import (
    SchoolDirectoryService,
    validate_import_rows,
)


def admin_actor() -> Actor:
    return Actor(
        user_id="USER_synthetic-admin",
        username="synthetic-admin",
        role=BackendRole.ADMIN,
        subject_id=None,
        scope_profile="school_tenant",
        school_id=17,
        school_ref="SCHOOL_synthetic-test",
    )


def batch_payload(**overrides):
    value = {
        "class_ref": "CLASS_synthetic-a",
        "rows": [
            {
                "row_no": 2,
                "login_name": "SYNTHETIC_STUDENT_001",
                "display_name": "演示学生甲",
                "role": "student",
            }
        ],
    }
    value.update(overrides)
    return AccountBatchRequest.model_validate(value)


def test_display_name_is_trimmed_and_bounded():
    assert DisplayNameRequest(display_name="  合成学校  ").display_name == "合成学校"
    with pytest.raises(ValidationError):
        DisplayNameRequest(display_name="  ")
    with pytest.raises(ValidationError):
        DisplayNameRequest(display_name="x" * 121)


def test_module_local_import_documents_both_rejection_forms():
    from smhai_backend.core.api_models import ApiEnvelope
    from smhai_backend.core.errors import ProblemDetails
    from smhai_backend.domains.school_directory.schemas import AccountImportPreviewDto

    assert set(get_args(_import_responses()[409]["model"])) == {
        ApiEnvelope[AccountImportPreviewDto],
        ProblemDetails,
    }
    route = next(
        item for item in school_directory_router.routes if item.path.endswith("/accounts/import")
    )
    assert route.status_code == 201


def test_import_dto_rejects_password_and_unknown_columns():
    payload = batch_payload().model_dump(mode="python")
    payload["rows"][0]["password"] = "synthetic-only-never-accept"
    with pytest.raises(ValidationError):
        AccountBatchRequest.model_validate(payload)

    payload = batch_payload().model_dump(mode="python")
    payload["rows"][0]["extra_column"] = "unsupported"
    with pytest.raises(ValidationError):
        AccountBatchRequest.model_validate(payload)


def test_import_request_bounds_row_count_and_requires_positive_distinct_row_numbers():
    rows = [
        {
            "row_no": index + 1,
            "login_name": f"SYNTHETIC_STUDENT_{index:03}",
            "display_name": f"合成学生{index}",
            "role": "student",
        }
        for index in range(100)
    ]
    assert len(batch_payload(rows=rows).rows) == 100
    with pytest.raises(ValidationError):
        batch_payload(rows=rows + [rows[0]])
    with pytest.raises(ValidationError):
        batch_payload(rows=[{**rows[0], "row_no": 0}])


def test_preview_errors_do_not_echo_login_names_or_display_names():
    payload = batch_payload(
        rows=[
            {
                "row_no": 1,
                "login_name": "invalid-private-value",
                "display_name": "synthetic-name-not-to-echo",
                "role": "student",
            },
            {
                "row_no": 2,
                "login_name": "invalid-private-value",
                "display_name": "synthetic-name-not-to-echo",
                "role": "teacher",
            },
        ]
    )
    errors = validate_import_rows(payload.rows)
    assert errors == [
        {"row_no": 1, "code": "INVALID_LOGIN_NAME"},
        {"row_no": 2, "code": "INVALID_LOGIN_NAME"},
        {"row_no": 2, "code": "DUPLICATE_LOGIN_NAME"},
    ]
    assert "invalid-private-value" not in repr(errors)
    assert "synthetic-name-not-to-echo" not in repr(errors)


def test_import_login_names_are_validated_without_silent_whitespace_normalization():
    payload = batch_payload(
        rows=[
            {
                "row_no": 1,
                "login_name": " SYNTHETIC_STUDENT_001 ",
                "display_name": "合成学生",
                "role": "student",
            }
        ]
    )

    assert payload.rows[0].login_name == " SYNTHETIC_STUDENT_001 "
    assert validate_import_rows(payload.rows) == [{"row_no": 1, "code": "INVALID_LOGIN_NAME"}]


def test_activation_secret_is_masked_and_strength_checked():
    value = "Synthetic-Strong-Password-9"
    request = AccountActivationRequest(new_password=value)
    assert isinstance(request.new_password, SecretStr)
    assert value not in repr(request)
    with pytest.raises(ValidationError):
        AccountActivationRequest(new_password="weakpassword")


def test_directory_dtos_exclude_credential_and_psychological_fields():
    row = {
        "user_id": "USER_synthetic",
        "display_name": "合成学生",
        "role": "student",
        "account_status": "SUSPENDED",
        "provisioning_status": "PENDING_ACTIVATION",
    }
    assert DirectoryMemberDto.model_validate(row).display_name == "合成学生"
    with pytest.raises(ValidationError):
        DirectoryMemberDto.model_validate({**row, "password_hash": "must-not-serialize"})
    with pytest.raises(ValidationError):
        DirectoryMemberDto.model_validate({**row, "subject_id": "SUBJ_private"})


def test_batch_idempotency_fingerprint_is_school_scoped_and_has_no_password_input():
    payload = batch_payload()
    key, request_fingerprint, scope = _batch_idempotency(
        admin_actor(), "synthetic-idempotency-key", payload.model_dump(mode="json")
    )
    assert key == "synthetic-idempotency-key"
    assert len(request_fingerprint) == 64
    assert len(scope) == 64
    assert "new_password" not in payload.model_dump(mode="json")


class FakeRevisionResult:
    def __init__(self, revision):
        self.revision = revision

    def scalars(self):
        return self

    def all(self):
        return [self.revision]


class FakeRevisionConnection:
    def __init__(self, revision):
        self.revision = revision

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def exec_driver_sql(self, _sql):
        return FakeRevisionResult(self.revision)


class FakeRevisionEngine:
    def __init__(self, revision):
        self.revision = revision

    def connect(self):
        return FakeRevisionConnection(self.revision)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("profile", "revision", "accepted"),
    [
        ("legacy_demo", REQUIRED_DATABASE_REVISION, True),
        ("legacy_demo", REQUIRED_SCHOOL_TENANT_DATABASE_REVISION, False),
        ("school_tenant", REQUIRED_SCHOOL_TENANT_DATABASE_REVISION, True),
        ("school_tenant", REQUIRED_DATABASE_REVISION, False),
    ],
)
async def test_database_revision_gate_is_profile_specific(profile, revision, accepted):
    adapter = MySqlBackendAdapter.__new__(MySqlBackendAdapter)
    adapter.identity_profile = profile
    adapter.engine = FakeRevisionEngine(revision)
    if accepted:
        await adapter._require_database_revision()
    else:
        with pytest.raises(RuntimeError):
            await adapter._require_database_revision()


class FakePersistence:
    def __init__(self):
        self.calls = []

    async def school_directory_get(self, actor):
        self.calls.append(("directory", actor.school_id))
        return {"school": {}, "classes": [], "members": []}

    async def school_directory_preview_accounts(self, actor, class_ref, rows):
        self.calls.append(("preview", actor.school_id, class_ref, len(rows)))
        return {"valid": True, "row_count": len(rows), "errors": []}

    async def school_directory_import_accounts(
        self, actor, class_ref, rows, *, idempotency, trace_id
    ):
        self.calls.append(("import", idempotency, trace_id, class_ref, len(rows)))
        return {"batch_ref": "BATCH_synthetic", "created_count": 1, "accounts": []}


@pytest.mark.asyncio
async def test_directory_service_fails_closed_for_non_admin_and_non_tenant_actors():
    persistence = FakePersistence()
    service = SchoolDirectoryService(persistence=persistence)
    for actor in (
        replace(admin_actor(), role=BackendRole.TEACHER),
        replace(admin_actor(), scope_profile="legacy_demo"),
        replace(admin_actor(), school_id=None),
    ):
        with pytest.raises(Exception) as caught:
            await service.get_directory(actor)
        assert getattr(caught.value, "code", None).value == "forbidden"
    assert persistence.calls == []


@pytest.mark.asyncio
async def test_directory_service_passes_scoped_preview_and_import_without_password_fields():
    persistence = FakePersistence()
    service = SchoolDirectoryService(persistence=persistence)
    payload = batch_payload()
    preview = await service.preview_accounts(admin_actor(), payload.class_ref, payload.rows)
    assert preview == {"valid": True, "row_count": 1, "errors": []}
    imported = await service.import_accounts(
        admin_actor(),
        payload.class_ref,
        payload.rows,
        idempotency=("key", "a" * 64, "scope"),
        trace_id="TRACE_synthetic",
    )
    assert imported["batch_ref"] == "BATCH_synthetic"
    assert persistence.calls == [
        ("preview", 17, "CLASS_synthetic-a", 1),
        ("import", ("key", "a" * 64, "scope"), "TRACE_synthetic", "CLASS_synthetic-a", 1),
    ]


def test_school_directory_routes_are_module_local_and_hidden_from_frozen_openapi():
    app = create_app(settings=BackendSettings(environment="test"))
    paths = {route.path for route in school_directory_router.routes}
    assert "/school/admin/directory" in paths
    assert "/school/admin/accounts/preview" in paths
    assert "/school/admin/accounts/import" in paths
    assert "/school/admin/accounts/{user_id}/activate" in paths
    assert "/api/v1/school/admin/directory" not in app.openapi()["paths"]
