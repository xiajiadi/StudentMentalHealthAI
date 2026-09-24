# D4 Slice 2 · Acceptance Publication

Published: 2026-09-24

## Controller decision

**D4 Slice 2 · Deterministic Trust & Safety Regression R1** is
**FULL PASS / CONTROLLER ACCEPTED** within its synthetic engineering scope.

- Accepted local annotated tag: `d4-slice2-r1-accepted`
- Accepted commit: `2ead2fd6a131f34c2cc7cb71274aed04ce935053`
- Initial P0 evidence commit: `42c2fc8e39dc3f2c571c7760a91b6c16d0110ed2`
- Tested repair implementation commit: `5400831a6df8ee46d1df421ddc596bbfe37366c0`
- Machine evidence closure commit: `a63d636482e5a787f5ab5c4bf8598356f79bc1d9`
- Final documentation closure commit: `2ead2fd6a131f34c2cc7cb71274aed04ce935053`
- Detailed deterministic evidence:
  `D4_SLICE2_DETERMINISTIC_REGRESSION_EVIDENCE.md`

## Preserved finding

D4E-26 discovered that a foreign existing sensitive assessment and an unknown
assessment produced distinguishable public denial envelopes. The initial
failure remains preserved in the initial evidence record and commit above. The
minimal Backend repair made both public envelopes return HTTP 404 with
`resource_not_found` and `assessment not found`, while retaining distinct
internal audit reasons. The repair is included in the accepted D4-2 scope.

The historical deterministic evidence retains its original
`READY_FOR_CONTROLLER_REVIEW / D4-2R REPAIR CLOSURE CANDIDATE` status. This
publication records the later Controller acceptance; it does not rewrite the
historical run as accepted when it was generated.

## Scope boundary and next slice

D4-2 acceptance covers synthetic engineering evidence only. It does not imply
psychology or psychometric validity, legal/consent or rights approval,
real-student authorization, pilot readiness, clinical certification, or
production enablement. D4 overall remains **IN_PROGRESS / NOT_ACCEPTED** and
real pilot remains **BLOCKED**.

The current slice is **D4-3A · Citation Support & Safe Utility Evaluation
Foundation**. Evaluation labels remain drafts until approved by the Project
Controller or a designated human reviewer. D4-3A does not itself accept D4
overall or authorize D4-3B product generation.
