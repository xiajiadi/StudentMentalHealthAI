from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from smhai_backend.domains.school_account_lifecycle.schemas import (
    StaffRosterCredentialDto,
    StaffRosterImportRequest,
)


def test_staff_roster_accepts_teacher_class_scope_and_unscoped_specialist():
    payload = StaffRosterImportRequest.model_validate(
        {
            "rows": [
                {
                    "row_no": 1,
                    "employee_ref": "T-001",
                    "display_name": "合成教师",
                    "role": "teacher",
                    "class_refs": ["CLASS_A"],
                },
                {
                    "row_no": 2,
                    "employee_ref": "P-001",
                    "display_name": "合成心理教师",
                    "role": "psychological_specialist",
                    "class_refs": [],
                },
            ]
        }
    )

    assert len(payload.rows) == 2
    assert payload.rows[0].class_refs == ["CLASS_A"]
    assert payload.rows[1].class_refs == []


@pytest.mark.parametrize(
    "row",
    [
        {
            "row_no": 1,
            "employee_ref": "T-001",
            "display_name": "合成教师",
            "role": "teacher",
            "class_refs": [],
        },
        {
            "row_no": 1,
            "employee_ref": "P-001",
            "display_name": "合成心理教师",
            "role": "psychological_specialist",
            "class_refs": ["CLASS_A"],
        },
        {
            "row_no": 1,
            "employee_ref": "心理-001",
            "display_name": "合成心理教师",
            "role": "psychological_specialist",
            "class_refs": [],
        },
    ],
)
def test_staff_roster_rejects_invalid_role_scope_or_non_ascii_employee_ref(row):
    with pytest.raises(ValidationError):
        StaffRosterImportRequest.model_validate({"rows": [row]})


def test_staff_roster_rejects_duplicate_employee_refs_case_insensitively():
    row = {
        "row_no": 1,
        "employee_ref": "T-001",
        "display_name": "合成教师",
        "role": "teacher",
        "class_refs": ["CLASS_A"],
    }
    duplicate = {**row, "row_no": 2, "employee_ref": "t-001"}

    with pytest.raises(ValidationError):
        StaffRosterImportRequest.model_validate({"rows": [row, duplicate]})


def test_staff_roster_credential_serializes_token_but_hides_it_from_repr():
    token = "synthetic-one-time-credential-value-123456"
    dto = StaffRosterCredentialDto(
        invitation_ref="INV_SYNTHETIC",
        user_id="USER_SYNTHETIC",
        login_name="STAFF_SYNTHETIC",
        display_name="合成教职工",
        role="teacher",
        class_refs=["CLASS_A"],
        credential=token,
        expires_at=datetime.fromisoformat("2026-10-25T00:00:00+00:00"),
    )

    assert dto.model_dump(mode="json")["credential"] == token
    assert token not in repr(dto)
