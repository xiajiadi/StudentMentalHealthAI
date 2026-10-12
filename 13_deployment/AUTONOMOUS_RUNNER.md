# Project-scoped task recovery

`autonomous_runner.py` stores leases and evidence metadata in ignored `.autonomous/`.
It does not call a model, execute arbitrary commands, read credentials, change databases or manage services. Codex performs implementation and verification; an independently assigned reviewer inspects actual diffs and outputs. A recorded command label is a human/agent assertion, not proof that a process ran.

Run from the repository using its existing Python environment:

```powershell
.\09_backend\.venv\Scripts\python.exe .\13_deployment\autonomous_runner.py ready
.\09_backend\.venv\Scripts\python.exe .\13_deployment\autonomous_runner.py claim --task runner --owner root
.\09_backend\.venv\Scripts\python.exe .\13_deployment\autonomous_runner.py checkpoint --task runner --owner root
```

After real checks and a local commit, record a sanitized evidence file using `evidence --task ... --owner ... --evidence project-relative/report.md --outcome pass --command "verification-command-label"`; then `submit`. A different reviewer uses `review`, reruns relevant checks, records their own evidence and uses `done`. Evidence is bound to current attempt, file digest and Git HEAD. DONE requires a clean worktree apart from the two explicitly preserved baseline artifacts listed in the queue. New task changes must be committed before DONE. If HEAD changes, rerun and record the relevant evidence again.

Failed verification cannot be submitted. `reject` returns a reviewed task for changes; `fail` releases its active owner. Three claims exhaust its automatic retry allowance and leave it BLOCKED. This bounds attempts, not permission to repeat identical approaches. Reassess causes between attempts.

`stop` prevents new mutations except recovery/resume. `recover` requeues expired leases without evidence, or returns tasks with evidence to REVIEW. Kernel file locks release on process crash; the lock file remains intentionally and is not a stale ownership claim.

Queue edits fail closed until explicit `sync`: active leases must first be released, changed task definitions and their dependents lose previous acceptance. A baseline change requires separate reviewed migration; never delete local state to conceal prior failure.

Thread heartbeat scheduling is separate from this lease Runner. The current
schedule and shutdown deadline are recorded in `CURRENT_STATE.md` and
`SHUTDOWN_CHECKPOINT.md`; inspect the saved automation before changing it.
This chat has performed actual continuations, but those do not prove an
independent persistent Runner or automatic recovery across an OS reboot.
The machine/app and project must remain available. User stop/pause requests
take precedence. Do not implement OS power changes, global scheduled services
or a recursive prompt loop as a substitute.

Verification:

```powershell
.\09_backend\.venv\Scripts\python.exe -m unittest discover -s 13_deployment/tests -p test_autonomous_runner.py -v
```

The tests use temporary directories, disposable Git repositories and owned subprocesses. They do not validate the product's database, AI or browser workflows.
