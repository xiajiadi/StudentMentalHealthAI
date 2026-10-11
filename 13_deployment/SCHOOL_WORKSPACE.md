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
