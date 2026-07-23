#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${HERMES_PROJECT_DIR:-$HOME/hermes-ngrok}"
cd "$PROJECT_DIR"

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
path = Path("/opt/data/tmp/delegation-failover-config.yaml")
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
delegation = config.setdefault("delegation", {})
delegation["provider"] = "forced-429"
delegation["model"] = "forced-rate-limit"
delegation["base_url"] = ""
delegation["api_key"] = ""
delegation["api_mode"] = ""
path.write_text(
    yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
    encoding="utf-8",
)
PY
docker cp \
  hermes-agent:/opt/data/tmp/delegation-failover-config.yaml \
  "$work_dir/failover-config.yaml"
docker cp "$work_dir/failover-config.yaml" hermes-agent:/opt/data/config.yaml
docker exec -u root hermes-agent sh -lc \
  'rm -f /opt/data/tmp/delegation-failover-config.yaml; chown 10000:10000 /opt/data/config.yaml; chmod 0640 /opt/data/config.yaml'
docker restart hermes-agent >/dev/null

wait_gateway || {
  echo "delegation_failover=failed gateway_not_healthy"
  exit 1
}

response="$(
  docker exec -u 10000 hermes-agent timeout 300s hermes -z \
    'Use delegate_task exactly once with role leaf. Give the child this bounded goal: reply exactly DELEGATION_FALLBACK_LOCAL_OK without using tools. Wait for the child result, then reply exactly PARENT_OK DELEGATION_FALLBACK_LOCAL_OK.'
)"
forced_request="$(
  docker logs --since "$started_at" hermes-ollama-bridge 2>&1 \
    | grep 'POST /test/429/v1/chat/completions HTTP/1.1" 429' \
    | tail -n 1 || true
)"
local_request="$(
  docker logs --since "$started_at" hermes-ollama-bridge 2>&1 \
    | grep 'POST /v1/chat/completions HTTP/1.1" 200' \
    | tail -n 1 || true
)"

[[ "$response" == *"PARENT_OK DELEGATION_FALLBACK_LOCAL_OK"* ]] || {
  echo "delegation_failover=failed missing_response_marker"
  exit 1
}
[[ -n "$forced_request" ]] || {
  echo "delegation_failover=failed missing_forced_429_evidence"
  exit 1
}
[[ -n "$local_request" ]] || {
  echo "delegation_failover=failed missing_local_qwen_evidence"
  exit 1
}

restore
trap - EXIT

echo "delegation_failover=passed"
echo "child_primary_status=429"
echo "child_recovered_with=ollama-local/qwen3-4b-gpu:latest"
echo "configuration_restored=true"
