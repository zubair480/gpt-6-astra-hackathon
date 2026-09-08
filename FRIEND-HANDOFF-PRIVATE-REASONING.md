# Build PLVA's optional private reasoning module

## Your assignment

You are the coding agent for a teammate at the GPT-6 Astra hackathon. Build a standalone repository containing an optional local Qwen reasoning service, its NemoClaw/OpenShell isolation, a client adapter, and tests. Work autonomously on implementation, verification, and documentation. Use subagents for independent work with clear ownership if your environment supports them.

Deliver working software, not just an architecture document. The main team must be able to clone your repository and connect it without importing your internal implementation or rewriting its privacy core.

Interpretation: this workstream is Qwen + NemoClaw (local private reasoning and sandboxing). It is not a digital-twin project or Claude integration.

The main team is building the computer-use agent with GPT-6 Astra. You are building the optional module that reasons locally when private data cannot be shown to Astra. Your module is not the cloud agent and must never call a cloud model with private inputs.

## Product context and boundaries

PLVA protects computer-use observations before they reach the cloud model. Its core detects private information, masks screenshots, substitutes tokens such as EMAIL_1_a3f9, stores token-to-value mappings in a memory-only vault, checks actions, and restores values only for approved local execution. It also re-scrubs later observations and history.

The main team owns:

- Astra API integration and the computer/browser runtime.
- Screenshot capture, local redaction, and outbound history scrubbing.
- The authoritative vault, token issuance, and privacy policy enforcement.
- Actual action execution, trusted destination verification, approval grants, and stopping the agent.
- The operator UI and the inspector showing exactly what was submitted to Astra.

You own:

1. Local recommendations about whether a proposed private action is allowed.
2. Local sort/select reasoning over explicitly supplied private values.
3. Local recommendations to continue, warn, or halt after a behavior trace.
4. Isolation of the service and model, including empirical network-denial checks.
5. A stable transport contract, client, mock service, test fixtures, and integration guide.

Your service recommends decisions. It cannot grant itself access, change policy, execute computer actions, fetch the vault, or directly stop the agent. The core enforces the final decision and may deny any recommendation.

## Reference implementation

Reference: https://github.com/dael-amz/browser-agent-privacy-layer

The main team reviewed commit `467a452`. Clone it into a separate reference directory if useful. Do not depend on its local checkout existing in the main project. Its large baseline archive was unavailable through Git LFS during the main team's clone; it is not needed for this assignment.

Read these files for architectural context:

- `src/plva_proxy/mediator.py`: approval requests, bounded grants, behavior review.
- `src/plva_proxy/local_llm.py`: loopback model client and output handling.
- `src/plva_proxy/semantic_executor.py`: sort/select validation and token-only external results.
- `src/plva_proxy/tool_channel.py`: optional wiring and deterministic operations.
- `config/mediator-criteria.json`: sample user rules.
- `config/openshell-mediator-policy.yaml`: sandbox policy.
- `run_mediator_sandbox.sh` and `docs/local-llm-runbook.md`: deployment and deny testing.
- Corresponding mediator, semantic-executor, local-client, and tool-channel tests.

Useful lessons, not claims to copy blindly:

- The reference's basic privacy core works without its optional generative local model.
- Its automatic approval bridge can judge metadata without receiving the secret itself.
- Its semantic executor may see real values internally; its externally returned answer contains only input tokens.
- Its sandbox launch is specific to a macOS host and Linux ARM64 image. Do not assume that launcher works on your machine.
- A loopback URL is not proof that the model has no outbound network access.
- Polling sockets and killing a process after a violation is not a preventive network boundary.
- A policy file or a passed policy prover alone does not demonstrate enforcement.

The event rules supplied to us require new hackathon work and a public open-source submission. Implement this module during the event, document inspiration and dependencies, and do not present pre-existing reference code as new work. Check licenses before copying code or distributing weights. Do not publish model weights, credentials, or private traces in your repository.

## Minimum successful delivery

The main team can start your mock service, call three stable APIs, then switch configuration to the real isolated Qwen service without changing application logic. The real service has a verified deployment path and safe failure behavior.

Prioritize this order:

1. Freeze schemas, examples, and a deterministic mock service.
2. Ship a thin client plus integration tests.
3. Implement and evaluate actual local model inference.
4. Finish sandbox enforcement and test it empirically.
5. Deliver a reproducible startup command and integration handoff.

Mock mode must visibly identify itself. If the real sandbox is unavailable, keep delivering mock/client/tests, but report the real deployment as blocked. Never quietly substitute unsandboxed inference or a cloud API.

## Integration contract: proposed v1

These are the proposed shared interfaces for parallel implementation; the main core has not implemented them yet. Freeze them in versioned JSON Schemas and OpenAPI before building internal details. Send the main team the first contract commit early. Do not silently rename fields or change meanings afterward; use a version bump for breaking changes.

Use a loopback-only HTTP service with configurable address/port; `http://127.0.0.1:18555` is the default host endpoint. Put the model and the component that handles cleartext inside the isolated boundary. Use a narrowly controlled inbound port forward if the sandbox requires one.

Authenticate every endpoint except a minimal liveness check using a per-launch local bearer credential. Generate it locally; never commit it or send it to Astra. Bind to loopback, disable broad CORS, reject unexpected Host/Origin values, and do not assume all localhost callers are trusted. The main agent must not receive direct tools for calling this service. The credential must not be reachable from its execution environment.

Accept JSON only; reject unknown fields, invalid enums, overlarge inputs, malformed tokens, and duplicate tokens where applicable. Requests use `schema_version: "1.0"`, `session_id`, and `request_id`. Echo those identifiers so the client can correlate results, but the core must still validate them. Identifiers are correlation data, not authorization credentials.

### 1. GET /health and GET /v1/readiness

`/health` says only whether the service process is alive. The authenticated readiness response includes:

```json
{
  "schema_version": "1.0",
  "mode": "mock",
  "ready_for_private_values": false,
  "model_loaded": false,
  "isolation": "unverified",
  "capabilities": ["approve", "compute", "review-trace"]
}
```

Modes: `mock` or `local`. Isolation states: `unverified`, `verified`, or `failed`. The real service may accept private values only after model readiness and isolation verification. Verification evidence must be tied to the running instance and effective policy, not a stale file from a previous launch. Include a non-sensitive instance ID and verification timestamp in the complete schema.

Synthetic mock fixtures may run when private-value readiness is false. The core adapter must prevent real private inputs from reaching mock mode.

### 2. POST /v1/approve

This endpoint judges a proposal using policy and context. Do not accept a secret value in the v1 approval request; it is unnecessary for the initial approval use case.

```json
{
  "schema_version": "1.0",
  "session_id": "demo-session",
  "request_id": "approval-001",
  "token": "API_KEY_1_a3f9",
  "pii_class": "API_KEY",
  "tool_name": "type",
  "argument_path": "text",
  "destination": {
    "origin": "https://service.example",
    "field_id": "api-key-input",
    "verified_by_runtime": true
  },
  "task_context": "Configure the authorized integration.",
  "policy": {
    "policy_id": "integration-policy-v1",
    "rules": ["Use this key only in the integration credential field."],
    "allowed_origins": ["https://service.example"],
    "allowed_fields": ["api-key-input"],
    "max_ttl_seconds": 60,
    "max_uses": 1
  }
}
```

Successful recommendation:

```json
{
  "schema_version": "1.0",
  "session_id": "demo-session",
  "request_id": "approval-001",
  "decision": "approve",
  "reason_code": "POLICY_MATCH",
  "scope": {
    "token": "API_KEY_1_a3f9",
    "tool_name": "type",
    "argument_path": "text",
    "origin": "https://service.example",
    "field_id": "api-key-input",
    "ttl_seconds": 30,
    "max_uses": 1
  }
}
```

Decisions: `approve` or `deny`; deny has `scope: null`. Model output cannot expand the requested scope. Deterministically enforce class restrictions, verified destination, origin/field allowlists, TTL bounds, and use bounds before accepting a recommendation. Missing destination evidence or missing policy means deny. The runtime-verification flag is trusted only because the caller is the core; accepting a model-created flag is not verification. The core must recheck the actual destination immediately before execution to handle page changes.

Use fixed reason codes; the UI renders human-readable text locally. Do not return arbitrary model explanations. Approval remains a recommendation: the core mints and consumes the actual grant.

### 3. POST /v1/compute

Only this endpoint receives the selected private values needed for computation. The core first checks that local computation is allowed for every value. Never send the whole vault.

```json
{
  "schema_version": "1.0",
  "session_id": "demo-session",
  "request_id": "compute-001",
  "operation": "sort",
  "instruction": "Alphabetical order by full name.",
  "items": [
    {"token": "NAME_1_a3f9", "value": "Charlie Example"},
    {"token": "NAME_2_a3f9", "value": "Alice Example"}
  ],
  "select_count": null
}
```

External result:

```json
{
  "schema_version": "1.0",
  "session_id": "demo-session",
  "request_id": "compute-001",
  "status": "ok",
  "tokens": ["NAME_2_a3f9", "NAME_1_a3f9"],
  "reason_code": "COMPLETED"
}
```

Operations: `sort` and `select`. Sort must return an exact permutation of input tokens. Select must return a unique subset, with the requested count when provided. Empty selection is valid when no positive count is required. Support at most 40 items, 500 characters per value, and 500 characters of instruction initially; document the minimum item count. Duplicate values must either have a correct unambiguous token mapping or be explicitly rejected; never silently lose their identities.

Failures use `status: "denied"` or `"error"`, `tokens: []`, and a fixed reason code. No partial answer. Internal grammar-constrained output should use enums from the request where supported. Regardless of model/server grammar support, deterministically validate membership, uniqueness, counts, and schema. Keep raw completions inside the trusted boundary. The API response must not contain real values, rationale, chain of thought, arbitrary strings, or unknown tokens.

Return only the minimum authorized result. Even token selection/order reveals something about private data; this endpoint is an intentional, bounded disclosure of an operation result, not a zero-information channel. The core controls which computations are allowed and limits repeated probing. Do not claim that token-only output proves unrestricted computation is private.

### 4. POST /v1/review-trace

Input contains structured value-free events: step number, event kind, token/class if needed, and fixed error codes. Include scrubbed task context and user policy. Do not accept arbitrary raw logs, screenshots, or secrets.

Return the common identifiers, `action: "continue" | "warn" | "halt"`, and a fixed `reason_code`. The model recommends; the main core applies the halt. A malformed response or timeout during a requested review becomes halt in the client adapter. Define allowed event kinds and maximum trace length in the schema.

### Common failure and replay rules

- Unavailable/unauthenticated/malformed approval result -> client returns deny.
- Unavailable/unauthenticated/malformed computation -> client returns an error with no tokens.
- Unavailable/unauthenticated/malformed requested trace review -> client returns halt.
- Do not request trace reviews when the optional feature is disabled; the core's deterministic controls continue operating.
- A policy denial is an ordinary typed result. Authentication and schema failures use appropriate HTTP status codes with fixed error bodies; do not echo rejected input.
- Do not return framework validation bodies that repeat submitted private values. Test error serialization explicitly.
- Bound timeouts, body size, concurrency, queues, model output length, and retries. Limit invalid-model-output retry to at most one initially.
- Cancelled or expired requests cannot later authorize an action. Late responses must be ignored by the client.
- Repeated request IDs with different bodies must be rejected. For v1, rejecting duplicates is acceptable and avoids retaining cleartext for response caching.
- Do not automatically retry approval requests with a new identity or let a replay mint multiple grants. The core owns grant consumption and deduplication.

## Model and isolation implementation

The reference uses Qwen3-4B-Instruct-2507 Q4_K_M through llama.cpp. Treat that as a starting candidate, not a requirement to use a particular hardware build. Verify current official model/runtime and NemoClaw/OpenShell documentation before choosing versions. Pin the model source/revision, weight checksum, runtime version, and effective policy. Verify licensing and do not bundle weights into Git.

Start with one supported deployment platform. Prefer the teammate's available hardware; Linux x86_64 is a useful target if supported. Explain CPU/GPU requirements and integration from a Windows host. Do not spend the hackathon claiming support for untested platforms. If an isolated companion machine is needed, document the authenticated transport and network policy; do not expose an unauthenticated LAN service.

Install/download model assets during an explicit provisioning phase. The private-data runtime must work offline with those assets; it must not fetch packages, weights, tokenizers, telemetry, or updates while processing requests.

NemoClaw/OpenShell is the preferred isolation target for this workstream. Keep a small backend boundary so deployment can change later. If unavailable, provide an honestly labeled mock or synthetic-only development mode. Do not claim equivalence for another sandbox without demonstrating its enforcement.

Test outbound denial from the same boundary containing both inference and cleartext-handling service code. Cover HTTPS, direct-IP TCP, DNS, and proxy/environment bypass paths supported by the runtime. A failed network request is not sufficient evidence by itself: distinguish policy denial from unavailable networking, missing tools, broken TLS, or a dead destination. Use documented enforcement evidence and a synthetic negative control in a separate disposable environment where appropriate; never weaken a live private-data runtime to test it.

Readiness must fail if the effective policy is permissive, evidence is inconclusive, or the running instance changes. Preserve sanitized test metadata only. Explain whether inbound forwarding permits any unintended outbound route.

## Data handling

- Keep values and raw model completions in request-scoped memory; no conversation persistence or value cache.
- Disable request-body logging, model prompt logging, raw output logging, telemetry, crash uploads, and tracing that captures content. Verify runtime defaults rather than assuming them.
- Do not print secrets to terminal or include them in exceptions, filenames, health endpoints, timing labels, or metrics.
- Audit only fixed codes, counts, durations, instance/version identifiers, and sanitized test evidence.
- Clear references after completion. Document that ordinary managed-memory cleanup is not guaranteed cryptographic zeroization and that host swap/crash-dump protections are outside a basic process-memory claim.
- Treat policy as trusted input from the core, and task text/item values as untrusted data. Instructions embedded in a value must not change policy or output rules.

## Suggested repository structure

```text
contracts/v1/              JSON Schemas and synthetic request/response examples
service/                   Transport, validation, authorization recommendations
service/model/             Local inference adapter and constrained output parser
service/operations/        Approve, compute, review-trace implementations
client/                    Thin client, disabled/mock behavior, core adapter example
sandbox/                   Pinned policy, startup, shutdown, readiness, deny checks
tests/                     Unit, contract, integration, live synthetic evaluations
examples/                  Standalone fake-core integration using synthetic values
docs/INTEGRATION.md         How the main team connects the module
docs/SECURITY.md            Trust boundary, limitations, isolation evidence
docs/HANDOFF.md             Final status, pinned commit, commands, results, blockers
README.md
LICENSE
.env.example
```

Choose one implementation language; Python is a reasonable default because the reference core is Python. The HTTP contract is language-independent. Ship a Python client first, with curl/JSON examples for other languages. Do not require the main team to adopt your web framework or inference library.

## Agent delegation plan

The session lead owns contracts and integration. After writing the v1 schemas, delegate these independent tracks if agents are available:

| Agent | Ownership | Deliverable |
| --- | --- | --- |
| Local reasoning | `service/model`, `service/operations` | Qwen inference, deterministic output checks, synthetic quality cases |
| Isolation | `sandbox`, security documentation | Reproducible deployment and empirical denial evidence |
| Client and verification | `client`, `tests`, `examples` | Mock, client fallback behavior, schema/contract tests, integration example |

The lead owns transport and shared schema changes, reviews security-sensitive boundaries, and merges the tracks. Establish test-directory ownership before agents edit files. Use branches/worktrees where helpful; do not have agents overwrite the same files. Keep a short `STATUS.md` with owner, current task, completed checks, blockers, and next integration handoff.

## Acceptance tests

Use unmistakably synthetic values throughout. Keep unit/mock results separate from actual model and isolation evidence.

1. Valid credential use can be recommended; wrong origin, field, class, unverifiable destination, or missing policy is denied.
2. Model recommendations cannot expand TTL, use count, token, tool, path, origin, or field scope.
3. Sort preserves every token once; select returns only permitted input tokens. Invalid/duplicate/unknown entries fail closed.
4. Private input containing instruction-like text cannot cause free-text output or a policy override.
5. Model output attempting to echo a secret is rejected or mapped internally; API outputs and logs contain none of the synthetic private values.
6. Invalid JSON, wrong types, unknown fields, and oversized bodies do not leak input through validation errors.
7. Stop model service, force timeout, supply malformed output, and cancel requests: client behavior remains deny/error/halt as specified.
8. Missing/wrong auth, cross-origin calls, request replays, cross-session confusion, and late responses cannot mint an actionable grant.
9. The real isolated deployment passes empirical outbound-denial checks and goes unready when its verified instance/policy is invalidated.
10. A standalone fake core calls the same client against mock and local modes. Mode changes require configuration only.
11. A small held-out synthetic set measures correct approvals, denials, selections, and sorts. Schema-valid answers are not automatically correct judgments; report these separately.

## Required handoff to the main team

Deliver the repository and a pinned integration commit, not a moving branch alone. Include:

- Exact install/start/stop/test commands and supported hardware/OS.
- Frozen v1 schemas, example payloads, and an OpenAPI document.
- Mock startup that requires no model or cloud credential.
- Real inference startup, provisioning instructions, pinned versions, and checksums.
- The client and a fake-core end-to-end example.
- A table of tests actually run, outcomes, measured latency, and known limitations.
- Isolation evidence for the actual deployment; explicitly label anything unverified.
- A concise mapping from the three APIs to the core's approval, private-computation, and trace-review hooks.
- A dependency and license inventory; no raw private traces or bundled secret files.

The main team can integrate initially as a separately launched service with your client. Repository merging or vendoring can happen later because the integration depends on contracts rather than directory layout. Keep your package namespace distinct, for example `plva_private_reasoning`.

## Working instructions

Start implementing now in your own repository. Make reasonable reversible implementation choices and keep working through routine issues. Share the contract/mock milestone before waiting for the full model deployment. If hardware, installation permissions, or external access blocks a track, document the exact blocker and continue independent deliverables; do not replace missing components with an undisclosed simulation.

Do not modify the main team's repository, publish deployments, purchase compute, or expose services publicly as part of this brief. Prepare the repository for the human owner to share. The goal is a small, independently testable module that plugs into PLVA—not a second full computer-use agent.
