from datetime import UTC, datetime, timedelta
from types import ModuleType, SimpleNamespace

import pytest

from smhai_backend.adapters.school_conversations import (
    SchoolConversationsPersistenceAdapter,
    _page,
    _required_key,
    _safe_component_metadata,
    _safe_evidence_projection,
    _safe_id,
    _timestamp,
)
from smhai_backend.core.errors import BackendError, ErrorCode
from smhai_backend.core.idempotency import fingerprint
from smhai_backend.domains.school_conversation_safety.contracts import SafetyCaseSeed


def test_pagination_is_bounded_and_rejects_boolean_values() -> None:
    assert _page(0, 50) == (0, 50)
    with pytest.raises(BackendError):
        _page(True, 10)
    with pytest.raises(BackendError):
        _page(0, 51)


def test_public_ids_are_prefix_checked_and_opaque() -> None:
    assert _safe_id("CONV_0123456789abcdef", "CONV") == "CONV_0123456789abcdef"
    for invalid in ("TURN_0123456789abcdef", "CONV_", "CONV_名字", "CONV_" + "x" * 128):
        with pytest.raises(BackendError):
            _safe_id(invalid, "CONV")


def test_metadata_allowlist_drops_free_text_and_sensitive_keys() -> None:
    assert _safe_component_metadata(
        {
            "generation_id": "GEN_demo_01",
            "evidence_count": 3,
            "message": "private student text",
            "prompt": "do not persist",
            "failure_code": "TURN_INTERRUPTED",
            "attempt_count": -1,
        }
    ) == {
        "generation_id": "GEN_demo_01",
        "evidence_count": 3,
        "failure_code": "TURN_INTERRUPTED",
    }


def test_dependency_error_diagnostic_allowlist_accepts_only_closed_codes() -> None:
    assert _safe_component_metadata(
        {
            "dependency_error_code": "dependency_invalid_response",
            "failure_code": "DEPENDENCY_FAILURE",
        }
    ) == {
        "dependency_error_code": "dependency_invalid_response",
        "failure_code": "DEPENDENCY_FAILURE",
    }
    assert _safe_component_metadata(
        {
            "dependency_error_code": "provider response contained private content",
            "failure_code": "DEPENDENCY_FAILURE",
        }
    ) == {"failure_code": "DEPENDENCY_FAILURE"}
    assert _safe_component_metadata({"dependency_error_code": {"message": "private"}}) == {}


def test_key_and_timestamp_helpers_normalize_without_echoing_input() -> None:
    assert _required_key("  synthetic-key  ") == "synthetic-key"
    with pytest.raises(BackendError):
        _required_key("  ")
    instant = datetime(2026, 10, 12, 3, 4, 5, tzinfo=UTC) + timedelta(milliseconds=123)
    assert _timestamp(instant) == "2026-10-12T03:04:05.123Z"


class _Expr:
    def __init__(self, clauses=()):
        self.clauses = tuple(clauses)

    def __and__(self, other):
        return _Expr((*self.clauses, *other.clauses))

    def __or__(self, other):
        return _Expr((*self.clauses, *other.clauses))


class _Column:
    def __init__(self, name):
        self.name = name

    def __eq__(self, value):
        return _Expr(((self.name, "eq", value),))

    def __le__(self, value):
        return _Expr(((self.name, "le", value),))

    def __ge__(self, value):
        return _Expr(((self.name, "ge", value),))

    def is_(self, value):
        return _Expr(((self.name, "is", value),))

    def in_(self, value):
        return _Expr(((self.name, "in", value),))

    def desc(self):
        return self


class _Query:
    def __init__(self, *selected):
        self.selected = selected
        self.criteria = []
        self.locked = False
        self.limit_value = None

    def where(self, *criteria):
        self.criteria.extend(criteria)
        return self

    def join(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def offset(self, *_args):
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def with_for_update(self):
        self.locked = True
        return self


def _model(name, *fields):
    return type(name, (), {field: _Column(f"{name}.{field}") for field in fields})


def _sqlalchemy_fake(monkeypatch):
    sqlalchemy = ModuleType("sqlalchemy")
    sqlalchemy.func = SimpleNamespace(
        max=lambda value: ("max", value),
        count=lambda value: ("count", value),
    )
    monkeypatch.setitem(__import__("sys").modules, "sqlalchemy", sqlalchemy)


def _enums():
    def values(**items):
        return SimpleNamespace(
            **{key: SimpleNamespace(value=value) for key, value in items.items()}
        )

    return SimpleNamespace(
        AuditResult=values(SUCCESS="SUCCESS"),
        SubjectStatus=values(ACTIVE="ACTIVE"),
        DataOrigin=values(SYNTHETIC="SYNTHETIC"),
        SupportStatus=values(OPEN="OPEN", ACTIVE="ACTIVE"),
        SupportRunStatus=values(
            REQUESTED="REQUESTED", COMPLETED="COMPLETED", BLOCKED="BLOCKED", FAILED="FAILED"
        ),
        MessageKind=values(USER_INPUT="USER_INPUT", APPROVED_OUTPUT="APPROVED_OUTPUT"),
        SafetyAction=(
            SimpleNamespace(value="PROCEED"),
            SimpleNamespace(value="PROCEED_WITH_BOUNDARY"),
            SimpleNamespace(value="BLOCK"),
            SimpleNamespace(value="REVIEW_REQUIRED"),
            SimpleNamespace(value="CRISIS_ROUTE"),
        ),
    )


class _FakeSession:
    def __init__(self, *scalar_results):
        self.scalar_results = list(scalar_results)
        self.statements = []
        self.scalars_results = []

    def add_scalars(self, rows):
        self.scalars_results.append(list(rows))

    async def scalars(self, statement):
        self.statements.append(statement)
        if not self.scalars_results:
            raise AssertionError("unexpected scalars query")
        rows = self.scalars_results.pop(0)
        return SimpleNamespace(all=lambda: rows)

    async def scalar(self, statement):
        self.statements.append(statement)
        if not self.scalar_results:
            raise AssertionError("unexpected scalar query")
        return self.scalar_results.pop(0)


class _FakeSupport:
    def __init__(self):
        self.run_calls = []
        self.message_calls = []
        self.evidence_calls = []
        self.session_calls = []
        self.created_sessions = []
        self.safety_decision_calls = []

    async def create_session(self, **kwargs):
        self.session_calls.append(kwargs)
        row = SimpleNamespace(
            support_ref=kwargs["support_ref"],
            status="OPEN",
            created_at=NOW,
            updated_at=NOW,
        )
        self.created_sessions.append(row)
        return row

    async def create_run(self, **kwargs):
        self.run_calls.append(kwargs)
        return SimpleNamespace(
            id=901,
            run_ref=kwargs["run_ref"],
            status=kwargs["status"].value,
            workflow_action=kwargs["workflow_action"],
            component_versions=kwargs["component_versions"],
            started_at=None,
            created_at=NOW,
        )

    async def persist_message(self, **kwargs):
        self.message_calls.append(kwargs)
        return SimpleNamespace(id=902)

    async def add_evidence(self, **kwargs):
        self.evidence_calls.append(kwargs)
        return SimpleNamespace(id=903)

    async def create_safety_decision(self, **kwargs):
        self.safety_decision_calls.append(kwargs)
        return SimpleNamespace(id=904)


class _FakeConversationSafety:
    def __init__(self):
        self.created = []

    async def create_from_safety_decision(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(case_ref="SCS_synthetic_1", status="UNASSIGNED_PENDING")


class _FakeUow:
    def __init__(self, session):
        self.session = session
        self.support = _FakeSupport()
        self.conversation_safety = _FakeConversationSafety()
        self.audit = SimpleNamespace(append=self._audit)
        self.audit_calls = []
        self.entered = False
        self.committed = False
        self.rolled_back = False

    async def _audit(self, **kwargs):
        self.audit_calls.append(kwargs)

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, exc_type, _exc, _traceback):
        self.committed = exc_type is None
        self.rolled_back = exc_type is not None
        return False


async def _async_value(value):
    return value


NOW = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)
ACTOR = SimpleNamespace(
    role="student", subject_id="SUBJ_SYNTHETIC_A", school_id=5, school_ref="SCHOOL_SYNTHETIC"
)
SUBJECT = SimpleNamespace(id=71, subject_ref="SUBJ_SYNTHETIC_A", retention_due_at=None)
SESSION = SimpleNamespace(
    id=81,
    support_ref="CONV_0123456789abcdef",
    status="OPEN",
    retention_due_at=None,
    trace_id=None,
)


def _fake_adapter(monkeypatch, session, *, target_role="student"):
    _sqlalchemy_fake(monkeypatch)
    models = SimpleNamespace(
        SupportRun=_model(
            "support_runs",
            "id",
            "run_ref",
            "support_session_id",
            "assessment_session_id",
            "status",
            "created_at",
        ),
        SupportMessage=_model(
            "support_messages", "support_session_id", "sequence_no", "message_kind"
        ),
        SupportEvidence=_model("support_evidence", "support_run_id", "rank_order"),
    )
    persistence = SimpleNamespace(
        _decrypt_support_message=lambda _row: (_ for _ in ()).throw(
            AssertionError("message decrypt was not expected")
        )
    )
    adapter = SchoolConversationsPersistenceAdapter(persistence, target_role=target_role)
    adapter._db_models = models
    adapter._db_enums = _enums()
    adapter._select = _Query
    adapter._uow = lambda: uow
    adapter._utc_now = lambda: NOW
    uow = _FakeUow(session)

    async def student_subject(_uow, _actor, _now):
        return 17, SUBJECT

    async def owned_session(_uow, actor, subject, conversation_id, *, lock):
        assert actor is ACTOR
        assert subject is SUBJECT
        assert conversation_id == SESSION.support_ref
        assert lock is True
        return SESSION

    adapter._student_subject = student_subject
    adapter._owned_session = owned_session
    return adapter, uow


@pytest.mark.asyncio
async def test_create_uses_explicit_research_storage_role(monkeypatch):
    session = _FakeSession(None)
    adapter, uow = _fake_adapter(monkeypatch, session, target_role="student_research")
    claims = []

    async def claim(_uow, value):
        claims.append(value)
        return SimpleNamespace(replayed=False, record=SimpleNamespace())

    async def complete(_uow, claim_value, *, resource_type, result_ref):
        return None

    adapter._school_idempotency_begin = claim
    adapter._school_idempotency_complete = complete

    async def owned(_uow, _actor, _subject, conversation_id, *, lock):
        assert conversation_id.startswith("CONV_")
        assert lock is False
        return uow.support.created_sessions[0]

    adapter._owned_session = owned
    result = await adapter.create(ACTOR, idempotency_key="research-create", trace_id="TRACE_test")

    assert result["conversation_id"].startswith("CONV_")
    assert uow.support.session_calls[0]["target_role"] == "student_research"
    assert uow.committed is True


@pytest.mark.asyncio
async def test_reserve_turn_persists_requested_run_encrypted_message_and_scoped_receipt(
    monkeypatch,
):
    session = _FakeSession(None, 4)
    adapter, uow = _fake_adapter(monkeypatch, session)
    claims = []
    completed = []

    async def claim(_uow, value):
        claims.append(value)
        return SimpleNamespace(replayed=False, record=SimpleNamespace())

    async def complete(_uow, claim_value, *, resource_type, result_ref):
        completed.append((claim_value, resource_type, result_ref))

    async def no_abandoned(_uow, _session, _now):
        return 0

    adapter._school_idempotency_begin = claim
    adapter._school_idempotency_complete = complete
    adapter._expire_abandoned = no_abandoned

    result = await adapter.reserve_turn(
        ACTOR,
        SESSION.support_ref,
        message="synthetic student message",
        idempotency_key="synthetic-turn-key",
        trace_id="TRACE_synthetic",
    )

    assert result["status"] == "requested"
    assert result["user_message_sequence"] == 5
    assert claims[0][0] == "synthetic-turn-key"
    assert claims[0][1] == fingerprint(
        {
            "operation": "conversation.reserve_turn",
            "conversation_id": SESSION.support_ref,
            "message": "synthetic student message",
        }
    )
    assert claims[0][2] == "17:student:conversation:turn:5:CONV_0123456789abcdef"
    assert uow.support.run_calls[0]["assessment_session_id"] is None
    assert uow.support.run_calls[0]["component_versions"]["user_message_sequence"] == 5
    assert uow.support.message_calls[0]["message_kind"].value == "USER_INPUT"
    assert uow.support.message_calls[0]["payload"]["text"] == "synthetic student message"
    assert completed[0][1] == "student_conversation_turn"
    assert completed[0][2] == result["turn_id"]
    assert uow.committed is True
    assert all("count" in row["safe_metadata"] for row in uow.audit_calls)


@pytest.mark.asyncio
async def test_finish_turn_blocked_is_terminal_without_persisting_candidate(monkeypatch):
    run = SimpleNamespace(
        id=901,
        run_ref="TURN_0123456789abcdef",
        support_session_id=SESSION.id,
        assessment_session_id=None,
        status="REQUESTED",
        workflow_action="REQUESTED",
        component_versions={"user_message_sequence": 1, "safe_metadata": {}},
        started_at=NOW,
        created_at=NOW,
        completed_at=None,
        duration_ms=None,
    )
    session = _FakeSession(run)
    adapter, uow = _fake_adapter(monkeypatch, session)

    result = await adapter.finish_turn(
        ACTOR,
        SESSION.support_ref,
        run.run_ref,
        status="BLOCKED",
        action="BLOCK",
        trace_id="TRACE_synthetic",
    )

    assert result["status"] == "blocked"
    assert run.status == "BLOCKED"
    assert run.workflow_action == "BLOCK"
    assert uow.support.message_calls == []
    assert uow.support.evidence_calls == []
    assert uow.committed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_action",
    ("DEPENDENCY_FAILURE", "INVALID_OUTPUT", "CLAIM_REJECTED", "INTERRUPTED"),
)
async def test_finish_turn_failure_actions_are_terminal_without_output(monkeypatch, failure_action):
    run = SimpleNamespace(
        id=901,
        run_ref="TURN_0123456789abcdef",
        support_session_id=SESSION.id,
        assessment_session_id=None,
        status="REQUESTED",
        workflow_action="REQUESTED",
        component_versions={"user_message_sequence": 1, "safe_metadata": {}},
        started_at=NOW,
        created_at=NOW,
        completed_at=None,
        duration_ms=None,
    )
    session = _FakeSession(run)
    adapter, uow = _fake_adapter(monkeypatch, session)

    result = await adapter.finish_turn(
        ACTOR,
        SESSION.support_ref,
        run.run_ref,
        status="FAILED",
        action=failure_action,
        safe_metadata={"failure_code": failure_action},
        trace_id="TRACE_synthetic",
    )

    assert result["status"] == "failed"
    assert result["action"] == failure_action
    assert run.status == "FAILED"
    assert run.workflow_action == failure_action
    assert uow.support.message_calls == []
    assert uow.support.evidence_calls == []
    assert uow.committed is True


@pytest.mark.asyncio
async def test_failed_proceed_candidate_is_rejected_before_any_persistence(monkeypatch):
    session = _FakeSession()
    adapter, uow = _fake_adapter(monkeypatch, session)

    with pytest.raises(BackendError) as caught:
        await adapter.finish_turn(
            ACTOR,
            SESSION.support_ref,
            "TURN_0123456789abcdef",
            status="FAILED",
            action="PROCEED",
            approved_content={"summary": "synthetic rejected candidate"},
            trace_id="TRACE_synthetic",
        )

    assert caught.value.code is ErrorCode.VALIDATION_FAILED
    assert uow.entered is False
    assert uow.support.message_calls == []
    assert uow.support.evidence_calls == []


@pytest.mark.asyncio
async def test_abstention_requires_approved_content_and_rejects_citations(monkeypatch):
    session = _FakeSession()
    adapter, uow = _fake_adapter(monkeypatch, session)

    with pytest.raises(BackendError) as caught:
        await adapter.finish_turn(
            ACTOR,
            SESSION.support_ref,
            "TURN_0123456789abcdef",
            status="COMPLETED",
            action="ABSTAIN",
            approved_content={"summary": "合成说明"},
            citations=({"citation_id": "CITE_SYNTHETIC"},),
            trace_id="TRACE_synthetic",
        )

    assert caught.value.code is ErrorCode.VALIDATION_FAILED
    assert uow.entered is False
    assert uow.support.message_calls == []


@pytest.mark.asyncio
async def test_abstention_persists_approved_content_without_citations(monkeypatch):
    run = SimpleNamespace(
        id=901,
        run_ref="TURN_0123456789abcdef",
        support_session_id=SESSION.id,
        assessment_session_id=None,
        status="REQUESTED",
        workflow_action="REQUESTED",
        component_versions={"user_message_sequence": 1, "safe_metadata": {}},
        started_at=NOW,
        created_at=NOW,
        completed_at=None,
        duration_ms=None,
    )
    session = _FakeSession(run, 1)
    adapter, uow = _fake_adapter(monkeypatch, session)

    result = await adapter.finish_turn(
        ACTOR,
        SESSION.support_ref,
        run.run_ref,
        status="COMPLETED",
        action="ABSTAIN",
        approved_content={"summary": "合成证据不足说明"},
        citations=(),
        trace_id="TRACE_synthetic",
    )

    assert result["action"] == "ABSTAIN"
    assert result["assistant_message_sequence"] == 2
    assert run.status == "COMPLETED"
    assert run.workflow_action == "ABSTAIN"
    assert uow.support.message_calls[0]["payload"]["content"] == {"summary": "合成证据不足说明"}
    assert uow.support.evidence_calls == []


@pytest.mark.asyncio
async def test_blocked_crisis_route_keeps_approved_response_path(monkeypatch):
    run = SimpleNamespace(
        id=901,
        run_ref="TURN_0123456789abcdef",
        support_session_id=SESSION.id,
        assessment_session_id=None,
        status="REQUESTED",
        workflow_action="REQUESTED",
        component_versions={"user_message_sequence": 1, "safe_metadata": {}},
        started_at=NOW,
        created_at=NOW,
        completed_at=None,
        duration_ms=None,
    )
    session = _FakeSession(run, 1)
    adapter, uow = _fake_adapter(monkeypatch, session)

    async def current_student_role(_uow, _actor, _role, _now):
        return 17, 19

    adapter._school_actor_role = current_student_role

    result = await adapter.finish_turn(
        ACTOR,
        SESSION.support_ref,
        run.run_ref,
        status="BLOCKED",
        action="CRISIS_ROUTE",
        approved_content={"summary": "approved synthetic safety response"},
        citations=(),
        safety_case=SafetyCaseSeed(
            action="CRISIS_ROUTE",
            reason_codes=("SYNTHETIC_TEST_CODE",),
            review_reference=None,
        ),
        trace_id="TRACE_synthetic",
    )

    assert result["status"] == "blocked"
    assert result["action"] == "CRISIS_ROUTE"
    assert run.status == "BLOCKED"
    assert uow.support.message_calls[0]["payload"]["content"] == {
        "summary": "approved synthetic safety response"
    }
    assert uow.support.evidence_calls == []
    assert uow.support.safety_decision_calls[0]["policy_version"] == (
        "safety-port-unversioned.v1"
    )
    assert uow.conversation_safety.created[0]["reason_codes"] == (
        "SYNTHETIC_TEST_CODE",
    )
    assert uow.conversation_safety.created[0]["safety_review_reference"] is None


@pytest.mark.asyncio
async def test_cross_owner_detail_denial_happens_before_any_decryption(monkeypatch):
    session = _FakeSession()
    adapter, uow = _fake_adapter(monkeypatch, session)

    async def deny_owner(*_args, **_kwargs):
        from smhai_backend.core.errors import error

        raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="conversation was not found")

    adapter._owned_session = deny_owner
    with pytest.raises(BackendError) as caught:
        await adapter.detail(ACTOR, SESSION.support_ref, offset=0, limit=10)

    assert caught.value.code is ErrorCode.RESOURCE_NOT_FOUND
    assert session.statements == []
    assert uow.committed is False
    assert uow.rolled_back is True


@pytest.mark.asyncio
async def test_create_replay_rejects_wrong_receipt_type_before_resource_lookup(monkeypatch):
    session = _FakeSession()
    adapter, uow = _fake_adapter(monkeypatch, session)
    claims = []

    async def replay(_uow, value):
        claims.append(value)
        return SimpleNamespace(
            replayed=True,
            record=SimpleNamespace(
                result_resource_type="student_conversation_turn",
                result_public_id="TURN_0123456789abcdef",
            ),
        )

    adapter._school_idempotency_begin = replay

    with pytest.raises(BackendError) as caught:
        await adapter.create(ACTOR, idempotency_key="synthetic-create-key", trace_id="TRACE_x")

    assert caught.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert claims[0][2] == "17:student:conversation:create:5"
    assert session.statements == []
    assert uow.support.run_calls == []


@pytest.mark.asyncio
async def test_turn_replay_receipt_lookup_is_bound_to_same_session_and_unbound_assessment(
    monkeypatch,
):
    run = SimpleNamespace(
        id=901,
        run_ref="TURN_0123456789abcdef",
        support_session_id=SESSION.id,
        assessment_session_id=None,
        status="REQUESTED",
        component_versions={"user_message_sequence": 7},
    )
    session = _FakeSession(run)
    adapter, uow = _fake_adapter(monkeypatch, session)
    receipt_record = SimpleNamespace(
        result_resource_type="student_conversation_turn",
        result_public_id=run.run_ref,
    )
    claims = []

    async def replay(_uow, value):
        claims.append(value)
        return SimpleNamespace(replayed=True, record=receipt_record)

    async def no_abandoned(_uow, _session, _now):
        return 0

    adapter._school_idempotency_begin = replay
    adapter._expire_abandoned = no_abandoned

    result = await adapter.reserve_turn(
        ACTOR,
        SESSION.support_ref,
        message="synthetic student message",
        idempotency_key="synthetic-turn-key",
        trace_id="TRACE_synthetic",
    )

    assert result == {
        "turn_id": run.run_ref,
        "status": "requested",
        "replayed": True,
        "user_message_sequence": 7,
        "action": None,
        "completed_at": None,
        "assistant_message_sequence": None,
        "citations": [],
        "safe_metadata": {},
        "content": None,
    }
    assert claims[0][2] == "17:student:conversation:turn:5:CONV_0123456789abcdef"
    criteria = session.statements[0].criteria
    flattened = [clause for criterion in criteria for clause in criterion.clauses]
    assert ("support_runs.support_session_id", "eq", SESSION.id) in flattened
    assert ("support_runs.assessment_session_id", "is", None) in flattened
    assert uow.support.message_calls == []


@pytest.mark.asyncio
async def test_failed_turn_replay_returns_terminal_projection_without_output(monkeypatch):
    run = SimpleNamespace(
        id=901,
        run_ref="TURN_0123456789abcdef",
        support_session_id=SESSION.id,
        assessment_session_id=None,
        status="FAILED",
        workflow_action="DEPENDENCY_FAILURE",
        completed_at=NOW,
        component_versions={
            "user_message_sequence": 7,
            "assistant_message_sequence": None,
            "safe_metadata": {"failure_code": "DEPENDENCY_FAILURE"},
        },
    )
    session = _FakeSession(run)
    session.add_scalars([])  # No stored citations on failed turns.
    adapter, uow = _fake_adapter(monkeypatch, session)
    adapter._school_idempotency_begin = lambda *_args: _async_value(
        SimpleNamespace(
            replayed=True,
            record=SimpleNamespace(
                result_resource_type="student_conversation_turn",
                result_public_id=run.run_ref,
            ),
        )
    )
    adapter._expire_abandoned = lambda *_args: _async_value(0)

    result = await adapter.reserve_turn(
        ACTOR,
        SESSION.support_ref,
        message="synthetic student message",
        idempotency_key="synthetic-turn-key",
        trace_id="TRACE_replay",
    )

    assert result == {
        "turn_id": run.run_ref,
        "status": "failed",
        "replayed": True,
        "user_message_sequence": 7,
        "action": "DEPENDENCY_FAILURE",
        "completed_at": "2026-10-12T00:00:00.000Z",
        "assistant_message_sequence": None,
        "citations": [],
        "safe_metadata": {"failure_code": "DEPENDENCY_FAILURE"},
        "content": None,
    }
    assert uow.support.message_calls == []
    assert uow.support.evidence_calls == []
    assert uow.committed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "action"),
    (("COMPLETED", "PROCEED"), ("BLOCKED", "CRISIS_ROUTE")),
)
async def test_approved_and_crisis_turn_replay_returns_validated_content_and_citations(
    monkeypatch, status, action
):
    content = (
        {"kind": "approved_safety_response", "text": "合成的已审核安全提示。"}
        if action == "CRISIS_ROUTE"
        else {
            "summary": "合成的已批准教育支持说明",
            "observations": [],
            "suggestions": [],
            "disclaimer": "这不是诊断或治疗建议。",
        }
    )
    run = SimpleNamespace(
        id=901,
        run_ref="TURN_0123456789abcdef",
        support_session_id=SESSION.id,
        assessment_session_id=None,
        status=status,
        workflow_action=action,
        completed_at=NOW,
        component_versions={
            "user_message_sequence": 7,
            "assistant_message_sequence": 8,
            "safe_metadata": {"output_safety_action": "PROCEED"},
        },
    )
    evidence = SimpleNamespace(
        support_run_id=run.id,
        citation_id="CITE_synthetic_1",
        source_id="DOC_synthetic_1",
        chunk_id="CHUNK_synthetic_1",
        document_id="DOC_synthetic_1",
        source_version="v1",
        source_hash="HASH_synthetic_1",
        citation_title="合成教育资料",
        citation_organization="合成组织",
        locator="第 1 页",
        rank_order=1,
    )
    message = SimpleNamespace(
        sequence_no=8,
        message_kind="APPROVED_OUTPUT",
    )
    session = _FakeSession(run)
    session.add_scalars([evidence] if status == "COMPLETED" else [])
    session.add_scalars([message])
    adapter, uow = _fake_adapter(monkeypatch, session)
    decrypted = []

    def decrypt(row):
        decrypted.append(row)
        return {
            "schema_version": "independent-message.v1",
            "turn_id": run.run_ref,
            "content": content,
        }

    adapter._persistence._decrypt_support_message = decrypt
    adapter._school_idempotency_begin = lambda *_args: _async_value(
        SimpleNamespace(
            replayed=True,
            record=SimpleNamespace(
                result_resource_type="student_conversation_turn",
                result_public_id=run.run_ref,
            ),
        )
    )
    adapter._expire_abandoned = lambda *_args: _async_value(0)

    result = await adapter.reserve_turn(
        ACTOR,
        SESSION.support_ref,
        message="synthetic student message",
        idempotency_key="synthetic-turn-key",
        trace_id="TRACE_replay",
    )

    assert result["status"] == status.lower()
    assert result["action"] == action
    assert result["completed_at"] == "2026-10-12T00:00:00.000Z"
    assert result["user_message_sequence"] == 7
    assert result["assistant_message_sequence"] == 8
    assert result["content"] == content
    assert result["citations"] == (
        [
            {
                "citation_id": "CITE_synthetic_1",
                "source_id": "DOC_synthetic_1",
                "chunk_id": "CHUNK_synthetic_1",
                "document_id": "DOC_synthetic_1",
                "title": "合成教育资料",
                "organization": "合成组织",
                "locator": "第 1 页",
                "source_version": "v1",
                "source_hash": "HASH_synthetic_1",
                "rank": 1,
            }
        ]
        if status == "COMPLETED"
        else []
    )
    assert decrypted == [message]
    assert uow.support.message_calls == []
    assert uow.support.evidence_calls == []
    assert uow.committed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message_kind", "payload"),
    (
        (
            "USER_INPUT",
            {
                "schema_version": "independent-message.v1",
                "turn_id": "TURN_0123456789abcdef",
                "content": {"summary": "must not be returned"},
            },
        ),
        (
            "APPROVED_OUTPUT",
            {
                "schema_version": "independent-message.v1",
                "turn_id": "TURN_other",
                "content": {"summary": "must not be returned"},
            },
        ),
        (
            "APPROVED_OUTPUT",
            {
                "schema_version": "wrong.v1",
                "turn_id": "TURN_0123456789abcdef",
                "content": {"summary": "must not be returned"},
            },
        ),
        (
            "APPROVED_OUTPUT",
            {
                "schema_version": "independent-message.v1",
                "turn_id": "TURN_0123456789abcdef",
                "content": {"summary": "incomplete schema"},
            },
        ),
    ),
)
async def test_terminal_replay_fails_closed_on_malformed_approved_message(
    monkeypatch, message_kind, payload
):
    run = SimpleNamespace(
        id=901,
        run_ref="TURN_0123456789abcdef",
        support_session_id=SESSION.id,
        assessment_session_id=None,
        status="COMPLETED",
        workflow_action="PROCEED",
        completed_at=NOW,
        component_versions={"user_message_sequence": 7, "assistant_message_sequence": 8},
    )
    session = _FakeSession(run)
    session.add_scalars([])
    session.add_scalars([SimpleNamespace(sequence_no=8, message_kind=message_kind)])
    adapter, uow = _fake_adapter(monkeypatch, session)
    adapter._persistence._decrypt_support_message = lambda _row: payload
    adapter._school_idempotency_begin = lambda *_args: _async_value(
        SimpleNamespace(
            replayed=True,
            record=SimpleNamespace(
                result_resource_type="student_conversation_turn",
                result_public_id=run.run_ref,
            ),
        )
    )
    adapter._expire_abandoned = lambda *_args: _async_value(0)

    with pytest.raises(BackendError) as caught:
        await adapter.reserve_turn(
            ACTOR,
            SESSION.support_ref,
            message="synthetic student message",
            idempotency_key="synthetic-turn-key",
            trace_id="TRACE_replay",
        )

    assert caught.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert uow.committed is False
    assert uow.rolled_back is True
    assert uow.support.message_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "crisis_content",
    (
        {"kind": "wrong_kind", "text": "synthetic approved text"},
        {"kind": "approved_safety_response", "text": None},
        {"kind": "approved_safety_response", "text": "  "},
        {"kind": "approved_safety_response", "text": "x" * 20_001},
        {"kind": "approved_safety_response", "text": "synthetic approved text", "extra": "no"},
    ),
)
async def test_crisis_replay_fails_closed_on_malformed_approved_safety_content(
    monkeypatch, crisis_content
):
    run = SimpleNamespace(
        id=901,
        run_ref="TURN_0123456789abcdef",
        support_session_id=SESSION.id,
        assessment_session_id=None,
        status="BLOCKED",
        workflow_action="CRISIS_ROUTE",
        completed_at=NOW,
        component_versions={"user_message_sequence": 7, "assistant_message_sequence": 8},
    )
    session = _FakeSession(run)
    session.add_scalars([])
    session.add_scalars([SimpleNamespace(sequence_no=8, message_kind="APPROVED_OUTPUT")])
    adapter, uow = _fake_adapter(monkeypatch, session)
    adapter._persistence._decrypt_support_message = lambda _row: {
        "schema_version": "independent-message.v1",
        "turn_id": run.run_ref,
        "content": crisis_content,
    }
    adapter._school_idempotency_begin = lambda *_args: _async_value(
        SimpleNamespace(
            replayed=True,
            record=SimpleNamespace(
                result_resource_type="student_conversation_turn",
                result_public_id=run.run_ref,
            ),
        )
    )
    adapter._expire_abandoned = lambda *_args: _async_value(0)

    with pytest.raises(BackendError) as caught:
        await adapter.reserve_turn(
            ACTOR,
            SESSION.support_ref,
            message="synthetic student message",
            idempotency_key="synthetic-turn-key",
            trace_id="TRACE_replay",
        )

    assert caught.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert uow.rolled_back is True
    assert uow.support.message_calls == []


@pytest.mark.asyncio
async def test_non_crisis_blocked_replay_rejects_proceed_action(monkeypatch):
    run = SimpleNamespace(
        id=901,
        run_ref="TURN_0123456789abcdef",
        support_session_id=SESSION.id,
        assessment_session_id=None,
        status="BLOCKED",
        workflow_action="PROCEED",
        completed_at=NOW,
        component_versions={"user_message_sequence": 7, "assistant_message_sequence": None},
    )
    session = _FakeSession(run)
    adapter, uow = _fake_adapter(monkeypatch, session)
    adapter._school_idempotency_begin = lambda *_args: _async_value(
        SimpleNamespace(
            replayed=True,
            record=SimpleNamespace(
                result_resource_type="student_conversation_turn",
                result_public_id=run.run_ref,
            ),
        )
    )
    adapter._expire_abandoned = lambda *_args: _async_value(0)

    with pytest.raises(BackendError) as caught:
        await adapter.reserve_turn(
            ACTOR,
            SESSION.support_ref,
            message="synthetic student message",
            idempotency_key="synthetic-turn-key",
            trace_id="TRACE_replay",
        )

    assert caught.value.code is ErrorCode.WORKFLOW_CONFLICT
    assert session.scalars_results == []
    assert uow.rolled_back is True
    assert uow.support.message_calls == []


def test_citation_fields_enforce_each_persisted_column_length():
    adapter = SchoolConversationsPersistenceAdapter(SimpleNamespace())
    valid = {
        "citation_id": "C" * 128,
        "document_id": "D" * 128,
        "chunk_id": "K" * 128,
        "source_version": "V" * 64,
        "source_hash": "H" * 128,
        "title": "T" * 512,
        "organization": "O" * 512,
        "locator": "L" * 512,
    }
    evidence = adapter._persist_evidence(None, None, [valid])[0]
    assert evidence["document_id"] == "D" * 128

    for field, too_long in (
        ("citation_id", "C" * 129),
        ("document_id", "D" * 129),
        ("chunk_id", "K" * 129),
        ("source_version", "V" * 65),
        ("source_hash", "H" * 129),
        ("title", "T" * 513),
        ("organization", "O" * 513),
        ("locator", "L" * 513),
    ):
        with pytest.raises(BackendError) as caught:
            adapter._persist_evidence(None, None, [{**valid, field: too_long}])
        assert caught.value.code is ErrorCode.VALIDATION_FAILED


def test_detail_projection_drops_malformed_stored_citation_instead_of_returning_it():
    row = SimpleNamespace(
        citation_id="CITE_1",
        source_id="DOC_1",
        chunk_id="CHUNK_1",
        document_id="D" * 129,
        source_version="V" * 65,
        source_hash="a" * 64,
        citation_title="synthetic title",
        citation_organization="synthetic org",
        locator="p.1",
        rank_order=1,
    )
    assert _safe_evidence_projection(row) is None
