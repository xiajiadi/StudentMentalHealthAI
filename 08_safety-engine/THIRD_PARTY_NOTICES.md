# THIRD-PARTY NOTICES

This module uses open-source software as isolated implementation dependencies.
The listed versions are the versions resolved in the Round 1 Python 3.12
environment on 2026-09-05. Transitive dependency licenses should be refreshed
when the lock file changes.

| Component | Resolved / pinned version | License | Source |
|---|---:|---|---|
| NVIDIA NeMo Guardrails | 0.24.0 | Apache-2.0 | https://github.com/NVIDIA-NeMo/Guardrails/blob/develop/LICENSE.md |
| Qwen3Guard-Gen-0.6B | revision fada3b2f655b89601929198343c94cd2f64d93cc | Apache-2.0 | https://huggingface.co/Qwen/Qwen3Guard-Gen-0.6B |
| Open Policy Agent | v1.20.2 Windows amd64 binary | Apache-2.0 | https://github.com/open-policy-agent/opa |
| Microsoft Presidio Analyzer | 2.2.364 | MIT | https://github.com/microsoft/presidio |
| Microsoft Presidio Anonymizer | 2.2.364 | MIT | https://github.com/microsoft/presidio |
| FastAPI | resolved in uv.lock | MIT | https://github.com/fastapi/fastapi |
| Pydantic | resolved in uv.lock | MIT | https://github.com/pydantic/pydantic |
| httpx | resolved in uv.lock | BSD-3-Clause | https://github.com/encode/httpx |
| PyYAML | resolved in uv.lock | MIT | https://github.com/yaml/pyyaml |
| jsonschema | resolved in uv.lock | MIT | https://github.com/python-jsonschema/jsonschema |
| PyTorch | resolved in uv.lock | BSD-3-Clause | https://github.com/pytorch/pytorch |
| Transformers | resolved in uv.lock | Apache-2.0 | https://github.com/huggingface/transformers |

The project must retain each upstream license and notice when distributing a
build. Model files are cached outside this repository on D: and are not
checked into the public project. No cloud provider or remote moderation API is
a runtime dependency.

## Internal policy artifacts

The Rego policies and crisis templates in this module are project-authored
artifacts. Crisis templates are synthetic placeholders, are marked
PENDING_PSYCH_REVIEW, and are not approved clinical or emergency content.

