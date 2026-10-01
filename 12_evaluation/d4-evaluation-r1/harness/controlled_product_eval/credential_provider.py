"""Fixed, evaluation-only credential sources for the approved D4-3B path.

This module intentionally has no generic secret lookup or operating-system
credential-store integration. Secret-bearing fields are excluded from reprs.
"""

from __future__ import annotations

import ast
import secrets
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .process_lifecycle import build_child_environment


ACCEPTED_PRODUCT_BASELINE = "dd083d7a9d50e554408571e8b6d8040700d7a88b"
ACCEPTED_FIXTURE_BLOB = "c56470f9d240b6d1d2af6e2891daaf8a454d2268"
FIXTURE_SOURCE_RELATIVE = Path(
    "09_backend/src/smhai_backend/adapters/database.py"
)
EXPECTED_SYNTHETIC_SUBJECTS = {
    "student_a": "SUBJ_demo_a",
    "student_b": "SUBJ_demo_b",
}


class CredentialProviderError(RuntimeError):
    """A fixed evaluation credential source failed a fail-closed check."""


@dataclass(frozen=True, slots=True)
class DatabaseCredential:
    host: str
    port: int
    database: str
    username: str
    password: str = field(repr=False)

    def __repr__(self) -> str:
        return (
            "DatabaseCredential(host='127.0.0.1', port=3307, "
            "database='smhai_d4_evaluation', username='smhai_eval_app', "
            "password=<redacted>)"
        )


@dataclass(frozen=True, slots=True)
class SyntheticLoginCredential:
    username: str
    password: str = field(repr=False)
    expected_subject_id: str

    def __repr__(self) -> str:
        return (
            f"SyntheticLoginCredential(username={self.username!r}, "
            f"expected_subject_id={self.expected_subject_id!r}, password=<redacted>)"
        )


@dataclass(frozen=True, slots=True)
class SyntheticLoginCredentials:
    student_a: SyntheticLoginCredential = field(repr=False)
    student_b: SyntheticLoginCredential = field(repr=False)
    source_verified: bool = True

    def __repr__(self) -> str:
        return "SyntheticLoginCredentials(users=('student_a', 'student_b'), passwords=<redacted>)"

    def password_mapping(self) -> Mapping[str, str]:
        return {
            "student_a": self.student_a.password,
            "student_b": self.student_b.password,
        }

    def expected_subject_mapping(self) -> Mapping[str, str]:
        return {
            "student_a": self.student_a.expected_subject_id,
            "student_b": self.student_b.expected_subject_id,
        }

    def secret_values(self) -> tuple[str, str]:
        return (self.student_a.password, self.student_b.password)


class EvaluationCredentialProvider:
    """Provide only the run-local DB credential and frozen A/B fixtures."""

    def generate_database_credential(self) -> DatabaseCredential:
        password = secrets.token_urlsafe(48)
        if not password:
            raise CredentialProviderError("DATABASE_CREDENTIAL_GENERATION_FAILED")
        return DatabaseCredential(
            host="127.0.0.1",
            port=3307,
            database="smhai_d4_evaluation",
            username="smhai_eval_app",
            password=password,
        )

    def resolve_frozen_synthetic_credentials(
        self, repo_root: str | Path
    ) -> SyntheticLoginCredentials:
        root = Path(repo_root).resolve()
        source_path = (root / FIXTURE_SOURCE_RELATIVE).resolve()
        try:
            source_path.relative_to(root)
        except ValueError:
            raise CredentialProviderError("FIXTURE_SOURCE_PATH_INVALID") from None
        if not source_path.is_file():
            raise CredentialProviderError("FIXTURE_SOURCE_UNAVAILABLE")

        baseline_blob = _git_blob_for_revision(
            root,
            f"{ACCEPTED_PRODUCT_BASELINE}:{FIXTURE_SOURCE_RELATIVE.as_posix()}",
        )
        current_blob = _git_blob_for_file(root, source_path)
        if (
            baseline_blob != ACCEPTED_FIXTURE_BLOB
            or current_blob != ACCEPTED_FIXTURE_BLOB
        ):
            raise CredentialProviderError("FIXTURE_SOURCE_DRIFT")

        try:
            source = source_path.read_bytes().decode("utf-8")
            tree = ast.parse(source, filename=str(FIXTURE_SOURCE_RELATIVE))
        except (OSError, UnicodeDecodeError, SyntaxError):
            raise CredentialProviderError("FIXTURE_SOURCE_UNREADABLE") from None
        rows = _fixture_rows(tree)
        return SyntheticLoginCredentials(
            student_a=SyntheticLoginCredential(
                username="student_a",
                password=rows["student_a"],
                expected_subject_id=EXPECTED_SYNTHETIC_SUBJECTS["student_a"],
            ),
            student_b=SyntheticLoginCredential(
                username="student_b",
                password=rows["student_b"],
                expected_subject_id=EXPECTED_SYNTHETIC_SUBJECTS["student_b"],
            ),
        )


def _git_executable() -> Path:
    candidate = shutil.which("git")
    if not candidate:
        raise CredentialProviderError("FIXTURE_SOURCE_VERIFICATION_UNAVAILABLE")
    path = Path(candidate)
    if not path.is_absolute() or not path.is_file():
        raise CredentialProviderError("FIXTURE_SOURCE_VERIFICATION_UNAVAILABLE")
    return path.resolve()


def _git_blob_for_revision(repo_root: Path, revision_path: str) -> str:
    try:
        result = subprocess.run(
            [
                str(_git_executable()),
                "-C",
                str(repo_root),
                "rev-parse",
                "--verify",
                revision_path,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=False,
            check=True,
            timeout=10,
            env=build_child_environment({}),
        )
    except (OSError, subprocess.SubprocessError):
        raise CredentialProviderError("FIXTURE_SOURCE_VERIFICATION_UNAVAILABLE") from None
    return result.stdout.decode("ascii", errors="ignore").strip().lower()


def _git_blob_for_file(repo_root: Path, source_path: Path) -> str:
    try:
        source_path.relative_to(repo_root)
        result = subprocess.run(
            [
                str(_git_executable()),
                "-c",
                "core.autocrlf=true",
                "-C",
                str(repo_root),
                "hash-object",
                f"--path={FIXTURE_SOURCE_RELATIVE.as_posix()}",
                str(source_path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=False,
            check=True,
            timeout=10,
            env=build_child_environment({}),
        )
    except (ValueError, OSError, subprocess.SubprocessError):
        raise CredentialProviderError("FIXTURE_SOURCE_VERIFICATION_UNAVAILABLE") from None
    return result.stdout.decode("ascii", errors="ignore").strip().lower()


def _fixture_rows(tree: ast.Module) -> dict[str, str]:
    adapter = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "MySqlBackendAdapter"
        ),
        None,
    )
    start = next(
        (
            node
            for node in adapter.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "start"
        ),
        None,
    ) if adapter else None
    if start is None:
        raise CredentialProviderError("FIXTURE_INITIALIZER_NOT_FOUND")

    start_calls_initializer = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_ensure_synthetic_fixtures"
        for node in ast.walk(start)
    )
    initializer = next(
        (
            node
            for node in adapter.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_ensure_synthetic_fixtures"
        ),
        None,
    )
    if not start_calls_initializer or initializer is None:
        raise CredentialProviderError("FIXTURE_INITIALIZER_NOT_FOUND")

    fixture_loop = any(
        isinstance(node, ast.For)
        and isinstance(node.iter, ast.Name)
        and node.iter.id == "fixtures"
        and isinstance(node.target, (ast.Tuple, ast.List))
        and [
            item.id if isinstance(item, ast.Name) else None
            for item in node.target.elts
        ]
        == ["username", "password", "role_code", "self_subject_ref"]
        for node in ast.walk(initializer)
    )
    if not fixture_loop:
        raise CredentialProviderError("FIXTURE_INITIALIZER_FORMAT_UNSUPPORTED")

    fixture_values: list[ast.expr] = []
    for node in ast.walk(initializer):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(
            isinstance(target, ast.Name) and target.id == "fixtures"
            for target in targets
        ):
            fixture_values.append(node.value)
    if len(fixture_values) != 1:
        raise CredentialProviderError("FIXTURE_INITIALIZER_AMBIGUOUS")

    value = fixture_values[0]
    if not isinstance(value, (ast.Tuple, ast.List)):
        raise CredentialProviderError("FIXTURE_INITIALIZER_FORMAT_UNSUPPORTED")

    resolved: dict[str, str] = {}
    for row in value.elts:
        if not isinstance(row, (ast.Tuple, ast.List)) or len(row.elts) < 4:
            continue
        username_node = row.elts[0]
        if not isinstance(username_node, ast.Constant) or not isinstance(
            username_node.value, str
        ):
            continue
        username = username_node.value
        if username not in EXPECTED_SYNTHETIC_SUBJECTS:
            continue
        if username in resolved:
            raise CredentialProviderError("FIXTURE_IDENTITY_DUPLICATED")
        password_node = row.elts[1]
        subject_node = row.elts[3]
        if (
            not isinstance(password_node, ast.Constant)
            or not isinstance(password_node.value, str)
            or not password_node.value
            or not isinstance(subject_node, ast.Constant)
            or subject_node.value != EXPECTED_SYNTHETIC_SUBJECTS[username]
        ):
            raise CredentialProviderError("FIXTURE_IDENTITY_MISMATCH")
        resolved[username] = password_node.value

    if set(resolved) != set(EXPECTED_SYNTHETIC_SUBJECTS):
        raise CredentialProviderError("FIXTURE_IDENTITIES_INCOMPLETE")
    return resolved


def credential_evidence_metadata() -> dict[str, object]:
    """Return the only allowed DB-credential evidence; never include a value."""

    return {
        "credential_source": "EPHEMERAL_RUN_LOCAL",
        "credential_generated": True,
        "credential_present": True,
        "plaintext_recorded": False,
        "serialized": False,
        "persisted": False,
        "credential_manager_target": "IGNORED_UNCLASSIFIED_CREDENTIAL_TARGET",
    }
