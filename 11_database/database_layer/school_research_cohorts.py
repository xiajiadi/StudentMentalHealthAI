"""Immutable school-cohort assignments for pinned public research rows.

The caller owns the transaction and actor authentication. This repository still
rechecks the same-school persisted role, profile flags, and every selected row
under locks before recording a map. Its deterministic lock order follows the
directory activation prefix and then the research/revocation roster prefix:
profile, accounts, provisions, memberships, roles, batches, rosters, classes,
subjects, SELF grants (each ID-ordered). SQLite tests exercise constraints but
cannot establish MySQL lock or deadlock behavior.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    Account,
    AccountSchoolMembership,
    MembershipRole,
    School,
    SchoolAccountBatch,
    SchoolAccountProvision,
    SchoolClass,
    SchoolClassStudent,
    SchoolResearchCohort,
    SchoolResearchCohortAssignment,
    SchoolResearchCohortBatch,
    SchoolResearchProfileVersion,
    Subject,
    SubjectAccessGrant,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PUBLIC_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class ResearchCohortErrorCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    PROFILE_NOT_ELIGIBLE = "PROFILE_NOT_ELIGIBLE"
    COHORT_NOT_FOUND = "COHORT_NOT_FOUND"
    COHORT_EXISTS = "COHORT_EXISTS"
    COHORT_SCOPE_MISMATCH = "COHORT_SCOPE_MISMATCH"
    COHORT_MEMBERSHIP_INVALID = "COHORT_MEMBERSHIP_INVALID"
    CASE_ASSIGNMENT_NOT_FOUND = "CASE_ASSIGNMENT_NOT_FOUND"
    PERSISTENCE_CONFLICT = "PERSISTENCE_CONFLICT"


class ResearchCohortRepositoryError(ValueError):
    """Fixed-code persistence failure that never embeds row data."""

    def __init__(self, code: ResearchCohortErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class ResearchCohortMetadata:
    """Content-free internal receipt; hashes and database keys are repr-hidden."""

    cohort_id: int = field(repr=False)
    school_id: int = field(repr=False)
    cohort_ref: str
    study_ref: str
    profile_ref: str
    profile_version_number: int
    profile_sha256: str = field(repr=False)
    manifest_sha256: str = field(repr=False)
    corpus_sha256: str = field(repr=False)
    case_count: int
    class_count: int
    subject_count: int
    sealed_at: datetime


@dataclass(frozen=True, slots=True, repr=False)
class ResearchCohortCaseAssignment:
    """Private persistence result; never serialize or include in logs/errors."""

    assignment_id: int = field(repr=False)
    cohort_id: int = field(repr=False)
    school_id: int = field(repr=False)
    class_id: int = field(repr=False)
    class_student_id: int = field(repr=False)
    subject_id: int = field(repr=False)
    case_index: int = field(repr=False)


@dataclass(frozen=True, slots=True)
class _DiscoveredMember:
    provision_id: int
    account_id: int
    membership_id: int
    membership_role_id: int
    batch_id: int
    class_id: int
    batch_ref: str


class SchoolResearchCohortRepository:
    """Create and read sealed 800-subject, complete-permutation cohort maps."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def seal_cohort(
        self,
        *,
        school_id: int,
        cohort_ref: str,
        study_ref: str,
        profile_version_id: int,
        profile_ref: str,
        profile_version_number: int,
        expected_profile_sha256: str,
        expected_manifest_sha256: str,
        expected_corpus_sha256: str,
        creator_membership_role_id: int,
        batch_refs: tuple[str, ...],
        case_index_plan: tuple[int, ...] | None,
        at: datetime,
    ) -> ResearchCohortMetadata:
        """Seal one complete cohort; caller must commit or roll back its UOW.

        ``case_index_plan`` is a trusted server-only argument. It must be a full
        permutation, but is not accepted from an HTTP body and is never returned
        by the safe metadata receipt.
        """

        at = _utc_naive(at)
        _require_id(school_id)
        _require_id(profile_version_id)
        _require_id(creator_membership_role_id)
        _require_ref(cohort_ref)
        _require_ref(study_ref)
        _require_ref(profile_ref)
        for sha in (expected_profile_sha256, expected_manifest_sha256, expected_corpus_sha256):
            if not isinstance(sha, str) or _SHA256.fullmatch(sha) is None:
                raise ResearchCohortRepositoryError(ResearchCohortErrorCode.INVALID_INPUT)
        _validate_batch_refs(batch_refs)

        existing = await self.session.scalar(
            select(SchoolResearchCohort.id).where(
                SchoolResearchCohort.school_id == school_id,
                SchoolResearchCohort.cohort_ref == cohort_ref,
            )
        )
        if existing is not None:
            return await self.require_existing_cohort_matches(
                school_id=school_id,
                cohort_ref=cohort_ref,
                study_ref=study_ref,
                profile_version_id=profile_version_id,
                profile_ref=profile_ref,
                profile_version_number=profile_version_number,
                expected_profile_sha256=expected_profile_sha256,
                expected_manifest_sha256=expected_manifest_sha256,
                expected_corpus_sha256=expected_corpus_sha256,
                batch_refs=batch_refs,
            )
        if case_index_plan is None:
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.INVALID_INPUT)
        _validate_case_plan(case_index_plan)

        profile = await self.session.scalar(
            select(SchoolResearchProfileVersion)
            .where(
                SchoolResearchProfileVersion.id == profile_version_id,
                SchoolResearchProfileVersion.school_id == school_id,
                SchoolResearchProfileVersion.profile_ref == profile_ref,
                SchoolResearchProfileVersion.version_number == profile_version_number,
                SchoolResearchProfileVersion.profile_sha256 == expected_profile_sha256,
                SchoolResearchProfileVersion.manifest_sha256 == expected_manifest_sha256,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not _eligible_profile(profile):
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.PROFILE_NOT_ELIGIBLE)

        # Discover only IDs first. These reads do not authorize or lock anything.
        batch_rows = list(
            (
                await self.session.scalars(
                    select(SchoolAccountBatch)
                    .where(
                        SchoolAccountBatch.school_id == school_id,
                        SchoolAccountBatch.batch_ref.in_(batch_refs),
                    )
                    .order_by(SchoolAccountBatch.id)
                )
            ).all()
        )
        if len(batch_rows) != 8 or {item.batch_ref for item in batch_rows} != set(batch_refs):
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID)
        class_id_candidates: list[int] = []
        for item in batch_rows:
            if item.class_id is None:
                raise ResearchCohortRepositoryError(
                    ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID
                )
            class_id_candidates.append(item.class_id)
        batch_ids = tuple(item.id for item in batch_rows)
        class_ids = tuple(sorted(set(class_id_candidates)))
        if len(class_ids) != 8:
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID)

        discovered_provisions = list(
            (
                await self.session.scalars(
                    select(SchoolAccountProvision)
                    .where(
                        SchoolAccountProvision.school_id == school_id,
                        SchoolAccountProvision.batch_id.in_(batch_ids),
                    )
                    .order_by(SchoolAccountProvision.id)
                )
            ).all()
        )
        discovered_provision_identity = {
            row.id: (
                row.batch_id,
                row.account_id,
                row.membership_id,
                row.membership_role_id,
                row.school_id,
                row.role_code,
                row.status,
            )
            for row in discovered_provisions
        }
        per_batch: dict[int, list[SchoolAccountProvision]] = {item: [] for item in batch_ids}
        for provision in discovered_provisions:
            per_batch.setdefault(provision.batch_id, []).append(provision)
        if len(discovered_provisions) != 800 or any(
            len(rows) != 100 for rows in per_batch.values()
        ):
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID)
        provision_ids = tuple(row.id for row in discovered_provisions)
        account_ids = tuple(sorted({row.account_id for row in discovered_provisions}))
        membership_ids = tuple(sorted({row.membership_id for row in discovered_provisions}))
        role_ids = tuple(sorted({row.membership_role_id for row in discovered_provisions}))
        if any(
            len(values) != 800 for values in (provision_ids, account_ids, membership_ids, role_ids)
        ):
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID)

        discovered_grants = list(
            (
                await self.session.scalars(
                    select(SubjectAccessGrant)
                    .where(
                        SubjectAccessGrant.school_id == school_id,
                        SubjectAccessGrant.principal_account_id.in_(account_ids),
                        SubjectAccessGrant.relationship_type == "SELF",
                        SubjectAccessGrant.status == "ACTIVE",
                        SubjectAccessGrant.revoked_at.is_(None),
                        SubjectAccessGrant.valid_from <= at,
                        (SubjectAccessGrant.valid_until.is_(None))
                        | (SubjectAccessGrant.valid_until >= at),
                    )
                    .order_by(SubjectAccessGrant.id)
                )
            ).all()
        )
        if len(discovered_grants) != 800:
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID)
        discovered_grant_identity = {
            row.id: (row.principal_account_id, row.subject_id, row.school_id)
            for row in discovered_grants
        }
        subject_ids = tuple(sorted({grant.subject_id for grant in discovered_grants}))
        if len(subject_ids) != 800:
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID)
        discovered_rosters = list(
            (
                await self.session.scalars(
                    select(SchoolClassStudent)
                    .where(
                        SchoolClassStudent.school_id == school_id,
                        SchoolClassStudent.class_id.in_(class_ids),
                        SchoolClassStudent.subject_id.in_(subject_ids or (-1,)),
                    )
                    .order_by(SchoolClassStudent.id)
                )
            ).all()
        )
        roster_ids = tuple(row.id for row in discovered_rosters)
        if len(roster_ids) != 800:
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID)
        discovered_roster_identity = {
            row.id: (row.subject_id, row.class_id, row.school_id) for row in discovered_rosters
        }

        # Common activation/research lock order. Each lock read refreshes ORM state.
        locked_accounts = await self._lock_ids(Account, account_ids)
        locked_provisions = await self._lock_ids(SchoolAccountProvision, provision_ids)
        current_provisions = list(
            (
                await self.session.scalars(
                    select(SchoolAccountProvision)
                    .where(
                        SchoolAccountProvision.school_id == school_id,
                        SchoolAccountProvision.batch_id.in_(batch_ids),
                    )
                    .order_by(SchoolAccountProvision.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        if (
            tuple(row.id for row in locked_provisions) != provision_ids
            or tuple(row.id for row in current_provisions) != provision_ids
            or any(
                discovered_provision_identity.get(row.id)
                != (
                    row.batch_id,
                    row.account_id,
                    row.membership_id,
                    row.membership_role_id,
                    row.school_id,
                    row.role_code,
                    row.status,
                )
                for row in current_provisions
            )
        ):
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID)
        locked_memberships = await self._lock_ids(AccountSchoolMembership, membership_ids)
        locked_roles = await self._lock_ids(MembershipRole, role_ids)
        locked_batches = await self._lock_ids(SchoolAccountBatch, batch_ids)
        locked_rosters = await self._lock_ids(SchoolClassStudent, roster_ids)
        locked_classes = await self._lock_ids(SchoolClass, class_ids)
        locked_subjects = await self._lock_ids(Subject, subject_ids)
        grant_ids = tuple(row.id for row in discovered_grants)
        locked_grants = list(
            (
                await self.session.scalars(
                    select(SubjectAccessGrant)
                    .where(
                        SubjectAccessGrant.school_id == school_id,
                        SubjectAccessGrant.principal_account_id.in_(account_ids),
                        SubjectAccessGrant.relationship_type == "SELF",
                        SubjectAccessGrant.status == "ACTIVE",
                        SubjectAccessGrant.revoked_at.is_(None),
                        SubjectAccessGrant.valid_from <= at,
                        (SubjectAccessGrant.valid_until.is_(None))
                        | (SubjectAccessGrant.valid_until >= at),
                    )
                    .order_by(SubjectAccessGrant.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        if tuple(row.id for row in locked_grants) != grant_ids:
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID)
        account_by_id = {row.id: row for row in locked_accounts}
        membership_by_id = {row.id: row for row in locked_memberships}
        role_by_id = {row.id: row for row in locked_roles}
        batch_by_id = {row.id: row for row in locked_batches}
        class_by_id = {row.id: row for row in locked_classes}
        subject_by_id = {row.id: row for row in locked_subjects}
        grants_by_account: dict[int, list[SubjectAccessGrant]] = {}
        for grant in locked_grants:
            if discovered_grant_identity.get(grant.id) != (
                grant.principal_account_id,
                grant.subject_id,
                grant.school_id,
            ):
                raise ResearchCohortRepositoryError(
                    ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID
                )
            grants_by_account.setdefault(grant.principal_account_id, []).append(grant)
        if any(
            discovered_roster_identity.get(row.id) != (row.subject_id, row.class_id, row.school_id)
            for row in locked_rosters
        ):
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID)

        batch_class_ref: dict[int, str] = {}
        for batch in locked_batches:
            klass = class_by_id.get(batch.class_id)
            if (
                batch.school_id != school_id
                or batch.class_id is None
                or batch.id not in batch_ids
                or batch.row_count != 100
                or klass is None
                or klass.school_id != school_id
                or klass.status != "ACTIVE"
            ):
                raise ResearchCohortRepositoryError(
                    ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID
                )
            batch_class_ref[batch.id] = klass.class_ref
        if {batch.batch_ref for batch in locked_batches} != set(batch_refs):
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID)

        school = await self.session.scalar(
            select(School).where(School.id == school_id).execution_options(populate_existing=True)
        )
        if school is None or school.status != "ACTIVE" or school.data_origin != "SYNTHETIC":
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_SCOPE_MISMATCH)

        creator = await self.session.scalar(
            select(MembershipRole)
            .join(
                AccountSchoolMembership, MembershipRole.membership_id == AccountSchoolMembership.id
            )
            .join(Account, Account.id == AccountSchoolMembership.account_id)
            .where(
                MembershipRole.id == creator_membership_role_id,
                MembershipRole.school_id == school_id,
                MembershipRole.role_code.in_(("admin", "psychological_specialist")),
                MembershipRole.status == "ACTIVE",
                MembershipRole.revoked_at.is_(None),
                MembershipRole.valid_from <= at,
                (MembershipRole.valid_until.is_(None)) | (MembershipRole.valid_until >= at),
                AccountSchoolMembership.school_id == school_id,
                AccountSchoolMembership.status == "ACTIVE",
                AccountSchoolMembership.revoked_at.is_(None),
                AccountSchoolMembership.valid_from <= at,
                (AccountSchoolMembership.valid_until.is_(None))
                | (AccountSchoolMembership.valid_until >= at),
                Account.status == "ACTIVE",
            )
            .execution_options(populate_existing=True)
        )
        if creator is None:
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_SCOPE_MISMATCH)

        # Recheck every immutable batch/provision/account/role/member relationship.
        members: list[
            tuple[_DiscoveredMember, SchoolClassStudent, Subject, SubjectAccessGrant]
        ] = []
        for row in current_provisions:
            batch = batch_by_id.get(row.batch_id)
            account = account_by_id.get(row.account_id)
            membership = membership_by_id.get(row.membership_id)
            role = role_by_id.get(row.membership_role_id)
            if (
                batch is None
                or account is None
                or membership is None
                or role is None
                or row.batch_id not in batch_ids
                or row.school_id != school_id
                or row.status != "ACTIVE"
                or row.activated_at is None
                or row.role_code != "student"
                or account.status != "ACTIVE"
                or membership.account_id != account.id
                or membership.school_id != school_id
                or membership.status != "ACTIVE"
                or membership.revoked_at is not None
                or membership.valid_from > at
                or (membership.valid_until is not None and membership.valid_until < at)
                or role.membership_id != membership.id
                or role.school_id != school_id
                or role.role_code != "student"
                or role.status != "ACTIVE"
                or role.revoked_at is not None
                or role.valid_from > at
                or (role.valid_until is not None and role.valid_until < at)
            ):
                raise ResearchCohortRepositoryError(
                    ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID
                )
            eligible_grants = [
                grant
                for grant in grants_by_account.get(account.id, [])
                if grant.principal_account_id == account.id
                and grant.school_id == school_id
                and grant.relationship_type == "SELF"
                and grant.status == "ACTIVE"
                and grant.revoked_at is None
                and grant.valid_from <= at
                and (grant.valid_until is None or grant.valid_until >= at)
            ]
            if len(eligible_grants) != 1:
                raise ResearchCohortRepositoryError(
                    ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID
                )
            grant = eligible_grants[0]
            subject = subject_by_id.get(grant.subject_id)
            roster_candidates = [
                roster
                for roster in locked_rosters
                if roster.subject_id == grant.subject_id and roster.class_id == batch.class_id
            ]
            if len(roster_candidates) != 1:
                raise ResearchCohortRepositoryError(
                    ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID
                )
            roster = roster_candidates[0]
            if (
                subject is None
                or subject.school_id != school_id
                or subject.status != "ACTIVE"
                or subject.data_origin != "SYNTHETIC"
                or roster.school_id != school_id
                or roster.status != "ACTIVE"
                or roster.revoked_at is not None
                or roster.valid_from > at
                or (roster.valid_until is not None and roster.valid_until < at)
            ):
                raise ResearchCohortRepositoryError(
                    ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID
                )
            member = _DiscoveredMember(
                provision_id=row.id,
                account_id=account.id,
                membership_id=membership.id,
                membership_role_id=role.id,
                batch_id=batch.id,
                class_id=batch.class_id,
                batch_ref=batch.batch_ref,
            )
            members.append((member, roster, subject, grant))

        if (
            len(members) != 800
            or len({record[2].id for record in members}) != 800
            or {record[0].class_id for record in members} != set(class_ids)
            or any(
                sum(1 for record in members if record[0].batch_id == batch_id) != 100
                for batch_id in batch_ids
            )
        ):
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID)

        members.sort(key=lambda item: (item[0].class_id, item[1].id))
        cohort = SchoolResearchCohort(
            school_id=school_id,
            cohort_ref=cohort_ref,
            study_ref=study_ref,
            profile_version_id=profile_version_id,
            profile_ref=profile_ref,
            profile_version_number=profile_version_number,
            profile_sha256=expected_profile_sha256,
            manifest_sha256=expected_manifest_sha256,
            corpus_sha256=expected_corpus_sha256,
            assignment_sha256="0" * 64,
            case_count=800,
            class_count=8,
            subject_count=800,
            status="SEALED",
            purpose="RESEARCH_SIMULATION",
            research_only=True,
            human_curated=False,
            psychological_interpretation_allowed=False,
            sealed_at=at,
            created_by_membership_role_id=creator_membership_role_id,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(cohort)
                await self.session.flush()
                cohort_batch_by_batch: dict[int, SchoolResearchCohortBatch] = {}
                for batch in sorted(locked_batches, key=lambda item: item.id):
                    cohort_batch = SchoolResearchCohortBatch(
                        cohort_id=cohort.id,
                        school_id=school_id,
                        class_id=batch.class_id,
                        batch_id=batch.id,
                        class_ref=batch_class_ref[batch.id],
                        batch_ref=batch.batch_ref,
                        row_count=100,
                    )
                    self.session.add(cohort_batch)
                    cohort_batch_by_batch[batch.id] = cohort_batch
                await self.session.flush()
                assignment_rows: list[SchoolResearchCohortAssignment] = []
                for (member, roster, subject, grant), case_index in zip(
                    members, case_index_plan, strict=True
                ):
                    cohort_batch = cohort_batch_by_batch[member.batch_id]
                    assignment = SchoolResearchCohortAssignment(
                        cohort_id=cohort.id,
                        school_id=school_id,
                        cohort_batch_id=cohort_batch.id,
                        batch_id=member.batch_id,
                        class_id=member.class_id,
                        provision_id=member.provision_id,
                        account_id=member.account_id,
                        membership_id=member.membership_id,
                        membership_role_id=member.membership_role_id,
                        class_student_id=roster.id,
                        subject_id=subject.id,
                        self_grant_id=grant.id,
                        case_index=case_index,
                    )
                    assignment_rows.append(assignment)
                    self.session.add(assignment)
                await self.session.flush()
                cohort.assignment_sha256 = _assignment_map_sha256(
                    cohort,
                    tuple(cohort_batch_by_batch.values()),
                    tuple(assignment_rows),
                )
                await self.session.flush()
        except IntegrityError:
            raise ResearchCohortRepositoryError(
                ResearchCohortErrorCode.PERSISTENCE_CONFLICT
            ) from None
        return _cohort_metadata(cohort)

    async def get_cohort_metadata(
        self, *, school_id: int, cohort_ref: str
    ) -> ResearchCohortMetadata:
        """Read safe cohort metadata; never return members or case indices."""

        _require_id(school_id)
        _require_ref(cohort_ref)
        record = await self.session.scalar(
            select(SchoolResearchCohort).where(
                SchoolResearchCohort.school_id == school_id,
                SchoolResearchCohort.cohort_ref == cohort_ref,
            )
        )
        if record is None:
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_NOT_FOUND)
        await self._verify_sealed_map(record.id)
        return _cohort_metadata(record)

    async def require_existing_cohort_matches(
        self,
        *,
        school_id: int,
        cohort_ref: str,
        study_ref: str,
        profile_version_id: int,
        profile_ref: str,
        profile_version_number: int,
        expected_profile_sha256: str,
        expected_manifest_sha256: str,
        expected_corpus_sha256: str,
        batch_refs: tuple[str, ...],
    ) -> ResearchCohortMetadata:
        """Return an exact immutable replay receipt without accepting a new map."""

        _require_id(school_id)
        _require_ref(cohort_ref)
        _require_ref(study_ref)
        _require_id(profile_version_id)
        _require_ref(profile_ref)
        _validate_batch_refs(batch_refs)
        for sha in (expected_profile_sha256, expected_manifest_sha256, expected_corpus_sha256):
            if not isinstance(sha, str) or _SHA256.fullmatch(sha) is None:
                raise ResearchCohortRepositoryError(ResearchCohortErrorCode.INVALID_INPUT)
        record = await self.session.scalar(
            select(SchoolResearchCohort).where(
                SchoolResearchCohort.school_id == school_id,
                SchoolResearchCohort.cohort_ref == cohort_ref,
            )
        )
        if record is None:
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_NOT_FOUND)
        if (
            record.study_ref != study_ref
            or record.profile_version_id != profile_version_id
            or record.profile_ref != profile_ref
            or record.profile_version_number != profile_version_number
            or record.profile_sha256 != expected_profile_sha256
            or record.manifest_sha256 != expected_manifest_sha256
            or record.corpus_sha256 != expected_corpus_sha256
            or record.case_count != 800
            or record.class_count != 8
            or record.subject_count != 800
            or record.status != "SEALED"
        ):
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_SCOPE_MISMATCH)
        batch_rows = list(
            (
                await self.session.scalars(
                    select(SchoolResearchCohortBatch)
                    .where(
                        SchoolResearchCohortBatch.cohort_id == record.id,
                        SchoolResearchCohortBatch.school_id == school_id,
                    )
                    .order_by(SchoolResearchCohortBatch.id)
                )
            ).all()
        )
        if {row.batch_ref for row in batch_rows} != set(batch_refs):
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_SCOPE_MISMATCH)
        await self._verify_sealed_map(record.id)
        return _cohort_metadata(record)

    async def _verify_sealed_map(self, cohort_id: int) -> None:
        cohort = await self.session.scalar(
            select(SchoolResearchCohort)
            .where(SchoolResearchCohort.id == cohort_id)
            .execution_options(populate_existing=True)
        )
        if cohort is None:
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_SCOPE_MISMATCH)
        batches = list(
            (
                await self.session.scalars(
                    select(SchoolResearchCohortBatch)
                    .where(SchoolResearchCohortBatch.cohort_id == cohort_id)
                    .order_by(SchoolResearchCohortBatch.id)
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        assignments = list(
            (
                await self.session.scalars(
                    select(SchoolResearchCohortAssignment)
                    .where(SchoolResearchCohortAssignment.cohort_id == cohort_id)
                    .order_by(SchoolResearchCohortAssignment.id)
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        valid_header = (
            cohort.status == "SEALED"
            and cohort.purpose == "RESEARCH_SIMULATION"
            and cohort.research_only is True
            and cohort.human_curated is False
            and cohort.psychological_interpretation_allowed is False
            and cohort.case_count == 800
            and cohort.class_count == 8
            and cohort.subject_count == 800
            and isinstance(cohort.assignment_sha256, str)
            and _SHA256.fullmatch(cohort.assignment_sha256) is not None
        )
        batch_ids = {row.id for row in batches}
        batch_by_id = {row.id: row for row in batches}
        per_batch: dict[int, list[SchoolResearchCohortAssignment]] = {
            row.id: [] for row in batches
        }
        valid_assignments = True
        for assignment in assignments:
            batch = batch_by_id.get(assignment.cohort_batch_id)
            if (
                batch is None
                or assignment.cohort_id != cohort_id
                or assignment.school_id != cohort.school_id
                or assignment.class_id != batch.class_id
                or assignment.batch_id != batch.batch_id
            ):
                valid_assignments = False
                break
            per_batch[batch.id].append(assignment)
        subjects = {row.subject_id for row in assignments}
        case_indexes = {row.case_index for row in assignments}
        if (
            not valid_header
            or not valid_assignments
            or len(batches) != 8
            or len(batch_ids) != 8
            or len({row.class_id for row in batches}) != 8
            or any(row.row_count != 100 for row in batches)
            or len(assignments) != 800
            or len(subjects) != 800
            or case_indexes != set(range(800))
            or any(
                len(rows) != 100
                or len({row.subject_id for row in rows}) != 100
                or len({row.case_index for row in rows}) != 100
                for rows in per_batch.values()
            )
        ):
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_SCOPE_MISMATCH)
        actual_sha256 = _assignment_map_sha256(cohort, tuple(batches), tuple(assignments))
        if actual_sha256 != cohort.assignment_sha256:
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_SCOPE_MISMATCH)

    async def require_subject_assignment(
        self,
        *,
        cohort_id: int,
        school_id: int,
        class_id: int,
        class_student_id: int,
        subject_id: int,
    ) -> ResearchCohortCaseAssignment:
        """Resolve a private map for its exact current class-roster identity."""

        for value in (cohort_id, school_id, class_id, class_student_id, subject_id):
            _require_id(value)
        record = await self.session.scalar(
            select(SchoolResearchCohortAssignment).where(
                SchoolResearchCohortAssignment.cohort_id == cohort_id,
                SchoolResearchCohortAssignment.school_id == school_id,
                SchoolResearchCohortAssignment.class_id == class_id,
                SchoolResearchCohortAssignment.class_student_id == class_student_id,
                SchoolResearchCohortAssignment.subject_id == subject_id,
            )
        )
        if record is None:
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.CASE_ASSIGNMENT_NOT_FOUND)
        return ResearchCohortCaseAssignment(
            assignment_id=record.id,
            cohort_id=record.cohort_id,
            school_id=record.school_id,
            class_id=record.class_id,
            class_student_id=record.class_student_id,
            subject_id=record.subject_id,
            case_index=record.case_index,
        )

    async def _lock_ids(self, model: type, ids: tuple[int, ...]) -> list:
        if not ids:
            return []
        statement = (
            select(model)
            .where(model.id.in_(ids))
            .order_by(model.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        rows = list((await self.session.scalars(statement)).all())
        if tuple(item.id for item in rows) != tuple(sorted(ids)):
            raise ResearchCohortRepositoryError(ResearchCohortErrorCode.COHORT_MEMBERSHIP_INVALID)
        return rows


def _eligible_profile(profile: SchoolResearchProfileVersion | None) -> bool:
    return bool(
        profile is not None
        and profile.rights_status == "VERIFIED"
        and profile.execution_status == "SIMULATION_ENABLED"
        and profile.purpose == "RESEARCH_SIMULATION"
        and profile.research_only is True
        and profile.human_curated is False
        and profile.psychological_interpretation_allowed is False
        and profile.publication_status == "not_approved_for_publication_or_operational_use"
        and profile.rights_revoked_at is None
        and profile.disabled_at is None
        and profile.simulation_enabled_at is not None
        and profile.parameter_origin == "PUBLISHED_ROUNDED_REFERENCE"
        and profile.fit_sha256 is None
        and profile.calibration_sha256 is None
        and isinstance(profile.published_parameter_crosswalk_sha256, str)
        and _SHA256.fullmatch(profile.published_parameter_crosswalk_sha256) is not None
    )


def _cohort_metadata(record: SchoolResearchCohort) -> ResearchCohortMetadata:
    return ResearchCohortMetadata(
        cohort_id=record.id,
        school_id=record.school_id,
        cohort_ref=record.cohort_ref,
        study_ref=record.study_ref,
        profile_ref=record.profile_ref,
        profile_version_number=record.profile_version_number,
        profile_sha256=record.profile_sha256,
        manifest_sha256=record.manifest_sha256,
        corpus_sha256=record.corpus_sha256,
        case_count=record.case_count,
        class_count=record.class_count,
        subject_count=record.subject_count,
        sealed_at=record.sealed_at,
    )


def _assignment_map_sha256(
    cohort: SchoolResearchCohort,
    batches: tuple[SchoolResearchCohortBatch, ...],
    assignments: tuple[SchoolResearchCohortAssignment, ...],
) -> str:
    """Digest the canonical private member-to-case map without exposing it."""

    canonical = [
        "psynova.school-research-cohort-map.v1",
        [
            cohort.id,
            cohort.school_id,
            cohort.cohort_ref,
            cohort.study_ref,
            cohort.profile_version_id,
            cohort.profile_ref,
            cohort.profile_version_number,
            cohort.profile_sha256,
            cohort.manifest_sha256,
            cohort.corpus_sha256,
            cohort.case_count,
            cohort.class_count,
            cohort.subject_count,
        ],
        [
            [
                row.id,
                row.cohort_id,
                row.school_id,
                row.class_id,
                row.batch_id,
                row.class_ref,
                row.batch_ref,
                row.row_count,
            ]
            for row in sorted(batches, key=lambda item: (item.class_id, item.batch_id, item.id))
        ],
        [
            [
                row.id,
                row.cohort_batch_id,
                row.cohort_id,
                row.school_id,
                row.batch_id,
                row.class_id,
                row.provision_id,
                row.account_id,
                row.membership_id,
                row.membership_role_id,
                row.class_student_id,
                row.subject_id,
                row.self_grant_id,
                row.case_index,
            ]
            for row in sorted(assignments, key=lambda item: (item.subject_id, item.provision_id))
        ],
    ]
    encoded = json.dumps(canonical, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_batch_refs(batch_refs: tuple[str, ...]) -> None:
    if (
        not isinstance(batch_refs, tuple)
        or len(batch_refs) != 8
        or any(
            not isinstance(value, str) or _PUBLIC_REF.fullmatch(value) is None
            for value in batch_refs
        )
        or len(set(batch_refs)) != 8
    ):
        raise ResearchCohortRepositoryError(ResearchCohortErrorCode.INVALID_INPUT)


def _validate_case_plan(case_index_plan: tuple[int, ...]) -> None:
    if (
        not isinstance(case_index_plan, tuple)
        or len(case_index_plan) != 800
        or any(type(value) is not int or value < 0 or value >= 800 for value in case_index_plan)
        or set(case_index_plan) != set(range(800))
    ):
        raise ResearchCohortRepositoryError(ResearchCohortErrorCode.INVALID_INPUT)


def _require_ref(value: object) -> None:
    if not isinstance(value, str) or _PUBLIC_REF.fullmatch(value) is None:
        raise ResearchCohortRepositoryError(ResearchCohortErrorCode.INVALID_INPUT)


def _require_id(value: object) -> None:
    if type(value) is not int or value <= 0:
        raise ResearchCohortRepositoryError(ResearchCohortErrorCode.INVALID_INPUT)


def _utc_naive(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ResearchCohortRepositoryError(ResearchCohortErrorCode.INVALID_INPUT)
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
