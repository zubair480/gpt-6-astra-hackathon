#!/usr/bin/env bash
# PLVA private reasoning: isolated service launcher.
#
#   sandbox/start.sh [--backend openshell|macos-dev] [--mock] [--port N] [--skip-negative-control]
#
# Backends
#   openshell   TARGET. NVIDIA OpenShell, Docker driver, Linux x86_64 host.
#               *** UNTESTED by the author: no `openshell` CLI or container runtime was
#               available on the macOS machine this was written on. Every openshell
#               command below follows the public docs and must be re-checked against
#               `openshell <cmd> --help` on the first real run. ***
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
IMAGE="${PLVA_PR_SANDBOX_IMAGE:-}"
TIMEOUT="${PLVA_PR_DENY_TIMEOUT:-5}"

say() { printf '\033[1m[plva-pr sandbox]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[plva-pr sandbox] FATAL:\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --backend) BACKEND="$2"; shift 2 ;;
    --mock) MOCK=1; shift ;;
    --port) PORT="$2"; shift 2 ;;
    --runtime-dir) RUNTIME_DIR="$2"; shift 2 ;;
    --skip-negative-control) SKIP_NEGATIVE=1; shift ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

if [ -z "$BACKEND" ]; then
  if command -v openshell >/dev/null 2>&1 && [ "$(uname -s)" = Linux ]; then BACKEND=openshell
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

wait_health() {
  for _ in $(seq 1 60); do
    curl -fsS -m 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && return 0
    sleep 0.5
  done
  return 1
}

readiness_field() {  # $1 = field name
  local cred; cred="$(cat "$RUNTIME_DIR/credential")"
  curl -fsS -m 5 -H "Authorization: Bearer $cred" "http://127.0.0.1:$PORT/v1/readiness" \
    | "$PY" -c "import json,sys; print(json.load(sys.stdin)['$1'])"
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
  [ "$(uname -s)" = Linux ] || say "WARNING: openshell backend is written for Linux x86_64; other hosts are untested"
  [ -n "$IMAGE" ] || die "PLVA_PR_SANDBOX_IMAGE must name a pre-provisioned image (service + runtime + /models baked in)"
  POLICY="$HERE/policy.yaml"
  say "backend=openshell (UNTESTED launcher path) policy=$POLICY sandbox=$SANDBOX_NAME"

  say "0/6 ensuring gateway and sandbox exist"
  openshell status >/dev/null 2>&1 || die "openshell gateway not connected; run: openshell gateway start"
  if ! openshell sandbox list 2>/dev/null | grep -q "^$SANDBOX_NAME\b"; then
    # Static policy sections (filesystem, landlock, process) are fixed here; verify the exact
    # image flag with `openshell sandbox create --help` (the docs show `--from <preset>` and
    # `-- <agent>` forms). --no-auto-providers keeps managed inference credentials out.
    openshell sandbox create --name "$SANDBOX_NAME" --policy "$POLICY" --no-auto-providers \
      --from "$IMAGE" || die "sandbox create failed"
  fi
  # Re-apply the dynamic network section and WAIT for propagation before trusting it.
  openshell policy set "$SANDBOX_NAME" --policy "$POLICY" --wait || die "policy set failed"

  say "1/6 starting service inside the sandbox"
  INNER_CMD="/app/.venv/bin/$(basename "$ENTRY") --host 127.0.0.1 --port $PORT --runtime-dir /tmp/plva-pr"
  openshell sandbox exec -n "$SANDBOX_NAME" --timeout 20 -- sh -c \
    "env -i PATH=/usr/bin:/bin nohup $INNER_CMD >/tmp/plva-pr/service.log 2>&1 &" \
    || die "could not start service in sandbox"

  say "1b/6 forwarding host 127.0.0.1:$PORT -> sandbox:$PORT (inbound only)"
  nohup openshell forward service "$SANDBOX_NAME" --target-port "$PORT" --local "127.0.0.1:$PORT" \
    >"$RUNTIME_DIR/forward.log" 2>&1 &
  echo $! >"$RUNTIME_DIR/forward.pid"
  wait_health || die "service did not answer /health through the forward"

  # The credential crosses the boundary over the gateway exec channel, never the network.
  openshell sandbox exec -n "$SANDBOX_NAME" --timeout 10 -- cat /tmp/plva-pr/credential \
    >"$RUNTIME_DIR/credential"; chmod 600 "$RUNTIME_DIR/credential"

  say "2/6 reading instance_id from /v1/readiness"
  INSTANCE_ID="$(readiness_field instance_id)"

  say "3/6 running deny checks INSIDE the sandbox"
  POLICY_SHA="$("$PY" -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$POLICY")"
  openshell sandbox upload "$SANDBOX_NAME" "$HERE/deny_check.py" /tmp/plva-pr/deny_check.py
  set +e
  openshell sandbox exec -n "$SANDBOX_NAME" --timeout 90 -- /app/.venv/bin/python /tmp/plva-pr/deny_check.py \
    --backend openshell --instance-id "$INSTANCE_ID" --policy-sha256 "$POLICY_SHA" \
    --policy-name policy.yaml --timeout "$TIMEOUT" --output - >"$DENY_EVIDENCE"
  DENY_RC=$?
  set -e
  say "deny_check exit=$DENY_RC (0 = all denied, 2 = inconclusive, 3 = egress observed)"
  say "gateway-side corroboration: openshell logs $SANDBOX_NAME --since 5m | grep action=deny"
  ;;
*) die "unknown backend: $BACKEND" ;;
esac

# ------------------------------------------------------------------------------ common tail
NEG_ARGS=()
if [ "$SKIP_NEGATIVE" = 1 ]; then
  say "4/6 SKIPPED negative control (resolver-based denials are uncorroborated; lower assurance)"
else
  say "4/6 running negative control on the HOST, unsandboxed (proves the probes are valid here)"
  set +e
  "$PY" "$HERE/deny_check.py" --negative-control --timeout "$TIMEOUT" --output "$NEG_EVIDENCE"
  NEG_RC=$?
  set -e
  [ "$NEG_RC" = 0 ] || say "negative control exit=$NEG_RC: host has no working network; verification will fail"
  NEG_ARGS=(--negative-control "$NEG_EVIDENCE")
fi

say "5/6 verifying evidence on the host"
EXPECTED_BACKEND=sandbox-exec; [ "$BACKEND" = openshell ] && EXPECTED_BACKEND=openshell
set +e
"$PY" "$HERE/verify_isolation.py" --evidence "$DENY_EVIDENCE" --policy "$POLICY" \
  --output "$ISO_EVIDENCE" --readiness-url "http://127.0.0.1:$PORT/v1/readiness" \
  --credential-file "$RUNTIME_DIR/credential" --expected-backend "$EXPECTED_BACKEND" "${NEG_ARGS[@]}"
VERIFY_RC=$?
set -e

if [ "$VERIFY_RC" != 0 ]; then
  say "6/6 isolation NOT verified: stopping the service (fail closed)"
  "$HERE/stop.sh" --backend "$BACKEND" --runtime-dir "$RUNTIME_DIR" >/dev/null 2>&1 || true
  die "isolation verification failed; see $ISO_EVIDENCE and $DENY_EVIDENCE"
fi
say "6/6 isolation VERIFIED for instance $INSTANCE_ID"
say "evidence:   $ISO_EVIDENCE   (pass as --isolation-evidence to plva-pr-local)"
say "credential: $RUNTIME_DIR/credential   endpoint: http://127.0.0.1:$PORT"
[ "$BACKEND" = macos-dev ] && say "REMINDER: macos-dev is a sandbox-exec dev fallback, not OpenShell; synthetic values only"
exit 0
