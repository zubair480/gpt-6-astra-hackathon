# Security: trust boundary, isolation evidence, and limits

Isolation track (`sandbox/`, `tests/test_sandbox_*.py`, this file). Everything below
distinguishes three states honestly: **tested here**, **untested** (written to public
documentation but never executed on this machine), and **blocked** (cannot be executed on this
machine at all). Nothing in this document is a claim of enforcement unless a row in the
"verified vs unverified" table says so.

## 1. Status on the author's machine (macOS 26.4, Apple Silicon)

| Item | State | Evidence / reason |
| --- | --- | --- |
| OpenShell policy (`sandbox/policy.yaml`) | **UNTESTED** | Written against the published policy schema. Never applied to a live sandbox. |
| OpenShell launcher (`sandbox/start.sh --backend openshell`) | **BLOCKED** | `openshell` CLI is not installed; neither Docker, Podman, Lima, Colima nor any other container runtime is present; installing system software and purchasing compute are out of scope for this track. OpenShell's own install path on macOS requires Docker Desktop. |
| `sandbox-exec` dev fallback (`sandbox/macos-dev.sb`) | **TESTED** | Deny checks run under it: 6/6 probes `denied`, all failures immediate (EPERM / fast EAI_NONAME). Writes outside the runtime dir fail with EPERM. The mock service starts, binds loopback, writes its credential, and answers `/v1/readiness` from the host. |
| Negative control (`deny_check.py --negative-control`, unsandboxed) | **TESTED** | 6/6 probes `succeeded` on this host (HTTPS 200, TCP connect, DNS resolved, UDP DNS reply, IP-literal HTTPS response, bogus proxy env honored -> ECONNREFUSED). |
| Evidence pipeline (`deny_check.py` -> `verify_isolation.py` -> `isolation-evidence.json`) | **TESTED** | Unit tests over synthetic evidence plus an end-to-end launcher test with the mock service. |
| Real local model inside a boundary | **BLOCKED** | Depends on the model track's `plva-pr-local` entry point and on a sandbox that can run it; neither exists on this machine yet. |

`sandbox-exec` is deprecated by Apple (still shipped and functional on macOS 26, but
undocumented and unsupported). It confines one process tree with a Seatbelt profile; it does
**not** create a network namespace, and it is **not equivalent** to OpenShell. It is provided
only so the evidence pipeline and readiness gating can be exercised with synthetic values on
a developer Mac.

## 2. Platform findings: NVIDIA OpenShell / NemoClaw

Researched 2026-09-08 from the NVIDIA docs and GitHub (links at the end).

- **What it is.** OpenShell is NVIDIA's sandboxed runtime for autonomous agents: a gateway
  that launches sandboxes (Docker/Podman/microVM drivers), enforces a declarative YAML policy
  covering filesystem (Landlock), process identity, and network, and fronts all outbound
  traffic with a deny-by-default L7 proxy. NemoClaw is a reference stack layered on top of
  OpenShell (agent presets, managed inference, lifecycle); for this module only OpenShell's
  sandbox + policy layer is relevant.
- **Install.** `curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh`
  followed by a gateway start; a Docker (or Podman) daemon is required for the container
  driver. The tutorial explicitly lists "Docker Desktop running" as a prerequisite.
- **Platforms.** Linux, macOS on Apple Silicon (via Docker Desktop), Windows through WSL 2
  (experimental). So OpenShell is *not* Linux-only, but on this Mac it is unavailable because
  no container runtime is installed. The spec's preferred target, Linux x86_64 with the Docker
  driver, is what `sandbox/policy.yaml` and the `openshell` branch of `start.sh` are written for.
- **Policy model.** A policy file has static sections fixed at `openshell sandbox create`
  (`filesystem_policy`, `landlock`, `process`) and dynamic sections hot-reloadable with
  `openshell policy set <sandbox> --policy file --wait` (`network_policies`,
  `network_middlewares`). Network policy is a map of named entries, each listing allowed
  endpoints (host, port, protocol, HTTP method/path rules) and the binaries allowed to reach
  them. **An empty map, `network_policies: {}`, denies every outbound connection.**
- **Enforcement (documented).** Denied HTTPS CONNECTs are answered by the sandbox's proxy
  with HTTP 403 (`curl: (56) Received HTTP code 403 from proxy after CONNECT`); L7 denials
  return a 403 JSON body; the gateway logs `action=deny dst_host=... deny_reason='no matching
  network policy'` (`openshell logs <sandbox> --since 5m`). The reference project established
  empirically (on its own machine, not this one) that DNS resolution is blocked and that
  `openshell policy prove` also passed a deliberately leaky negative control, so `prove` is not
  evidence; only an in-sandbox deny test is.
- **Inbound.** Host access to a service inside the sandbox goes through the gateway:
  `openshell forward service <sandbox> --target-port 18555 --local 127.0.0.1:18555`.

## 3. Trust boundary

```
 HOST (operator machine)                                    ISOLATION BOUNDARY
 ─────────────────────────────────────────────────         ────────────────────────────────────
 PLVA core (authoritative vault, policy, execution)          plva-pr-local  (FastAPI, loopback)
   │  thin client, bearer credential from .plva-pr/            │  request-scoped memory only
   │  synthetic or core-selected values only                    │  reads /models (read-only)
   ▼                                                            ▼
 127.0.0.1:18555  ══ inbound-only forward ══════════════▶  service :18555 ──▶ llama.cpp runtime
   ▲                                                            │
   │ readiness(instance_id)                                     ✗ no outbound: HTTPS, TCP/IP,
   │                                                            ✗ UDP, DNS, proxy env  (policy)
 sandbox/verify_isolation.py ◀── deny-check.json ◀──── sandbox/deny_check.py (runs INSIDE)
   │        ▲
   │        └── negative-control.json (deny_check.py --negative-control, HOST, unsandboxed)
   ▼
 isolation-evidence.json ──▶ plva-pr-local --isolation-evidence  (readiness gate)

 Cloud model (GPT-6 Astra) ◀── main team's scrubbed channel; never reachable from the boundary
```

Inside the boundary: the HTTP transport, validation, the approve/compute/review-trace
operations, the inference runtime, and the model weights. Everything that can see cleartext
values or raw model completions is inside. The evidence tools straddle it on purpose:
`deny_check.py` must run inside (it probes the boundary from within); `verify_isolation.py`
runs on the host because it needs the readiness endpoint and the host clock.

## 4. What the service can and cannot do

Can:

- Accept authenticated JSON on loopback and return the fixed-shape v1 responses
  (approve / compute / review-trace), including bounded token-only compute results.
- Report readiness, including `isolation`, `instance_id`, and `verified_at`.

Cannot (by construction, and in the boundary by policy):

- Reach any network destination: no HTTPS, no direct-IP TCP, no UDP, no DNS, no proxy route.
- Mint grants, change policy, execute computer actions, read the vault, or stop the agent.
  It only recommends; the core enforces (spec, "Product context and boundaries").
- Become `ready_for_private_values` without `mode == local`, a loaded model, **and**
  `isolation == verified` (`ServiceState.ready_for_private_values`).
- Persist anything: no request-body/prompt/output logging, no access log, no telemetry;
  the only files written are the 0600 credential and the sanitized evidence in the runtime dir.

## 5. Credential handling

- Per-launch bearer credential, generated with `secrets.token_urlsafe(32)` inside the
  service process, written once to `<runtime-dir>/credential` with mode 0600 in a 0700
  directory. Never logged, never in a URL, compared with `hmac.compare_digest`.
- `sandbox-exec` backend: the runtime dir is the only writable path, so the credential file
  is where the host reads it; same user, no network involved.
- OpenShell backend (untested): the credential is written to `/tmp/plva-pr/credential`
  inside the sandbox and copied out with `openshell sandbox exec -- cat`, i.e. over the
  gateway's exec channel, not over any network socket. `stop.sh` deletes both copies.
- The main agent's execution environment must not be able to read the runtime dir; that is a
  host-configuration obligation of the core team (separate user or directory ACL).

## 6. Data handling limits

- Values and raw completions live in request-scoped Python objects and are dereferenced when
  the request finishes. **This is ordinary managed-memory cleanup, not cryptographic
  zeroization.** Freed memory may retain bytes until reused.
- Host swap, hibernation images, crash dumps / core files, and memory captured by a debugger
  or a privileged host process are **outside** this module's claim. Turn off core dumps and
  use encrypted swap on the host if that matters to your deployment.
- Evidence files are sanitized by construction: fixed probe names, exception class names,
  errno names, fixed detail codes, durations, platform strings, `instance_id`, and the policy
  hash. No probe targets, no exception messages, no environment values (only the *names* of
  proxy variables present at start). Unit tests assert none of the fixed targets appear.
- Policy is trusted input from the core; task text and item values are untrusted data. The
  operations layer (lead/model tracks) is responsible for keeping instructions embedded in
  values from changing output rules; this track only guarantees that whatever the model does,
  it cannot talk to the network.

## 7. Isolation evidence model

### Pipeline (`sandbox/start.sh`)

1. Launch the service inside the boundary with a scrubbed environment (no proxy variables).
2. Read `instance_id` from `/v1/readiness` on the host.
3. Run `sandbox/deny_check.py --backend <b> --instance-id <id> --policy <file>` **inside the
   same boundary**. It writes `deny-check.json`.
4. Run `sandbox/deny_check.py --negative-control` on the host, unsandboxed, to prove the same
   probes succeed when nothing restricts them (`negative-control.json`). `--skip-negative-control`
   exists for offline hosts and is printed loudly because it lowers assurance.
5. Run `sandbox/verify_isolation.py` on the host. It re-hashes the policy, re-fetches the
   `instance_id`, and writes `isolation-evidence.json`.
6. If the result is not `verified`, the launcher stops the service (fail closed).

`isolation-evidence.json` shape (consumed by `plva-pr-local --isolation-evidence`):

```json
{"isolation": "verified", "verified_at": "2026-09-08T12:00:00+00:00",
 "instance_id": "...", "policy_sha256": "...", "backend": "sandbox-exec",
 "checked_at": "2026-09-08T12:00:00+00:00", "reasons": ["ALL_PROBES_DENIED"]}
```

### Probes (fixed names; targets are constants in `deny_check.py`)

| Probe | What it exercises | Target (never written to evidence) |
| --- | --- | --- |
| `https_well_known` | HTTPS through whatever proxy env the runtime injected | `https://example.com/` |
| `tcp_direct_ip` | raw TCP connect to a public IP, no DNS | `1.1.1.1:443` |
| `dns_resolve` | the system resolver (`getaddrinfo`) | `example.com` |
| `udp_dns_query` | UDP route lookup + send + wait for a real DNS reply | `1.1.1.1:53` |
| `proxy_env_bogus_loopback` | `HTTP(S)_PROXY`/`ALL_PROXY` set to a loopback proxy and honored by urllib | `http://127.0.0.1:1` |
| `proxy_env_cleared_direct_ip` | proxy env removed + empty `ProxyHandler`, HTTPS to an IP literal (no resolver) | `https://1.1.1.1/` |

### Classification: what counts as policy denial

Each backend has a *signature*: the way its enforcement mechanism makes a denied connection
fail. Anything else is `inconclusive`, and one inconclusive probe makes the whole run fail.

| Observation | sandbox-exec (tested) | OpenShell (documented, untested) | Negative control |
| --- | --- | --- | --- |
| connect/sendto `EPERM` within 2 s | **denied** | denied | - |
| `ENETUNREACH` / `EHOSTUNREACH` / `ECONNREFUSED` within 2 s | inconclusive (`UNEXPECTED_ERRNO`) | **denied** (private netns, no route) | - |
| HTTP CONNECT answered 403 by the runtime's proxy | inconclusive (`UNEXPECTED_PROXY_RESPONSE`) | **denied** (`L7_PROXY_403`) | - |
| resolver failure within 1.5 s | **denied** (`RESOLVER_BLOCKED_FAST_FAIL`, weaker; see below) | denied (weaker) | inconclusive |
| resolver failure after > 1.5 s | inconclusive | inconclusive | inconclusive |
| timeout / UDP sent but no reply | inconclusive | inconclusive | inconclusive |
| TLS error | inconclusive | inconclusive | inconclusive |
| any HTTP response, TCP connected, name resolved, DNS reply | **succeeded = egress open** | succeeded = egress open | succeeded (expected) |
| bogus loopback proxy `ECONNREFUSED` | inconclusive (loopback reachable) | denied (namespaced loopback) | succeeded (`PROXY_ENV_HONORED`) |
| bogus loopback proxy `EPERM` | **denied** | denied | - |

Why the resolver signature is weaker: an offline host also fails resolution immediately.
`verify_isolation.py --negative-control` therefore requires a fresh, same-platform,
all-succeeded negative control from the same host, which shows the resolver *worked* outside
the boundary minutes earlier. The connect path is covered independently by the two IP-literal
probes, whose `EPERM` cannot be produced by an offline host.

### Freshness and binding (`verify_isolation.py`)

`failed` unless all of: `evidence_version == 1`, `kind == deny-check`,
`negative_control == false`, `backend` known (and equal to `--expected-backend` if given),
`policy_sha256` equals the hash of the effective policy file on disk, `instance_id` equals
the one the running service reports, timestamp is timezone-aware, not more than 60 s in the
future and at most `--max-age-seconds` (default 900) old, every required probe present exactly
once with outcome `denied`, and `summary.all_expected` true. The summary flag alone cannot
verify: the per-probe outcomes are re-checked.

Invalidation: every launch has a new `instance_id`, so evidence cannot outlive the process it
describes; `stop.sh` deletes the evidence and credential; editing the policy file changes its
hash and fails the next verification. This is acceptance test 9's "goes unready when its
verified instance/policy is invalidated" for the evidence side; the service side (re-reading
the evidence file and dropping to `failed`) belongs to the model track's `plva-pr-local`.

## 8. Does the inbound port forward permit any unintended outbound route?

**OpenShell.** No. The sandbox has a private network namespace; the forward is a gateway-side
listener on host loopback that opens connections *into* the sandbox. A TCP connection is
bidirectional, so the service can only send response bytes on connections the host opened;
it cannot initiate anything toward the host or beyond, and there is no route from the sandbox
namespace to the host's loopback interface. Host-side proxies listening on 127.0.0.1 are
therefore unreachable from inside. The only outbound path that exists at all is the gateway
proxy, and `network_policies: {}` makes it deny everything.

**sandbox-exec (dev fallback).** Mostly, with one documented caveat. The profile denies every
socket operation, then allows only bind + inbound on the service port. Because sandbox-exec
shares the host's loopback interface, *any* loopback outbound allowance would be an egress
route through a host process (a SOCKS/HTTP proxy, an SSH tunnel). The profile grants none by
default; when `inner_port` is supplied for a subprocess `llama-server`, outbound to exactly
that loopback port is allowed, and an unsandboxed host process squatting on that port before
launch would be reachable. Run inference in-process (omit `inner_port`) to close the route,
or verify with `lsof -nP -iTCP:<inner_port>` that only the sandboxed runtime listens there.

## 9. Commands

```bash
uv sync
uv run pytest -q tests/test_sandbox_*.py            # unit + macOS integration (skips elsewhere)
uv run ruff check sandbox tests && uv run ruff format --check sandbox tests

# macOS dev fallback (tested): launcher end to end with the mock service
sandbox/start.sh --backend macos-dev --mock          # PLVA_PR_PORT to change 18555
sandbox/stop.sh  --backend macos-dev

# macOS dev fallback with the real local service (needs the model track's plva-pr-local)
sandbox/start.sh --backend macos-dev                 # PLVA_PR_INNER_PORT=<port> if llama-server is a subprocess
sandbox/stop.sh  --backend macos-dev

# Linux x86_64 + OpenShell (UNTESTED; re-check flags against `openshell ... --help`)
PLVA_PR_SANDBOX_IMAGE=<pre-provisioned image with /app and /models> sandbox/start.sh --backend openshell
openshell logs plva-pr --since 5m | grep action=deny   # gateway-side corroboration
sandbox/stop.sh --backend openshell [--delete]

# Pieces by hand
uv run python sandbox/deny_check.py --negative-control --output negative-control.json
/usr/bin/sandbox-exec -f sandbox/macos-dev.sb -D service_port=18555 -D write_dir="$PWD/.plva-pr" \
  .venv/bin/python sandbox/deny_check.py --backend sandbox-exec --instance-id <id> \
  --policy sandbox/macos-dev.sb --output .plva-pr/deny-check.json
uv run python sandbox/verify_isolation.py --evidence .plva-pr/deny-check.json \
  --policy sandbox/macos-dev.sb --output .plva-pr/isolation-evidence.json \
  --negative-control negative-control.json
```

## 10. Known gaps

- The OpenShell path is unexecuted. Its denial signature (403 on CONNECT, no-route errnos,
  fast resolver failure) is taken from documentation and the reference runbook; the first real
  run must confirm it, and `openshell logs ... action=deny` lines should be kept as
  corroborating (sanitized) evidence.
- UDP under OpenShell: if the sandbox namespace has a default route to the gateway that
  silently drops non-proxied packets, `udp_dns_query` will time out and be `inconclusive`
  rather than `denied`. That is the honest result; proving UDP denial there needs gateway log
  correlation, which this tool does not automate.
- The service must re-read `isolation-evidence.json` after `verify_isolation.py` writes it
  (the evidence can only be produced after the service is running, because it is bound to
  the running `instance_id`). That reload belongs to `plva-pr-local` (model track).
- `sandbox-exec` provides no memory or process-count limits and no protection against a
  privileged host process.

## Sources

- OpenShell repository: https://github.com/NVIDIA/openshell
- Policy schema reference: https://docs.nvidia.com/openshell/reference/policy-schema
- First network policy tutorial (denial behaviour, `policy set --wait`, logs): https://docs.nvidia.com/openshell/get-started/tutorials/first-network-policy
- NemoClaw repository and network-policy guide: https://github.com/NVIDIA/NemoClaw ,
  https://docs.nvidia.com/nemoclaw/latest/reference/network-policies.html
- Reference project lessons (not claims copied): `reference/browser-agent-privacy-layer/docs/local-llm-runbook.md`
