# IPIP100 Extraversion research profile candidate

Date: 2026-10-14. Status: `RESEARCH_ONLY / ADAPTER_VALIDATION_CANDIDATE`.

An external-D, response-free profile was assembled for testing the research-session adapter's profile loader. It contains the official English IPIP Extraversion 20-item key, exact SAPA item crosswalk, key direction, and research-only mirt item parameters. It is not a published bank or approved scale and must not enter the online item bank.

## Profile

- Profile: `ipip100-extraversion-sapa-mirt1.47-20261014-r1`
- Instrument identifier: `IPIP100_B5_E_EXTRAVERSION_20_RESEARCH`
- Dimension: Extraversion; one-dimensional GRM only.
- External file: `D:\Dev\datasets\psynova-public-research\research-profiles\ipip100-extraversion-sapa-mirt-20261014-r1\profile.json`
- Profile SHA-256: `cf49329d2848f5fc4ba38f29e39144b79e7363e0725a3381d0b0273bab235f10`
- Manifest SHA-256: `74e2e9b026b72ce6fa5913527a554db152d7f200e44532df60d9e3ee70145690`

The profile has 20 items in the official key's order: ten positive-keyed and ten reverse-keyed. Every English stem matches the official IPIP Factor I 20-item key and the staged SAPA `ItemInfo373` / crosswalk entry. Each item carries its `qid`, `B5:E` IPIP100 factor code, source locator, keyed `a` discrimination and five thresholds, and mirt fit locator.

## Response labels and scoring direction

The fitted response values are `1..6`. `category_labels` is explicit JSON `null`, with status `unconfirmed_for_sapa_six_category_responses`: the SAPA response-only manifest records numeric codes but no text labels. The official IPIP scoring page documents five response labels; it does not confirm labels for this six-category SAPA dataset, so those five labels are not mapped onto six categories. No Chinese item translation is included.

The mirt parameters are on the positively keyed Extraversion response scale. Positive items use the raw response; reverse-keyed items use `7 - response` before converting categories to a zero-based index. The adapter may use that transform for mathematical loader validation only; the profile does not authorize a response collection study or a score interpretation.

## Source, rights, and population

- The official [IPIP Big-Five Factor Markers key](https://ipip.ori.org/newBigFive5broadKey.htm) defines the 20-item Extraversion positive and reverse key blocks. The official [IPIP permission page](https://ipip.ori.org/newPermission.htm) says its items and scales are public domain and available for commercial or non-commercial use.
- Data source: SAPA-Project, *Selected personality data from the SAPA-Project: 18aug2010 to 08dec2013*, version 3.0, DOI [10.7910/DVN/C40K1U](https://doi.org/10.7910/DVN/C40K1U), license `CC0-1.0` as recorded in the staged Dataverse source manifest.
- The population boundary in the source manifest is self-selected SAPA Project online respondents. The split excludes demographics and is not a school, high-school, university-representative, clinical, or diagnostic sample.
- Profile rights are recorded as source rights plus a research-only candidate. No rights or publication approval is inferred for an operational instrument.

## Fit provenance and limits

The referenced fit is mirt 1.47, one-factor graded GRM, EM, Gaussian `N(0,1)`, 41 quadrature points, up to 1,000 cycles, `SE=FALSE`, using 10,000 calibration rows. It converged in 90 iterations; 9,788 nonempty patterns were used, while 212 all-missing rows were retained in the input and omitted as informationless. Ten reverse-keyed items were recoded with `7 - response`; no imputation or complete-case deletion was used. Mirt warned `data contains response patterns with only NAs`; the warning is preserved in the fit artifact.

This fit has no standard errors and does not validate the item parameters, translations, school suitability, norms, or individual interpretation. It contains no response rows, person theta, individual score, clinical or crisis label. It is separate from the NHANES DPQ work and does not mix personality and clinical questions.

## Hash-bound provenance

The profile manifest records the exact expected profile SHA-256 and hashes for the downloaded official key, scoring and permission pages, `sapa-ItemInfo373.tab`, exact item crosswalk, source/split manifests, calibration file, fit result, mirt script, and package lock. The mirt fit JSON SHA-256 is `4bac0b2f903af047c28426493c279b3b0ab067fe8ab9de89472f6e5a35864980`.

No respondent rows or person-specific estimates are copied into the repository; only aggregate provenance and metadata are summarized here. The external candidate does not change approval gates or online-bank state.

## Historical SAPA response-scale source review

Historical SAPA sources corroborate the six labels as `1 Very Inaccurate`, `2 Moderately Inaccurate`, `3 Slightly Inaccurate`, `4 Slightly Accurate`, `5 Moderately Accurate`, and `6 Very Accurate`: the author-maintained `psych` manual documents them for its Spring 2010 SAPA sample, and the Condon–Revelle paper documents the same options in a later 2013–2014 SAPA collection. The target C40K1U Dataverse metadata, `ItemInfo373.tab`, and its DDI metadata do not bind text labels to the numeric response variables; thus the immutable candidate profile retains `category_labels: null`. The precise historical instruction sentence and any phase-specific UI differences remain unconfirmed. See the [external source review](D:/Dev/datasets/psynova-public-research/research-profiles/sapa-response-scale-source-review-20261014-r1/source-review.md).
