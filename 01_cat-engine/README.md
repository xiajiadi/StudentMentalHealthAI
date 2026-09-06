# CAT Engine V0.1

This directory contains the Round 1 Measurement Layer baseline for
StudentMentalHealthAI. It runs a versioned synthetic GRM item bank through an
`adaptivetesting` adapter, records a structured CAT trace, maps the completed
session to the frozen `assessment.v1` Contract, and runs reproducible batch
simulation.

All fixtures, parameters and results are:

`NOT FOR PSYCHOLOGICAL INTERPRETATION`  
`DEMO / ENGINEERING USE ONLY`

The item bank does not represent a validated instrument, a target population,
a clinical scale, or a risk rule. Formal psychometric decisions remain
`PENDING_PSYCHOMETRIC_CONFIRMATION`.

## Environment

The verified local environment is Python 3.14 and the project-local isolated
environment `.venv314`. `adaptivetesting==1.2.1` is used only behind
`AdaptiveTestingProvider`. See
`ADAPTIVETESTING_COMPATIBILITY_REPORT.md` for the Python 3.12 compatibility
finding and the public API inspection.

## Run

From this directory:

```powershell
& .venv314\Scripts\python.exe -m pytest
```

The simulation command used for the Round 1 acceptance run is documented in
the acceptance report and writes JSON, CSV and Markdown outputs under
`reports/`.

## Architecture

`CATService` and `Session` depend on `CATProvider`; the provider adapter owns
all `adaptivetesting` types. The assessment mapper accepts a risk snapshot
from outside CAT and never calculates risk or an interpretation band.

