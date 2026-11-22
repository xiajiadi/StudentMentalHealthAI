"""School grade-lead authorization persistence.

The repository participates in the caller's unit of work and never commits.
Backend role authorization remains outside this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .errors import ForeignKeyConflict, NotFound, PersistenceError
from .models import SchoolGradeLeader

_GRADE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


class SchoolGradeLeaderError(PersistenceError):
    """Fixed grade-leader persistence error with no personal content."""


@dataclass(frozen=True, slots=True, repr=False)
class SchoolGradeLeaderDTO:
    id: int = field(repr=False)
    public_id: str = field(repr=False)
    school_id: int = field(repr=False)
    membership_role_id: int = field(repr=False)
    grade_ref: str
    status: str
    valid_from: datetime
    valid_until: datetime | None
    revoked_at: datetime | None


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SchoolGradeLeaderError(f"invalid {name}")
    return value


def _grade_ref(value: object) -> str:
    if not isinstance(value, str) or _GRADE_REF.fullmatch(value) is None:
        raise SchoolGradeLeaderError("invalid grade_ref")
    return value


def _utc_naive(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC).replace(tzinfo=None)
    if not isinstance(value, datetime):
        raise SchoolGradeLeaderError("invalid timestamp")
    if value.tzinfo is None:
        return value
    if value.utcoffset() is None:
        raise SchoolGradeLeaderError("invalid timestamp")
    return value.astimezone(UTC).replace(tzinfo=None)


def _dto(row: SchoolGradeLeader) -> SchoolGradeLeaderDTO:
    return SchoolGradeLeaderDTO(
        id=row.id,
        public_id=row.public_id,
        school_id=row.school_id,
        membership_role_id=row.membership_role_id,
        grade_ref=row.grade_ref,
        status=row.status,
        valid_from=row.valid_from,
        valid_until=row.valid_until,
        revoked_at=row.revoked_at,
    )


class SchoolGradeLeaderRepository:
    """Same-UOW grade-lead assignment and revocation operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        school_id: int,
        membership_role_id: int,
        grade_ref: str,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        now: datetime | None = None,
    ) -> SchoolGradeLeaderDTO:
        school_id = _positive_int(school_id, "school_id")
        role_id = _positive_int(membership_role_id, "membership_role_id")
        grade_ref = _grade_ref(grade_ref)
        clock = _utc_naive(now)
        starts_at = _utc_naive(valid_from) if valid_from is not None else clock
        ends_at = _utc_naive(valid_until) if valid_until is not None else None
        if ends_at is not None and ends_at < starts_at:
            raise SchoolGradeLeaderError("invalid grade leader validity window")
        row = SchoolGradeLeader(
            school_id=school_id,
            membership_role_id=role_id,
            grade_ref=grade_ref,
            status="ACTIVE",
            valid_from=starts_at,
            valid_until=ends_at,
            revoked_at=None,
            created_at=clock,
            updated_at=clock,
        )
        try:
            self.session.add(row)
            await self.session.flush()
        except IntegrityError:
            raise ForeignKeyConflict("grade leader scope was rejected") from None
        return _dto(row)

    async def get(
        self, *, school_id: int, public_id: str
    ) -> SchoolGradeLeaderDTO | None:
        school_id = _positive_int(school_id, "school_id")
        if not isinstance(public_id, str) or not public_id:
            raise SchoolGradeLeaderError("invalid public_id")
        row = await self.session.scalar(
            select(SchoolGradeLeader).where(
                SchoolGradeLeader.school_id == school_id,
                SchoolGradeLeader.public_id == public_id,
            )
        )
        return _dto(row) if row is not None else None

    async def list_active(
        self,
        *,
        school_id: int,
        membership_role_id: int,
        at: datetime | None = None,
    ) -> list[SchoolGradeLeaderDTO]:
        school_id = _positive_int(school_id, "school_id")
        role_id = _positive_int(membership_role_id, "membership_role_id")
        clock = _utc_naive(at)
        rows = await self.session.scalars(
            select(SchoolGradeLeader)
            .where(
                SchoolGradeLeader.school_id == school_id,
                SchoolGradeLeader.membership_role_id == role_id,
                SchoolGradeLeader.status == "ACTIVE",
                SchoolGradeLeader.revoked_at.is_(None),
                SchoolGradeLeader.valid_from <= clock,
                (SchoolGradeLeader.valid_until.is_(None))
                | (SchoolGradeLeader.valid_until >= clock),
            )
            .order_by(SchoolGradeLeader.grade_ref, SchoolGradeLeader.id)
        )
        return [_dto(row) for row in rows.all()]

    async def active_grade_refs(
        self,
        *,
        school_id: int,
        membership_role_id: int,
        at: datetime | None = None,
    ) -> list[str]:
        return [
            row.grade_ref
            for row in await self.list_active(
                school_id=school_id,
                membership_role_id=membership_role_id,
                at=at,
            )
        ]

    async def revoke(
        self,
        *,
        school_id: int,
        public_id: str,
        now: datetime | None = None,
    ) -> SchoolGradeLeaderDTO:
        school_id = _positive_int(school_id, "school_id")
        if not isinstance(public_id, str) or not public_id:
            raise SchoolGradeLeaderError("invalid public_id")
        clock = _utc_naive(now)
        row = await self.session.scalar(
            select(SchoolGradeLeader)
            .where(
                SchoolGradeLeader.school_id == school_id,
                SchoolGradeLeader.public_id == public_id,
            )
            .with_for_update()
        )
        if row is None:
            raise NotFound("grade leader is unavailable")
        if row.status != "ACTIVE":
            raise SchoolGradeLeaderError("grade leader is already revoked")
        row.status = "REVOKED"
        row.revoked_at = clock
        row.updated_at = clock
        await self.session.flush()
        return _dto(row)


__all__ = [
    "SchoolGradeLeaderDTO",
    "SchoolGradeLeaderError",
    "SchoolGradeLeaderRepository",
]
