# School MySQL workspace resume

`resume_school_workspace.py` supports four explicit classifications:

- No mode flags: the registered legacy synthetic workspace on port `3308`.
- `--restore-mode`: an isolated restored copy, validated against its existing restore state.
- `--fresh-mode`: an already initialized and migrated install target with no runtime or restore artifacts.
- `--prepared-install-mode`: that install target after runtime provisioning has completed and its runtime identity is available.

Both install modes require an absolute workspace path, its port, and the exact workspace ID supplied by the trusted install handoff. Replace these placeholders with the values from that handoff:

```powershell
python 13_deployment/resume_school_workspace.py `
  --fresh-mode `
  --workspace '<INSTALL_WORKSPACE>' `
  --port <INSTALL_PORT> `
  --expected-workspace-id '<EXPECTED_WORKSPACE_ID>'
```

For a runtime-prepared install, use the same arguments with `--prepared-install-mode` instead of `--fresh-mode`. Fresh mode rejects any partial or complete runtime artifacts. Prepared mode requires `runtime.private.dpapi`, `school-auth.private.dpapi`, and a matching `runtime-ready.json`; after startup it uses the existing runtime validator to check the minimal database grants, active role, schema revision, and school authentication material. Either mode rejects `restore-state.json`.

The install-style directory name and expected ID bind the request to one target. The workspace JSON marker is not signed and, by itself, does not prove who created it. Both modes check the existing initialized MySQL files, current-user-only DACL, exact guardian executable/arguments/PID creation time, and loopback listener ownership. Fresh mode validates current-user DPAPI material and then checks database identity and migration revision with read-only queries. Prepared mode validates runtime and authentication DPAPI material through the existing runtime validator. Neither path requires restore state.

Resume only starts the existing data directory or verifies its exact running guardian. It does not initialize/reset a database, change credentials, run migrations, create a runtime identity, or seed data. Any target classification, ID, port, private-settings, process, listener, or database mismatch fails closed. Partial runtime artifacts require explicit local recovery; resume will not delete or repair them. The per-workspace lock serializes attempts. A launched guardian is preserved if later readiness verification fails; inspect the owned workspace locally before retrying.

The `3308` legacy mode and `--restore-mode` retain their existing validation rules. Ports `3306` and `3307` are outside the accepted workspace range. Do not use this synthetic demo flow with real student data or treat its engineering checks as school deployment approval.
