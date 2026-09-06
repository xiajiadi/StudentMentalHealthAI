# Safety configuration

`safety.v1.json` is the module runtime boundary. `rules.v1.json` is the
versioned manifest for every Round 1 deterministic domain rule. Each entry
records its rule ID, version, status, owner, approval status, and source.

`PENDING_PSYCH_REVIEW` and `SYNTHETIC_POLICY_ONLY` are deliberate statuses;
they are not clinical or legal approval. The manifest does not authorize real
student data, real crisis notification, or clinical decisions.
