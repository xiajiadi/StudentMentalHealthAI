"""Explicit, caller-transaction-owned synthetic school seed recipe."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from .base import utc_now
from .enums import AccountStatus, DataOrigin
from .errors import UniqueConflict
from .models import (
    Account,
    AccountRole,
    AccountSchoolMembership,
    MembershipRole,
    School,
    Subject,
    SubjectAccessGrant,
)
from .provenance import SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF
from .repositories import AccountRepository, SchoolMembershipRepository, SubjectRepository

SCHOOL_SEED_SLOTS = tuple(
    f"{school}.{role}"
    for school in ("alpha", "beta")
    for role in ("student", "teacher", "psychological_specialist", "admin")
)
SCHOOL_SEED_ROLE_CODES = ("student", "teacher", "psychological_specialist", "admin")


@dataclass(frozen=True, slots=True)
class SyntheticSchoolRecipe:
    key: str
    school_ref: str
    subject_ref: str


SYNTHETIC_SCHOOL_RECIPES = (
    SyntheticSchoolRecipe(
        key="alpha",
        school_ref="SYNTHETIC_SCHOOL_SEED_ALPHA_V1",
        subject_ref="SUBJ_SYNTHETIC_SCHOOL_SEED_ALPHA_V1",
    ),
    SyntheticSchoolRecipe(
        key="beta",
        school_ref="SYNTHETIC_SCHOOL_SEED_BETA_V1",
        subject_ref="SUBJ_SYNTHETIC_SCHOOL_SEED_BETA_V1",
    ),
)

_SYNTHETIC_LOGIN_PREFIX = "SYNTHETIC_"
_MAX_LOGIN_LENGTH = 128
_MAX_LOGIN_SUFFIX_LENGTH = _MAX_LOGIN_LENGTH - len(_SYNTHETIC_LOGIN_PREFIX)
_SYNTHETIC_LOGIN = re.compile(
    rf"{_SYNTHETIC_LOGIN_PREFIX}[A-Za-z0-9._-]{{1,{_MAX_LOGIN_SUFFIX_LENGTH}}}\Z"
)
_MIN_PASSWORD_LENGTH = 16
_MAX_PASSWORD_LENGTH = 256


class PasswordHasher(Protocol):
    """Small adapter implemented by the caller's configured Argon2id hasher."""

    def hash(self, password: str) -> str: ...

    def verify(self, password: str, encoded_hash: str) -> bool: ...


class SyntheticSchoolSeedError(ValueError):
    """Safe seed failure that never includes caller credential values."""


class SyntheticSchoolSeedConflict(SyntheticSchoolSeedError):
    """Seed identifiers or persisted state conflict with this recipe."""


@dataclass(frozen=True, slots=True)
class SyntheticSchoolSeedResult:
    school_refs: tuple[str, ...]
    subject_refs: tuple[str, ...]
    account_public_ids: tuple[tuple[str, str], ...]


def _active_at(
    record: AccountSchoolMembership | MembershipRole | SubjectAccessGrant,
    at: datetime,
) -> bool:
    return (
        record.status == "ACTIVE"
        and record.revoked_at is None
        and record.valid_from <= at
        and (record.valid_until is None or record.valid_until >= at)
    )


def _validated_credentials(
    credentials: Mapping[str, tuple[str, str]],
) -> dict[str, tuple[str, str]]:
    if not isinstance(credentials, Mapping) or set(credentials) != set(SCHOOL_SEED_SLOTS):
        raise SyntheticSchoolSeedError("exactly eight named synthetic credentials are required")

    validated: dict[str, tuple[str, str]] = {}
    normalized_logins: set[str] = set()
    for slot in SCHOOL_SEED_SLOTS:
        entry = credentials[slot]
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise SyntheticSchoolSeedError("synthetic credentials have an invalid shape")
        login_name, password = entry
        if (
            not isinstance(login_name, str)
            or _SYNTHETIC_LOGIN.fullmatch(login_name) is None
            or not isinstance(password, str)
            or not _MIN_PASSWORD_LENGTH <= len(password) <= _MAX_PASSWORD_LENGTH
        ):
            raise SyntheticSchoolSeedError("synthetic credentials are malformed")
        normalized_login = login_name.casefold()
        if normalized_login in normalized_logins:
            raise SyntheticSchoolSeedError("synthetic login names must be unique")
        normalized_logins.add(normalized_login)
        validated[slot] = (login_name, password)
    return validated


def _make_result(
    accounts: Mapping[str, Account],
) -> SyntheticSchoolSeedResult:
    return SyntheticSchoolSeedResult(
        school_refs=tuple(recipe.school_ref for recipe in SYNTHETIC_SCHOOL_RECIPES),
        subject_refs=tuple(recipe.subject_ref for recipe in SYNTHETIC_SCHOOL_RECIPES),
        account_public_ids=tuple(
            (slot, accounts[slot].public_id) for slot in SCHOOL_SEED_SLOTS
        ),
    )


async def _is_exact_existing_seed(
    *,
    memberships: SchoolMembershipRepository,
    credentials: Mapping[str, tuple[str, str]],
    password_hasher: PasswordHasher,
    at: datetime,
    schools_by_key: Mapping[str, School | None],
    subjects_by_key: Mapping[str, Subject | None],
    accounts_by_slot: Mapping[str, Account | None],
    account_memberships: Mapping[str, list[AccountSchoolMembership]],
    membership_roles: Mapping[int, list[MembershipRole]],
    account_grants: Mapping[str, list[SubjectAccessGrant]],
    platform_roles: Mapping[str, list[AccountRole]],
    schools_by_provenance: list[School],
    school_memberships: Mapping[str, list[AccountSchoolMembership]],
    school_subjects: Mapping[str, list[Subject]],
    subject_grants: list[SubjectAccessGrant],
) -> bool:
    if any(schools_by_key.get(recipe.key) is None for recipe in SYNTHETIC_SCHOOL_RECIPES):
        return False
    if any(subjects_by_key.get(recipe.key) is None for recipe in SYNTHETIC_SCHOOL_RECIPES):
        return False
    if any(accounts_by_slot.get(slot) is None for slot in SCHOOL_SEED_SLOTS):
        return False

    if len(schools_by_provenance) != len(SYNTHETIC_SCHOOL_RECIPES) or {
        school.school_ref for school in schools_by_provenance
    } != {recipe.school_ref for recipe in SYNTHETIC_SCHOOL_RECIPES}:
        return False

    expected_grants: set[tuple[int, int, int, str]] = set()
    for recipe in SYNTHETIC_SCHOOL_RECIPES:
        school = schools_by_key[recipe.key]
        subject = subjects_by_key[recipe.key]
        if school is None or subject is None:
            return False
        school_id = school.id
        subject_id = subject.id
        if (
            school.status != "ACTIVE"
            or school.data_origin != DataOrigin.SYNTHETIC.value
            or school.provenance_ref != SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF
            or subject.school_id != school_id
            or subject.subject_ref != recipe.subject_ref
            or subject.status != "ACTIVE"
            or subject.data_origin != DataOrigin.SYNTHETIC.value
        ):
            return False

        expected_membership_account_ids: set[int] = set()
        for role_code in SCHOOL_SEED_ROLE_CODES:
            slot = f"{recipe.key}.{role_code}"
            account = accounts_by_slot[slot]
            if account is None:
                return False
            account_id = account.id
            expected_membership_account_ids.add(account_id)
            if (
                account.login_name != credentials[slot][0]
                or account.status != AccountStatus.ACTIVE.value
                or platform_roles[slot]
            ):
                return False
            try:
                if not password_hasher.verify(credentials[slot][1], account.password_hash):
                    return False
            except Exception:
                raise SyntheticSchoolSeedConflict(
                    "provided credentials do not match the persisted synthetic seed"
                ) from None

            account_contexts = account_memberships[slot]
            if len(account_contexts) != 1:
                return False
            membership = account_contexts[0]
            if (
                membership.account_id != account_id
                or membership.school_id != school_id
                or not _active_at(membership, at)
            ):
                return False
            membership_id = membership.id
            roles = membership_roles[membership_id]
            if len(roles) != 1:
                return False
            school_role = roles[0]
            if (
                school_role.membership_id != membership_id
                or school_role.school_id != school_id
                or school_role.role_code != role_code
                or not _active_at(school_role, at)
            ):
                return False

            expected_relation = {"student": "SELF", "teacher": "TEACHER_OF"}.get(role_code)
            grants = account_grants[slot]
            if expected_relation is None:
                if grants:
                    return False
            else:
                if len(grants) != 1:
                    return False
                grant = grants[0]
                if (
                    grant.principal_account_id != account_id
                    or grant.subject_id != subject_id
                    or grant.school_id != school_id
                    or grant.relationship_type != expected_relation
                    or not _active_at(grant, at)
                ):
                    return False
                expected_grants.add((account_id, subject_id, school_id, expected_relation))

        if len(school_memberships[recipe.key]) != len(SCHOOL_SEED_ROLE_CODES) or {
            membership.account_id
            for membership in school_memberships[recipe.key]
        } != expected_membership_account_ids:
            return False
        school_subject_rows = school_subjects[recipe.key]
        if len(school_subject_rows) != 1 or school_subject_rows[0].id != subject_id:
            return False

    actual_grants = {
        (
            grant.principal_account_id,
            grant.subject_id,
            grant.school_id,
            grant.relationship_type,
        )
        for grant in subject_grants
    }
    return len(actual_grants) == len(subject_grants) and actual_grants == expected_grants


async def seed_synthetic_school_contexts(
    session: AsyncSession,
    *,
    credentials: Mapping[str, tuple[str, str]],
    password_hasher: PasswordHasher,
) -> SyntheticSchoolSeedResult:
    """Create or exactly read back the two registered synthetic school contexts.

    Callers must open the transaction before invoking this API and commit or
    roll it back themselves. Passwords are hashed in memory by the caller's
    configured Argon2id adapter; this function never logs, returns, or embeds
    them in safe errors.
    """

    clean_credentials = _validated_credentials(credentials)
    if not session.in_transaction():
        raise SyntheticSchoolSeedError("school seed requires a caller-owned transaction")

    memberships = SchoolMembershipRepository(session)
    account_repository = AccountRepository(session)
    subject_repository = SubjectRepository(session)

    try:
        async with session.begin_nested():
            verification_time = utc_now()
            schools_by_key: dict[str, School | None] = {
                recipe.key: await memberships.get_school_by_ref(recipe.school_ref)
                for recipe in SYNTHETIC_SCHOOL_RECIPES
            }
            subjects_by_key: dict[str, Subject | None] = {
                recipe.key: await subject_repository.get_by_ref(recipe.subject_ref)
                for recipe in SYNTHETIC_SCHOOL_RECIPES
            }
            existing_accounts_by_slot: dict[str, Account | None] = {
                slot: await account_repository.get_by_login_name(clean_credentials[slot][0])
                for slot in SCHOOL_SEED_SLOTS
            }

            account_memberships: dict[str, list[AccountSchoolMembership]] = {}
            membership_roles: dict[int, list[MembershipRole]] = {}
            account_grants: dict[str, list[SubjectAccessGrant]] = {}
            platform_roles: dict[str, list[AccountRole]] = {}
            for slot, account in existing_accounts_by_slot.items():
                if account is None:
                    account_memberships[slot] = []
                    account_grants[slot] = []
                    platform_roles[slot] = []
                    continue
                account_id = account.id
                contexts = await memberships.memberships_for_account(account_id=account_id)
                account_memberships[slot] = list(contexts)
                account_grants[slot] = await memberships.grants_for_account(
                    account_id=account_id
                )
                platform_roles[slot] = await memberships.platform_roles_for_account(
                    account_id=account_id
                )
                for context in contexts:
                    context_id = context.id
                    membership_roles[context_id] = await memberships.roles_for_membership(
                        membership_id=context_id
                    )

            schools_by_provenance = await memberships.schools_with_provenance(
                provenance_ref=SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF
            )
            school_memberships: dict[str, list[AccountSchoolMembership]] = {}
            school_subjects: dict[str, list[Subject]] = {}
            for recipe in SYNTHETIC_SCHOOL_RECIPES:
                school = schools_by_key[recipe.key]
                if school is None:
                    school_memberships[recipe.key] = []
                    school_subjects[recipe.key] = []
                    continue
                school_id = school.id
                school_memberships[recipe.key] = await memberships.memberships_for_school(
                    school_id=school_id
                )
                school_subjects[recipe.key] = await subject_repository.for_school(
                    school_id=school_id
                )

            found_subject_ids = [
                subject.id
                for subject in subjects_by_key.values()
                if subject is not None
            ]
            subject_grants = await memberships.grants_for_subjects(
                subject_ids=found_subject_ids
            )
            any_existing = bool(
                any(schools_by_key.values())
                or any(subjects_by_key.values())
                or any(existing_accounts_by_slot.values())
                or any(account_memberships.values())
                or any(membership_roles.values())
                or any(account_grants.values())
                or any(platform_roles.values())
                or schools_by_provenance
                or any(school_memberships.values())
                or any(school_subjects.values())
                or subject_grants
            )
            if any_existing:
                exact = await _is_exact_existing_seed(
                    memberships=memberships,
                    credentials=clean_credentials,
                    password_hasher=password_hasher,
                    at=verification_time,
                    schools_by_key=schools_by_key,
                    subjects_by_key=subjects_by_key,
                    accounts_by_slot=existing_accounts_by_slot,
                    account_memberships=account_memberships,
                    membership_roles=membership_roles,
                    account_grants=account_grants,
                    platform_roles=platform_roles,
                    schools_by_provenance=schools_by_provenance,
                    school_memberships=school_memberships,
                    school_subjects=school_subjects,
                    subject_grants=subject_grants,
                )
                if not exact:
                    raise SyntheticSchoolSeedConflict(
                        "existing school seed state conflicts with the registered recipe"
                    )
                complete_accounts = {
                    slot: account
                    for slot, account in existing_accounts_by_slot.items()
                    if account is not None
                }
                if len(complete_accounts) != len(SCHOOL_SEED_SLOTS):
                    raise SyntheticSchoolSeedConflict(
                        "existing school seed state conflicts with the registered recipe"
                    )
                return _make_result(complete_accounts)

            encoded_hashes: dict[str, str] = {}
            for slot in SCHOOL_SEED_SLOTS:
                try:
                    encoded_hash = password_hasher.hash(clean_credentials[slot][1])
                except Exception:
                    raise SyntheticSchoolSeedError("password hashing failed") from None
                if (
                    not isinstance(encoded_hash, str)
                    or not encoded_hash.startswith("$argon2id$")
                    or len(encoded_hash) > 255
                ):
                    raise SyntheticSchoolSeedError(
                        "password hasher must return an Argon2id encoded value"
                    )
                encoded_hashes[slot] = encoded_hash

            schools: dict[str, School] = {}
            subjects: dict[str, Subject] = {}
            for recipe in SYNTHETIC_SCHOOL_RECIPES:
                school = await memberships.create_school(
                    school_ref=recipe.school_ref,
                    data_origin=DataOrigin.SYNTHETIC,
                    provenance_ref=SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF,
                )
                schools[recipe.key] = school
                subjects[recipe.key] = await subject_repository.create(
                    subject_ref=recipe.subject_ref,
                    school_id=school.id,
                    data_origin=DataOrigin.SYNTHETIC,
                )

            accounts_by_slot: dict[str, Account] = {}
            for slot in SCHOOL_SEED_SLOTS:
                login_name, _ = clean_credentials[slot]
                accounts_by_slot[slot] = await account_repository.create(
                    login_name=login_name,
                    password_hash=encoded_hashes[slot],
                    status=AccountStatus.ACTIVE,
                )

            membership_time = verification_time
            for recipe in SYNTHETIC_SCHOOL_RECIPES:
                school_id = schools[recipe.key].id
                for role_code in SCHOOL_SEED_ROLE_CODES:
                    slot = f"{recipe.key}.{role_code}"
                    membership = await memberships.create_membership(
                        account_id=accounts_by_slot[slot].id,
                        school_id=school_id,
                        valid_from=membership_time,
                    )
                    await memberships.add_role(
                        membership_id=membership.id,
                        school_id=school_id,
                        role_code=role_code,
                        valid_from=membership_time,
                    )

            for recipe in SYNTHETIC_SCHOOL_RECIPES:
                school_id = schools[recipe.key].id
                subject_id = subjects[recipe.key].id
                for role_code in ("student", "teacher"):
                    slot = f"{recipe.key}.{role_code}"
                    await memberships.grant_subject_in_school(
                        principal_account_id=accounts_by_slot[slot].id,
                        subject_id=subject_id,
                        school_id=school_id,
                        role_code=role_code,
                        valid_from=membership_time,
                    )

            return _make_result(accounts_by_slot)
    except UniqueConflict:
        raise SyntheticSchoolSeedConflict(
            "synthetic school seed identifiers conflict with persisted data"
        ) from None


__all__ = [
    "PasswordHasher",
    "SCHOOL_SEED_ROLE_CODES",
    "SCHOOL_SEED_SLOTS",
    "SYNTHETIC_SCHOOL_RECIPES",
    "SyntheticSchoolRecipe",
    "SyntheticSchoolSeedConflict",
    "SyntheticSchoolSeedError",
    "SyntheticSchoolSeedResult",
    "seed_synthetic_school_contexts",
]
