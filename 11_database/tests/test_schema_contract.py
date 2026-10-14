from pathlib import Path

import pytest
from database_layer.base import Base
from database_layer.models import (  # noqa: F401
    Account,
    AccountRole,
    AccountSchoolMembership,
    AssessmentResponse,
    AssessmentResult,
    AssessmentSession,
    AuditEvent,
    AuthSession,
    ConsentRecord,
    IdempotencyRecord,
    MeasurementTask,
    MembershipRole,
    ReviewCase,
    ReviewEvent,
    Role,
    SafetyDecision,
    School,
    SchoolAccountBatch,
    SchoolAccountProvision,
    SchoolCatActivation,
    SchoolCatItemBank,
    SchoolCatItemBankVersion,
    SchoolCatPlan,
    SchoolCatPlanVersion,
    SchoolCatSessionBinding,
    SchoolCatTaskBinding,
    SchoolClass,
    SchoolClassStudent,
    SchoolClassTeacher,
    SchoolConversationSafetyCase,
    SchoolConversationSafetyEvent,
    SchoolFeedbackEvent,
    SchoolFeedbackRecord,
    SchoolPostAssessmentJob,
    SchoolProfessionalReviewCase,
    SchoolProfessionalReviewEvent,
    SchoolResearchFeedbackEvent,
    SchoolResearchFeedbackRecord,
    SchoolResearchReviewCase,
    SchoolResearchReviewEvent,
    SchoolTaskSpecialistAssignment,
    Subject,
    SubjectAccessGrant,
    SupportEvidence,
    SupportMessage,
    SupportRun,
    SupportSession,
    TaskEnrollment,
)
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable


def test_domain_table_count_and_explicit_mysql_defaults() -> None:
    assert len(Base.metadata.tables) == 57
    assert set(Base.metadata.tables) == {
        "accounts",
        "roles",
        "account_roles",
        "schools",
        "school_classes",
        "school_account_batches",
        "school_account_provisions",
        "school_class_students",
        "school_class_teachers",
        "measurement_tasks",
        "task_enrollments",
        "account_school_memberships",
        "membership_roles",
        "subjects",
        "subject_access_grants",
        "consent_records",
        "auth_sessions",
        "assessment_sessions",
        "assessment_responses",
        "assessment_results",
        "support_sessions",
        "support_messages",
        "support_runs",
        "support_evidence",
        "safety_decisions",
        "review_cases",
        "review_events",
        "school_task_specialist_assignments",
        "school_professional_review_cases",
        "school_professional_review_events",
        "school_feedback_records",
        "school_feedback_events",
        "school_post_assessment_jobs",
        "school_cat_item_banks",
        "school_cat_item_bank_versions",
        "school_cat_plans",
        "school_cat_plan_versions",
        "school_cat_activations",
        "school_cat_task_bindings",
        "school_cat_session_bindings",
        "school_research_profile_versions",
        "school_research_task_bindings",
        "school_research_sessions",
        "school_research_case_assignments",
        "school_research_cohorts",
        "school_research_cohort_batches",
        "school_research_cohort_assignments",
        "school_research_education_jobs",
        "school_research_review_cases",
        "school_research_review_events",
        "school_research_feedback_records",
        "school_research_feedback_events",
        "school_research_programme_candidates",
        "school_conversation_safety_cases",
        "school_conversation_safety_events",
        "idempotency_records",
        "audit_events",
    }
    for table in Base.metadata.tables.values():
        assert table.dialect_options["mysql"]["engine"] == "InnoDB"
        assert table.dialect_options["mysql"]["charset"] == "utf8mb4"
        assert table.dialect_options["mysql"]["collate"] == "utf8mb4_0900_ai_ci"
        CreateTable(table).compile(dialect=mysql.dialect())


def test_sensitive_columns_are_binary_and_raw_secret_columns_absent() -> None:
    forbidden = {"password", "session_token", "csrf_token", "client_ip", "ip_address"}
    for table in Base.metadata.tables.values():
        assert not forbidden.intersection(table.c.keys())

    encrypted_columns = {
        "assessment_responses.response_ciphertext",
        "assessment_results.payload_ciphertext",
        "support_messages.payload_ciphertext",
        "safety_decisions.detail_ciphertext",
        "review_cases.case_note_ciphertext",
        "review_events.note_ciphertext",
        "school_professional_review_cases.case_note_ciphertext",
        "school_conversation_safety_cases.review_note_ciphertext",
    }
    for dotted in encrypted_columns:
        table_name, column_name = dotted.split(".")
        column = Base.metadata.tables[table_name].c[column_name]
        assert column.type.python_type is bytes


def test_no_clinical_label_columns_and_no_universal_soft_delete() -> None:
    all_columns = {
        column.name for table in Base.metadata.tables.values() for column in table.columns
    }
    assert not {
        "depression_level",
        "suicide_risk_level",
        "diagnosis",
        "mental_disorder",
    }.intersection(all_columns)
    assert sum("deleted_at" in table.c for table in Base.metadata.tables.values()) == 0


def test_school_membership_and_legacy_scope_constraints_are_additive() -> None:
    memberships = Base.metadata.tables["account_school_memberships"]
    membership_roles = Base.metadata.tables["membership_roles"]
    schools = Base.metadata.tables["schools"]
    subjects = Base.metadata.tables["subjects"]
    grants = Base.metadata.tables["subject_access_grants"]
    sessions = Base.metadata.tables["auth_sessions"]

    assert subjects.c.school_id.nullable is True
    assert grants.c.school_id.nullable is True
    assert sessions.c.active_school_id.nullable is True
    assert sessions.c.active_membership_role_id.nullable is True
    assert schools.c.data_origin.nullable is False
    assert schools.c.provenance_ref.nullable is False
    assert isinstance(schools.c.provenance_ref.type, String)
    assert schools.c.provenance_ref.type.length == 48
    school_constraints = {
        constraint.name: str(getattr(constraint, "sqltext", ""))
        for constraint in schools.constraints
    }
    assert "'SYNTHETIC'" in school_constraints["ck_schools_data_origin_allowed"]
    assert "'PRODUCTION_PENDING'" in school_constraints["ck_schools_data_origin_allowed"]
    assert (
        school_constraints["ck_schools_provenance_ref_token"]
        == "provenance_ref IN ('SYNTHETIC_REF_AUTH_TENANT_FIXTURE_V1', "
        "'SYNTHETIC_REF_SCHOOL_SEED_RECIPE_V1')"
    )

    school_subject_fk = next(
        constraint
        for constraint in grants.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and tuple(element.parent.name for element in constraint.elements)
        == ("subject_id", "school_id")
    )
    assert tuple(element.target_fullname for element in school_subject_fk.elements) == (
        "subjects.id",
        "subjects.school_id",
    )
    principal_membership_fk = next(
        constraint
        for constraint in grants.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and tuple(element.parent.name for element in constraint.elements)
        == ("principal_account_id", "school_id")
    )
    assert tuple(element.target_fullname for element in principal_membership_fk.elements) == (
        "account_school_memberships.account_id",
        "account_school_memberships.school_id",
    )
    assert {"account_id", "school_id"}.issubset(memberships.c.keys())
    assert {"membership_id", "school_id", "role_code"}.issubset(membership_roles.c.keys())
    session_context_fk = next(
        constraint
        for constraint in sessions.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and tuple(element.parent.name for element in constraint.elements)
        == ("active_membership_role_id", "active_school_id")
    )
    assert tuple(element.target_fullname for element in session_context_fk.elements) == (
        "membership_roles.id",
        "membership_roles.school_id",
    )
    school_role_check = next(
        constraint
        for constraint in membership_roles.constraints
        if getattr(constraint, "name", None) == "ck_membership_roles_role_allowed"
    )
    assert isinstance(school_role_check, CheckConstraint)
    assert "reviewer" not in str(school_role_check.sqltext).lower()


def test_tenant_status_server_defaults_match_reviewed_migration_literals() -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20261011_0003_school_membership_context.py"
    )
    migration = migration_path.read_text(encoding="utf-8")
    expected_migration_column = (
        'sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE")'
    )
    assert migration.count(expected_migration_column) == 3

    for table_name in (
        "schools",
        "account_school_memberships",
        "membership_roles",
    ):
        table = Base.metadata.tables[table_name]
        status = table.c.status
        assert status.default is not None
        assert getattr(status.default, "arg", None) == "ACTIVE"
        assert status.server_default is not None
        assert getattr(status.server_default, "arg", None) == "ACTIVE"
        compiled = str(CreateTable(table).compile(dialect=mysql.dialect()))
        assert "status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE'" in compiled


def test_migration_keeps_existing_legacy_rows_unscoped() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20261011_0003_school_membership_context.py"
    ).read_text(encoding="utf-8")
    upgrade = migration.split("def downgrade()", maxsplit=1)[0]
    assert "nullable=True" in upgrade
    assert "does not infer or backfill a school" in migration
    assert "UPDATE subjects" not in upgrade
    assert "UPDATE subject_access_grants" not in upgrade
    assert "data_origin" in upgrade
    assert "provenance_ref" in upgrade
    assert "provenance_ref = 'SYNTHETIC_REF_AUTH_TENANT_FIXTURE_V1'" in upgrade


def test_school_task_models_are_typed_and_same_school() -> None:
    classes = Base.metadata.tables["school_classes"]
    students = Base.metadata.tables["school_class_students"]
    teachers = Base.metadata.tables["school_class_teachers"]
    tasks = Base.metadata.tables["measurement_tasks"]
    enrollments = Base.metadata.tables["task_enrollments"]
    sessions = Base.metadata.tables["assessment_sessions"]

    for table in (classes, students, teachers, tasks, enrollments):
        assert table.c.school_id.nullable is False

    assert {"class_id", "subject_id", "school_id"}.issubset(students.c.keys())
    assert {"class_id", "membership_role_id", "school_id"}.issubset(teachers.c.keys())
    assert {"task_id", "class_student_id", "subject_id", "school_id"}.issubset(
        enrollments.c.keys()
    )
    assert sessions.c.task_enrollment_id.nullable is True

    def fk_targets(table, column_names):
        return next(
            constraint
            for constraint in table.constraints
            if isinstance(constraint, ForeignKeyConstraint)
            and tuple(element.parent.name for element in constraint.elements) == column_names
        )

    assert tuple(
        element.target_fullname
        for element in fk_targets(students, ("class_id", "school_id")).elements
    ) == ("school_classes.id", "school_classes.school_id")
    assert tuple(
        element.target_fullname
        for element in fk_targets(students, ("subject_id", "school_id")).elements
    ) == ("subjects.id", "subjects.school_id")
    assert tuple(
        element.target_fullname
        for element in fk_targets(teachers, ("membership_role_id", "school_id")).elements
    ) == ("membership_roles.id", "membership_roles.school_id")
    assert tuple(
        element.target_fullname
        for element in fk_targets(teachers, ("class_id", "school_id")).elements
    ) == ("school_classes.id", "school_classes.school_id")
    assert tuple(
        element.target_fullname
        for element in fk_targets(tasks, ("class_id", "school_id")).elements
    ) == ("school_classes.id", "school_classes.school_id")
    assert tuple(
        element.target_fullname
        for element in fk_targets(
            enrollments, ("class_student_id", "subject_id", "class_id", "school_id")
        ).elements
    ) == (
        "school_class_students.id",
        "school_class_students.subject_id",
        "school_class_students.class_id",
        "school_class_students.school_id",
    )
    assert tuple(
        element.target_fullname
        for element in fk_targets(enrollments, ("task_id", "school_id", "class_id")).elements
    ) == (
        "measurement_tasks.id",
        "measurement_tasks.school_id",
        "measurement_tasks.class_id",
    )
    assert tuple(
        element.target_fullname
        for element in fk_targets(sessions, ("task_enrollment_id", "subject_id")).elements
    ) == ("task_enrollments.id", "task_enrollments.subject_id")
    assert any(
        isinstance(constraint, UniqueConstraint)
        and tuple(column.name for column in constraint.columns) == ("task_enrollment_id",)
        for constraint in sessions.constraints
    )

    private_or_psychological = {
        "theta",
        "score",
        "response_ciphertext",
        "payload_ciphertext",
        "report_status",
        "review_status",
    }
    for table in (classes, students, teachers, tasks, enrollments):
        assert not private_or_psychological.intersection(table.c.keys())


def test_school_directory_models_have_scoped_provenance_constraints() -> None:
    schools = Base.metadata.tables["schools"]
    classes = Base.metadata.tables["school_classes"]
    memberships = Base.metadata.tables["account_school_memberships"]
    batches = Base.metadata.tables["school_account_batches"]
    provisions = Base.metadata.tables["school_account_provisions"]

    for table in (schools, classes, memberships):
        assert table.c.display_name.nullable is True
        assert isinstance(table.c.display_name.type, String)
        assert table.c.display_name.type.length == 120

    assert SchoolAccountBatch.__tablename__ == "school_account_batches"
    assert SchoolAccountProvision.__tablename__ == "school_account_provisions"
    assert batches.c.class_id.nullable is True
    assert batches.c.row_count.nullable is False
    assert provisions.c.activated_at.nullable is True

    def fk_targets(table, column_names):
        return next(
            constraint
            for constraint in table.constraints
            if isinstance(constraint, ForeignKeyConstraint)
            and tuple(element.parent.name for element in constraint.elements) == column_names
        )

    assert tuple(
        element.target_fullname
        for element in fk_targets(batches, ("created_by_membership_role_id", "school_id")).elements
    ) == ("membership_roles.id", "membership_roles.school_id")
    assert tuple(
        element.target_fullname
        for element in fk_targets(batches, ("class_id", "school_id")).elements
    ) == ("school_classes.id", "school_classes.school_id")
    assert tuple(
        element.target_fullname
        for element in fk_targets(provisions, ("batch_id", "school_id")).elements
    ) == ("school_account_batches.id", "school_account_batches.school_id")
    assert tuple(
        element.target_fullname
        for element in fk_targets(provisions, ("membership_id", "account_id", "school_id")).elements
    ) == (
        "account_school_memberships.id", "account_school_memberships.account_id",
        "account_school_memberships.school_id",
    )
    assert tuple(
        element.target_fullname
        for element in fk_targets(
            provisions, ("membership_role_id", "membership_id", "school_id")
        ).elements
    ) == ("membership_roles.id", "membership_roles.membership_id", "membership_roles.school_id")

    def unique_columns(table):
        return {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }

    assert ("id", "school_id") in unique_columns(batches)
    assert ("batch_ref",) in unique_columns(batches)
    assert ("account_id",) in unique_columns(provisions)
    assert ("batch_id", "row_no") in unique_columns(provisions)

    checks = {
        table.name: {
            constraint.name: str(constraint.sqltext)
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        for table in (batches, provisions)
    }
    assert "row_count BETWEEN 1 AND 100" in checks[batches.name][
        "ck_school_account_batches_row_count_allowed"
    ]
    assert "role_code IN ('student', 'teacher')" in checks[provisions.name][
        "ck_school_account_provisions_role_allowed"
    ]
    activation_check = checks[provisions.name][
        "ck_school_account_provisions_activation_matches_status"
    ]
    assert "PENDING_ACTIVATION" in activation_check
    assert "activated_at IS NOT NULL" in activation_check


def test_school_account_directory_migration_is_additive_and_downgrade_guarded(
    monkeypatch,
) -> None:
    from importlib.util import module_from_spec, spec_from_file_location

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20261012_0006_school_account_directory.py"
    )
    spec = spec_from_file_location("migration_20261012_0006", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261012_0006"
    assert migration.down_revision == "20261011_0005"

    operations: list[tuple[object, ...]] = []

    class _Connection:
        def __init__(self, populated_query: str | None = None) -> None:
            self.populated_query = populated_query

        def execute(self, statement):
            statement_text = str(statement)
            operations.append(("guard", statement_text))
            return type("Result", (), {
                "scalar_one": lambda _self: int(
                    self.populated_query is not None
                    and self.populated_query in statement_text
                )
            })()

    class _Ops:
        def __init__(self, populated_query: str | None = None) -> None:
            self.populated_query = populated_query

        def __getattr__(self, name):
            if name == "get_bind":
                return lambda: _Connection(self.populated_query)

            def record(*args, **kwargs):
                operations.append((name, *args, kwargs))

            return record

    monkeypatch.setattr(migration, "op", _Ops())
    migration.upgrade()
    assert [entry[1] for entry in operations if entry[0] == "create_table"] == [
        "school_account_batches",
        "school_account_provisions",
    ]
    assert [entry[1] for entry in operations if entry[0] == "add_column"] == [
        "schools",
        "school_classes",
        "account_school_memberships",
    ]

    guarded_queries = (
        "FROM school_account_batches",
        "FROM school_account_provisions",
        "FROM schools WHERE display_name IS NOT NULL",
        "FROM school_classes WHERE display_name IS NOT NULL",
        "FROM account_school_memberships WHERE display_name IS NOT NULL",
    )
    for populated_query in guarded_queries:
        operations.clear()
        monkeypatch.setattr(migration, "op", _Ops(populated_query=populated_query))
        with pytest.raises(RuntimeError, match="cannot downgrade school account directory"):
            migration.downgrade()
        assert operations
        assert all(entry[0] == "guard" for entry in operations)

    operations.clear()
    monkeypatch.setattr(migration, "op", _Ops())
    migration.downgrade()
    assert all(entry[0] == "guard" for entry in operations[:5])
    assert any(entry[0] == "drop_table" for entry in operations)
    assert any(entry[0] == "drop_column" for entry in operations)


def test_school_task_migration_is_additive_and_data_guarded(monkeypatch) -> None:
    from importlib.util import module_from_spec, spec_from_file_location

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20261011_0005_school_task_operations.py"
    )
    spec = spec_from_file_location("migration_20261011_0005", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261011_0005"
    assert migration.down_revision == "20261011_0004"

    operations: list[tuple[object, ...]] = []

    class _Connection:
        def __init__(self, populated_table: str | None = None) -> None:
            self.populated_table = populated_table

        def execute(self, statement):
            text = str(statement)
            operations.append(("guard", text))
            populated = self.populated_table is not None and self.populated_table in text
            return type("Result", (), {"scalar_one": lambda _self: int(populated)})()

    class _Ops:
        def __init__(self, populated_table: str | None = None) -> None:
            self.populated_table = populated_table

        def __getattr__(self, name):
            if name == "get_bind":
                return lambda: _Connection(self.populated_table)

            def record(*args, **kwargs):
                operations.append((name, *args, kwargs))

            return record

    monkeypatch.setattr(migration, "op", _Ops())
    migration.upgrade()
    created = [entry[1] for entry in operations if entry[0] == "create_table"]
    assert created == list(migration._BUSINESS_TABLES)
    assert any(entry[0] == "add_column" for entry in operations)

    for populated_table in (*migration._BUSINESS_TABLES, "assessment_sessions"):
        operations.clear()
        monkeypatch.setattr(migration, "op", _Ops(populated_table=populated_table))
        with pytest.raises(RuntimeError, match="business rows exist"):
            migration.downgrade()
        assert all(entry[0] == "guard" for entry in operations)

    operations.clear()
    monkeypatch.setattr(migration, "op", _Ops())
    migration.downgrade()
    assert all(entry[0] == "guard" for entry in operations[: len(migration._BUSINESS_TABLES) + 1])
    assert any(entry[0] == "drop_table" for entry in operations)


def test_school_professional_review_schema_has_task_school_subject_and_assessment_scope():
    tasks = Base.metadata.tables["measurement_tasks"]
    enrollments = Base.metadata.tables["task_enrollments"]
    assessments = Base.metadata.tables["assessment_sessions"]
    assignments = Base.metadata.tables["school_task_specialist_assignments"]
    cases = Base.metadata.tables["school_professional_review_cases"]
    events = Base.metadata.tables["school_professional_review_events"]

    def unique_columns(table):
        return {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }

    def fk_targets(table, column_names):
        return next(
            constraint
            for constraint in table.constraints
            if isinstance(constraint, ForeignKeyConstraint)
            and tuple(element.parent.name for element in constraint.elements) == column_names
        )

    assert ("id", "school_id") in unique_columns(tasks)
    assert ("id", "task_id", "school_id", "subject_id") in unique_columns(enrollments)
    assert ("id", "task_enrollment_id", "subject_id") in unique_columns(assessments)
    assert ("task_id", "specialist_membership_role_id") in unique_columns(assignments)
    assert assignments.c.status.type.length == 16
    assert cases.c.case_note_ciphertext.type.python_type is bytes
    assert "note" not in cases.c
    assert "note" not in events.c

    assert tuple(
        element.target_fullname
        for element in fk_targets(
            cases,
            ("task_enrollment_id", "task_id", "school_id", "subject_id"),
        ).elements
    ) == (
        "task_enrollments.id",
        "task_enrollments.task_id",
        "task_enrollments.school_id",
        "task_enrollments.subject_id",
    )
    assert tuple(
        element.target_fullname
        for element in fk_targets(
            cases,
            ("assessment_session_id", "task_enrollment_id", "subject_id"),
        ).elements
    ) == (
        "assessment_sessions.id",
        "assessment_sessions.task_enrollment_id",
        "assessment_sessions.subject_id",
    )
    assert tuple(
        element.target_fullname
        for element in fk_targets(
            assignments, ("specialist_membership_role_id", "school_id")
        ).elements
    ) == ("membership_roles.id", "membership_roles.school_id")
    assert tuple(
        element.target_fullname
        for element in fk_targets(events, ("actor_membership_role_id", "school_id")).elements
    ) == ("membership_roles.id", "membership_roles.school_id")


def test_school_professional_review_migration_is_additive_and_downgrade_guarded(
    monkeypatch,
) -> None:
    from importlib.util import module_from_spec, spec_from_file_location

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20261012_0007_school_professional_reviews.py"
    )
    spec = spec_from_file_location("migration_20261012_0007", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261012_0007"
    assert migration.down_revision == "20261012_0006"

    operations: list[tuple[object, ...]] = []

    class _Connection:
        def __init__(self, populated_table: str | None = None) -> None:
            self.populated_table = populated_table

        def execute(self, statement):
            statement_text = str(statement)
            operations.append(("guard", statement_text))
            return type("Result", (), {
                "scalar_one": lambda _self: int(
                    self.populated_table is not None and self.populated_table in statement_text
                )
            })()

    class _Ops:
        def __init__(self, populated_table: str | None = None) -> None:
            self.populated_table = populated_table

        def __getattr__(self, name):
            if name == "get_bind":
                return lambda: _Connection(self.populated_table)

            def record(*args, **kwargs):
                operations.append((name, *args, kwargs))

            return record

    monkeypatch.setattr(migration, "op", _Ops())
    migration.upgrade()
    created_tables = [entry[1] for entry in operations if entry[0] == "create_table"]
    assert created_tables == list(migration._BUSINESS_TABLES)
    created_uniques = [entry[1] for entry in operations if entry[0] == "create_unique_constraint"]
    assert created_uniques == [name for _table, name in migration._ADDED_UNIQUES[::-1]]

    for populated_table in migration._BUSINESS_TABLES:
        operations.clear()
        monkeypatch.setattr(migration, "op", _Ops(populated_table=populated_table))
        with pytest.raises(RuntimeError, match="cannot downgrade school professional review"):
            migration.downgrade()
        assert operations
        assert all(entry[0] == "guard" for entry in operations)

    operations.clear()
    monkeypatch.setattr(migration, "op", _Ops())
    migration.downgrade()
    assert all(entry[0] == "guard" for entry in operations[: len(migration._BUSINESS_TABLES)])
    assert [entry[1] for entry in operations if entry[0] == "drop_table"] == [
        "school_professional_review_events",
        "school_professional_review_cases",
        "school_task_specialist_assignments",
    ]
    assert [entry[1] for entry in operations if entry[0] == "drop_constraint"] == [
        name for _table, name in migration._ADDED_UNIQUES
    ]


def test_school_seed_provenance_migration_is_additive_and_downgrade_guarded(
    monkeypatch,
) -> None:
    from importlib.util import module_from_spec, spec_from_file_location

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20261011_0004_school_seed_provenance.py"
    )
    spec = spec_from_file_location("migration_20261011_0004", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261011_0004"
    assert migration.down_revision == "20261011_0003"

    operations: list[tuple[object, ...]] = []

    class _Connection:
        def __init__(self, count: int) -> None:
            self.count = count

        def execute(self, _statement, _params):
            operations.append(("guard", str(_statement), _params))
            return type("Result", (), {"scalar_one": lambda _self: self.count})()

    class _Ops:
        def __init__(self, count: int = 0) -> None:
            self.count = count

        def drop_constraint(self, *args, **kwargs) -> None:
            operations.append(("drop", *args, kwargs))

        def create_check_constraint(self, *args, **kwargs) -> None:
            operations.append(("create", *args, kwargs))

        def get_bind(self):
            return _Connection(self.count)

    monkeypatch.setattr(migration, "op", _Ops())
    migration.upgrade()
    assert operations[0][0:3] == ("drop", "ck_schools_provenance_ref_token", "schools")
    assert operations[1][0:3] == ("create", "ck_schools_provenance_ref_token", "schools")
    assert "SYNTHETIC_REF_AUTH_TENANT_FIXTURE_V1" in str(operations[1][3])
    assert "SYNTHETIC_REF_SCHOOL_SEED_RECIPE_V1" in str(operations[1][3])

    operations.clear()
    monkeypatch.setattr(migration, "op", _Ops(count=1))
    with pytest.raises(RuntimeError, match="registered seed rows exist"):
        migration.downgrade()
    assert len(operations) == 1
    assert operations[0][0] == "guard"
    assert "SELECT COUNT(*) FROM schools WHERE provenance_ref = :provenance_ref" in str(
        operations[0][1]
    )
    assert operations[0][2] == {
        "provenance_ref": "SYNTHETIC_REF_SCHOOL_SEED_RECIPE_V1"
    }

    operations.clear()
    monkeypatch.setattr(migration, "op", _Ops(count=0))
    migration.downgrade()
    assert operations[0][0] == "guard"
    assert operations[1][0:3] == ("drop", "ck_schools_provenance_ref_token", "schools")
    assert operations[2][0:3] == ("create", "ck_schools_provenance_ref_token", "schools")
    assert operations[2][3] == "provenance_ref = 'SYNTHETIC_REF_AUTH_TENANT_FIXTURE_V1'"


def test_school_cat_asset_models_keep_versions_immutable_and_school_scoped() -> None:
    banks = Base.metadata.tables["school_cat_item_banks"]
    bank_versions = Base.metadata.tables["school_cat_item_bank_versions"]
    plans = Base.metadata.tables["school_cat_plans"]
    plan_versions = Base.metadata.tables["school_cat_plan_versions"]

    assert set(banks.c.keys()) >= {
        "school_id", "display_name", "status", "revision", "creator_membership_role_id"
    }
    assert set(bank_versions.c.keys()) >= {
        "school_id", "bank_id", "version_number", "creator_membership_role_id",
        "item_count", "dimension_count", "payload_ciphertext", "cipher_format_version",
        "key_version", "payload_schema_version",
    }
    assert set(plans.c.keys()) >= {
        "school_id", "display_name", "status", "revision", "creator_membership_role_id"
    }
    assert set(plan_versions.c.keys()) >= {
        "school_id", "plan_id", "version_number", "bank_version_id",
        "creator_membership_role_id", "payload_ciphertext", "cipher_format_version",
        "key_version", "payload_schema_version",
    }
    assert SchoolCatItemBank.__tablename__ == banks.name
    assert SchoolCatItemBankVersion.__tablename__ == bank_versions.name
    assert SchoolCatPlan.__tablename__ == plans.name
    assert SchoolCatPlanVersion.__tablename__ == plan_versions.name
    assert bank_versions.c.payload_ciphertext.type.python_type is bytes
    assert plan_versions.c.payload_ciphertext.type.python_type is bytes

    def constraints(table):
        return {constraint.name: constraint for constraint in table.constraints}

    for table in (banks, bank_versions, plans, plan_versions):
        table_constraints = constraints(table)
        assert any(
            isinstance(constraint, UniqueConstraint)
            and tuple(column.name for column in constraint.columns) == ("id", "school_id")
            for constraint in table_constraints.values()
        )
        assert all(
            element.ondelete == "RESTRICT"
            for constraint in table_constraints.values()
            if isinstance(constraint, ForeignKeyConstraint)
            for element in constraint.elements
        )

    bank_version_scope = next(
        constraint for constraint in bank_versions.foreign_key_constraints
        if constraint.name == "fk_school_cat_item_bank_versions_bank_school"
    )
    assert tuple(element.target_fullname for element in bank_version_scope.elements) == (
        "school_cat_item_banks.id", "school_cat_item_banks.school_id"
    )
    plan_bank_version_scope = next(
        constraint for constraint in plan_versions.foreign_key_constraints
        if constraint.name == "fk_school_cat_plan_versions_bank_version_school"
    )
    assert tuple(element.target_fullname for element in plan_bank_version_scope.elements) == (
        "school_cat_item_bank_versions.id", "school_cat_item_bank_versions.school_id"
    )
    bank_version_checks = {
        constraint.name
        for constraint in bank_versions.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert bank_version_checks >= {
        "ck_school_cat_item_bank_versions_version_number_positive",
        "ck_school_cat_item_bank_versions_item_count_allowed",
        "ck_school_cat_item_bank_versions_dimension_count_allowed",
    }
    plan_version_checks = {
        constraint.name
        for constraint in plan_versions.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert plan_version_checks >= {
        "ck_school_cat_plan_versions_version_number_positive",
    }


def test_school_cat_assets_migration_is_additive_and_downgrade_guarded(monkeypatch) -> None:
    from importlib.util import module_from_spec, spec_from_file_location

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20261012_0008_school_cat_assets.py"
    )
    spec = spec_from_file_location("migration_20261012_0008", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261012_0008"
    assert migration.down_revision == "20261012_0007"

    operations: list[tuple[object, ...]] = []

    class _Connection:
        def __init__(self, populated_table: str | None = None) -> None:
            self.populated_table = populated_table

        def execute(self, statement):
            statement_text = str(statement)
            operations.append(("guard", statement_text))
            return type("Result", (), {
                "scalar_one": lambda _self: int(
                    self.populated_table is not None and self.populated_table in statement_text
                )
            })()

    class _Ops:
        def __init__(self, populated_table: str | None = None) -> None:
            self.populated_table = populated_table

        def __getattr__(self, name):
            if name == "get_bind":
                return lambda: _Connection(self.populated_table)

            def record(*args, **kwargs):
                operations.append((name, *args, kwargs))

            return record

    monkeypatch.setattr(migration, "op", _Ops())
    migration.upgrade()
    assert [entry[1] for entry in operations if entry[0] == "create_table"] == [
        "school_cat_item_banks",
        "school_cat_item_bank_versions",
        "school_cat_plans",
        "school_cat_plan_versions",
    ]
    assert not any(
        entry[0] in {"drop_table", "drop_column", "drop_constraint"}
        for entry in operations
    )

    for populated_table in migration._BUSINESS_TABLES:
        operations.clear()
        monkeypatch.setattr(migration, "op", _Ops(populated_table=populated_table))
        with pytest.raises(RuntimeError, match="cannot downgrade school CAT assets"):
            migration.downgrade()
        assert operations and all(entry[0] == "guard" for entry in operations)

    operations.clear()
    monkeypatch.setattr(migration, "op", _Ops())
    migration.downgrade()
    assert [entry[1] for entry in operations if entry[0] == "drop_table"] == list(
        migration._BUSINESS_TABLES
    )


def test_school_cat_activation_and_bindings_are_exactly_scoped() -> None:
    tasks = Base.metadata.tables["measurement_tasks"]
    sessions = Base.metadata.tables["assessment_sessions"]
    activations = Base.metadata.tables["school_cat_activations"]
    task_bindings = Base.metadata.tables["school_cat_task_bindings"]
    session_bindings = Base.metadata.tables["school_cat_session_bindings"]

    assert tasks.c.cat_binding_mode.server_default.arg == "FIXTURE"
    assert sessions.c.cat_binding_mode.server_default.arg == "FIXTURE"
    assert tasks.c.cat_binding_mode.type.length == 16
    assert sessions.c.cat_binding_mode.type.length == 16
    assert SchoolCatActivation.__tablename__ == activations.name
    assert SchoolCatTaskBinding.__tablename__ == task_bindings.name
    assert SchoolCatSessionBinding.__tablename__ == session_bindings.name
    assert activations.c.purpose.default.arg == "SYNTHETIC_ENGINEERING"
    assert activations.c.revoked_at.nullable

    def unique_columns(table):
        return {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }

    assert ("task_id",) in unique_columns(task_bindings)
    assert ("assessment_session_id",) in unique_columns(session_bindings)

    def fk_targets(table, name):
        constraint = next(
            constraint
            for constraint in table.foreign_key_constraints
            if constraint.name == name
        )
        assert all(element.ondelete == "RESTRICT" for element in constraint.elements)
        return tuple(element.target_fullname for element in constraint.elements)

    assert fk_targets(
        activations, "fk_school_cat_activations_plan_version_school"
    ) == ("school_cat_plan_versions.id", "school_cat_plan_versions.school_id")
    assert fk_targets(
        task_bindings, "fk_school_cat_task_bindings_task_scope"
    ) == ("measurement_tasks.id", "measurement_tasks.school_id")
    assert fk_targets(
        task_bindings, "fk_school_cat_task_bindings_activation_exact_version"
    ) == (
        "school_cat_activations.id",
        "school_cat_activations.school_id",
        "school_cat_activations.plan_version_id",
    )
    assert fk_targets(
        session_bindings, "fk_school_cat_session_bindings_assessment_scope"
    ) == (
        "assessment_sessions.id",
        "assessment_sessions.task_enrollment_id",
        "assessment_sessions.subject_id",
    )
    assert fk_targets(
        session_bindings, "fk_school_cat_session_bindings_enrollment_scope"
    ) == (
        "task_enrollments.id",
        "task_enrollments.task_id",
        "task_enrollments.school_id",
        "task_enrollments.subject_id",
    )
    assert fk_targets(
        session_bindings, "fk_school_cat_session_bindings_task_binding_exact"
    ) == (
        "school_cat_task_bindings.id",
        "school_cat_task_bindings.school_id",
        "school_cat_task_bindings.task_id",
        "school_cat_task_bindings.activation_id",
        "school_cat_task_bindings.plan_version_id",
    )

    for table in (activations, task_bindings, session_bindings):
        for constraint in table.foreign_key_constraints:
            assert all(element.ondelete == "RESTRICT" for element in constraint.elements)


def test_school_cat_task_binding_migration_is_additive_and_guarded(monkeypatch) -> None:
    from importlib.util import module_from_spec, spec_from_file_location

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20261013_0009_synthetic_cat_task_binding.py"
    )
    spec = spec_from_file_location("migration_20261013_0009", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261013_0009"
    assert migration.down_revision == "20261012_0008"

    operations: list[tuple[object, ...]] = []

    class _Connection:
        def __init__(self, populated_query: str | None = None) -> None:
            self.populated_query = populated_query

        def execute(self, statement):
            statement_text = str(statement)
            operations.append(("guard", statement_text))
            return type("Result", (), {
                "scalar_one": lambda _self: int(
                    self.populated_query is not None and self.populated_query in statement_text
                )
            })()

    class _Ops:
        def __init__(self, populated_query: str | None = None) -> None:
            self.populated_query = populated_query

        def __getattr__(self, name):
            if name == "get_bind":
                return lambda: _Connection(self.populated_query)

            def record(*args, **kwargs):
                operations.append((name, *args, kwargs))

            return record

    monkeypatch.setattr(migration, "op", _Ops())
    migration.upgrade()
    added_columns = [entry for entry in operations if entry[0] == "add_column"]
    assert [entry[1] for entry in added_columns] == ["measurement_tasks", "assessment_sessions"]
    assert [entry[2].name for entry in added_columns] == [
        "cat_binding_mode", "cat_binding_mode"
    ]
    assert all(entry[2].server_default.arg == "FIXTURE" for entry in added_columns)
    assert [entry[1] for entry in operations if entry[0] == "create_table"] == [
        "school_cat_activations", "school_cat_task_bindings", "school_cat_session_bindings"
    ]
    assert not any(
        entry[0] in {"execute", "drop_table", "drop_column", "drop_constraint"}
        for entry in operations
    )

    guarded_selects = [
        *(f"FROM {table}" for table in migration._BUSINESS_TABLES),
        "FROM measurement_tasks WHERE cat_binding_mode = 'SAVED_VERSION'",
        "FROM assessment_sessions WHERE cat_binding_mode = 'SAVED_VERSION'",
    ]
    for query in guarded_selects:
        operations.clear()
        monkeypatch.setattr(migration, "op", _Ops(populated_query=query))
        with pytest.raises(RuntimeError, match="cannot downgrade synthetic CAT bindings"):
            migration.downgrade()
        assert operations and all(entry[0] == "guard" for entry in operations)

    operations.clear()
    monkeypatch.setattr(migration, "op", _Ops())
    migration.downgrade()
    assert len([entry for entry in operations if entry[0] == "guard"]) == len(guarded_selects)
    assert [entry[1] for entry in operations if entry[0] == "drop_table"] == list(
        migration._BUSINESS_TABLES
    )
