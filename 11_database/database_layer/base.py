"""SQLAlchemy 2.0 declarative base and shared technical types."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import MetaData, String
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utc_now() -> datetime:
    """Return a timezone-naive UTC value for MySQL DATETIME(6)."""

    return datetime.now(UTC).replace(tzinfo=None)


def new_public_id() -> str:
    """Return a UUID4 string for a database resource public identifier."""

    return str(uuid4())


def ascii_id(length: int = 128) -> String:
    """Return a case-sensitive ASCII identifier column type."""

    return String(length, collation="ascii_bin")


def utc_datetime() -> mysql.DATETIME:
    """MySQL business timestamp baseline."""

    return mysql.DATETIME(fsp=6)


def unsigned_id() -> mysql.BIGINT:
    """Internal auto-increment identifier baseline."""

    return mysql.BIGINT(unsigned=True)


def mysql_table_args(*items: object) -> tuple[object, ...]:
    """Append explicit MySQL table options to a table's constraints/indexes."""

    return (
        *items,
        {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        },
    )


class Base(DeclarativeBase):
    """Typed SQLAlchemy 2.0 declarative base."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class ResourceIdentityMixin:
    """Internal numeric key plus opaque UUID4 public identifier."""

    id: Mapped[int] = mapped_column(unsigned_id(), primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(
        ascii_id(36), nullable=False, unique=True, default=new_public_id
    )


class TimestampMixin:
    """Universal technical timestamps; deliberately no deleted_at field."""

    created_at: Mapped[datetime] = mapped_column(utc_datetime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        utc_datetime(), nullable=False, default=utc_now, onupdate=utc_now
    )
