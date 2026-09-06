# Reference Validation Status

Status: `PENDING`

Execution: `NOT EXECUTED`

Reason: `R environment unavailable / not configured`

Reference: R `mirt` / `mirtCAT`

Checked: `2026-09-04`

## Why it was not executed

`R` and `Rscript` are not configured on the current machine. No reference
result is claimed and no reference comparison numbers are included.

## Required environment

- R runtime;
- `mirt` and `mirtCAT` packages at recorded versions;
- a matching unidimensional GRM item bank and prior/configuration;
- a reproducible script that exports theta, SE, selected item IDs and stop
  reason without using real student data.

## Follow-up

Run the same synthetic bank and aligned configuration through `mirtCAT`, then
compare theta, SE, item-selection decisions and stopping behavior. Record
package versions, R version, seed, tolerances, deviations and any model/API
translation. This validation must remain a reference comparison, not a
replacement for the provider adapter.
