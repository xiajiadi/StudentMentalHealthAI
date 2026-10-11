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

This validates the marker, guardian/listener ownership, current-user-only DACL, connected port/datadir/schema and revision 0003. It generates a separate account with only SELECT/INSERT/UPDATE/DELETE on `smhai_school_demo`. Sealed recovery settings are written before account DDL; existing runtime settings are never overwritten. A new login then checks actual grants and active roles, refusing global/schema/role/grant-option expansion. Failure locks the account created by this attempt and preserves sealed material for explicit inspection rather than silently resetting or retrying account creation. Only successful permission verification writes `runtime-ready.json`; launchers must require that marker and recheck permissions. If locking fails, startup remains blocked pending owned-workspace inspection. The script does not launch applications or seed users.

Current isolated 3308 workspace has passed native runtime login, exact grants/no-active-role verification and revision read. A clean repeated full install and school backend/browser operation remain pending.

School-profile backend now consumes the current-user DPAPI key provider without plaintext fallback. Real workspace key-provider/Fernet encryption and decryption roundtrip passes; this proves key-format compatibility, not full backend/browser operation.

## School backend foreground entrypoint

```powershell
.\09_backend\.venv\Scripts\python.exe .\13_deployment\school_backend.py --workspace <absolute-external-directory> --preflight-only
```

The entrypoint requires matching `runtime-ready.json`, verifies process/listener/DACL and actual runtime grants/revision again, and reads the sealed authentication and database key files. It clears inherited database/SMHAI settings in its own process and rebuilds only the verified target; no plaintext `.env` is loaded. Application configuration fixes school tenancy, MySQL persistence and real HTTP module clients. Configuration preflight does not prove running services or authenticated workflows. Without `--preflight-only`, it runs the backend in the foreground on loopback 8088; an owning launcher still needs to manage its lifecycle. The corresponding frontend origin is loopback 4178. Historical M0 service processes are not stopped or reconfigured by this entrypoint.

Current entrypoint target/grants/revision/auth environment checks pass against the owned workspace, and deployment tests pass 49/49 (also independently rerun). Application startup, controlled four-role seed and browser business tests remain pending.

School authentication uses an independently generated 32-byte CSRF HMAC key from `school-auth.private.dpapi`, validated as 64 hex characters and passed only in process memory. Missing/invalid secrets fail closed. Current actual foreground startup and HTTP health/ready are verified, with zero implicit accounts; role login and browser workflows await controlled synthetic seeding.
