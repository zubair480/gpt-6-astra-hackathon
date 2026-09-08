#!/usr/bin/env bash
# PLVA private reasoning: stop the isolated service and INVALIDATE its isolation evidence.
#
#   sandbox/stop.sh [--backend openshell|macos-dev] [--runtime-dir DIR] [--keep-sandbox]
#
# Removing isolation-evidence.json here is deliberate: evidence is bound to the instance_id
# of the process being stopped and must never be reused by the next launch (acceptance
# test 9). openshell backend (TESTED with openshell 0.0.116, Docker driver on Colima): stops
# the host-side forward and DELETES the sandbox (start.sh creates a fresh one every launch;
# the service is its main process, so stopping it means deleting it). --keep-sandbox only
# stops the forward and scrubs the in-sandbox credential/evidence. The gateway itself is left
# running; stop it with sandbox/openshell-gateway.sh stop.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
BACKEND="${PLVA_PR_SANDBOX_BACKEND:-}"
RUNTIME_DIR="${PLVA_PR_RUNTIME_DIR:-$ROOT/.plva-pr}"
SANDBOX_NAME="${PLVA_PR_SANDBOX_NAME:-plva-pr}"
DELETE=1

say() { printf '\033[1m[plva-pr sandbox]\033[0m %s\n' "$*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --backend) BACKEND="$2"; shift 2 ;;
    --runtime-dir) RUNTIME_DIR="$2"; shift 2 ;;
    --delete) DELETE=1; shift ;;
    --keep-sandbox) DELETE=0; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$BACKEND" ]; then
  if [ -f "$RUNTIME_DIR/forward.pid" ]; then BACKEND=openshell; else BACKEND=macos-dev; fi
fi

stop_pid_file() {  # $1 = pid file
  [ -f "$1" ] || return 0
  local pid; pid="$(cat "$1")"
  if kill -0 "$pid" 2>/dev/null; then
    kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "$1"
}

case "$BACKEND" in
  macos-dev)
    stop_pid_file "$RUNTIME_DIR/service.pid"
    say "service stopped (macos-dev)"
    ;;
  openshell)
    stop_pid_file "$RUNTIME_DIR/forward.pid"
    if command -v openshell >/dev/null 2>&1 && openshell sandbox list --names 2>/dev/null | grep -qx "$SANDBOX_NAME"; then
      if [ "$DELETE" = 1 ]; then
        openshell sandbox delete "$SANDBOX_NAME" >/dev/null 2>&1 || true
        say "sandbox $SANDBOX_NAME deleted (service, credential and in-sandbox evidence gone with it)"
      else
        openshell sandbox exec -n "$SANDBOX_NAME" --no-tty --timeout 15 -- \
          rm -f /tmp/plva-pr/credential /tmp/plva-pr/isolation-evidence.json /tmp/plva-pr/deny-check.json \
          >/dev/null 2>&1 || true
        say "sandbox $SANDBOX_NAME kept; in-sandbox credential and evidence removed (service still running, unready)"
      fi
    fi
    say "forward stopped (openshell)"
    ;;
  *) echo "unknown backend: $BACKEND" >&2; exit 2 ;;
esac

# Invalidate: evidence for the stopped instance must not survive it.
rm -f "$RUNTIME_DIR/isolation-evidence.json" "$RUNTIME_DIR/deny-check.json" \
      "$RUNTIME_DIR/negative-control.json" "$RUNTIME_DIR/credential"
say "isolation evidence and credential removed from $RUNTIME_DIR"
exit 0
