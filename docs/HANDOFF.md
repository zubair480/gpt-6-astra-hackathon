# Handoff (draft, updated at integration time)

Branch: `feat/private-reasoning-module`. Pin the commit at merge time.

## Commands

| Purpose | Command |
| --- | --- |
| Install | `uv sync --group dev` |
| Mock service | `uv run plva-pr-mock` |
| Fake core against a running service | `uv run plva-pr-fake-core` |
| Real local service | see `docs/MODEL.md` |
| Full test suite | `uv run pytest -q` |
| Contract drift check | `uv run python scripts/export_contracts.py --check` |

## API to core hook mapping

| Endpoint | Core hook (reference names) |
| --- | --- |
| `/v1/approve` | `Mediator.judge` → `SessionVault.grant_approval` (core mints and consumes the grant) |
| `/v1/compute` | `SemanticExecutor.execute` for `sort` / `select` (core resolves tokens, returns token-only result upstream) |
| `/v1/review-trace` | `Mediator.review_trace` after `should_review` fires (core applies the halt) |

## Tests actually run (2026-09-08, macOS 26.4, Apple M2, 8 GB)

| Suite | Result | Evidence type |
| --- | --- | --- |
| Operations, contracts, service, client (`tests/test_operations_*`, `test_contracts`, `test_service_*`, `test_client_*`) | 172 passed | unit + mock |
| Model adapter/backend/CLI with FakeBackend (`tests/test_model_*`) | 86 passed | unit |
| Live eval on Qwen3-1.7B-Q8_0 (`tests/test_model_live.py`) | approve 11/12, select 7/7, trace 4/4, sort 4/6 model-only (plain alphabetical sorts now take a deterministic path) | real model |
| Sandbox (`tests/test_sandbox_*`) | 48 passed; deny check 6/6 denied under sandbox-exec, 6/6 succeed in negative control | real enforcement (dev backend) |
| Agent demo (`tests/test_demo_*`) | 167 passed | unit + Playwright |
| End-to-end demo runs | see README "Agent demo" table | real GPT-6 Astra + real local model |

Latency: approve 1.7 s p50, compute 2 to 4 s, review-trace 1 s, model load 5 s, peak RSS 1.1 GB.

## Isolation status

| Backend | Status |
| --- | --- |
| macOS `sandbox-exec` (dev) | verified on this machine; instance-bound evidence; readiness flips to unverified when evidence is removed |
| NVIDIA OpenShell / NemoClaw (target) | launcher and policy written; UNTESTED here (no container runtime at time of writing) |

## Known limitations

- Mock mode is deterministic and model-free; it validates contracts and fail-closed paths only.
- Real inference and isolation status are documented in `docs/MODEL.md` and `docs/SECURITY.md`,
  including anything unverified or blocked on this machine.
