#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${HERMES_PROJECT_DIR:-$HOME/hermes-ngrok}"
cd "$PROJECT_DIR"

stamp="$(date +%Y%m%d_%H%M%S)"
work_dir="$(mktemp -d)"
backup="$work_dir/config.yaml"
started_at="$(date --iso-8601=seconds)"
restored=0

wait_gateway() {
  for _ in $(seq 1 45); do
    status="$(curl -sS -o /dev/null --max-time 4 -w '%{http_code}' \
      http://127.0.0.1:8642/health 2>/dev/null || true)"
    [[ "$status" == "200" ]] && return 0
    sleep 2
  done
  return 1
}

restore() {
  if [[ "$restored" -eq 0 && -s "$backup" ]]; then
    docker cp "$backup" hermes-agent:/opt/data/config.yaml >/dev/null
    docker exec -u root hermes-agent sh -lc \
      'chown 10000:10000 /opt/data/config.yaml && chmod 0640 /opt/data/config.yaml'
    docker restart hermes-agent >/dev/null
    wait_gateway || true
    restored=1
  fi
  rm -rf "$work_dir"
}
trap restore EXIT

docker cp hermes-agent:/opt/data/config.yaml "$backup"
docker exec -i -u 10000 hermes-agent python - <<'PY'
from pathlib import Path
import yaml

source = Path("/opt/data/config.yaml")
path = Path("/opt/data/tmp/failover-config.yaml")
config = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
providers = config.setdefault("custom_providers", [])
providers = [
    item
    for item in providers
    if not isinstance(item, dict) or item.get("name") != "forced-429"
]
providers.append(
    {
        "name": "forced-429",
        "base_url": "http://ollama-bridge:8000/test/429/v1",
        "model": "forced-rate-limit",
        "api_key": "no-key-required",
        "api_mode": "chat_completions",
    }
)
config["custom_providers"] = providers
config["model"] = {
    "provider": "forced-429",
    "default": "forced-rate-limit",
    "base_url": "http://ollama-bridge:8000/test/429/v1",
}
config["fallback_providers"] = [
    {
        "provider": "ollama-local",
        "model": "qwen3-4b-gpu:latest",
        "base_url": "http://ollama-bridge:8000/v1",
    }
]
path.write_text(
    yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
    encoding="utf-8",
)
PY
docker cp hermes-agent:/opt/data/tmp/failover-config.yaml "$work_dir/failover-config.yaml"
docker cp "$work_dir/failover-config.yaml" hermes-agent:/opt/data/config.yaml
docker exec -u root hermes-agent sh -lc \
  'rm -f /opt/data/tmp/failover-config.yaml; chown 10000:10000 /opt/data/config.yaml; chmod 0640 /opt/data/config.yaml'
docker restart hermes-agent >/dev/null

wait_gateway || {
  echo "automatic_failover=failed gateway_not_healthy"
  exit 1
}

API_SERVER_KEY="$(
  sed -n 's/^API_SERVER_KEY=//p' .env | tail -n 1
)"
[[ -n "$API_SERVER_KEY" ]] || {
  echo "automatic_failover=failed missing_api_server_key"
  exit 1
}
response="$(
  curl -fsS --max-time 180 \
    -H "Authorization: Bearer $API_SERVER_KEY" \
    -H "Content-Type: application/json" \
    http://127.0.0.1:8642/v1/chat/completions \
    -d '{
      "model": "hermes-agent",
      "messages": [{
        "role": "user",
        "content": "Reply with exactly FAILOVER_LOCAL_OK and no other text."
      }],
      "stream": false
    }'
)"
content="$(printf '%s' "$response" | jq -r '.choices[0].message.content // ""')"
switched="$(
  docker logs --since "$started_at" hermes-agent 2>&1 \
    | grep -E 'switching to fallback.*qwen3-4b-gpu|Switched to fallback model.*qwen3-4b-gpu' \
    | tail -n 1 || true
)"

[[ "$content" == *"FAILOVER_LOCAL_OK"* ]] || {
  echo "automatic_failover=failed missing_response_marker"
  exit 1
}
[[ -n "$switched" ]] || {
  echo "automatic_failover=failed missing_switch_evidence"
  exit 1
}

restore
trap - EXIT

echo "automatic_failover=passed"
echo "forced_status=429"
echo "recovered_with=ollama-local/qwen3-4b-gpu:latest"
echo "configuration_restored=true"
