# PsyNova autonomous engineering mandate

Decision: `SMAI_LONG_RUN_AUTONOMOUS_DELIVERY_MANDATE_20261011`.
Authority: [operator mandate](https://github.com/xiajiadi/StudentMentalHealthAI/issues/1#issuecomment-6106668496).
Baseline: M0 `74372fef547ea6d0eba0e88fd5dd44750d7f1f8e`.
Integration branch: `xiajiadi/autonomous-delivery-20261011`.

## Outcome

Deliver a runnable, persistent, synthetic-only four-role school measurement and education-support product. Preserve the current PsyNova UI direction. Build complete frontend/backend/authorization/database workflows; static screens and isolated passing tests do not establish delivery.

Roles: STUDENT, TEACHER (Scope A, completion metadata only), PSYCHOLOGICAL_SPECIALIST (tiered, assigned cases), SCHOOL_ADMIN (organization and operations, no psychological content). REVIEWER remains an internal controlled safety capability. Parents are deferred.

Required work: organization/accounts/imports/tasks; synthetic item banks, tested CAT estimation/selection/stopping/simulation; student completion and history; measurement separated from L1/L2/L3 publication; assigned professional reviews; independent local AI conversations with RAG/citations/history; safe repeatable install/start/stop/backup/recovery and browser QA.

## Authority and limits

The operator delegates ordinary synthetic engineering, additive interfaces, tests, local commits, integration and pushes to NEW dedicated development branches, draft PRs and local packaging. Never force-push, overwrite protected/default branches, merge protected D4, alter frozen evidence, or create production release tags. Preserve untracked user artifacts.

Root acts as Autonomous Controller. Execution Lead uses explicit Luna/max; its direct Workers use the explicit Luna/high role, default 272k context and depth 0. Each worker owns disjoint files or an isolated worktree. Independent review must inspect actual changes and fresh evidence.

No real student data, approved pilot, clinical thresholds, professional validity claim, cloud-model fallback, automatic external contact, global MySQL change, privilege escalation, destructive old-database reset or unlicensed redistribution. Preserve Safety, Claim Boundary, crisis routing, abstention and citation validation. Human professional approvals remain external gates; unrelated synthetic engineering continues.

## Completion

Only declare `ENGINEERING_DEMO_READY` after all role workflows, local AI, CAT engineering, security negative cases, real database integration, browser evidence, installation/recovery and independent QA satisfy the operator's mandate. This never implies `SCHOOL_PRODUCTION_APPROVED` or psychometric validation.

## Recovery

Read this file, `CURRENT_STATE.md`, `TASK_QUEUE.json` and the baseline report before resuming. Inspect Git and owned services before any mutation. Runner leases serialize task ownership; successful verification and an independent review precede DONE. Save checkpoints every 60–90 minutes and a concise daily outcome report. Do not store credentials, private conversations or raw rejected model candidates.

Scheduling requires the computer and desktop app to be running with the project available. A scheduled wakeup does not prove uninterrupted execution or survival of reboot; verify actual runs and recover from durable state. [Official scheduled-task documentation](https://learn.chatgpt.com/docs/automations?surface=app).
