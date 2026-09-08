# PLVA private reasoning module

Optional, loopback-only local reasoning service for the [PLVA](https://github.com/dael-amz/browser-agent-privacy-layer)
privacy core. It answers three narrow questions so private data never has to be shown to the
cloud model:

| Endpoint | Question | Result |
| --- | --- | --- |
| `POST /v1/approve` | May this token be resolved into this tool argument at this destination? | `approve` with a clamped scope, or `deny` |
| `POST /v1/compute` | Sort or select over explicitly supplied private values | input tokens only, never values |
| `POST /v1/review-trace` | Given a value-free event trace, continue, warn, or halt? | `continue` / `warn` / `halt` |

The service **recommends**; the PLVA core enforces. It cannot grant itself access, change
policy, execute actions, read the vault, or stop the agent. It never calls a cloud model.

## Status

| Track | State |
| --- | --- |
| Frozen v1 contracts (`contracts/v1/`) | done: JSON Schema 2020-12, OpenAPI 3.1, examples, reason codes |
| Deterministic mock service (`plva-pr-mock`) | done: loopback, per-launch bearer credential, fixed error bodies, replay guard |
| Thin stdlib client + fake core | see `docs/INTEGRATION.md` |
| Real local inference (Qwen via llama.cpp) | see `docs/MODEL.md` |
| Isolation (NemoClaw/OpenShell) and deny evidence | see `docs/SECURITY.md` |
| Agent demo (`plva_agent_demo`) | done: Playwright browser, DOM redaction, vault, GPT-6 Astra planner, operator UI |
| Final handoff | `docs/HANDOFF.md` |

`STATUS.md` tracks owners, checks, and blockers.

## Quickstart (mock, no model, no credentials)

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --group dev
uv run plva-pr-mock            # binds 127.0.0.1:18555, writes .plva-pr/credential (0600)
```

In another shell:

```bash
CRED=$(cat .plva-pr/credential)
curl -s -H "Authorization: Bearer $CRED" http://127.0.0.1:18555/v1/readiness
curl -s -H "Authorization: Bearer $CRED" -H 'Content-Type: application/json' \
  --data @contracts/v1/examples/approve-request.json http://127.0.0.1:18555/v1/approve
```

Mock mode identifies itself (`"mode": "mock"`, `"ready_for_private_values": false`). The
client refuses to send real private values to it unless explicitly overridden for tests.

## Agent demo: URL + task in, private run out

`src/plva_agent_demo` is a standalone showcase of the whole loop. The cloud planner
(OpenAI `gpt-6-astra`) sees only redacted frames and a value-free token manifest; this module
answers approve / compute / review-trace locally.

```bash
cp -n .env.example .env            # set OPENAI_API_KEY; OPENAI_MODEL=gpt-6-astra
uv sync --group dev --group demo && uv run playwright install chromium
uv run plva-pr-mock                # or the real local model: see docs/MODEL.md + sandbox/start.sh
uv run python -m plva_agent_demo.ui --port 3000   # open http://localhost:3000
```

Measured on 2026-09-08 (M2, 8 GB) against the real local Qwen3-1.7B service with verified
isolation (macOS `sandbox-exec` dev backend):

| Task on the synthetic Acme page | Steps | Outcome | Private-reasoning call |
| --- | --- | --- | --- |
| Paste my Acme API key into Connect analytics and click Connect | 4 | done, key typed locally only | approve → POLICY_MATCH, 2.5 s |
| List the team members sorted alphabetically by name | 3 | done, correct order as tokens | compute/sort → COMPLETED, 3.9 s |
| Find a phone number on mozilla.org/contact (real site) | 8 | no number exists; agent stopped at the step cap without inventing one | none |

GPT-6 Astra step latency 3 to 5 s; redaction 40 to 100 ms; 0 leaks over every outbound body.

## Tests and checks

```bash
uv run pytest -q
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy
uv run python scripts/export_contracts.py --check   # frozen contracts match the models
```

## Contract rules (v1)

- Every request carries `schema_version: "1.0"`, `session_id`, `request_id`; they are echoed back
  and are correlation data only, never authorization.
- Unknown fields, wrong types, oversize bodies (> 64 KiB), malformed tokens, and duplicate tokens
  are rejected with a fixed body `{"schema_version":"1.0","error_code":"SCHEMA_INVALID"}`.
  Rejected input is never echoed.
- A repeated `(session_id, request_id)` is rejected with `409 DUPLICATE_REQUEST`.
- Every endpoint except `GET /health` requires `Authorization: Bearer <per-launch credential>`.
  Requests with an `Origin` header or an unexpected `Host` are refused.
- Approve: missing policy, unverified destination, blocked class, origin/field/tool outside the
  allowlists are denied deterministically before any reasoning runs. A recommendation can only
  shrink TTL and use count; it can never widen token, tool, path, origin, or field.
- Compute: 2 to 40 items, 500 chars per value, 500 chars of instruction. Sort returns an exact
  permutation of the input tokens; select returns a unique subset with the requested count.
  Anything else is `status: "error"`, `tokens: []`.
- Review-trace: `blocked_class_attempt` (when the policy says so), `destination_mismatch`,
  `token_invalid`, or repeated denials inside the window halt regardless of the backend.
- Values and raw completions live only in request-scoped memory. Nothing is logged.

Reason codes are fixed and listed in `contracts/v1/reason-codes.json`.

## Layout

```text
contracts/v1/                 frozen schemas, openapi.json, examples/, reason-codes.json
src/plva_private_reasoning/
  contracts.py                runtime twin of the schemas (pydantic, extra=forbid)
  operations/                 approve / compute / review_trace with deterministic guards
  service/                    loopback transport, auth, replay guard, fixed error bodies
  model/                      local inference adapter (llama.cpp) and constrained parser
  client/                     stdlib client, fake core example
sandbox/                      isolation policy, launcher, empirical deny checks
tests/                        unit, contract, service, client, model, sandbox
docs/                         INTEGRATION.md, SECURITY.md, MODEL.md, HANDOFF.md
scripts/export_contracts.py   regenerates and drift-checks contracts/v1
```

## Provenance

Built during the GPT-6 Astra hackathon as new work. Architecture and lessons are drawn from
the PLVA reference (`reference/browser-agent-privacy-layer`, commit `467a452`); no reference
code is vendored. No model weights, credentials, or private traces are committed.
