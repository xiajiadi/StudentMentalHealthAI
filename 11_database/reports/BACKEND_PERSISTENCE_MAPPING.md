# Backend Persistence Mapping

Inspection date: 2026-09-05. `09_backend` currently contains only `TASK.md`;
there are no Python Protocols, method signatures, Repository implementations,
UnitOfWork ports, SessionStore, IdempotencyStore, AuditRepository,
AssessmentRepository, or ReviewProjectionRepository to import. This report
therefore records structural compatibility candidates without claiming a real
cross-module integration.

| Backend port / expected responsibility | Database implementation | Method mapping | Transaction behavior | Status | Blocking discrepancy |
| --- | --- | --- | --- | --- | --- |
| AssessmentRepository | `AssessmentRepository` | `create_session`, `append_response`, `save_result`, `get_session` | Caller opens `SqlAlchemyUnitOfWork`; repository flushes only | MAPPED | Exact Backend Protocol does not exist yet |
| SessionStore | `AuthSessionStore` | `create`, `find_by_token`, `revoke` | Same UnitOfWork; raw token is hashed before SQL | MAPPED | Backend cookie/session semantics are not frozen |
| IdempotencyStore | `IdempotencyStore` | `claim`, `complete` | Unique `(scope, key_hash)` plus nested savepoint; UnitOfWork commits | MAPPED | Exact result replay envelope is a Backend decision |
| AuditRepository | `AuditRepository` | `append` | Append and commit at use-case boundary; allowlisted metadata | MAPPED | Backend actor/resource vocabulary is not defined |
| ReviewProjectionRepository | `ReviewRepository` | `create_case`, `update_case`, `add_event` | Optimistic `version` predicate; stale update raises conflict | MAPPED | Review projection/query methods and transition rules are absent |
| Support/conversation repository | `SupportRepository` | session/run/message/evidence/safety decision methods | One transaction can persist a complete workflow slice | MAPPED | API generation/report persistence shape is not yet a port |
| Knowledge document/chunk repository | Not implemented in Round 1 | `support_evidence` stores source/citation references only | RAG owns corpus; DB stores provenance references | DEFERRED | Duplicating the corpus would violate the database boundary |
| Generation/report repository | `SupportRepository` plus support run references | `generation_ref`, `retrieval_ref`, and safe output message | No unsafe candidate persistence | DEFERRED | No Backend report/generation port or report table contract |
| UnitOfWork | `SqlAlchemyUnitOfWork` | `__aenter__`, `commit`, `rollback`, `__aexit__` | Owns session lifetime and transaction; no global session | MAPPED | Backend composition root is not implemented |

## Integration rules

1. Backend must define Protocols/DTOs in `09_backend` before a runtime adapter
   is wired. The Database module must not modify them unilaterally.
2. Backend maps frozen Contract IDs such as `SUBJ_*`, `ASSESS_*`, `GEN_*`, and
   `REPORT_*` to database UUID4 public IDs and internal foreign keys. The
   opaque contract reference is stored where provenance requires it.
3. Backend owns authorization, role scope, safety interpretation, state-machine
   decisions, and HTTP error envelopes. Database repositories only enforce
   persistence integrity and concurrency.
4. A later integration gate must test one synthetic assessment -> support run
   -> safety decision -> review chain through the actual Backend ports.
