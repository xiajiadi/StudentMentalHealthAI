# Pyright Reconciliation — Runtime Reconstruction R1

Date: 2026-09-07  
Tool: Pyright 1.1.411  
Baseline: `66cb0e8a5eeecd05c8c5c1a3d0a3018a63920772`  
Candidate at closure start: `6293144d921ea43c298327bd6a5063cd84e13b8b`

## Reconstructed scope

Command:

```text
uvx pyright --pythonpath .venv\Scripts\python.exe --outputjson src\llm_runtime tests\test_runtime_reconstruction.py
```

Result: `PASS` — 26 files analyzed, 0 errors, 0 warnings, 0 information
diagnostics. The reconstructed Runtime package and its dedicated tests have no
current Pyright findings.

## Candidate-versus-baseline differential

The same command and candidate project environment were run from the detached
baseline worktree and the candidate worktree over `src\llm_runtime tests`.
Diagnostics were normalized by relative file, rule, and message.

| Scope | Errors | Warnings | Files analyzed |
|---|---:|---:|---:|
| Baseline | 41 | 0 | 30 |
| Candidate | 20 | 0 | 37 |
| New candidate findings | 0 | 0 | — |
| Resolved findings | 21 | — | — |

The 20 remaining candidate findings are confined to legacy test typing in
`tests/integration/test_ollama_integration.py`, `tests/test_provider_ollama.py`,
and `tests/test_runtime_service.py`. They do not occur in reconstructed source
or `tests/test_runtime_reconstruction.py`, and they are not new relative to the
baseline differential.

No `pyrightconfig.json` exists for `06_llm-runtime`; the command and Python
environment are therefore recorded explicitly rather than inferred from a
module configuration.
