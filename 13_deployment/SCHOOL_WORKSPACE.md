# Isolated synthetic school-schema workspace

The school-schema development code must never be migrated onto the preserved M0 database. The legacy launcher fails before dependency/bootstrap/DDL when the school migration is present. Existing M0 processes remain a historical baseline; use the pinned M0 source for legacy operation.

## Current fresh offline install (schema 20261024_0025)

`school_install.py` composes the existing cached dependency preparer, fresh isolated workspace creator, empty-schema migration, least-privilege runtime identity, fictional synthetic seed, owned preview lifecycle, and four-role browser check. It requires a clean dependency-target worktree at the same HEAD as the source and an absolute, non-existing external workspace. The parent directory, vendor MySQL binary directory, six already-installed Python interpreters, and offline dependency caches must already exist. Standard CAT uses port 8182 by default; the database/API/UI ports are always explicit and must be free.

The command does not download or package Ollama/model, OPA, Guard, corpus, or vector assets. Keep those assets on the host and verify the actual service dependencies during startup; a dependency-package PASS is not AI readiness or whole-platform readiness. No backup or workspace from another Windows user is reused: DPAPI credentials remain bound to the current Windows user.

### Explicit research profile opt-in

`plan`, `install`, and `resume` also accept the existing Backend/lifecycle research options: the paired runtime/service files and hashes plus CAT paths; the paired study-use file/hash, `--research-source-rights-verified`, and `--research-latest-study-end`; optional student-source and general-education draft file/hash pairs; and the existing worker and one-shot continuation flags. A draft requires the matching student-source and study-use configuration. These options are absent by default. The source-rights flag is an operator declaration consumed by the existing policy validator; it does not represent ethics, clinical, psychometric, or school approval.

The installer verifies every supplied file's exact bytes against its SHA-256 and binds the normalized paths, hashes, and opt-in flags into its content-free checkpoint. The runtime, service, and study-use JSON files are the only files imported into the newly created workspace; they are copied byte-for-byte with exclusive creation to `.school-research-profile/` and rechecked on resume. Student-source, draft, and programme-manifest files stay at their supplied absolute paths and must remain present and unchanged for resume. Existing Backend and lifecycle validation still checks their schemas, study/source bindings, and permissions before application startup. This does not start or certify the external Runtime, RAG, Safety, OPA, or model services and does not change `whole_ready=false`.

From the source checkout, first run the read-only plan with the six Python paths used by the official dependency preparation tool:

```powershell
$source = 'D:\Projects\StudentMentalHealthAI-m0-integration'
$dependencyTarget = 'D:\Dev\projects\smhai-school-install-deps-20261016-v'
$workspace = 'D:\Projects\.StudentMentalHealthAI-school-install-20261016-v'
$mysqlBin = 'D:\Dev\tools\mysql\bin'
$installerPython = 'D:\Dev\pythons\python312\python.exe'
$catPython = 'D:\Dev\pythons\python314\python.exe'
$py312 = 'D:\Dev\pythons\python312\python.exe'
$head = git -C $source rev-parse HEAD
git -C $source worktree add --detach $dependencyTarget $head
$pythonArgs = @(
  '--python', "01_cat-engine=$catPython",
  '--python', "09_backend=$py312",
  '--python', "11_database=$py312",
  '--python', "05_rag-engine=$py312",
  '--python', "06_llm-runtime=$py312",
  '--python', "08_safety-engine=$py312"
)
& $installerPython .\13_deployment\school_install.py plan `
  --source-root $source --dependency-target-root $dependencyTarget `
  --workspace $workspace --mysql-bin $mysqlBin `
  --database-port 3330 --backend-port 8104 --frontend-port 4194 `
  --standard-cat-port 8182 @pythonArgs
```

After reviewing the plan, replace `plan` with `install`. To continue after a fully completed stage, rerun the same arguments with `resume`. Completed stages are rechecked; a stage left `running` or marked failed blocks automated replay. Inspect and preserve that target rather than resetting it or re-running seed, migration, or lifecycle start. The checkpoint is a content-free sibling JSON file; workspace credentials stay in the workspace's current-user DPAPI files.

The final machine result is `APP_AND_ROLE_BROWSER_VERIFIED` only when the current-schema workspace, owned services, and all four synthetic role browser sessions verify. `whole_ready` remains false; the command does not claim AI readiness, asset redistribution rights, psychometric validation, or production approval.

Initialize a **new, non-existing external directory** using an already-installed vendor MySQL binary and the database module's environment:

```powershell
.\11_database\.venv\Scripts\python.exe .\13_deployment\create_school_workspace.py --workspace <absolute-external-directory> --mysql-bin <vendor-mysql-bin> --port 3308
```

The initializer rejects existing paths, repository paths and system/legacy ports. It creates a dedicated loopback-only instance and `smhai_school_demo`; does not install a service, elevate privilege or reuse/reset old data. The directory DACL is verified to grant only the current user. Credentials/encryption keys are randomly generated and sealed using current-user Windows DPAPI; plaintext settings, password argv and `MYSQL_PWD` are not used. Vendor initialization output stays in memory. A one-purpose PyMySQL connection sends password rotation before the driver's usual SET NAMES, as required by expired-password initialization; normal database connections are unchanged.

`READY_FOR_MIGRATION` proves initialization only. Check the marker, owned process/listener and empty schema before migrations. Use the protected configuration only inside the database process, never display/export values or put them into shell text. `prepare_school_runtime.py` creates and verifies a separate runtime identity limited to `SELECT`, `INSERT`, `UPDATE`, and `DELETE` on this schema; the application does not receive the workspace-builder account.

Creation does not silently reuse a failed directory. On setup failure, preserve the new data and sealed recovery material; stop only the process tree held by this creation attempt. Recovery requires checking the marker/executable/datadir/listener and the actual failure cause. The official sealed-backup restore flow is implemented separately; it does not make failed initialization safe to replay or reset.

The official backup and restore flow is implemented and has verified current-schema key decryption in an isolated workspace. DPAPI settings remain bound to the Windows user that created them: copying a backup to another user or machine does not make its keys portable.

## Runtime database identity

After the empty-schema migration and ownership checks, run:

```powershell
.\11_database\.venv\Scripts\python.exe .\13_deployment\prepare_school_runtime.py --workspace <absolute-external-directory>
```

This validates the marker, guardian/listener ownership, current-user-only DACL, connected port/datadir/schema and the current revision `20261024_0025`. It generates a separate account with only `SELECT`/`INSERT`/`UPDATE`/`DELETE` on `smhai_school_demo`. Sealed recovery settings are written before account DDL; existing runtime settings are never overwritten. A new login then checks actual grants and active roles, refusing global/schema/role/grant-option expansion. Failure locks the account created by this attempt and preserves sealed material for explicit inspection rather than silently resetting or retrying account creation. Only successful permission verification writes `runtime-ready.json`; launchers must require that marker and recheck permissions. If locking fails, startup remains blocked pending owned-workspace inspection. The script does not launch applications or seed users.

The current workspace schema revision is `20261024_0025`. The migrator accepts a new empty workspace or an exact `20261016_0024` schema after checking its trusted table, column, key, foreign-key, index, and CHECK layout. It applies the existing Alembic chain additively to 0025 and verifies the resulting schema. Unknown, partial, extra-object, or other historical revisions are rejected. It does not delete or rebuild data. A workspace that already has runtime, auth, or seed credential markers remains blocked by this new-workspace migration path and requires a separately reviewed maintenance/backup procedure. Create a new external workspace for a fresh install flow; historical runtime evidence alone is not proof of current-schema readiness.

School-profile backend now consumes the current-user DPAPI key provider without plaintext fallback. Real workspace key-provider/Fernet encryption and decryption roundtrip passes; this proves key-format compatibility, not full backend/browser operation.

## School backend foreground entrypoint

```powershell
.\09_backend\.venv\Scripts\python.exe .\13_deployment\school_backend.py --workspace <absolute-external-directory> --preflight-only
```

The entrypoint requires matching `runtime-ready.json`, verifies process/listener/DACL and actual runtime grants/revision again, and reads the sealed authentication and database key files. It clears inherited database/SMHAI settings in its own process and rebuilds only the verified target; no plaintext `.env` is loaded. Application configuration fixes school tenancy, MySQL persistence and real HTTP module clients. Configuration preflight does not prove running services or authenticated workflows. Without `--preflight-only`, it runs the backend in the foreground on loopback 8088; an owning launcher still needs to manage its lifecycle. The corresponding frontend origin is loopback 4178. Historical M0 service processes are not stopped or reconfigured by this entrypoint.

The backend preflight verifies the runtime marker, grants, current revision, and auth environment. It does not by itself verify service ownership or browser workflows; the fresh install command follows it with lifecycle status and four-role browser checks.

School authentication uses an independently generated 32-byte CSRF HMAC key from `school-auth.private.dpapi`, validated as 64 hex characters and passed only in process memory. Missing/invalid secrets fail closed. Role credentials are created only by the explicit fictional school seed and remain sealed for the current Windows user.

## Backend + Frontend lifecycle for a prepared workspace

`school_app_lifecycle.py` owns the Backend and Frontend application processes for an already prepared workspace at the current revision required by `school_schema.py`. Standard synthetic CAT is managed only with explicit `--enable-standard-cat` (default off); it starts before Backend and uses a separately configurable `--standard-cat-port` (default 8180). Its source fingerprint canonicalizes CRLF to LF for hashing only; it does not rewrite CAT files. CAT/RAG/LLM/Safety remain unverified unless individually observed, and lifecycle status never means whole-platform readiness. The lifecycle is not an installer: Python/Node project environments and vendor MySQL must already exist. It does not migrate, seed, reset, start or stop MySQL.

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
