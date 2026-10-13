import json
import subprocess
import sys
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import migrate_school_workspace as migration
import resume_school_workspace as resume
from school_check_names import (
    LEGACY_CHECK_NAME_DECLARATIONS,
    legacy_school_check_names,
)

BUILDER_PASSWORD = "a" * 64
WORKSPACE_ID = "b" * 32
PORT = 3315


class FakeCursor:
    def __init__(self, database):
        self.database = database
        self.statement = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, statement, _params=None):
        self.statement = statement

    def fetchone(self):
        if self.statement == "SELECT @@port, @@datadir, DATABASE()":
            return (
                self.database.port,
                self.database.datadir,
                self.database.name,
            )
        if self.statement == "SELECT CURRENT_ROLE()":
            return (self.database.current_role,)
        if self.statement == "SELECT version_num FROM database_alembic_version":
            return (self.database.revisions[0],) if self.database.revisions else None
        return None

    def fetchall(self):
        if self.statement == "SHOW GRANTS FOR CURRENT_USER()":
            return tuple((grant,) for grant in self.database.grants)
        if (
            "COLUMN_TYPE" in self.statement
            and "information_schema.COLUMNS" in self.statement
        ):
            return tuple(
                (
                    table,
                    name,
                    value["type"],
                    value.get("collation"),
                    "YES" if value["nullable"] else "NO",
                    "auto_increment" if value["auto_increment"] else "",
                )
                for table, contract in self.database.schema.items()
                for name, value in contract.get("columns", {}).items()
            )
        if "tc.CONSTRAINT_TYPE IN ('PRIMARY KEY', 'UNIQUE')" in self.statement:
            rows = []
            for table, contract in self.database.schema.items():
                primary_key = contract.get("primary_key", ())
                if primary_key:
                    rows.extend(
                        (table, "PRIMARY", "PRIMARY KEY", column, index)
                        for index, column in enumerate(primary_key, 1)
                    )
                rows.extend(
                    (table, name, "UNIQUE", column, index)
                    for name, columns in contract.get("uniques", set())
                    for index, column in enumerate(columns, 1)
                )
            return tuple(rows)
        if "REFERENCED_TABLE_NAME IS NOT NULL" in self.statement:
            return tuple(
                (
                    table,
                    name,
                    self.database.foreign_schema_override or migration.DATABASE,
                    local,
                    target_table,
                    target_column,
                    index,
                    ondelete,
                    onupdate,
                )
                for table, contract in self.database.schema.items()
                for name, local_columns, target_table, target_columns, ondelete, onupdate in contract.get(
                    "foreign_keys", set()
                )
                for index, (local, target_column) in enumerate(
                    zip(local_columns, target_columns, strict=True), 1
                )
            )
        if "CHECK_CONSTRAINTS" in self.statement and "CHECK_CLAUSE" in self.statement:
            return tuple(
                (table, name, expression, "YES" if enforced else "NO")
                for table, contract in self.database.schema.items()
                for name, expression, enforced in contract.get("checks", set())
            )
        if "information_schema.STATISTICS" in self.statement:
            return tuple(
                (table, name, not unique, index, column, None)
                for table, contract in self.database.schema.items()
                for name, columns, unique in contract.get("indexes", set())
                for index, column in enumerate(columns, 1)
            )
        if "FROM information_schema.TABLES" in self.statement:
            return tuple(
                (table, self.database.table_type_overrides.get(table, "BASE TABLE"))
                for table in self.database.tables
            )
        if any(
            f"information_schema.{name}" in self.statement
            for name in ("ROUTINES", "EVENTS", "TRIGGERS")
        ):
            return tuple((name,) for name in self.database.other_objects)
        if self.statement == "SELECT version_num FROM database_alembic_version":
            return tuple((revision,) for revision in self.database.revisions)
        if "FROM information_schema.COLUMNS" in self.statement:
            return tuple(
                (table, column)
                for table, columns in self.database.columns.items()
                for column in columns
            )
        return ()


class FakeConnection:
    def __init__(self, database):
        self.database = database
        self.closed = False

    def cursor(self):
        return FakeCursor(self.database)

    def close(self):
        self.closed = True


class FakeType:
    def __init__(self, name):
        self.name = name

    def compile(self, dialect=None):
        return self.name


class FakeDatabase:
    def __init__(self, datadir):
        self.port = PORT
        self.datadir = str(datadir)
        self.name = "smhai_school_demo"
        self.current_role = "NONE"
        self.grants = [
            "GRANT USAGE ON *.* TO 'psynova_builder'@'127.0.0.1'",
            "GRANT ALL PRIVILEGES ON `smhai_school_demo`.* TO 'psynova_builder'@'127.0.0.1'",
        ]
        self.tables = []
        self.table_type_overrides = {}
        self.columns = {}
        self.other_objects = []
        self.revisions = []
        self.schema = {}
        self.expected_schema = {}
        self.foreign_schema_override = None


def set_current_schema(database):
    database.schema = deepcopy(database.expected_schema)
    database.tables = list(database.schema)
    database.columns = {
        table: list(contract["columns"]) for table, contract in database.schema.items()
    }
    database.revisions = [migration.CURRENT_SCHOOL_REVISION]


class FakeOperations:
    def __init__(self, marker, database):
        self.marker = marker
        self.database = database
        self.verified = []
        self.connects = 0
        self.migrations = []
        self.process_override = None
        self.child_processes = {}
        self.process_sequences = {}
        self.process_sequence_reads = {}
        self.listener_owner = marker["parent_pid"]
        self.acl_valid = True
        self.process_valid = True
        self.migration_exit = 0
        self.lock_active = False
        self.lock_busy = False
        self.lock_acquisitions = 0
        self.lock_exit_error = False
        self.guardian_calls = 0
        self.guardian_fail_on_call = None
        self.post_migration_mutation = None

    @staticmethod
    def is_supported_platform():
        return True

    @contextmanager
    def workspace_lock(self, _workspace):
        self.lock_acquisitions += 1
        if self.lock_busy or self.lock_active:
            raise resume.ResumeError("synthetic lock busy")
        self.lock_active = True
        try:
            yield
        finally:
            self.lock_active = False
            if self.lock_exit_error:
                raise OSError("synthetic lock release failure")

    def verify_acl(self, workspace):
        self.verified.append("acl")
        if not self.acl_valid:
            raise resume.ResumeError("ACL mismatch")

    def verify_running_process(self, marker):
        self.guardian_calls += 1
        self.verified.append("guardian")
        if not self.process_valid or self.guardian_calls == self.guardian_fail_on_call:
            raise resume.ResumeError("Guardian mismatch")

    def inspect_process(self, pid):
        if self.process_override is not None:
            return self.process_override
        if pid in self.process_sequences:
            reads = self.process_sequence_reads.get(pid, 0)
            self.process_sequence_reads[pid] = reads + 1
            sequence = self.process_sequences[pid]
            return deepcopy(sequence[min(reads, len(sequence) - 1)])
        if pid in self.child_processes:
            return deepcopy(self.child_processes[pid])
        return {
            "ProcessId": pid,
            "ParentProcessId": 1,
            "ExecutablePath": self.marker["executable"],
            "CreationUtc": self.marker["parent_creation_time"],
            "CommandLine": subprocess.list2cmdline(
                resume.guardian_arguments(
                    Path(self.marker["executable"]),
                    Path(self.marker["data_directory"]).parent,
                    Path(self.marker["data_directory"]),
                    self.marker["port"],
                )
            ),
        }

    def listeners(self, port):
        return [
            {
                "OwningProcess": self.listener_owner,
                "LocalAddress": "127.0.0.1",
                "LocalPort": port,
            }
        ]

    def connect_builder(self, marker, password):
        assert self.lock_active
        self.connects += 1
        assert password == BUILDER_PASSWORD
        return FakeConnection(self.database)

    def run_alembic(self, database_python, database_root, database_url):
        assert self.lock_active
        self.migrations.append((database_python, database_root, database_url))
        if self.migration_exit == 0:
            set_current_schema(self.database)
            if self.post_migration_mutation is not None:
                self.post_migration_mutation(self.database)
        return self.migration_exit


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    repo = tmp_path / "checkout"
    workspace = tmp_path / "external" / "school-demo"
    database_root = repo / "11_database"
    mysql_bin = workspace / "vendor"
    data_directory = workspace / "mysql-data"
    (database_root / "migrations" / "versions").mkdir(parents=True)
    python = database_root / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"synthetic interpreter marker")
    (database_root / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    (
        database_root
        / "migrations"
        / "versions"
        / f"{migration.CURRENT_SCHOOL_REVISION}_school_feedback_publication.py"
    ).write_text("# synthetic revision marker\n", encoding="utf-8")
    mysql_bin.mkdir(parents=True)
    executable = mysql_bin / "mysqld.exe"
    executable.write_bytes(b"synthetic executable marker")
    (data_directory / "mysql").mkdir(parents=True)
    (data_directory / "auto.cnf").write_text("synthetic", encoding="utf-8")
    (data_directory / "ibdata1").write_bytes(b"synthetic")
    workspace.mkdir(parents=True, exist_ok=True)
    parent_created = datetime.now(UTC) - timedelta(seconds=60)
    marker = {
        "schema_version": "psynova.synthetic-workspace.v1",
        "project": "StudentMentalHealthAI",
        "workspace_id": WORKSPACE_ID,
        "state": "READY_FOR_MIGRATION",
        "host": "127.0.0.1",
        "port": PORT,
        "database": "smhai_school_demo",
        "synthetic_only": True,
        "data_directory": str(data_directory),
        "executable": str(executable),
        "parent_pid": 7001,
        "parent_creation_time": parent_created.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z"),
    }
    (workspace / "workspace.json").write_text(json.dumps(marker), encoding="utf-8")
    (workspace / "database.private.dpapi").write_bytes(b"synthetic sealed marker")
    database = FakeDatabase(data_directory)
    trusted_database_root = Path(__file__).resolve().parents[2] / "11_database"
    expected_schema = migration._trusted_current_schema(trusted_database_root)
    monkeypatch.setattr(
        migration, "_trusted_current_schema", lambda _root: expected_schema
    )
    operations = FakeOperations(marker, database)
    database.expected_schema = expected_schema
    settings = {
        "DB_USER": "psynova_builder",
        "DB_PASSWORD": BUILDER_PASSWORD,
        "DB_HOST": "127.0.0.1",
        "DB_PORT": str(PORT),
        "DB_NAME": "smhai_school_demo",
    }
    reader_calls = []
    private_values = []

    def private_reader(path):
        reader_calls.append(path)
        private = dict(settings)
        private["root_password"] = "b" * 64
        private_values.append(private)
        return private

    service = migration.SchoolWorkspaceMigrator(
        repo,
        operations,
        private_reader=private_reader,
        lock_factory=operations.workspace_lock,
    )
    service.private_values = private_values
    return (
        repo,
        workspace,
        marker,
        database,
        operations,
        service,
        settings,
        reader_calls,
    )


def test_plan_is_read_only_and_does_not_decrypt_or_connect(prepared):
    _repo, workspace, _marker, _db, ops, service, _settings, reads = prepared
    result = service.plan(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)
    assert result["status"] == "PLAN_ONLY"
    assert result["schema_state"] == "NOT_INSPECTED"
    assert result["side_effects"] == []
    assert reads == []
    assert ops.connects == 0
    assert ops.migrations == []
    assert ops.verified == []


def test_source_database_port_is_never_a_migration_target(prepared):
    _repo, workspace, _marker, _db, ops, service, _settings, reads = prepared

    with pytest.raises(
        migration.MigrationError, match="SOURCE_WORKSPACE_PORT_NOT_ALLOWED"
    ):
        service.upgrade(workspace, expected_port=resume.PORT, workspace_id=WORKSPACE_ID)

    assert reads == []
    assert ops.connects == 0
    assert ops.migrations == []


def test_registered_source_workspace_path_is_never_a_migration_target(prepared):
    _repo, _workspace, _marker, _db, ops, service, _settings, reads = prepared
    with pytest.raises(
        migration.MigrationError, match="SOURCE_WORKSPACE_PATH_NOT_ALLOWED"
    ):
        service.plan(
            resume.DEFAULT_WORKSPACE,
            expected_port=PORT,
            workspace_id=WORKSPACE_ID,
        )

    assert reads == []
    assert ops.connects == 0
    assert ops.migrations == []


def test_empty_owned_schema_migrates_only_to_pinned_revision(prepared):
    _repo, workspace, _marker, db, ops, service, _settings, _reads = prepared
    result = service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)
    assert result["status"] == "MIGRATED"
    assert result["revision"] == "20261013_0010"
    assert ops.migrations[0][2].startswith("mysql+aiomysql://psynova_builder:")
    assert ops.migrations[0][2].endswith(
        "@127.0.0.1:3315/smhai_school_demo?charset=utf8mb4"
    )
    assert db.revisions == [migration.CURRENT_SCHOOL_REVISION]
    assert ops.connects == 2
    assert service.private_values == [{}]
    assert not ops.lock_active
    assert ops.lock_acquisitions == 1


def test_competing_workspace_upgrade_lock_fails_before_secret_or_database_access(
    prepared,
):
    _repo, workspace, _marker, _db, ops, service, _settings, reads = prepared
    ops.lock_busy = True
    with pytest.raises(migration.MigrationError) as exc:
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)
    assert exc.value.code == "WORKSPACE_LOCK_UNAVAILABLE"
    assert reads == []
    assert ops.connects == 0
    assert ops.migrations == []
    assert not ops.lock_active


def test_lock_release_failure_after_migration_is_partial(prepared):
    _repo, workspace, _marker, db, ops, service, _settings, reads = prepared
    ops.lock_exit_error = True

    with pytest.raises(migration.MigrationError) as exc:
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)

    assert exc.value.code == "WORKSPACE_LOCK_RELEASE_FAILED"
    assert exc.value.partial is True
    assert len(ops.migrations) == 1
    assert db.revisions == [migration.CURRENT_SCHOOL_REVISION]
    assert len(reads) == 1
    assert not ops.lock_active


def test_lock_release_failure_preserves_original_partial_migration_error(prepared):
    _repo, workspace, _marker, _db, ops, service, _settings, _reads = prepared
    ops.lock_exit_error = True
    ops.migration_exit = 1

    with pytest.raises(migration.MigrationError) as exc:
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)

    assert exc.value.code == "MIGRATION_FAILED"
    assert exc.value.partial is True
    assert len(ops.migrations) == 1
    assert not ops.lock_active


def test_lock_release_failure_without_ddl_is_blocked_not_partial(prepared):
    _repo, workspace, _marker, db, ops, service, _settings, _reads = prepared
    set_current_schema(db)
    ops.lock_exit_error = True

    with pytest.raises(migration.MigrationError) as exc:
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)

    assert exc.value.code == "WORKSPACE_LOCK_RELEASE_FAILED"
    assert exc.value.partial is False
    assert ops.migrations == []
    assert not ops.lock_active


def test_guardian_change_after_ddl_is_reported_as_partial(prepared):
    _repo, workspace, _marker, db, ops, service, _settings, _reads = prepared
    ops.guardian_fail_on_call = 3

    with pytest.raises(migration.MigrationError) as exc:
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)

    assert exc.value.code == "GUARDIAN_VERIFICATION_FAILED"
    assert exc.value.partial is True
    assert db.revisions == [migration.CURRENT_SCHOOL_REVISION]
    assert len(ops.migrations) == 1
    assert ops.connects == 1
    assert not ops.lock_active
    assert service.private_values == [{}]


def test_exact_current_schema_is_read_only(prepared):
    _repo, workspace, _marker, db, ops, service, _settings, _reads = prepared
    set_current_schema(db)
    result = service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)
    assert result["status"] == "ALREADY_CURRENT"
    assert result["side_effects"] == []
    assert ops.migrations == []


def test_legacy_check_names_are_deterministic_mysql_compiler_outputs():
    first = legacy_school_check_names()
    second = legacy_school_check_names()
    assert first == second
    assert first["account_school_memberships"] == {
        "ck_account_school_memberships_ck_account_school_membersh_d859": "ck_account_school_memberships_status_allowed",
        "ck_account_school_memberships_ck_account_school_membersh_11e7": "ck_account_school_memberships_validity_ordered",
    }
    assert all(len(name) <= 64 for aliases in first.values() for name in aliases)


def test_legacy_check_name_allowlist_is_present_in_trusted_migrations():
    root = Path(__file__).resolve().parents[2]
    sources = "\n".join(
        (root / "11_database" / "migrations" / "versions" / name).read_text(
            encoding="utf-8"
        )
        for name in (
            "20261011_0003_school_membership_context.py",
            "20261011_0004_school_seed_provenance.py",
        )
    )
    for declarations in LEGACY_CHECK_NAME_DECLARATIONS.values():
        for declaration in declarations:
            assert declaration in sources


def test_current_accepts_only_source_derived_legacy_check_names(prepared):
    _repo, workspace, _marker, db, ops, service, _settings, _reads = prepared
    set_current_schema(db)
    aliases = legacy_school_check_names()
    alias_by_canonical = {
        table: {canonical: legacy for legacy, canonical in values.items()}
        for table, values in aliases.items()
    }
    for table_name, contract in db.schema.items():
        if table_name not in alias_by_canonical:
            continue
        assert set(alias_by_canonical[table_name]) == {
            name
            for name, _expression, _enforced in db.expected_schema[table_name]["checks"]
        }
        converted = set()
        for index, (name, expression, enforced) in enumerate(
            sorted(contract["checks"])
        ):
            legacy_name = alias_by_canonical[table_name].get(name)
            physical_name = legacy_name if index % 2 == 0 and legacy_name else name
            converted.add((physical_name, expression, enforced))
        contract["checks"] = converted

    result = service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)
    assert result["status"] == "ALREADY_CURRENT"
    assert ops.migrations == []


@pytest.mark.parametrize(
    "drift", ["unknown_name", "case", "duplicate", "expression", "unenforced"]
)
def test_legacy_check_compatibility_rejects_unknown_duplicate_or_semantic_drift(
    prepared, drift
):
    _repo, workspace, _marker, db, ops, service, _settings, _reads = prepared
    set_current_schema(db)
    table_name = "account_school_memberships"
    contract = db.schema[table_name]
    name, expression, enforced = next(
        item for item in contract["checks"] if item[0].endswith("status_allowed")
    )
    legacy_name = next(
        legacy
        for legacy, canonical in legacy_school_check_names()[table_name].items()
        if canonical == name
    )
    contract["checks"].remove((name, expression, enforced))
    if drift == "unknown_name":
        contract["checks"].add(("ck_untrusted_status_allowed", expression, enforced))
    elif drift == "case":
        contract["checks"].add((legacy_name.upper(), expression, enforced))
    elif drift == "duplicate":
        contract["checks"].add((name, expression, enforced))
        contract["checks"].add((legacy_name, expression, enforced))
    elif drift == "expression":
        contract["checks"].add(
            (legacy_name, expression.replace("REVOKED", "DISABLED"), enforced)
        )
    else:
        contract["checks"].add((legacy_name, expression, False))

    with pytest.raises(migration.MigrationError, match="CURRENT_SCHEMA_DRIFT"):
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)
    assert ops.migrations == []


@pytest.mark.parametrize(
    "drift",
    [
        "column",
        "table",
        "view",
        "routine",
        "type",
        "nullability",
        "auto_increment",
        "primary_key",
        "unique",
        "foreign_key",
        "foreign_key_action",
        "foreign_schema",
        "check",
        "index",
        "extra_index",
    ],
)
def test_current_revision_with_table_or_column_drift_fails_closed(prepared, drift):
    _repo, workspace, _marker, db, ops, service, _settings, _reads = prepared
    set_current_schema(db)
    if drift == "column":
        db.schema["accounts"]["columns"]["unexpected_column"] = {
            "type": "INT",
            "nullable": True,
            "auto_increment": False,
        }
        db.columns["accounts"].append("unexpected_column")
    elif drift == "table":
        db.tables.append("unexpected_table")
        db.columns["unexpected_table"] = ["id"]
        db.schema["unexpected_table"] = {}
    elif drift == "view":
        db.table_type_overrides["accounts"] = "VIEW"
    elif drift == "routine":
        db.other_objects = ["unexpected_routine"]
    elif drift == "type":
        _mutate_first(db, "columns", lambda value: value.update(type="VARCHAR(2)"))
    elif drift == "nullability":
        _mutate_first(
            db, "columns", lambda value: value.update(nullable=not value["nullable"])
        )
    elif drift == "auto_increment":
        column = next(
            value
            for contract in db.schema.values()
            for value in contract.get("columns", {}).values()
            if value["auto_increment"]
        )
        column["auto_increment"] = False
    elif drift == "primary_key":
        next(
            contract for contract in db.schema.values() if contract.get("primary_key")
        )["primary_key"] = ()
    elif drift == "unique":
        _mutate_first(db, "uniques", lambda value: value.pop())
    elif drift == "foreign_key":
        _mutate_first(db, "foreign_keys", lambda value: value.pop())
    elif drift == "foreign_key_action":
        table = next(
            contract for contract in db.schema.values() if contract.get("foreign_keys")
        )
        table["foreign_keys"] = {
            (*constraint[:4], "CASCADE", constraint[5])
            for constraint in table["foreign_keys"]
        }
    elif drift == "foreign_schema":
        db.foreign_schema_override = "other_database"
    elif drift == "check":
        _mutate_first(db, "checks", lambda value: value.pop())
    elif drift == "index":
        _mutate_first(db, "indexes", lambda value: value.pop())
    elif drift == "extra_index":
        db.schema["accounts"]["indexes"].add(("unexpected_idx", ("id",), False))
    with pytest.raises(migration.MigrationError, match="CURRENT_SCHEMA_DRIFT"):
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)
    assert ops.migrations == []


def test_current_rejects_missing_review_scope_unique(prepared):
    _repo, workspace, _marker, db, ops, service, _settings, _reads = prepared
    set_current_schema(db)
    db.schema["school_professional_review_cases"]["uniques"].remove(
        (
            "school_professional_review_feedback_scope_unique",
            (
                "id",
                "school_id",
                "task_id",
                "class_id",
                "task_enrollment_id",
                "subject_id",
                "assessment_session_id",
            ),
        )
    )

    with pytest.raises(migration.MigrationError, match="CURRENT_SCHEMA_DRIFT"):
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)
    assert ops.migrations == []


def test_current_ignores_only_known_mysql_backing_indexes(prepared):
    _repo, workspace, _marker, db, ops, service, _settings, _reads = prepared
    set_current_schema(db)
    table_name, contract = next(
        (name, item)
        for name, item in db.schema.items()
        if item["uniques"] and item["foreign_keys"]
    )
    unique_name, unique_columns = next(iter(contract["uniques"]))
    foreign_name, foreign_columns, *_rest = next(iter(contract["foreign_keys"]))
    assert (unique_name, unique_columns, True) not in contract["indexes"]
    assert (foreign_name, foreign_columns, False) not in contract["indexes"]
    contract["indexes"].add((unique_name, unique_columns, True))
    contract["indexes"].add((foreign_name, foreign_columns, False))
    contract["indexes"].add(("primary", contract["primary_key"], True))

    result = service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)
    assert result["status"] == "ALREADY_CURRENT"
    assert ops.migrations == []
    assert table_name in db.schema


def test_post_migration_uses_full_metadata_contract(prepared):
    _repo, workspace, _marker, db, ops, service, _settings, _reads = prepared

    def remove_current_unique(database):
        database.schema["school_professional_review_cases"]["uniques"].clear()

    ops.post_migration_mutation = remove_current_unique
    with pytest.raises(migration.MigrationError) as exc:
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)

    assert exc.value.code == "POST_MIGRATION_CHECK_FAILED"
    assert exc.value.partial is True
    assert len(ops.migrations) == 1
    assert db.revisions == [migration.CURRENT_SCHOOL_REVISION]


def _mutate_first(database, part, mutate):
    for contract in database.schema.values():
        value = contract.get(part)
        if part == "columns" and value:
            mutate(next(iter(value.values())))
            return
        if part == "primary_key" and value:
            mutate(value)
            return
        if value:
            mutate(value)
            return
    pytest.fail(f"No fixture metadata available for {part}")


def test_metadata_normalizers_preserve_string_literal_semantics():
    assert migration._normalized_type(
        FakeType("ENUM('created')"), None
    ) != migration._normalized_type(FakeType("ENUM('CREATED')"), None)
    assert migration._normalize_check_sql(
        "status IN ('created')"
    ) != migration._normalize_check_sql("((`status` in (_utf8mb4'CREATED')))")
    assert migration._normalize_check_sql(
        "status IN ('CREATED')"
    ) == migration._normalize_check_sql("((`status` in (_utf8mb4'CREATED')))")
    assert migration._normalized_type(
        FakeType("BOOL"), None
    ) == migration._normalized_type(FakeType("TINYINT(1)"), None)
    assert migration._normalized_type(
        FakeType("INT(11)"), None
    ) == migration._normalized_type(FakeType("INTEGER"), None)
    assert (
        migration._normalized_type(FakeType("VARCHAR(36) COLLATE ASCII_BIN"), None)
        == "VARCHAR(36)"
    )


def test_check_normalizer_matches_mysql_metadata_transport_and_parentheses():
    expected = (
        "(status = 'DRAFT' AND published_at IS NULL AND revoked_at IS NULL) OR "
        "(status = 'PUBLISHED' AND published_at IS NOT NULL AND revoked_at IS NULL) OR "
        "(status = 'REVOKED' AND published_at IS NOT NULL AND revoked_at IS NOT NULL)"
    )
    actual = (
        "((((`status` = _utf8mb4\\'DRAFT\\') AND (`published_at` IS NULL) "
        "AND (`revoked_at` IS NULL))) OR (((`status` = _utf8mb4\\'PUBLISHED\\') "
        "AND (`published_at` IS NOT NULL) AND (`revoked_at` IS NULL))) OR "
        "(((`status` = _utf8mb4\\'REVOKED\\') AND (`published_at` IS NOT NULL) "
        "AND (`revoked_at` IS NOT NULL))))"
    )
    assert migration._normalize_check_sql(actual) == migration._normalize_check_sql(
        expected
    )


@pytest.mark.parametrize(
    "left,right",
    [
        ("level = 'L3'", "level = _ascii\\'l3\\'"),
        (
            "left_flag = 1 OR right_flag = 1 AND enabled = 1",
            "(left_flag = 1 OR right_flag = 1) AND enabled = 1",
        ),
        ("row_count BETWEEN 1 AND 100", "row_count >= 1 AND row_count <= 100"),
        ("value = 1", "value <> 1"),
    ],
)
def test_check_normalizer_preserves_literals_operators_and_precedence(left, right):
    assert migration._normalize_check_sql(left) != migration._normalize_check_sql(right)


def test_check_normalizer_rejects_unknown_expression_syntax():
    with pytest.raises(ValueError, match="unsupported CHECK syntax"):
        migration._normalize_check_sql("status IN (SELECT status FROM roles)")


def test_current_schema_rejects_explicit_collation_drift(prepared):
    _repo, workspace, _marker, db, ops, service, _settings, _reads = prepared
    set_current_schema(db)
    expected_collation = db.schema["accounts"]["columns"]["public_id"]["collation"]
    assert expected_collation == "ascii_bin"
    db.schema["accounts"]["columns"]["public_id"]["collation"] = "ascii_general_ci"

    with pytest.raises(migration.MigrationError) as exc:
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)

    assert exc.value.code == "CURRENT_SCHEMA_DRIFT"
    assert ops.migrations == []


def test_empty_tables_with_untracked_routine_is_not_a_fresh_schema(prepared):
    _repo, workspace, _marker, db, ops, service, _settings, _reads = prepared
    db.other_objects = ["unexpected_routine"]
    with pytest.raises(migration.MigrationError, match="NONEMPTY_UNKNOWN_SCHEMA"):
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)
    assert ops.migrations == []


def test_empty_schema_with_runtime_auth_or_seed_artifacts_is_rejected(prepared):
    _repo, workspace, _marker, _db, ops, service, _settings, _reads = prepared
    (workspace / "school-accounts.private.dpapi").write_bytes(b"synthetic")
    with pytest.raises(migration.MigrationError, match="WORKSPACE_ALREADY_PREPARED"):
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)
    assert ops.migrations == []


@pytest.mark.parametrize(
    "tables,revisions,expected_code",
    [
        (
            ["database_alembic_version", "accounts"],
            ["20261011_0005"],
            "UNSUPPORTED_SCHEMA_REVISION",
        ),
        (["database_alembic_version"], [], "PARTIAL_SCHEMA"),
        (["unknown_table"], [], "NONEMPTY_UNKNOWN_SCHEMA"),
    ],
)
def test_old_partial_or_unknown_schema_fails_closed(
    prepared, tables, revisions, expected_code
):
    _repo, workspace, _marker, db, ops, service, _settings, _reads = prepared
    db.tables = tables
    db.columns = {
        table: ["version_num"] if table == "database_alembic_version" else ["id"]
        for table in tables
    }
    db.revisions = revisions
    with pytest.raises(migration.MigrationError) as exc:
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)
    assert exc.value.code == expected_code
    assert ops.migrations == []


@pytest.mark.parametrize(
    "field,value,expected_code",
    [
        ("DB_PORT", "3316", "SEALED_BUILDER_TARGET_MISMATCH"),
        ("DB_NAME", "other_schema", "SEALED_BUILDER_TARGET_MISMATCH"),
        ("DB_HOST", "0.0.0.0", "SEALED_BUILDER_TARGET_MISMATCH"),
        ("DB_USER", "root", "SEALED_BUILDER_TARGET_MISMATCH"),
        ("DB_PASSWORD", "not-a-generated-password", "SEALED_BUILDER_TARGET_MISMATCH"),
    ],
)
def test_sealed_builder_settings_must_match_workspace(
    prepared, field, value, expected_code
):
    _repo, workspace, _marker, _db, ops, service, settings, reads = prepared
    settings[field] = value
    with pytest.raises(migration.MigrationError) as exc:
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)
    assert exc.value.code == expected_code
    assert ops.connects == 0
    assert ops.migrations == []
    assert len(reads) == 1


@pytest.mark.parametrize(
    "tamper", ["global_privilege", "grant_option", "role", "missing_role"]
)
def test_builder_grants_must_be_exact_single_schema_scope(prepared, tamper):
    _repo, workspace, _marker, db, ops, service, _settings, _reads = prepared
    if tamper == "global_privilege":
        db.grants.append("GRANT SELECT ON *.* TO 'psynova_builder'@'127.0.0.1'")
    elif tamper == "grant_option":
        db.grants[1] = db.grants[1].replace(" TO ", " WITH GRANT OPTION TO ", 1)
    elif tamper == "missing_role":
        db.current_role = None
    else:
        db.current_role = "`unexpected_role`@`%`"
    with pytest.raises(migration.MigrationError, match="BUILDER_PRIVILEGES_INVALID"):
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)
    assert ops.migrations == []


@pytest.mark.parametrize("mismatch", ["port", "datadir", "database"])
def test_connected_mysql_identity_must_match_marker(prepared, mismatch):
    _repo, workspace, _marker, db, ops, service, _settings, _reads = prepared
    if mismatch == "port":
        db.port += 1
    elif mismatch == "datadir":
        db.datadir = str(workspace)
    else:
        db.name = "other_schema"
    with pytest.raises(migration.MigrationError) as exc:
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)
    assert exc.value.code == "CONNECTED_DATABASE_IDENTITY_MISMATCH"
    assert ops.migrations == []


def test_marker_identity_mismatch_fails_before_sealed_read(prepared):
    _repo, workspace, _marker, _db, ops, service, _settings, reads = prepared
    with pytest.raises(migration.MigrationError, match="WORKSPACE_ID_MISMATCH"):
        service.upgrade(workspace, expected_port=PORT, workspace_id="c" * 32)
    assert reads == []
    assert ops.connects == 0


@pytest.mark.parametrize(
    "tamper",
    ["executable", "creation", "argv", "argv_order", "listener", "acl", "guardian"],
)
def test_guardian_or_listener_tampering_blocks_migration(prepared, tamper):
    _repo, workspace, marker, _db, ops, service, _settings, reads = prepared
    if tamper == "executable":
        ops.process_override = {
            "ProcessId": marker["parent_pid"],
            "ExecutablePath": str(workspace / "other.exe"),
            "CreationUtc": marker["parent_creation_time"],
            "CommandLine": subprocess.list2cmdline(
                resume.guardian_arguments(
                    Path(marker["executable"]),
                    workspace,
                    Path(marker["data_directory"]),
                    PORT,
                )
            ),
        }
    elif tamper == "creation":
        ops.process_override = {
            "ProcessId": marker["parent_pid"],
            "ExecutablePath": marker["executable"],
            "CreationUtc": "2026-10-13T00:00:02.000000Z",
            "CommandLine": subprocess.list2cmdline(
                resume.guardian_arguments(
                    Path(marker["executable"]),
                    workspace,
                    Path(marker["data_directory"]),
                    PORT,
                )
            ),
        }
    elif tamper == "argv":
        ops.process_override = {
            **ops.inspect_process(marker["parent_pid"]),
            "CommandLine": "mysqld.exe --port=3306",
        }
    elif tamper == "argv_order":
        expected = resume.guardian_arguments(
            Path(marker["executable"]),
            workspace,
            Path(marker["data_directory"]),
            PORT,
        )
        reordered = list(expected)
        reordered[1], reordered[2] = reordered[2], reordered[1]
        ops.process_override = {
            **ops.inspect_process(marker["parent_pid"]),
            "CommandLine": subprocess.list2cmdline(reordered),
        }
    elif tamper == "listener":
        ops.listener_owner = marker["parent_pid"] + 1
    elif tamper == "acl":
        ops.acl_valid = False
    else:
        ops.process_valid = False
    with pytest.raises(migration.MigrationError):
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)
    assert reads == []
    assert ops.connects == 0
    assert ops.migrations == []


def _install_direct_child_listener(ops, marker, pid=7002):
    guardian = ops.inspect_process(marker["parent_pid"])
    child = {
        **guardian,
        "ProcessId": pid,
        "ParentProcessId": marker["parent_pid"],
        "CreationUtc": (datetime.now(UTC) - timedelta(seconds=30))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
    }
    ops.child_processes[pid] = child
    ops.listener_owner = pid
    return child


def test_exact_direct_guardian_child_may_own_loopback_listener(prepared):
    _repo, workspace, marker, db, ops, service, _settings, reads = prepared
    _install_direct_child_listener(ops, marker)

    result = service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)

    assert result["status"] == "MIGRATED"
    assert ops.connects == 2
    assert len(ops.migrations) == 1
    assert len(reads) == 1
    assert db.revisions == [migration.CURRENT_SCHOOL_REVISION]


@pytest.mark.parametrize(
    "tamper",
    ["parent", "executable", "argv", "stale_creation", "future_creation", "pid"],
)
def test_unverified_direct_child_listener_fails_closed(prepared, tamper):
    _repo, workspace, marker, _db, ops, service, _settings, reads = prepared
    child = _install_direct_child_listener(ops, marker)
    if tamper == "parent":
        child["ParentProcessId"] += 1
    elif tamper == "executable":
        child["ExecutablePath"] = sys.executable
    elif tamper == "argv":
        child["CommandLine"] += " --unexpected"
    elif tamper == "stale_creation":
        child["CreationUtc"] = (
            (
                datetime.fromisoformat(
                    marker["parent_creation_time"].replace("Z", "+00:00")
                )
                - timedelta(seconds=1)
            )
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
    elif tamper == "future_creation":
        child["CreationUtc"] = (
            (datetime.now(UTC) + timedelta(minutes=1))
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
    else:
        child["ProcessId"] += 1

    with pytest.raises(migration.MigrationError):
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)

    assert reads == []
    assert ops.connects == 0
    assert ops.migrations == []


def test_direct_child_identity_must_remain_consistent_during_listener_check(prepared):
    _repo, workspace, marker, _db, ops, service, _settings, reads = prepared
    pid = 7002
    child = _install_direct_child_listener(ops, marker, pid)
    changed = {
        **child,
        "CreationUtc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    ops.process_sequences[pid] = [child, child, changed]

    with pytest.raises(migration.MigrationError, match="LISTENER_PROCESS_CHANGED"):
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)

    assert reads == []
    assert ops.connects == 0
    assert ops.migrations == []


def test_process_inspection_returns_parent_identity(monkeypatch):
    observed = {}

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed["pid"] = kwargs["env"]["PSYNOVA_MIGRATION_PID"]
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "ProcessId": 7002,
                    "ParentProcessId": 7001,
                    "ExecutablePath": "C:\\synthetic\\mysqld.exe",
                    "CommandLine": "C:\\synthetic\\mysqld.exe --port=3315",
                    "CreationUtc": "2026-10-13T00:00:02.0000000Z",
                }
            ).encode("utf-8")
        )

    monkeypatch.setattr(migration.subprocess, "run", fake_run)
    result = migration.MigrationOperations().inspect_process(7002)

    assert result["ParentProcessId"] == 7001
    assert observed["pid"] == "7002"
    assert "ParentProcessId = $p.ParentProcessId" in observed["argv"][3]


def test_process_inspection_rejects_non_utf8_metadata_without_leaking_output(
    monkeypatch,
):
    monkeypatch.setattr(
        migration.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=b"\xffprivate"),
    )

    with pytest.raises(migration.MigrationError) as exc:
        migration.MigrationOperations().inspect_process(7002)

    assert exc.value.code == "PROCESS_IDENTITY_UNAVAILABLE"
    assert str(exc.value) == "PROCESS_IDENTITY_UNAVAILABLE"


def test_metadata_powershell_uses_redacted_environment_for_all_identity_checks(
    prepared, monkeypatch
):
    _repo, workspace, marker, _db, _ops, _service, _settings, _reads = prepared
    secret = "syntheticsecret-not-for-child"
    source_environment = {
        "PATH": "synthetic-path",
        "SystemRoot": "synthetic-system-root",
        "WINDIR": "synthetic-windir",
        "TEMP": "synthetic-temp",
        "TMP": "synthetic-tmp",
        "USERNAME": "synthetic-user",
        "USERPROFILE": "synthetic-profile",
        "LOCALAPPDATA": "synthetic-localappdata",
        "DATABASE_URL": secret,
        "DB_PASSWORD": secret,
        "MYSQL_PWD": secret,
        "SMHAI_TOKEN": secret,
        "VITE_SECRET": secret,
        "HF_TOKEN": secret,
        "OPENAI_API_KEY": secret,
        "PYTHONPATH": secret,
        "PYTHONHOME": secret,
        "NODE_OPTIONS": secret,
        "NODE_PATH": secret,
        "HTTPS_PROXY": secret,
        "PSYNOVA_RESUME_PID": secret,
    }
    monkeypatch.setattr(migration.os, "environ", source_environment)
    observed = []
    expected_argv = resume.guardian_arguments(
        Path(marker["executable"]),
        Path(marker["data_directory"]).parent,
        Path(marker["data_directory"]),
        marker["port"],
    )
    process = {
        "ProcessId": marker["parent_pid"],
        "ParentProcessId": 1,
        "ExecutablePath": marker["executable"],
        "CommandLine": subprocess.list2cmdline(expected_argv),
        "CreationUtc": marker["parent_creation_time"],
    }

    def fake_run(argv, **kwargs):
        environment = kwargs["env"]
        observed.append((argv, dict(environment)))
        assert secret not in repr(environment)
        if "PSYNOVA_MIGRATION_WORKSPACE" in environment:
            output = "PRIVATE"
        elif "PSYNOVA_MIGRATION_PID" in environment:
            output = json.dumps(process)
        else:
            output = json.dumps(
                [
                    {
                        "OwningProcess": marker["parent_pid"],
                        "LocalAddress": "127.0.0.1",
                        "LocalPort": marker["port"],
                    }
                ]
            )
        return SimpleNamespace(stdout=output.encode("utf-8"))

    monkeypatch.setattr(migration.subprocess, "run", fake_run)
    ops = migration.MigrationOperations()
    ops.verify_acl(workspace)
    assert ops.inspect_process(marker["parent_pid"]) == process
    assert ops.listeners(marker["port"])[0]["LocalPort"] == marker["port"]
    ops.verify_running_process(marker)

    expected_base = {
        "PATH",
        "SystemRoot",
        "WINDIR",
        "TEMP",
        "TMP",
        "USERNAME",
        "USERPROFILE",
        "LOCALAPPDATA",
    }
    assert len(observed) == 5
    assert {"PSYNOVA_MIGRATION_WORKSPACE"} <= set(observed[0][1])
    assert {"PSYNOVA_MIGRATION_PID"} <= set(observed[1][1])
    assert {"PSYNOVA_MIGRATION_PORT"} <= set(observed[2][1])
    assert "PSYNOVA_MIGRATION_PID" in observed[-2][1]
    assert "PSYNOVA_MIGRATION_PORT" in observed[-1][1]
    for _argv, environment in observed:
        assert (
            set(environment)
            - {
                "PSYNOVA_MIGRATION_WORKSPACE",
                "PSYNOVA_MIGRATION_PID",
                "PSYNOVA_MIGRATION_PORT",
            }
            == expected_base
        )
        assert all("syntheticsecret" not in value for value in environment.values())


def test_workspace_reparse_path_is_rejected(prepared, monkeypatch):
    _repo, workspace, _marker, _db, ops, service, _settings, reads = prepared
    original = resume._reject_reparse_path

    def fake_reject(path):
        if Path(path) == workspace:
            raise resume.ResumeError("synthetic reparse marker")
        return original(path)

    monkeypatch.setattr(resume, "_reject_reparse_path", fake_reject)
    with pytest.raises(migration.MigrationError, match="WORKSPACE_INVALID"):
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)
    assert reads == []
    assert ops.connects == 0


def test_migration_failure_is_partial_and_preserves_workspace(prepared):
    _repo, workspace, _marker, db, ops, service, _settings, _reads = prepared
    ops.migration_exit = 1
    with pytest.raises(migration.MigrationError) as exc:
        service.upgrade(workspace, expected_port=PORT, workspace_id=WORKSPACE_ID)
    assert exc.value.code == "MIGRATION_FAILED"
    assert exc.value.partial is True
    assert not db.tables
    assert (
        workspace / "database.private.dpapi"
    ).read_bytes() == b"synthetic sealed marker"


def test_child_environment_and_argv_never_contain_builder_secret(prepared, monkeypatch):
    repo, _workspace, _marker, _db, _ops, _service, _settings, _reads = prepared
    observed = {}

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed["env"] = kwargs["env"]
        observed["capture_output"] = kwargs["capture_output"]
        observed["text"] = kwargs["text"]
        observed["stdin"] = kwargs["stdin"]
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(migration.subprocess, "run", fake_run)
    monkeypatch.setattr(
        migration.os,
        "environ",
        {
            "PATH": "synthetic-path",
            "SystemRoot": "synthetic-system-root",
            "USERNAME": "synthetic-user",
            "DATABASE_URL": "unrelated-url-secret",
            "MYSQL_PWD": "unrelated-password-secret",
            "PYTHONPATH": "synthetic-pythonpath",
            "SMHAI_SECRET": "unrelated-secret",
            "HTTPS_PROXY": "synthetic-proxy",
        },
    )
    ops = migration.MigrationOperations()
    database_root = repo / "11_database"
    result = ops.run_alembic(
        database_root / ".venv" / "Scripts" / "python.exe",
        database_root,
        "mysql+aiomysql://psynova_builder:"
        + BUILDER_PASSWORD
        + "@127.0.0.1:3315/smhai_school_demo?charset=utf8mb4",
    )
    assert result == 0
    assert observed["argv"][-2:] == ["upgrade", "20261013_0010"]
    assert BUILDER_PASSWORD not in " ".join(observed["argv"])
    assert observed["env"]["DATABASE_URL"].endswith(
        "@127.0.0.1:3315/smhai_school_demo?charset=utf8mb4"
    )
    assert set(observed["env"]) == {
        "PATH",
        "SystemRoot",
        "USERNAME",
        "DATABASE_URL",
    }
    assert observed["capture_output"] is True
    assert observed["text"] is False
    assert observed["stdin"] is subprocess.DEVNULL


def test_alembic_timeout_is_partial_without_retry(prepared, monkeypatch):
    repo, _workspace, _marker, _db, _ops, _service, _settings, _reads = prepared
    calls = []

    def timeout_once(*_args, **_kwargs):
        calls.append("called")
        raise subprocess.TimeoutExpired("alembic", migration.MIGRATION_TIMEOUT_SECONDS)

    monkeypatch.setattr(migration.subprocess, "run", timeout_once)
    database_root = repo / "11_database"
    ops = migration.MigrationOperations()

    with pytest.raises(migration.MigrationError) as exc:
        ops.run_alembic(
            database_root / ".venv" / "Scripts" / "python.exe",
            database_root,
            "mysql+aiomysql://psynova_builder:<synthetic>@127.0.0.1:3315/"
            "smhai_school_demo?charset=utf8mb4",
        )

    assert exc.value.code == "MIGRATION_TIMEOUT"
    assert exc.value.partial is True
    assert calls == ["called"]


def test_console_result_never_contains_secret_values(capsys, monkeypatch, prepared):
    _repo, workspace, _marker, _db, _ops, _service, _settings, _reads = prepared
    monkeypatch.setattr(
        migration,
        "SchoolWorkspaceMigrator",
        lambda _repo: SimpleNamespace(
            upgrade=lambda *_args, **_kwargs: {
                "status": "MIGRATED",
                "revision": "20261013_0010",
            }
        ),
    )
    rc = migration.main(
        [
            "upgrade",
            "--workspace",
            str(workspace),
            "--expected-port",
            str(PORT),
            "--workspace-id",
            WORKSPACE_ID,
        ]
    )
    output = capsys.readouterr().out
    assert rc == 0
    assert BUILDER_PASSWORD not in output
    assert "DATABASE_URL" not in output
