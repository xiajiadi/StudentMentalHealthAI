from __future__ import annotations

import copy
import hashlib
import secrets
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast

import database_layer.school_seed as school_seed
import pytest
from database_layer.base import utc_now
from database_layer.enums import AccountStatus, DataOrigin
from database_layer.provenance import SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF
from database_layer.school_seed import (
    SCHOOL_SEED_SLOTS,
    SYNTHETIC_SCHOOL_RECIPES,
    SyntheticSchoolSeedConflict,
    SyntheticSchoolSeedError,
    seed_synthetic_school_contexts,
)


class _FakeSession:
    def __init__(self) -> None:
        self.data: dict[str, list[SimpleNamespace]] = {
            name: []
            for name in (
                "schools",
                "subjects",
                "accounts",
                "memberships",
                "membership_roles",
                "account_roles",
                "grants",
            )
        }
        self.transaction_active = True
        self.savepoint_count = 0

    def in_transaction(self) -> bool:
        return self.transaction_active

    def begin_nested(self):
        session = self

        class _Savepoint:
            async def __aenter__(self):
                self.snapshot = copy.deepcopy(session.data)
                session.savepoint_count += 1
                return self

            async def __aexit__(self, exc_type, _exc, _traceback):
                if exc_type is not None:
                    session.data = self.snapshot
                return False

        return _Savepoint()

    def new_id(self, table_name: str) -> int:
        return len(self.data[table_name]) + 1


class _FakeAccountRepository:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def get_by_login_name(self, login_name: str):
        return next(
            (
                account
                for account in self.session.data["accounts"]
                if account.login_name.casefold() == login_name.casefold()
            ),
            None,
        )

    async def create(self, *, login_name: str, password_hash: str, status: AccountStatus):
        row = SimpleNamespace(
            id=self.session.new_id("accounts"),
            public_id=f"PUBLIC_ACCOUNT_{self.session.new_id('accounts')}".ljust(36, "X"),
            login_name=login_name,
            password_hash=password_hash,
            status=status.value,
        )
        self.session.data["accounts"].append(row)
        return row


class _FakeSubjectRepository:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def get_by_ref(self, subject_ref: str):
        return next(
            (row for row in self.session.data["subjects"] if row.subject_ref == subject_ref),
            None,
        )

    async def for_school(self, *, school_id: int):
        return [row for row in self.session.data["subjects"] if row.school_id == school_id]

    async def create(self, *, subject_ref: str, school_id: int, data_origin: DataOrigin):
        row = SimpleNamespace(
            id=self.session.new_id("subjects"),
            subject_ref=subject_ref,
            school_id=school_id,
            status="ACTIVE",
            data_origin=data_origin.value,
        )
        self.session.data["subjects"].append(row)
        return row


class _FakeSchoolMembershipRepository:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def get_school_by_ref(self, school_ref: str):
        return next(
            (row for row in self.session.data["schools"] if row.school_ref == school_ref),
            None,
        )

    async def schools_with_provenance(self, *, provenance_ref: str):
        return [
            row
            for row in self.session.data["schools"]
            if row.provenance_ref == provenance_ref
        ]

    async def memberships_for_account(self, *, account_id: int):
        return [
            row for row in self.session.data["memberships"] if row.account_id == account_id
        ]

    async def memberships_for_school(self, *, school_id: int):
        return [
            row for row in self.session.data["memberships"] if row.school_id == school_id
        ]

    async def roles_for_membership(self, *, membership_id: int):
        return [
            row
            for row in self.session.data["membership_roles"]
            if row.membership_id == membership_id
        ]

    async def grants_for_account(self, *, account_id: int):
        return [
            row for row in self.session.data["grants"] if row.principal_account_id == account_id
        ]

    async def platform_roles_for_account(self, *, account_id: int):
        return [row for row in self.session.data["account_roles"] if row.account_id == account_id]

    async def grants_for_subjects(self, *, subject_ids: list[int]):
        return [row for row in self.session.data["grants"] if row.subject_id in subject_ids]

    async def create_school(self, *, school_ref: str, data_origin: DataOrigin, provenance_ref: str):
        if data_origin != DataOrigin.SYNTHETIC:
            raise ValueError("synthetic only")
        row = SimpleNamespace(
            id=self.session.new_id("schools"),
            school_ref=school_ref,
            status="ACTIVE",
            data_origin=data_origin.value,
            provenance_ref=provenance_ref,
        )
        self.session.data["schools"].append(row)
        return row

    async def create_membership(self, *, account_id: int, school_id: int, valid_from):
        row = SimpleNamespace(
            id=self.session.new_id("memberships"),
            account_id=account_id,
            school_id=school_id,
            status="ACTIVE",
            revoked_at=None,
            valid_from=valid_from,
            valid_until=None,
        )
        self.session.data["memberships"].append(row)
        return row

    async def add_role(self, *, membership_id: int, school_id: int, role_code: str, valid_from):
        row = SimpleNamespace(
            id=self.session.new_id("membership_roles"),
            membership_id=membership_id,
            school_id=school_id,
            role_code=role_code,
            status="ACTIVE",
            revoked_at=None,
            valid_from=valid_from,
            valid_until=None,
        )
        self.session.data["membership_roles"].append(row)
        return row

    async def grant_subject_in_school(
        self,
        *,
        principal_account_id: int,
        subject_id: int,
        school_id: int,
        role_code: str,
        valid_from,
    ):
        role = {"student": "SELF", "teacher": "TEACHER_OF"}.get(role_code)
        if role is None:
            raise ValueError("role cannot receive grant")
        membership = next(
            (
                item
                for item in self.session.data["memberships"]
                if item.account_id == principal_account_id and item.school_id == school_id
            ),
            None,
        )
        subject = next(
            (
                item
                for item in self.session.data["subjects"]
                if item.id == subject_id and item.school_id == school_id
            ),
            None,
        )
        if membership is None or subject is None:
            raise ValueError("cross-school grant rejected")
        row = SimpleNamespace(
            principal_account_id=principal_account_id,
            subject_id=subject_id,
            school_id=school_id,
            relationship_type=role,
            status="ACTIVE",
            revoked_at=None,
            valid_from=valid_from,
            valid_until=None,
        )
        self.session.data["grants"].append(row)
        return row


class _SyntheticHasher:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.hash_calls = 0
        self.verify_calls = 0

    def hash(self, password: str) -> str:
        self.hash_calls += 1
        encoded = "$argon2id$synthetic$" + hashlib.sha256(password.encode()).hexdigest()
        self.values[encoded] = password
        return encoded

    def verify(self, password: str, encoded_hash: str) -> bool:
        self.verify_calls += 1
        return self.values.get(encoded_hash) == password


def _credentials() -> dict[str, tuple[str, str]]:
    return {
        slot: (
            "SYNTHETIC_" + slot.replace(".", "_").upper(),
            secrets.token_urlsafe(32),
        )
        for slot in SCHOOL_SEED_SLOTS
    }


def _use_fake_repositories(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(school_seed, "AccountRepository", _FakeAccountRepository)
    monkeypatch.setattr(school_seed, "SubjectRepository", _FakeSubjectRepository)
    monkeypatch.setattr(school_seed, "SchoolMembershipRepository", _FakeSchoolMembershipRepository)


async def _run_seed(
    session: _FakeSession,
    *,
    credentials: dict[str, tuple[str, str]],
    password_hasher: school_seed.PasswordHasher,
):
    return await seed_synthetic_school_contexts(
        cast(Any, session),
        credentials=credentials,
        password_hasher=password_hasher,
    )


async def test_school_seed_creates_two_isolated_schools_with_minimal_grants(monkeypatch):
    _use_fake_repositories(monkeypatch)
    session = _FakeSession()
    hasher = _SyntheticHasher()
    credentials = _credentials()

    result = await _run_seed(
        session,
        credentials=credentials,
        password_hasher=hasher,
    )

    assert len(result.school_refs) == 2
    assert len(result.subject_refs) == 2
    assert len(result.account_public_ids) == 8
    assert len({account_id for _, account_id in result.account_public_ids}) == 8
    assert hasher.hash_calls == 8
    assert session.savepoint_count == 1
    assert len(session.data["schools"]) == 2
    assert len(session.data["subjects"]) == 2
    assert len(session.data["accounts"]) == 8
    assert len(session.data["memberships"]) == 8
    assert len(session.data["membership_roles"]) == 8
    assert len(session.data["grants"]) == 4
    assert session.data["account_roles"] == []
    assert {row.provenance_ref for row in session.data["schools"]} == {
        SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF
    }

    schools = {row.school_ref: row for row in session.data["schools"]}
    subjects = {row.subject_ref: row for row in session.data["subjects"]}
    accounts = {row.login_name: row for row in session.data["accounts"]}
    grants_by_login = {}
    for grant in session.data["grants"]:
        account = next(
            row for row in session.data["accounts"] if row.id == grant.principal_account_id
        )
        grants_by_login[account.login_name] = grant

    assert schools[SYNTHETIC_SCHOOL_RECIPES[0].school_ref].id != schools[
        SYNTHETIC_SCHOOL_RECIPES[1].school_ref
    ].id
    assert subjects[SYNTHETIC_SCHOOL_RECIPES[0].subject_ref].school_id != subjects[
        SYNTHETIC_SCHOOL_RECIPES[1].subject_ref
    ].school_id
    for recipe in SYNTHETIC_SCHOOL_RECIPES:
        school_id = schools[recipe.school_ref].id
        own_subject = subjects[recipe.subject_ref]
        for role_code in ("student", "teacher"):
            slot = f"{recipe.key}.{role_code}"
            grant = grants_by_login[accounts[credentials[slot][0]].login_name]
            assert grant.school_id == school_id
            assert grant.subject_id == own_subject.id
            assert grant.relationship_type == ("SELF" if role_code == "student" else "TEACHER_OF")
        for role_code in ("psychological_specialist", "admin"):
            slot = f"{recipe.key}.{role_code}"
            assert credentials[slot][0] not in grants_by_login

    assert all(password not in repr(result) for _, password in credentials.values())


async def test_school_seed_exact_repeat_reads_existing_hashes_without_rehash(monkeypatch):
    _use_fake_repositories(monkeypatch)
    session = _FakeSession()
    hasher = _SyntheticHasher()
    credentials = _credentials()
    first = await _run_seed(
        session, credentials=credentials, password_hasher=hasher
    )
    before = copy.deepcopy(session.data)

    second = await _run_seed(
        session, credentials=credentials, password_hasher=hasher
    )

    assert second == first
    assert hasher.hash_calls == 8
    assert hasher.verify_calls == 8
    assert session.data == before


async def test_school_seed_rejects_inactive_existing_context_without_changes(monkeypatch):
    _use_fake_repositories(monkeypatch)
    session = _FakeSession()
    hasher = _SyntheticHasher()
    credentials = _credentials()
    await _run_seed(session, credentials=credentials, password_hasher=hasher)
    session.data["memberships"][0].valid_until = utc_now() - timedelta(seconds=1)
    before = copy.deepcopy(session.data)

    with pytest.raises(SyntheticSchoolSeedConflict):
        await _run_seed(session, credentials=credentials, password_hasher=hasher)

    assert session.data == before
    assert hasher.hash_calls == 8


async def test_school_seed_changed_credentials_fail_without_password_rotation(monkeypatch):
    _use_fake_repositories(monkeypatch)
    session = _FakeSession()
    hasher = _SyntheticHasher()
    credentials = _credentials()
    await _run_seed(
        session, credentials=credentials, password_hasher=hasher
    )
    before = copy.deepcopy(session.data)
    changed = dict(credentials)
    slot = SCHOOL_SEED_SLOTS[0]
    changed[slot] = (credentials[slot][0], secrets.token_urlsafe(32))
    changed_password = changed[slot][1]

    with pytest.raises(SyntheticSchoolSeedConflict) as caught:
        await _run_seed(
            session, credentials=changed, password_hasher=hasher
        )

    assert session.data == before
    assert changed_password not in str(caught.value)
    assert changed_password not in repr(caught.value)
    assert hasher.hash_calls == 8


async def test_school_seed_partial_or_unrelated_state_fails_without_writes(monkeypatch):
    _use_fake_repositories(monkeypatch)
    session = _FakeSession()
    session.data["schools"].append(
        SimpleNamespace(
            id=1,
            school_ref=SYNTHETIC_SCHOOL_RECIPES[0].school_ref,
            status="ACTIVE",
            data_origin="SYNTHETIC",
            provenance_ref=SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF,
        )
    )
    before = copy.deepcopy(session.data)
    hasher = _SyntheticHasher()

    with pytest.raises(SyntheticSchoolSeedConflict):
        await _run_seed(
            session, credentials=_credentials(), password_hasher=hasher
        )

    assert session.data == before
    assert hasher.hash_calls == 0


async def test_school_seed_rolls_back_partial_writes_to_its_savepoint(monkeypatch):
    class _FailingSchoolRepository(_FakeSchoolMembershipRepository):
        async def add_role(self, **_kwargs):
            raise RuntimeError("SYNTHETIC_INSERT_FAILURE_SENTINEL")

    monkeypatch.setattr(school_seed, "AccountRepository", _FakeAccountRepository)
    monkeypatch.setattr(school_seed, "SubjectRepository", _FakeSubjectRepository)
    monkeypatch.setattr(school_seed, "SchoolMembershipRepository", _FailingSchoolRepository)
    session = _FakeSession()
    before = copy.deepcopy(session.data)

    with pytest.raises(RuntimeError, match="SYNTHETIC_INSERT_FAILURE_SENTINEL"):
        await _run_seed(
            session,
            credentials=_credentials(),
            password_hasher=_SyntheticHasher(),
        )

    assert session.data == before
    assert session.transaction_active is True


async def test_school_seed_validates_all_eight_credentials_without_echo(monkeypatch):
    _use_fake_repositories(monkeypatch)
    session = _FakeSession()
    hasher = _SyntheticHasher()
    credentials = _credentials()
    missing = dict(credentials)
    password = missing.pop(SCHOOL_SEED_SLOTS[0])[1]
    with pytest.raises(SyntheticSchoolSeedError) as missing_error:
        await _run_seed(
            session, credentials=missing, password_hasher=hasher
        )
    assert password not in str(missing_error.value)
    assert password not in repr(missing_error.value)

    malformed = dict(credentials)
    malformed[SCHOOL_SEED_SLOTS[0]] = ("real-name-sentinel", credentials[SCHOOL_SEED_SLOTS[0]][1])
    with pytest.raises(SyntheticSchoolSeedError):
        await _run_seed(
            session, credentials=malformed, password_hasher=hasher
        )

    weak_passwords = dict(credentials)
    slot = SCHOOL_SEED_SLOTS[1]
    weak_password_sentinel = "SYNTH_WEAK"
    weak_passwords[slot] = (credentials[slot][0], weak_password_sentinel)
    with pytest.raises(SyntheticSchoolSeedError) as weak_error:
        await _run_seed(
            session, credentials=weak_passwords, password_hasher=hasher
        )
    assert weak_password_sentinel not in str(weak_error.value)
    assert weak_password_sentinel not in repr(weak_error.value)
    assert hasher.hash_calls == 0


def test_school_seed_credential_limits_match_login_request_without_echo():
    credentials = _credentials()
    slot = SCHOOL_SEED_SLOTS[0]
    max_login = "SYNTHETIC_" + ("A" * 118)
    max_password = "x" * 256
    accepted = dict(credentials)
    accepted[slot] = (max_login, max_password)

    validated = school_seed._validated_credentials(accepted)
    assert len(validated[slot][0]) == 128
    assert len(validated[slot][1]) == 256

    overlong_login = "SYNTHETIC_" + ("B" * 119)
    rejected_login = dict(credentials)
    rejected_login[slot] = (overlong_login, credentials[slot][1])
    with pytest.raises(SyntheticSchoolSeedError) as login_error:
        school_seed._validated_credentials(rejected_login)
    assert overlong_login not in str(login_error.value)
    assert overlong_login not in repr(login_error.value)

    overlong_password = "y" * 257
    rejected_password = dict(credentials)
    rejected_password[slot] = (credentials[slot][0], overlong_password)
    with pytest.raises(SyntheticSchoolSeedError) as password_error:
        school_seed._validated_credentials(rejected_password)
    assert overlong_password not in str(password_error.value)
    assert overlong_password not in repr(password_error.value)


async def test_school_seed_sanitizes_hashing_errors_and_rolls_back(monkeypatch):
    _use_fake_repositories(monkeypatch)
    session = _FakeSession()
    credentials = _credentials()
    sentinel = credentials[SCHOOL_SEED_SLOTS[0]][1]

    class _FailingHasher:
        def hash(self, password: str) -> str:
            del password
            raise RuntimeError(f"SYNTHETIC_HASH_FAILURE:{sentinel}")

        def verify(self, password: str, encoded_hash: str) -> bool:
            del password, encoded_hash
            return False

    with pytest.raises(SyntheticSchoolSeedError) as caught:
        await _run_seed(
            session, credentials=credentials, password_hasher=_FailingHasher()
        )

    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)
    assert all(not rows for rows in session.data.values())


async def test_school_seed_requires_caller_owned_transaction(monkeypatch):
    _use_fake_repositories(monkeypatch)
    session = _FakeSession()
    session.transaction_active = False
    with pytest.raises(SyntheticSchoolSeedError, match="caller-owned transaction"):
        await _run_seed(
            session, credentials=_credentials(), password_hasher=_SyntheticHasher()
        )
    assert session.savepoint_count == 0
