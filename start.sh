#!/bin/bash
set -euo pipefail

log() { printf '[start.sh] %s\n' "$*" >&2; }

DATA_DIR="${OPENHOST_APP_DATA_DIR:-/data/app_data/hermes-agent}"
HERMES_HOME="$DATA_DIR/hermes"
export HERMES_HOME

mkdir -p "$HERMES_HOME"

ZONE_DOMAIN="${OPENHOST_ZONE_DOMAIN:-localhost}"
APP_NAME="${OPENHOST_APP_NAME:-hermes-agent}"
PUBLIC_HOST="$APP_NAME.$ZONE_DOMAIN"

DASHBOARD_PORT=9119
PROXY_PORT=8080

GATEWAY_PID=""
DASHBOARD_PID=""
PROXY_PID=""
trap 'kill -TERM ${GATEWAY_PID:-} ${DASHBOARD_PID:-} ${PROXY_PID:-} 2>/dev/null; wait' TERM INT

log "starting hermes gateway"
hermes gateway run &
GATEWAY_PID=$!

log "starting hermes dashboard on :$DASHBOARD_PORT"
hermes dashboard --host 0.0.0.0 --port "$DASHBOARD_PORT" --no-open --insecure --tui &
DASHBOARD_PID=$!

log "starting auth proxy on :$PROXY_PORT -> :$DASHBOARD_PORT"
export AUTH_PROXY_LISTEN_PORT="$PROXY_PORT"
export AUTH_PROXY_UPSTREAM_HOST="127.0.0.1"
export AUTH_PROXY_UPSTREAM_PORT="$DASHBOARD_PORT"
python3 /opt/openhost-hermes/auth_proxy.py &
PROXY_PID=$!

set +e
wait -n "$GATEWAY_PID" "$DASHBOARD_PID" "$PROXY_PID"
EXIT_CODE=$?
set -e

log "child exited (code=$EXIT_CODE); stopping container"
kill -TERM "$GATEWAY_PID" "$DASHBOARD_PID" "$PROXY_PID" 2>/dev/null || true
wait || true
exit "$EXIT_CODE"
