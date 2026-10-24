from __future__ import annotations

import base64
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prepare_school_runtime
import restore_school_workspace as restore_module
from school_restore_plan import trusted_manifest
from school_schema import (
    CURRENT_SCHOOL_REVISION,
    INDEPENDENT_EDUCATION_REVIEW_REVISION,
    PUBLIC_OBSERVED_CASE_ASSIGNMENTS_REVISION,
    RESEARCH_EDUCATION_JOBS_REVISION,
    RESEARCH_REVIEW_FEEDBACK_REVISION,
)


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "workspace.json").write_text('{"workspace_id":"source-id"}')
    backups = source / "backups"
    backups.mkdir()
    backup_file = backups / "sealed.private.dpapi"
    backup_file.write_bytes(b"synthetic-sealed-fixture")
    target = tmp_path / "new-target"
    package = {"workspace_id": "source-id", "port": 3308, "revision": "20261011_0005",
               "database_key_container_b64": base64.b64encode(b"original-sealed-key").decode()}
    calls = []

    def read_private(path):
        if path == backup_file:
            return package
        return {"DB_USER": "synthetic", "DB_PASSWORD": "synthetic"}

    def create(target, _vendor, _repo, port):
        calls.append("create")
        target.mkdir()
        marker = {"workspace_id": "new-id", "database": "smhai_school_demo",
                  "port": port, "data_directory": str(target / "mysql-data")}
        (target / "workspace.json").write_text(json.dumps(marker))
        (target / "database-keys.private.dpapi").write_bytes(b"generated-sealed-key")
        return marker

    class Connection:
        def close(self):
            calls.append("close")

    monkeypatch.setattr(restore_module, "read_private", read_private)
    monkeypatch.setattr(restore_module, "plan_restore", lambda *_a, **_kw: calls.append("preflight"))
    monkeypatch.setattr(restore_module, "validate_target", lambda *_a: calls.append("validate-target"))
    monkeypatch.setattr(restore_module, "create", create)
    monkeypatch.setattr(prepare_school_runtime, "verify_process", lambda *_a: calls.append("verify-process"))
    monkeypatch.setattr(prepare_school_runtime, "prepare", lambda *_a: calls.append("prepare-runtime"))
    monkeypatch.setattr(restore_module, "_migrate", lambda *_a: calls.append("migrate"))
    monkeypatch.setattr(restore_module, "import_snapshot", lambda *_a, **_kw: {"row_count": 3})
    def verify_ciphertexts(_connection, _target, _repository, snapshot_revision):
        calls.append(("verify-ciphertexts", snapshot_revision))
        return 2

    monkeypatch.setattr(restore_module, "_verify_ciphertexts", verify_ciphertexts)
    monkeypatch.setitem(sys.modules, "pymysql", types.SimpleNamespace(connect=lambda **_kw: Connection()))
    return backup_file, source, target, tmp_path / "vendor", tmp_path / "repo", package, calls


def run(scenario, port=3309):
    return restore_module.restore(*scenario[:5], port)


def test_full_fake_restore_preserves_source_and_unused_generated_keys(scenario):
    backup, source, target, *_rest = scenario
    before = backup.read_bytes()
    result = run(scenario)
    assert result["ready"] is False
    assert result["ciphertext_count"] == 2
    assert (target / "database-keys.private.dpapi").read_bytes() == b"original-sealed-key"
    assert (target / "generated-unused-keys.private.dpapi").read_bytes() == b"generated-sealed-key"
    assert backup.read_bytes() == before
    assert not (source / "restore-state.json").exists()
    assert scenario[-1].index("preflight") < scenario[-1].index("create")
    assert scenario[-1].index("verify-process") < scenario[-1].index("migrate")
    assert ("verify-ciphertexts", scenario[-2]["revision"]) in scenario[-1]


def test_0014_backup_imports_at_source_revision_then_migrates_forward(scenario, monkeypatch):
    package = scenario[-2]
    package["revision"] = PUBLIC_OBSERVED_CASE_ASSIGNMENTS_REVISION
    migrations = []
    monkeypatch.setattr(
        restore_module,
        "_migrate",
        lambda _target, _repository, _marker, revision: migrations.append(revision),
    )

    run(scenario)

    assert migrations == [PUBLIC_OBSERVED_CASE_ASSIGNMENTS_REVISION, CURRENT_SCHOOL_REVISION]
    state = json.loads((scenario[2] / "restore-state.json").read_text(encoding="utf-8"))
    assert state["snapshot_revision"] == PUBLIC_OBSERVED_CASE_ASSIGNMENTS_REVISION
    assert state["runtime_revision"] == CURRENT_SCHOOL_REVISION
    assert ("verify-ciphertexts", PUBLIC_OBSERVED_CASE_ASSIGNMENTS_REVISION) in scenario[-1]


def test_source_port_rejected_before_target_creation(scenario):
    with pytest.raises(ValueError, match="different isolated port"):
        run(scenario, 3308)
    assert "create" not in scenario[-1]


def test_newer_snapshot_is_rejected_before_target_creation(scenario, monkeypatch):
    monkeypatch.setattr(restore_module, "CURRENT_SCHOOL_REVISION", "20261012_0006")
    scenario[-2]["revision"] = "20261012_0007"
    with pytest.raises(ValueError, match="newer than"):
        run(scenario)
    assert "create" not in scenario[-1]


def test_overlap_rejected_before_target_creation(scenario):
    overlap = (*scenario[:2], scenario[1] / "nested-target", *scenario[3:])
    with pytest.raises(ValueError, match="must not overlap"):
        run(overlap)
    assert "create" not in scenario[-1]


def test_preflight_failure_does_not_create_target(scenario, monkeypatch):
    def reject(*_a, **_kw):
        raise ValueError("invalid snapshot")

    monkeypatch.setattr(restore_module, "plan_restore", reject)
    with pytest.raises(ValueError, match="invalid snapshot"):
        run(scenario)
    assert not scenario[2].exists()


def test_failed_import_preserves_target_and_records_only_error_type(scenario, monkeypatch):
    def reject(*_a, **_kw):
        raise RuntimeError("synthetic sensitive row must not be persisted")

    monkeypatch.setattr(restore_module, "import_snapshot", reject)
    with pytest.raises(RuntimeError) as error:
        run(scenario)
    state = (scenario[2] / "restore-state.json").read_text()
    assert "FAILED_PRESERVED" in state and "SCHEMA_READY" in state
    assert "sensitive row" not in state and "sensitive row" not in str(error.value)
    assert (scenario[2] / "database-keys.private.dpapi").read_bytes() == b"generated-sealed-key"
    assert "close" in scenario[-1]
    assert "prepare-runtime" not in scenario[-1]


class CiphertextCursor:
    def __init__(self, available_tables, rows_by_column):
        self.available_tables = available_tables
        self.rows_by_column = rows_by_column
        self.queries = []
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False

    def execute(self, statement):
        self.queries.append(statement)
        table = statement.split("FROM `", maxsplit=1)[1].split("`", maxsplit=1)[0]
        column = statement.split("SELECT `", maxsplit=1)[1].split("`", maxsplit=1)[0]
        if table not in self.available_tables:
            raise AssertionError(f"query references a table absent from this snapshot: {table}")
        self.rows = self.rows_by_column.get((table, column), [])

    def fetchall(self):
        return self.rows


class CiphertextConnection:
    def __init__(self, available_tables, rows_by_column=None):
        self.fake_cursor = CiphertextCursor(available_tables, rows_by_column or {})

    def cursor(self):
        return self.fake_cursor


def install_fake_crypto(monkeypatch, decrypted, *, contact_payload=None):
    crypto = types.ModuleType("database_layer.crypto")

    class EncryptedPayload:
        def __init__(self, *, ciphertext, key_version, cipher_format_version, payload_schema_version):
            self.ciphertext = ciphertext
            self.key_version = key_version
            self.cipher_format_version = cipher_format_version
            self.payload_schema_version = payload_schema_version

    class DataProtection:
        def __init__(self, _key_provider):
            pass

        def decrypt_json(self, payload):
            decrypted.append(payload.ciphertext)
            if payload.payload_schema_version == "school-staff-contact.v1":
                return contact_payload or {"contact": "staff@example.test"}
            return {"synthetic": True}

    crypto.EncryptedPayload = EncryptedPayload
    crypto.FernetDataProtectionProvider = DataProtection
    crypto.WindowsDpapiKeyProvider = lambda *_args: object()
    monkeypatch.setitem(sys.modules, "database_layer.crypto", crypto)


@pytest.mark.parametrize("revision", ["20261011_0005", "20261012_0006"])
def test_ciphertext_verification_uses_historical_manifest_without_new_review_table(
    tmp_path, monkeypatch, revision
):
    manifest = trusted_manifest(revision)
    assert "school_professional_review_cases" not in manifest
    connection = CiphertextConnection(set(manifest))
    decrypted = []
    install_fake_crypto(monkeypatch, decrypted)

    checked = restore_module._verify_ciphertexts(
        connection, tmp_path, tmp_path, revision
    )

    assert checked == 0
    assert decrypted == []
    assert connection.fake_cursor.queries
    assert all("school_professional_review_cases" not in sql for sql in connection.fake_cursor.queries)


def test_ciphertext_verification_checks_review_note_for_0007_snapshot(tmp_path, monkeypatch):
    revision = "20261012_0007"
    manifest = trusted_manifest(revision)
    assert "case_note_ciphertext" in manifest["school_professional_review_cases"]
    connection = CiphertextConnection(
        set(manifest),
        {
            ("school_professional_review_cases", "case_note_ciphertext"): [
                (b"synthetic-encrypted-note", "key-v1", "fernet.v1", "review-note.v1")
            ]
        },
    )
    decrypted = []
    install_fake_crypto(monkeypatch, decrypted)

    checked = restore_module._verify_ciphertexts(
        connection, tmp_path, tmp_path, revision
    )

    assert checked == 1
    assert decrypted == [b"synthetic-encrypted-note"]
    assert any(
        "SELECT `case_note_ciphertext`,`key_version`,`cipher_format_version`,"
        "`payload_schema_version`" in sql
        and "FROM `school_professional_review_cases`" in sql
        for sql in connection.fake_cursor.queries
    )


def test_0017_ciphertext_verification_uses_new_review_and_feedback_metadata(tmp_path, monkeypatch):
    manifest = trusted_manifest(RESEARCH_REVIEW_FEEDBACK_REVISION)
    new_tables = {
        "school_research_review_cases",
        "school_research_review_events",
        "school_research_feedback_records",
        "school_research_feedback_events",
    }
    assert new_tables <= set(manifest)
    connection = CiphertextConnection(
        set(manifest),
        {
            ("school_research_review_cases", "case_note_ciphertext"): [
                (b"synthetic-review-note-cipher", "key-v1", "fernet.v1", "research-note.v1")
            ],
            ("school_research_feedback_records", "payload_ciphertext"): [
                (b"synthetic-feedback-cipher", "key-v1", "fernet.v1", "research-feedback.v1")
            ],
        },
    )
    decrypted = []
    install_fake_crypto(monkeypatch, decrypted)

    checked = restore_module._verify_ciphertexts(
        connection, tmp_path, tmp_path, RESEARCH_REVIEW_FEEDBACK_REVISION
    )

    assert checked == 2
    assert set(decrypted) == {
        b"synthetic-review-note-cipher",
        b"synthetic-feedback-cipher",
    }
    assert any(
        "`case_note_key_version`,`case_note_cipher_format_version`,"
        "`case_note_payload_schema_version`" in sql
        and "FROM `school_research_review_cases`" in sql
        for sql in connection.fake_cursor.queries
    )
    assert any(
        "SELECT `payload_ciphertext`,`key_version`,`cipher_format_version`,"
        "`payload_schema_version`" in sql
        and "FROM `school_research_feedback_records`" in sql
        for sql in connection.fake_cursor.queries
    )


def test_0020_ciphertext_verification_includes_held_education_candidate(tmp_path, monkeypatch):
    manifest = trusted_manifest(CURRENT_SCHOOL_REVISION)
    table_name = "school_research_education_candidates"
    assert table_name in manifest
    connection = CiphertextConnection(
        set(manifest),
        {
            (table_name, "payload_ciphertext"): [
                (
                    b"synthetic-held-candidate-cipher",
                    "school-key-v1",
                    "fernet.v1",
                    "school_research_education_candidate.v1",
                )
            ],
        },
    )
    decrypted = []
    install_fake_crypto(monkeypatch, decrypted)
    checked = restore_module._verify_ciphertexts(
        connection, tmp_path, tmp_path, CURRENT_SCHOOL_REVISION
    )

    assert checked == 1
    assert decrypted == [b"synthetic-held-candidate-cipher"]
    assert any(
        "SELECT `payload_ciphertext`,`key_version`,`cipher_format_version`,`payload_schema_version`" in sql
        and f"FROM `{table_name}`" in sql
        for sql in connection.fake_cursor.queries
    )
    assert "school_research_education_candidate_events" in manifest


def test_0025_verifies_encrypted_staff_contact_envelope_and_metadata(
    tmp_path, monkeypatch
):
    table_name = "school_staff_invitations"
    manifest = trusted_manifest(CURRENT_SCHOOL_REVISION)
    assert {
        "work_contact_ciphertext",
        "work_contact_cipher_format_version",
        "work_contact_key_version",
        "work_contact_payload_schema_version",
    } <= set(manifest[table_name])
    connection = CiphertextConnection(
        set(manifest),
        {
            (table_name, "work_contact_ciphertext"): [
                (b"synthetic-encrypted-contact", "key-v1", "fernet.v1", "school-staff-contact.v1")
            ],
        },
    )
    decrypted = []
    install_fake_crypto(monkeypatch, decrypted)

    checked = restore_module._verify_ciphertexts(
        connection, tmp_path, tmp_path, CURRENT_SCHOOL_REVISION
    )

    assert checked == 1
    assert decrypted == [b"synthetic-encrypted-contact"]
    assert any(
        "SELECT `work_contact_ciphertext`,`work_contact_key_version`,"
        "`work_contact_cipher_format_version`,`work_contact_payload_schema_version`"
        in sql
        and "FROM `school_staff_invitations`" in sql
        for sql in connection.fake_cursor.queries
    )


def test_0025_rejects_unsupported_staff_contact_envelope(tmp_path, monkeypatch):
    table_name = "school_staff_invitations"
    manifest = {
        table_name: [
            "work_contact_ciphertext",
            "work_contact_cipher_format_version",
            "work_contact_key_version",
            "work_contact_payload_schema_version",
        ],
        "database_alembic_version": ["version_num"],
    }
    monkeypatch.setattr(restore_module, "trusted_manifest", lambda _revision: manifest)
    connection = CiphertextConnection(
        set(manifest),
        {
            (table_name, "work_contact_ciphertext"): [
                (b"synthetic-encrypted-contact", "key-v1", "fernet.v1", "unexpected.v1")
            ],
        },
    )
    decrypted = []
    install_fake_crypto(monkeypatch, decrypted)

    with pytest.raises(RuntimeError, match="schema version"):
        restore_module._verify_ciphertexts(
            connection, tmp_path, tmp_path, CURRENT_SCHOOL_REVISION
        )
    assert decrypted == []


def test_0025_rejects_extra_fields_in_staff_contact_envelope(tmp_path, monkeypatch):
    table_name = "school_staff_invitations"
    manifest = {
        table_name: [
            "work_contact_ciphertext",
            "work_contact_cipher_format_version",
            "work_contact_key_version",
            "work_contact_payload_schema_version",
        ],
        "database_alembic_version": ["version_num"],
    }
    monkeypatch.setattr(restore_module, "trusted_manifest", lambda _revision: manifest)
    connection = CiphertextConnection(
        set(manifest),
        {
            (table_name, "work_contact_ciphertext"): [
                (b"synthetic-encrypted-contact", "key-v1", "fernet.v1", "school-staff-contact.v1")
            ],
        },
    )
    install_fake_crypto(
        monkeypatch,
        [],
        contact_payload={"contact": "staff@example.test", "unexpected": "value"},
    )

    with pytest.raises(TypeError, match="encrypted object"):
        restore_module._verify_ciphertexts(
            connection, tmp_path, tmp_path, CURRENT_SCHOOL_REVISION
        )


def test_0024_ciphertext_verification_uses_exact_independent_review_metadata_columns(
    tmp_path, monkeypatch
):
    table_name = "school_independent_education_reviews"
    manifest = {
        table_name: [
            "candidate_payload_ciphertext",
            "candidate_cipher_format_version",
            "candidate_key_version",
            "candidate_payload_schema_version",
            "reviewed_payload_ciphertext",
            "reviewed_cipher_format_version",
            "reviewed_key_version",
            "reviewed_payload_schema_version",
        ],
        "school_independent_education_review_events": ["id"],
    }
    def pinned_manifest(revision):
        assert revision == INDEPENDENT_EDUCATION_REVIEW_REVISION
        return manifest

    monkeypatch.setattr(restore_module, "trusted_manifest", pinned_manifest)
    connection = CiphertextConnection(
        set(manifest),
        {
            (table_name, "candidate_payload_ciphertext"): [
                (b"synthetic-candidate-payload", "key-v1", "fernet.v1", "candidate.v1")
            ],
            (table_name, "reviewed_payload_ciphertext"): [
                (b"synthetic-reviewed-payload", "key-v1", "fernet.v1", "reviewed.v1")
            ],
        },
    )
    decrypted = []
    install_fake_crypto(monkeypatch, decrypted)

    checked = restore_module._verify_ciphertexts(
        connection, tmp_path, tmp_path, INDEPENDENT_EDUCATION_REVIEW_REVISION
    )

    assert checked == 2
    assert set(decrypted) == {b"synthetic-candidate-payload", b"synthetic-reviewed-payload"}
    queries = connection.fake_cursor.queries
    assert any(
        "SELECT `candidate_payload_ciphertext`,`candidate_key_version`,"
        "`candidate_cipher_format_version`,`candidate_payload_schema_version`" in sql
        and f"FROM `{table_name}`" in sql
        for sql in queries
    )
    assert any(
        "SELECT `reviewed_payload_ciphertext`,`reviewed_key_version`,"
        "`reviewed_cipher_format_version`,`reviewed_payload_schema_version`" in sql
        and f"FROM `{table_name}`" in sql
        for sql in queries
    )


def test_0024_ciphertext_verification_rejects_missing_special_metadata(tmp_path, monkeypatch):
    table_name = "school_independent_education_reviews"
    manifest = {
        table_name: ["candidate_payload_ciphertext", "candidate_cipher_format_version",
                     "candidate_payload_schema_version"],
    }
    monkeypatch.setattr(restore_module, "trusted_manifest", lambda _revision: manifest)
    connection = CiphertextConnection(
        set(manifest), {(table_name, "candidate_payload_ciphertext"): []}
    )
    decrypted = []
    install_fake_crypto(monkeypatch, decrypted)

    with pytest.raises(RuntimeError, match="Trusted encrypted payload metadata is incomplete"):
        restore_module._verify_ciphertexts(
            connection, tmp_path, tmp_path, INDEPENDENT_EDUCATION_REVIEW_REVISION
        )

    assert connection.fake_cursor.queries == []
    assert decrypted == []


def test_0016_ciphertext_verification_excludes_0017_tables(tmp_path, monkeypatch):
    manifest = trusted_manifest(RESEARCH_EDUCATION_JOBS_REVISION)
    new_tables = {
        "school_research_review_cases",
        "school_research_review_events",
        "school_research_feedback_records",
        "school_research_feedback_events",
    }
    assert new_tables.isdisjoint(manifest)
    connection = CiphertextConnection(set(manifest))
    decrypted = []
    install_fake_crypto(monkeypatch, decrypted)

    checked = restore_module._verify_ciphertexts(
        connection, tmp_path, tmp_path, RESEARCH_EDUCATION_JOBS_REVISION
    )

    assert checked == 0
    assert decrypted == []
    assert all(not any(table in sql for table in new_tables) for sql in connection.fake_cursor.queries)


def test_ciphertext_verification_rejects_unknown_revision_before_query(tmp_path, monkeypatch):
    connection = CiphertextConnection(set())
    decrypted = []
    install_fake_crypto(monkeypatch, decrypted)

    with pytest.raises(ValueError, match="Unsupported restore revision"):
        restore_module._verify_ciphertexts(connection, tmp_path, tmp_path, "head")

    assert connection.fake_cursor.queries == []
    assert decrypted == []
