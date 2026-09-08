#!/usr/bin/env bash
# Expose the PLVA agent demo through Tailscale.
#
#   scripts/expose.sh funnel   # PUBLIC internet link (anyone with the link + access code)
#   scripts/expose.sh serve    # tailnet only (people on your Tailscale network)
#   scripts/expose.sh off      # stop exposing
#
# The demo UI must be started in public mode so the access-code gate is on:
#   PLVA_UI_PUBLIC=1 uv run python -m plva_agent_demo.ui --port 3000
# The code is printed at startup and stored in .plva-pr/ui-access-code.
set -euo pipefail
PORT="${PLVA_UI_PORT:-3000}"
TS="$(command -v tailscale || echo /Applications/Tailscale.app/Contents/MacOS/Tailscale)"
case "${1:-}" in
  funnel)
    "$TS" funnel --bg "$PORT"
    echo "PUBLIC. Share the https URL above plus the access code in .plva-pr/ui-access-code."
    ;;
  serve)
    "$TS" serve --bg "$PORT"
    echo "Tailnet only. Share the URL above with people on your tailnet."
    ;;
  off)
    "$TS" funnel --bg off "$PORT" 2>/dev/null || true
    "$TS" serve --bg off "$PORT" 2>/dev/null || true
    echo "exposure removed"
    ;;
  *) echo "usage: $0 funnel|serve|off" >&2; exit 2 ;;
esac
