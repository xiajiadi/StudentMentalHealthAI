# adaptivetesting Compatibility Report

Date checked: `2026-09-04`

## Conclusion

`adaptivetesting==1.2.1` is usable for the CAT V0.1 PoC in the isolated
Python 3.14.6 environment at `01_cat-engine/.venv314`. The adapter has been
implemented against observed public exports and the GRM path has been run
locally.

The package metadata declares `Requires-Python: >=3.12`, but the installed
source imports `deprecated` from Python's `warnings` module. That symbol is
not present in Python 3.12.12, so importing the package fails there before any
CAT code runs. Python 3.14.6 provides the symbol and the package imports and
executes successfully. The project therefore pins the verified Round 1
environment to Python `>=3.14,<3.15` rather than patching third-party source
or weakening the global Python installation.

## Observed package facts

- Package: `adaptivetesting`
- Version: `1.2.1`
- Source: PyPI wheel installed into the project-local environment
- Declared Python requirement: `>=3.12`
- Declared runtime dependencies: `numpy>=2.1.0`, `pandas>=2.3.0`,
  `scipy>=1.15.0`, `tqdm>=4.66.0`, `matplotlib>=3.10.0`,
  `numdifftools>=0.9.42`
- License file: Mozilla Public License 2.0 (MPL-2.0)
- License review: no Round 1 engineering blocker identified; release
  distribution must retain the MPL-2.0 notices and receive the project's
  normal license review.

## Public API inspected

The installed package exports and the adapter uses:

- `TestItem` and `ItemPool` for item conversion;
- `TestAssembler` with `simulation=False` for online orchestration;
- `ExpectedAPosteriori` and `NormalPrior` for EAP estimation;
- `maximum_information_criterion` for MFI item selection;
- `item_information_function` for the observable selection score;
- `generate_response_pattern` for model-based synthetic responses;
- `StoppingCriterion.SE` and `StoppingCriterion.LENGTH` in the package's
  native simulation API.

The inspected constructors and functions include:

```text
ItemPool(test_items, simulated_responses=None)
TestAssembler(item_pool, simulation_id, participant_id, ability_estimator,
              estimator_args, item_selector, item_selector_args,
              model_type, initial_ability_level, simulation)
ExpectedAPosteriori(response_pattern, items, prior,
                    optimization_interval, model)
maximum_information_criterion(items, ability, model)
generate_response_pattern(ability, items, model, seed)
```

The installed source contains GRM and GPCM polynomial model implementations.
Round 1 uses the public GRM/EAP path with a five-category synthetic item bank.
The package does not return a selection score from MFI directly; the adapter
computes the same package information function at the selected theta and
records that value. A provider-specific score remains nullable in the
provider-neutral trace contract if a future adapter cannot expose one.

## Installation and verification

The environment was created under the project on D: and installed with:

```powershell
uv venv --python C:\Python314\python.exe .venv314
uv pip install --python .venv314\Scripts\python.exe `
  "adaptivetesting==1.2.1" "jsonschema>=4.23,<5" "pytest>=8,<9"
```

Observed checks:

```text
Python 3.12.12: import failure, warnings.deprecated is absent
Python 3.14.6: import success
GRM response generation: success
GRM EAP estimate and SE update: success
MFI selection: success
```

No R or `Rscript` executable was found on this machine during the check.

