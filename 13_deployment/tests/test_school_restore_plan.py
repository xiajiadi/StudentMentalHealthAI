import base64
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_restore_plan as restore_plan
from private_settings import MAGIC
from school_backup import (
    AUTH_SESSION_POLICY,
    BACKUP_V2,
    RECOVERY_SCOPE,
    SUPPORTED_REVISION,
    TARGET_POLICY,
    encode_value,
)
from school_schema import (
    CAT_ASSETS_REVISION,
    CAT_TASK_BINDING_REVISION,
    CURRENT_SCHOOL_MIGRATION_FILE,
    CURRENT_SCHOOL_REVISION,
    DIRECTORY_SCHOOL_REVISION,
    POST_ASSESSMENT_JOB_OUTBOX_REVISION,
    PROFESSIONAL_REVIEW_REVISION,
    PUBLIC_OBSERVED_CASE_ASSIGNMENTS_REVISION,
    RESEARCH_CAT_SESSIONS_REVISION,
    RESEARCH_COHORTS_REVISION,
    RESEARCH_EDUCATION_JOBS_REVISION,
    RESEARCH_PARAMETER_PROVENANCE_REVISION,
    RESEARCH_PROGRAMME_CANDIDATES_REVISION,
    RESEARCH_REVIEW_FEEDBACK_REVISION,
    SCHOOL_FEEDBACK_PUBLICATION_REVISION,
    SCHOOL_REVISION_CHAIN,
    SUPPORTED_SNAPSHOT_REVISIONS,
)

RESTORED_AT = datetime(2026, 10, 12, 4, 5, 6, 123456, tzinfo=UTC)
STAMP = datetime(2026, 10, 10, 1, 2, 3)  # noqa: DTZ001 - MySQL DATETIME is naive UTC.


def test_explicit_current_manifest_preserves_old_snapshot_layout():
    old = restore_plan.trusted_manifest(SUPPORTED_REVISION)
    current = restore_plan.trusted_manifest(DIRECTORY_SCHOOL_REVISION)
    assert len(old) == 28 and len(current) == 30
    assert set(current) - set(old) == restore_plan.DIRECTORY_TABLES
    for name in restore_plan.DIRECTORY_NAME_TABLES:
        assert "display_name" not in old[name]
        assert "display_name" in current[name]
    with pytest.raises(ValueError, match="Unsupported restore revision"):
        restore_plan.trusted_manifest("head")


def test_current_snapshot_requires_its_exact_table_layout_and_revision():
    package = empty_package()
    package["revision"] = CURRENT_SCHOOL_REVISION
    current = restore_plan.trusted_manifest(CURRENT_SCHOOL_REVISION)
    package["tables"] = {
        name: {"create_sql": "opaque archived DDL", "columns": columns, "rows": []}
        for name, columns in current.items()
    }
    package["tables"][restore_plan.REVISION_TABLE]["rows"] = [[CURRENT_SCHOOL_REVISION]]
    plan = restore_plan.plan_restore(package, restored_at=RESTORED_AT)
    assert plan["revision"] == CURRENT_SCHOOL_REVISION
    assert len(plan["table_order"]) == 55
    package["revision"] = SUPPORTED_REVISION
    with pytest.raises(ValueError, match="manifest mismatch"):
        restore_plan.plan_restore(package, restored_at=RESTORED_AT)


def test_professional_review_manifest_preserves_directory_snapshot_layout():
    directory = restore_plan.trusted_manifest("20261012_0006")
    professional = restore_plan.trusted_manifest(PROFESSIONAL_REVIEW_REVISION)
    assert len(directory) == 30 and len(professional) == 33
    assert set(professional) - set(directory) == restore_plan.PROFESSIONAL_REVIEW_TABLES
    assert all(professional[name] == columns for name, columns in directory.items())
    package = empty_package()
    package["revision"] = PROFESSIONAL_REVIEW_REVISION
    package["tables"] = {
        name: {"create_sql": "opaque archived DDL", "columns": columns, "rows": []}
        for name, columns in professional.items()
    }
    package["tables"][restore_plan.REVISION_TABLE]["rows"] = [[PROFESSIONAL_REVIEW_REVISION]]
    plan = restore_plan.plan_restore(package, restored_at=RESTORED_AT)
    assert len(plan["table_order"]) == 32
    order = plan["table_order"]
    assert order.index("school_professional_review_cases") < order.index("school_professional_review_events")
    package["revision"] = "20261012_0006"
    with pytest.raises(ValueError, match="manifest mismatch"):
        restore_plan.plan_restore(package, restored_at=RESTORED_AT)


def test_cat_assets_manifest_preserves_professional_snapshot_and_exact_foreign_keys():
    professional = restore_plan.trusted_manifest(PROFESSIONAL_REVIEW_REVISION)
    current = restore_plan.trusted_manifest(CAT_ASSETS_REVISION)
    assert set(current) - set(professional) == restore_plan.CAT_ASSET_TABLES
    assert len(current) == 37
    assert all(current[name] == columns for name, columns in professional.items())
    package = empty_package()
    package['revision'] = CAT_ASSETS_REVISION
    package['tables'] = {
        name: {'create_sql': 'opaque archived DDL', 'columns': columns, 'rows': []}
        for name, columns in current.items()
    }
    package['tables'][restore_plan.REVISION_TABLE]['rows'] = [[CAT_ASSETS_REVISION]]
    plan = restore_plan.plan_restore(package, restored_at=RESTORED_AT)
    order = plan['table_order']
    assert order.index('school_cat_item_banks') < order.index('school_cat_item_bank_versions')
    assert order.index('school_cat_item_bank_versions') < order.index('school_cat_plan_versions')
    assert order.index('school_cat_plans') < order.index('school_cat_plan_versions')
    package['revision'] = PROFESSIONAL_REVIEW_REVISION
    with pytest.raises(ValueError, match='manifest mismatch'):
        restore_plan.plan_restore(package, restored_at=RESTORED_AT)


def test_task_binding_manifest_preserves_exact_previous_columns_and_scope_chain():
    previous = restore_plan.trusted_manifest(CAT_ASSETS_REVISION)
    current = restore_plan.trusted_manifest(CAT_TASK_BINDING_REVISION)
    assert len(previous) == 37 and len(current) == 40
    assert set(current) - set(previous) == restore_plan.CAT_TASK_BINDING_TABLES
    for name, columns in previous.items():
        if name in restore_plan.CAT_TASK_BINDING_MODE_TABLES:
            assert "cat_binding_mode" not in columns
            assert set(current[name]) - set(columns) == {"cat_binding_mode"}
            assert [column for column in current[name] if column != "cat_binding_mode"] == columns
        else:
            assert current[name] == columns
    specs = restore_plan._load_trusted_tables(CAT_TASK_BINDING_REVISION)
    binding = specs["school_cat_session_bindings"]
    assert any(
        fk.remote_table == "school_cat_task_bindings"
        and fk.local_columns == ("task_binding_id", "school_id", "task_id", "activation_id", "plan_version_id")
        for fk in binding.foreign_keys
    )
    assert any(
        fk.remote_table == "task_enrollments"
        and fk.local_columns == ("task_enrollment_id", "task_id", "school_id", "subject_id")
        for fk in binding.foreign_keys
    )
    package = empty_package()
    package["revision"] = CAT_TASK_BINDING_REVISION
    package["tables"] = {
        name: {"create_sql": "opaque archived DDL", "columns": columns, "rows": []}
        for name, columns in current.items()
    }
    package["tables"][restore_plan.REVISION_TABLE]["rows"] = [[CAT_TASK_BINDING_REVISION]]
    order = restore_plan.plan_restore(package, restored_at=RESTORED_AT)["table_order"]
    assert order.index("school_cat_plan_versions") < order.index("school_cat_activations")
    assert order.index("school_cat_activations") < order.index("school_cat_task_bindings")
    assert order.index("school_cat_task_bindings") < order.index("school_cat_session_bindings")
    assert order.index("assessment_sessions") < order.index("school_cat_session_bindings")
    package["revision"] = CAT_ASSETS_REVISION
    with pytest.raises(ValueError, match="manifest mismatch"):
        restore_plan.plan_restore(package, restored_at=RESTORED_AT)


def test_feedback_publication_revision_adds_only_feedback_tables_and_preserves_0009():
    feedback_index = SCHOOL_REVISION_CHAIN.index(SCHOOL_FEEDBACK_PUBLICATION_REVISION)
    assert SCHOOL_REVISION_CHAIN[feedback_index - 1] == CAT_TASK_BINDING_REVISION
    assert SCHOOL_REVISION_CHAIN[feedback_index + 1] == POST_ASSESSMENT_JOB_OUTBOX_REVISION
    assert SCHOOL_FEEDBACK_PUBLICATION_REVISION in SUPPORTED_SNAPSHOT_REVISIONS
    previous = restore_plan.trusted_manifest(CAT_TASK_BINDING_REVISION)
    current = restore_plan.trusted_manifest(SCHOOL_FEEDBACK_PUBLICATION_REVISION)
    assert len(previous) == 40
    assert len(current) == 42
    assert set(previous).issubset(current)
    assert set(current) - set(previous) == restore_plan.SCHOOL_FEEDBACK_TABLES
    assert "school_feedback_records" not in previous
    assert "school_feedback_events" not in previous
    assert all(current[name] == columns for name, columns in previous.items())

    specs = restore_plan._load_trusted_tables(SCHOOL_FEEDBACK_PUBLICATION_REVISION)
    record = specs["school_feedback_records"]
    assert any(
        fk.remote_table == "school_professional_review_cases"
        and fk.local_columns
        == (
            "review_case_id",
            "school_id",
            "task_id",
            "class_id",
            "task_enrollment_id",
            "subject_id",
            "assessment_session_id",
        )
        for fk in record.foreign_keys
    )
    assert any(
        fk.remote_table == "task_enrollments"
        and fk.local_columns
        == ("task_enrollment_id", "task_id", "school_id", "subject_id")
        for fk in record.foreign_keys
    )

    package = empty_package()
    package["revision"] = SCHOOL_FEEDBACK_PUBLICATION_REVISION
    package["tables"] = {
        name: {"create_sql": "opaque archived DDL", "columns": columns, "rows": []}
        for name, columns in current.items()
    }
    package["tables"][restore_plan.REVISION_TABLE]["rows"] = [
        [SCHOOL_FEEDBACK_PUBLICATION_REVISION]
    ]
    plan = restore_plan.plan_restore(package, restored_at=RESTORED_AT)
    order = plan["table_order"]
    assert len(order) == 41
    for parent in (
        "school_professional_review_cases",
        "measurement_tasks",
        "task_enrollments",
        "assessment_sessions",
        "subjects",
        "membership_roles",
    ):
        assert order.index(parent) < order.index("school_feedback_records")
    assert order.index("school_feedback_records") < order.index(
        "school_feedback_events"
    )


def test_post_assessment_outbox_revision_adds_one_table_and_preserves_0010():
    assert POST_ASSESSMENT_JOB_OUTBOX_REVISION in SCHOOL_REVISION_CHAIN
    assert POST_ASSESSMENT_JOB_OUTBOX_REVISION in SUPPORTED_SNAPSHOT_REVISIONS
    previous = restore_plan.trusted_manifest(SCHOOL_FEEDBACK_PUBLICATION_REVISION)
    current = restore_plan.trusted_manifest(POST_ASSESSMENT_JOB_OUTBOX_REVISION)
    assert len(previous) == 42
    assert len(current) == 43
    assert set(previous).issubset(current)
    assert set(current) - set(previous) == restore_plan.POST_ASSESSMENT_JOB_TABLES
    assert all(current[name] == columns for name, columns in previous.items())

    specs = restore_plan._load_trusted_tables(POST_ASSESSMENT_JOB_OUTBOX_REVISION)
    job = specs["school_post_assessment_jobs"]
    expected_fk_targets = {
        "schools",
        "measurement_tasks",
        "school_class_students",
        "task_enrollments",
        "assessment_sessions",
        "subjects",
    }
    assert {fk.remote_table for fk in job.foreign_keys} == expected_fk_targets

    package = empty_package()
    package["revision"] = POST_ASSESSMENT_JOB_OUTBOX_REVISION
    package["tables"] = {
        name: {"create_sql": "opaque archived DDL", "columns": columns, "rows": []}
        for name, columns in current.items()
    }
    package["tables"][restore_plan.REVISION_TABLE]["rows"] = [
        [POST_ASSESSMENT_JOB_OUTBOX_REVISION]
    ]
    plan = restore_plan.plan_restore(package, restored_at=RESTORED_AT)
    order = plan["table_order"]
    assert len(order) == 42
    for parent in expected_fk_targets:
        assert order.index(parent) < order.index("school_post_assessment_jobs")

    package["revision"] = SCHOOL_FEEDBACK_PUBLICATION_REVISION
    package["tables"].pop("school_post_assessment_jobs")
    package["tables"][restore_plan.REVISION_TABLE]["rows"] = [
        [SCHOOL_FEEDBACK_PUBLICATION_REVISION]
    ]
    older_plan = restore_plan.plan_restore(package, restored_at=RESTORED_AT)
    assert "school_post_assessment_jobs" not in older_plan["tables"]


def test_research_revision_adds_three_isolated_tables_and_preserves_0011_layout():
    assert RESEARCH_CAT_SESSIONS_REVISION in SCHOOL_REVISION_CHAIN
    previous = restore_plan.trusted_manifest(POST_ASSESSMENT_JOB_OUTBOX_REVISION)
    current = restore_plan.trusted_manifest(RESEARCH_CAT_SESSIONS_REVISION)
    assert len(previous) == 43 and len(current) == 46
    assert set(current) - set(previous) == restore_plan.RESEARCH_CAT_TABLES
    assert all(current[name] == columns for name, columns in previous.items())

    specs = restore_plan._load_trusted_tables(RESEARCH_CAT_SESSIONS_REVISION)
    session = specs["school_research_sessions"]
    assert any(
        fk.remote_table == "task_enrollments"
        and fk.local_columns == ("task_enrollment_id", "task_id", "school_id", "subject_id")
        for fk in session.foreign_keys
    )

    package = empty_package()
    package["revision"] = RESEARCH_CAT_SESSIONS_REVISION
    package["tables"] = {
        name: {"create_sql": "opaque archived DDL", "columns": columns, "rows": []}
        for name, columns in current.items()
    }
    package["tables"][restore_plan.REVISION_TABLE]["rows"] = [
        [RESEARCH_CAT_SESSIONS_REVISION]
    ]
    plan = restore_plan.plan_restore(package, restored_at=RESTORED_AT)
    assert len(plan["table_order"]) == 45
    assert plan["table_order"].index("school_research_profile_versions") < plan["table_order"].index("school_research_task_bindings")
    assert plan["table_order"].index("school_research_task_bindings") < plan["table_order"].index("school_research_sessions")


def test_parameter_provenance_revision_preserves_0012_snapshot_shape():
    assert RESEARCH_PARAMETER_PROVENANCE_REVISION in SCHOOL_REVISION_CHAIN
    assert CURRENT_SCHOOL_REVISION == RESEARCH_PROGRAMME_CANDIDATES_REVISION
    assert SCHOOL_REVISION_CHAIN[-4] == RESEARCH_COHORTS_REVISION
    assert SCHOOL_REVISION_CHAIN[-3] == RESEARCH_EDUCATION_JOBS_REVISION
    assert SCHOOL_REVISION_CHAIN[-2] == RESEARCH_REVIEW_FEEDBACK_REVISION
    assert SCHOOL_REVISION_CHAIN[-1] == RESEARCH_PROGRAMME_CANDIDATES_REVISION
    old = restore_plan._load_trusted_tables(RESEARCH_CAT_SESSIONS_REVISION)
    current = restore_plan._load_trusted_tables(RESEARCH_PARAMETER_PROVENANCE_REVISION)
    assert set(old) == set(current) and len(current) == 46
    profile = "school_research_profile_versions"
    added = {"parameter_origin", "published_parameter_crosswalk_sha256"}
    assert set(current[profile].columns) - set(old[profile].columns) == added
    assert all(old[name] == spec for name, spec in current.items() if name != profile)
    assert tuple(c for c in current[profile].columns if c not in added) == old[profile].columns
    assert {"fit_sha256", "calibration_sha256"}.isdisjoint(old[profile].nullable_columns)
    assert {"fit_sha256", "calibration_sha256", "published_parameter_crosswalk_sha256"} <= current[profile].nullable_columns
    assert "parameter_origin" not in current[profile].nullable_columns


def test_public_observed_revision_preserves_0013_snapshots_and_adds_exact_assignment_table():
    assert RESEARCH_PARAMETER_PROVENANCE_REVISION in SUPPORTED_SNAPSHOT_REVISIONS
    assert PUBLIC_OBSERVED_CASE_ASSIGNMENTS_REVISION in SUPPORTED_SNAPSHOT_REVISIONS
    old = restore_plan._load_trusted_tables(RESEARCH_PARAMETER_PROVENANCE_REVISION)
    current = restore_plan._load_trusted_tables(PUBLIC_OBSERVED_CASE_ASSIGNMENTS_REVISION)
    assert len(old) == 46
    assert len(current) == 47
    assert set(current) - set(old) == restore_plan.PUBLIC_OBSERVED_CASE_ASSIGNMENT_TABLES
    for name, old_spec in old.items():
        if name == "school_research_task_bindings":
            assert tuple(
                column for column in current[name].columns
                if column not in {"corpus_sha256", "case_count"}
            ) == old_spec.columns
            assert tuple(
                column for column in current[name].columns
                if column not in old_spec.columns
            ) == ("corpus_sha256", "case_count")
        else:
            assert current[name] == old_spec

    assignment = current["school_research_case_assignments"]
    assert {
        "task_enrollment_id", "task_binding_id", "profile_version_id",
        "corpus_sha256", "case_count", "case_index", "purpose",
    } <= set(assignment.columns)
    assert any(
        fk.remote_table == "school_research_task_bindings"
        and fk.local_columns[-2:] == ("corpus_sha256", "case_count")
        for fk in assignment.foreign_keys
    )

    package = empty_package()
    package["revision"] = RESEARCH_PARAMETER_PROVENANCE_REVISION
    package["tables"] = {
        name: {"create_sql": "opaque archived DDL", "columns": list(spec.columns), "rows": []}
        for name, spec in old.items()
    }
    package["tables"][restore_plan.REVISION_TABLE]["rows"] = [
        [RESEARCH_PARAMETER_PROVENANCE_REVISION]
    ]
    old_plan = restore_plan.plan_restore(package, restored_at=RESTORED_AT)
    assert old_plan["revision"] == RESEARCH_PARAMETER_PROVENANCE_REVISION
    assert len(old_plan["table_order"]) == 45
    assert "school_research_case_assignments" not in old_plan["tables"]

    package["revision"] = PUBLIC_OBSERVED_CASE_ASSIGNMENTS_REVISION
    package["tables"] = {
        name: {"create_sql": "opaque archived DDL", "columns": list(spec.columns), "rows": []}
        for name, spec in current.items()
    }
    package["tables"][restore_plan.REVISION_TABLE]["rows"] = [
        [PUBLIC_OBSERVED_CASE_ASSIGNMENTS_REVISION]
    ]
    current_plan = restore_plan.plan_restore(package, restored_at=RESTORED_AT)
    assert current_plan["revision"] == PUBLIC_OBSERVED_CASE_ASSIGNMENTS_REVISION
    assert len(current_plan["table_order"]) == 46
    order = current_plan["table_order"]
    assert order.index("school_research_task_bindings") < order.index(
        "school_research_case_assignments"
    )
    assert order.index("task_enrollments") < order.index("school_research_case_assignments")


def test_sealed_cohort_revision_preserves_0014_snapshot_and_adds_only_cohort_projection():
    assert RESEARCH_COHORTS_REVISION in SCHOOL_REVISION_CHAIN
    assert CURRENT_SCHOOL_REVISION == RESEARCH_PROGRAMME_CANDIDATES_REVISION
    assert SCHOOL_REVISION_CHAIN[-4] == RESEARCH_COHORTS_REVISION
    assert SCHOOL_REVISION_CHAIN[-3] == RESEARCH_EDUCATION_JOBS_REVISION
    assert SCHOOL_REVISION_CHAIN[-2] == RESEARCH_REVIEW_FEEDBACK_REVISION
    assert SCHOOL_REVISION_CHAIN[-1] == RESEARCH_PROGRAMME_CANDIDATES_REVISION

    previous = restore_plan._load_trusted_tables(PUBLIC_OBSERVED_CASE_ASSIGNMENTS_REVISION)
    current = restore_plan._load_trusted_tables(RESEARCH_COHORTS_REVISION)
    assert len(previous) == 47
    assert len(current) == 50
    assert set(current) - set(previous) == restore_plan.RESEARCH_COHORT_TABLES

    binding_name = "school_research_task_bindings"
    binding = current[binding_name]
    assert "cohort_id" not in previous[binding_name].columns
    assert binding.columns[-1] == "cohort_id"
    assert "cohort_id" in binding.nullable_columns
    assert binding.columns == previous[binding_name].columns + ("cohort_id",)

    assignment_name = "school_research_case_assignments"
    assignment = current[assignment_name]
    previous_assignment = previous[assignment_name]
    added_assignment_columns = {"cohort_id", "cohort_assignment_id"}
    assert added_assignment_columns.isdisjoint(previous_assignment.columns)
    assert set(assignment.columns) - set(previous_assignment.columns) == added_assignment_columns
    assert added_assignment_columns <= assignment.nullable_columns
    assert assignment.columns == previous_assignment.columns + ("cohort_id", "cohort_assignment_id")

    old_package = empty_package()
    old_package["revision"] = PUBLIC_OBSERVED_CASE_ASSIGNMENTS_REVISION
    old_package["tables"] = {
        name: {"create_sql": "opaque archived DDL", "columns": list(spec.columns), "rows": []}
        for name, spec in previous.items()
    }
    old_package["tables"][restore_plan.REVISION_TABLE]["rows"] = [
        [PUBLIC_OBSERVED_CASE_ASSIGNMENTS_REVISION]
    ]
    old_plan = restore_plan.plan_restore(old_package, restored_at=RESTORED_AT)
    assert old_plan["revision"] == PUBLIC_OBSERVED_CASE_ASSIGNMENTS_REVISION
    assert len(old_plan["table_order"]) == 46
    assert set(old_plan["tables"]).isdisjoint(restore_plan.RESEARCH_COHORT_TABLES)
    assert "cohort_id" not in old_plan["tables"][binding_name]["columns"]
    assert added_assignment_columns.isdisjoint(old_plan["tables"][assignment_name]["columns"])

    current_package = empty_package()
    current_package["revision"] = RESEARCH_COHORTS_REVISION
    current_package["tables"] = {
        name: {"create_sql": "opaque archived DDL", "columns": list(spec.columns), "rows": []}
        for name, spec in current.items()
    }
    current_package["tables"][restore_plan.REVISION_TABLE]["rows"] = [
        [RESEARCH_COHORTS_REVISION]
    ]
    current_plan = restore_plan.plan_restore(current_package, restored_at=RESTORED_AT)
    assert current_plan["revision"] == RESEARCH_COHORTS_REVISION
    assert len(current_plan["table_order"]) == 49
    order = current_plan["table_order"]
    assert order.index("school_research_cohorts") < order.index("school_research_cohort_batches")
    assert order.index("school_research_cohort_batches") < order.index("school_research_cohort_assignments")
    assert order.index("school_research_cohort_assignments") < order.index(assignment_name)
    assert order.index("school_research_cohorts") < order.index(binding_name)
    assert order.index(binding_name) < order.index(assignment_name)


def test_research_education_jobs_revision_adds_one_table_and_preserves_0015_rows():
    assert RESEARCH_EDUCATION_JOBS_REVISION in SCHOOL_REVISION_CHAIN
    assert RESEARCH_EDUCATION_JOBS_REVISION in SUPPORTED_SNAPSHOT_REVISIONS
    assert CURRENT_SCHOOL_REVISION == RESEARCH_PROGRAMME_CANDIDATES_REVISION
    assert SCHOOL_REVISION_CHAIN[-4] == RESEARCH_COHORTS_REVISION
    assert SCHOOL_REVISION_CHAIN[-3] == RESEARCH_EDUCATION_JOBS_REVISION
    assert SCHOOL_REVISION_CHAIN[-2] == RESEARCH_REVIEW_FEEDBACK_REVISION
    assert SCHOOL_REVISION_CHAIN[-1] == RESEARCH_PROGRAMME_CANDIDATES_REVISION

    previous = restore_plan._load_trusted_tables(RESEARCH_COHORTS_REVISION)
    current = restore_plan._load_trusted_tables(RESEARCH_EDUCATION_JOBS_REVISION)
    job_table = "school_research_education_jobs"
    assert len(previous) == 50
    assert len(current) == 51
    assert set(current) - set(previous) == {job_table}
    assert all(current[name] == spec for name, spec in previous.items())

    job = current[job_table]
    assert job.columns == (
        "job_ref", "research_session_id", "school_id", "task_id", "class_id",
        "task_enrollment_id", "subject_id", "task_binding_id", "profile_version_id",
        "profile_ref", "profile_version_number", "profile_sha256", "response_origin",
        "job_kind", "purpose", "research_only", "publication_status", "policy_version",
        "policy_hash", "status", "attempt_count", "next_attempt_at", "lease_owner",
        "lease_expires_at", "lease_token", "last_error_code", "id", "public_id",
        "created_at", "updated_at",
    )
    assert job.primary_key == ("id",)
    assert job.nullable_columns == frozenset(
        {
            "policy_hash", "next_attempt_at", "lease_owner", "lease_expires_at",
            "lease_token", "last_error_code",
        }
    )
    exact_scope = (
        "research_session_id", "school_id", "task_id", "class_id",
        "task_enrollment_id", "subject_id", "task_binding_id", "profile_version_id",
        "profile_ref", "profile_version_number", "profile_sha256", "response_origin",
    )
    session_fk = next(fk for fk in job.foreign_keys if fk.remote_table == "school_research_sessions")
    assert session_fk.local_columns == exact_scope
    assert session_fk.remote_columns == ("id", *exact_scope[1:])

    for older_revision in (
        PUBLIC_OBSERVED_CASE_ASSIGNMENTS_REVISION,
        RESEARCH_COHORTS_REVISION,
    ):
        assert job_table not in restore_plan._load_trusted_tables(older_revision)

    old_package = empty_package()
    old_package["revision"] = RESEARCH_COHORTS_REVISION
    old_package["tables"] = {
        name: {
            "create_sql": "opaque archived DDL",
            "columns": list(spec.columns),
            "rows": [],
        }
        for name, spec in previous.items()
    }
    old_package["tables"][restore_plan.REVISION_TABLE]["rows"] = [
        [RESEARCH_COHORTS_REVISION]
    ]
    school_spec = previous["schools"]
    school_row = {
        column: (
            5001 if column == "id"
            else STAMP if column in {"created_at", "updated_at"}
            else None if column in school_spec.nullable_columns
            else "synthetic-preserved"
        )
        for column in school_spec.columns
    }
    add_row(old_package, "schools", school_row)
    original_school_rows = deepcopy(old_package["tables"]["schools"]["rows"])
    old_plan = restore_plan.plan_restore(old_package, restored_at=RESTORED_AT)
    assert old_package["tables"]["schools"]["rows"] == original_school_rows
    assert old_plan["revision"] == RESEARCH_COHORTS_REVISION
    assert len(old_plan["table_order"]) == 49
    assert job_table not in old_plan["tables"]
    restored_school_columns = old_plan["tables"]["schools"]["columns"]
    restored_school_row = dict(
        zip(restored_school_columns, old_plan["tables"]["schools"]["rows"][0])
    )
    assert restored_school_row == school_row

    current_package = empty_package()
    current_package["revision"] = RESEARCH_EDUCATION_JOBS_REVISION
    current_package["tables"] = {
        name: {
            "create_sql": "opaque archived DDL",
            "columns": list(spec.columns),
            "rows": [],
        }
        for name, spec in current.items()
    }
    current_package["tables"][restore_plan.REVISION_TABLE]["rows"] = [
        [RESEARCH_EDUCATION_JOBS_REVISION]
    ]
    current_plan = restore_plan.plan_restore(
        current_package, restored_at=RESTORED_AT
    )
    assert current_plan["revision"] == RESEARCH_EDUCATION_JOBS_REVISION
    assert len(current_plan["table_order"]) == 50
    assert current_plan["row_counts"][job_table] == 0
    assert current_plan["table_order"].index("school_research_sessions") < current_plan[
        "table_order"
    ].index(job_table)


def test_research_review_feedback_revision_adds_four_tables_and_preserves_0016():
    assert RESEARCH_REVIEW_FEEDBACK_REVISION in SCHOOL_REVISION_CHAIN
    assert RESEARCH_REVIEW_FEEDBACK_REVISION in SUPPORTED_SNAPSHOT_REVISIONS
    assert CURRENT_SCHOOL_REVISION == RESEARCH_PROGRAMME_CANDIDATES_REVISION
    assert CURRENT_SCHOOL_MIGRATION_FILE == "20261014_0018_research_programme_candidates.py"

    previous = restore_plan._load_trusted_tables(RESEARCH_EDUCATION_JOBS_REVISION)
    current = restore_plan._load_trusted_tables(RESEARCH_REVIEW_FEEDBACK_REVISION)
    assert len(previous) == 51
    assert len(current) == 55
    assert set(current) - set(previous) == restore_plan.RESEARCH_REVIEW_FEEDBACK_TABLES
    assert all(current[name] == spec for name, spec in previous.items())
    assert "case_note_ciphertext" in current["school_research_review_cases"].columns
    assert "payload_ciphertext" in current["school_research_feedback_records"].columns
    assert "case_note_ciphertext" not in current["school_research_review_events"].columns
    assert "payload_ciphertext" not in current["school_research_feedback_events"].columns

    for old_revision in (RESEARCH_EDUCATION_JOBS_REVISION, RESEARCH_COHORTS_REVISION):
        assert set(restore_plan._load_trusted_tables(old_revision)).isdisjoint(
            restore_plan.RESEARCH_REVIEW_FEEDBACK_TABLES
        )

    package = empty_package()
    package["revision"] = RESEARCH_REVIEW_FEEDBACK_REVISION
    package["tables"] = {
        name: {"create_sql": "opaque archived DDL", "columns": list(spec.columns), "rows": []}
        for name, spec in current.items()
    }
    package["tables"][restore_plan.REVISION_TABLE]["rows"] = [
        [RESEARCH_REVIEW_FEEDBACK_REVISION]
    ]
    plan = restore_plan.plan_restore(package, restored_at=RESTORED_AT)
    assert plan["revision"] == RESEARCH_REVIEW_FEEDBACK_REVISION
    assert len(plan["table_order"]) == 54
    order = plan["table_order"]
    assert order.index("school_research_sessions") < order.index("school_research_review_cases")
    assert order.index("school_research_review_cases") < order.index("school_research_review_events")
    assert order.index("school_research_review_cases") < order.index("school_research_feedback_records")
    assert order.index("school_research_feedback_records") < order.index("school_research_feedback_events")


def test_0018_candidate_revision_preserves_0017_snapshot_and_adds_encrypted_candidate():
    assert CURRENT_SCHOOL_REVISION == RESEARCH_PROGRAMME_CANDIDATES_REVISION
    assert SCHOOL_REVISION_CHAIN[-2] == RESEARCH_REVIEW_FEEDBACK_REVISION
    assert CURRENT_SCHOOL_MIGRATION_FILE == "20261014_0018_research_programme_candidates.py"
    previous = restore_plan._load_trusted_tables(RESEARCH_REVIEW_FEEDBACK_REVISION)
    current = restore_plan._load_trusted_tables(RESEARCH_PROGRAMME_CANDIDATES_REVISION)
    candidate_table = "school_research_programme_candidates"
    assert len(previous) == 55
    assert len(current) == 56
    assert set(current) - set(previous) == {candidate_table}
    assert all(current[name] == spec for name, spec in previous.items())
    assert "payload_ciphertext" in current[candidate_table].columns
    assert "school_id" in current[candidate_table].columns
    assert current[candidate_table].foreign_keys

    old_candidate_refs = restore_plan._load_trusted_tables(RESEARCH_REVIEW_FEEDBACK_REVISION)
    assert candidate_table not in old_candidate_refs
    package = empty_package()
    package["revision"] = RESEARCH_PROGRAMME_CANDIDATES_REVISION
    package["tables"] = {
        name: {"create_sql": "opaque archived DDL", "columns": list(spec.columns), "rows": []}
        for name, spec in current.items()
    }
    package["tables"][restore_plan.REVISION_TABLE]["rows"] = [
        [RESEARCH_PROGRAMME_CANDIDATES_REVISION]
    ]
    plan = restore_plan.plan_restore(package, restored_at=RESTORED_AT)
    assert plan["revision"] == RESEARCH_PROGRAMME_CANDIDATES_REVISION
    assert len(plan["table_order"]) == 55
    assert plan["table_order"].index("school_research_task_bindings") < plan["table_order"].index(candidate_table)


def empty_package():
    manifest = restore_plan.trusted_manifest()
    tables = {
        name: {
            "create_sql": f"CREATE TABLE `{name}` (archived only)",
            "columns": columns.copy(),
            "rows": [],
        }
        for name, columns in manifest.items()
    }
    tables[restore_plan.REVISION_TABLE]["rows"] = [[SUPPORTED_REVISION]]
    return {
        "schema_version": BACKUP_V2,
        "project": "StudentMentalHealthAI",
        "synthetic_only": True,
        "workspace_id": "source-synthetic-001",
        "database": "smhai_school_demo",
        "port": 3308,
        "revision": SUPPORTED_REVISION,
        "tables": tables,
        "database_key_container_b64": base64.b64encode(
            MAGIC + b"synthetic-sealed-key"
        ).decode("ascii"),
        "recovery_scope": RECOVERY_SCOPE,
        "target_policy": TARGET_POLICY,
        "auth_session_policy": AUTH_SESSION_POLICY,
    }


def add_row(package, table_name, values, *, column_order=None):
    table = package["tables"][table_name]
    columns = column_order or table["columns"]
    assert set(columns) == set(table["columns"])
    table["columns"] = list(columns)
    table["rows"].append([encode_value(values[column]) for column in columns])


def account_row(account_id=1, *, login_name="student-demo", password_hash="synthetic-hash"):
    return {
        "id": account_id,
        "public_id": f"00000000-0000-4000-8000-{account_id:012d}",
        "created_at": STAMP,
        "updated_at": STAMP,
        "login_name": login_name,
        "password_hash": password_hash,
        "status": "ACTIVE",
    }


def school_row(school_id, school_ref):
    return {
        "id": school_id,
        "public_id": f"10000000-0000-4000-8000-{school_id:012d}",
        "created_at": STAMP,
        "updated_at": STAMP,
        "school_ref": school_ref,
        "status": "ACTIVE",
        "data_origin": "SYNTHETIC",
        "provenance_ref": "SYNTHETIC_REF_SCHOOL_SEED_RECIPE_V1",
    }


def membership_row(membership_id, account_id, school_id):
    return {
        "id": membership_id,
        "public_id": f"20000000-0000-4000-8000-{membership_id:012d}",
        "created_at": STAMP,
        "updated_at": STAMP,
        "account_id": account_id,
        "school_id": school_id,
        "status": "ACTIVE",
        "valid_from": STAMP,
        "valid_until": None,
        "revoked_at": None,
    }


def test_trusted_manifest_is_exactly_27_models_plus_alembic_version():
    manifest = restore_plan.trusted_manifest()

    assert len(manifest) == restore_plan.MODEL_TABLE_COUNT + 1
    assert set(manifest) == restore_plan.EXPECTED_MODEL_TABLES | {
        restore_plan.REVISION_TABLE
    }
    assert manifest[restore_plan.REVISION_TABLE] == ["version_num"]


def test_empty_snapshot_builds_deterministic_parent_first_plan():
    package = empty_package()

    plan = restore_plan.plan_restore(package, restored_at=RESTORED_AT)

    assert plan["revision"] == SUPPORTED_REVISION
    assert restore_plan.REVISION_TABLE not in plan["table_order"]
    assert restore_plan.REVISION_TABLE not in plan["tables"]
    assert restore_plan.REVISION_TABLE not in plan["row_counts"]
    assert len(plan["table_order"]) == restore_plan.MODEL_TABLE_COUNT
    assert set(plan["tables"]) == restore_plan.EXPECTED_MODEL_TABLES
    assert all(count == 0 for count in plan["row_counts"].values())
    assert plan["revoked_session_count"] == 0

    order_index = {name: index for index, name in enumerate(plan["table_order"])}
    trusted_tables = restore_plan._load_trusted_tables()
    for child_name, spec in trusted_tables.items():
        if child_name == restore_plan.REVISION_TABLE:
            continue
        for foreign_key in spec.foreign_keys:
            assert order_index[foreign_key.remote_table] < order_index[child_name]


def test_input_column_order_is_mapped_to_trusted_local_order():
    package = empty_package()
    original_columns = package["tables"]["accounts"]["columns"].copy()
    row = account_row()
    add_row(package, "accounts", row, column_order=list(reversed(original_columns)))

    plan = restore_plan.plan_restore(package, restored_at=RESTORED_AT)
    planned = plan["tables"]["accounts"]

    assert planned["columns"] == original_columns
    assert planned["rows"] == [[row[column] for column in original_columns]]


def test_nonnullable_null_and_duplicate_primary_keys_are_rejected():
    with_null = empty_package()
    invalid = account_row(password_hash=None)
    add_row(with_null, "accounts", invalid)
    with pytest.raises(ValueError, match="NULL in non-null column accounts.password_hash"):
        restore_plan.plan_restore(with_null, restored_at=RESTORED_AT)

    duplicate = empty_package()
    add_row(duplicate, "accounts", account_row())
    add_row(duplicate, "accounts", account_row(login_name="another-demo"))
    with pytest.raises(ValueError, match="Duplicate primary key in accounts"):
        restore_plan.plan_restore(duplicate, restored_at=RESTORED_AT)


def test_simple_foreign_key_missing_parent_is_rejected():
    package = empty_package()
    add_row(package, "accounts", account_row())
    child = {
        "id": 5,
        "public_id": "50000000-0000-4000-8000-000000000005",
        "created_at": STAMP,
        "updated_at": STAMP,
        "account_id": 1,
        "role_id": 404,
        "status": "ACTIVE",
        "granted_at": STAMP,
        "revoked_at": None,
    }
    add_row(package, "account_roles", child)

    with pytest.raises(ValueError, match="Foreign-key reference missing for account_roles"):
        restore_plan.plan_restore(package, restored_at=RESTORED_AT)


def test_composite_foreign_key_mismatch_is_rejected():
    package = empty_package()
    add_row(package, "accounts", account_row())
    add_row(package, "schools", school_row(10, "school-a"))
    add_row(package, "schools", school_row(20, "school-b"))
    add_row(package, "account_school_memberships", membership_row(30, 1, 10))
    add_row(
        package,
        "membership_roles",
        {
            "id": 40,
            "public_id": "40000000-0000-4000-8000-000000000040",
            "created_at": STAMP,
            "updated_at": STAMP,
            "membership_id": 30,
            "school_id": 20,
            "role_code": "student",
            "status": "ACTIVE",
            "valid_from": STAMP,
            "valid_until": None,
            "revoked_at": None,
        },
    )

    with pytest.raises(ValueError, match="Foreign-key reference missing for membership_roles"):
        restore_plan.plan_restore(package, restored_at=RESTORED_AT)


def test_revision_table_must_contain_exactly_the_supported_single_row():
    package = empty_package()
    package["tables"][restore_plan.REVISION_TABLE]["rows"] = []
    with pytest.raises(ValueError, match="exactly the supported revision"):
        restore_plan.plan_restore(package, restored_at=RESTORED_AT)

    package = empty_package()
    package["tables"][restore_plan.REVISION_TABLE]["rows"].append([SUPPORTED_REVISION])
    with pytest.raises(ValueError, match="exactly the supported revision"):
        restore_plan.plan_restore(package, restored_at=RESTORED_AT)

    package = empty_package()
    package["tables"][restore_plan.REVISION_TABLE]["rows"] = [["20261011_0004"]]
    with pytest.raises(ValueError, match="exactly the supported revision"):
        restore_plan.plan_restore(package, restored_at=RESTORED_AT)


def test_table_and_column_manifest_must_match_trusted_models():
    package = empty_package()
    package["tables"].pop("roles")
    with pytest.raises(ValueError, match="table manifest mismatch"):
        restore_plan.plan_restore(package, restored_at=RESTORED_AT)

    package = empty_package()
    package["tables"]["accounts"]["columns"].append("untrusted_column")
    with pytest.raises(ValueError, match="column manifest mismatch for accounts"):
        restore_plan.plan_restore(package, restored_at=RESTORED_AT)


def test_active_sessions_receive_explicit_utc_revoke_transform_without_input_mutation():
    package = empty_package()
    add_row(package, "accounts", account_row())
    session = {
        "id": 10,
        "public_id": "60000000-0000-4000-8000-000000000010",
        "created_at": STAMP,
        "updated_at": STAMP,
        "account_id": 1,
        "active_school_id": None,
        "active_membership_role_id": None,
        "session_token_hash": b"s" * 32,
        "csrf_token_hash": b"c" * 32,
        "user_agent_hash": None,
        "last_seen_at": STAMP,
        "idle_expires_at": STAMP + timedelta(days=1),
        "absolute_expires_at": STAMP + timedelta(days=2),
        "revoked_at": None,
        "revocation_reason": None,
    }
    add_row(package, "auth_sessions", session)
    package_before = deepcopy(package)

    plan = restore_plan.plan_restore(package, restored_at=RESTORED_AT)
    table = plan["tables"]["auth_sessions"]
    planned_row = dict(zip(table["columns"], table["rows"][0], strict=True))

    assert plan["revoked_session_count"] == 1
    assert planned_row["revoked_at"] == RESTORED_AT.replace(tzinfo=None)
    assert planned_row["revocation_reason"] == "RECOVERY_RELOGIN_REQUIRED"
    assert package == package_before


def test_existing_revocations_are_preserved_and_not_counted_twice():
    package = empty_package()
    add_row(package, "accounts", account_row())
    already_revoked_at = STAMP - timedelta(hours=1)
    add_row(
        package,
        "auth_sessions",
        {
            "id": 11,
            "public_id": "60000000-0000-4000-8000-000000000011",
            "created_at": STAMP,
            "updated_at": STAMP,
            "account_id": 1,
            "active_school_id": None,
            "active_membership_role_id": None,
            "session_token_hash": b"t" * 32,
            "csrf_token_hash": None,
            "user_agent_hash": None,
            "last_seen_at": STAMP,
            "idle_expires_at": STAMP + timedelta(days=1),
            "absolute_expires_at": STAMP + timedelta(days=2),
            "revoked_at": already_revoked_at,
            "revocation_reason": "USER_LOGOUT",
        },
    )

    plan = restore_plan.plan_restore(package, restored_at=RESTORED_AT)
    table = plan["tables"]["auth_sessions"]
    planned_row = dict(zip(table["columns"], table["rows"][0], strict=True))

    assert plan["revoked_session_count"] == 0
    assert planned_row["revoked_at"] == already_revoked_at
    assert planned_row["revocation_reason"] == "USER_LOGOUT"


@pytest.mark.parametrize(
    "restored_at",
    [
        datetime(2026, 10, 12),  # noqa: DTZ001 - Explicitly tests rejected naive input.
        datetime(2026, 10, 12, tzinfo=timezone(timedelta(hours=1))),
    ],
)
def test_restore_time_must_be_explicit_utc(restored_at):
    with pytest.raises(ValueError, match="restored_at"):
        restore_plan.plan_restore(empty_package(), restored_at=restored_at)


def test_parent_first_sort_rejects_cycles():
    cyclic = {
        "a": restore_plan.TableSpec(
            ("id", "b_id"), frozenset(), ("id",),
            (restore_plan.ForeignKeySpec(("b_id",), "b", ("id",)),),
        ),
        "b": restore_plan.TableSpec(
            ("id", "a_id"), frozenset(), ("id",),
            (restore_plan.ForeignKeySpec(("a_id",), "a", ("id",)),),
        ),
        restore_plan.REVISION_TABLE: restore_plan.TableSpec(
            ("version_num",), frozenset(), ("version_num",)
        ),
    }

    with pytest.raises(ValueError, match="dependency cycle"):
        restore_plan._parent_first_order(cyclic)
