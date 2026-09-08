# STATUS

| Track | Owner | Current task | Completed checks | Blockers |
| --- | --- | --- | --- | --- |
| Contracts + transport (lead) | lead | operations tests, README, handoff docs | ruff, mypy strict, contract drift check | none |
| Client + verification | agent: client | thin client, mock/disabled behavior, contract + service tests, fake core example | pending | none |
| Local reasoning | agent: model | llama.cpp adapter, constrained output parser, provisioning script, synthetic eval | pending | model weights not downloaded (needs explicit approval) |
| Isolation | agent: isolation | NemoClaw/OpenShell policy, launcher, empirical deny checks | pending | platform availability unknown |

File ownership (do not edit outside your track without lead approval):

- lead: `src/plva_private_reasoning/{contracts,reason_codes,cli}.py`, `service/`, `operations/`, `contracts/`, `scripts/export_contracts.py`, `pyproject.toml`, `tests/test_operations_*.py`, `README.md`, `STATUS.md`, `docs/HANDOFF.md`
- client: `src/plva_private_reasoning/client/`, `tests/test_client_*.py`, `tests/test_service_*.py`, `tests/test_contracts.py`, `examples/`, `docs/INTEGRATION.md`
- model: `src/plva_private_reasoning/model/`, `scripts/provision_model.*`, `tests/test_model_*.py`, `docs/MODEL.md`, `[project.optional-dependencies] local` in pyproject
- isolation: `sandbox/`, `tests/test_sandbox_*.py`, `docs/SECURITY.md`

Next integration handoff: mock service + client + fake-core example runnable end to end.
