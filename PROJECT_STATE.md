# Project State

Current objective: complete Stage 0 and Contract/API Hardening Round 1 as a
candidate-only change, preserving the frozen v0.1.0 root contracts.

Current phase: Candidate hardening evidence complete; promotion proposal on hold.

Authoritative references:

- CONTRACTS.md
- A_PHASE_ACCEPTANCE.md
- 14_docs/contract-hardening/CURRENT_STATE_INVENTORY.md
- 14_docs/contract-hardening/research/OPEN_SOURCE_REFERENCE_AUDIT.md
- 14_docs/contract-hardening/DECISION_REGISTER.md
- 14_docs/contract-hardening/project_state.json

Completed:

- Recomputed frozen root-contract hashes.
- Reconstructed accepted Software Integration Round 1 evidence.
- Ran the root contract gate, Backend tests, database module tests, and
  frontend typecheck/lint/unit/build checks.
- Identified the response-schema, source-operationId, RFC 9457 documentation,
  provenance round-trip, and NOT_RUN identity gaps.
- Initialized a local Git repository on main with no remote.
- Added root ignore and redacted Gitleaks policy after pre-Git scanning.
- Implemented candidate-only response, error, security, provenance, and
  execution-state hardening without editing the frozen root contract.
- Generated the hardened candidate from the actual FastAPI app and regenerated
  the Hey API SDK twice with byte-identical output.
- Completed Redocly, Schemathesis, provenance, secret-scan, and module-local
  verification evidence; recorded oasdiff and Respect limitations honestly.

Current blockers:

- The candidate cannot be promoted to root v0.2 by this round.
- oasdiff reports compatibility findings and two Respect workflows need a
  supported opaque-cookie handoff.
- Live MySQL integration evidence remains pending because the service was not
  active in the final run.

Next action:

Obtain an owner-approved compatibility/migration decision, supported workflow
cookie handoff, and live MySQL evidence before considering any v0.2 promotion.
