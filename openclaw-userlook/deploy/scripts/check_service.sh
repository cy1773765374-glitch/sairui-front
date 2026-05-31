#!/usr/bin/env bash
set -euo pipefail

BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:10009}"
PUBLIC_URL="${PUBLIC_URL:-}"
GATEWAY_HOST="${GATEWAY_HOST:-127.0.0.1}"
GATEWAY_PORT="${GATEWAY_PORT:-18789}"

echo "Checking backend health: ${BACKEND_URL}/api/health"
curl -fsS "${BACKEND_URL}/api/health"
echo

echo "Checking database health: ${BACKEND_URL}/api/health/db"
curl -fsS "${BACKEND_URL}/api/health/db"
echo

echo "Checking OpenClaw Gateway TCP port: ${GATEWAY_HOST}:${GATEWAY_PORT}"
if command -v nc >/dev/null 2>&1; then
  nc -z "${GATEWAY_HOST}" "${GATEWAY_PORT}"
else
  timeout 3 bash -c "cat < /dev/null > /dev/tcp/${GATEWAY_HOST}/${GATEWAY_PORT}"
fi
echo "OpenClaw Gateway port is reachable from this host."

if [ -n "${PUBLIC_URL}" ]; then
  echo "Checking public HTTPS entry: ${PUBLIC_URL}"
  curl -fsSI "${PUBLIC_URL}" >/dev/null
  echo "Public HTTPS entry responded."

  echo "Checking public API proxy: ${PUBLIC_URL%/}/api/health"
  curl -fsS "${PUBLIC_URL%/}/api/health"
  echo
else
  echo "Set PUBLIC_URL=https://your-domain.example to check Nginx HTTPS and API proxy."
fi

echo "WebSocket proxy check requires a valid JWT and conversation id:"
echo "  wscat -c 'wss://your-domain.example/api/ws/conversations/<conversation_id>?token=<JWT>'"
