# D3 Slice 4 Controlled Validation Decision V1

Status: **FROZEN FOR FINAL VALIDATION**

This decision table is the Controller-frozen validation boundary for D3 Slice 4.
It permits only the final evidence closure of the existing D3-4 implementation.
It does not authorize D4, a new population policy, a D2 publication edit, a
runtime redesign, or a production/real-student pilot.

For the accepted Runtime identity decision, the registry's historical logical alias is
`qwen2.5-0.5b-engineering`; the sealed accepted provider identity remains
`qwen2.5:7b-instruct-q4_K_M` with the recorded digest and contract model. The
alias does not select the lightweight 0.5B provider.

| ID | Controller decision |
| --- | --- |
| D3VAL-01 | Validate the existing D3-4 candidate in the current worktree without resetting, cleaning, rebasing, merging, pushing, or tagging. |
| D3VAL-02 | Do not map `K12学生` to `UNIVERSITY_FRESHMEN_SYNTHETIC_DEMO`; the K12 mismatch remains a fail-closed regression. |
| D3VAL-03 | Do not edit, relabel, republish, or replace the accepted D2 publication. |
| D3VAL-04 | Use a tiny deterministic `SYNTHETIC_VALIDATION_ONLY` fixture for the compatible-population validation case. |
| D3VAL-05 | The compatible validation fixture must declare exactly `UNIVERSITY_FRESHMEN_SYNTHETIC_DEMO` and contain no real people, data, diagnosis, severity, crisis, clinical recommendation, or psychology-validity claim. |
| D3VAL-06 | Exercise the real accepted RAG service and retrieval algorithm over an ephemeral index/cache built from the validation fixture. |
| D3VAL-07 | The final Normal HTTP case must use the sealed accepted C Runtime identity and must not use the lightweight 0.5B validation runtime. |
| D3VAL-08 | The Normal HTTP case must traverse Input Safety, assessment binding, D3-2, real RAG, EvidenceBundle, D3-3, `render_projected`, accepted Runtime, Output Safety, and post-safety persistence. |
| D3VAL-09 | Preserve a real/integration K12 population mismatch case that reaches RAG and fails closed before D3-3/Runtime, with no fabricated mapping. |
| D3VAL-10 | Use a deterministic evaluation-only HTTP Runtime harness for the output-unsafe case; it must not modify `06_llm-runtime`, product configuration, or the Normal case. |
| D3VAL-11 | The output-unsafe case must use a safe user input, buffer the candidate, reach the real Output Safety service, block or require review, and persist no normal content. |
| D3VAL-12 | A separate RAG case with zero eligible trusted evidence must reach RAG, invoke neither D3-1 nor Runtime, produce no citations or fallback, and fail closed or abstain. |
| D3VAL-13 | Crisis routing and Safety-down behavior must remain fail closed: Crisis bypasses normal RAG/prompt/Runtime; Safety-down prevents normal generation. |
| D3VAL-14 | Full Pyright may retain only the two documented baseline SQLAlchemy import errors; touched D3-4/seam scope must remain at zero new errors. |
| D3VAL-15 | Fresh Prompt Engine, D3-2, CAT, RAG, Safety, Backend, Root, OpenAPI, Frozen Root, Ruff, compile/import, and diff checks must be green. |
| D3VAL-16 | Three fresh read-only reviewers must reconcile D3SEAM 20/20, D3INT 60/60, and D3VAL 16/16 with zero semantic or mission deviations; Commit 2 is allowed only if every hard gate is green and remains subject to Controller review. |

The validation package is synthetic engineering evidence only. It is not
psychology approval, legal/consent approval, real-student disclosure
authorization, real-pilot authorization, or production enablement.
