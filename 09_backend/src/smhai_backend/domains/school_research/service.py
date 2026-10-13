"""L1-only service orchestration for the private research CAT bridge."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from smhai_backend.core.errors import BackendError, ErrorCode, error
from smhai_backend.domains.models import Actor, BackendRole
from smhai_backend.domains.school_research.client import ResearchCATClientError

from .schemas import (
    ResearchCompletionDto,
    ResearchL1SessionDto,
    ResearchQuestionDto,
    ResearchResponseOptionDto,
)


class SchoolResearchService:
    """Coordinate short persistence UOWs with stateless CAT HTTP calls."""

    def __init__(self, *, persistence: Any, clock=None) -> None:
        if persistence is None:
            raise TypeError("school research persistence must be configured")
        self.persistence = persistence
        self._clock = clock or (lambda: datetime.now(UTC))

    @staticmethod
    def _require_student(actor: Actor) -> None:
        if actor.scope_profile != "school_tenant" or actor.role is not BackendRole.STUDENT:
            raise error(ErrorCode.FORBIDDEN, detail="access denied")

    async def start_task(
        self,
        actor: Actor,
        task_ref: str,
        *,
        trace_id: str,
        idempotency: tuple[str, str, str],
    ) -> ResearchL1SessionDto:
        self._require_student(actor)
        prepared = await self.persistence.prepare_start(
            actor,
            task_ref,
            at=self._clock(),
            idempotency=idempotency,
        )
        if _is_persisted_result(prepared):
            return _metadata_projection(prepared.metadata)
        client = _plan_client(prepared)
        try:
            state = await client.start()
            committed = await self.persistence.commit_start(
                actor,
                prepared,
                state,
                at=self._clock(),
                trace_id=trace_id,
                idempotency=idempotency,
            )
            if not _state_matches_receipt(state, committed):
                return _metadata_projection(committed.metadata)
            return _state_projection(
                state,
                session_ref=committed.metadata.session_ref,
                state_version=committed.metadata.state_version,
            )
        except BackendError:
            raise
        except Exception as exc:
            raise _external_failure(exc) from None
        finally:
            await _close_client(client)

    async def resume_session(self, actor: Actor, session_ref: str) -> ResearchL1SessionDto:
        self._require_student(actor)
        plan = await self.persistence.prepare_resume(actor, session_ref, at=self._clock())
        client = _plan_client(plan)
        try:
            state = await client.resume_from_persisted(
                plan.signed_snapshot_json,
                expected_session_ref=plan.session_ref,
                expected_profile_id=plan.profile_ref,
                expected_config_version=plan.config_version,
                expected_status="ACTIVE",
                expected_items_answered=plan.items_answered,
            )
            if (
                state.session_ref != plan.session_ref
                or state.items_answered != plan.items_answered
                or state.status != "ACTIVE"
            ):
                raise _invalid_dependency_response()
            return _state_projection(
                state,
                session_ref=plan.session_ref,
                state_version=plan.state_version,
            )
        except BackendError:
            raise
        except Exception as exc:
            raise _external_failure(exc) from None
        finally:
            await _close_client(client)

    async def answer(
        self,
        actor: Actor,
        session_ref: str,
        *,
        item_id: str,
        raw_value: int,
        expected_state_version: int,
        idempotency: tuple[str, str, str],
    ) -> ResearchL1SessionDto:
        self._require_student(actor)
        prepared = await self.persistence.prepare_answer(
            actor,
            session_ref,
            expected_state_version=expected_state_version,
            at=self._clock(),
            idempotency=idempotency,
        )
        if _is_persisted_result(prepared):
            return _metadata_projection(prepared.metadata)
        client = _plan_client(prepared)
        try:
            state = await client.resume_from_persisted(
                prepared.signed_snapshot_json,
                expected_session_ref=prepared.session_ref,
                expected_profile_id=prepared.profile_ref,
                expected_config_version=prepared.config_version,
                expected_status="ACTIVE",
                expected_items_answered=prepared.items_answered,
            )
            advanced = await client.answer(state, item_id=item_id, raw_value=raw_value)
            committed = await self.persistence.commit_answer(
                actor,
                prepared,
                advanced,
                at=self._clock(),
                idempotency=idempotency,
            )
            if not _state_matches_receipt(advanced, committed):
                return _metadata_projection(committed.metadata)
            return _state_projection(
                advanced,
                session_ref=committed.metadata.session_ref,
                state_version=committed.metadata.state_version,
            )
        except BackendError:
            raise
        except Exception as exc:
            raise _external_failure(exc) from None
        finally:
            await _close_client(client)


def _is_persisted_result(value: Any) -> bool:
    from smhai_backend.adapters.school_research import ResearchSessionPersistenceResult

    return type(value) is ResearchSessionPersistenceResult


def _plan_client(plan: Any) -> Any:
    client = getattr(plan, "client", None)
    if (
        client is None
        or not callable(getattr(client, "aclose", None))
        or not callable(getattr(client, "snapshot_for_persistence", None))
    ):
        raise _invalid_dependency_response()
    return client


def _state_matches_receipt(state: Any, result: Any) -> bool:
    if not _is_persisted_result(result) or not result.persisted:
        raise _invalid_dependency_response()
    metadata = result.metadata
    storage_status = "IN_PROGRESS" if state.status == "ACTIVE" else state.status
    return (
        result.state_accepted
        and state.session_ref == metadata.session_ref
        and state.items_answered == metadata.items_answered
        and storage_status == metadata.status
    )


def _metadata_projection(metadata: Any) -> ResearchL1SessionDto:
    status = metadata.status
    return _build_projection(
        session_ref=metadata.session_ref,
        status=status,
        state_version=metadata.state_version,
        items_answered=metadata.items_answered,
        stop_reason=metadata.stop_reason,
        resume_required=status == "IN_PROGRESS",
        question=None,
        completion=(
            ResearchCompletionDto(
                status="COMPLETED",
                items_answered=metadata.items_answered,
                stop_reason=metadata.stop_reason,
            )
            if status == "COMPLETED"
            else None
        ),
    )


def _state_projection(state: Any, *, session_ref: str, state_version: int) -> ResearchL1SessionDto:
    if (
        state.research_only is not True
        or state.human_curated is not False
        or state.psychological_interpretation_allowed is not False
        or state.publication_status
        not in {"not_approved", "not_approved_for_publication_or_operational_use"}
        or type(state.items_answered) is not int
    ):
        raise _invalid_dependency_response()
    status = "IN_PROGRESS" if state.status == "ACTIVE" else state.status
    question = None
    if state.question is not None:
        question = ResearchQuestionDto(
            item_id=state.question.item_id,
            stem=state.question.stem,
            step=state.question.step,
            response_options=[
                ResearchResponseOptionDto(value=item.value, label=item.label)
                for item in state.question.response_options
            ],
        )
    completion = None
    if state.completion is not None:
        completion = ResearchCompletionDto(
            status="COMPLETED",
            items_answered=state.completion.items_answered,
            stop_reason=state.completion.stop_reason,
        )
    return _build_projection(
        session_ref=session_ref,
        status=status,
        state_version=state_version,
        items_answered=state.items_answered,
        stop_reason=(state.completion.stop_reason if state.completion else None),
        resume_required=False,
        question=question,
        completion=completion,
    )


def _build_projection(**values: Any) -> ResearchL1SessionDto:
    try:
        return ResearchL1SessionDto(research_only=True, **values)
    except ValidationError:
        raise _invalid_dependency_response() from None


async def _close_client(client: Any) -> None:
    try:
        await client.aclose()
    except Exception:
        raise error(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            detail="research CAT service is unavailable",
            retryable=True,
        ) from None


def _external_failure(exc: Exception) -> BackendError:
    if isinstance(exc, ValidationError):
        return _invalid_dependency_response()
    if isinstance(exc, ResearchCATClientError):
        if exc.code in {"dependency_unavailable", "upstream_rejected"}:
            if exc.status_code == 408:
                return error(
                    ErrorCode.DEPENDENCY_TIMEOUT,
                    detail="research CAT service timed out",
                    retryable=True,
                )
            if exc.status_code is None or exc.status_code >= 500 or exc.status_code == 429:
                return error(
                    ErrorCode.DEPENDENCY_UNAVAILABLE,
                    detail="research CAT service is unavailable",
                    retryable=True,
                )
        return _invalid_dependency_response()
    return error(
        ErrorCode.DEPENDENCY_UNAVAILABLE,
        detail="research CAT service is unavailable",
        retryable=True,
    )


def _invalid_dependency_response() -> BackendError:
    return error(
        ErrorCode.DEPENDENCY_INVALID_RESPONSE,
        detail="research CAT response is invalid",
    )
