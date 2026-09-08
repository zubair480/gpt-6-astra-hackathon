#!/usr/bin/env bash
# PLVA private reasoning: isolated service launcher.
#
#   sandbox/start.sh [--backend openshell|macos-dev] [--mock] [--port N] [--skip-negative-control]
#
# Backends
#   openshell   TARGET. NVIDIA OpenShell, Docker driver.
#               TESTED 2026-09-08: openshell 0.0.116 + openshell-gateway 0.0.116 (Homebrew),
#               Docker 29.x via Colima (vz, aarch64, 2 vCPU / 3 GiB), macOS 26.4 Apple Silicon,
#               image sandbox/Dockerfile (python:3.12-slim, llama-cpp-python 0.3.35 CPU).
#               Needs: sandbox/openshell-gateway.sh start (gateway with DOCKER_HOST), and the
#               image (built here on first run, or PLVA_PR_SANDBOX_IMAGE=<ref>).
#               Host side of the service is 127.0.0.1:$PLVA_PR_HOST_PORT (default 18575),
#               an inbound-only gRPC forward into the sandbox's loopback :$PORT.
#   macos-dev   DEV-ONLY fallback: Apple `sandbox-exec` with sandbox/macos-dev.sb.
#               Tested on macOS 26.4 / Apple Silicon. NOT equivalent to OpenShell; use
#               with synthetic values only. sandbox-exec is deprecated by Apple.
#
# Sequence (both backends)
#   1. launch the service inside the boundary
#   2. read its per-launch credential and /v1/readiness instance_id from the host
#   3. run sandbox/deny_check.py INSIDE the same boundary -> deny-check.json
#   4. (unless --skip-negative-control) run deny_check.py --negative-control on the host,
#      unsandboxed, to prove the probes are valid on this machine -> negative-control.json
#   5. run sandbox/verify_isolation.py on the host -> isolation-evidence.json
#   6. hard-fail: if verification is not "verified", stop the service and exit 1.
#
# The service never becomes ready_for_private_values on its own; it reads
# isolation-evidence.json (path printed at the end) via `plva-pr-local --isolation-evidence`.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
BACKEND="${PLVA_PR_SANDBOX_BACKEND:-}"
MOCK=0
PORT="${PLVA_PR_PORT:-18555}"
RUNTIME_DIR="${PLVA_PR_RUNTIME_DIR:-$ROOT/.plva-pr}"
SKIP_NEGATIVE=0
# Loopback port the sandboxed service may connect to (subprocess llama-server). Empty = none.
INNER_PORT="${PLVA_PR_INNER_PORT:-}"
SANDBOX_NAME="${PLVA_PR_SANDBOX_NAME:-plva-pr}"
IMAGE="${PLVA_PR_SANDBOX_IMAGE:-plva-pr-sandbox:local}"
TIMEOUT="${PLVA_PR_DENY_TIMEOUT:-5}"
# openshell backend only: host loopback port of the inbound forward, memory cap, model dir.
HOST_PORT="${PLVA_PR_HOST_PORT:-18575}"
SANDBOX_MEMORY="${PLVA_PR_SANDBOX_MEMORY:-}"
MODELS_DIR="${PLVA_PR_MODELS_DIR:-$ROOT/models}"
# In-sandbox runtime dir (writable per policy.yaml) and paths of the installed package.
INNER_RUNTIME=/tmp/plva-pr
INNER_PY=/app/.venv/bin/python

say() { printf '\033[1m[plva-pr sandbox]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[plva-pr sandbox] FATAL:\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --backend) BACKEND="$2"; shift 2 ;;
    --mock) MOCK=1; shift ;;
    --port) PORT="$2"; shift 2 ;;
    --runtime-dir) RUNTIME_DIR="$2"; shift 2 ;;
    --skip-negative-control) SKIP_NEGATIVE=1; shift ;;
    --host-port) HOST_PORT="$2"; shift 2 ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

if [ -z "$BACKEND" ]; then
  # openshell is chosen automatically only when a gateway is already connected.
  if command -v openshell >/dev/null 2>&1 && openshell status >/dev/null 2>&1; then BACKEND=openshell
  elif [ "$(uname -s)" = Darwin ] && [ -x /usr/bin/sandbox-exec ]; then BACKEND=macos-dev
  else die "no supported backend: need openshell on Linux, or sandbox-exec on macOS (dev only)"; fi
fi

mkdir -p "$RUNTIME_DIR"; chmod 700 "$RUNTIME_DIR"
RUNTIME_DIR="$(cd "$RUNTIME_DIR" && pwd)"
DENY_EVIDENCE="$RUNTIME_DIR/deny-check.json"
NEG_EVIDENCE="$RUNTIME_DIR/negative-control.json"
ISO_EVIDENCE="$RUNTIME_DIR/isolation-evidence.json"
PID_FILE="$RUNTIME_DIR/service.pid"
rm -f "$DENY_EVIDENCE" "$ISO_EVIDENCE" "$RUNTIME_DIR/credential"

PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || die "no .venv; run: uv sync"
if [ "$MOCK" = 1 ]; then
  ENTRY="$ROOT/.venv/bin/plva-pr-mock"
  say "MOCK mode: exercising the launcher only; the mock is never ready for private values"
else
  ENTRY="$ROOT/.venv/bin/plva-pr-local"
  [ -x "$ENTRY" ] || die "plva-pr-local entrypoint missing (model track); use --mock to test the launcher"
fi

# macos-dev talks to the service port directly. openshell talks to the host-side forward, and
# the service inside listens on the SAME port number: its Host-header allowlist is built from
# its own bind port, so a forward to a different host port answers 403 FORBIDDEN_HOST.
if [ "$BACKEND" = openshell ]; then PORT="$HOST_PORT"; else HOST_PORT="$PORT"; fi

wait_health() {  # $1 = max tries (0.5 s apart)
  for _ in $(seq 1 "${1:-60}"); do
    curl -fsS -m 2 "http://127.0.0.1:$HOST_PORT/health" >/dev/null 2>&1 && return 0
    sleep 0.5
  done
  return 1
}

readiness_field() {  # $1 = field name
  local cred; cred="$(cat "$RUNTIME_DIR/credential")"
  curl -fsS -m 5 -H "Authorization: Bearer $cred" "http://127.0.0.1:$HOST_PORT/v1/readiness" \
    | "$PY" -c "import json,sys; print(json.load(sys.stdin)['$1'])"
}

sbx_exec() {  # run a command inside the sandbox (policy, netns and user apply): sbx_exec [--timeout N] -- cmd...
  # stdin must be closed: with an open stdin `sandbox exec` waits for EOF and never returns.
  openshell sandbox exec -n "$SANDBOX_NAME" --no-tty "$@" </dev/null
}

case "$BACKEND" in
# ------------------------------------------------------------------------------ macos-dev
macos-dev)
  [ "$(uname -s)" = Darwin ] || die "macos-dev backend only runs on macOS"
  POLICY="$HERE/macos-dev.sb"
  say "backend=macos-dev (sandbox-exec, DEV ONLY, not OpenShell) policy=$POLICY"
  SBX=(/usr/bin/sandbox-exec -f "$POLICY" -D "service_port=$PORT" -D "write_dir=$RUNTIME_DIR")
  if [ -n "$INNER_PORT" ]; then
    SBX+=(-D "inner_port=$INNER_PORT")
    say "WARNING: loopback outbound to 127.0.0.1:$INNER_PORT is allowed for a subprocess llama-server"
  fi

  say "1/6 starting service inside sandbox-exec on 127.0.0.1:$PORT"
  # Environment is scrubbed: no proxy variables reach the boundary.
  env -i HOME="$HOME" PATH=/usr/bin:/bin LANG=C.UTF-8 PLVA_PR_RUNTIME_DIR="$RUNTIME_DIR" \
    "${SBX[@]}" "$ENTRY" --host 127.0.0.1 --port "$PORT" --runtime-dir "$RUNTIME_DIR" \
    >"$RUNTIME_DIR/service.log" 2>&1 &
  echo $! >"$PID_FILE"
  wait_health || { "$HERE/stop.sh" --backend macos-dev --runtime-dir "$RUNTIME_DIR" >/dev/null || true; die "service did not answer /health (see $RUNTIME_DIR/service.log)"; }

  say "2/6 reading instance_id from /v1/readiness"
  INSTANCE_ID="$(readiness_field instance_id)"
  say "instance_id=$INSTANCE_ID"

  say "3/6 running deny checks INSIDE the same sandbox-exec profile"
  set +e
  env -i PATH=/usr/bin:/bin LANG=C.UTF-8 "${SBX[@]}" "$PY" "$HERE/deny_check.py" \
    --backend sandbox-exec --instance-id "$INSTANCE_ID" --policy "$POLICY" \
    --timeout "$TIMEOUT" --output "$DENY_EVIDENCE"
  DENY_RC=$?
  set -e
  say "deny_check exit=$DENY_RC (0 = all denied, 2 = inconclusive, 3 = egress observed)"
  ;;
# ------------------------------------------------------------------------------ openshell
openshell)
  command -v openshell >/dev/null 2>&1 || die "openshell CLI not found (install: https://github.com/NVIDIA/OpenShell)"
  POLICY="$HERE/policy.yaml"
  export DOCKER_HOST="${DOCKER_HOST:-unix://$HOME/.colima/default/docker.sock}"
  say "backend=openshell policy=$POLICY sandbox=$SANDBOX_NAME image=$IMAGE host_port=$HOST_PORT"

  say "0/6 checking gateway, image and model"
  openshell status >/dev/null 2>&1 || die "openshell gateway not connected; run: $HERE/openshell-gateway.sh start"
  if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    [ "$IMAGE" = plva-pr-sandbox:local ] || die "image $IMAGE not present in the docker daemon"
    # Build with a staged context: the legacy builder (no buildx on this Mac) would otherwise
    # ship the 1.8 GB models/ directory as build context. Takes several minutes (llama.cpp).
    CTX="$(mktemp -d "${TMPDIR:-/tmp}/plva-pr-ctx.XXXXXX")"
    cp "$ROOT/pyproject.toml" "$ROOT/README.md" "$ROOT/LICENSE" "$CTX/"
    rsync -a --exclude '__pycache__' "$ROOT/src" "$CTX/"
    say "building $IMAGE from $HERE/Dockerfile (several minutes, log: $RUNTIME_DIR/docker-build.log)"
    docker build --platform linux/arm64 -f "$HERE/Dockerfile" -t "$IMAGE" "$CTX" >"$RUNTIME_DIR/docker-build.log" 2>&1 \
      || { rm -rf "$CTX"; die "image build failed; see $RUNTIME_DIR/docker-build.log"; }
    rm -rf "$CTX"
  fi
  MODELS_DIR="$(cd "$MODELS_DIR" && pwd)"
  MODEL_FILE="$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1]))['filename'])" "$ROOT/src/plva_private_reasoning/model/manifest.json")"
  [ "$MOCK" = 1 ] || [ -f "$MODELS_DIR/$MODEL_FILE" ] || die "model $MODELS_DIR/$MODEL_FILE missing; run scripts/provision_model.sh"
  POLICY_SHA="$("$PY" -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$POLICY")"

  say "1/6 creating sandbox $SANDBOX_NAME (fresh every launch) and starting the service inside"
  if openshell sandbox list --names 2>/dev/null | grep -qx "$SANDBOX_NAME"; then
    openshell sandbox delete "$SANDBOX_NAME" >/dev/null || die "could not delete stale sandbox $SANDBOX_NAME"
  fi
  # Model weights: host models/ bind-mounted READ-ONLY at /models (docker driver config; the
  # sandbox policy also lists /models as read_only). Nothing else from the host is mounted.
  DRIVER_JSON="$("$PY" -c 'import json,sys;print(json.dumps({"docker":{"mounts":[{"type":"bind","source":sys.argv[1],"target":"/models","read_only":True}]}}))' "$MODELS_DIR")"
  CREATE_ARGS=(--name "$SANDBOX_NAME" --from "$IMAGE" --policy "$POLICY" --no-auto-providers
               --detach --no-tty --driver-config-json "$DRIVER_JSON")
  [ -n "$SANDBOX_MEMORY" ] && CREATE_ARGS+=(--memory "$SANDBOX_MEMORY")
  if [ "$MOCK" = 1 ]; then
    INNER_CMD=(/app/.venv/bin/plva-pr-mock --host 127.0.0.1 --port "$PORT" --runtime-dir "$INNER_RUNTIME")
  else
    # --n-gpu-layers 0: CPU-only inside the container. --policy-sha256 binds readiness to this policy.
    INNER_CMD=(/app/.venv/bin/plva-pr-local --host 127.0.0.1 --port "$PORT" --runtime-dir "$INNER_RUNTIME"
               --model-path "/models/$MODEL_FILE" --n-gpu-layers 0 --policy-sha256 "$POLICY_SHA")
  fi
  # The service IS the sandbox's main process: the supervisor applies policy.yaml (Landlock,
  # run_as_user, private netns with deny-all rules) before exec'ing it. No proxy env is set.
  openshell sandbox create "${CREATE_ARGS[@]}" -- "${INNER_CMD[@]}" >"$RUNTIME_DIR/sandbox-create.log" 2>&1 </dev/null \
    || { cat "$RUNTIME_DIR/sandbox-create.log" >&2; die "sandbox create failed"; }

  say "1b/6 forwarding host 127.0.0.1:$HOST_PORT -> sandbox 127.0.0.1:$PORT (inbound only, gRPC)"
  nohup openshell forward service "$SANDBOX_NAME" --target-port "$PORT" --local "127.0.0.1:$HOST_PORT" \
    >"$RUNTIME_DIR/forward.log" 2>&1 </dev/null &
  echo $! >"$RUNTIME_DIR/forward.pid"
  # Model load on 2 vCPU is slow (tens of seconds); allow up to 5 minutes.
  wait_health 600 || { openshell logs "$SANDBOX_NAME" -n 40 >&2 || true; "$HERE/stop.sh" --backend openshell --runtime-dir "$RUNTIME_DIR" >/dev/null || true; die "service did not answer /health through the forward"; }

  # The credential crosses the boundary over the gateway exec channel, never the network.
  sbx_exec --timeout 10 -- cat "$INNER_RUNTIME/credential" >"$RUNTIME_DIR/credential" \
    || die "could not read the credential from the sandbox"
  chmod 600 "$RUNTIME_DIR/credential"

  say "2/6 reading instance_id from /v1/readiness"
  INSTANCE_ID="$(readiness_field instance_id)"
  say "instance_id=$INSTANCE_ID"

  say "3/6 running deny checks INSIDE the sandbox (same netns, user and policy as the service)"
  # DEST is a directory: the file lands at $INNER_RUNTIME/deny_check.py.
  openshell sandbox upload "$SANDBOX_NAME" "$HERE/deny_check.py" "$INNER_RUNTIME" >/dev/null </dev/null \
    || die "could not upload deny_check.py"
  set +e
  sbx_exec --timeout 120 -- "$INNER_PY" "$INNER_RUNTIME/deny_check.py" \
    --backend openshell --instance-id "$INSTANCE_ID" --policy-sha256 "$POLICY_SHA" \
    --policy-name policy.yaml --timeout "$TIMEOUT" --output - >"$DENY_EVIDENCE"
  DENY_RC=$?
  set -e
  say "deny_check exit=$DENY_RC (0 = all denied, 2 = inconclusive, 3 = egress observed)"
  say "gateway-side corroboration: openshell logs $SANDBOX_NAME --since 5m"
  ;;
*) die "unknown backend: $BACKEND" ;;
esac

# ------------------------------------------------------------------------------ common tail
NEG_ARGS=()
if [ "$SKIP_NEGATIVE" = 1 ]; then
  say "4/6 SKIPPED negative control (resolver-based denials are uncorroborated; lower assurance)"
else
  set +e
  if [ "$BACKEND" = openshell ]; then
    # The boundary is a Linux container; the negative control must come from the same platform
    # (verify_isolation.py compares system/machine). Run the same probes in a plain, unpolicied
    # container from the same image on the same Docker daemon: no OpenShell supervisor, no
    # namespace, default bridge network. Same kernel, same Python, no restrictions.
    say "4/6 running negative control in an UNRESTRICTED plain container from $IMAGE (same platform as the boundary)"
    docker run --rm --platform linux/arm64 -v "$HERE/deny_check.py:/deny_check.py:ro" "$IMAGE" \
      "$INNER_PY" /deny_check.py --negative-control --timeout "$TIMEOUT" --output - >"$NEG_EVIDENCE" </dev/null
    NEG_RC=$?
  else
    say "4/6 running negative control on the HOST, unsandboxed (proves the probes are valid here)"
    "$PY" "$HERE/deny_check.py" --negative-control --timeout "$TIMEOUT" --output "$NEG_EVIDENCE"
    NEG_RC=$?
  fi
  set -e
  [ "$NEG_RC" = 0 ] || say "negative control exit=$NEG_RC: host has no working network; verification will fail"
  NEG_ARGS=(--negative-control "$NEG_EVIDENCE")
fi

say "5/6 verifying evidence on the host"
EXPECTED_BACKEND=sandbox-exec; [ "$BACKEND" = openshell ] && EXPECTED_BACKEND=openshell
set +e
"$PY" "$HERE/verify_isolation.py" --evidence "$DENY_EVIDENCE" --policy "$POLICY" \
  --output "$ISO_EVIDENCE" --readiness-url "http://127.0.0.1:$HOST_PORT/v1/readiness" \
  --credential-file "$RUNTIME_DIR/credential" --expected-backend "$EXPECTED_BACKEND" "${NEG_ARGS[@]}"
VERIFY_RC=$?
set -e

if [ "$VERIFY_RC" != 0 ]; then
  say "6/6 isolation NOT verified: stopping the service (fail closed)"
  "$HERE/stop.sh" --backend "$BACKEND" --runtime-dir "$RUNTIME_DIR" >/dev/null 2>&1 || true
  die "isolation verification failed; see $ISO_EVIDENCE and $DENY_EVIDENCE"
fi
say "6/6 isolation VERIFIED for instance $INSTANCE_ID"
if [ "$BACKEND" = openshell ]; then
  # The service re-reads <runtime-dir>/isolation-evidence.json on every readiness check; put the
  # verified document where the in-sandbox service looks (upload goes over the gateway channel).
  openshell sandbox upload "$SANDBOX_NAME" "$ISO_EVIDENCE" "$INNER_RUNTIME" >/dev/null </dev/null \
    || die "could not upload isolation evidence into the sandbox"
  READY="$(readiness_field ready_for_private_values)"
  say "service readiness after evidence upload: ready_for_private_values=$READY"
  [ "$READY" = True ] || [ "$MOCK" = 1 ] || die "service did not flip to ready (see $RUNTIME_DIR/service readiness)"
fi
say "evidence:   $ISO_EVIDENCE   (pass as --isolation-evidence to plva-pr-local)"
say "credential: $RUNTIME_DIR/credential   endpoint: http://127.0.0.1:$HOST_PORT"
[ "$BACKEND" = macos-dev ] && say "REMINDER: macos-dev is a sandbox-exec dev fallback, not OpenShell; synthetic values only"
exit 0
