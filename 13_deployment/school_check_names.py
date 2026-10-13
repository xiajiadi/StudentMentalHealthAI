"""Trusted historical CHECK names emitted by the 20261011_0003 migration."""

from __future__ import annotations

import re
from collections.abc import Mapping

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

_NAMING_CONVENTION = {"ck": "ck_%(table_name)s_%(constraint_name)s"}
_CONSTRAINT_PATTERN = re.compile(
    r"\bCONSTRAINT\s+`?([A-Za-z0-9_]+)`?\s+CHECK\b", re.IGNORECASE
)


def legacy_school_check_names() -> dict[str, dict[str, str]]:
    """Return physical legacy name -> canonical name using MySQL DDL compilation.

    Compiling a real ``CheckConstraint`` through SQLAlchemy's MySQL dialect
    applies both the metadata naming convention and that dialect's 64-character
    constraint-name truncation/hash rule. This keeps long-name aliases tied to
    the installed, pinned SQLAlchemy behavior rather than live database data.
    """

    aliases: dict[str, dict[str, str]] = {}
    dialect = mysql.dialect()
    for table_name, declarations in LEGACY_CHECK_NAME_DECLARATIONS.items():
        table_aliases: dict[str, str] = {}
        for declaration in declarations:
            metadata = MetaData(naming_convention=_NAMING_CONVENTION)
            table = Table(
                table_name,
                metadata,
                Column("_name_probe", Integer, nullable=True),
                CheckConstraint("_name_probe IS NULL", name=declaration),
            )
            ddl = str(CreateTable(table).compile(dialect=dialect))
            matches = _CONSTRAINT_PATTERN.findall(ddl)
            if len(matches) != 1:
                raise RuntimeError("cannot derive trusted legacy CHECK name")
            legacy_name = matches[0]
            canonical_name = declaration
            if legacy_name == canonical_name or legacy_name in table_aliases:
                raise RuntimeError("ambiguous trusted legacy CHECK name")
            table_aliases[legacy_name] = canonical_name
        aliases[table_name] = table_aliases
    return aliases
