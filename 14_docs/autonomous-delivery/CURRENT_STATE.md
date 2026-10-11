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

## Checkpoint after first engineering cycle

Root committed runner/audit (`2f29f5e`) and student completion/original covers (`2d69368`), and pushed only the new dedicated development branch. Latest frontend verification: 48 unit tests, Lint and typechecked build pass. Existing untracked artifacts remain excluded. One real synthetic support attempt returns 502; only status/code were recorded, so its precise failing stage is not yet established. Login/list/logout return 200.

A real local runner lease for task `runner` has now been adopted by root and saved atomically in ignored state. The initial capability audit task is complete; Foundation phase is not accepted. Auth/tenant Worker has reviewed local commits, pending provenance, new-schema migration proof and launcher integration guard; no new migration has run against the old demo database.

## Next actions

Baseline report is available. Lead reused its explicit Luna/high app Worker in an isolated baseline worktree for schools/memberships/roles, tenant-scoped auth and negative tests. Root approved additive nullable legacy isolation, explicit context selection and disposable-schema-only migration checks. Never run the new migration against the old demo database. Root is replacing assessment covers with reproducible original SVGs and removing the per-card brand mark per the operator's latest annotations; other unverified image groups still block final packaging. Prioritize actual business QA and Claim Boundary diagnosis next.

## External gates

Real students/pilot, clinical thresholds, formal calibration/validity, ethics and production deployment remain unapproved. Synthetic engineering continues. Credentials and raw sensitive model output must not enter state or reports.

## School-workspace and tenant integration checkpoint

New external workspace `D:\Projects\.StudentMentalHealthAI-school-workspace-20261011` runs its separately owned loopback MySQL on 3308. Its directory DACL grants only the current user; generated credentials and encryption keys use current-user DPAPI. No plaintext secret configuration is written. Initialization was recovered after driver/expired-password setup failures; a clean repeatable installation remains unproven.

The new `smhai_school_demo` schema upgraded from empty to revision `20261011_0003` (23 tables). Alembic consistency check passes after matching three ORM server defaults. A separate owned `smhai_school_synthetic_test_20261011` schema on 3308 passes all seven native MySQL integration tests. Tests preserve foreign keys and explicitly flush cleanup dependencies. Old 3307 and system 3306 were not migrated or reset.

Auth integration includes school memberships/roles, explicit CSRF-protected active context, tenant-scoped grants, invalid/revoked context denial and concurrent context re-projection. School profile does not seed legacy identities. Backend checks the required schema revision before bootstrap. Integration-tree focused tests: backend 23/23, schema/provenance 14/14. Lead's additional safe/quality checks remain separate evidence. Legacy launcher now fails before bootstrap when the school migration is present; existing historical M0 services must not be restarted with this new source against the old schema.

Deployment tests now pass 27/27 (runner 19, workspace 7, launcher guard 1). Runner is a recoverable lease/state CLI, not a coding executor; scheduled unattended/reboot continuation is still unproven.

Next: integrate a DPAPI key provider, create a least-privilege runtime identity, controlled synthetic school accounts and a new owned school launcher, then verify real school-profile auth and browser workflows. Four-role product delivery and AI recovery remain incomplete.

Runtime preparation checkpoint: generated current-user DPAPI-sealed runtime identity on the owned 3308 instance. Native login and exact schema-only DML/no-active-role gate pass. Script fresh tests: 16/16; deployment aggregate before the last four permission-negative additions: 39/39. Lead identified missing in-script grant readback; this is now implemented and native-checked. No clean repeat-install or application launch claim.

DPAPI integration checkpoint: Worker af4a928 reviewed and integrated; integration crypto 9/9 and adapter 12/12 pass, and the actual workspace key file supports Fernet roundtrip without plaintext persistence. Runtime preparation now locks its newly-created account on failed verification and emits readiness only on success; focused tests 17/17. School-profile CSRF key configuration is the next isolated backend task.
