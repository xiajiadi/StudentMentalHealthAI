"""Relational persistence schema.

The model deliberately keeps operational state queryable while placing
assessment answers, support content, safety detail and review notes in
application-encrypted binary columns.  There are no clinical label columns.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BINARY,
    Boolean,
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
        UniqueConstraint(
            "id", "school_id", "class_id", name="school_account_batch_id_school_class_unique"
        ),
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
        UniqueConstraint(
            "id", "batch_id", "account_id", "membership_id", "membership_role_id", "school_id",
            name="school_account_provision_cohort_scope_unique",
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
        UniqueConstraint("id", "principal_account_id", "subject_id", "school_id",
                        name="subject_grant_cohort_scope_unique"),
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
        UniqueConstraint("id", "school_id", name="measurement_task_id_school_unique"),
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
        CheckConstraint(
            "cat_binding_mode IN ('FIXTURE', 'SAVED_VERSION', 'RESEARCH_PROFILE')",
            name="cat_binding_mode_allowed",
        ),
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
    cat_binding_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="FIXTURE", server_default="FIXTURE"
    )


class TaskEnrollment(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "task_enrollments"
    __table_args__ = mysql_table_args(
        UniqueConstraint("task_id", "class_student_id", name="task_student_enrollment_unique"),
        UniqueConstraint("id", "subject_id", name="task_enrollment_subject_unique"),
        UniqueConstraint(
            "id", "task_id", "school_id", "subject_id",
            name="task_enrollment_review_scope_unique",
        ),
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
        CheckConstraint(
            "cat_binding_mode IN ('FIXTURE', 'SAVED_VERSION')",
            name="cat_binding_mode_allowed",
        ),
        Index("ix_assessment_sessions_subject_created", "subject_id", "created_at"),
        Index("ix_assessment_sessions_status_created", "status", "created_at"),
        UniqueConstraint("task_enrollment_id", name="assessment_task_enrollment_unique"),
        UniqueConstraint("id", "subject_id", name="assessment_session_subject_unique"),
        UniqueConstraint(
            "id", "task_enrollment_id", "subject_id",
            name="assessment_session_review_scope_unique",
        ),
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
    cat_binding_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="FIXTURE", server_default="FIXTURE"
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


class SchoolTaskSpecialistAssignment(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "school_task_specialist_assignments"
    __table_args__ = mysql_table_args(
        UniqueConstraint(
            "task_id", "specialist_membership_role_id",
            name="school_task_specialist_unique",
        ),
        CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name="status_allowed"),
        CheckConstraint(
            "(status = 'ACTIVE' AND revoked_at IS NULL) OR "
            "(status = 'REVOKED' AND revoked_at IS NOT NULL)",
            name="revocation_matches_status",
        ),
        ForeignKeyConstraint(
            ["task_id", "school_id", "class_id"],
            ["measurement_tasks.id", "measurement_tasks.school_id", "measurement_tasks.class_id"],
            name="fk_school_task_specialist_task_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["specialist_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_task_specialist_specialist_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["assigned_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_task_specialist_assigner_school",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_school_task_specialist_scope_status",
            "school_id", "task_id", "status",
        ),
        Index(
            "ix_school_task_specialist_role_status",
            "specialist_membership_role_id", "status",
        ),
    )

    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    task_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    class_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    specialist_membership_role_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    assigned_by_membership_role_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    revoked_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class SchoolProfessionalReviewCase(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "school_professional_review_cases"
    __table_args__ = mysql_table_args(
        UniqueConstraint("review_ref", name="school_professional_review_ref_unique"),
        UniqueConstraint(
            "task_enrollment_id", name="school_professional_review_enrollment_unique"
        ),
        UniqueConstraint(
            "assessment_session_id", name="school_professional_review_assessment_unique"
        ),
        UniqueConstraint("id", "school_id", name="school_professional_review_id_school_unique"),
        UniqueConstraint(
            "id", "school_id", "task_id", "class_id", "task_enrollment_id", "subject_id",
            "assessment_session_id", name="school_professional_review_feedback_scope_unique",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'IN_REVIEW', 'APPROVED', 'REJECTED')",
            name="status_allowed",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        ForeignKeyConstraint(
            ["task_id", "school_id", "class_id"],
            ["measurement_tasks.id", "measurement_tasks.school_id", "measurement_tasks.class_id"],
            name="fk_school_professional_review_task_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["task_enrollment_id", "task_id", "school_id", "subject_id"],
            [
                "task_enrollments.id",
                "task_enrollments.task_id",
                "task_enrollments.school_id",
                "task_enrollments.subject_id",
            ],
            name="fk_school_professional_review_enrollment_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["assessment_session_id", "task_enrollment_id", "subject_id"],
            [
                "assessment_sessions.id",
                "assessment_sessions.task_enrollment_id",
                "assessment_sessions.subject_id",
            ],
            name="fk_school_professional_review_assessment_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["subject_id", "school_id"],
            ["subjects.id", "subjects.school_id"],
            name="fk_school_professional_review_subject_scope",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_school_professional_review_scope_status",
            "school_id", "task_id", "status", "created_at",
        ),
        Index(
            "ix_school_professional_review_subject_created",
            "subject_id", "created_at",
        ),
    )

    review_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    task_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    class_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    task_enrollment_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    subject_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    assessment_session_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    case_note_ciphertext: Mapped[bytes | None] = mapped_column(mysql.MEDIUMBLOB, nullable=True)
    cipher_format_version: Mapped[str | None] = mapped_column(ascii_id(32), nullable=True)
    key_version: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    payload_schema_version: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    retention_due_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class SchoolProfessionalReviewEvent(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "school_professional_review_events"
    __table_args__ = mysql_table_args(
        UniqueConstraint(
            "review_case_id", "version", name="school_professional_review_event_version_unique"
        ),
        CheckConstraint("event_type IN ('CREATED', 'TRANSITION')", name="event_type_allowed"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "from_status IS NULL OR from_status IN ('OPEN', 'IN_REVIEW', 'APPROVED', 'REJECTED')",
            name="from_status_allowed",
        ),
        CheckConstraint(
            "to_status IN ('OPEN', 'IN_REVIEW', 'APPROVED', 'REJECTED')",
            name="to_status_allowed",
        ),
        ForeignKeyConstraint(
            ["review_case_id", "school_id"],
            ["school_professional_review_cases.id", "school_professional_review_cases.school_id"],
            name="fk_school_professional_review_events_case_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_professional_review_events_actor_school",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_school_professional_review_events_case_created",
            "review_case_id", "created_at",
        ),
    )

    review_case_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    actor_membership_role_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(ascii_id(128), nullable=True)
    retention_due_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class SchoolFeedbackRecord(ResourceIdentityMixin, TimestampMixin, Base):
    """Immutable synthetic L3 feedback content revision and release state."""

    __tablename__ = "school_feedback_records"
    __table_args__ = mysql_table_args(
        UniqueConstraint("feedback_ref", name="school_feedback_ref_unique"),
        UniqueConstraint(
            "review_case_id",
            "content_revision",
            name="school_feedback_case_content_revision_unique",
        ),
        UniqueConstraint(
            "id",
            "school_id",
            "review_case_id",
            "content_revision",
            name="school_feedback_event_scope_unique",
        ),
        CheckConstraint("status IN ('DRAFT', 'PUBLISHED', 'REVOKED')", name="status_allowed"),
        CheckConstraint("content_revision >= 1", name="content_revision_positive"),
        CheckConstraint("state_version >= 1", name="state_version_positive"),
        CheckConstraint("case_version >= 1", name="case_version_positive"),
        CheckConstraint("level = 'L3'", name="level_synthetic_l3_only"),
        CheckConstraint("synthetic_only = 1", name="synthetic_only_locked"),
        CheckConstraint(
            "(status = 'DRAFT' AND published_at IS NULL AND revoked_at IS NULL) OR "
            "(status = 'PUBLISHED' AND published_at IS NOT NULL AND revoked_at IS NULL) OR "
            "(status = 'REVOKED' AND published_at IS NOT NULL AND revoked_at IS NOT NULL)",
            name="status_timestamps_match",
        ),
        ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name="fk_school_feedback_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "review_case_id",
                "school_id",
                "task_id",
                "class_id",
                "task_enrollment_id",
                "subject_id",
                "assessment_session_id",
            ],
            [
                "school_professional_review_cases.id",
                "school_professional_review_cases.school_id",
                "school_professional_review_cases.task_id",
                "school_professional_review_cases.class_id",
                "school_professional_review_cases.task_enrollment_id",
                "school_professional_review_cases.subject_id",
                "school_professional_review_cases.assessment_session_id",
            ],
            name="fk_school_feedback_review_case_exact_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["task_id", "school_id", "class_id"],
            ["measurement_tasks.id", "measurement_tasks.school_id", "measurement_tasks.class_id"],
            name="fk_school_feedback_task_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["task_enrollment_id", "task_id", "school_id", "subject_id"],
            [
                "task_enrollments.id",
                "task_enrollments.task_id",
                "task_enrollments.school_id",
                "task_enrollments.subject_id",
            ],
            name="fk_school_feedback_enrollment_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["assessment_session_id", "task_enrollment_id", "subject_id"],
            [
                "assessment_sessions.id",
                "assessment_sessions.task_enrollment_id",
                "assessment_sessions.subject_id",
            ],
            name="fk_school_feedback_assessment_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["subject_id", "school_id"],
            ["subjects.id", "subjects.school_id"],
            name="fk_school_feedback_subject_scope",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_school_feedback_student_status_created",
            "school_id",
            "subject_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_school_feedback_case_revision",
            "school_id",
            "review_case_id",
            "content_revision",
        ),
    )

    feedback_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    task_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    class_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    task_enrollment_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    subject_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    assessment_session_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    review_case_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    content_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    case_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")
    level: Mapped[str] = mapped_column(ascii_id(2), nullable=False, default="L3")
    synthetic_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    payload_ciphertext: Mapped[bytes] = mapped_column(mysql.MEDIUMBLOB, nullable=False)
    cipher_format_version: Mapped[str] = mapped_column(ascii_id(32), nullable=False)
    key_version: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    payload_schema_version: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    retention_due_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class SchoolFeedbackEvent(ResourceIdentityMixin, TimestampMixin, Base):
    """Content-free history of authorized feedback state transitions."""

    __tablename__ = "school_feedback_events"
    __table_args__ = mysql_table_args(
        UniqueConstraint(
            "feedback_id",
            "state_version",
            name="school_feedback_event_state_version_unique",
        ),
        CheckConstraint(
            "event_type IN ('CREATED', 'PUBLISHED', 'REVOKED')", name="event_type_allowed"
        ),
        CheckConstraint(
            "from_status IS NULL OR from_status IN ('DRAFT', 'PUBLISHED', 'REVOKED')",
            name="from_status_allowed",
        ),
        CheckConstraint("to_status IN ('DRAFT', 'PUBLISHED', 'REVOKED')", name="to_status_allowed"),
        CheckConstraint("state_version >= 1", name="state_version_positive"),
        ForeignKeyConstraint(
            ["feedback_id", "school_id", "review_case_id", "content_revision"],
            [
                "school_feedback_records.id",
                "school_feedback_records.school_id",
                "school_feedback_records.review_case_id",
                "school_feedback_records.content_revision",
            ],
            name="fk_school_feedback_events_record_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_feedback_events_actor_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name="fk_school_feedback_events_school",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_school_feedback_events_case_created",
            "school_id",
            "review_case_id",
            "created_at",
        ),
    )

    feedback_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    review_case_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    content_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_membership_role_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(ascii_id(128), nullable=True)


class SchoolCatItemBank(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "school_cat_item_banks"
    __table_args__ = mysql_table_args(
        UniqueConstraint("id", "school_id", name="school_cat_item_bank_id_school_unique"),
        CheckConstraint("status IN ('ACTIVE', 'ARCHIVED')", name="status_allowed"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        ForeignKeyConstraint(
            ["school_id"], ["schools.id"],
            name="fk_school_cat_item_banks_school", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["creator_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_cat_item_banks_creator_role_school", ondelete="RESTRICT",
        ),
        Index("ix_school_cat_item_banks_school_status", "school_id", "status"),
    )

    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    creator_membership_role_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)


class SchoolCatItemBankVersion(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "school_cat_item_bank_versions"
    __table_args__ = mysql_table_args(
        UniqueConstraint("id", "school_id", name="school_cat_item_bank_version_id_school_unique"),
        UniqueConstraint(
            "bank_id", "version_number", name="school_cat_item_bank_version_number_unique"
        ),
        CheckConstraint("version_number >= 1", name="version_number_positive"),
        CheckConstraint("item_count BETWEEN 1 AND 100", name="item_count_allowed"),
        CheckConstraint("dimension_count = 1", name="dimension_count_allowed"),
        ForeignKeyConstraint(
            ["school_id"], ["schools.id"],
            name="fk_school_cat_item_bank_versions_school", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["bank_id", "school_id"],
            ["school_cat_item_banks.id", "school_cat_item_banks.school_id"],
            name="fk_school_cat_item_bank_versions_bank_school", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["creator_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_cat_item_bank_versions_creator_role_school", ondelete="RESTRICT",
        ),
        Index("ix_school_cat_item_bank_versions_school_bank", "school_id", "bank_id"),
    )

    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    bank_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    creator_membership_role_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    dimension_count: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_ciphertext: Mapped[bytes] = mapped_column(mysql.MEDIUMBLOB, nullable=False)
    cipher_format_version: Mapped[str] = mapped_column(ascii_id(32), nullable=False)
    key_version: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    payload_schema_version: Mapped[str] = mapped_column(ascii_id(64), nullable=False)


class SchoolCatPlan(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "school_cat_plans"
    __table_args__ = mysql_table_args(
        UniqueConstraint("id", "school_id", name="school_cat_plan_id_school_unique"),
        CheckConstraint("status IN ('ACTIVE', 'ARCHIVED')", name="status_allowed"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        ForeignKeyConstraint(
            ["school_id"], ["schools.id"],
            name="fk_school_cat_plans_school", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["creator_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_cat_plans_creator_role_school", ondelete="RESTRICT",
        ),
        Index("ix_school_cat_plans_school_status", "school_id", "status"),
    )

    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    creator_membership_role_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)


class SchoolCatPlanVersion(ResourceIdentityMixin, TimestampMixin, Base):
    __tablename__ = "school_cat_plan_versions"
    __table_args__ = mysql_table_args(
        UniqueConstraint("id", "school_id", name="school_cat_plan_version_id_school_unique"),
        UniqueConstraint("plan_id", "version_number", name="school_cat_plan_version_number_unique"),
        CheckConstraint("version_number >= 1", name="version_number_positive"),
        ForeignKeyConstraint(
            ["school_id"], ["schools.id"],
            name="fk_school_cat_plan_versions_school", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["plan_id", "school_id"],
            ["school_cat_plans.id", "school_cat_plans.school_id"],
            name="fk_school_cat_plan_versions_plan_school", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["bank_version_id", "school_id"],
            ["school_cat_item_bank_versions.id", "school_cat_item_bank_versions.school_id"],
            name="fk_school_cat_plan_versions_bank_version_school", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["creator_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_cat_plan_versions_creator_role_school", ondelete="RESTRICT",
        ),
        Index("ix_school_cat_plan_versions_school_plan", "school_id", "plan_id"),
        Index("ix_school_cat_plan_versions_bank_version", "bank_version_id", "school_id"),
    )

    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    plan_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    bank_version_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    creator_membership_role_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    payload_ciphertext: Mapped[bytes] = mapped_column(mysql.MEDIUMBLOB, nullable=False)
    cipher_format_version: Mapped[str] = mapped_column(ascii_id(32), nullable=False)
    key_version: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    payload_schema_version: Mapped[str] = mapped_column(ascii_id(64), nullable=False)


class SchoolCatActivation(ResourceIdentityMixin, TimestampMixin, Base):
    """A revocable engineering-only eligibility record for one saved plan version."""

    __tablename__ = "school_cat_activations"
    __table_args__ = mysql_table_args(
        UniqueConstraint(
            "id", "school_id", "plan_version_id",
            name="school_cat_activation_exact_version_unique",
        ),
        CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name="status_allowed"),
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint(
            "revoked_at IS NULL OR status = 'REVOKED'", name="revocation_matches_status"
        ),
        CheckConstraint(
            "purpose = 'SYNTHETIC_ENGINEERING'", name="purpose_engineering_only"
        ),
        ForeignKeyConstraint(
            ["school_id"], ["schools.id"],
            name="fk_school_cat_activations_school", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["plan_version_id", "school_id"],
            ["school_cat_plan_versions.id", "school_cat_plan_versions.school_id"],
            name="fk_school_cat_activations_plan_version_school", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["creator_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_cat_activations_creator_role_school", ondelete="RESTRICT",
        ),
        Index("ix_school_cat_activations_school_status", "school_id", "status"),
        Index(
            "ix_school_cat_activations_school_version_status",
            "school_id", "plan_version_id", "status",
        ),
    )

    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    plan_version_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    creator_membership_role_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    purpose: Mapped[str] = mapped_column(
        ascii_id(32), nullable=False, default="SYNTHETIC_ENGINEERING",
        server_default="SYNTHETIC_ENGINEERING",
    )
    revoked_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class SchoolCatTaskBinding(ResourceIdentityMixin, TimestampMixin, Base):
    """The immutable activation and plan version selected for a school task."""

    __tablename__ = "school_cat_task_bindings"
    __table_args__ = mysql_table_args(
        UniqueConstraint("task_id", name="school_cat_task_binding_task_unique"),
        UniqueConstraint(
            "id", "school_id", "task_id", "activation_id", "plan_version_id",
            name="school_cat_task_binding_exact_scope_unique",
        ),
        ForeignKeyConstraint(
            ["task_id", "school_id"],
            ["measurement_tasks.id", "measurement_tasks.school_id"],
            name="fk_school_cat_task_bindings_task_scope", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["activation_id", "school_id", "plan_version_id"],
            [
                "school_cat_activations.id", "school_cat_activations.school_id",
                "school_cat_activations.plan_version_id",
            ],
            name="fk_school_cat_task_bindings_activation_exact_version", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["plan_version_id", "school_id"],
            ["school_cat_plan_versions.id", "school_cat_plan_versions.school_id"],
            name="fk_school_cat_task_bindings_plan_version_school", ondelete="RESTRICT",
        ),
        Index("ix_school_cat_task_bindings_school_task", "school_id", "task_id"),
    )

    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    task_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    activation_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    plan_version_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)


class SchoolCatSessionBinding(ResourceIdentityMixin, TimestampMixin, Base):
    """The immutable saved CAT version attached to one assessment session."""

    __tablename__ = "school_cat_session_bindings"
    __table_args__ = mysql_table_args(
        UniqueConstraint(
            "assessment_session_id", name="school_cat_session_binding_assessment_unique"
        ),
        ForeignKeyConstraint(
            ["assessment_session_id", "task_enrollment_id", "subject_id"],
            [
                "assessment_sessions.id", "assessment_sessions.task_enrollment_id",
                "assessment_sessions.subject_id",
            ],
            name="fk_school_cat_session_bindings_assessment_scope", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["task_enrollment_id", "task_id", "school_id", "subject_id"],
            [
                "task_enrollments.id", "task_enrollments.task_id",
                "task_enrollments.school_id", "task_enrollments.subject_id",
            ],
            name="fk_school_cat_session_bindings_enrollment_scope", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["task_binding_id", "school_id", "task_id", "activation_id", "plan_version_id"],
            [
                "school_cat_task_bindings.id", "school_cat_task_bindings.school_id",
                "school_cat_task_bindings.task_id", "school_cat_task_bindings.activation_id",
                "school_cat_task_bindings.plan_version_id",
            ],
            name="fk_school_cat_session_bindings_task_binding_exact", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["activation_id", "school_id", "plan_version_id"],
            [
                "school_cat_activations.id", "school_cat_activations.school_id",
                "school_cat_activations.plan_version_id",
            ],
            name="fk_school_cat_session_bindings_activation_exact_version",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_school_cat_session_bindings_school_enrollment",
            "school_id", "task_enrollment_id",
        ),
    )

    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    assessment_session_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    task_enrollment_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    subject_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    task_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    task_binding_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    activation_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    plan_version_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)


class SchoolResearchProfileVersion(ResourceIdentityMixin, TimestampMixin, Base):
    """Immutable encrypted public-source research profile version."""

    __tablename__ = "school_research_profile_versions"
    __table_args__ = mysql_table_args(
        UniqueConstraint(
            "school_id", "profile_ref", "version_number",
            name="school_research_profile_version_unique",
        ),
        UniqueConstraint(
            "id", "school_id", "profile_ref", "version_number", "profile_sha256",
            name="school_research_profile_exact_scope_unique",
        ),
        UniqueConstraint(
            "id", "school_id", "profile_ref", "version_number", "profile_sha256",
            "manifest_sha256", name="school_research_profile_manifest_scope_unique",
        ),
        CheckConstraint("version_number >= 1", name="version_positive"),
        CheckConstraint(
            "rights_status IN ('PENDING', 'VERIFIED', 'REVOKED')",
            name="rights_status_allowed",
        ),
        CheckConstraint(
            "execution_status IN ('CANDIDATE_RESEARCH_ONLY', 'SIMULATION_ENABLED', 'DISABLED')",
            name="execution_status_allowed",
        ),
        CheckConstraint(
            "execution_status <> 'SIMULATION_ENABLED' OR rights_status = 'VERIFIED'",
            name="sim_rights_verified",
        ),
        CheckConstraint(
            "rights_status <> 'REVOKED' OR execution_status = 'DISABLED'",
            name="revoked_disables",
        ),
        CheckConstraint("research_only = 1", name="research_only_locked"),
        CheckConstraint("human_curated = 0", name="human_curated_false"),
        CheckConstraint(
            "psychological_interpretation_allowed = 0",
            name="interpretation_forbidden",
        ),
        CheckConstraint(
            "purpose = 'RESEARCH_SIMULATION'", name="purpose_research_only"
        ),
        CheckConstraint(
            "publication_status = 'not_approved_for_publication_or_operational_use'",
            name="publication_unapproved",
        ),
        CheckConstraint(
            "parameter_origin IN ('LOCAL_RESEARCH_FIT', 'PUBLISHED_ROUNDED_REFERENCE')",
            name="parameter_origin_allowed",
        ),
        CheckConstraint(
            "(parameter_origin = 'LOCAL_RESEARCH_FIT' "
            "AND fit_sha256 IS NOT NULL AND calibration_sha256 IS NOT NULL "
            "AND published_parameter_crosswalk_sha256 IS NULL) OR "
            "(parameter_origin = 'PUBLISHED_ROUNDED_REFERENCE' "
            "AND fit_sha256 IS NULL AND calibration_sha256 IS NULL "
            "AND published_parameter_crosswalk_sha256 IS NOT NULL)",
            name="parameter_provenance_shape",
        ),
        ForeignKeyConstraint(
            ["school_id"], ["schools.id"],
            name="fk_school_research_profile_versions_school", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_research_profiles_creator_school", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["status_changed_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_research_profiles_status_actor_school", ondelete="RESTRICT",
        ),
        Index(
            "ix_school_research_profiles_school_status",
            "school_id", "execution_status", "rights_status",
        ),
    )

    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    profile_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    instrument_id: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    dimension: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    source_population_scope: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    profile_sha256: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    fit_sha256: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    calibration_sha256: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    rights_status: Mapped[str] = mapped_column(String(16), nullable=False)
    execution_status: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose: Mapped[str] = mapped_column(
        ascii_id(32), nullable=False, default="RESEARCH_SIMULATION",
        server_default="RESEARCH_SIMULATION",
    )
    research_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    human_curated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    psychological_interpretation_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    publication_status: Mapped[str] = mapped_column(
        ascii_id(64), nullable=False,
        default="not_approved_for_publication_or_operational_use",
        server_default="not_approved_for_publication_or_operational_use",
    )
    payload_ciphertext: Mapped[bytes] = mapped_column(mysql.MEDIUMBLOB, nullable=False)
    cipher_format_version: Mapped[str] = mapped_column(ascii_id(32), nullable=False)
    key_version: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    payload_schema_version: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    created_by_membership_role_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    status_changed_by_membership_role_id: Mapped[int | None] = mapped_column(
        unsigned_id(), nullable=True
    )
    simulation_enabled_at: Mapped[datetime | None] = mapped_column(
        utc_datetime(), nullable=True
    )
    rights_revoked_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    parameter_origin: Mapped[str] = mapped_column(
        ascii_id(32),
        nullable=False,
        default="LOCAL_RESEARCH_FIT",
        server_default="LOCAL_RESEARCH_FIT",
    )
    published_parameter_crosswalk_sha256: Mapped[str | None] = mapped_column(
        ascii_id(64), nullable=True
    )


class SchoolResearchCohort(ResourceIdentityMixin, TimestampMixin, Base):
    """Sealed server-derived 800-subject public-observation cohort metadata."""

    __tablename__ = "school_research_cohorts"
    __table_args__ = mysql_table_args(
        UniqueConstraint("school_id", "cohort_ref", name="school_research_cohort_ref_unique"),
        UniqueConstraint("id", "school_id", name="school_research_cohort_id_school_unique"),
        UniqueConstraint(
            "id",
            "school_id",
            "profile_version_id",
            "profile_ref",
            "profile_version_number",
            "profile_sha256",
            "manifest_sha256",
            "corpus_sha256",
            "case_count",
            name="school_research_cohort_exact_pin_unique",
        ),
        UniqueConstraint(
            "id",
            "school_id",
            "profile_version_id",
            "profile_ref",
            "profile_version_number",
            "profile_sha256",
            "corpus_sha256",
            "case_count",
            name="school_research_cohort_binding_exact_unique",
        ),
        CheckConstraint("status = 'SEALED'", name="status_sealed_only"),
        CheckConstraint("case_count = 800", name="case_count_fixed"),
        CheckConstraint("class_count = 8", name="class_count_fixed"),
        CheckConstraint("subject_count = 800", name="subject_count_fixed"),
        CheckConstraint("length(profile_sha256) = 64", name="profile_sha_shape"),
        CheckConstraint("length(manifest_sha256) = 64", name="manifest_sha_shape"),
        CheckConstraint("length(corpus_sha256) = 64", name="corpus_sha_shape"),
        CheckConstraint("length(assignment_sha256) = 64", name="assignment_sha_shape"),
        CheckConstraint("purpose = 'RESEARCH_SIMULATION'", name="purpose_research_only"),
        CheckConstraint("research_only = 1", name="research_only_locked"),
        CheckConstraint("human_curated = 0", name="human_curated_false"),
        CheckConstraint(
            "psychological_interpretation_allowed = 0", name="interpretation_forbidden"
        ),
        ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name="fk_school_research_cohorts_school",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "profile_version_id",
                "school_id",
                "profile_ref",
                "profile_version_number",
                "profile_sha256",
                "manifest_sha256",
            ],
            [
                "school_research_profile_versions.id",
                "school_research_profile_versions.school_id",
                "school_research_profile_versions.profile_ref",
                "school_research_profile_versions.version_number",
                "school_research_profile_versions.profile_sha256",
                "school_research_profile_versions.manifest_sha256",
            ],
            name="fk_school_research_cohorts_profile_exact",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_research_cohorts_creator_school",
            ondelete="RESTRICT",
        ),
        Index("ix_school_research_cohorts_school_study", "school_id", "study_ref"),
    )

    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    cohort_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    study_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    profile_version_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    profile_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    profile_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_sha256: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    corpus_sha256: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    assignment_sha256: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    case_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=800, server_default="800"
    )
    class_count: Mapped[int] = mapped_column(Integer, nullable=False, default=8, server_default="8")
    subject_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=800, server_default="800"
    )
    status: Mapped[str] = mapped_column(
        ascii_id(16), nullable=False, default="SEALED", server_default="SEALED"
    )
    purpose: Mapped[str] = mapped_column(
        ascii_id(32),
        nullable=False,
        default="RESEARCH_SIMULATION",
        server_default="RESEARCH_SIMULATION",
    )
    research_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    human_curated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    psychological_interpretation_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    sealed_at: Mapped[datetime] = mapped_column(utc_datetime(), nullable=False)
    created_by_membership_role_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)


class SchoolResearchCohortBatch(ResourceIdentityMixin, TimestampMixin, Base):
    """One exact 100-row school account batch captured by a sealed cohort."""

    __tablename__ = "school_research_cohort_batches"
    __table_args__ = mysql_table_args(
        UniqueConstraint("cohort_id", "class_id", name="school_research_cohort_class_unique"),
        UniqueConstraint("cohort_id", "batch_id", name="school_research_cohort_batch_unique"),
        UniqueConstraint(
            "id",
            "cohort_id",
            "school_id",
            "class_id",
            "batch_id",
            name="school_research_cohort_batch_exact_unique",
        ),
        CheckConstraint("row_count = 100", name="row_count_fixed"),
        ForeignKeyConstraint(
            ["cohort_id", "school_id"],
            ["school_research_cohorts.id", "school_research_cohorts.school_id"],
            name="fk_school_research_cohort_batches_cohort",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["batch_id", "school_id", "class_id"],
            [
                "school_account_batches.id",
                "school_account_batches.school_id",
                "school_account_batches.class_id",
            ],
            name="fk_school_research_cohort_batches_batch_exact",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["class_id", "school_id"],
            ["school_classes.id", "school_classes.school_id"],
            name="fk_school_research_cohort_batches_class",
            ondelete="RESTRICT",
        ),
        Index("ix_school_research_cohort_batches_cohort", "cohort_id", "class_id"),
    )

    cohort_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    class_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    batch_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    class_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    batch_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    row_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )


class SchoolResearchCohortAssignment(ResourceIdentityMixin, TimestampMixin, Base):
    """Private immutable link from one synthetic subject to one corpus case index."""

    __tablename__ = "school_research_cohort_assignments"
    __table_args__ = mysql_table_args(
        UniqueConstraint("cohort_id", "case_index", name="school_research_cohort_case_unique"),
        UniqueConstraint("cohort_id", "subject_id", name="school_research_cohort_subject_unique"),
        UniqueConstraint(
            "id",
            "cohort_id",
            "school_id",
            "subject_id",
            "case_index",
            name="school_research_cohort_assignment_exact_unique",
        ),
        CheckConstraint("case_index >= 0 AND case_index < 800", name="case_index_range"),
        ForeignKeyConstraint(
            ["cohort_batch_id", "cohort_id", "school_id", "class_id", "batch_id"],
            [
                "school_research_cohort_batches.id",
                "school_research_cohort_batches.cohort_id",
                "school_research_cohort_batches.school_id",
                "school_research_cohort_batches.class_id",
                "school_research_cohort_batches.batch_id",
            ],
            name="fk_school_research_cohort_assignments_batch_exact",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "provision_id",
                "batch_id",
                "account_id",
                "membership_id",
                "membership_role_id",
                "school_id",
            ],
            [
                "school_account_provisions.id",
                "school_account_provisions.batch_id",
                "school_account_provisions.account_id",
                "school_account_provisions.membership_id",
                "school_account_provisions.membership_role_id",
                "school_account_provisions.school_id",
            ],
            name="fk_school_research_cohort_assignments_provision_exact",
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
            name="fk_school_research_cohort_assignments_roster_exact",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["self_grant_id", "account_id", "subject_id", "school_id"],
            [
                "subject_access_grants.id",
                "subject_access_grants.principal_account_id",
                "subject_access_grants.subject_id",
                "subject_access_grants.school_id",
            ],
            name="fk_school_research_cohort_assignments_self_exact",
            ondelete="RESTRICT",
        ),
        Index("ix_school_research_cohort_assignments_subject", "school_id", "subject_id"),
    )

    cohort_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    cohort_batch_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    batch_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    class_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    provision_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    account_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    membership_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    membership_role_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    class_student_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    subject_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    self_grant_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    case_index: Mapped[int] = mapped_column(Integer, nullable=False)


class SchoolResearchTaskBinding(ResourceIdentityMixin, TimestampMixin, Base):
    """Immutable research profile/config binding for one measurement task."""

    __tablename__ = "school_research_task_bindings"
    __table_args__ = mysql_table_args(
        UniqueConstraint("task_id", name="school_research_task_binding_task_unique"),
        UniqueConstraint(
            "id", "school_id", "task_id", "class_id", "profile_version_id",
            "profile_ref", "profile_version_number", "profile_sha256", "response_origin",
            name="school_research_binding_exact_scope_unique",
        ),
        UniqueConstraint(
            "id", "school_id", "task_id", "class_id", "profile_version_id",
            "profile_ref", "profile_version_number", "profile_sha256", "response_origin",
            "corpus_sha256", "case_count",
            name="school_research_binding_corpus_scope_unique",
        ),
        UniqueConstraint("id", "cohort_id", name="school_research_binding_cohort_id_unique"),
        CheckConstraint(
            "response_origin IN ('PUBLIC_OBSERVED', 'MODEL_GENERATED')",
            name="response_origin_allowed",
        ),
        CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name="status_allowed"),
        CheckConstraint(
            "revoked_at IS NULL OR status = 'REVOKED'",
            name="revocation_matches_status",
        ),
        CheckConstraint(
            "(corpus_sha256 IS NULL AND case_count IS NULL) OR "
            "(corpus_sha256 IS NOT NULL AND case_count IS NOT NULL AND case_count = 800)",
            name="corpus_pin_shape",
        ),
        CheckConstraint(
            "cohort_id IS NULL OR (corpus_sha256 IS NOT NULL AND case_count = 800)",
            name="cohort_requires_corpus_pin",
        ),
        CheckConstraint("research_only = 1", name="research_only_locked"),
        CheckConstraint(
            "purpose = 'RESEARCH_SIMULATION'", name="purpose_research_only"
        ),
        ForeignKeyConstraint(
            ["school_id"], ["schools.id"],
            name="fk_school_research_bindings_school", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["task_id", "school_id", "class_id"],
            ["measurement_tasks.id", "measurement_tasks.school_id", "measurement_tasks.class_id"],
            name="fk_school_research_bindings_task_scope", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "profile_version_id", "school_id", "profile_ref",
                "profile_version_number", "profile_sha256",
            ],
            [
                "school_research_profile_versions.id",
                "school_research_profile_versions.school_id",
                "school_research_profile_versions.profile_ref",
                "school_research_profile_versions.version_number",
                "school_research_profile_versions.profile_sha256",
            ],
            name="fk_school_research_bindings_profile_exact", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_research_bindings_creator_school", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["cohort_id", "school_id", "profile_version_id", "profile_ref",
             "profile_version_number", "profile_sha256", "corpus_sha256", "case_count"],
            ["school_research_cohorts.id", "school_research_cohorts.school_id",
             "school_research_cohorts.profile_version_id", "school_research_cohorts.profile_ref",
             "school_research_cohorts.profile_version_number",
             "school_research_cohorts.profile_sha256", "school_research_cohorts.corpus_sha256",
             "school_research_cohorts.case_count"],
            name="fk_school_research_bindings_cohort_exact", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["revoked_by_membership_role_id", "school_id"],
            ["membership_roles.id", "membership_roles.school_id"],
            name="fk_school_research_bindings_revoker_school", ondelete="RESTRICT",
        ),
        Index("ix_school_research_bindings_school_task", "school_id", "task_id"),
    )

    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    task_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    class_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    profile_version_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    profile_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    profile_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_sha256: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    response_origin: Mapped[str] = mapped_column(ascii_id(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    purpose: Mapped[str] = mapped_column(
        ascii_id(32), nullable=False, default="RESEARCH_SIMULATION",
        server_default="RESEARCH_SIMULATION",
    )
    research_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    config_version: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    config_sha256: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    config_ciphertext: Mapped[bytes] = mapped_column(mysql.MEDIUMBLOB, nullable=False)
    cipher_format_version: Mapped[str] = mapped_column(ascii_id(32), nullable=False)
    key_version: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    payload_schema_version: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    created_by_membership_role_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    revoked_by_membership_role_id: Mapped[int | None] = mapped_column(
        unsigned_id(), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    corpus_sha256: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    case_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cohort_id: Mapped[int | None] = mapped_column(unsigned_id(), nullable=True, sort_order=1000)


class SchoolResearchCaseAssignment(ResourceIdentityMixin, TimestampMixin, Base):
    """Private content-free row mapping one task enrollment to one public case index."""

    __tablename__ = "school_research_case_assignments"
    __table_args__ = mysql_table_args(
        UniqueConstraint(
            "task_enrollment_id", name="school_research_case_enrollment_unique"
        ),
        UniqueConstraint(
            "task_id", "case_index", name="school_research_case_task_index_unique"
        ),
        CheckConstraint(
            "response_origin = 'PUBLIC_OBSERVED'", name="response_origin_public_observed"
        ),
        CheckConstraint(
            "case_index >= 0 AND case_index < 800", name="case_index_range"
        ),
        CheckConstraint("case_count = 800", name="case_count_fixed"),
        CheckConstraint("purpose = 'RESEARCH_SIMULATION'", name="purpose_research_only"),
        CheckConstraint(
            "(cohort_id IS NULL AND cohort_assignment_id IS NULL) OR "
            "(cohort_id IS NOT NULL AND cohort_assignment_id IS NOT NULL)",
            name="cohort_assignment_pair",
        ),
        ForeignKeyConstraint(
            ["school_id"], ["schools.id"],
            name="fk_school_research_case_assignments_school", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["task_id", "school_id", "class_id"],
            ["measurement_tasks.id", "measurement_tasks.school_id", "measurement_tasks.class_id"],
            name="fk_school_research_case_assignments_task_scope", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["task_enrollment_id", "task_id", "school_id", "subject_id"],
            ["task_enrollments.id", "task_enrollments.task_id", "task_enrollments.school_id",
             "task_enrollments.subject_id"],
            name="fk_school_research_case_assignments_enrollment_scope", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["subject_id", "school_id"], ["subjects.id", "subjects.school_id"],
            name="fk_school_research_case_assignments_subject_scope", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["profile_version_id", "school_id", "profile_ref", "profile_version_number",
             "profile_sha256"],
            ["school_research_profile_versions.id", "school_research_profile_versions.school_id",
             "school_research_profile_versions.profile_ref",
             "school_research_profile_versions.version_number",
             "school_research_profile_versions.profile_sha256"],
            name="fk_school_research_case_assignments_profile_exact", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["task_binding_id", "school_id", "task_id", "class_id", "profile_version_id",
             "profile_ref", "profile_version_number", "profile_sha256", "response_origin",
             "corpus_sha256", "case_count"],
            ["school_research_task_bindings.id", "school_research_task_bindings.school_id",
             "school_research_task_bindings.task_id", "school_research_task_bindings.class_id",
             "school_research_task_bindings.profile_version_id",
             "school_research_task_bindings.profile_ref",
             "school_research_task_bindings.profile_version_number",
             "school_research_task_bindings.profile_sha256",
             "school_research_task_bindings.response_origin",
             "school_research_task_bindings.corpus_sha256",
             "school_research_task_bindings.case_count"],
            name="fk_school_research_case_assignments_binding_exact", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["task_binding_id", "cohort_id"],
            ["school_research_task_bindings.id", "school_research_task_bindings.cohort_id"],
            name="fk_school_research_case_assignments_binding_cohort", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "cohort_assignment_id",
                "cohort_id",
                "school_id",
                "subject_id",
                "case_index",
            ],
            ["school_research_cohort_assignments.id",
             "school_research_cohort_assignments.cohort_id",
             "school_research_cohort_assignments.school_id",
             "school_research_cohort_assignments.subject_id",
             "school_research_cohort_assignments.case_index"],
            name="fk_school_research_case_assignments_cohort_exact",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        Index(
            "ix_school_research_case_assignments_scope",
            "school_id", "task_id", "task_binding_id",
        ),
    )

    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    task_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    class_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    task_enrollment_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    subject_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    task_binding_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    profile_version_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    profile_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    profile_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_sha256: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    response_origin: Mapped[str] = mapped_column(ascii_id(32), nullable=False)
    corpus_sha256: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    case_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=800, server_default="800"
    )
    case_index: Mapped[int] = mapped_column(Integer, nullable=False)
    purpose: Mapped[str] = mapped_column(
        ascii_id(32), nullable=False, default="RESEARCH_SIMULATION",
        server_default="RESEARCH_SIMULATION",
    )
    cohort_id: Mapped[int | None] = mapped_column(
        unsigned_id(), nullable=True, sort_order=1000
    )
    cohort_assignment_id: Mapped[int | None] = mapped_column(
        unsigned_id(), nullable=True, sort_order=1001
    )


class SchoolResearchSession(ResourceIdentityMixin, TimestampMixin, Base):
    """Encrypted CAT state for a research task; never an AssessmentSession."""

    __tablename__ = "school_research_sessions"
    __table_args__ = mysql_table_args(
        UniqueConstraint("session_ref", name="school_research_session_ref_unique"),
        UniqueConstraint("task_enrollment_id", name="school_research_session_enrollment_unique"),
        UniqueConstraint(
            "id", "school_id", "task_id", "class_id", "task_enrollment_id", "subject_id",
            "task_binding_id", "profile_version_id", "profile_ref", "profile_version_number",
            "profile_sha256", "response_origin",
            name="school_research_session_exact_scope_unique",
        ),
        CheckConstraint(
            "status IN ('IN_PROGRESS', 'COMPLETED', 'ABANDONED', 'FAILED')",
            name="status_allowed",
        ),
        CheckConstraint("state_version >= 1", name="state_version_positive"),
        CheckConstraint("items_answered >= 0", name="items_answered_nonnegative"),
        CheckConstraint("research_only = 1", name="research_only_locked"),
        CheckConstraint(
            "purpose = 'RESEARCH_SIMULATION'", name="purpose_research_only"
        ),
        CheckConstraint(
            "response_origin IN ('PUBLIC_OBSERVED', 'MODEL_GENERATED')",
            name="response_origin_allowed",
        ),
        CheckConstraint(
            "(status = 'IN_PROGRESS' AND completed_at IS NULL) OR "
            "(status = 'COMPLETED' AND completed_at IS NOT NULL) OR "
            "(status IN ('ABANDONED', 'FAILED') AND completed_at IS NULL)",
            name="status_timestamps_match",
        ),
        ForeignKeyConstraint(
            ["school_id"], ["schools.id"],
            name="fk_school_research_sessions_school", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["task_id", "school_id", "class_id"],
            ["measurement_tasks.id", "measurement_tasks.school_id", "measurement_tasks.class_id"],
            name="fk_school_research_sessions_task_scope", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["task_enrollment_id", "task_id", "school_id", "subject_id"],
            [
                "task_enrollments.id", "task_enrollments.task_id",
                "task_enrollments.school_id", "task_enrollments.subject_id",
            ],
            name="fk_school_research_sessions_enrollment_scope", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "task_binding_id", "school_id", "task_id", "class_id",
                "profile_version_id", "profile_ref", "profile_version_number",
                "profile_sha256", "response_origin",
            ],
            [
                "school_research_task_bindings.id", "school_research_task_bindings.school_id",
                "school_research_task_bindings.task_id", "school_research_task_bindings.class_id",
                "school_research_task_bindings.profile_version_id",
                "school_research_task_bindings.profile_ref",
                "school_research_task_bindings.profile_version_number",
                "school_research_task_bindings.profile_sha256",
                "school_research_task_bindings.response_origin",
            ],
            name="fk_school_research_sessions_binding_exact", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["subject_id", "school_id"], ["subjects.id", "subjects.school_id"],
            name="fk_school_research_sessions_subject_scope", ondelete="RESTRICT",
        ),
        Index(
            "ix_school_research_sessions_school_task_status",
            "school_id", "task_id", "status",
        ),
        Index(
            "ix_school_research_sessions_school_subject_status",
            "school_id", "subject_id", "status",
        ),
    )

    session_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    task_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    class_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    task_enrollment_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    subject_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    task_binding_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    profile_version_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    profile_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False)
    profile_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_sha256: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    response_origin: Mapped[str] = mapped_column(ascii_id(32), nullable=False)
    config_version: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    config_sha256: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    purpose: Mapped[str] = mapped_column(
        ascii_id(32), nullable=False, default="RESEARCH_SIMULATION",
        server_default="RESEARCH_SIMULATION",
    )
    research_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="IN_PROGRESS", server_default="IN_PROGRESS"
    )
    state_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    items_answered: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    stop_reason: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    snapshot_ciphertext: Mapped[bytes] = mapped_column(mysql.MEDIUMBLOB, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    cipher_format_version: Mapped[str] = mapped_column(ascii_id(32), nullable=False)
    key_version: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    payload_schema_version: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(utc_datetime(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(ascii_id(128), nullable=True)
    retention_due_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)


class SchoolPostAssessmentJob(ResourceIdentityMixin, TimestampMixin, Base):
    """Content-free durable work envelope for post-assessment education support."""

    __tablename__ = "school_post_assessment_jobs"
    __table_args__ = mysql_table_args(
        UniqueConstraint(
            "school_id",
            "assessment_session_id",
            "job_kind",
            "policy_version",
            name="school_post_assessment_job_idempotency_unique",
        ),
        CheckConstraint("job_kind = 'EDUCATION_SUPPORT'", name="job_kind_allowed"),
        CheckConstraint(
            "status IN ('QUEUED', 'LEASED', 'RETRY', 'HELD', 'ABSTAINED', "
            "'REVIEW_REQUIRED', 'CRISIS_ROUTED', 'FAILED', 'CANCELLED')",
            name="status_allowed",
        ),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint(
            "(status = 'LEASED' AND lease_owner IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND lease_token IS NOT NULL) OR "
            "(status <> 'LEASED' AND lease_owner IS NULL "
            "AND lease_expires_at IS NULL AND lease_token IS NULL)",
            name="lease_matches_status",
        ),
        CheckConstraint(
            "status <> 'RETRY' OR next_attempt_at IS NOT NULL",
            name="retry_has_next_attempt",
        ),
        Index(
            "ix_school_post_assessment_jobs_claim",
            "status",
            "next_attempt_at",
            "lease_expires_at",
            "created_at",
        ),
        Index(
            "ix_school_post_assessment_jobs_student_status",
            "school_id",
            "subject_id",
            "status",
            "created_at",
        ),
        ForeignKeyConstraint(
            ["school_id"], ["schools.id"],
            name="fk_school_post_assessment_jobs_school", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["task_id", "school_id", "class_id"],
            ["measurement_tasks.id", "measurement_tasks.school_id", "measurement_tasks.class_id"],
            name="fk_school_post_assessment_jobs_task_scope", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["class_student_id", "subject_id", "class_id", "school_id"],
            [
                "school_class_students.id", "school_class_students.subject_id",
                "school_class_students.class_id", "school_class_students.school_id",
            ],
            name="fk_school_post_assessment_jobs_roster_scope", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["task_enrollment_id", "task_id", "school_id", "subject_id"],
            [
                "task_enrollments.id", "task_enrollments.task_id",
                "task_enrollments.school_id", "task_enrollments.subject_id",
            ],
            name="fk_school_post_assessment_jobs_enrollment_scope", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["assessment_session_id", "task_enrollment_id", "subject_id"],
            [
                "assessment_sessions.id", "assessment_sessions.task_enrollment_id",
                "assessment_sessions.subject_id",
            ],
            name="fk_school_post_assessment_jobs_assessment_scope", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["subject_id", "school_id"], ["subjects.id", "subjects.school_id"],
            name="fk_school_post_assessment_jobs_subject_scope", ondelete="RESTRICT",
        ),
    )

    job_ref: Mapped[str] = mapped_column(ascii_id(128), nullable=False, unique=True)
    school_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    task_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    class_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    class_student_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    task_enrollment_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    subject_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    assessment_session_id: Mapped[int] = mapped_column(unsigned_id(), nullable=False)
    job_kind: Mapped[str] = mapped_column(ascii_id(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(ascii_id(64), nullable=False)
    policy_hash: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="QUEUED", server_default="QUEUED"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(ascii_id(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(ascii_id(128), nullable=True)
    source_snapshot_ref: Mapped[str | None] = mapped_column(ascii_id(128), nullable=True)
    source_snapshot_sha256: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    source_qualification_status: Mapped[str | None] = mapped_column(ascii_id(32), nullable=True)
    source_population: Mapped[str | None] = mapped_column(ascii_id(64), nullable=True)
    source_layer: Mapped[str | None] = mapped_column(ascii_id(32), nullable=True)
    source_rights_status: Mapped[str | None] = mapped_column(ascii_id(32), nullable=True)
    source_review_status: Mapped[str | None] = mapped_column(ascii_id(32), nullable=True)
    source_qualified_at: Mapped[datetime | None] = mapped_column(utc_datetime(), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(ascii_id(128), nullable=True)


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
    "SchoolProfessionalReviewCase",
    "SchoolProfessionalReviewEvent",
    "SchoolFeedbackRecord",
    "SchoolFeedbackEvent",
    "Role",
    "SafetyDecision",
    "SchoolAccountBatch",
    "SchoolAccountProvision",
    "SchoolClass",
    "SchoolClassStudent",
    "SchoolClassTeacher",
    "SchoolTaskSpecialistAssignment",
    "Subject",
    "SubjectAccessGrant",
    "SupportEvidence",
    "SupportMessage",
    "SupportRun",
    "SupportSession",
    "TaskEnrollment",
    "SchoolResearchCohort",
    "SchoolResearchCohortAssignment",
    "SchoolResearchCohortBatch",
]
