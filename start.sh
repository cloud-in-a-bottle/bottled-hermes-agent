#!/bin/bash
set -euo pipefail

export PATH="/opt/hermes/.venv/bin:$PATH"
export VIRTUAL_ENV="/opt/hermes/.venv"

log() { printf '[start.sh] %s\n' "$*" >&2; }

DATA_DIR="${OPENHOST_APP_DATA_DIR:-/data/app_data/hermes-agent}"
HERMES_HOME="$DATA_DIR/hermes"
export HERMES_HOME

mkdir -p "$HERMES_HOME"

GATEWAY_PID=""
DASHBOARD_PID=""
trap 'kill -TERM ${GATEWAY_PID:-} ${DASHBOARD_PID:-} 2>/dev/null; wait' TERM INT

log "starting hermes gateway"
hermes gateway run &
GATEWAY_PID=$!

log "starting hermes dashboard on :8080"
hermes dashboard --host 0.0.0.0 --port 8080 --no-open --insecure --tui &
DASHBOARD_PID=$!

set +e
wait -n "$GATEWAY_PID" "$DASHBOARD_PID"
EXIT_CODE=$?
set -e

log "child exited (code=$EXIT_CODE); stopping container"
kill -TERM "$GATEWAY_PID" "$DASHBOARD_PID" 2>/dev/null || true
wait || true
exit "$EXIT_CODE"
