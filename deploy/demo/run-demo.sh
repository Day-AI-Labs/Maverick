#!/usr/bin/env bash
# One-command Maverick browser demo (Model 1: local).
#
# Generates a dashboard token if none is set, boots the dashboard container,
# waits for it to answer, prints the tokenized URL, and opens your browser.
# The only "terminal" step the demo audience sees is running this once.
set -euo pipefail

cd "$(dirname "$0")"

COMPOSE_FILE="docker-compose.yml"
ENV_FILE="demo.env"
PORT="${MAVERICK_DEMO_PORT:-8765}"
TOKEN_FILE=".demo-token"

if [ ! -f "$ENV_FILE" ]; then
  echo "No $ENV_FILE found. Create it and add your key:" >&2
  echo "  cp demo.env.example demo.env && \${EDITOR:-nano} demo.env" >&2
  exit 1
fi

# Read MAVERICK_DEMO_PORT from the env file too, so the URL matches the publish.
PORT="$(grep -E '^MAVERICK_DEMO_PORT=' "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2 || true)"
PORT="${PORT:-8765}"

# A stable token per machine, so the demo URL keeps working across restarts.
# Stored beside this script and never committed (see .gitignore).
if [ -n "${MAVERICK_DASHBOARD_TOKEN:-}" ]; then
  TOKEN="$MAVERICK_DASHBOARD_TOKEN"
elif [ -f "$TOKEN_FILE" ]; then
  TOKEN="$(cat "$TOKEN_FILE")"
else
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))' 2>/dev/null \
           || openssl rand -hex 24)"
  printf '%s' "$TOKEN" > "$TOKEN_FILE"
fi
export MAVERICK_DASHBOARD_TOKEN="$TOKEN"

echo "Building and starting the Maverick demo dashboard..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --build

URL="http://localhost:${PORT}/?token=${TOKEN}"
printf 'Waiting for the dashboard to come up'
for _ in $(seq 1 60); do
  if curl -fsS "http://localhost:${PORT}/livez" >/dev/null 2>&1; then
    break
  fi
  printf '.'
  sleep 1
done
echo

echo
echo "Maverick demo is live:"
echo "  $URL"
echo
echo "Stop it with:   docker compose -f deploy/demo/$COMPOSE_FILE down"
echo "Reset state:    docker compose -f deploy/demo/$COMPOSE_FILE down -v"

# Best-effort browser open (macOS 'open' / Linux 'xdg-open'); harmless if neither.
{ command -v open >/dev/null 2>&1 && open "$URL"; } \
  || { command -v xdg-open >/dev/null 2>&1 && xdg-open "$URL"; } \
  || true
