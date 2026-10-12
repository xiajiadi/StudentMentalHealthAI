# Independent synthetic education-support conversations

Controller implementation direction, 2026-10-12. This is a module-local engineering design, not psychological feedback approval or a change to frozen contracts.

## Outcome

A school student can open education support before starting CAT, submit a message, receive a safely grounded answer or an explicit abstention, continue the conversation and recover its encrypted history after restart. No fabricated assessment is created. Existing assessment-bound support remains separate.

## API and ownership

- New module-local routes: POST/GET `/api/v1/student/conversations`; POST `/api/v1/student/conversations/{conversation_id}/messages`; GET `/api/v1/student/conversations/{conversation_id}`.
- Create establishes an empty conversation. Message submission is a separate durable turn resource. Both writes require authenticated active STUDENT context, CSRF and an idempotency key; message submission additionally uses the support rate limit.
- Server derives school, membership, account and subject from the active context. Payloads cannot select a role, owner, model, prompt, retrieval or citation identity. Unknown fields are rejected.
- Query and mutation require the same school and student subject. Teachers, administrators and specialists cannot read private conversation content. Cross-owner access returns the established resource-not-found response; nonstudent role returns forbidden.
- Lists expose identifiers, created/updated timestamps and lifecycle status, not decrypted message summaries. Detail returns bounded ordered messages, safe per-turn status and validated citations after authorization.

## Orchestration

Use a dedicated orchestration path with no AssessmentStore lookup, assessment binding, D3 measurement interpretation or report lookup. Add a module-local independent Runtime request/domain type and endpoint, with real conversation/turn/retrieval identifiers and no assessment field. Reuse provider generation and tracing through an explicit compatible request interface; do not serialize this request as frozen generation.v1 or create a placeholder assessment identity. The existing frozen assessment-bound request remains unchanged.

Input Safety receives the student message with no measurement signals. Crisis, block and human-review routes bypass ordinary RAG/LLM. Crisis is an explicitly safe response, not a normal generated answer. Ordinary retrieval accepts server-owned student/population scope and the message; it must not invent a theta, risk band or measurement result to fit an old RAG DTO. Add a module-local independent retrieval endpoint and plan with assessment_id=None, risk_level=None and empty risk filters. Preserve validation of the existing assessment-bound plan's four risk values; unknown risk is valid only in the explicitly independent path. Verify available corpus population/license eligibility before offering a grounded university-student answer; no matching eligible evidence means abstention.

Zero eligible evidence produces abstention without a model call. Retrieved evidence passes Retrieval Safety; approved evidence alone enters the prompt. The prompt is specific to independent education support and makes no assessment or diagnostic claim. Model identity and output budget are server-owned. One provider attempt, no model/cloud fallback or JSON repair.

Validate native structured output, Output Safety, the existing Backend Claim Boundary and evidence-bound citations before publishing an assistant message. Persist safe stage/error metadata on failure; never persist a rejected candidate. An earlier failed turn is not automatically regenerated on restart or idempotency replay.

## Storage and recovery

Reuse nullable-assessment support sessions/runs and encrypted support messages where their actual schema allows it. Add explicit independent repository operations rather than adapting assessment-bound `begin_workflow`/`complete_workflow` by passing null into code that dereferences assessments.

Serialize writes per conversation in the database, allocate monotonically increasing message sequence numbers and persist a stable turn resource/receipt. Input and turn reservation commit before network calls; accepted output/evidence and terminal status commit together. No long database transaction across model inference. A crash leaves an observable interrupted/in-progress turn requiring explicit reconciliation, not hidden resubmission. Replaying a key restores the original turn resource after a process restart; different content with the same key is rejected. Never expose a turn from another school/subject through its receipt.

Professional feedback sharing is unavailable until a separately verified publication entity exists. Default conversation does not read raw answers, unpublished reports or review text. A future opt-in must reference an authorized published version and be explicitly chosen by the student.

## Evidence needed

- Real native database: no-CAT creation, encrypted multi-turn persistence, same-key replay after backend restart, cross-student/school denial and concurrent sequence reservation.
- Real local AI: normal cited answer, no-evidence abstention, blocked input, crisis bypass, output/claim rejection with no candidate persistence, exact model/digest and one-attempt trace.
- Browser: student opens support without CAT, sends/continues, sees citations and failure state, reloads history; teacher/admin access denied by Backend.
- Preserve frozen Contract/Safety/research evidence and existing assessment-bound behavior. A mock-only or health-endpoint result cannot establish this outcome.
