"""Trusted physical CHECK names emitted by the pinned Alembic migrations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import CheckConstraint, Column, Integer, MetaData, Table
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

# These are the explicit ``name=`` arguments in 20261011_0003 and the later
# 20261011_0004 provenance replacement. Alembic applies the configured
# ``ck_%(table_name)s_%(constraint_name)s`` convention to those already
# table-qualified names. Keep this allowlist source-bound; never learn names
# from an inspected database.
LEGACY_CHECK_NAME_DECLARATIONS: Mapping[str, tuple[str, ...]] = {
    "schools": (
        "ck_schools_status_allowed",
        "ck_schools_data_origin_allowed",
        "ck_schools_provenance_ref_token",
    ),
    "account_school_memberships": (
        "ck_account_school_memberships_status_allowed",
        "ck_account_school_memberships_validity_ordered",
    ),
    "membership_roles": (
        "ck_membership_roles_role_allowed",
        "ck_membership_roles_status_allowed",
        "ck_membership_roles_validity_ordered",
    ),
    "auth_sessions": ("ck_auth_sessions_active_context_complete",),
}

# These trusted revisions declare the affected table CHECK names explicitly.
# Only canonical names present as string literals in the table's listed
# migration sources are eligible for the MySQL naming-convention projection.
MIGRATION_CHECK_NAME_SOURCES: Mapping[str, tuple[str, ...]] = {
    "school_independent_education_reviews": (
        "20261016_0024_student_independent_education_reviews.py",
    ),
    "school_independent_education_review_events": (
        "20261016_0024_student_independent_education_reviews.py",
    ),
    "school_conversation_safety_cases": ("20261015_0019_school_conversation_safety_cases.py",),
    "school_conversation_safety_events": ("20261015_0019_school_conversation_safety_cases.py",),
    "school_research_case_assignments": (
        "20261014_0014_public_observed_case_assignments.py",
        "20261014_0015_sealed_research_cohorts.py",
    ),
    "school_research_cohort_assignments": ("20261014_0015_sealed_research_cohorts.py",),
    "school_research_cohort_batches": ("20261014_0015_sealed_research_cohorts.py",),
    "school_research_cohorts": ("20261014_0015_sealed_research_cohorts.py",),
    "school_research_education_candidate_events": (
        "20261015_0020_school_research_education_candidates.py",
    ),
    "school_research_education_candidates": (
        "20261015_0020_school_research_education_candidates.py",
        "20261015_0022_research_education_input_review_continuation.py",
    ),
    "school_research_education_input_review_events": (
        "20261015_0021_school_research_education_input_reviews.py",
        "20261015_0022_research_education_input_review_continuation.py",
    ),
    "school_research_education_input_reviews": (
        "20261015_0021_school_research_education_input_reviews.py",
        "20261015_0022_research_education_input_review_continuation.py",
    ),
    "school_research_education_jobs": (
        "20261014_0016_research_education_jobs.py",
        "20261015_0020_school_research_education_candidates.py",
        "20261015_0021_school_research_education_input_reviews.py",
        "20261015_0022_research_education_input_review_continuation.py",
    ),
    "school_research_feedback_events": ("20261014_0017_research_review_feedback.py",),
    "school_research_feedback_records": (
        "20261014_0017_research_review_feedback.py",
        "20261015_0020_school_research_education_candidates.py",
    ),
    "school_research_programme_candidates": ("20261014_0018_research_programme_candidates.py",),
    "school_research_review_cases": ("20261014_0017_research_review_feedback.py",),
    "school_research_review_events": ("20261014_0017_research_review_feedback.py",),
    "school_research_task_bindings": (
        "20261014_0012_research_cat_sessions.py",
        "20261014_0013_research_parameter_provenance.py",
        "20261014_0014_public_observed_case_assignments.py",
        "20261014_0015_sealed_research_cohorts.py",
        "20261014_0018_research_programme_candidates.py",
    ),
}

# A small number of trusted revisions used short batch-operation names or
# manually shortened names before the ORM's canonical full names were adopted.
# Keep each source declaration explicit; do not infer a name by stripping a
# table prefix or by observing the live database.
MIGRATION_CHECK_NAME_DECLARATIONS: Mapping[str, Mapping[str, str]] = {
    "school_research_case_assignments": {
        "ck_school_research_case_assignments_response_origin_public_observed": (
            "response_origin_public_observed"
        ),
    },
    "school_research_education_candidate_events": {
        "ck_school_research_education_candidate_events_from_status_allowed": (
            "ck_school_research_education_candidate_events_from_statu_9335"
        ),
        "ck_school_research_education_candidate_events_candidate_revision_fixed": (
            "ck_school_research_education_candidate_events_candidate__b62a"
        ),
        "ck_school_research_education_candidate_events_state_version_allowed": (
            "ck_school_research_education_candidate_events_state_vers_9036"
        ),
        "ck_school_research_education_candidate_events_event_shape_matches_transition": (
            "ck_school_research_education_candidate_events_event_shap_1daf"
        ),
    },
    "school_research_education_input_reviews": {
        "ck_school_research_education_input_reviews_original_job_round_zero": (
            "ck_school_research_education_input_reviews_original_round_zero"
        ),
    },
    "school_research_feedback_records": {
        "ck_school_research_feedback_records_source_candidate_pair_matches": (
            "source_candidate_pair_matches"
        ),
    },
}

_NAMING_CONVENTION = {"ck": "ck_%(table_name)s_%(constraint_name)s"}
_CONSTRAINT_PATTERN = re.compile(
    r"\bCONSTRAINT\s+`?([A-Za-z0-9_]+)`?\s+CHECK\b", re.IGNORECASE
)


def legacy_school_check_names() -> dict[str, dict[str, str]]:
    """Return physical legacy name -> canonical name from old migrations."""

    aliases: dict[str, dict[str, str]] = {}
    for table_name, declarations in LEGACY_CHECK_NAME_DECLARATIONS.items():
        table_aliases: dict[str, str] = {}
        for declaration in declarations:
            physical_name = _mysql_check_name(table_name, declaration)
            if physical_name == declaration or physical_name in table_aliases:
                raise RuntimeError("ambiguous trusted legacy CHECK name")
            table_aliases[physical_name] = declaration
        aliases[table_name] = table_aliases
    return aliases


def source_derived_school_check_names(
    expected: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, str]]:
    """Return exact MySQL aliases for names declared by trusted migrations.

    Compiling a real ``CheckConstraint`` through SQLAlchemy's MySQL dialect
    applies both the metadata naming convention and that dialect's 64-character
    constraint-name truncation/hash rule. This keeps long-name aliases tied to
    the installed, pinned SQLAlchemy behavior rather than live database data.
    A source declaration must be a quoted literal in the allowlisted migration
    files for that exact table; expressions and enforcement are still checked
    by the caller against the trusted ORM contract.
    """

    aliases = legacy_school_check_names()
    migration_root = Path(__file__).resolve().parents[1] / "11_database" / "migrations" / "versions"
    for table_name, filenames in MIGRATION_CHECK_NAME_SOURCES.items():
        expected_table = expected.get(table_name)
        if expected_table is None:
            continue
        source_texts = []
        for filename in filenames:
            path = (migration_root / filename).resolve(strict=True)
            if migration_root.resolve(strict=True) not in path.parents:
                raise RuntimeError("trusted migration path escaped source root")
            source_texts.append(path.read_text(encoding="utf-8"))
        table_aliases = aliases.setdefault(table_name, {})
        for canonical_name, _expression, _enforced in expected_table.get("checks", set()):
            declared_name = MIGRATION_CHECK_NAME_DECLARATIONS.get(
                table_name, {}
            ).get(canonical_name, canonical_name)
            declaration = f'"{declared_name}"'
            single_quoted_declaration = f"'{declared_name}'"
            if not any(
                declaration in source or single_quoted_declaration in source
                for source in source_texts
            ):
                continue
            physical_name = _mysql_check_name(table_name, declared_name)
            if physical_name == canonical_name:
                continue
            existing = table_aliases.get(physical_name)
            if existing is not None and existing != canonical_name:
                raise RuntimeError("ambiguous trusted migration CHECK name")
            table_aliases[physical_name] = canonical_name
    return aliases


def _mysql_check_name(table_name: str, declaration: str) -> str:
    metadata = MetaData(naming_convention=_NAMING_CONVENTION)
    table = Table(
        table_name,
        metadata,
        Column("_name_probe", Integer, nullable=True),
        CheckConstraint("_name_probe IS NULL", name=declaration),
    )
    ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
    matches = _CONSTRAINT_PATTERN.findall(ddl)
    if len(matches) != 1:
        raise RuntimeError("cannot derive trusted CHECK name")
    return matches[0]
