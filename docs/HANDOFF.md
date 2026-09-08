# Handoff (draft, updated at integration time)

Pinned integration commit: _to be filled when the owner tags the repo_.

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

## Tests actually run

Filled in per track; see `STATUS.md` and the track docs for what is unit/mock evidence versus
real model and isolation evidence.

## Known limitations

- Mock mode is deterministic and model-free; it validates contracts and fail-closed paths only.
- Real inference and isolation status are documented in `docs/MODEL.md` and `docs/SECURITY.md`,
  including anything unverified or blocked on this machine.
