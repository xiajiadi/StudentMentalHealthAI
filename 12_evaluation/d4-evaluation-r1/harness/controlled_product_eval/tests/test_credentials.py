from __future__ import annotations

import uuid
from pathlib import Path
import sys

import pytest

from harness.controlled_product_eval import credential_provider as provider_module
from harness.controlled_product_eval.credential_provider import (
    ACCEPTED_FIXTURE_BLOB,
    ACCEPTED_PRODUCT_BASELINE,
    DatabaseCredential,
    FIXTURE_SOURCE_RELATIVE,
    CredentialProviderError,
    EvaluationCredentialProvider,
    credential_evidence_metadata,
)
from harness.controlled_product_eval.mysql_bootstrap import IsolatedMySqlBootstrap
from harness.controlled_product_eval.process_lifecycle import ManagedCommandResult
from harness.controlled_product_eval.secret_scan import scan_secret_artifacts


ROOT = Path(__file__).resolve().parents[5]


def _fixture_source(student_a_subject: str = "SUBJ_demo_a") -> tuple[str, tuple[str, str]]:
    password_a = "fixture-a-" + uuid.uuid4().hex
    password_b = "fixture-b-" + uuid.uuid4().hex
    source = f'''\
class MySqlBackendAdapter:
    async def start(self):
        await self._ensure_synthetic_fixtures()

    async def _ensure_synthetic_fixtures(self):
        fixtures = (
            ("student_a", {password_a!r}, "student", {student_a_subject!r}),
            ("student_b", {password_b!r}, "student", "SUBJ_demo_b"),
            ("teacher_demo", "unrelated-{uuid.uuid4().hex}", "teacher", None),
        )
        for username, password, role_code, self_subject_ref in fixtures:
            pass
'''
    return source, (password_a, password_b)


def _write_fixture_source(root: Path, source: str) -> Path:
    target = root / FIXTURE_SOURCE_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return target


def test_each_run_generates_an_independent_database_credential():
    provider = EvaluationCredentialProvider()
    first = provider.generate_database_credential()
    second = provider.generate_database_credential()
    independent = first.password != second.password
    assert independent, "fresh runs must receive distinct generated credentials"
    assert first.host == second.host == "127.0.0.1"
    assert first.port == second.port == 3307
    assert "<redacted>" in repr(first)
    assert first.password not in repr(first), "credential repr must redact the value"


def test_frozen_source_resolves_only_expected_synthetic_accounts():
    credentials = EvaluationCredentialProvider().resolve_frozen_synthetic_credentials(ROOT)
    password_mapping = credentials.password_mapping()
    identities = credentials.expected_subject_mapping()
    assert set(password_mapping) == {"student_a", "student_b"}
    assert all(password_mapping.values()), "both frozen fixture credentials must be present"
    assert identities == {"student_a": "SUBJ_demo_a", "student_b": "SUBJ_demo_b"}
    assert credentials.source_verified is True
    assert "passwords=<redacted>" in repr(credentials)


def test_fixture_blob_drift_fails_closed_without_revealing_fixture_values(tmp_path, monkeypatch):
    source, passwords = _fixture_source()
    _write_fixture_source(tmp_path, source)
    monkeypatch.setattr(
        provider_module,
        "_git_blob_for_revision",
        lambda _root, _revision: ACCEPTED_FIXTURE_BLOB,
    )
    monkeypatch.setattr(
        provider_module,
        "_git_blob_for_file",
        lambda _root, _path: "0" * 40,
    )
    with pytest.raises(CredentialProviderError) as exc_info:
        EvaluationCredentialProvider().resolve_frozen_synthetic_credentials(tmp_path)
    error_text = str(exc_info.value)
    assert all(password not in error_text for password in passwords), "drift errors must not reveal fixture values"


def test_unexpected_fixture_subject_fails_closed(tmp_path, monkeypatch):
    source, passwords = _fixture_source(student_a_subject="SUBJ_demo_unexpected")
    _write_fixture_source(tmp_path, source)
    monkeypatch.setattr(
        provider_module,
        "_git_blob_for_revision",
        lambda _root, _revision: ACCEPTED_FIXTURE_BLOB,
    )
    monkeypatch.setattr(
        provider_module,
        "_git_blob_for_file",
        lambda _root, _path: ACCEPTED_FIXTURE_BLOB,
    )
    with pytest.raises(CredentialProviderError) as exc_info:
        EvaluationCredentialProvider().resolve_frozen_synthetic_credentials(tmp_path)
    error_text = str(exc_info.value)
    assert all(password not in error_text for password in passwords), "identity errors must not reveal fixture values"


def test_fixed_provider_has_no_generic_secret_or_credential_manager_lookup():
    provider = EvaluationCredentialProvider()
    public_methods = {
        name
        for name in dir(provider)
        if not name.startswith("_") and callable(getattr(provider, name))
    }
    assert public_methods == {
        "generate_database_credential",
        "resolve_frozen_synthetic_credentials",
    }


def test_credential_evidence_and_artifact_scan_never_record_plaintext(tmp_path):
    marker = "artifact-scan-" + uuid.uuid4().hex
    root = tmp_path / "artifacts"
    root.mkdir()
    evidence = credential_evidence_metadata()
    assert evidence == {
        "credential_source": "EPHEMERAL_RUN_LOCAL",
        "credential_generated": True,
        "credential_present": True,
        "plaintext_recorded": False,
        "serialized": False,
        "persisted": False,
        "credential_manager_target": "IGNORED_UNCLASSIFIED_CREDENTIAL_TARGET",
    }
    (root / "credential-evidence.json").write_text(str(evidence), encoding="utf-8")
    (root / "credential-evidence.md").write_text(
        "Credential source: EPHEMERAL_RUN_LOCAL; plaintext recorded: false.\n",
        encoding="utf-8",
    )
    safe_scan = scan_secret_artifacts(root, (marker,))
    assert safe_scan["status"] == "PASS"
    assert safe_scan["plaintext_occurrences"] == 0

    (root / "child.stderr.log").write_bytes(b"x" * 1022 + marker.encode("utf-8"))
    leaking_scan = scan_secret_artifacts(root, (marker,), chunk_size=1024)
    assert leaking_scan["status"] == "FAIL"
    assert leaking_scan["plaintext_occurrences"] >= 1
    assert marker not in str(leaking_scan)


def test_mysql_bootstrap_and_migration_keep_secret_only_in_child_environment(
    tmp_path, monkeypatch
):
    marker = "mysql-child-" + uuid.uuid4().hex
    credential = DatabaseCredential(
        host="127.0.0.1",
        port=3307,
        database="smhai_d4_evaluation",
        username="smhai_eval_app",
        password=marker,
    )
    bootstrap = IsolatedMySqlBootstrap(
        repo_root=ROOT,
        run_root=tmp_path / "run",
        backend_python=Path(sys.executable).resolve(),
        credential=credential,
    )
    calls = []

    def capture(**kwargs):
        calls.append(kwargs)
        return ManagedCommandResult(0, b"D4_MYSQL_BOOTSTRAP=PASS", b"")

    monkeypatch.setattr(
        "harness.controlled_product_eval.mysql_bootstrap.run_managed_command",
        capture,
    )
    bootstrap._create_app_database_and_user()
    create_call = calls[-1]
    create_argv = " ".join(create_call["arguments"])
    assert marker not in create_argv, "database password must not enter bootstrap argv"
    bootstrap_environment = create_call["environment"]
    secret_was_in_child_environment = marker in bootstrap_environment.values()
    assert secret_was_in_child_environment, "database password must be passed only to the bootstrap child"

    calls.clear()
    bootstrap._run_alembic("upgrade", "head")
    migration_call = calls[-1]
    migration_argv = " ".join(migration_call["arguments"])
    assert marker not in migration_argv, "database password must not enter Alembic argv"
    migration_url = migration_call["environment"].get("DATABASE_URL", "")
    migration_secret_is_child_local = marker in migration_url
    assert migration_secret_is_child_local, "Alembic database credentials must stay in child environment"
    assert marker not in repr(migration_call["stdout_path"])
    assert marker not in repr(migration_call["stderr_path"])


def test_mysql_server_profile_is_fresh_loopback_and_has_no_secret_argv(tmp_path):
    marker = "mysql-server-" + uuid.uuid4().hex
    credential = DatabaseCredential(
        host="127.0.0.1",
        port=3307,
        database="smhai_d4_evaluation",
        username="smhai_eval_app",
        password=marker,
    )
    bootstrap = IsolatedMySqlBootstrap(
        repo_root=ROOT,
        run_root=tmp_path / "run",
        backend_python=Path(sys.executable).resolve(),
        credential=credential,
    )
    spec = bootstrap.server_spec()
    assert spec.name == "d4-mysql"
    assert spec.executable.is_absolute()
    assert "--no-defaults" in spec.arguments
    assert "--bind-address=127.0.0.1" in spec.arguments
    assert "--port=3307" in spec.arguments
    assert "--port=3306" not in spec.arguments
    assert spec.environment == {}
    secret_free_argv = all(marker not in value for value in spec.arguments)
    assert secret_free_argv, "MySQL server command line must not contain the app credential"
    assert marker not in repr(spec)


def test_fixture_source_identity_constants_are_the_authorized_baseline():
    assert ACCEPTED_PRODUCT_BASELINE == "dd083d7a9d50e554408571e8b6d8040700d7a88b"
    assert ACCEPTED_FIXTURE_BLOB == "c56470f9d240b6d1d2af6e2891daaf8a454d2268"
