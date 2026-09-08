#!/usr/bin/env bash
# PLVA private reasoning: run the NVIDIA OpenShell gateway manually with the Docker driver.
#
#   sandbox/openshell-gateway.sh start|stop|status|register
#
# Why manual: the Homebrew launchd service (sh.brew.openshell) has no DOCKER_HOST in its
# environment, so on a Colima/Lima Docker it fails with
#   "no compute driver configured and auto-detection found no suitable installed driver".
# This script starts the same binary with the docker driver pointed at the Colima socket,
# bound to loopback only, and logs to <runtime-dir>/openshell-gateway.log.
#
# TESTED: openshell 0.0.116 / openshell-gateway 0.0.116 (Homebrew), Docker 29.x via Colima
# (vz, aarch64), macOS 26.4 Apple Silicon.
#
# Environment (all optional)
#   DOCKER_HOST               default unix://$HOME/.colima/default/docker.sock
#   OPENSHELL_LOCAL_TLS_DIR   mTLS material laid out by the Homebrew wrapper
#                             (default $HOME/.local/state/openshell/homebrew/tls)
#   OPENSHELL_GATEWAY_PORT    default 17670 (the endpoint the CLI is registered against)
#   PLVA_PR_RUNTIME_DIR       where pid + log go (default <repo>/.plva-pr)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
RUNTIME_DIR="${PLVA_PR_RUNTIME_DIR:-$ROOT/.plva-pr}"
PORT="${OPENSHELL_GATEWAY_PORT:-17670}"
BIND="127.0.0.1"
ENDPOINT="https://localhost:$PORT"
TLS_DIR="${OPENSHELL_LOCAL_TLS_DIR:-$HOME/.local/state/openshell/homebrew/tls}"
BREW_TLS_SRC="${OPENSHELL_BREW_TLS_SRC:-/opt/homebrew/var/openshell/tls}"
export DOCKER_HOST="${DOCKER_HOST:-unix://$HOME/.colima/default/docker.sock}"
export OPENSHELL_DRIVERS=docker
export OPENSHELL_LOCAL_TLS_DIR="$TLS_DIR"
PID_FILE="$RUNTIME_DIR/openshell-gateway.pid"
LOG="$RUNTIME_DIR/openshell-gateway.log"
CONFIG="$RUNTIME_DIR/openshell-gateway.toml"

say() { printf '\033[1m[openshell-gateway]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[openshell-gateway] FATAL:\033[0m %s\n' "$*" >&2; exit 1; }

# Same layout the Homebrew wrapper (libexec/openshell-gateway-homebrew-service) prepares.
ensure_tls() {
  [ -f "$TLS_DIR/server/tls.crt" ] && [ -f "$TLS_DIR/server/tls.key" ] && return 0
  [ -d "$BREW_TLS_SRC" ] || die "no mTLS material at $TLS_DIR and no Homebrew source at $BREW_TLS_SRC"
  mkdir -p "$TLS_DIR/server" "$TLS_DIR/client" "$TLS_DIR/jwt"
  chmod 700 "$TLS_DIR" "$TLS_DIR/server" "$TLS_DIR/client" "$TLS_DIR/jwt"
  install -m 0644 "$BREW_TLS_SRC/ca.crt" "$TLS_DIR/ca.crt"
  install -m 0644 "$BREW_TLS_SRC/server/tls.crt" "$TLS_DIR/server/tls.crt"
  install -m 0600 "$BREW_TLS_SRC/server/tls.key" "$TLS_DIR/server/tls.key"
  install -m 0644 "$BREW_TLS_SRC/client/tls.crt" "$TLS_DIR/client/tls.crt"
  install -m 0600 "$BREW_TLS_SRC/client/tls.key" "$TLS_DIR/client/tls.key"
  install -m 0600 "$BREW_TLS_SRC/jwt/signing.pem" "$TLS_DIR/jwt/signing.pem"
  install -m 0644 "$BREW_TLS_SRC/jwt/public.pem" "$TLS_DIR/jwt/public.pem"
  install -m 0644 "$BREW_TLS_SRC/jwt/kid" "$TLS_DIR/jwt/kid"
}

running() {
  [ -f "$PID_FILE" ] || return 1
  kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

healthy() { openshell status >/dev/null 2>&1; }

cmd_start() {
  command -v openshell-gateway >/dev/null 2>&1 || die "openshell-gateway not on PATH"
  mkdir -p "$RUNTIME_DIR"; chmod 700 "$RUNTIME_DIR"
  if running; then say "already running (pid $(cat "$PID_FILE")) at $ENDPOINT"; exit 0; fi
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    die "something else is listening on $BIND:$PORT (brew services? run: brew services stop openshell)"
  fi
  ensure_tls
  docker info >/dev/null 2>&1 || die "docker daemon not reachable at $DOCKER_HOST (colima start?)"
  # Gateway config (RFC 0003 TOML). Bind mounts are off by default in the docker driver;
  # start.sh needs exactly one: the host models/ directory, read-only, at /models.
  cat >"$CONFIG" <<EOF
[openshell]
version = 1

[openshell.gateway]

[openshell.drivers.docker]
enable_bind_mounts = true
EOF
  say "starting openshell-gateway --drivers docker --bind-address $BIND --port $PORT --config $CONFIG"
  say "DOCKER_HOST=$DOCKER_HOST"
  nohup openshell-gateway --config "$CONFIG" --drivers docker --bind-address "$BIND" --port "$PORT" \
    --tls-cert "$TLS_DIR/server/tls.crt" --tls-key "$TLS_DIR/server/tls.key" \
    --tls-client-ca "$TLS_DIR/ca.crt" \
    >>"$LOG" 2>&1 &
  echo $! >"$PID_FILE"
  for _ in $(seq 1 40); do
    running || { tail -20 "$LOG" >&2; rm -f "$PID_FILE"; die "gateway exited; see $LOG"; }
    healthy && break
    sleep 0.5
  done
  healthy || { tail -20 "$LOG" >&2; die "gateway up but 'openshell status' fails; see $LOG"; }
  say "gateway ready: $ENDPOINT  (pid $(cat "$PID_FILE"), log $LOG)"
  echo "$ENDPOINT"
}

cmd_register() {
  # Registers the mTLS gateway with the CLI (idempotent: the Homebrew installer usually did it).
  if openshell gateway list 2>/dev/null | grep -q "$ENDPOINT"; then
    say "gateway already registered for $ENDPOINT"; return 0
  fi
  openshell gateway add "$ENDPOINT" --local --name openshell
}

cmd_stop() {
  running || { say "not running"; rm -f "$PID_FILE"; return 0; }
  local pid; pid="$(cat "$PID_FILE")"
  kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
  kill -KILL "$pid" 2>/dev/null || true
  rm -f "$PID_FILE"
  say "stopped"
}

cmd_status() {
  if running; then say "pid $(cat "$PID_FILE") endpoint $ENDPOINT"; else say "not running (no live pid in $PID_FILE)"; fi
  openshell status
}

case "${1:-}" in
  start) cmd_start ;;
  register) cmd_register ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  *) sed -n '2,20p' "$0"; exit 2 ;;
esac
