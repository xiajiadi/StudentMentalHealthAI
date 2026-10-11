# Current autonomous delivery state

Updated: 2026-10-11. Phase I, ongoing; no delivery acceptance.

## Git and ownership

Baseline local and remote M0: `74372fef547ea6d0eba0e88fd5dd44750d7f1f8e`.
Current dedicated integration branch: `xiajiadi/autonomous-delivery-20261011`.
Existing untracked frontend output and unused login asset are preserved.
Root owns mission, queue, recovery runner and integration. Luna/max Lead owns `AUTONOMOUS_BASELINE_REPORT.md`; its explicit Luna/high app-audit Worker runs in an isolated baseline worktree. Confirm live agent inventory on recovery before reassigning files.

## Fresh evidence

- M0 HEAD equals remote at initial inspection.
- Initial inspection found M0 services stopped; subsequent project-only recovery restored frontend 4173/backend 8080/CAT 8180/RAG 8170/Runtime 8160/OPA 8181/Safety 8190 and Ollama 11434 through the existing launcher.
- System MySQL listens on 3306; it must remain unchanged.
- Initial preflight exited 1. Old manifest matched this worktree and all eight recorded PIDs were absent; it was backed up externally before the existing stop script cleared it. Project MySQL was started from its existing external datadir with no-defaults, loopback bind and port 3307. Native listener PID and parent executable/arguments were verified. No reset, old-row deletion, privilege escalation or global MySQL change occurred.
- New preflight and launcher completed successfully. Knowledge pipeline exported one synthetic document/chunk for M0; all listed services reported ready. Actual student/database/model/browser business workflows still need verification.
- Runner: 17 fresh tests pass, independent Lead rerun and disposable Git dirty-tree verification pass. This accepts the bounded task-state mechanism only, not Phase I or final delivery. Heartbeat `psynova` is ACTIVE at 90-minute intervals; first actual scheduled trigger/reboot continuation is unproven.
- Final-package redistribution evidence is missing for several image groups; original compatible replacements are planned.
- Original proposal was read as background, not as current capability evidence.

## Next actions

Baseline report is available. Lead reused its explicit Luna/high app Worker in an isolated baseline worktree for schools/memberships/roles, tenant-scoped auth and negative tests. Root approved additive nullable legacy isolation, explicit context selection and disposable-schema-only migration checks. Never run the new migration against the old demo database. Root is replacing assessment covers with reproducible original SVGs and removing the per-card brand mark per the operator's latest annotations; other unverified image groups still block final packaging. Prioritize actual business QA and Claim Boundary diagnosis next.

## External gates

Real students/pilot, clinical thresholds, formal calibration/validity, ethics and production deployment remain unapproved. Synthetic engineering continues. Credentials and raw sensitive model output must not enter state or reports.
