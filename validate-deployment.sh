#!/usr/bin/env bash
set -euo pipefail

: "${PORTAL_EMAIL:?PORTAL_EMAIL is required}"
: "${PORTAL_PASSWORD:?PORTAL_PASSWORD is required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${HERMES_PROJECT_DIR:-$HOME/hermes-ngrok}"
docker compose config --quiet
docker compose up -d --build --force-recreate

for _ in $(seq 1 90); do
  webui_health="$(docker inspect hermes-open-webui --format '{{.State.Health.Status}}' 2>/dev/null || true)"
  agent_state="$(docker inspect hermes-agent --format '{{.State.Status}}' 2>/dev/null || true)"
  ngrok_state="$(docker inspect hermes-ngrok --format '{{.State.Status}}' 2>/dev/null || true)"
  if [[ "$webui_health" == "healthy" && "$agent_state" == "running" && "$ngrok_state" == "running" ]]; then
    break
  fi
  sleep 2
done

[[ "$webui_health" == "healthy" ]] || { docker compose ps; exit 1; }
[[ "$agent_state" == "running" && "$ngrok_state" == "running" ]] || { docker compose ps; exit 1; }

docker exec hermes-agent /opt/hermes/.venv/bin/python -c \
  'import faster_whisper, edge_tts' >/dev/null
docker exec hermes-agent grep -q 'HERMES_STT_INITIAL_PROMPT' \
  /opt/hermes/tools/transcription_tools.py

public_url=""
for _ in $(seq 1 45); do
  public_url="$(curl -fsS http://127.0.0.1:4040/api/tunnels 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(next((x['public_url'] for x in d.get('tunnels',[]) if x.get('proto')=='https'), ''))" 2>/dev/null || true)"
  [[ -n "$public_url" ]] && break
  sleep 2
done
[[ -n "$public_url" ]] || exit 1

PORTAL_EMAIL="$PORTAL_EMAIL" PORTAL_PASSWORD="$PORTAL_PASSWORD" PUBLIC_URL="$public_url" \
  EXPECTED_OPEN_WEBUI_VERSION="${EXPECTED_OPEN_WEBUI_VERSION:-}" \
  python3 "$SCRIPT_DIR/validate-deployment.py"

docker compose ps
df -h /
echo "public_url=$public_url"
