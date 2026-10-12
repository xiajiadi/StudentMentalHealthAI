# Planned shutdown and resume checkpoint

User instruction received: 2026-10-11, Beijing time.

## Deadline

- Laptop shutdown: **2026-10-12 06:40 Asia/Shanghai** / 2026-10-11 22:40 UTC.
- Begin safe wrap-up: 06:20 Beijing / 22:20 UTC.
- Complete pause by: 06:35 Beijing / 22:35 UTC, allowing five minutes of buffer.
- Continue authorized synthetic engineering before this window. Do not mark the
  project complete unless the entire mandate is actually satisfied.

Desktop heartbeat `psynova` is bounded by the pause deadline. Separate heartbeat
`psynova-2` requests wrap-up at 22:20/22:35 UTC. Scheduled execution depends on the
computer and desktop app remaining available; configuration is not trigger proof.

## Wrap-up procedure

1. Check real clock and live agents; stop dispatching new work at wrap-up time.
2. Ask running Workers to return their actual diff, current checks and remaining
   work. Preserve uncommitted edits; do not discard or fabricate completion.
3. Finish active database transactions, migrations and Git operations safely.
   Do not kill an in-flight data operation to meet a cosmetic timestamp.
4. Record actual HEAD, branch, dirty files, verified tests, public evidence paths,
   owned process manifest, unresolved failures and the exact next action in
   CURRENT_STATE.md. Review and commit coherent source when possible; unfinished
   changes may remain explicitly recorded for resumption.
5. Stop the project Runner and pause both heartbeats. Stop only verified owned
   school application processes, preserving old M0/system/shared module services.
   Do not shut down the user's machine or delete data.
6. Call update_goal(status="paused") under the user's explicit authorization,
   report the returned state and stop work. Actual pause evidence belongs below.

## Resume when the user clicks Continue

Read AGENTS.md, MISSION.md, CURRENT_STATE.md and this checkpoint. Inspect Git and
the actual clock, services and agents. After shutdown, old numeric PIDs are not
ownership proof. Revalidate external workspace, DPAPI settings, schema revision
and DACL; start only missing owned services. Do not recreate/reset databases,
reseed existing passwords, rerun an already-completed migration blindly or revive
an expired automation automatically. Resume the Runner and establish a fresh
schedule only within the user's resumed authorization and available resources.

## Actual pause record

The reminder was observed after the deadline at UTC2026-10-12 00:09 (Beijing08:09). Both expired heartbeats were set PAUSED. A scheduled pause by06:35 is not verified and must not be claimed. The user then explicitly resumed while away without RTX3060; the goal is now ACTIVE. Existing data/credentials were preserved and missing CPU school services were recovered after fresh ownership checks. See CURRENT_STATE.md for actual service identities, working tree and next actions. The old deadline is historical; do not revive its expired automations automatically.
