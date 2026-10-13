# NHANES P_DPQ response-only GRM baseline

Date: 2026-10-14. Status: `RESEARCH_ONLY / CONTROLLER_REVIEW_REQUESTED`.

This is an isolated one-factor graded-response model (GRM) research fit for nine NHANES public-use response columns. It does not approve an item bank, CAT parameters, clinical interpretation, crisis classification, school use, or publication. No online bank, DB, service, CAT math, or product code was changed.

## Source and limits

- Source: [NCHS P_DPQ codebook](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/P_DPQ.htm) and [public-use XPT](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/P_DPQ.xpt), covering the adult public-use file (18+) in NHANES 2017–2018 plus 2019–March 2020 pre-pandemic data. The codebook target is 18–150; this is not an observed age range in the response-only extract, which contains no ages. It is not an adolescent, high-school, university, or school cohort.
- The response-only staged CSV has 8,965 rows and SHA-256 `1a050397dc420e8eb685a43a5a7b481bb3ff61c38e3b5f4d6fb00988a15a2091`. The upstream manifest SHA-256 is `73827fd3be8a353ae6ecf97ff52982cfe57a96da220d0b33878361e80f7ceec5`.
- No dataset-specific Creative Commons license was identified in the source manifest. The output remains on D: for isolated research with attribution; this work does not authorize redistribution of transformed response rows.
- No demographic variables or survey weights were included. These data cannot establish US population norms or represent school or university students.
- The response-only data contains no item text. This fit provides no clinical, diagnostic, risk, or crisis labels; any DPQ090 response is not treated as a current crisis indicator.

The upstream source manifest records the following aggregate missing-category counts. Values 7 and 9 are distinct source categories; `missing` is the source blank count.

| Item | Refused (7) | Don't know (9) | Blank |
|---|---:|---:|---:|
| DPQ010 | 4 | 6 | 657 |
| DPQ020 | 2 | 5 | 659 |
| DPQ030 | 3 | 5 | 659 |
| DPQ040 | 4 | 4 | 660 |
| DPQ050 | 2 | 4 | 660 |
| DPQ060 | 3 | 6 | 661 |
| DPQ070 | 2 | 3 | 661 |
| DPQ080 | 2 | 5 | 661 |
| DPQ090 | 2 | 4 | 663 |

## Response splits

The existing response-only importer generated seed `20261014` splits by reservoir sampling without replacement, then shuffled the selected records. It retained all 6,000 calibration and all 800 evaluation rows, including incomplete and all-missing records. The manifest declares disjoint splits and writes no source row identifiers.

| Split | Rows | Complete 9-item rows | Partial missing rows retained | All-missing rows retained |
|---|---:|---:|---:|---:|
| Calibration | 6,000 | 5,529 | 22 | 449 |
| Evaluation | 800 | 745 | 1 | 54 |

The evaluation complete-row count is aggregate QA only. No rows were replaced to raise the count, no imputation was performed, and evaluation responses were not fitted. The calibration fit used every partially observed record (5,551 nonempty records); its 449 all-missing records stayed in the input and were omitted by mirt as informationless patterns.

Codes 7 (refused) and 9 (don't know) were converted to empty/NA cells by the importer, as were original blanks. The split-level data cannot distinguish those three original missing types. The split manifest preserves their source-level per-item aggregates and documents this loss of split-level distinction.

## Fit and diagnostics

The isolated run used R 4.6.1 and `mirt` 1.47: one-factor graded GRM, EM, Gaussian `N(0,1)`, 41 quadrature points, `SE=FALSE`, maximum 1,000 cycles. It fitted calibration only.

- Converged in 76 EM iterations using 5,551 nonempty calibration records and 36 freely estimated parameters.
- Log likelihood: `-30361.645410`; AIC: `60795.290820`; BIC: `61033.673222`.
- All 9 items had positive observed support in all four categories (0–3), finite discrimination and finite ordered thresholds. This category support does not establish parameter stability or validity; DPQ090 categories 2 and 3 were sparse in calibration (38 and 27 observations).
- AIC/BIC and item parameters are descriptive model output for this split, not a selection rule or approval criterion. Standard errors and item-fit statistics were not estimated.
- The fit warning `data contains response patterns with only NAs` was retained. It corresponds to the 449 all-missing calibration records kept in the input; no complete-case filter was applied.

Item discrimination, thresholds, per-item category counts/support, convergence details, AIC/BIC, warning, and provenance are in the external fit summary. No person theta, individual score, response row, or respondent identifier was written.

## External artifacts and hashes

All split and fit artifacts are outside the repository under `D:\Dev\datasets\psynova-public-research\derived\nhanes-dpq-20261014-v1\`.

- `manifest.json` — split source/sampling/output hashes, upstream refusal/don't-know/blank aggregates, and aggregate completeness QA; SHA-256 `17f73b25173206e28e7342448eb9a106a539d3d65886e513483bc8b94b8e361f`.
- `run-manifest.json` — run identity and source, split, script, runtime, package-lock, and fit hashes; SHA-256 `20c75a2faf3420173fe7fa529b757755ca5b617310ee06a4d778a5128eae0fbd`.
- Split CSV hashes: calibration `4d7536cc669084b7ff815e47e5da556d3dc69e58254630e3c20b3d4874396c95`; evaluation `0a2e2f825cc450f9f53ce403e30c5979fb57f2e4e239b6dedbb2afaa79ba9669`.
- `mirt-nhanes-dpq-20261014-r1/fit-summary.json` — fit summary and item-level parameters; SHA-256 `becedd3437d18a1bdfbb2cf7e4af6f8fef84fd37ca740c68c0bd04b4eb1ae9f6`.
- `mirt-nhanes-dpq-20261014-r1/fit_nhanes_dp_q_grm.R` — exact fit script; SHA-256 `2145704a0ea0c4ab80840122936488913e79555f346b4f9836c2c1e241834a96`.
- Importer SHA-256: `901d09e23f95c58ebd5f3d5cb2676822df25f1a2c6b89fe4634c592fa4ea99e2`. Audit helper SHA-256: `7efe045f2dbb885e151681a39e607d2fd7121c82ffa6549afcff039978a12bd5`.
- Rscript SHA-256: `3ad097e10d867e09eb7e54d8ed1f8ef933779b82be56482a04a27d65536d15f9`. The isolated CRAN Windows package lock SHA-256 is `19d53d2083d9535b756448a733259f112494a0d467efdea42f33385ba5282e0a`.

## Review boundary

This is a converged numerical baseline on an adult public-use sample. It does not show that the DPQ items or parameters are suitable for adolescents, high-school students, university students, school delivery, or individual decisions. It is not a validated CAT bank and must not be loaded into the online bank. Any future professional review, rights decision, psychometric validation, and population-specific study remain separate work.
