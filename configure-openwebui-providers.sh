#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://192.168.1.2:11434}"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3-4b-gpu:latest}"

stamp="$(date +%Y%m%d_%H%M%S)"
backup_dir="${HERMES_BACKUP_DIR:-$HOME/hermes-backups}/${stamp}-openwebui-providers"
mkdir -p "$backup_dir"

docker exec -i hermes-open-webui python - <<'PY'
import sqlite3
src = sqlite3.connect('/app/backend/data/webui.db')
dst = sqlite3.connect('/tmp/webui-provider-backup.db')
src.backup(dst)
dst.close()
src.close()
PY
docker cp hermes-open-webui:/tmp/webui-provider-backup.db "$backup_dir/webui.db.bak"
docker exec hermes-open-webui rm -f /tmp/webui-provider-backup.db

docker cp "$SCRIPT_DIR/configure-openwebui-providers.py" \
  hermes-open-webui:/tmp/configure-openwebui-providers.py
docker exec \
  -e OLLAMA_BASE_URL="$OLLAMA_BASE_URL" \
  -e OLLAMA_MODEL="$OLLAMA_MODEL" \
  hermes-open-webui python /tmp/configure-openwebui-providers.py
docker restart hermes-open-webui >/dev/null

for _ in $(seq 1 60); do
  status="$(docker inspect hermes-open-webui --format '{{.State.Health.Status}}' 2>/dev/null || true)"
  if [[ "$status" == "healthy" ]]; then
    docker exec hermes-open-webui curl -fsS "$OLLAMA_BASE_URL/api/version" >/dev/null
    echo 'webui=healthy'
    echo 'ollama_api=native'
    echo "ollama_model=$OLLAMA_MODEL"
    echo "backup_dir=$backup_dir"
    exit 0
  fi
  sleep 2
done

echo 'ERROR: Open WebUI failed health after provider configuration' >&2
exit 1
