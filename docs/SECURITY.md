# Security: trust boundary, isolation evidence, and limits

Isolation track (`sandbox/`, `tests/test_sandbox_*.py`, this file). Everything below
distinguishes three states honestly: **tested here**, **untested** (written to public
documentation but never executed on this machine), and **blocked** (cannot be executed on this
machine at all). Nothing in this document is a claim of enforcement unless a row in the
"verified vs unverified" table says so.

## 1. Status on the author's machine (macOS 26.4, Apple Silicon M2, 8 GB)

| Item | State | Evidence / reason |
| --- | --- | --- |
| OpenShell policy (`sandbox/policy.yaml`) | **TESTED** | Accepted by `openshell sandbox create --policy` (openshell 0.0.116); Landlock applied with `rules_applied:10 skipped:0`; `/models` is a read-only filesystem, `/usr` write is `EPERM`, process runs as `sandbox` (uid 1000). |
| OpenShell launcher (`sandbox/start.sh --backend openshell`) | **TESTED** | End to end on 2026-09-08: gateway (`sandbox/openshell-gateway.sh`) with the Docker driver on Colima, image `sandbox/Dockerfile` (432 MB), real `plva-pr-local` + Qwen3-1.7B-Q8_0 inside the sandbox, 6/6 probes `denied` inside, negative control 6/6 `succeeded` in a plain container, `isolation=verified`, service reports `ready_for_private_values: true`. 41 s wall clock. |
| `sandbox-exec` dev fallback (`sandbox/macos-dev.sb`) | **TESTED** | Deny checks run under it: 6/6 probes `denied`, all failures immediate (EPERM / fast EAI_NONAME). Writes outside the runtime dir fail with EPERM. The mock service starts, binds loopback, writes its credential, and answers `/v1/readiness` from the host. Re-checked after the OpenShell work (mock, port 18577). |
| Negative control (`deny_check.py --negative-control`) | **TESTED** | macOS host: 6/6 `succeeded`. Linux/aarch64 plain container from the same image (used by the openshell backend so the platform matches the boundary): 6/6 `succeeded`. |
| Evidence pipeline (`deny_check.py` -> `verify_isolation.py` -> `isolation-evidence.json`) | **TESTED** | Unit tests over synthetic evidence, the macOS launcher test with the mock, and the OpenShell run above (evidence uploaded into the sandbox flips readiness). |
| Real local model inside a boundary | **TESTED** | `plva-pr-local` is the sandbox's main process; model load about 25 s (CPU, 2 vCPU); `/v1/approve` 37-98 s per request (see section 11). |

`sandbox-exec` is deprecated by Apple (still shipped and functional on macOS 26, but
undocumented and unsupported). It confines one process tree with a Seatbelt profile; it does
**not** create a network namespace, and it is **not equivalent** to OpenShell. It is provided
only so the evidence pipeline and readiness gating can be exercised with synthetic values on
a developer Mac without Docker.

## 2. Platform findings: NVIDIA OpenShell / NemoClaw

Researched 2026-09-08 from the NVIDIA docs and GitHub (links at the end).

- **What it is.** OpenShell is NVIDIA's sandboxed runtime for autonomous agents: a gateway
  that launches sandboxes (Docker/Podman/microVM drivers), enforces a declarative YAML policy
  covering filesystem (Landlock), process identity, and network, and fronts all outbound
  traffic with a deny-by-default L7 proxy. NemoClaw is a reference stack layered on top of
  OpenShell (agent presets, managed inference, lifecycle); for this module only OpenShell's
  sandbox + policy layer is relevant.
- **Install (as found here).** NVIDIA's installer put a Homebrew formula on the Mac:
  `openshell` 0.0.116 and `openshell-gateway` 0.0.116 in `/opt/homebrew/bin`, mTLS material
  in `/opt/homebrew/var/openshell/tls`, a launchd service `sh.brew.openshell`. That service
  cannot start on a Colima Docker because launchd has no `DOCKER_HOST` (section 11).
- **Docker driver, observed.** The gateway pulls `ghcr.io/nvidia/openshell/supervisor:0.0.116`,
  extracts a static `openshell-sandbox` supervisor binary to `~/.local/share/openshell/` and
  bind-mounts it into every sandbox container as the ENTRYPOINT (`/opt/openshell/bin/openshell-sandbox`).
  The container runs as root with `SYS_ADMIN`, `NET_ADMIN`, `SYS_PTRACE`, `SYSLOG` on a dedicated
  `openshell-docker` network; the supervisor then creates a *second*, private network namespace
  (`10.200.0.2/24`, default route `10.200.0.1`) for the sandboxed process, installs nftables
  REJECT rules and a policy DNS/proxy listener at `10.200.0.1:3128`, applies Landlock, drops to
  the policy user, and execs the main command. Image requirements it enforces: an OCI `USER`
  (or `process.run_as_user`), a workspace (`WORKDIR`) writable by that user, and trusted `ip`
  and `nft` helpers in the image (`iproute2`, `nftables`), otherwise the container exits with a
  clear error (section 11).
- **Policy schema (real).** `openshell sandbox get <name> --policy-only` prints the effective
  policy. Sections: `version: 1`, `filesystem_policy` (`include_workdir`, `read_only`,
  `read_write`), `landlock.compatibility`, `process.run_as_user/run_as_group`, and the dynamic
  `network_policies` map (`openshell policy set <sandbox> --policy file --wait`). `network_policies: {}`
  denies everything; the gateway log line for a denied connection is
  `NET:OPEN [MED] DENIED /usr/local/bin/python3.12(<pid>) -> example.com:443 [policy:- engine:opa] [reason:network connections not allowed by policy]`.
- **Enforcement (observed inside, `deny_check.py --backend openshell`).** The supervisor injects
  `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY=http://10.200.0.1:3128`, `NO_PROXY=127.0.0.1,localhost,::1`
  and CA-bundle variables. HTTPS via that proxy: `Tunnel connection failed: 403`. Direct TCP to
  an IP: `ECONNREFUSED` in under 10 ms (nft reject with tcp-reset). UDP `sendto`: `EPERM`.
  `getaddrinfo`: `EAI_AGAIN` in about 1 ms (`/etc/resolv.conf` points at `127.0.0.11`, which
  has no listener inside the namespace). Loopback proxy on `:1`: `ECONNREFUSED`. Nothing times
  out, so no probe is `inconclusive`. `openshell sandbox exec` runs under the same policy: each
  exec re-applies Landlock (`rules_applied:10`), runs as `sandbox`, in the same netns.
- **Mounts.** `openshell sandbox create` has no mount flag; the docker driver accepts
  `--driver-config-json '{"docker":{"mounts":[{"type":"bind","source":"<abs host path>","target":"/models","read_only":true}]}}'`
  only when the gateway config has `[openshell.drivers.docker] enable_bind_mounts = true`
  (`sandbox/openshell-gateway.sh` writes that TOML and passes `--config`).
- **Inbound.** `openshell forward service <sandbox> --target-port P --local 127.0.0.1:P` (gRPC
  relay to the sandbox's loopback; "phase 1 accepts loopback only"). The relay presents the
  host-side `Host:` header to the service, and the service's allowlist is built from its own
  bind port, so the launcher uses the same port number (18575) inside and outside.

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
- OpenShell backend (tested): the credential is written to `/tmp/plva-pr/credential` (0600,
  owner `sandbox`) inside the sandbox and copied out with `openshell sandbox exec -- cat`, i.e.
  over the gateway's mTLS gRPC exec channel, not over any sandbox network socket. `stop.sh`
  deletes the host copy and the sandbox (default) or scrubs the in-sandbox copy (`--keep-sandbox`).
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
4. Run `sandbox/deny_check.py --negative-control` unsandboxed to prove the same probes succeed
   when nothing restricts them (`negative-control.json`). macos-dev: on the host. openshell: in a
   plain `docker run` container from the same image (no supervisor, default bridge network),
   because `verify_isolation.py` requires the control to come from the same platform
   (system + machine) as the boundary and the boundary is Linux/aarch64, not macOS.
   `--skip-negative-control` exists for offline hosts and is printed loudly because it lowers
   assurance.
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

| Observation | sandbox-exec (tested) | OpenShell (tested 2026-09-08) | Negative control |
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

**OpenShell.** No (observed). The sandboxed process has a private network namespace whose only
neighbour is the supervisor's proxy; the forward is a gRPC relay: a listener on host loopback
that the supervisor connects *into* the sandbox's `127.0.0.1:18575`. A TCP connection is
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

# OpenShell (TESTED on this Mac: openshell 0.0.116, Docker via Colima). First run builds the image.
sandbox/openshell-gateway.sh start                   # gateway w/ docker driver + Colima socket, loopback :17670
PLVA_PR_RUNTIME_DIR=$PWD/.plva-pr-openshell sandbox/start.sh --backend openshell   # host endpoint 127.0.0.1:18575
openshell logs plva-pr --since 5m | grep DENIED      # gateway-side corroboration
PLVA_PR_RUNTIME_DIR=$PWD/.plva-pr-openshell sandbox/stop.sh --backend openshell    # deletes the sandbox
sandbox/openshell-gateway.sh stop

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

- Inference inside the boundary is CPU-only (a Linux container on a 2-vCPU / 3 GiB Colima VM):
  `/v1/approve` takes 37-98 s here. The macOS Metal path is only available outside the
  OpenShell boundary (macos-dev fallback). A Linux host with a GPU (`--gpu`, CDI) or more
  vCPUs is the production shape.
- The negative control for the openshell backend runs in a plain container, not on the macOS
  host. It proves the probes work on the container platform with no policy; it does not prove
  anything about the Mac's own network.
- `openshell policy prove` is not used and not evidence; only the in-sandbox deny test is.
- UDP is fenced by nftables (`EPERM` on send), so `udp_dns_query` is a firm denial here; a
  runtime that silently drops instead of rejecting would make it `inconclusive`, which is the
  honest result.
- `sandbox-exec` provides no memory or process-count limits and no protection against a
  privileged host process.

## 11. OpenShell on this machine: blockers hit and how each was resolved

Everything below is literal output from 2026-09-08 (openshell 0.0.116, Docker 29.x via Colima
2 vCPU / 3 GiB, macOS 26.4, M2, 8 GB). No sudo was used; nothing was installed.

| Blocker | Literal error | Command | Resolution |
| --- | --- | --- | --- |
| Homebrew gateway service does not start | `configuration error: no compute driver configured and auto-detection found no suitable installed driver; set --drivers <name> or OPENSHELL_DRIVERS=<name>` | `brew services start openshell` (launchd has no `DOCKER_HOST`) | `sandbox/openshell-gateway.sh start` runs the same binary with `OPENSHELL_DRIVERS=docker DOCKER_HOST=unix://$HOME/.colima/default/docker.sock`, loopback bind, `--config` TOML, log in `.plva-pr/openshell-gateway.log`. Stop the brew service first if it is retrying. |
| No BuildKit on this Mac | `unknown flag: --progress` / `ERROR: BuildKit is enabled but the buildx component is missing or broken` | `docker build --progress=plain ...` / `DOCKER_BUILDKIT=1 docker build` (the `~/.docker/cli-plugins/*` symlinks point into an uninstalled Docker.app) | Legacy builder with a staged context (pyproject, README, LICENSE, src) so the 1.8 GB `models/` is not sent; `sandbox/Dockerfile.dockerignore` documents the intent for BuildKit users. `start.sh` builds this way when the image is missing (5 m 39 s cold, 16 s cached). |
| Image without a user | `OCI USER is required because run_as_user is omitted` | `openshell sandbox create --from python:3.12-slim` | Dockerfile: `useradd sandbox` + `USER sandbox`; policy `process.run_as_user: sandbox`. |
| Namespace helpers missing from a slim image | `Network namespace creation failed and proxy mode requires isolation. Ensure CAP_NET_ADMIN and CAP_SYS_ADMIN are available and iproute2 is installed. Error: trusted ip helper not found; checked /usr/sbin/ip, /sbin/ip, /usr/bin/ip, /bin/ip` (and, from the supervisor's strings, `trusted nft helper not found; policy DNS and transparent TCP require nftables`) | `openshell sandbox create --policy sandbox/policy.yaml` | Dockerfile installs `iproute2` and `nftables` in the runtime stage. |
| Workspace not writable | `image workspace validation failed: workspace path component '/tmp/plva-pr' is not writable by the sandbox identity in the image: Permission denied (os error 13)` | same | Dockerfile: `install -d -o sandbox -g sandbox -m 700 /tmp/plva-pr` before `WORKDIR`. |
| Bind mounts refused | `docker bind mounts require enable_bind_mounts = true in [openshell.drivers.docker]` | `openshell sandbox create --driver-config-json '{"docker":{"mounts":[...]}}'` | Gateway config TOML written by `openshell-gateway.sh`. Mount schema (from validation errors): `{"type":"bind","source","target","read_only","selinux_label"}`; other types `volume`, `tmpfs`, `image`. |
| `sandbox exec` hangs | no output, never returns | `openshell sandbox exec -n X --no-tty -- id` from a script with stdin open | Redirect stdin: `</dev/null` (start.sh `sbx_exec`). |
| `sandbox upload` treats DEST as a directory | `can't find '__main__' module in '/tmp/plva-pr/deny_check.py'` (a directory of that name was created) | `openshell sandbox upload X sandbox/deny_check.py /tmp/plva-pr/deny_check.py` | Upload to the directory `/tmp/plva-pr`. |
| Service rejects the forward | `{"schema_version":"1.0","error_code":"FORBIDDEN_HOST"}` | `curl http://127.0.0.1:18576/health` with the service on 18555 inside | Same port inside and out (18575). Lead-owned: `plva-pr-local` also refuses `--host 0.0.0.0` (`refusing to bind a non-loopback address`), which is fine because the forward targets loopback. |
| Negative control platform | `[verify-isolation] isolation=failed reasons=NEGATIVE_CONTROL_PLATFORM_MISMATCH` | host negative control (Darwin/arm64) vs sandbox evidence (Linux/aarch64) | Negative control runs in a plain container from the same image. |
| `sandbox upload` skips or fails | evidence upload: `ssh tar extract exited with status exit status: 2` (the runtime dir matches `.gitignore` `.plva-pr*/`, so the tar is empty); `--no-git-ignore`: the same `exit status: 2` even for a tracked file | `openshell sandbox upload [--no-git-ignore] plva-pr <file> /tmp/plva-pr` | Files are copied through the exec channel instead: `openshell sandbox exec -n plva-pr --no-tty -- sh -c 'cat > /tmp/plva-pr/<name>' < <file>` (`start.sh` `sbx_put`; sha256 verified equal inside). Same mTLS gRPC channel, same policy. |
| macos-dev with a `/var/folders` runtime dir | `service did not answer /health` | `start.sh --backend macos-dev --runtime-dir "$(mktemp -d)"` | Pre-existing: Seatbelt matches real paths; `start.sh` now resolves the runtime dir with `pwd -P`. |

Observed but not attributable to the boundary (for the service owner):

- The service runs llama.cpp synchronously inside `async def` handlers, so `/health` and
  `/v1/readiness` do not answer while an approve is being computed (28 s measured after one
  client-aborted approve). Five client-aborted approves in a row: `/health` answered `503`
  after 27.7 s (uvicorn `limit_concurrency=4`), then `/v1/readiness` 200 in 21 ms and
  `/health` 200 in 4 ms, so aborted requests do not wedge it.
- Once, after three clean approves (61.6 / 37.1 / 98.4 s) while a second container and the
  macos-dev test were also running on the 3 GiB VM (the sandbox's resident set fell from
  2.27 GiB to 687 MiB, i.e. the mmap'd weights were evicted), the service stopped accepting
  connections for good: `py-spy dump` showed `MainThread` idle in `selectors.select`, no CPU
  use, 7 connections waiting in the listen backlog (`/proc/net/tcp` rx_queue), one accepted
  socket in `CLOSE_WAIT`, llama threads idle. Not reproduced on a fresh launch. Keep the VM
  to one sandbox at a time, or give Colima more memory.
- `docker exec` as root in the sandbox *container* (the supervisor's namespace, outside the
  policy) has egress through the `openshell-docker` bridge (it downloaded a wheel). That
  context belongs to the driver/operator side of the boundary, not to the sandboxed process
  tree; it is how the supervisor talks to the gateway. Do not run workloads there.

Resource usage measured: image 432 MB; sandbox container 2.27 GiB resident (mostly page cache
for the mmap'd 1.83 GB GGUF), VM `free -m`: 2898 total / 904 used / 1994 available; model load
about 25 s from container start to first `/health`; full launcher 41 s cold, 26 s with the weights already in the VM page cache; `/v1/approve` 61.6 s,
37.1 s, 98.4 s (three requests, `contracts/v1/examples/approve-request.json`, HTTP 200,
`decision: approve`).

## Sources

- OpenShell repository: https://github.com/NVIDIA/openshell
- Policy schema reference: https://docs.nvidia.com/openshell/reference/policy-schema
- First network policy tutorial (denial behaviour, `policy set --wait`, logs): https://docs.nvidia.com/openshell/get-started/tutorials/first-network-policy
- NemoClaw repository and network-policy guide: https://github.com/NVIDIA/NemoClaw ,
  https://docs.nvidia.com/nemoclaw/latest/reference/network-policies.html
- Reference project lessons (not claims copied): `reference/browser-agent-privacy-layer/docs/local-llm-runbook.md`
