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
    CURRENT_SCHOOL_REVISION,
    DIRECTORY_SCHOOL_REVISION,
    PROFESSIONAL_REVIEW_REVISION,
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
    assert len(plan["table_order"]) == 39
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
