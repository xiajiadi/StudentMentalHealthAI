# OWASP Database Security Mapping

Source references: [OWASP Database Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Database_Security_Cheat_Sheet.html),
[OWASP Cryptographic Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html),
and [OWASP Key Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Key_Management_Cheat_Sheet.html).
This mapping records engineering controls; it is not a security certification.

| OWASP concern | Round 1 control | Evidence/status |
| --- | --- | --- |
| Network isolation | Local MySQL is intended for loopback (`127.0.0.1`/localhost); no public binding is added by this module. | Final isolated run used `127.0.0.1:3307`; production network boundary deferred. |
| TLS | Production connections must use TLS; local loopback TLS is not a hard Round 1 gate. | Documented as `LOCAL_LOOPBACK_DEV`; no claim that local TLS is enabled. |
| Authentication | DB URL is environment-driven; raw credentials are not committed or printed. | `DatabaseSettings`; sanitized URL only. |
| Least privilege | Runtime user and migrator user are separate; runtime DDL, `GRANT`, and `FILE` are denied. | `database_round1_evaluation.json`; app `SHOW GRANTS` and four denial probes passed. |
| Credentials | Passwords are read from environment/interactive client prompt and excluded from files. | No credentials in repository search; backup scripts contain no password value. |
| Patching | MySQL 8.4 LTS and stable SQLAlchemy/Alembic lines are selected. | Technical decision and dependency lock. |
| Backup | `mysqldump --single-transaction --no-tablespaces` baseline with synthetic database-name guard. | `database_round1_evaluation.json`; synthetic logical dump completed. |
| Restore | Fresh test/restore database guard and verification procedure. | `database_round1_evaluation.json`; fresh restore decrypted an encrypted assessment payload. |
| Injection | SQLAlchemy expressions and bound parameters are used; raw SQL is isolated to operational scripts with explicit values. | Repository code review and static checks. |
| Sensitive storage | Assessment/support/safety/review payloads are Fernet-encrypted binary values; raw unsafe candidates are not persisted. | Crypto tests and privacy matrix. |
| Logging | SQL echo is disabled by default; audit metadata is allowlisted and does not contain payloads. | `DatabaseSettings`, `AuditRepository`. |
| Key management | Dev keys are outside the repository; key versions and rotation are explicit; production KMS/Vault/HSM is deferred. | `DevLocalKeyProvider`, rotation tests, privacy model. |
| Data lifecycle | Explicit synthetic purge/erasure routines are separate from operational status. | `SyntheticLifecycleService`, retention placeholder. |
