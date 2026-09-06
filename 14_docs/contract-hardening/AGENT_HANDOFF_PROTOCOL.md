# Agent Handoff Protocol

Before continuing this task in a new session:

1. Read PROJECT_STATE.md and this directory's current-state inventory.
2. Read DECISION_REGISTER.md and the current machine evaluation JSON when it
   exists.
3. Verify the current checkout, branch, tag, and working-tree diff.
4. Recompute frozen root-contract hashes before editing.
5. Treat candidate, evidence, and report files as repository source of truth;
   do not rely on chat history or unverified prior claims.
6. Update PROJECT_STATE.md only at a phase boundary, blocker, or decision
   change.
7. Never promote the root contract, push remote changes, or introduce real
   student data from an agent handoff.

At handoff, record the active phase, completed evidence, blockers, and one next
action. Do not record a tool-call diary.
