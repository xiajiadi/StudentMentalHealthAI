"""Run loopback HTTP role-isolation and session-persistence smoke checks."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

BACKEND = "http://127.0.0.1:8088"
DEFAULT_UI_ORIGIN = "http://127.0.0.1:4178"
ACCOUNT_CREDENTIAL = Path("/etc/credstore.encrypted/psynova-school-seed-accounts.cred")
SEED_CREDENTIAL_NAME = "school-seed-accounts.json"
EXPECTED_SCHOOL = {
    "alpha": "SYNTHETIC_SCHOOL_SEED_ALPHA_V1",
    "beta": "SYNTHETIC_SCHOOL_SEED_BETA_V1",
}
ROLE_PROJECTION = {
    "student": ("STUDENT", "STUDENT"),
    "teacher": ("TEACHER", "TEACHER"),
    "psychological_specialist": (
        "PSYCHOLOGICAL_SPECIALIST",
        "PSYCHOLOGICAL_SPECIALIST",
    ),
    "admin": ("ADMIN", "ADMIN"),
}


class SmokeError(RuntimeError):
    pass


def _run(args: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise SmokeError("required smoke operation could not be executed") from None
    if result.returncode != 0:
        raise SmokeError("required smoke operation failed")
    return result


def _read_accounts() -> dict[str, tuple[str, str]]:
    result = _run(
        [
            "systemd-creds",
            "decrypt",
            f"--name={SEED_CREDENTIAL_NAME}",
            str(ACCOUNT_CREDENTIAL),
            "-",
        ]
    )
    try:
        payload = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise SmokeError("synthetic account credential is unavailable") from None
    expected_slots = {
        f"{school}.{role}" for school in ("alpha", "beta") for role in ROLE_PROJECTION
    }
    if (
        type(payload) is not dict
        or set(payload) != {"schema", "credentials"}
        or payload.get("schema") != "psynova.school-seed-accounts.v1"
        or type(payload.get("credentials")) is not dict
        or set(payload["credentials"]) != expected_slots
    ):
        raise SmokeError("synthetic account credential is invalid")
    accounts: dict[str, tuple[str, str]] = {}
    for slot, entry in payload["credentials"].items():
        if (
            type(entry) is not list
            or len(entry) != 2
            or not isinstance(entry[0], str)
            or not entry[0].startswith("SYNTHETIC_")
            or not isinstance(entry[1], str)
            or len(entry[1]) < 16
        ):
            raise SmokeError("synthetic account credential is invalid")
        accounts[slot] = (entry[0], entry[1])
    return accounts


def _data(response) -> dict[str, Any]:
    try:
        value = response.json()
        data = value["data"]
    except (KeyError, TypeError, ValueError):
        raise SmokeError(
            "HTTP response did not match the expected API envelope"
        ) from None
    if not isinstance(data, dict):
        raise SmokeError("HTTP response did not match the expected API envelope")
    return data


def _login(
    httpx,
    slot: str,
    account: tuple[str, str],
    *,
    base_url: str = BACKEND,
    origin: str = DEFAULT_UI_ORIGIN,
):
    client = httpx.Client(base_url=base_url, timeout=15, trust_env=False)
    response = client.post(
        "/api/v1/auth/login",
        json={"username": account[0], "password": account[1]},
        headers={"Origin": origin, "Accept": "application/json"},
    )
    if response.status_code != 200:
        client.close()
        raise SmokeError(f"synthetic account login failed: {slot}")
    data = _data(response)
    actor = data.get("actor")
    csrf = data.get("csrf_token")
    school, role = slot.split(".", 1)
    expected_actor_role, context_role = ROLE_PROJECTION[role]
    if (
        not isinstance(actor, dict)
        or actor.get("role") != expected_actor_role
        or not isinstance(actor.get("user_id"), str)
        or not isinstance(csrf, str)
        or not csrf
    ):
        client.close()
        raise SmokeError(f"synthetic account role projection failed: {slot}")
    selected = client.post(
        "/api/v1/auth/active-context",
        json={"role": context_role, "school_ref": EXPECTED_SCHOOL[school]},
        headers={
            "Origin": origin,
            "X-CSRF-Token": csrf,
            "Accept": "application/json",
        },
    )
    if selected.status_code != 200:
        client.close()
        raise SmokeError(f"synthetic school context selection failed: {slot}")
    actor = _data(selected)
    if actor.get("active_context", {}).get("school_ref") != EXPECTED_SCHOOL[school]:
        client.close()
        raise SmokeError(f"synthetic school context verification failed: {slot}")
    return {"client": client, "actor": actor, "csrf": csrf, "slot": slot}


def _require_csrf_rejection(session, *, origin: str = DEFAULT_UI_ORIGIN) -> None:
    school, role = session["slot"].split(".", 1)
    _, context_role = ROLE_PROJECTION[role]
    response = session["client"].post(
        "/api/v1/auth/active-context",
        json={"role": context_role, "school_ref": EXPECTED_SCHOOL[school]},
        headers={
            "Origin": origin,
            "Accept": "application/json",
        },
    )
    if response.status_code != 403:
        raise SmokeError(f"CSRF authorization check failed: {session['slot']}")
    me = session["client"].get("/api/v1/auth/me")
    if me.status_code != 200:
        raise SmokeError(f"session failed after CSRF denial: {session['slot']}")


def _require_status(session, method: str, path: str, expected: int, label: str) -> None:
    response = getattr(session["client"], method)(
        path, headers={"Accept": "application/json"}
    )
    if response.status_code != expected:
        raise SmokeError(f"HTTP authorization check failed: {label}")


def _restart_backend() -> None:
    _run(["systemctl", "restart", "psynova-school-demo.service"], timeout=180)
    import httpx

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{BACKEND}/health/live", timeout=2, trust_env=False)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(1)
    raise SmokeError("Backend did not recover after the persistence restart")


def _verification_origin(base_url: str, origin: str | None = None) -> str:
    try:
        base = urlsplit(base_url)
        if (
            base.scheme not in {"http", "https"}
            or not base.hostname
            or base.username is not None
            or base.password is not None
            or base.path not in {"", "/"}
            or base.query
            or base.fragment
        ):
            raise ValueError
        base_port = base.port
    except ValueError:
        raise SmokeError("verification base URL is invalid") from None

    if origin is None:
        if base_url.rstrip("/") == BACKEND:
            return DEFAULT_UI_ORIGIN
        return f"{base.scheme}://{base.netloc}"

    try:
        supplied = urlsplit(origin)
        if (
            supplied.scheme not in {"http", "https"}
            or not supplied.hostname
            or supplied.username is not None
            or supplied.password is not None
            or supplied.path not in {"", "/"}
            or supplied.query
            or supplied.fragment
            or (supplied.scheme, supplied.hostname, supplied.port)
            != (base.scheme, base.hostname, base_port)
        ):
            raise ValueError
    except ValueError:
        raise SmokeError("verification origin does not match the base URL") from None
    return f"{supplied.scheme}://{supplied.netloc}"


def run(
    repository_root: Path,
    *,
    base_url: str = BACKEND,
    origin: str | None = None,
) -> dict[str, object]:
    repo = repository_root.resolve(strict=True)
    request_origin = _verification_origin(base_url, origin)
    sys.path.insert(0, str(repo / "09_backend" / "src"))
    sys.path.insert(0, str(repo / "11_database"))
    import httpx

    accounts = _read_accounts()
    sessions: dict[str, dict[str, Any]] = {}
    try:
        for slot, account in accounts.items():
            sessions[slot] = _login(
                httpx,
                slot,
                account,
                base_url=base_url,
                origin=request_origin,
            )
            me = sessions[slot]["client"].get("/api/v1/auth/me")
            if (
                me.status_code != 200
                or _data(me).get("user_id") != sessions[slot]["actor"]["user_id"]
            ):
                raise SmokeError(f"authenticated actor read failed: {slot}")
            _require_csrf_rejection(sessions[slot], origin=request_origin)

        for school in ("alpha", "beta"):
            teacher = sessions[f"{school}.teacher"]
            specialist = sessions[f"{school}.psychological_specialist"]
            admin = sessions[f"{school}.admin"]
            student = sessions[f"{school}.student"]
            if teacher["client"].get("/api/v1/teacher/overview").status_code != 200:
                raise SmokeError(f"teacher endpoint failed for {school}")
            if (
                specialist["client"]
                .get("/api/v1/school/professional-reviews/tasks")
                .status_code
                != 200
            ):
                raise SmokeError(f"specialist endpoint failed for {school}")
            admin_directory = admin["client"].get("/api/v1/school/admin/directory")
            if admin_directory.status_code != 200:
                raise SmokeError(f"administrator endpoint failed for {school}")
            directory = _data(admin_directory)
            other_school = "beta" if school == "alpha" else "alpha"
            if EXPECTED_SCHOOL[other_school] in json.dumps(directory):
                raise SmokeError(
                    f"administrator directory crossed school scope: {school}"
                )
            _require_status(
                student,
                "get",
                "/api/v1/teacher/overview",
                403,
                f"student_teacher:{school}",
            )
            _require_status(
                student,
                "get",
                "/api/v1/school/admin/directory",
                403,
                f"student_admin:{school}",
            )
            _require_status(
                student,
                "get",
                "/api/v1/school/professional-reviews/tasks",
                403,
                f"student_specialist:{school}",
            )
            _require_status(
                teacher,
                "get",
                "/api/v1/school/professional-reviews/tasks",
                403,
                f"teacher_specialist:{school}",
            )
            _require_status(
                specialist,
                "get",
                "/api/v1/teacher/overview",
                403,
                f"specialist_teacher:{school}",
            )
            _require_status(
                specialist,
                "get",
                "/api/v1/school/admin/directory",
                403,
                f"specialist_admin:{school}",
            )
            _require_status(
                teacher,
                "get",
                "/api/v1/school/admin/directory",
                403,
                f"teacher_admin:{school}",
            )
            _require_status(
                admin,
                "get",
                "/api/v1/school/professional-reviews/tasks",
                403,
                f"admin_specialist:{school}",
            )
            _require_status(
                admin,
                "get",
                "/api/v1/teacher/overview",
                403,
                f"admin_teacher:{school}",
            )

        cross_school = sessions["alpha.teacher"]["client"].get(
            "/api/v1/teacher/students/SUBJ_SYNTHETIC_SCHOOL_SEED_BETA_V1"
        )
        if cross_school.status_code not in {403, 404}:
            raise SmokeError("cross-school teacher subject access was not rejected")

        teacher = sessions["alpha.teacher"]
        teacher_user_id = teacher["actor"]["user_id"]
        _restart_backend()
        persisted_session = teacher["client"].get("/api/v1/auth/me")
        if (
            persisted_session.status_code != 200
            or _data(persisted_session).get("user_id") != teacher_user_id
        ):
            raise SmokeError("database-backed session did not survive Backend restart")

        return {
            "http_smoke": "PASS",
            "base_url": base_url,
            "authenticated_accounts": len(sessions),
            "role_boundaries": "PASS",
            "cross_school_subject_denial": "PASS",
            "csrf_enforcement": "PASS",
            "session_after_restart": "PASS",
            "response_bodies_or_credentials_logged": False,
        }
    finally:
        for session in sessions.values():
            with suppress(httpx.HTTPError):
                session["client"].post(
                    "/api/v1/auth/logout",
                    headers={
                        "Origin": request_origin,
                        "X-CSRF-Token": session["csrf"],
                        "Accept": "application/json",
                    },
                    timeout=10,
                )
            session["client"].close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--base-url", default=BACKEND)
    parser.add_argument("--origin")
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                run(args.repo_root, base_url=args.base_url, origin=args.origin),
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - credentials, tokens, response data stay private.
        print(
            json.dumps(
                {"http_smoke": "BLOCKED", "error_type": type(exc).__name__},
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
