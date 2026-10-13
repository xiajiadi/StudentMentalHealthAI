# NHANES P_DPQ adult research profile draft

Date: 2026-10-14. Status: `RESEARCH_ONLY / REVIEW_REQUESTED`; not approved for publication, operation, or psychological interpretation.

## Artifact

- Profile: `D:\Dev\datasets\psynova-public-research\research-profiles\nhanes-p-dpq-adult-mirt-20261014-v2\profile.json` (schema `psynova.research-profile.v2`, SHA-256 `8fd1a76718447b5401da3a9c380f1b2fd64bb5a8b22b60e148986a7f74ca7401`). Manifest SHA-256: `60f61130c15de2eb143010e3fa479c2bd8bc1c3ca4b267879ea70031ef691d63`.
- The item IDs, QIDs, and instrument item codes are the nine actual `DPQ010`–`DPQ090` variables. No IPIP100 or ItemInfo fields are invented. This draft is deliberately incompatible with the current v1 loader; a separately reviewed adapter-v2 change is required.

## Official wording and reuse basis

- The nine exact English Text fields and official response labels `0 Not at all`, `1 Several days`, `2 More than half the days`, `3 Nearly every day` were checked verbatim against the official [NCHS P_DPQ codebook](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/P_DPQ.htm). Retrieved HTML SHA-256: `579e0bcef4f8c2efc815f538b590cdbbf86f3d201309d8d8347d7b3dd299684d` (44395 bytes; first published June 2021; last revised listed `NA`).
- The [official PHQ Screeners page](https://www.phqscreeners.com/select-screener) states PHQ/GAD screeners and translations may be reproduced, translated, displayed, and distributed without permission. Retrieved HTML SHA-256: `192c0c7924c6005d60e391e255ddf2c4a9608b4649aef3f83e096c22db91eb64`. This is the item-text reuse basis; it is not approval for clinical adaptation, school use, CAT validity, or deployment.
- The [NCHS Data User Agreement](https://www.cdc.gov/nchs/policy/data-user-agreement.html) limits public-use data to statistical reporting and analysis and prohibits identifying or linking respondents. This profile contains wording and aggregate fit parameters, no response rows or person metadata. It does not assert unrestricted redistribution of NHANES data.
- CDC’s [Use of Agency Materials](https://www.cdc.gov/Other/imagereuse.html) notes third-party exceptions and calls for attribution and a no-endorsement disclaimer. The item text is attributed to NHANES/NCHS and no endorsement is implied. The specific item-reuse statement is from the PHQ official site.

## Population, fit and limits

- The public-use P_DPQ file contains adults 18+; the codebook target is 18–150. The response-only fit input has no observed ages. Youth 12–17 data are available only through NCHS Research Data Center and were not accessed. This is not an adolescent or high-school cohort.
- `a` and three ordered thresholds per item are copied directly from the existing mirt 1.47 one-factor graded fit summary, SHA-256 `becedd3437d18a1bdfbb2cf7e4af6f8fef84fd37ca740c68c0bd04b4eb1ae9f6`; parameter keys match the real DPQ variable names. Calibration CSV SHA-256 `4d7536cc669084b7ff815e47e5da556d3dc69e58254630e3c20b3d4874396c95`; response source SHA-256 `1a050397dc420e8eb685a43a5a7b481bb3ff61c38e3b5f4d6fb00988a15a2091`. Calibration used 5,551 nonempty rows from the 6,000-row split; 449 all-missing rows were retained then omitted as informationless. Partial missingness was retained; no complete-case filter or imputation was used. The original 800-row evaluation split was not fitted.
- All items use direct source codes 0–3, with no reverse-key transform. No score, norm, cut-point, diagnosis, crisis threshold, person theta, or response is included. Parameters are descriptive adult-sample research output, not approved CAT parameters.
- Candidate bounds are `min_items=9`, `max_items=9`, `se_threshold=null`, explicitly `NOT_APPROVED_RESEARCH_CANDIDATE`; all nine source variables are administered in this engineering configuration. No PHQ screening cut-point or clinical stopping rule is carried into CAT.
- `DPQ090` is retained as an ordinal response only, not a current crisis or suicide-risk gold label. Profile remains rights/specialist review pending and not operational.

No frozen bank, adapter, service, DB, school workflow, calibration/evaluation split, or fitted parameter file was changed.
