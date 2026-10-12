"""Relational persistence schema.

The model deliberately keeps operational state queryable while placing
assessment answers, support content, safety detail and review notes in
application-encrypted binary columns.  There are no clinical label columns.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BINARY,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from .base import (
    Base,
    ResourceIdentityMixin,
    TimestampMixin,
    ascii_id,
    mysql_table_args,
    unsigned_id,
    utc_datetime,
    utc_now,
)
from .enums import (
    AccountStatus,
    AssessmentStatus,
    DataOrigin,
    GrantStatus,
    IdempotencyState,
    ReviewPriority,
    ReviewStatus,
    SubjectStatus,
    SupportRunStatus,
    SupportStatus,
)
from .provenance import SCHOOL_PROVENANCE_CHECK_VALUES


class Account(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "accounts"
    __table_args__ = mysql_table_args(
        CheckConstraint("status IN ('ACTIVE', 'SUSPENDED', 'DISABLED')", name="status_allowed"),
    )

    login_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AccountStatus.ACTIVE.value
    )


class Role(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "roles"
    __table_args__ = mysql_table_args(
        CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name="status_allowed"),
    )

    role_code: Mapped[str] = mapped_column(ascii_id(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")


class School(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "schools"
    __table_args__ = mysql_table_args(
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="status_allowed"),
        CheckConstraint(
            "data_origin IN ('SYNTHETIC', 'PRODUCTION_PENDING')",
            name="data_origin_allowed",
        ),
        CheckConstraint(
            f"provenance_ref IN ({SCHOOL_PROVENANCE_CHECK_VALUES})",
            name="provenance_ref_token",
        ),
    )

    school_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    data_origin: Mapped[str] = mapped_column(String(24), nullable=False)
    provenance_ref: Mapped[str] = mapped_column(ascii_id(48), nullable=False)


class AccountSchoolMembership(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "account_school_memberships"
    __table_args__ = mysql_table_args(
        UniqueConstraint("account_id", "school_id", name="account_school_unique"),
        UniqueConstraint("id", "school_id", name="membership_id_school_unique"),
        UniqueConstraint("id", "account_id", "school_id", name="membership_account_school_unique"),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE', 'REVOKED')", name="status_allowed"),
        CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from", name="validity_ordered"
        ),
        Index("ix_memberships_account_status", "account_id", "status"),
        Index("ix_memberships_school_status", "school_id", "status"),
    )

    account_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey("accounts.id", ondelete="RESTRICT", name="fk_memberships_account"),
        nullable=False,
    )
    school_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey("schools.id", ondelete="RESTRICT", name="fk_memberships_school"),
        nullable=False,
    )
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    valid_from: Mapped[datetime] = mapped_column(utc_datetime(), nullable=False, default=utc_now)
    valid_until: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class MembershipRole(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "membership_roles"
    __table_args__ = mysql_table_args(
        UniqueConstraint("membership_id", "role_code", name="membership_role_unique"),
        UniqueConstraint("id", "school_id", name="membership_role_id_school_unique"),
        UniqueConstraint("id", "membership_id", "school_id", name="role_membership_school_unique"),
        ForeignKeyConstraint(
            ["membership_id", "school_id"],
            ["account_school_memberships.id", "account_school_memberships.school_id"],
            name="fk_membership_roles_membership_school",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "role_code IN ('student', 'teacher', 'psychological_specialist', 'admin')",
            name="role_allowed",
        ),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE', 'REVOKED')", name="status_allowed"),
        CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from", name="validity_ordered"
        ),
        Index("ix_membership_roles_membership_status", "membership_id", "status"),
    )

    membership_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey(
            "account_school_memberships.id",
            ondelete="RESTRICT",
            name="fk_membership_roles_membership",
        ),
        nullable=False,
    )
    school_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey("schools.id", ondelete="RESTRICT", name="fk_membership_roles_school"),
        nullable=False,
    )
    role_code: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    valid_from: Mapped[datetime] = mapped_column(utc_datetime(), nullable=False, default=utc_now)
    valid_until: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class SchoolAccountBatch(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "school_account_batches"
    __table_args__ = mysql_table_args(
        UniqueConstraint("batch_ref", name="school_account_batch_ref_unique"),
        UniqueConstraint("id", "school_id", name="school_account_batch_id_school_unique"),
        ForeignKeyConstraint(
            ["created_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_account_batches_creator_role_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["school_classes.id", "school_classes.school_id"],
            name="fk_school_account_batches_class_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["school_id"], ["schools.id"], name="fk_school_account_batches_school",
            ondelete="RESTRICT",
        ),
        CheckConstraint("row_count BETWEEN 1 AND 100", name="row_count_allowed"),
        Index("ix_school_account_batches_school_created", "school_id", "created_at"),
    )

    batch_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    created_by_membership_role_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    class_id: Mapped[int | None] = mapped_column(unsigned_id(), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)


class SchoolAccountProvision(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "school_account_provisions"
    __table_args__ = mysql_table_args(
        UniqueConstraint("account_id", name="school_account_provision_account_unique"),
        UniqueConstraint(
            "batch_id", "row_no", name="school_account_provision_batch_row_unique"
        ),
        ForeignKeyConstraint(
            ["batch_id", "school_id"],
            ["school_account_batches.id", "school_account_batches.school_id"],
            name="fk_school_account_provisions_batch_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["membership_id", "account_id", "school_id"],
            [
                "account_school_memberships.id", "account_school_memberships.account_id",
                "account_school_memberships.school_id",
            ],
            name="fk_school_account_provisions_membership_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["membership_role_id", "membership_id", "school_id"],
            ["membership_roles.id", "membership_roles.membership_id", "membership_roles.school_id"],
            name="fk_school_account_provisions_role_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name="fk_school_account_provisions_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["school_id"], ["schools.id"], name="fk_school_account_provisions_school",
            ondelete="RESTRICT",
        ),
        CheckConstraint("role_code IN ('student', 'teacher')", name="role_allowed"),
        CheckConstraint(
            "status IN ('PENDING_ACTIVATION', 'ACTIVE')", name="status_allowed"
        ),
        CheckConstraint(
            "(status = 'PENDING_ACTIVATION' AND activated_at IS NULL) OR "
            "(status = 'ACTIVE' AND activated_at IS NOT NULL)",
            name="activation_matches_status",
        ),
        Index("ix_school_account_provisions_school_status", "school_id", "status"),
    )

    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    batch_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    account_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    membership_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    membership_role_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    role_code: Mapped[str] = mapped_column(ascii_id(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class AccountRole(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "account_roles"
    __table_args__ = mysql_table_args(
        UniqueConstraint("account_id", "role_id", name="account_role_unique"),
        CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name="status_allowed"),
        Index("ix_account_roles_account_status", "account_id", "status"),
    )

    account_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey("accounts.id", ondelete="RESTRICT", name="fk_account_roles_account"),
        nullable=False,
    )
    role_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey("roles.id", ondelete="RESTRICT", name="fk_account_roles_role"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    granted_at: Mapped[datetime] = mapped_column(utc_datetime(), nullable=False, default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class Subject(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "subjects"
    __table_args__ = mysql_table_args(
        CheckConstraint("status IN ('ACTIVE', 'ARCHIVED', 'ERASED')", name="status_allowed"),
        CheckConstraint(
            "data_origin IN ('SYNTHETIC', 'PRODUCTION_PENDING')", name="data_origin_allowed"
        ),
        UniqueConstraint("id", "school_id", name="subject_id_school_unique"),
    )

    subject_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False, unique=True)
    school_id: Mapped[int | None] = mapped_column(
        unsigned_id(), ForeignKey("schools.id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SubjectStatus.ACTIVE.value
    )
    data_origin: Mapped[str] = mapped_column(
        String(24), nullable=False, default=DataOrigin.SYNTHETIC.value
    )
    retention_due_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    erased_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class SubjectAccessGrant(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "subject_access_grants"
    __table_args__ = mysql_table_args(
        CheckConstraint(
            "relationship_type IN ('SELF', 'TEACHER_OF', 'GUARDIAN_OF', 'REVIEW_ASSIGNMENT')",
            name="relationship_allowed",
        ),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE', 'REVOKED')", name="status_allowed"),
        CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from", name="validity_ordered"
        ),
        Index(
            "ix_subject_access_grants_principal_subject_status",
            "principal_account_id",
            "subject_id",
            "status",
        ),
        Index("ix_subject_grants_school_subject_status", "school_id", "subject_id", "status"),
        ForeignKeyConstraint(
            ["subject_id", "school_id"],
            ["subjects.id", "subjects.school_id"],
            name="fk_subject_grants_subject_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["principal_account_id", "school_id"],
            ["account_school_memberships.account_id", "account_school_memberships.school_id"],
            name="fk_subject_grants_membership_school",
            ondelete="RESTRICT",
        ),
    )

    principal_account_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey("accounts.id", ondelete="RESTRICT", name="fk_subject_access_grants_account"),
        nullable=False,
    )
    subject_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey("subjects.id", ondelete="RESTRICT", name="fk_subject_access_grants_subject"),
        nullable=False,
    )
    school_id: Mapped[int | None] = mapped_column(
        unsigned_id(), ForeignKey("schools.id", ondelete="RESTRICT"), nullable=True
    )
    relationship_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=GrantStatus.ACTIVE.value
    )
    valid_from: Mapped[datetime] = mapped_column(utc_datetime(), nullable=False, default=utc_now)
    valid_until: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class SchoolClass(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "school_classes"
    __table_args__ = mysql_table_args(
        UniqueConstraint("school_id", "class_ref", name="school_class_ref_unique"),
        UniqueConstraint("id", "school_id", name="school_class_id_school_unique"),
        ForeignKeyConstraint(
            ["created_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_classes_creator_role_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["school_id"], ["schools.id"], name="fk_school_classes_school", ondelete="RESTRICT"
        ),
        CheckConstraint("status IN ('ACTIVE', 'ARCHIVED')", name="status_allowed"),
        Index("ix_school_classes_school_status", "school_id", "status"),
    )

    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    class_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_by_membership_role_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )


class SchoolClassStudent(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "school_class_students"
    __table_args__ = mysql_table_args(
        UniqueConstraint("class_id", "subject_id", name="school_class_student_unique"),
        UniqueConstraint(
            "id", "subject_id", "class_id", "school_id", name="class_student_subject_scope_unique"
        ),
        ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["school_classes.id", "school_classes.school_id"],
            name="fk_class_students_class_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["subject_id", "school_id"],
            ["subjects.id", "subjects.school_id"],
            name="fk_class_students_subject_school",
            ondelete="RESTRICT",
        ),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE', 'REVOKED')", name="status_allowed"),
        CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from", name="validity_ordered"
        ),
        CheckConstraint(
            "revoked_at IS NULL OR status = 'REVOKED'", name="revocation_matches_status"
        ),
        Index("ix_class_students_school_class_status", "school_id", "class_id", "status"),
        Index("ix_class_students_subject_status", "subject_id", "status"),
    )

    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    class_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    subject_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    valid_from: Mapped[datetime] = mapped_column(utc_datetime(), nullable=False, default=utc_now)
    valid_until: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class SchoolClassTeacher(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "school_class_teachers"
    __table_args__ = mysql_table_args(
        UniqueConstraint("class_id", "membership_role_id", name="school_class_teacher_unique"),
        UniqueConstraint(
            "id", "class_id", "school_id", name="class_teacher_scope_unique"
        ),
        ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["school_classes.id", "school_classes.school_id"],
            name="fk_class_teachers_class_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_class_teachers_role_school",
            ondelete="RESTRICT",
        ),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE', 'REVOKED')", name="status_allowed"),
        CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from", name="validity_ordered"
        ),
        CheckConstraint(
            "revoked_at IS NULL OR status = 'REVOKED'", name="revocation_matches_status"
        ),
        Index("ix_class_teachers_school_class_status", "school_id", "class_id", "status"),
        Index("ix_class_teachers_role_status", "membership_role_id", "status"),
    )

    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    class_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    membership_role_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    valid_from: Mapped[datetime] = mapped_column(utc_datetime(), nullable=False, default=utc_now)
    valid_until: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class MeasurementTask(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "measurement_tasks"
    __table_args__ = mysql_table_args(
        UniqueConstraint("task_ref", name="measurement_task_ref_unique"),
        UniqueConstraint(
            "id", "school_id", "class_id", name="measurement_task_scope_unique"
        ),
        ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["school_classes.id", "school_classes.school_id"],
            name="fk_measurement_tasks_class_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_measurement_tasks_creator_role_school",
            ondelete="RESTRICT",
        ),
        CheckConstraint("status IN ('PUBLISHED', 'CLOSED', 'CANCELLED')", name="status_allowed"),
        CheckConstraint("due_at IS NULL OR due_at >= opens_at", name="task_window_ordered"),
        Index("ix_measurement_tasks_school_class_status", "school_id", "class_id", "status"),
        Index("ix_measurement_tasks_open_due", "status", "opens_at", "due_at"),
    )

    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    class_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    task_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    created_by_membership_role_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    instrument_id: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    instrument_version: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    item_bank_version: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    config_version: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    opens_at: Mapped[datetime] = mapped_column(utc_datetime(), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    published_at: Mapped[datetime] = mapped_column(utc_datetime(), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PUBLISHED", server_default="PUBLISHED"
    )


class TaskEnrollment(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "task_enrollments"
    __table_args__ = mysql_table_args(
        UniqueConstraint("task_id", "class_student_id", name="task_student_enrollment_unique"),
        UniqueConstraint("id", "subject_id", name="task_enrollment_subject_unique"),
        ForeignKeyConstraint(
            ["task_id", "school_id", "class_id"],
            ["measurement_tasks.id", "measurement_tasks.school_id", "measurement_tasks.class_id"],
            name="fk_task_enrollments_task_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["class_student_id", "subject_id", "class_id", "school_id"],
            [
                "school_class_students.id",
                "school_class_students.subject_id",
                "school_class_students.class_id",
                "school_class_students.school_id",
            ],
            name="fk_task_enrollments_roster_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name="status_allowed"),
        CheckConstraint(
            "revoked_at IS NULL OR status = 'REVOKED'", name="revocation_matches_status"
        ),
        Index("ix_task_enrollments_school_task_status", "school_id", "task_id", "status"),
        Index("ix_task_enrollments_student_status", "class_student_id", "status"),
    )

    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    task_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    class_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    class_student_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    subject_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    revoked_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class ConsentRecord(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "consent_records"
    __table_args__ = mysql_table_args(
        CheckConstraint(
            "status IN ('GRANTED', 'WITHDRAWN', 'EXPIRED', 'REVOKED')", name="status_allowed"
        ),
        Index("ix_consent_records_subject_type", "subject_id", "consent_type", "created_at"),
    )

    subject_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey("subjects.id", ondelete="RESTRICT", name="fk_consent_records_subject"),
        nullable=False,
    )
    consent_type: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    policy_version: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    scope_identifier: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    granted_by_account_id: Mapped[int | None] = mapped_column(
        unsigned_id(),
        ForeignKey("accounts.id", ondelete="RESTRICT", name="fk_consent_records_granted_by"),
        nullable=True,
    )
    granted_by_relationship: Mapped[str | None] = mapped_column(String(32), nullable=True)
    granted_at: Mapped[datetime] = mapped_column(utc_datetime(), nullable=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(ascii_id(128), nullable=True)
    retention_due_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class AuthSession(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "auth_sessions"
    __table_args__ = mysql_table_args(
        UniqueConstraint("session_token_hash", name="session_token_hash_unique"),
        Index("ix_auth_sessions_account_active", "account_id", "revoked_at", "absolute_expires_at"),
        CheckConstraint(
            "(active_membership_role_id IS NULL AND active_school_id IS NULL) OR "
            "(active_membership_role_id IS NOT NULL AND active_school_id IS NOT NULL)",
            name="active_context_complete",
        ),
        ForeignKeyConstraint(
            ["active_membership_role_id", "active_school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_auth_sessions_active_role_school",
            ondelete="RESTRICT",
        ),
    )

    account_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey("accounts.id", ondelete="RESTRICT", name="fk_auth_sessions_account"),
        nullable=False,
    )
    active_school_id: Mapped[int | None] = mapped_column(unsigned_id(), nullable=True)
    active_membership_role_id: Mapped[int | None] = mapped_column(unsigned_id(), nullable=True)
    session_token_hash: Mapped[bytes] = mapped_column(BINARY(32), nullable=False)
    csrf_token_hash: Mapped[bytes | None] = mapped_column(BINARY(32), nullable=True)
    user_agent_hash: Mapped[bytes | None] = mapped_column(BINARY(32), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(utc_datetime(), nullable=False, default=utc_now)
    idle_expires_at: Mapped[datetime] = mapped_column(utc_datetime(), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(utc_datetime(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)


class AssessmentSession(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "assessment_sessions"
    __table_args__ = mysql_table_args(
        CheckConstraint(
            "status IN ('CREATED', 'IN_PROGRESS', 'COMPLETED', 'ABANDONED', 'INVALID')",
            name="status_allowed",
        ),
        Index("ix_assessment_sessions_subject_created", "subject_id", "created_at"),
        Index("ix_assessment_sessions_status_created", "status", "created_at"),
        UniqueConstraint("task_enrollment_id", name="assessment_task_enrollment_unique"),
        UniqueConstraint("id", "subject_id", name="assessment_session_subject_unique"),
        ForeignKeyConstraint(
            ["task_enrollment_id", "subject_id"],
            ["task_enrollments.id", "task_enrollments.subject_id"],
            name="fk_assessment_sessions_task_enrollment_subject",
            ondelete="RESTRICT",
        ),
    )

    assessment_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False, unique=True)
    subject_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey("subjects.id", ondelete="RESTRICT", name="fk_assessment_sessions_subject"),
        nullable=False,
    )
    task_enrollment_id: Mapped[int | None] = mapped_column(unsigned_id(), nullable=True)
    instrument_id: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    instrument_version: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    item_bank_version: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    config_version: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    schema_version: Mapped[str] = mapped_column(
        ascii_id(64), nullable=False, default="assessment.v1"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AssessmentStatus.CREATED.value
    )
    started_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(ascii_id(128), nullable=True)
    retention_due_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class AssessmentResponse(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "assessment_responses"
    __table_args__ = mysql_table_args(
        UniqueConstraint("assessment_session_id", "sequence_no", name="session_sequence_unique"),
        UniqueConstraint("assessment_session_id", "item_ref", name="session_item_unique"),
        Index("ix_assessment_responses_session_sequence", "assessment_session_id", "sequence_no"),
    )

    assessment_session_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey(
            "assessment_sessions.id", ondelete="RESTRICT", name="fk_assessment_responses_session"
        ),
        nullable=False,
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    item_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    response_ciphertext: Mapped[bytes | None] = mapped_column(mysql.MEDIUMBLOB, nullable=True)
    cipher_format_version: Mapped[str | None] = mapped_column(ascii_id(32), nullable=True)
    key_version: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    payload_schema_version: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(ascii_id(128), nullable=True)
    retention_due_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class AssessmentResult(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "assessment_results"
    __table_args__ = mysql_table_args(
        UniqueConstraint("assessment_session_id", name="session_result_unique"),
        Index("ix_assessment_results_retention", "retention_due_at"),
    )

    assessment_session_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey(
            "assessment_sessions.id", ondelete="RESTRICT", name="fk_assessment_results_session"
        ),
        nullable=False,
    )
    schema_version: Mapped[str] = mapped_column(
        ascii_id(64), nullable=False, default="assessment.v1"
    )
    payload_ciphertext: Mapped[bytes | None] = mapped_column(mysql.MEDIUMBLOB, nullable=True)
    cipher_format_version: Mapped[str | None] = mapped_column(ascii_id(32), nullable=True)
    key_version: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    payload_schema_version: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    retention_due_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class SupportSession(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "support_sessions"
    __table_args__ = mysql_table_args(
        CheckConstraint(
            "status IN ('OPEN', 'ACTIVE', 'CLOSED', 'ARCHIVED')", name="status_allowed"
        ),
        Index("ix_support_sessions_subject_created", "subject_id", "created_at"),
    )

    support_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False, unique=True)
    subject_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey("subjects.id", ondelete="RESTRICT", name="fk_support_sessions_subject"),
        nullable=False,
    )
    assessment_session_id: Mapped[int | None] = mapped_column(
        unsigned_id(),
        ForeignKey(
            "assessment_sessions.id", ondelete="RESTRICT", name="fk_support_sessions_assessment"
        ),
        nullable=True,
    )
    target_role: Mapped[str] = mapped_column(ascii_id(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SupportStatus.OPEN.value
    )
    started_at: Mapped[datetime] = mapped_column(utc_datetime(), nullable=False, default=utc_now)
    closed_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(ascii_id(128), nullable=True)
    retention_due_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class SupportMessage(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "support_messages"
    __table_args__ = mysql_table_args(
        CheckConstraint(
            "message_kind IN ('USER_INPUT', 'APPROVED_OUTPUT')", name="message_kind_allowed"
        ),
        UniqueConstraint("support_session_id", "sequence_no", name="support_sequence_unique"),
        Index("ix_support_messages_session_created", "support_session_id", "created_at"),
    )

    support_session_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey("support_sessions.id", ondelete="RESTRICT", name="fk_support_messages_session"),
        nullable=False,
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    message_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    payload_ciphertext: Mapped[bytes | None] = mapped_column(mysql.MEDIUMBLOB, nullable=True)
    cipher_format_version: Mapped[str | None] = mapped_column(ascii_id(32), nullable=True)
    key_version: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    payload_schema_version: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    safety_decision_id: Mapped[int | None] = mapped_column(
        unsigned_id(),
        ForeignKey("safety_decisions.id", ondelete="RESTRICT", name="fk_support_messages_safety"),
        nullable=True,
    )
    retention_due_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class SupportRun(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "support_runs"
    __table_args__ = mysql_table_args(
        CheckConstraint(
            "status IN ('REQUESTED', 'COMPLETED', 'BLOCKED', 'FAILED')", name="status_allowed"
        ),
        Index("ix_support_runs_session_created", "support_session_id", "created_at"),
        Index("ix_support_runs_trace", "trace_id"),
    )

    run_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False, unique=True)
    support_session_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey("support_sessions.id", ondelete="RESTRICT", name="fk_support_runs_session"),
        nullable=False,
    )
    assessment_session_id: Mapped[int | None] = mapped_column(
        unsigned_id(),
        ForeignKey(
            "assessment_sessions.id", ondelete="RESTRICT", name="fk_support_runs_assessment"
        ),
        nullable=True,
    )
    generation_ref: Mapped[str | None] = mapped_column(ascii_id(128), nullable=True)
    retrieval_ref: Mapped[str | None] = mapped_column(ascii_id(128), nullable=True)
    trace_id: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SupportRunStatus.REQUESTED.value
    )
    workflow_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    component_versions: Mapped[dict[str, object] | None] = mapped_column(mysql.JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retention_due_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class SupportEvidence(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "support_evidence"
    __table_args__ = mysql_table_args(
        UniqueConstraint("support_run_id", "citation_id", name="support_citation_unique"),
        Index("ix_support_evidence_run_rank", "support_run_id", "rank_order"),
    )

    support_run_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey("support_runs.id", ondelete="RESTRICT", name="fk_support_evidence_run"),
        nullable=False,
    )
    citation_id: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    source_id: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    chunk_id: Mapped[str | None] = mapped_column(ascii_id(128), nullable=True)
    document_id: Mapped[str | None] = mapped_column(ascii_id(128), nullable=True)
    source_version: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    source_hash: Mapped[str | None] = mapped_column(ascii_id(128), nullable=True)
    citation_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    citation_organization: Mapped[str | None] = mapped_column(String(512), nullable=True)
    locator: Mapped[str | None] = mapped_column(String(512), nullable=True)
    rank_order: Mapped[int] = mapped_column(Integer, nullable=False)


class SafetyDecision(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "safety_decisions"
    __table_args__ = mysql_table_args(
        CheckConstraint(
            "action IN ("
            "'PROCEED', 'PROCEED_WITH_BOUNDARY', 'BLOCK', 'REVIEW_REQUIRED', 'CRISIS_ROUTE'"
            ")",
            name="action_allowed",
        ),
        Index("ix_safety_decisions_run_created", "support_run_id", "created_at"),
    )

    decision_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False, unique=True)
    support_run_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey("support_runs.id", ondelete="RESTRICT", name="fk_safety_decisions_run"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    guard_model_revision: Mapped[str | None] = mapped_column(ascii_id(128), nullable=True)
    trace_id: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    detail_ciphertext: Mapped[bytes | None] = mapped_column(mysql.MEDIUMBLOB, nullable=True)
    cipher_format_version: Mapped[str | None] = mapped_column(ascii_id(32), nullable=True)
    key_version: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    payload_schema_version: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    retention_due_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class ReviewCase(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "review_cases"
    __table_args__ = mysql_table_args(
        CheckConstraint("priority IN ('LOW', 'NORMAL', 'HIGH', 'URGENT')", name="priority_allowed"),
        CheckConstraint(
            "status IN ('OPEN', 'ASSIGNED', 'IN_REVIEW', 'APPROVED', 'REJECTED', 'CLOSED')",
            name="status_allowed",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_review_cases_status_priority_created", "status", "priority", "created_at"),
        Index("ix_review_cases_subject_created", "subject_id", "created_at"),
    )

    review_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False, unique=True)
    subject_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey("subjects.id", ondelete="RESTRICT", name="fk_review_cases_subject"),
        nullable=False,
    )
    safety_decision_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey("safety_decisions.id", ondelete="RESTRICT", name="fk_review_cases_safety"),
        nullable=False,
    )
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ReviewPriority.NORMAL.value
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ReviewStatus.OPEN.value)
    assigned_account_id: Mapped[int | None] = mapped_column(
        unsigned_id(),
        ForeignKey("accounts.id", ondelete="RESTRICT", name="fk_review_cases_assignee"),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    case_note_ciphertext: Mapped[bytes | None] = mapped_column(mysql.MEDIUMBLOB, nullable=True)
    cipher_format_version: Mapped[str | None] = mapped_column(ascii_id(32), nullable=True)
    key_version: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    payload_schema_version: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    retention_due_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class ReviewEvent(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "review_events"
    __table_args__ = mysql_table_args(
        CheckConstraint(
            "event_type IN ("
            "'CREATED', 'ASSIGNED', 'OPENED', 'DECISION_RECORDED', 'ESCALATED', 'CLOSED'"
            ")",
            name="event_type_allowed",
        ),
        Index("ix_review_events_case_created", "review_case_id", "created_at"),
    )

    review_case_id: Mapped[int] = mapped_column(
        unsigned_id(),
        ForeignKey("review_cases.id", ondelete="RESTRICT", name="fk_review_events_case"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_account_id: Mapped[int | None] = mapped_column(
        unsigned_id(),
        ForeignKey("accounts.id", ondelete="RESTRICT", name="fk_review_events_actor"),
        nullable=True,
    )
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    note_ciphertext: Mapped[bytes | None] = mapped_column(mysql.MEDIUMBLOB, nullable=True)
    cipher_format_version: Mapped[str | None] = mapped_column(ascii_id(32), nullable=True)
    key_version: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    payload_schema_version: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(ascii_id(128), nullable=True)
    retention_due_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class IdempotencyRecord(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = mysql_table_args(
        UniqueConstraint("scope", "key_hash", name="scope_key_hash_unique"),
        CheckConstraint("state IN ('IN_PROGRESS', 'COMPLETED', 'FAILED')", name="state_allowed"),
        Index("ix_idempotency_records_scope_key_hash", "scope", "key_hash"),
        Index("ix_idempotency_records_expiry", "expires_at"),
    )

    scope: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    key_hash: Mapped[bytes] = mapped_column(BINARY(32), nullable=False)
    request_hash: Mapped[bytes] = mapped_column(BINARY(32), nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=IdempotencyState.IN_PROGRESS.value
    )
    result_resource_type: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    result_public_id: Mapped[str | None] = mapped_column(ascii_id(128), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(utc_datetime(), nullable=False)


class AuditEvent(ResourceIdentityMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = mysql_table_args(
        CheckConstraint("result IN ('SUCCESS', 'FAILURE', 'DENIED')", name="result_allowed"),
        Index("ix_audit_events_trace", "trace_id"),
        Index("ix_audit_events_resource", "resource_type", "resource_public_id", "created_at"),
    )

    actor_account_id: Mapped[int | None] = mapped_column(
        unsigned_id(),
        ForeignKey("accounts.id", ondelete="RESTRICT", name="fk_audit_events_actor"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    resource_public_id: Mapped[str | None] = mapped_column(ascii_id(128), nullable=True)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    trace_id: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    safe_metadata: Mapped[dict[str, object] | None] = mapped_column(mysql.JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(utc_datetime(), nullable=False, default=utc_now)


__all__ = [
    "Account",
    "AccountRole",
    "AssessmentResponse",
    "AssessmentResult",
    "AssessmentSession",
    "AuditEvent",
    "AuthSession",
    "ConsentRecord",
    "IdempotencyRecord",
    "MeasurementTask",
    "ReviewCase",
    "ReviewEvent",
    "Role",
    "SafetyDecision",
    "SchoolAccountBatch",
    "SchoolAccountProvision",
    "SchoolClass",
    "SchoolClassStudent",
    "SchoolClassTeacher",
    "Subject",
    "SubjectAccessGrant",
    "SupportEvidence",
    "SupportMessage",
    "SupportRun",
    "SupportSession",
    "TaskEnrollment",
]
