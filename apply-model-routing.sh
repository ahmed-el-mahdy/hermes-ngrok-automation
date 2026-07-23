#!/usr/bin/env bash
set -euo pipefail

: "${GOOGLE_API_KEY:?GOOGLE_API_KEY is required}"
: "${OPENROUTER_API_KEY:?OPENROUTER_API_KEY is required}"
PROJECT_DIR="${HERMES_PROJECT_DIR:-$HOME/hermes-ngrok}"
HERMES_DATA_DIR="${HERMES_DATA_DIR:-$HOME/.hermes}"
BACKUP_ROOT="${HERMES_BACKUP_DIR:-$HOME/hermes-backups}"

stamp="$(date +%Y%m%d_%H%M%S)"
backup_dir="${BACKUP_ROOT}/${stamp}-model-routing"
mkdir -p "$backup_dir"

cp -a "$PROJECT_DIR/.env" "$backup_dir/compose.env.bak"
docker cp hermes-agent:/opt/data/.env "$backup_dir/hermes.env.bak"
docker cp hermes-agent:/opt/data/config.yaml "$backup_dir/config.yaml.bak"

export GOOGLE_API_KEY
export OPENROUTER_API_KEY
PROJECT_ENV="$PROJECT_DIR/.env" python3 - <<'PY'
from pathlib import Path
import os

path = Path(os.environ['PROJECT_ENV'])
updates = {
    'GOOGLE_API_KEY': os.environ['GOOGLE_API_KEY'],
    'GEMINI_API_KEY': os.environ['GOOGLE_API_KEY'],
    'OPENROUTER_API_KEY': os.environ['OPENROUTER_API_KEY'],
}
remove = {'NARA_ROUTER_API_KEY'}
lines = path.read_text().splitlines()
seen = set()
out = []
for line in lines:
    key = line.split('=', 1)[0].strip() if '=' in line and not line.lstrip().startswith('#') else ''
    if key in remove:
        continue
    if key in updates:
        out.append(f'{key}={updates[key]}')
        seen.add(key)
    else:
        out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f'{key}={value}')
path.write_text('\n'.join(out) + '\n')
PY

docker exec -u root \
  -e GOOGLE_API_KEY \
  -e OPENROUTER_API_KEY \
  hermes-agent /bin/bash -lc '
    set -euo pipefail
    . /opt/hermes/.venv/bin/activate
    python - <<"PY"
from pathlib import Path
import os
import yaml

env_path = Path("/opt/data/.env")
updates = {
    "GOOGLE_API_KEY": os.environ["GOOGLE_API_KEY"],
    "GEMINI_API_KEY": os.environ["GOOGLE_API_KEY"],
    "OPENROUTER_API_KEY": os.environ["OPENROUTER_API_KEY"],
}
remove = {"NARA_ROUTER_API_KEY"}
lines = env_path.read_text().splitlines()
seen = set()
out = []
for line in lines:
    key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
    if key in remove:
        continue
    if key in updates:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")
env_path.write_text("\n".join(out) + "\n")

config_path = Path("/opt/data/config.yaml")
config = yaml.safe_load(config_path.read_text()) or {}
config["model"] = {
    "default": "nvidia/nemotron-3-super-120b-a12b:free",
    "provider": "openrouter",
    "base_url": "https://openrouter.ai/api/v1",
}
config.setdefault("providers", {}).pop("nararouter", None)
config["fallback_providers"] = [
    {
        "provider": "openrouter",
        "model": "openai/gpt-oss-20b:free",
        "base_url": "https://openrouter.ai/api/v1",
    },
    {
        "provider": "openrouter",
        "model": "openrouter/free",
        "base_url": "https://openrouter.ai/api/v1",
    },
    {
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
    },
]
config.setdefault("agent", {})["api_max_retries"] = 1
config["agent"]["tool_use_enforcement"] = ["gemini", "openrouter"]
for task, settings in (config.get("auxiliary") or {}).items():
    if isinstance(settings, dict):
        settings["provider"] = "gemini"
        settings["model"] = "gemini-3.1-flash-lite"
        settings["base_url"] = ""
        settings["api_key"] = ""
config_path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
PY
    chown 10000:10000 /opt/data/.env /opt/data/config.yaml
    chmod 600 /opt/data/.env
  '

docker exec hermes-agent sh -lc '. /opt/hermes/.venv/bin/activate && hermes doctor' \
  > "$backup_dir/doctor-before-restart.txt" 2>&1 || true

docker restart hermes-agent >/dev/null

healthy=0
for _ in $(seq 1 30); do
  status="$(curl -sS -o /dev/null --max-time 4 -w '%{http_code}' http://127.0.0.1:8642/health 2>/dev/null || true)"
  if [[ "$status" == "200" ]]; then
    healthy=1
    break
  fi
  sleep 2
done

if [[ "$healthy" -ne 1 ]]; then
  docker cp "$backup_dir/hermes.env.bak" hermes-agent:/opt/data/.env
  docker cp "$backup_dir/config.yaml.bak" hermes-agent:/opt/data/config.yaml
  cp -a "$backup_dir/compose.env.bak" "$PROJECT_DIR/.env"
  docker exec -u root hermes-agent chown 10000:10000 /opt/data/.env /opt/data/config.yaml
  docker restart hermes-agent >/dev/null
  echo 'ERROR: gateway failed health check; previous configuration restored' >&2
  exit 1
fi

echo "backup_dir=$backup_dir"
echo 'gateway=healthy'
echo 'primary=openrouter/nvidia/nemotron-3-super-120b-a12b:free'
echo 'fallbacks=openai/gpt-oss-20b:free,openrouter/free,gemini-2.5-flash'
echo 'local_qwen=Open WebUI native Ollama API'
