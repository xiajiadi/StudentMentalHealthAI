# D4 execution policy diagnosis

Assessment date: 2026-09-30. Formal worktree: `D:\Projects\StudentMentalHealthAI-d4-formal-run`. Branch and starting HEAD: `work/d4-3b-formal-run-integration` at `35f1ac86fe941aa015cd85163fda50ccddf6a1d7`.

## Finding

The historical `blocked by policy` message is confirmed at the Codex execution-tool boundary. The available output contains no Windows error code, child PID, rule identifier, command classification, or process-broker trace. It therefore does **not** identify which internal Codex policy component issued the rejection, and it does not establish whether Windows process creation was attempted.

The failure was not reproduced during the controlled probes on 2026-09-30. Direct Python, nested PowerShell and `cmd.exe` probes, direct `uv.exe`, direct Git, and the Codex CLI version check all exited with code 0. The finding is therefore “historical tool-level rejection; internal source unknown,” not a current reproducible block.

Classification:

- **Observed boundary: CLASS_C.** Codex execution returned `rejected: blocked by policy`. This establishes the tool boundary, not the specific sandbox broker or enforcement component.
- **Unresolved source: CLASS_H.** The historical response exposes no rule ID or lower-level diagnostic, and the current probes pass.
- **CLASS_A is a context risk, not the demonstrated cause.** The formal worktree has no project `.codex/config.toml` and no exact trusted-project entry was found. Project configuration is loaded only for trusted projects. However, the recorded historical rejection occurred while executing from the trusted main project, so this mismatch does not explain that event. [Codex configuration and trust](https://learn.chatgpt.com/docs/config-file/config-basic)
- **CLASS_B cannot be fully excluded.** The local system and user managed-requirements files checked were absent. Cloud-delivered Agent Security requirements are not inspectable from this execution context. Managed requirements outrank ordinary config and can enforce command rules. [Managed configuration](https://learn.chatgpt.com/docs/enterprise/managed-configuration)
- **CLASS_D is not evidenced as the source.** AppLocker had no effective rule collections; no relevant AppLocker or Code Integrity block events were found for the reviewed window. Kernel Code Integrity reports enforced status, so Windows policy is not categorically ruled out. Smart App Control was off, Defender was passive, and no applied Group Policy restriction was found.
- **CLASS_E is not supported as the proximate cause.** PowerShell policy was `RemoteSigned`; the harmless PowerShell probe completed successfully.
- **CLASS_F is unproven.** The historical output did not retain enough runner detail to show that wrapper syntax caused the rejection. The current wrapper and direct-executable probes both pass.
- **CLASS_G is unproven.** The evidence does not isolate a Codex regression from an unseen policy decision.

## Configuration and host evidence

- Codex Desktop package: `OpenAI.Codex 26.924.2738.0`.
- Bundled CLI: `codex-cli 0.158.0-alpha.2.1`.
- Active mode: local Codex Desktop. The current app execution context reports Full Access / `danger-full-access` and `approval_policy = never`; user config also records Windows sandbox mode `elevated`.
- The user-level config records `sandbox_mode = workspace-write`. The main project has a trusted project configuration for Full Access. The formal worktree has no `.codex/config.toml` and no matching trusted-project entry, so those project overrides do not carry over to it.
- Local `requirements.toml`, legacy `managed_config.toml`, and user `requirements.toml` were absent. Cloud-delivered managed requirements were not available for inspection.
- The reviewed user rules had no D4 PowerShell/Python/`uv`/Git deny rule. `codex execpolicy check` returned `matchedRules: []` for representative direct commands. The official checker reports matched rules and the strictest decision. [Rule semantics and checker](https://learn.chatgpt.com/docs/agent-configuration/rules)
- Host evidence: PowerShell `LocalMachine` execution policy `RemoteSigned`; AppLocker effective XML contained no rule collections; no relevant AppLocker 8003/8004 or Code Integrity 3076/3077 event was observed. DeviceGuard reported kernel Code Integrity status 2 (enforced) and user-mode Code Integrity status 0. Smart App Control registry state was 0 (off). Defender was passive with real-time protection disabled; Lenovo/Huorong security software was present. The machine was not domain-joined and `gpresult` showed no applied policy lines relevant to this event.
- Historical Codex session records contain the literal execution-tool rejection. They do not contain a broker trace or process identifier that would attribute it more narrowly.

## Controlled harmless probes

| Probe | Result | Process evidence |
|---|---|---|
| `C:\Python314\python.exe -c ...` | Exit 0 | Python printed `probe-ok`; child PID 27328 |
| Windows PowerShell `-NoProfile -Command ...` | Exit 0 | Child printed `probe-ok`; PowerShell PID 3524 |
| `cmd.exe /d /c echo probe-ok` | Exit 0 | Completed successfully; PID not returned by the probe |
| Direct `uv.exe --version` | Exit 0, `uv 0.12.3` | Completed successfully |
| Direct `git.exe --version` | Exit 0, `git version 2.49.0.windows.1` | Completed successfully |
| Direct Codex CLI `--version` | Exit 0, `codex-cli 0.158.0-alpha.2.1` | Completed successfully |

No formal service was started by these probes. They wrote no product data and issued no support request. Because the historical refusal is not reproducible, repeated command-form variations would add no evidence and are not justified.

## Decision

No local rule, managed policy, or Windows security setting was changed. The direct-launch and supervisor changes are normal evaluation process management, not a policy bypass: they use absolute executables, argument arrays, `shell=False`, and a fixed operation allowlist. The unresolved historical decision must be escalated with the original session trace if a repeatable rejection returns.

`Full Access` and `approval_policy = never` do not disable higher-priority managed requirements, command rules, the Codex execution broker, or host security controls. Configuration and requirements are separate layers, and managed requirements can constrain sandbox and command behavior. [Codex configuration precedence](https://learn.chatgpt.com/docs/config-file/config-basic), [managed requirements](https://learn.chatgpt.com/docs/enterprise/managed-configuration)

## Authorized alternative channels

- **Remote Desktop Commander:** not present in this task’s callable tools. It cannot be used or represented as connected here. An authorized installation/connection could provide interactive UI execution, but it is not needed for the currently passing probes and would not replace the project’s service lifecycle record.
- **OpenAI self-hosted executor:** current official documentation describes `codex exec-server`, local file and shell access, a restricted environment key, and an outbound WebSocket connection. The documentation reviewed does not explicitly confirm Windows support. It also requires a separate Agents API environment and credentials; no proof-of-concept was started. A future PoC would need a dedicated, least-privilege environment and explicit Windows compatibility verification. [Official self-hosted sandbox guide](https://developers.openai.com/api/docs/guides/agents-api/environments/self-hosted)
- **Project-local supervisor:** implemented as a persistent stdin/stdout JSONL process. It uses no listening port or shell endpoint and owns only the RAG service, evaluation observers, and Backend it starts. Existing MySQL, CAT, OPA, Safety, Runtime, and Ollama processes remain external and are not adopted or stopped.

The current evidence does not justify switching execution channels. It does justify retaining this diagnosis and the direct-launch path so a future reproducible refusal can be compared against a controlled baseline.
