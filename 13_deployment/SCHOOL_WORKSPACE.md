# Isolated synthetic school-schema workspace

The school-schema development code must never be migrated onto the preserved M0 database. The legacy launcher fails before dependency/bootstrap/DDL when the school migration is present. Existing M0 processes remain a historical baseline; use the pinned M0 source for legacy operation.

Initialize a **new, non-existing external directory** using an already-installed vendor MySQL binary and the database module's environment:

```powershell
.\11_database\.venv\Scripts\python.exe .\13_deployment\create_school_workspace.py --workspace <absolute-external-directory> --mysql-bin <vendor-mysql-bin> --port 3308
```

The initializer rejects existing paths, repository paths and system/legacy ports. It creates a dedicated loopback-only instance and `smhai_school_demo`; does not install a service, elevate privilege or reuse/reset old data. The directory DACL is verified to grant only the current user. Credentials/encryption keys are randomly generated and sealed using current-user Windows DPAPI; plaintext settings, password argv and `MYSQL_PWD` are not used. Vendor initialization output stays in memory. A one-purpose PyMySQL connection sends password rotation before the driver's usual SET NAMES, as required by expired-password initialization; normal database connections are unchanged.

`READY_FOR_MIGRATION` proves initialization only. Check the marker, owned process/listener and empty schema before migrations. Use the protected configuration only inside the database process, never display/export values or put them into shell text. Builder permission is limited to this new schema; a separate runtime identity with fewer permissions remains a delivery requirement.

Creation does not silently reuse a failed directory. On setup failure, preserve the new data and sealed recovery material; stop only the process tree held by this creation attempt. Recovery requires checking the marker/executable/datadir/listener and the actual failure cause. Current initialization was recovered after a missing driver environment and expired-password driver initialization issue; generic unattended recovery is not yet implemented or accepted.

The state is Windows/user-bound: another user or machine cannot decrypt the DPAPI settings by merely copying these files. Portability, backup/recovery and runtime-key-provider integration still need separate implementation and QA before packaging.

## Runtime database identity

After the empty-schema migration and ownership checks, run:

```powershell
.\11_database\.venv\Scripts\python.exe .\13_deployment\prepare_school_runtime.py --workspace <absolute-external-directory>
```

This validates the marker, guardian/listener ownership, current-user-only DACL, connected port/datadir/schema and current revision `20261013_0010`. It generates a separate account with only SELECT/INSERT/UPDATE/DELETE on `smhai_school_demo`. Sealed recovery settings are written before account DDL; existing runtime settings are never overwritten. A new login then checks actual grants and active roles, refusing global/schema/role/grant-option expansion. Failure locks the account created by this attempt and preserves sealed material for explicit inspection rather than silently resetting or retrying account creation. Only successful permission verification writes `runtime-ready.json`; launchers must require that marker and recheck permissions. If locking fails, startup remains blocked pending owned-workspace inspection. The script does not launch applications or seed users.

Current isolated 3308 workspace has passed native runtime login, exact grants/no-active-role verification and revision read. A clean repeated full install and school backend/browser operation remain pending.

School-profile backend now consumes the current-user DPAPI key provider without plaintext fallback. Real workspace key-provider/Fernet encryption and decryption roundtrip passes; this proves key-format compatibility, not full backend/browser operation.

## School backend foreground entrypoint

```powershell
.\09_backend\.venv\Scripts\python.exe .\13_deployment\school_backend.py --workspace <absolute-external-directory> --preflight-only
```

The entrypoint requires matching `runtime-ready.json`, verifies process/listener/DACL and actual runtime grants/revision again, and reads the sealed authentication and database key files. It clears inherited database/SMHAI settings in its own process and rebuilds only the verified target; no plaintext `.env` is loaded. Application configuration fixes school tenancy, MySQL persistence and real HTTP module clients. Configuration preflight does not prove running services or authenticated workflows. Without `--preflight-only`, it runs the backend in the foreground on loopback 8088; an owning launcher still needs to manage its lifecycle. The corresponding frontend origin is loopback 4178. Historical M0 service processes are not stopped or reconfigured by this entrypoint.

Current entrypoint target/grants/revision/auth environment checks pass against the owned workspace, and deployment tests pass 49/49 (also independently rerun). Application startup, controlled four-role seed and browser business tests remain pending.

School authentication uses an independently generated 32-byte CSRF HMAC key from `school-auth.private.dpapi`, validated as 64 hex characters and passed only in process memory. Missing/invalid secrets fail closed. Current actual foreground startup and HTTP health/ready are verified, with zero implicit accounts; role login and browser workflows await controlled synthetic seeding.

## Backend + Frontend lifecycle for a prepared workspace

`school_app_lifecycle.py` owns only the Backend and Frontend application processes for an already prepared workspace at schema revision `20261013_0010`. It is not an installer: Python/Node project environments and vendor MySQL must already exist. It does not migrate, seed, reset, start or stop MySQL, or manage CAT/RAG/LLM/Safety. Those modules remain separately managed dependencies and are reported as `UNVERIFIED`; this two-process status never means whole-platform readiness.

Use an explicit external workspace path and frontend mode. `dev` serves the current source tree; `preview` first runs the frontend typecheck and production build with `VITE_API_MODE=real` and the selected loopback Backend URL, then serves the built output. Neither mode publishes the site.

```powershell
$py = '.\09_backend\.venv\Scripts\python.exe'
$lifecycle = '.\13_deployment\school_app_lifecycle.py'
$workspace = '<absolute external prepared workspace>'

& $py $lifecycle plan --workspace $workspace --frontend-mode dev --llm-profile school-gpu-7b
& $py $lifecycle start --workspace $workspace --frontend-mode dev --llm-profile school-gpu-7b
& $py $lifecycle status --workspace $workspace
& $py $lifecycle stop --workspace $workspace
```

Choose `--frontend-mode preview` when validating the production build locally. `--llm-profile school-gpu-7b` explicitly selects the existing frozen 7B profile; it is never selected automatically. `default` preserves the Backend's existing default configuration and does not assert CPU model suitability or AI readiness. The launcher does not substitute the CPU engineering test model for the school 7B profile. With RTX 3060 unavailable, keep the 7B-dependent AI path unverified/unavailable; the business UI/API process status does not change that boundary.

`plan` is read-only and does not inspect sealed credentials, build, or spawn. `start` requires the prepared runtime marker and passes the existing Backend preflight, which rechecks the sealed runtime grants and current schema revision before checking both application ports. It also resolves the Backend listener interpreter from the existing `.venv/pyvenv.cfg` `home` and requires the actual child executable to match that exact base Python path. It refuses occupied ports and any active, partial, stale, or foreign manifest. After a fully verified stop, it preserves the old manifest under a timestamped history name and starts a fresh lifecycle record; it will not archive a manifest while an old owner PID or listener remains. Process records include the wrapper launcher and actual listener PID, executable, creation time, command line and parent link. If readiness is not observed, the process and partial manifest are retained for explicit status/recovery review. `stop` first checks all recorded process chains and listeners, then stops only verified Backend/Frontend processes in reverse order. On Windows each PID is opened and revalidated through a pinned process handle before termination, avoiding PID reuse. A partial stop remains explicitly recorded for recovery. It never stops database or shared module processes. A malformed, stale, or foreign process manifest fails closed.

Lifecycle status may report both application processes ready while external modules remain unverified. `whole_ready` therefore remains `false`; browser/business-path acceptance still requires the Controller's separate live verification.

## Native lifecycle evidence (2026-10-13)

Controller verified the prepared0010 targetF with actual dev start, four-role browser
login/route/denial/logout4/4, verified stop, then repeat preview start with real frontend
typecheck/build and another4/4 browser check. The venv launcher, approved base-Python
child and Node listener were recorded separately. No shared modules or database
processes were stopped.28 focused fake tests and108 related deployment tests pass.
CURRENT_STATE.md indexes native artifacts and retained initial failures. Current
preview application availability is a bounded lifecycle result; installation
portability, complete business acceptance and AI readiness remain pending.
