#!/bin/bash
set -e

export DB_PATH="${DB_PATH:-/data/mg4_mate.db}"

echo "[MG4 Mate] Starting..."
echo "[MG4 Mate] DB: ${DB_PATH}"

# Start poller in background
PYTHONPATH=/app/poller python3 /app/poller/main.py &
POLLER_PID=$!
echo "[MG4 Mate] Poller PID: ${POLLER_PID}"

# Start web server in background
PYTHONPATH=/app/web python3 /app/web/main.py &
WEB_PID=$!
echo "[MG4 Mate] Web PID: ${WEB_PID}"

# If either service exits, stop the container (HA or Docker will restart it)
wait -n "$POLLER_PID" "$WEB_PID"
EXIT_CODE=$?
echo "[MG4 Mate] A service exited (code ${EXIT_CODE}) — stopping"
kill "$POLLER_PID" "$WEB_PID" 2>/dev/null
exit "$EXIT_CODE"
