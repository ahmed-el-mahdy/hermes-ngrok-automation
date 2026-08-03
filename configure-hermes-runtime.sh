#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${HERMES_PROJECT_DIR:-$HOME/hermes-ngrok}"
BACKUP_ROOT="${HERMES_BACKUP_DIR:-$HOME/hermes-backups}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$PROJECT_DIR"

# Keep standalone send_message calls aligned with the private Telegram allowlist.
# The gateway reads TELEGRAM_HOME_CHANNEL from the container environment, not
# from the top-level Hermes YAML key.
python3 - "$PROJECT_DIR/.env" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
values = {}
for line in lines:
    stripped = line.strip()
    if stripped and not stripped.startswith("#") and "=" in stripped:
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()

home = values.get("TELEGRAM_HOME_CHANNEL", "")
allowed = values.get("TELEGRAM_ALLOWED_USERS", "")
if not home and allowed:
    home = allowed.split(",", 1)[0].strip()
    if home:
        replaced = False
        for index, line in enumerate(lines):
            if line.startswith("TELEGRAM_HOME_CHANNEL="):
                lines[index] = f"TELEGRAM_HOME_CHANNEL={home}"
                replaced = True
                break
        if not replaced:
            lines.append(f"TELEGRAM_HOME_CHANNEL={home}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        path.chmod(0o600)
        print("telegram_home_channel=derived-from-allowlist")
PY

stamp="$(date +%Y%m%d_%H%M%S)"
backup_dir="${BACKUP_ROOT}/${stamp}-runtime"
mkdir -p "$backup_dir"
docker cp hermes-agent:/opt/data/config.yaml "$backup_dir/config.yaml.bak"

docker cp "$SCRIPT_DIR/configure-hermes-runtime.py" \
  hermes-agent:/tmp/configure-hermes-runtime.py
docker cp "$SCRIPT_DIR/scripts/monitor_gold.py" \
  hermes-agent:/tmp/monitor_gold.py

docker exec -u root hermes-agent sh -lc '
  set -eu
  install -d -o 10000 -g 10000 -m 0750 \
    /opt/data/.local/bin \
    /opt/data/backups/runtime \
    /opt/data/bin \
    /opt/data/cache/pytest \
    /opt/data/cache/uv \
    /opt/data/cache/huggingface \
    /opt/data/scripts \
    /opt/data/state \
    /opt/data/python-packages \
    /opt/data/tmp
  chown -R 10000:10000 \
    /opt/data/cache/pytest \
    /opt/data/cache/uv \
    /opt/data/cache/huggingface \
    /opt/data/python-packages \
    /opt/data/tmp

  ln -sf /opt/hermes/.venv/bin/hermes /opt/data/.local/bin/hermes
  ln -sf /usr/local/bin/hermes-admin /opt/data/.local/bin/hermes-admin
  ln -sf /usr/local/bin/hermes-personal-memory \
    /opt/data/.local/bin/hermes-personal-memory
  ln -sf /usr/local/bin/hermes-smoke-test /opt/data/.local/bin/hermes-smoke-test
  chown -h 10000:10000 \
    /opt/data/.local/bin/hermes \
    /opt/data/.local/bin/hermes-admin \
    /opt/data/.local/bin/hermes-personal-memory \
    /opt/data/.local/bin/hermes-smoke-test

  cat > /opt/data/home/.hermes_env <<"EOF"
export PATH="/opt/data/.local/bin:/opt/data/bin:/usr/local/bin:/opt/hermes/bin:/opt/hermes/.venv/bin:$PATH"
export PIP_TARGET="/opt/data/python-packages"
export PYTHONPATH="/opt/data/python-packages${PYTHONPATH:+:$PYTHONPATH}"
export UV_CACHE_DIR="/opt/data/cache/uv"
export XDG_CACHE_HOME="/opt/data/cache"
export HF_HOME="/opt/data/cache/huggingface"
export TMPDIR="/opt/data/tmp"
export PYTEST_ADDOPTS="-o cache_dir=/opt/data/cache/pytest"
EOF

  cat > /opt/data/bin/pip <<"EOF"
#!/bin/sh
if [ "${1:-}" = "install" ]; then
  shift
  exec /opt/hermes/.venv/bin/python -m pip install \
    --target "${PIP_TARGET:-/opt/data/python-packages}" "$@"
fi
exec /opt/hermes/.venv/bin/python -m pip "$@"
EOF
  ln -sf pip /opt/data/bin/pip3
  chmod 0755 /opt/data/bin/pip
  chown -h 10000:10000 /opt/data/bin/pip /opt/data/bin/pip3
  chown 10000:10000 /opt/data/home/.hermes_env
  chmod 0640 /opt/data/home/.hermes_env

  /opt/hermes/.venv/bin/python /tmp/configure-hermes-runtime.py
  if [ -f /opt/data/home/.hermes/state/gold-price.json ] \
    && [ ! -f /opt/data/state/gold-price.json ]; then
    cp /opt/data/home/.hermes/state/gold-price.json \
      /opt/data/state/gold-price.json
    chown 10000:10000 /opt/data/state/gold-price.json
    chmod 0640 /opt/data/state/gold-price.json
  fi
  install -o 10000 -g 10000 -m 0750 /tmp/monitor_gold.py \
    /opt/data/scripts/monitor_gold.py
  install -d -o 10000 -g 10000 -m 0750 /opt/data/home/.hermes/scripts
  ln -sf /opt/data/scripts/monitor_gold.py \
    /opt/data/home/.hermes/scripts/monitor_gold.py
  chown -h 10000:10000 /opt/data/home/.hermes/scripts/monitor_gold.py
  chown -R 10000:10000 /opt/data/state
  rm -f /tmp/configure-hermes-runtime.py /tmp/monitor_gold.py
  chown 10000:10000 /opt/data/config.yaml
  chmod 0640 /opt/data/config.yaml
'

if ! docker exec -u 10000 hermes-agent /opt/hermes/.venv/bin/python \
  /opt/data/scripts/monitor_gold.py --always-report; then
  echo "WARNING: runtime configured, but the external gold feeds were unavailable" >&2
fi

skip_restart="${HERMES_RUNTIME_SKIP_RESTART:-0}"
if [[ "$skip_restart" =~ ^(1|true|yes)$ ]]; then
  echo "runtime_restart=skipped"
else
  for _ in $(seq 1 120); do
    active_agents="$(docker exec hermes-agent jq -r \
      '.active_agents // 0' /opt/data/gateway_state.json 2>/dev/null || echo 0)"
    [[ "$active_agents" == "0" ]] && break
    sleep 5
  done
  if [[ "${active_agents:-0}" != "0" ]]; then
    echo 'ERROR: Hermes is busy; configuration was saved but restart was deferred' >&2
    exit 2
  fi
  docker compose --env-file .env -f docker-compose.yml restart \
    ollama-bridge hermes-agent >/dev/null
fi

healthy=0
bridge_healthy=0
for _ in $(seq 1 45); do
  status="$(curl -sS -o /dev/null --max-time 4 -w '%{http_code}' \
    http://127.0.0.1:8642/health 2>/dev/null || true)"
  bridge_status="$(docker exec hermes-ollama-bridge sh -lc \
    "curl -sS -o /dev/null --max-time 4 -w '%{http_code}' http://127.0.0.1:8000/health" \
    2>/dev/null || true)"
  if [[ "$bridge_status" == "200" ]]; then
    bridge_healthy=1
  fi
  if [[ "$status" == "200" ]]; then
    healthy=1
    break
  fi
  sleep 2
done

if [[ "$healthy" -ne 1 ]]; then
  docker cp "$backup_dir/config.yaml.bak" hermes-agent:/opt/data/config.yaml
  docker exec -u root hermes-agent sh -lc \
    'chown 10000:10000 /opt/data/config.yaml && chmod 0640 /opt/data/config.yaml'
  docker restart hermes-agent >/dev/null
  echo "ERROR: Hermes did not become healthy; previous config restored" >&2
  exit 1
fi

if [[ "$bridge_healthy" -ne 1 ]]; then
  echo "WARNING: Hermes is healthy, but the local GPU bridge is not ready yet" >&2
fi

if ! docker exec -u 10000 hermes-agent timeout 15s \
  validate-telegram --write-status; then
  echo "WARNING: Telegram live validation was unavailable" >&2
fi

echo "runtime=ready"
echo "backup_dir=$backup_dir"
docker exec hermes-agent hermes-admin status
