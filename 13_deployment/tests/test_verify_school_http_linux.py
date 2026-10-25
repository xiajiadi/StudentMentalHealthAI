"""Tests for the Linux school HTTP verifier's protected credential handoff."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest
import verify_school_http_linux as verifier


def test_seed_accounts_decrypt_uses_embedded_credential_name(monkeypatch):
    credentials = {
        f"{school}.{role}": [
            f"SYNTHETIC_{school.upper()}_{role.upper()}_TEST",
            f"synthetic-test-password-{school}-{role}",
        ]
        for school in ("alpha", "beta")
        for role in verifier.ROLE_PROJECTION
    }
    expected = {slot: (entry[0], entry[1]) for slot, entry in credentials.items()}
    calls = []

    def fake_run(args, *, timeout=120):
        calls.append((args, timeout))
        payload = {
            "schema": "psynova.school-seed-accounts.v1",
            "credentials": credentials,
        }
        return subprocess.CompletedProcess(args, 0, json.dumps(payload).encode(), b"")

    monkeypatch.setattr(verifier, "_run", fake_run)

    assert verifier._read_accounts() == expected
    assert calls == [
        (
            [
                "systemd-creds",
                "decrypt",
                "--name=school-seed-accounts.json",
                str(verifier.ACCOUNT_CREDENTIAL),
                "-",
            ],
            120,
        )
    ]


def test_seed_account_decrypt_failure_does_not_expose_command_output(monkeypatch):
    sentinel = "SYNTHETIC_SECRET_SENTINEL"

    def fail_run(args, **_kwargs):
        return subprocess.CompletedProcess(args, 1, b"", sentinel.encode())

    monkeypatch.setattr(verifier.subprocess, "run", fail_run)

    with pytest.raises(verifier.SmokeError) as caught:
        verifier._read_accounts()

    assert "required smoke operation failed" == str(caught.value)
    assert sentinel not in str(caught.value)


def test_missing_csrf_header_is_rejected_without_losing_session():
    class Response:
        def __init__(self, status_code):
            self.status_code = status_code

    class Client:
        def __init__(self):
            self.post_calls = []

        def post(self, path, *, json, headers):
            self.post_calls.append((path, json, headers))
            return Response(403)

        def get(self, path):
            assert path == "/api/v1/auth/me"
            return Response(200)

    client = Client()
    verifier._require_csrf_rejection({"slot": "alpha.teacher", "client": client})

    assert len(client.post_calls) == 1
    path, _, headers = client.post_calls[0]
    assert path == "/api/v1/auth/active-context"
    assert "X-CSRF-Token" not in headers


def test_public_https_base_defaults_origin_to_its_origin():
    assert verifier._verification_origin("https://psynova.top") == "https://psynova.top"


def test_loopback_default_keeps_local_frontend_origin():
    assert verifier._verification_origin(verifier.BACKEND) == verifier.DEFAULT_UI_ORIGIN


def test_loopback_backend_can_use_explicit_public_browser_origin():
    assert (
        verifier._verification_origin(
            verifier.BACKEND,
            "https://psynova.top",
        )
        == "https://psynova.top"
    )


@pytest.mark.parametrize(
    "origin", ["https://psynova.top/path", "https://user@psynova.top"]
)
def test_explicit_origin_rejects_non_origin_url_components(origin):
    with pytest.raises(verifier.SmokeError, match="does not match"):
        verifier._verification_origin(verifier.BACKEND, origin)


def test_login_uses_public_https_base_and_origin():
    calls = []

    class Response:
        status_code = 200

        def __init__(self, data):
            self.data = data

        def json(self):
            return {"data": self.data}

    class Client:
        def __init__(self, *, base_url, timeout, trust_env):
            calls.append(("client", base_url, timeout, trust_env))

        def post(self, path, *, json, headers):
            calls.append((path, headers["Origin"]))
            if path.endswith("/login"):
                return Response(
                    {
                        "actor": {"role": "STUDENT", "user_id": "synthetic-user"},
                        "csrf_token": "synthetic-csrf-token",
                    }
                )
            return Response(
                {"active_context": {"school_ref": verifier.EXPECTED_SCHOOL["alpha"]}}
            )

        def close(self):
            pass

    httpx = SimpleNamespace(Client=Client)
    session = verifier._login(
        httpx,
        "alpha.student",
        ("SYNTHETIC_ALPHA_STUDENT_TEST", "synthetic-password"),
        base_url="https://psynova.top",
        origin="https://psynova.top",
    )

    assert session["slot"] == "alpha.student"
    assert calls == [
        ("client", "https://psynova.top", 15, False),
        ("/api/v1/auth/login", "https://psynova.top"),
        ("/api/v1/auth/active-context", "https://psynova.top"),
    ]
