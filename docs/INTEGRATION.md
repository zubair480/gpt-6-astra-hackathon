# Integrating the private reasoning module into the PLVA core

This module is an optional, separately launched loopback service plus a thin Python client.
The core talks to it through three frozen v1 APIs (`contracts/v1/`). Nothing in the core needs to
import the service, FastAPI, or any inference library: the client is standard library only and
returns the pydantic models from `plva_private_reasoning.contracts` (or plain dicts via
`.model_dump()` if you would rather not depend on pydantic at your call sites).

The service **recommends**. The core still mints and consumes grants, re-verifies destinations
immediately before execution, decides which computations are permitted, and applies halts.

## 1. Start the mock (no model, no cloud credential)

```sh
uv sync
uv run plva-pr-mock                 # binds 127.0.0.1:18555, writes .plva-pr/credential (mode 0600)
```

The mock prints `MODE=mock` and states that it is not ready for private values. It is
deterministic: policy match approves with the tightest scope, sort is case-insensitive value order,
select takes the first `select_count` of that order, trace review applies the deterministic floor.
Stop it with Ctrl-C; the credential is regenerated on every launch.

Overrides: `--host` (loopback only), `--port`, `--runtime-dir`, or the matching
`PLVA_PR_HOST` / `PLVA_PR_PORT` / `PLVA_PR_RUNTIME_DIR` environment variables (see `.env.example`).

## 2. Construct the client

```python
from plva_private_reasoning.client import PrivateReasoningClient, load_credential

client = PrivateReasoningClient(
    base_url="http://127.0.0.1:18555",
    credential=load_credential(".plva-pr/credential"),   # per-launch bearer token
    timeout_seconds=10.0,                                 # hard deadline per call, no retries
    enabled=True,                                         # False = feature off, no network at all
    allow_mock_for_private_values=False,                  # keep False in the real core
)
readiness = client.readiness()      # ReadinessResponse | None
```

Rules the client enforces on your behalf:

* Sends only `Authorization: Bearer <credential>`, `Accept`, and `Content-Type: application/json`.
  No `Origin` header (the service rejects any). The `Host` header is derived from `base_url`, which
  the service checks, so use the same host:port the service was bound to.
* Validates the request against the contract before it leaves the process. A request that does not
  satisfy the contract raises `ClientError` with a fixed message; the offending body is not attached
  as the message, cause, or context.
* Validates the response against the contract and requires the echoed `schema_version`,
  `session_id`, and `request_id` to match the request. Anything else is treated as a failure.
* Ignores a response that arrives after the call's deadline, even if it is valid.
* Never retries anything. If you need to ask again, use a new `request_id`; the service rejects a
  replayed `(session_id, request_id)` with `409 DUPLICATE_REQUEST`.
* `client.last_failure` is a fixed, value-free diagnostic for the most recent failed call
  (`unreachable`, `timeout`, `late`, `malformed`, `mismatch`, `oversized`, `not_ready`,
  `disabled`, `http_<status>`). Safe to log. Never log request bodies.

The credential file must stay outside the cloud agent's reach: the Astra-facing runtime must not be
able to read it or to call this service directly.

## 3. Mapping the three APIs to core hooks

| Core hook | API | Send | Get back | Core still does |
| --- | --- | --- | --- | --- |
| Approval bridge: "may token `X` be resolved into this field?" | `client.approve(req) -> ApproveResponse` (`POST /v1/approve`) | token, PII class, tool, argument path, runtime-verified destination, task context, the user's policy. **No secret value.** | `decision` approve/deny, fixed `reason_code`, `scope` (null on deny) | Treat `scope` as an upper bound; mint the grant yourself with `ttl <= scope.ttl_seconds`, `uses <= scope.max_uses`; recheck the destination right before execution; consume and dedupe grants. |
| Private computation: semantic sort/select over vault values | `client.compute(req) -> ComputeResponse` (`POST /v1/compute`) | operation `sort`/`select`, instruction, 2-40 `{token, value}` items (values <= 500 chars), optional `select_count`. Only the values this computation needs, never the vault. | `status` ok/denied/error, `tokens` (a permutation for sort, a unique subset for select), fixed `reason_code` | Check that local computation is permitted for every value first; rate-limit repeated probing; map tokens back to values yourself. The response never carries values. |
| Behaviour review: continue / warn / halt after N steps | `client.review_trace(req) -> ReviewTraceResponse` (`POST /v1/review-trace`) | 1-200 value-free events (`step`, `kind`, optional token/class/tool/error code), scrubbed task context, trace policy | `action` continue/warn/halt, fixed `reason_code` | Apply the halt; keep your deterministic controls running whether or not this feature is on. Do not call this when the feature is disabled. |

Request and response shapes: `contracts/v1/examples/*.json`; reason codes:
`contracts/v1/reason-codes.json`. Render reason codes to human text in the UI; the API never
returns free text.

Minimal usage:

```python
approval = client.approve({
    "schema_version": "1.0", "session_id": session, "request_id": new_id(),
    "token": "API_KEY_1_a3f9", "pii_class": "API_KEY", "tool_name": "type",
    "argument_path": "text",
    "destination": {"origin": origin, "field_id": field, "verified_by_runtime": True},
    "task_context": scrubbed_context,
    "policy": {"policy_id": "integration-policy-v1", "rules": [...],
               "allowed_origins": [origin], "allowed_fields": [field],
               "max_ttl_seconds": 60, "max_uses": 1},
})
if approval.decision == "approve" and approval.scope is not None:
    grant = mint_grant(approval.scope)          # core-owned; scope can only be narrowed further
```

## 4. Readiness gate for private values

`compute` is the only endpoint that receives cleartext. The client refuses to send it unless a
readiness probe (cached for `readiness_ttl_seconds`, default 5 s) reported
`ready_for_private_values: true`; otherwise it returns `status: "error"`, `tokens: []`,
`reason_code: "NOT_READY"` without contacting the endpoint. Mock mode is never ready, so real
values cannot reach it through this client.

`allow_mock_for_private_values=True` disables that gate. It exists for synthetic fixtures only
(the fake core uses it); leave it `False` in the real core.

## 5. Switching mock -> local

Application logic does not change. Only configuration does:

| Setting | Mock | Local (isolated Qwen) |
| --- | --- | --- |
| `base_url` | `http://127.0.0.1:18555` | address printed by `plva-pr-local` (loopback, or the sandbox's forwarded port) |
| `credential` | `.plva-pr/credential` written by `plva-pr-mock` | credential file written by the local launcher |
| `readiness().mode` | `mock` | `local` |
| `ready_for_private_values` | always `false` | `true` only after model load and isolation verification |

Verify the switch with the fake core, which uses the same client:

```sh
uv run plva-pr-mock                                   # terminal 1
uv run plva-pr-fake-core                              # terminal 2: exit 0, prints codes/tokens/latency only
PLVA_PR_BASE_URL=http://127.0.0.1:<port> PLVA_PR_CREDENTIAL_FILE=<path> uv run plva-pr-fake-core
```

`examples/curl.md` has the same calls without Python.

## 6. Fail-closed behaviour

| Situation | `approve` | `compute` | `review_trace` | `readiness` |
| --- | --- | --- | --- | --- |
| `enabled=False` (no network call is made) | deny `MODEL_UNAVAILABLE` | error `MODEL_UNAVAILABLE` | halt `MODEL_UNAVAILABLE` | `None` |
| Service unreachable / connection refused | deny `MODEL_UNAVAILABLE` | error `MODEL_UNAVAILABLE` | halt `MODEL_UNAVAILABLE` | `None` |
| Timeout, or a valid reply arriving after the deadline | deny `MODEL_UNAVAILABLE` | error `MODEL_UNAVAILABLE` | halt `MODEL_UNAVAILABLE` | `None` |
| Non-200 (401, 403, 409, 413, 500, ...) | deny `MODEL_UNAVAILABLE` | error `MODEL_UNAVAILABLE` | halt `MODEL_UNAVAILABLE` | `None` |
| Malformed JSON, contract violation, extra fields, oversized body | deny `MODEL_UNAVAILABLE` | error `MODEL_UNAVAILABLE` | halt `MODEL_UNAVAILABLE` | `None` |
| Echoed `session_id` / `request_id` / `schema_version` differ | deny `MODEL_UNAVAILABLE` | error `MODEL_UNAVAILABLE` | halt `MODEL_UNAVAILABLE` | `None` |
| Service not ready for private values (or readiness unavailable) | n/a | error `NOT_READY` (nothing sent) | n/a | as reported |
| Policy denial / count mismatch / model output rejected | deny with the service's reason code | error with the service's reason code | halt/warn with the service's reason code | n/a |
| Request does not satisfy the contract locally | `ClientError` raised, nothing sent | `ClientError` raised, nothing sent | `ClientError` raised, nothing sent | n/a |

Every fallback response carries the request's own identifiers so it correlates like a real one.
`plva_private_reasoning.client.closed_approve / closed_compute / closed_review` build the same
fallback results if the core wants to short-circuit a call itself.

## 7. Service-side guarantees you can rely on

* Loopback bind only; `Host` allowlist; any `Origin` header -> `403 FORBIDDEN_ORIGIN`.
* Bearer credential required on everything except `GET /health`.
* JSON only, unknown fields rejected, body cap 65536 bytes, `Cache-Control: no-store` everywhere.
* Every error body is exactly `{"schema_version": "1.0", "error_code": "<CODE>"}`; validation
  errors never echo the rejected input.
* Replay of `(session_id, request_id)` -> `409 DUPLICATE_REQUEST`, regardless of body.
* No access logs, no request-body logging.

## 8. Test commands

```sh
uv run pytest -q                       # contracts, service boundary, client fallbacks, fake-core e2e
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy
```
