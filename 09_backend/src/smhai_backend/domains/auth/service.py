"""Opaque server-side session authentication."""

from __future__ import annotations

from pwdlib import PasswordHash

from smhai_backend.core.async_utils import maybe_await
from smhai_backend.core.config import AuthSettings
from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.domains.audit import AuditService
from smhai_backend.domains.models import Actor, SessionRecord
from smhai_backend.domains.ports import SessionStore, UserRepository


class AuthService:
    def __init__(
        self,
        *,
        users: UserRepository,
        sessions: SessionStore,
        auth_settings: AuthSettings,
        audit: AuditService,
        password_hash: PasswordHash | None = None,
    ) -> None:
        self.users = users
        self.sessions = sessions
        self.settings = auth_settings
        self.audit = audit
        self.password_hash = password_hash or PasswordHash.recommended()

    async def login(
        self,
        *,
        username: str,
        password: str,
        old_session_id: str | None,
        request_id: str,
        trace_id: str,
    ) -> tuple[Actor, SessionRecord]:
        user = await maybe_await(self.users.get_by_username(username))
        valid = False
        if user is not None:
            try:
                valid = self.password_hash.verify(password, user.password_hash)
            except (ValueError, TypeError):
                valid = False
        if not valid:
            await self.audit.record(
                event="LOGIN_FAILURE",
                actor=None,
                request_id=request_id,
                trace_id=trace_id,
                outcome="denied",
                metadata={"credential_identifier_hash": _credential_hash(username)},
            )
            raise error(
                ErrorCode.AUTH_INVALID_CREDENTIALS,
                detail="username or password is invalid",
            )
        assert user is not None
        if old_session_id:
            await maybe_await(self.sessions.revoke(old_session_id))
        session = await maybe_await(
            self.sessions.create(user.user_id, self.settings.session_ttl_seconds)
        )
        actor = user.actor()
        await self.audit.record(
            event="LOGIN_SUCCESS",
            actor=actor,
            request_id=request_id,
            trace_id=trace_id,
            outcome="accepted",
            metadata={"session_rotated": bool(old_session_id)},
        )
        return actor, session

    async def actor_for_session(
        self, session_id: str | None, *, request_id: str, trace_id: str
    ) -> tuple[Actor, SessionRecord]:
        if not session_id:
            raise error(ErrorCode.AUTH_SESSION_EXPIRED, detail="authentication is required")
        session = await maybe_await(self.sessions.get(session_id))
        if session is None:
            code = (
                ErrorCode.AUTH_SESSION_REVOKED
                if await maybe_await(self.sessions.is_revoked(session_id))
                else ErrorCode.AUTH_SESSION_EXPIRED
            )
            raise error(code, detail="authentication is required")
        user = await maybe_await(self.users.get(session.user_id))
        if user is None:
            await maybe_await(self.sessions.revoke(session_id))
            raise error(ErrorCode.AUTH_SESSION_REVOKED, detail="authentication is required")
        touched = (
            await maybe_await(self.sessions.touch(session_id, self.settings.session_ttl_seconds))
            or session
        )
        return user.actor(), touched

    async def logout(self, session_id: str | None, *, request_id: str, trace_id: str) -> None:
        if session_id:
            session = await maybe_await(self.sessions.get(session_id))
            if session:
                user = await maybe_await(self.users.get(session.user_id))
                await self.audit.record(
                    event="LOGOUT",
                    actor=user.actor() if user else None,
                    request_id=request_id,
                    trace_id=trace_id,
                    outcome="accepted",
                    metadata={},
                )
            await maybe_await(self.sessions.revoke(session_id))


def _credential_hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()
