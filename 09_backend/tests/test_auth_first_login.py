from __future__ import annotations

import hashlib

import pytest
from pydantic import SecretStr, ValidationError

from smhai_backend.domains.auth.schemas import CompleteInitialLoginRequest


async def test_first_login_hashes_the_one_time_credential_and_disables_caching(
    app, client, monkeypatch
):
    captured: dict[str, object] = {}

    async def complete(**kwargs):
        captured.update(kwargs)
        return {"status": "PASSWORD_SET"}

    monkeypatch.setattr(
        app.state.container.school_directory,
        "complete_initial_credential",
        complete,
    )
    response = await client.post(
        "/api/v1/auth/first-login",
        json={
            "school_ref": "SCHOOL_SYNTHETIC",
            "username": "STUDENT_SYNTHETIC",
            "credential": "one-time-synthetic-credential-value",
            "new_password": "NewStrongPassword123!",
            "confirm_password": "NewStrongPassword123!",
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.json()["data"]["status"] == "PASSWORD_SET"
    assert captured["token_hash"] == hashlib.sha256(
        b"one-time-synthetic-credential-value"
    ).digest()
    assert "credential" not in captured
    assert captured["new_password"] == "NewStrongPassword123!"


def test_first_login_request_masks_secrets_and_requires_matching_strong_passwords():
    request = CompleteInitialLoginRequest(
        school_ref=" SCHOOL_SYNTHETIC ",
        username=" STUDENT_SYNTHETIC ",
        credential="one-time-synthetic-credential-value",
        new_password="NewStrongPassword123!",
        confirm_password="NewStrongPassword123!",
    )
    assert request.school_ref == "SCHOOL_SYNTHETIC"
    assert request.username == "STUDENT_SYNTHETIC"
    assert isinstance(request.credential, SecretStr)
    assert "one-time-synthetic-credential-value" not in repr(request)
    assert "NewStrongPassword123!" not in repr(request)

    with pytest.raises(ValidationError):
        CompleteInitialLoginRequest(
            school_ref="SCHOOL_SYNTHETIC",
            username="STUDENT_SYNTHETIC",
            credential="one-time-synthetic-credential-value",
            new_password="all-lowercase-password",
            confirm_password="all-lowercase-password",
        )
    with pytest.raises(ValidationError):
        CompleteInitialLoginRequest(
            school_ref="SCHOOL_SYNTHETIC",
            username="STUDENT_SYNTHETIC",
            credential="one-time-synthetic-credential-value",
            new_password="NewStrongPassword123!",
            confirm_password="DifferentStrongPassword123!",
        )
