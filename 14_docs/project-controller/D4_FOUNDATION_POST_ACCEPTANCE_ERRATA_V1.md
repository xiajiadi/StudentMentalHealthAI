# D4 Foundation Post-Acceptance Errata V1

## Scope

This record documents two D4-1 foundation corrections found while preparing
the D4-2 deterministic regression repair. The accepted D4-1 tag and commit are
immutable. No accepted D3 fixture was edited.

The correction is limited to evaluation evidence and its verification rules:

- the exact synthetic D3 fixture is identified by canonical JSON content;
- JSON line-ending differences between a Windows checkout and a canonical
  evidence representation do not create different semantic fixture identities;
- the D4 machine-evidence transaction pattern matches the accepted product
  generator (`TX_` plus 32 lowercase hexadecimal characters).

## Fixture provenance

| Hash | File/path | Commit | Semantic identity | Why it exists | Authority |
|---|---|---|---|---|---|
| `cb647c639188e0d1e752c8c842a649a0245a57849458f4cb26d9fc8b7a413abd` | `03_assessment-adapter/fixtures/synthetic_assessment.v1.json` | `80140de6fbb63d3239ecc425f9c3daaaf34fb4d7` (accepted D3-4 evidence closure) | Canonical LF-normalized bytes of the accepted D3 synthetic assessment fixture | Binds D4 exact fixture references to the accepted D3 product source | **Authoritative** |
| `174c27a4dccbb9e5656afa1d7d79db1920c610768c67ec0705bc58eff7c61398` | `03_assessment-adapter/fixtures/synthetic_assessment.v1.json` | Same source, current Windows checkout representation | Same JSON content with CRLF line endings | Historical raw checkout hash used by the first D4-2 run | Non-authoritative representation |
| `7a18e4a995fe54f00f8d8e0cb5e34b30ae7f99e02f72793391152a3fff6dcc01` | `12_evaluation/d4-evaluation-r1/datasets/fixtures/synthetic_assessment.v1.json` | `5944f91a0a00a823bc7a3a97ae2069e28d01c3c3` (D4-1 foundation introduction) | Canonical LF-normalized bytes of the D4-1 evaluation snapshot | Preserves the original D4-1 snapshot identity | **Authoritative for that historical snapshot only** |
| `cea8c09796ee0c92ced891b6fc7e1d1114fd4a264262a0ca5bfe375f31e40d61` | `12_evaluation/d4-evaluation-r1/datasets/fixtures/synthetic_assessment.v1.json` | Same D4-1 snapshot, current Windows checkout representation | Same snapshot content with CRLF line endings | Explains the original D4-1 fixture mismatch in a byte-sensitive loader | Non-authoritative representation |

The accepted D3 fixture and the D4-1 snapshot are not silently treated as the
same source. The D4-2 `exact_d3_fixture` records now bind to the authoritative
D3 source hash `cb647...`; the D4-1 historical snapshot hash `7a18...` remains
documented and is not rewritten.

## Frozen identity mechanism

For JSON fixture verification, the evaluation loader reads UTF-8 bytes and
normalizes `CRLF` to `LF` before calculating SHA-256. JSON content is otherwise
unchanged. This makes the identity a content identity across Windows checkout
line endings while preserving the exact parsed fixture bytes and schema.

The exact D3 binding is:

```text
fixture_version: synthetic_assessment.v1
source_commit: 80140de6fbb63d3239ecc425f9c3daaaf34fb4d7
source_path: 03_assessment-adapter/fixtures/synthetic_assessment.v1.json
source_sha256: cb647c639188e0d1e752c8c842a649a0245a57849458f4cb26d9fc8b7a413abd
canonical_identity: canonical UTF-8 JSON with LF line endings
snapshot_path: not used for exact_d3_fixture
snapshot_sha256: not applicable to exact_d3_fixture
byte_identity: canonicalized byte identity (CRLF -> LF only)
```

The D4 snapshot remains available for historical foundation evidence and is
bound separately by its own `7a18...` canonical identity.

## Transaction identity erratum

The accepted Backend generator creates transaction IDs as `TX_` followed by
32 lowercase hexadecimal characters. The D4 schema and deterministic evidence
validator therefore use the exact pattern:

```text
^TX_[0-9a-f]{32}$
```

`REQ_` and `TRACE_` identities already match the accepted product identity
family and remain unchanged. No product transaction ID, Root contract, or
OpenAPI contract was modified.

## Closure boundary

This is an evaluation/fact-layer erratum. It does not amend or reclassify the
accepted D4-1 tag, does not alter D3 fixtures, and does not imply psychology
approval, real-student authorization, pilot readiness, or production enablement.
